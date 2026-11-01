#!/usr/bin/env python3
"""Лёгкая сборка для установки из интернета: один и тот же результат на Mac и на GitHub Actions.

  build-release.py                  dist/release/: архив, install.sh, SHA256SUMS. DA в архиве нет
  build-release.py --with-da ПАПКА  dist/release-with-da/: то же с файлами *.bin из папки. Не публиковать без решения владельца
  --repo владелец/имя               откуда install.sh будет качать
"""
import argparse
import gzip
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SKIP_DIRS = {"__pycache__", ".git"}
# RECORD и INSTALLER пишет pip, они зависят от компьютера сборки, программе не нужны
SKIP_FILES = {".DS_Store", "hwparam.json", ".state", "RECORD", "INSTALLER", "REQUESTED", "direct_url.json"}
SKIP_SUFFIX = (".pyc", ".pyo", ".orig", ".pyi", ".bak")


def pure_libs(dest):
    """Библиотеки строго по суммам из requirements-router.txt, только чистый Python."""
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "--no-compile", "--no-deps",
                           "--only-binary", ":all:", "--require-hashes", "--disable-pip-version-check",
                           "--target", dest, "-r", os.path.join(ROOT, "requirements-router.txt")])
    bad = []
    for d, dirs, files in os.walk(dest):
        dirs[:] = [x for x in dirs if x != "bin"]
        bad += [f for f in files if f.endswith((".so", ".dylib", ".pyd"))]
    if bad:
        sys.exit("ОШИБКА: не чистый Python: %s" % bad)
    for name in ("bin", "__pycache__"):
        shutil.rmtree(os.path.join(dest, name), ignore_errors=True)


def walk(top, arc):
    """(имя в архиве, путь) по порядку, чтобы архив не зависел от файловой системы."""
    out = []
    for d, dirs, files in os.walk(top):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        rel = os.path.relpath(d, top)
        base = arc if rel == "." else arc + "/" + rel.replace(os.sep, "/")
        out.append((base, d))
        for f in sorted(files):
            if f not in SKIP_FILES and not f.endswith(SKIP_SUFFIX):
                out.append((base + "/" + f, os.path.join(d, f)))
    return out


def add(tar, name, path=None, data=None):
    info = tarfile.TarInfo(name)
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    if path is not None and os.path.isdir(path):
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        tar.addfile(info)
        return
    if data is None:
        with open(path, "rb") as f:
            data = f.read()
    executable = path is not None and os.access(path, os.X_OK)
    info.mode = 0o755 if executable else 0o644
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def build(version, outdir, da_dir):
    tar_name = "fm350backup-%s.tar.gz" % version
    # имя страницы меняется с версией: браузеры долго держат файлы LuCI в кеше
    page = "backup_" + version.replace(".", "_")
    with tempfile.TemporaryDirectory() as tmp:
        pylib = os.path.join(tmp, "pylib")
        pure_libs(pylib)
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as tar:
            add(tar, "VERSION", data=(version + "\n").encode())
            add(tar, "uninstall.sh", os.path.join(ROOT, "uninstall.sh"))
            add(tar, "LICENSE", os.path.join(ROOT, "LICENSE"))
            add(tar, "THIRD_PARTY.md", os.path.join(ROOT, "THIRD_PARTY.md"))
            add(tar, "mtkclient-changes.md", os.path.join(ROOT, "docs", "mtkclient-changes.md"))
            for name, path in walk(os.path.join(ROOT, "files"), "files"):
                if name.endswith("/fm350backup/backup.js"):
                    add(tar, name.replace("/backup.js", "/%s.js" % page), path)
                elif name.endswith("/menu.d/luci-app-fm350backup.json"):
                    with open(path, encoding="utf-8") as f:
                        text = f.read().replace("fm350backup/backup", "fm350backup/" + page)
                    add(tar, name, data=text.encode())
                else:
                    add(tar, name, path)
            for name, path in walk(os.path.join(ROOT, "third_party", "mtkclient"), "mtkclient"):
                add(tar, name, path)
            for name, path in walk(pylib, "pylib"):
                add(tar, name, path)
            if da_dir:
                add(tar, "kit", da_dir)
                for f in sorted(os.listdir(da_dir)):
                    if f.endswith(".bin"):
                        add(tar, "kit/" + f, os.path.join(da_dir, f))
    os.makedirs(outdir, exist_ok=True)
    tar_path = os.path.join(outdir, tar_name)
    with open(tar_path, "wb") as f:
        with gzip.GzipFile(filename="", fileobj=f, mode="wb", compresslevel=9, mtime=0) as z:
            z.write(raw.getvalue())
    return tar_path


def check_contents(tar_path, with_da):
    """В публичном архиве нет DA и ничего скомпилированного."""
    with tarfile.open(tar_path) as tar:
        names = tar.getnames()
    for must in ("VERSION", "LICENSE", "mtkclient/LICENSE", "mtkclient/mtk.py", "files/usr/libexec/fm350-backup"):
        if must not in names:
            sys.exit("ОШИБКА: в архиве нет " + must)
    forbidden = (".so", ".dylib", ".pyd", ".exe", ".dll", ".auth", ".pyc") + (() if with_da else (".bin",))
    bad = [n for n in names if n.endswith(forbidden) or (not with_da and n.startswith("kit"))]
    if bad:
        sys.exit("ОШИБКА: этого не должно быть в архиве: %s" % bad)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-da")
    ap.add_argument("--repo", default="Rombaldo/luci-app-fm350backup")
    args = ap.parse_args()
    with open(os.path.join(ROOT, "VERSION")) as f:
        version = f.read().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        sys.exit("ОШИБКА: неверная версия " + version)
    outdir = os.path.join(ROOT, "dist", "release-with-da" if args.with_da else "release")
    shutil.rmtree(outdir, ignore_errors=True)
    tar_path = build(version, outdir, args.with_da)
    with open(os.path.join(ROOT, "install.sh"), encoding="utf-8") as f:
        script = f.read().replace("@VERSION@", version).replace("@REPO@", args.repo)
    install = os.path.join(outdir, "install.sh")
    with open(install, "w", encoding="utf-8") as f:
        f.write(script)
    os.chmod(install, 0o755)
    sums = []
    for path in (tar_path, install):
        with open(path, "rb") as f:
            sums.append("%s  %s" % (hashlib.sha256(f.read()).hexdigest(), os.path.basename(path)))
    with open(os.path.join(outdir, "SHA256SUMS"), "w") as f:
        f.write("\n".join(sums) + "\n")
    check_contents(tar_path, bool(args.with_da))
    subprocess.check_call([os.path.join(ROOT, "scripts", "check-private.sh"), tar_path])
    subprocess.check_call([os.path.join(ROOT, "scripts", "check-private.sh"), install])
    print("\n".join(sums))
    print("Собрано: %s, %.0f КБ" % (outdir, os.path.getsize(tar_path) / 1024))


if __name__ == "__main__":
    main()
