#!/usr/bin/env python3
"""Общие шаблоны личных данных, в том числе в двоичных файлах: номера вроде IMEI и почта."""
import os
import re
import sys

IMEI = re.compile(rb"(?<![0-9a-fA-Fx])[0-9]{15}(?![0-9a-fA-F])")
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}")
# служебные адреса и открытые адреса авторов чужих библиотек, только точно
ALLOWED_MAIL = re.compile(rb"@(fsf\.org|gnu\.org|noreply\.github\.com|anthropic\.com|example\.(com|org))$", re.I)
ALLOWED_AUTHORS = {b"cliechti@gmx.net", b"grante@visi.com", b"rasky@develer.com", b"me@jonasmalaco.com", b"tartley@tartley.com"}
SKIP = {"check-patterns.py", "check-private.sh"}


def luhn(digits):
    total = 0
    for i, c in enumerate(reversed(digits)):
        n = c - 48
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def scan(path):
    with open(path, "rb") as f:
        data = f.read()
    hits = []
    hits += [m.group().decode() for m in IMEI.finditer(data) if luhn(m.group())]
    hits += [m.group().decode("latin-1") for m in EMAIL.finditer(data) if not ALLOWED_MAIL.search(m.group()) and m.group() not in ALLOWED_AUTHORS]
    return hits


def main():
    bad = 0
    for top in sys.argv[1:]:
        if not os.path.exists(top):
            continue
        paths = [top] if os.path.isfile(top) else [os.path.join(d, f) for d, _, fs in os.walk(top) for f in fs]
        for p in paths:
            if os.path.basename(p) in SKIP or "__pycache__" in p:
                continue
            for hit in scan(p):
                print("%s: похоже на личные данные: %s" % (p, hit))
                bad = 1
    sys.exit(bad)


if __name__ == "__main__":
    main()
