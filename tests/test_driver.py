"""Тесты логики драйвера, которым не нужны роутер и модем."""
import importlib.machinery
import importlib.util
import hashlib
import io
import json
import os
import random
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
PATH = os.path.join(ROOT, "files", "usr", "libexec", "fm350-backup")
loader = importlib.machinery.SourceFileLoader("fm350_backup", PATH)
spec = importlib.util.spec_from_loader("fm350_backup", loader)
drv = importlib.util.module_from_spec(spec)
loader.exec_module(drv)
drv.SHARE = os.path.join(ROOT, "files", "usr", "share", "fm350backup")
NAND_SIZE = 0x1FF00000


class FilesDA(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.up = tempfile.TemporaryDirectory()
        self.old = drv.KIT
        drv.KIT = self.tmp.name

    def tearDown(self):
        drv.KIT = self.old
        self.tmp.cleanup()
        self.up.cleanup()

    def put(self, name, data):
        with open(os.path.join(self.tmp.name, name), "wb") as f:
            f.write(data)

    def upload(self, data):
        path = os.path.join(self.up.name, "upload")
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_upload_goes_to_the_folder(self):
        data = b"MTK_DOWNLOAD_AGENT" + bytes(100)
        self.assertEqual(drv.install_da(self.upload(data), "DA_BR.bin"), "DA_BR.bin")
        self.assertEqual([os.path.basename(p) for p in drv.list_das()], ["DA_BR.bin"])
        with open(os.path.join(self.tmp.name, "DA_BR.bin"), "rb") as f:
            self.assertEqual(f.read(), data)

    def test_upload_rejects_a_foreign_file(self):
        with self.assertRaisesRegex(RuntimeError, "Это не файл DA"):
            drv.install_da(self.upload(b"PK zip archive" + bytes(100)), "DA_BR.bin")
        self.assertEqual(drv.list_das(), [])

    def test_upload_rejects_too_big_file(self):
        path = self.upload(b"MTK_DOWNLOAD_AGENT")
        with open(path, "ab") as f:
            f.truncate(drv.DA_MAX_SIZE + 1)
        with self.assertRaisesRegex(RuntimeError, "Это не файл DA"):
            drv.install_da(path, "DA.bin")

    def test_same_file_is_not_copied_twice(self):
        data = b"MTK_DOWNLOAD_AGENT" + bytes(100)
        drv.install_da(self.upload(data), "DA_BR.bin")
        self.assertEqual(drv.install_da(self.upload(data), "other.bin"), "DA_BR.bin")
        self.assertEqual(len(drv.list_das()), 1)

    def test_different_file_with_same_name_is_kept(self):
        drv.install_da(self.upload(b"MTK_DOWNLOAD_AGENT" + b"1" * 50), "DA_BR.bin")
        self.assertEqual(drv.install_da(self.upload(b"MTK_DOWNLOAD_AGENT" + b"2" * 50), "DA_BR.bin"), "DA_BR_1.bin")
        self.assertEqual(len(drv.list_das()), 2)

    def test_name_cannot_escape_the_folder(self):
        for bad in ("../../etc/passwd", "/etc/config/x.bin", "..bin", "a b;rm -rf.bin", ""):
            name = drv.install_da(self.upload(b"MTK_DOWNLOAD_AGENT" + bad.encode() + bytes(9)), bad)
            self.assertRegex(name, r"^[A-Za-z0-9_-][A-Za-z0-9._-]*\.bin$", bad)
            self.assertTrue(os.path.isfile(os.path.join(self.tmp.name, name)), bad)

    def test_gpio_without_effect_asks_to_replug(self):
        gpio = os.path.join(self.up.name, "value")
        with mock.patch.object(drv, "gpio_path", lambda: gpio), mock.patch.object(drv.time, "sleep"), \
                mock.patch.object(drv, "log"):
            with mock.patch.object(drv, "modem", lambda: ("2-1.4", "7127")):
                self.assertFalse(drv.gpio_cycle())
            with mock.patch.object(drv, "modem", lambda: (None, None)):
                self.assertTrue(drv.gpio_cycle())

    def test_no_da_is_not_an_error(self):
        self.assertEqual(drv.list_das(), [])

    def test_any_name_with_real_header_newest_first(self):
        self.put("DA_2023.bin", b"MTK_DOWNLOAD_AGENT" + bytes(100))
        self.put("DA_2025.bin", b"MTK_DOWNLOAD_AGENT" + bytes(100))
        self.put("DA_BR.bin", b"MTK_DOWNLOAD_AGENT" + bytes(100))
        self.assertEqual([os.path.basename(p) for p in drv.list_das()], ["DA_BR.bin", "DA_2025.bin", "DA_2023.bin"])

    def test_foreign_files_are_ignored(self):
        self.put("full_dump.bin", bytes(100))
        self.put("notes.txt", b"MTK_DOWNLOAD_AGENT")
        self.assertEqual(drv.list_das(), [])


class UsbDrops(unittest.TestCase):
    # журнал роутера 01.11, строки дословно: запуск, затем перезагрузка сторожем 5gmodem
    DMESG = """
[    5.949256] usb 1-1.4: new full-speed USB device number 4 using xhci-mtk
[    7.093570] usb 1-1.4: USB disconnect, device number 4
[   25.319701] usb 2-1.4: new SuperSpeed USB device number 3 using xhci-mtk
[   28.057560] usb 2-1.4: GSM modem (1-port) converter now attached to ttyUSB0
[   28.072380] usb 2-1.4: GSM modem (1-port) converter now attached to ttyUSB1
[  682.945022] usb 2-1.4: USB disconnect, device number 3
[  685.324471] usb 1-1.4: new high-speed USB device number 5 using xhci-mtk
[  686.608532] usb 1-1.4: USB disconnect, device number 5
[  697.611253] usb 1-1.4: new high-speed USB device number 6 using xhci-mtk
[  698.893396] usb 1-1.4: USB disconnect, device number 6
[  717.476603] usb 2-1.4: new SuperSpeed USB device number 4 using xhci-mtk
[  720.215131] usb 2-1.4: GSM modem (1-port) converter now attached to ttyUSB0
"""
    LOG = """Sun Nov  1 19:12:16 2026 user.notice 5gmodem: watchdog: healing modem: reconnecting the interface (1/6)
Sun Nov  1 19:17:27 2026 user.notice 5gmodem: watchdog: healing modem: rebooting the module, AT+CFUN=1,1 (2/6)
"""

    def test_bootloader_stage_and_usb_stick_are_not_drops(self):
        self.assertEqual(drv.usb_drops(self.DMESG), 1)

    def test_stick_removed_is_not_a_drop(self):
        text = "usb 1-1.3: new high-speed USB device number 3\nusb 1-1.3: USB disconnect, device number 3"
        self.assertEqual(drv.usb_drops(text), 0)

    def test_program_reboot_is_counted_only_once(self):
        now = time.mktime(time.strptime("Nov 1 19:18:00 2026", "%b %d %H:%M:%S %Y"))
        count, ago = drv.program_reboots(self.LOG, now)
        self.assertEqual(count, 1)
        self.assertEqual(ago, 33)

    def test_no_reboots_in_log(self):
        self.assertEqual(drv.program_reboots("Sun Nov  1 19:18:44 2026 daemon.notice netifd: down"), (0, None))

    def test_report_blames_program_not_power(self):
        import sys
        sys.path.insert(0, drv.SHARE)
        import fm350diag
        none = fm350diag.diagnose("none", None, 0, 1, True)
        self.assertEqual(none["findings"][0]["title"], "Модем перезагружается")
        self.assertEqual(none["level"], "info")
        self.assertNotIn("обесточ", none["findings"][0]["action"])
        self.assertEqual(fm350diag.diagnose("none")["findings"][0]["title"], "Модем не виден на USB")


class CatchDA(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (drv.KIT, drv.LOG, drv.LOCK, drv.RUN, drv.STATE, drv.stop_services, drv.gpio_cycle)
        drv.KIT = self.tmp.name
        drv.LOG = os.path.join(self.tmp.name, "dump.log")
        drv.LOCK = os.path.join(self.tmp.name, "dump.pid")
        drv.RUN = self.tmp.name
        drv.STATE = os.path.join(self.tmp.name, "state.json")
        open(drv.LOG, "w").close()
        self.stopped = []
        drv.stop_services = lambda: self.stopped.append(True)
        drv.gpio_cycle = lambda *a: True

    def tearDown(self):
        drv.KIT, drv.LOG, drv.LOCK, drv.RUN, drv.STATE, drv.stop_services, drv.gpio_cycle = self.saved
        self.tmp.cleanup()

    def test_no_da_stops_before_touching_the_modem(self):
        with self.assertRaisesRegex(RuntimeError, "Нет файла DA"):
            drv.catch_da(["ro"], {})
        self.assertEqual(self.stopped, [])

    def test_all_da_rejected_says_so(self):
        with open(os.path.join(self.tmp.name, "DA_a.bin"), "wb") as f:
            f.write(b"MTK_DOWNLOAD_AGENT")

        class Proc:
            pid = 1

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self):
                pass

        def popen(*a, **k):
            with open(drv.LOG, "a") as f:
                f.write("DAA_SIG_VERIFY_FAILED\n")
            return Proc()

        with mock.patch.object(drv.subprocess, "Popen", popen), mock.patch.object(drv.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "не принял ни один файл DA"):
                drv.catch_da(["ro %s"], {})


class Partitions(unittest.TestCase):
    def test_table_covers_whole_nand_without_gaps(self):
        pos = 0
        parts = drv.load_partitions()
        self.assertEqual(len(parts), 40)
        for name, start, size in parts:
            self.assertEqual(start, pos, name)
            pos += size
        self.assertEqual(pos, NAND_SIZE)

    def test_always_full_with_reserved_regions_last(self):
        seq = [p[0] for p in drv.dump_sequence(drv.load_partitions())]
        self.assertEqual(len(seq), 40)
        self.assertEqual(seq[-2:], ["pmt", "expdb"])


class WantBytes(unittest.TestCase):
    def test_pmt_is_read_one_byte_short(self):
        self.assertEqual(drv.want_bytes("pmt", 0x80000), 0x7FFFF)
        self.assertEqual(drv.want_bytes("expdb", 0x1400000), 0x1400000)


class Classify(unittest.TestCase):
    parts = [("lk", 0, 10), ("pmt", 10, 10), ("expdb", 20, 10)]

    def test_everything_read(self):
        self.assertEqual(drv.classify(self.parts, {"lk": 10, "pmt": 9, "expdb": 10}), ([], [], True))

    def test_short_real_partition_is_missing(self):
        self.assertEqual(drv.classify(self.parts, {"lk": 3, "pmt": 9, "expdb": 10})[0], ["lk"])

    def test_empty_pmt_is_not_real(self):
        self.assertEqual(drv.classify(self.parts, {"lk": 10, "pmt": 0, "expdb": 0}), ([], ["pmt", "expdb"], False))

    def test_expdb_alone_keeps_dump_usable(self):
        self.assertEqual(drv.classify(self.parts, {"lk": 10, "pmt": 9, "expdb": 0}), ([], ["expdb"], True))


class Card(unittest.TestCase):
    def test_parses_real_answers(self):
        c = drv.parse_card({
            "ATI": "Manufacturer: Fibocom Wireless Inc.\r\nModel: FM350-GL\r\nRevision: 81600\r\nOK\r\n",
            "AT+GTPKGVER?": '+GTPKGVER: "81600.0000.00.29.23.22_F30"\r\nOK\r\n',
            "AT+CGSN": "123456789012345\r\nOK\r\n", "AT+CFSN": '+CFSN: "ABC123"\r\nOK\r\n', "AT+CPIN?": "+CPIN: READY\r\nOK\r\n",
            "AT+CSQ": "+CSQ: 12, 99\r\nOK\r\n", "AT+COPS?": '+COPS:0,2,"25002",7\r\nOK\r\n',
            "AT+GTDIPCMODE?": "+GTDIPCMODE: 3,1,1,1,3,15\r\nOK\r\n",
            "AT+GTSENRDTEMP=1": "+GTSENRDTEMP: 1,47579\r\nOK\r\n"})
        self.assertEqual(c, {"model": "FM350-GL", "firmware": "81600.0000.00.29.23.22_F30",
                             "imei": "123456789012345", "serial": "ABC123", "sim": True, "signal": "средний",
                             "operator": "MegaFon", "rat": "LTE", "dipc": "3,1,1,1,3,15", "dipc_ok": True,
                             "temp_c": 48})

    def test_pcie_setting_is_flagged(self):
        self.assertFalse(drv.parse_card({"AT+GTDIPCMODE?": "+GTDIPCMODE: 1,2,2,2,23,13\r\nOK"})["dipc_ok"])

    def test_silence_and_no_sim(self):
        c = drv.parse_card({"AT+CPIN?": "ERROR", "AT+CSQ": "+CSQ: 99,99\r\nOK"})
        self.assertEqual(c, {"sim": False})


class Identity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = drv.IDENTITY
        drv.IDENTITY = os.path.join(self.tmp.name, "x", "modems.json")
        self.addCleanup(setattr, drv, "IDENTITY", self.old)

    def test_chip_id_is_kept_for_same_modem_and_dropped_for_another(self):
        drv.remember_identity(imei="1", me_id="AA")
        self.assertEqual(drv.remember_identity(imei="1", firmware="f")["me_id"], "AA")
        self.assertNotIn("me_id", drv.remember_identity(imei="2"))


class MtkEnv(unittest.TestCase):
    def test_no_bytecode_is_written(self):
        env = drv.mtk_env()
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")


class BundledMtkclient(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "third_party", "mtkclient", "mtkclient", "Library", "DA", "xmlflash",
                               "xml_lib.py"), encoding="utf-8") as f:
            self.text = f.read()

    def test_has_speed_and_pause_fixes(self):
        self.assertIn("FM350_RUNTIME_PARAMETER", self.text)
        self.assertIn("if self.mtk.config.hwcode == 0x992:\n            return False", self.text)

    def test_has_no_write_hook_or_fixed_router_paths(self):
        self.assertNotIn("nvhook", self.text)
        self.assertNotIn("/root/mtk", self.text)


class Menu(unittest.TestCase):
    def test_page_has_its_own_parent_section(self):
        # раздел Modem есть только там, где стоит другой пакет: без родителя LuCI страницу не покажет
        with open(os.path.join(ROOT, "files", "usr", "share", "luci", "menu.d", "luci-app-fm350backup.json"),
                  encoding="utf-8") as f:
            menu = json.load(f)
        self.assertEqual(menu["admin/modem"]["action"]["type"], "firstchild")
        self.assertIn("admin/modem/fm350backup", menu)


class NoLeftovers(unittest.TestCase):
    def test_interface_has_no_removed_controls(self):
        with open(os.path.join(ROOT, "files", "www", "luci-static", "resources", "view", "fm350backup",
                               "backup.js"), encoding="utf-8") as f:
            js = f.read()
        for word in ("auth_sv5", "set_mode", "start_deps", "безопасн"):
            self.assertNotIn(word, js)


class StreamTar(unittest.TestCase):
    """Настоящие FIFO, настоящий tarfile и писатели, которые отдают данные неровными кусками."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.threads = []

    def part(self, name, size, data, optional=False, want=None):
        fifo = os.path.join(self.tmp.name, name)
        os.mkfifo(fifo)
        if data is not None:
            def writer():
                with open(fifo, "wb", buffering=0) as f:
                    pos, rnd = 0, random.Random(1)
                    while pos < len(data):
                        k = rnd.randint(1, 70000)
                        f.write(data[pos:pos + k])
                        pos += k
            t = threading.Thread(target=writer, daemon=True)
            t.start()
            self.threads.append(t)
        return {"name": name, "size": size, "want": size if want is None else want, "fifo": fifo, "optional": optional}

    def run_tar(self, parts, order, alive=lambda: True):
        out = io.BytesIO()
        res = drv.stream_tar(out, parts, order, "r", alive, lambda k, n: None, {"imei": "1"})
        out.seek(0)
        with tarfile.open(fileobj=out) as t:
            return res, {m.name: t.extractfile(m).read() for m in t.getmembers()}

    def test_uneven_chunks_arrive_whole(self):
        a, b = os.urandom(300000), os.urandom(70001)
        res, files = self.run_tar([self.part("a", len(a), a), self.part("b", len(b), b)], ["b", "a"])
        self.assertEqual(res, ([], [], True))
        self.assertEqual(files["r/partitions/a.bin"], a)
        self.assertEqual(files["r/partitions/b.bin"], b)
        self.assertIn("cat partitions/b.bin partitions/a.bin > full_dump.img", files["r/" + drv.SCRIPT_LINUX].decode())
        self.assertIn("copy /b /y partitions\\b.bin+partitions\\a.bin full_dump.img", files["r/" + drv.SCRIPT_WINDOWS].decode())
        self.assertEqual(files["r/" + drv.SCRIPT_MACOS], files["r/" + drv.SCRIPT_LINUX])
        self.assertIn("ПРОЧТИ", drv.README_NAME)
        self.assertIn("full_dump.img", files["r/" + drv.README_NAME].decode("utf-8-sig"))
        self.assertIn(hashlib.md5(a).hexdigest() + "  a.bin", files["r/partitions/md5sum.txt"].decode())

    def unpack_and_build(self, damage=False):
        a, b = os.urandom(5000), os.urandom(7000)
        out = io.BytesIO()
        res = drv.stream_tar(out, [self.part("a", len(a), a), self.part("b", len(b), b)], ["b", "a"], "r",
                             lambda: True, lambda k, n: None, {})
        self.assertEqual(res, ([], [], True))
        out.seek(0)
        with tempfile.TemporaryDirectory() as tmp:
            with tarfile.open(fileobj=out) as t:
                t.extractall(tmp)
            top = os.path.join(tmp, "r")
            self.assertEqual(sorted(os.listdir(top)), sorted([drv.README_NAME, drv.SCRIPT_WINDOWS, drv.SCRIPT_MACOS,
                                                               drv.SCRIPT_LINUX, "partitions"]))
            self.assertTrue(os.access(os.path.join(top, drv.SCRIPT_MACOS), os.X_OK))
            if damage:
                with open(os.path.join(top, "partitions", "a.bin"), "r+b") as f:
                    f.write(b"\x00\x01\x02")
            run = subprocess.run(["sh", os.path.join(top, drv.SCRIPT_LINUX)], capture_output=True, text=True, cwd="/")
            image = os.path.join(top, "full_dump.img")
            data = None
            if os.path.exists(image):
                with open(image, "rb") as f:
                    data = f.read()
            return run, data, b + a

    def test_script_builds_image_in_address_order(self):
        run, data, want = self.unpack_and_build()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(data, want)

    def test_script_refuses_damaged_archive(self):
        run, data, _ = self.unpack_and_build(damage=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("повреждён", run.stdout)
        self.assertIsNone(data)

    def test_pmt_one_byte_short_is_padded_and_counts_as_real(self):
        d = os.urandom(99)
        res, files = self.run_tar([self.part("pmt", 100, d, True, 99)], ["pmt"])
        self.assertEqual(res, ([], [], True))
        self.assertEqual(files["r/partitions/pmt.bin"], d + b"\xff")

    def test_unread_expdb_is_padded_after_process_dies(self):
        a = os.urandom(1000)
        res, files = self.run_tar([self.part("a", 1000, a), self.part("expdb", 500, None, True)], ["a", "expdb"],
                                  alive=lambda: False)
        self.assertEqual(res, ([], ["expdb"], True))
        self.assertEqual(files["r/partitions/expdb.bin"], b"\xff" * 500)

    def test_stops_after_missing_required_partition(self):
        a = os.urandom(10)
        res, files = self.run_tar([self.part("a", 1000, a), self.part("b", 1000, None)], ["a", "b"], alive=lambda: False)
        self.assertEqual(res, (["a"], [], False))
        self.assertNotIn("r/partitions/b.bin", files)
        self.assertNotIn("r/" + drv.SCRIPT_LINUX, files)
        self.assertFalse(json.loads(files["r/partitions/manifest.json"])["complete"])


class Listener(unittest.TestCase):
    def request(self, port, path):
        c = socket.create_connection(("127.0.0.1", port), timeout=5)
        c.sendall(("GET %s HTTP/1.1\r\nHost: x\r\n\r\n" % path).encode())
        d = c.recv(4096)
        c.close()
        return d

    def test_token_is_required(self):
        srv = drv.open_listener()
        self.addCleanup(srv.close)
        port, got = srv.getsockname()[1], {}

        def serve():
            got["conn"] = drv.wait_client(srv, "secret", "x.tar", timeout=10)
        t = threading.Thread(target=serve)
        t.start()
        self.assertIn(b"403", self.request(port, "/x.tar"))
        self.assertIn(b"403", self.request(port, "/x.tar?t=wrong"))
        self.assertIn(b"403", self.request(port, "/x.tar?t=secretX"))
        answer = self.request(port, "/x.tar?t=secret")
        t.join()
        got["conn"].close()
        self.assertIn(b"200 OK", answer)
        self.assertIn(b'filename="x.tar"', answer)


class DiagCopy(unittest.TestCase):
    def test_same_engine_as_mac_program(self):
        mac = os.path.expanduser("~/Developer/fm350-dump/src/app/fm350diag.py")
        if not os.path.exists(mac):
            self.skipTest("нет репозитория программы для Mac")
        with open(mac, encoding="utf-8") as a, open(os.path.join(ROOT, "files", "usr", "share", "fm350backup", "fm350diag.py"), encoding="utf-8") as b:
            self.assertEqual(a.read(), b.read())


class Version(unittest.TestCase):
    def test_source_tree_reports_dev(self):
        self.assertEqual(drv.version(), "dev")


class DeleteGuard(unittest.TestCase):
    def test_refuses_paths_outside_backups(self):
        for path in ("/etc", "/tmp", "/", "/root/fm350_x", "../fm350_x"):
            self.assertFalse(drv.is_backup_dir(path), path)


if __name__ == "__main__":
    unittest.main()
