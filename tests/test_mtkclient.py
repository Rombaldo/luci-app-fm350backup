"""Урезанный mtkclient: только чтение, без приёмов обхода защиты. Роутер и модем не нужны."""
import json
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "third_party", "mtkclient")


def sources():
    for d, _, files in os.walk(ROOT):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(d, f)


class Cut(unittest.TestCase):
    def test_no_exploit_code(self):
        words = re.compile(r"carbonara|kamakiri|heapbait|hashimoto|amonet|PLTools|bypass_security|crasher", re.I)
        for p in sources():
            with open(p, encoding="utf-8") as f:
                self.assertIsNone(words.search(f.read()), p)

    def test_removed_parts_stay_removed(self):
        for part in ("mtkclient/Library/Exploit", "mtkclient/Library/pltools.py", "mtkclient/payloads",
                     "mtkclient/Loader", "mtkclient/Library/DA/xflash", "mtkclient/Library/DA/legacy",
                     "mtkclient/Library/DA/xmlflash/extension", "stage2.py"):
            self.assertFalse(os.path.exists(os.path.join(ROOT, part)), part)

    def test_no_prebuilt_binaries(self):
        for d, _, files in os.walk(ROOT):
            for f in files:
                self.assertFalse(f.endswith((".bin", ".so", ".dll", ".exe", ".auth")), os.path.join(d, f))

    def test_only_read_commands(self):
        with open(os.path.join(ROOT, "mtk.py"), encoding="utf-8") as f:
            cmds = re.findall(r'subparsers\.add_parser\(\s*"(\w+)"', f.read())
        self.assertEqual(sorted(cmds), ["multi", "ro"])

    def test_no_write_exchange_with_da(self):
        with open(os.path.join(ROOT, "mtkclient", "Library", "DA", "xmlflash", "xml_cmd.py"), encoding="utf-8") as f:
            text = f.read()
        for cmd in ("WRITE-FLASH", "WRITE-PARTITION", "ERASE-FLASH", "ERASE-PARTITION", "FLASH-ALL", "FLASH-UPDATE",
                    "WRITE-EFUSE", "WRITE-REGISTER", "WRITE-PRIVATE-CERT"):
            self.assertNotIn(cmd, text, cmd)


class CryptoFree(unittest.TestCase):
    def test_nothing_imports_crypto_libraries(self):
        words = re.compile(r"^\s*(from|import)\s+(Crypto|Cryptodome|capstone|keystone|mfusepy|PySide6)\b", re.M)
        for p in sources():
            with open(p, encoding="utf-8") as f:
                self.assertIsNone(words.search(f.read()), p)

    def test_requirements_are_pure_python(self):
        with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read().split(), ["pyusb", "pyserial", "colorama"])

    def test_no_sla_keys(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "mtkclient", "Library", "Auth")))
        with open(os.path.join(ROOT, "mtkclient", "Library", "DA", "xmlflash", "xml_lib.py"), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("sla_signature", text)
        self.assertNotIn("Transsion", text)


class ReadFlow(unittest.TestCase):
    """Весь путь команды, как её запускает драйвер, с поддельным портом вместо USB, без библиотек шифрования."""

    def check(self, what):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mtk_flow_check.py")
        out = subprocess.run([sys.executable, script, what], capture_output=True, text=True, timeout=60,
                             env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        lines = [x for x in out.stdout.splitlines() if x.startswith("RESULT ")]
        self.assertTrue(lines, out.stdout + out.stderr)
        return json.loads(lines[-1][7:])

    def test_multi_as_the_driver_runs_it(self):
        res = self.check("multi")
        self.assertEqual(res["reads"], [[0, 0x1000], [0x1000, 0x2000]])
        self.assertEqual(res["uploads"], 1)

    def test_slow_disk_keeps_the_end_of_the_file(self):
        res = self.check("slow_disk")
        self.assertTrue(res["ok"])
        self.assertEqual(res["size"], res["want"])
        self.assertEqual(res["joins"], [None])
        self.assertLessEqual(res["deepest"], 16)

    def test_sla_stops_and_nothing_goes_on(self):
        res = self.check("sla")
        self.assertFalse(res["result"])
        self.assertIn("SLA is enabled", res["error"])
        self.assertEqual(res["reinit"], 0)


if __name__ == "__main__":
    unittest.main()
