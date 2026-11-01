#!/bin/sh
# Запускается внутри контейнера OpenWrt на GitHub Actions: ставит программу и проверяет, что она работает.
# Модема и настоящего USB там нет, поэтому это проверка установки, а не дампа.
#   test-in-openwrt.sh <адрес, откуда качать> <папка с install.sh>
set -e
mkdir -p /var/lock /var/run
FM350_BASE_URL="$1" sh "$2/install.sh"

echo "--- программа отвечает, DA нет"
/usr/libexec/fm350-backup status > /tmp/status.json
python3 - <<'PY'
import json
st = json.load(open("/tmp/status.json"))
assert st["version"], st
assert st["da_count"] == 0, st
assert st["ready"] is False, st
print("status:", st["version"], "ready:", st["ready"])
PY

echo "--- mtkclient запускается"
cd /usr/share/fm350backup/mtkclient
PYTHONPATH=/usr/share/fm350backup/pylib PYTHONDONTWRITEBYTECODE=1 python3 mtk.py --help > /dev/null

echo "--- libusb загружается"
# саму инициализацию здесь не проверить: в контейнере нет USB
python3 - <<'PY'
import ctypes
loaded = []
for name in ("libusb-1.0.so", "libusb-1.0.so.0"):
    try:
        ctypes.CDLL(name)
        loaded.append(name)
    except OSError:
        pass
assert loaded, "нет libusb"
print("libusb:", loaded)
PY

echo "--- повторная установка и удаление"
FM350_BASE_URL="$1" sh "$2/install.sh" > /dev/null
fm350-uninstall
[ ! -e /usr/libexec/fm350-backup ]
[ ! -e /usr/bin/fm350-uninstall ]
[ ! -e /etc/fm350backup ]
# контейнер был без Python: установщик его поставил, значит удаление обязано его убрать.
# Смотрим сам файл и список пакетов: ash помнит путь и command -v здесь мог бы соврать.
left=$( (apk list -I 2>/dev/null || opkg list-installed 2>/dev/null) | grep -E '^(python3|libpython3|libusb-1)' || true)
if [ -n "$left" ] || [ -e /usr/bin/python3 ]; then
	echo "ОШИБКА: после удаления остались пакеты:"
	echo "$left"
	ls -l /usr/bin/python3 2>&1 || true
	exit 1
fi
echo "Python и libusb удалены"
for p in block-mount kmod-usb-storage; do
	if ! (apk info -e "$p" 2>/dev/null || opkg status "$p" 2>/dev/null | grep -q ' installed') >/dev/null; then
		echo "ОШИБКА: удаление сняло $p"
		exit 1
	fi
done
echo "Установка проверена: $(sed -n "s/^DISTRIB_RELEASE='\(.*\)'/\1/p" /etc/openwrt_release)"
