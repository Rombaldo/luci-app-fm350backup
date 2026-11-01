#!/bin/sh
# Удаляет FM350 Backup и Python с libusb, если их поставил её установщик. Драйверы USB и block-mount остаются.
# Дампы на флешках и в /root/fm350-backup не трогает.
#   fm350-uninstall             удалить всё, включая файлы DA
#   fm350-uninstall --keep-da   оставить файлы DA в /etc/fm350backup/kit
set -e
R="${FM350_ROOT:-}"
KEEP_DA=
case "$1" in
	--keep-da) KEEP_DA=1 ;;
	"") ;;
	*) echo "Неизвестный параметр: $1. Можно только --keep-da" >&2; exit 2 ;;
esac

pid=$(sed -n 1p "$R/tmp/fm350backup/dump.pid" 2>/dev/null || true)
if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
	echo "ОШИБКА: сейчас снимается дамп, дождись конца" >&2
	exit 1
fi

ADDED=$(cat "$R/etc/fm350backup/added-packages" 2>/dev/null || true)

rm -f  "$R/usr/libexec/fm350-backup" \
       "$R/usr/libexec/rpcd/luci.fm350backup" \
       "$R/usr/share/rpcd/acl.d/luci-app-fm350backup.json" \
       "$R/usr/share/luci/menu.d/luci-app-fm350backup.json" \
       "$R/etc/config/fm350backup" \
       "$R/etc/fm350backup/modems.json" \
       "$R/etc/fm350backup/added-packages"
rm -rf "$R/www/luci-static/resources/view/fm350backup" "$R/usr/share/fm350backup" "$R/tmp/fm350backup"
if [ -z "$KEEP_DA" ]; then
	rm -rf "$R/etc/fm350backup"
fi
if [ -f "$R/etc/sysupgrade.conf" ]; then
	sed -i.old -e '/fm350/d' "$R/etc/sysupgrade.conf"
	rm -f "$R/etc/sysupgrade.conf.old"
fi
rm -f "$R"/tmp/luci-indexcache* 2>/dev/null || true
[ -n "$R" ] || /etc/init.d/rpcd restart 2>/dev/null || true

remove_package() {
	if command -v apk >/dev/null 2>&1; then
		apk del "$1" >/dev/null 2>&1
	else
		opkg remove --autoremove "$1" >/dev/null 2>&1
	fi
}

if [ -n "$ADDED" ]; then
	echo "Удаляю пакеты, которые поставила программа"
	# пакет не удалить, пока от него зависит другой из этого же списка, поэтому несколько проходов
	left="$ADDED"
	for pass in 1 2 3 4; do
		still=""
		for p in $left; do
			# старые версии установщика запоминали и их: снятие block-mount отмонтирует /overlay и /rom
			case "$p" in
				block-mount|kmod-*) continue ;;
			esac
			remove_package "$p" || still="$still $p"
		done
		left="$still"
		[ -n "$left" ] || break
	done
	for p in $left; do
		echo "Пакет $p оставлен: он нужен чему-то ещё"
	done
fi

rm -f "$R/usr/bin/fm350-uninstall"
echo "Удалено. Дампы на флешке не тронуты."
if [ -n "$KEEP_DA" ]; then
	echo "Файлы DA остались в /etc/fm350backup/kit"
fi
if [ -z "$ADDED" ]; then
	echo "Системные пакеты не удалялись: их не ставила эта версия установщика"
fi
exit 0
