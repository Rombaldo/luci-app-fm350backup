"""install.sh и uninstall.sh в папке-песочнице: поддельные apk и opkg, настоящая раздача файлов по HTTP."""
import hashlib
import http.server
import io
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VERSION = "9.9.9"
TAR = "fm350backup-%s.tar.gz" % VERSION


def read(path, mode="r"):
    with open(path, mode) as f:
        return f.read()


def make_tar():
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tar:
        def add(name, data, mode=0o644):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))
        add("VERSION", (VERSION + "\n").encode())
        add("uninstall.sh", read(os.path.join(ROOT, "uninstall.sh"), "rb"), 0o755)
        add("pylib/usb/__init__.py", b"")
        add("mtkclient/mtk.py", b"")
        add("files/usr/libexec/fm350-backup", b"#!/bin/sh\n", 0o755)
        add("files/usr/libexec/rpcd/luci.fm350backup", b"#!/bin/sh\n", 0o755)
        add("files/etc/config/fm350backup", b"config main\n")
        add("files/www/luci-static/resources/view/fm350backup/backup_9_9_9.js", b"new")
    return raw.getvalue()


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.root = os.path.join(self.tmp, "root")
        self.web = os.path.join(self.tmp, "web")
        self.bin = os.path.join(self.tmp, "bin")
        self.calls = os.path.join(self.tmp, "calls")
        for d in (self.root + "/etc", self.root + "/tmp", self.web, self.bin):
            os.makedirs(d)
        self.release("25.12.6")
        self.publish(make_tar())
        # sha256sum есть на роутере, но не на каждом Mac
        if not shutil.which("sha256sum"):
            self.stub("sha256sum", 'shasum -a 256 "$@"\n')
        handler = lambda *a, **k: Quiet(*a, directory=self.web, **k)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def release(self, version):
        with open(self.root + "/etc/openwrt_release", "w") as f:
            f.write("DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='%s'\n" % version)

    def publish(self, data, wrong_sum=False):
        with open(os.path.join(self.web, TAR), "wb") as f:
            f.write(data)
        digest = hashlib.sha256(b"other" if wrong_sum else data).hexdigest()
        with open(os.path.join(self.web, "SHA256SUMS"), "w") as f:
            f.write("%s  %s\n" % (digest, TAR))

    def stub(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

    def manager(self, name, fail_on=""):
        self.stub(name, 'echo "%s $*" >> "%s"\ncase "$*" in "info -e "*) exit 1;; *%s*) [ -n "%s" ] && exit 1;; esac\nexit 0\n'
                  % (name, self.calls, fail_on or "@", fail_on))

    def run_install(self, path=None, **env):
        script = read(os.path.join(ROOT, "install.sh")).replace("@VERSION@", VERSION).replace("@REPO@", "owner/repo")
        full = dict(os.environ, FM350_ROOT=self.root, TMPDIR=self.tmp,
                    FM350_BASE_URL="http://127.0.0.1:%d" % self.server.server_address[1],
                    PATH=path or self.bin + ":/usr/bin:/bin", **env)
        return subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=full, timeout=60)

    def log(self):
        return read(self.calls) if os.path.exists(self.calls) else ""

    def installed(self, rel):
        return os.path.exists(os.path.join(self.root, rel))

    def test_apk_router(self):
        self.manager("apk")
        out = self.run_install()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("apk update", self.log())
        self.assertIn("apk add python3-light python3-logging python3-ctypes libusb-1.0-0", self.log())
        self.assertNotIn("opkg", self.log())
        self.assertTrue(self.installed("usr/share/fm350backup/mtkclient/mtk.py"))
        self.assertTrue(self.installed("usr/share/fm350backup/pylib/usb/__init__.py"))
        self.assertTrue(os.access(self.root + "/usr/libexec/fm350-backup", os.X_OK))
        self.assertEqual(read(self.root + "/usr/share/fm350backup/VERSION").strip(), VERSION)
        self.assertIn("файл DA", out.stdout)

    def test_opkg_router(self):
        self.manager("opkg")
        self.release("23.05.5")
        out = self.run_install()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("opkg update", self.log())
        self.assertIn("opkg install python3-light", self.log())

    def test_no_package_manager(self):
        for tool in ("sh", "sed", "awk", "grep", "df"):
            found = shutil.which(tool)
            os.symlink(found, os.path.join(self.bin, tool))
        out = self.run_install(path=self.bin + ":/nonexistent")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("нет ни apk, ни opkg", out.stderr)

    def test_space_requirement(self):
        self.manager("apk")
        # среда без Python: только нужные инструменты и поддельный df
        for tool in ("sh", "sed", "awk", "grep", "tar", "gzip", "mktemp", "curl", "cut", "mkdir", "rm", "cp", "mv",
                     "chmod", "touch", "cat", "ls", "tr", "sleep", "uname", "date"):
            found = shutil.which(tool)
            if found and not os.path.exists(os.path.join(self.bin, tool)):
                os.symlink(found, os.path.join(self.bin, tool))
        sha = shutil.which("sha256sum")
        if sha:
            os.symlink(sha, os.path.join(self.bin, "sha256sum"))
        else:
            self.stub("sha256sum", '/usr/bin/shasum -a 256 "$@"\n')

        def free(kb):
            self.stub("df", 'echo "Filesystem 1K Used Available"\necho "overlay 100 0 %d"\n' % kb)

        path = self.bin
        free(19000)
        out = self.run_install(path=path)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("мало места", out.stderr)
        free(21000)
        self.assertEqual(self.run_install(path=path).returncode, 0)
        # Python уже есть: хватает места на саму программу
        self.stub("python3", "exit 0\n")
        free(3500)
        self.assertEqual(self.run_install(path=path).returncode, 0)
        free(2000)
        self.assertIn("мало места", self.run_install(path=path).stderr)

    def test_wrong_checksum_changes_nothing(self):
        self.manager("apk")
        self.publish(make_tar(), wrong_sum=True)
        out = self.run_install()
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("контрольная сумма не совпала", out.stderr)
        self.assertEqual(self.log(), "")
        self.assertFalse(self.installed("usr/share/fm350backup"))

    def test_download_error_changes_nothing(self):
        self.manager("apk")
        os.remove(os.path.join(self.web, TAR))
        out = self.run_install()
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("не удалось скачать", out.stderr)
        self.assertEqual(self.log(), "")

    def test_old_openwrt_is_refused_unless_forced(self):
        self.manager("opkg")
        self.release("22.03.7")
        out = self.run_install()
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("слишком старый", out.stderr)
        self.assertEqual(self.log(), "")
        self.assertEqual(self.run_install(FM350_FORCE="1").returncode, 0)

    def test_newer_and_snapshot_only_warn(self):
        self.manager("apk")
        for release in ("26.06.0", "SNAPSHOT"):
            self.release(release)
            out = self.run_install()
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("ВНИМАНИЕ", out.stdout)

    def test_missing_optional_package_only_warns(self):
        self.manager("apk", fail_on="kmod-fs-exfat")
        out = self.run_install()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("нет пакета kmod-fs-exfat", out.stdout)

    def test_missing_required_package_stops(self):
        self.manager("apk", fail_on="python3-light")
        out = self.run_install()
        self.assertNotEqual(out.returncode, 0)
        self.assertFalse(self.installed("usr/share/fm350backup"))

    def test_user_da_moves_and_survives_update(self):
        self.manager("apk")
        old = self.root + "/usr/share/fm350backup/kit"
        os.makedirs(old)
        with open(old + "/DA_mine.bin", "wb") as f:
            f.write(b"da")
        out = self.run_install()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(os.path.exists(old))
        self.assertEqual(read(self.root + "/etc/fm350backup/kit/DA_mine.bin", "rb"), b"da")
        self.assertNotIn("файл DA", out.stdout)
        self.assertEqual(self.run_install().returncode, 0)
        self.assertTrue(self.installed("etc/fm350backup/kit/DA_mine.bin"))

    def test_second_run_does_not_repeat_sysupgrade_lines(self):
        self.manager("apk")
        self.run_install()
        self.run_install()
        conf = read(self.root + "/etc/sysupgrade.conf").split()
        self.assertEqual(len(conf), len(set(conf)))
        self.assertIn("/etc/fm350backup", conf)

    def test_running_dump_blocks_update(self):
        self.manager("apk")
        os.makedirs(self.root + "/tmp/fm350backup")
        with open(self.root + "/tmp/fm350backup/dump.pid", "w") as f:
            f.write("%d\n" % os.getpid())
        out = self.run_install()
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("снимается дамп", out.stderr)

    def uninstall(self, *args):
        return subprocess.run(["sh", self.root + "/usr/bin/fm350-uninstall"] + list(args), capture_output=True, text=True,
                              env=dict(os.environ, FM350_ROOT=self.root, PATH=self.bin + ":/usr/bin:/bin"))

    def put_da(self):
        os.makedirs(self.root + "/etc/fm350backup/kit", exist_ok=True)
        with open(self.root + "/etc/fm350backup/kit/DA_mine.bin", "wb") as f:
            f.write(b"da")

    def test_uninstall_removes_everything_but_dumps(self):
        self.manager("apk")
        self.run_install()
        self.put_da()
        dump = self.root + "/mnt/sda1/fm350-backup/fm350_1"
        os.makedirs(dump)
        with open(dump + "/full_dump.img", "wb") as f:
            f.write(b"dump")
        out = self.uninstall()
        self.assertEqual(out.returncode, 0, out.stderr)
        for gone in ("usr/share/fm350backup", "usr/libexec/fm350-backup", "etc/fm350backup", "usr/bin/fm350-uninstall",
                     "www/luci-static/resources/view/fm350backup"):
            self.assertFalse(self.installed(gone), gone)
        self.assertTrue(self.installed("mnt/sda1/fm350-backup/fm350_1/full_dump.img"))
        self.assertNotIn("fm350", read(self.root + "/etc/sysupgrade.conf"))

    def test_keep_da_on_request(self):
        self.manager("apk")
        self.run_install()
        self.put_da()
        self.assertEqual(self.uninstall("--keep-da").returncode, 0)
        self.assertTrue(self.installed("etc/fm350backup/kit/DA_mine.bin"))
        self.assertFalse(self.installed("usr/share/fm350backup"))

    def test_uninstall_removes_only_packages_it_added(self):
        self.stub("apk", 'echo "apk $*" >> "%s"\ncase "$*" in "info -e python3-light"|"info -e kmod-usb-storage") exit 0;; "info -e "*) exit 1;; esac\nexit 0\n' % self.calls)
        self.run_install()
        self.assertEqual(self.uninstall().returncode, 0)
        log = self.log()
        self.assertIn("apk del python3-logging", log)
        self.assertIn("apk del kmod-fs-exfat", log)
        self.assertNotIn("apk del python3-light", log)
        self.assertNotIn("apk del kmod-usb-storage", log)

    def test_dependent_packages_are_removed_whatever_the_order(self):
        # python3-light нельзя удалить, пока стоит python3-logging, как на настоящем opkg
        mark = self.calls + ".logging-gone"
        self.stub("apk", """echo "apk $*" >> "%s"
case "$*" in
  "info -e "*) exit 1;;
  "del python3-light") [ -f "%s" ] || exit 1;;
  "del python3-logging") : > "%s";;
esac
exit 0
""" % (self.calls, mark, mark))
        self.run_install()
        out = self.uninstall()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("оставлен", out.stdout)
        self.assertEqual(self.log().count("apk del python3-light"), 2)

    def test_package_needed_by_others_stays_and_is_named(self):
        self.stub("apk", """echo "apk $*" >> "%s"
case "$*" in "info -e "*) exit 1;; "del libusb-1.0-0") exit 1;; esac
exit 0
""" % self.calls)
        self.run_install()
        out = self.uninstall()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Пакет libusb-1.0-0 оставлен", out.stdout)


    def test_second_install_does_not_forget_or_repeat_added_packages(self):
        self.stub("apk", """echo "apk $*" >> "%s"
case "$1 $2" in "info -e") [ -f "%s" ] && exit 0; exit 1;; esac
exit 0
""" % (self.calls, self.calls + ".present"))
        self.run_install()
        first = read(self.root + "/etc/fm350backup/added-packages").split()
        self.assertIn("python3-light", first)
        with open(self.calls + ".present", "w"):
            pass
        self.run_install()
        self.assertEqual(read(self.root + "/etc/fm350backup/added-packages").split(), first)

    def test_uninstall_refuses_during_dump(self):
        self.manager("apk")
        self.run_install()
        os.makedirs(self.root + "/tmp/fm350backup", exist_ok=True)
        with open(self.root + "/tmp/fm350backup/dump.pid", "w") as f:
            f.write("%d\n" % os.getpid())
        out = self.uninstall()
        self.assertNotEqual(out.returncode, 0)
        self.assertTrue(self.installed("usr/share/fm350backup"))

    def test_uninstall_rejects_unknown_option(self):
        self.manager("apk")
        self.run_install()
        self.assertEqual(self.uninstall("--all").returncode, 2)
        self.assertTrue(self.installed("usr/share/fm350backup"))


class Release(unittest.TestCase):
    def test_install_script_has_placeholders_only_for_version_and_repo(self):
        self.assertEqual(set(re.findall(r"@([A-Z]+)@", read(os.path.join(ROOT, "install.sh")))), {"VERSION", "REPO"})

    def test_versions_agree(self):
        version = read(os.path.join(ROOT, "VERSION")).strip()
        self.assertIn("## " + version, read(os.path.join(ROOT, "CHANGELOG.md")))

    def test_nothing_internal_in_the_repository(self):
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        for name in ("CLAUDE.md", "vendor.lock", "install-offline.sh", "Makefile"):
            self.assertNotIn(name, files)
        for path in files:
            self.assertFalse(path.startswith(("vendor/", "dist/", "build/")), path)
            self.assertFalse(path.endswith((".bin", ".img", ".apk", ".run", ".auth", ".tar", ".gz")), path)
        words = re.compile("FM350-дампы/|/Users/|fm350-private".encode())
        for path in files:
            if path in ("scripts/check-private.sh", "tests/test_install.py"):
                continue
            self.assertIsNone(words.search(read(os.path.join(ROOT, path), "rb")), path)


if __name__ == "__main__":
    unittest.main()
