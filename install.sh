#!/bin/sh
# FM350 Backup: установка на роутер с OpenWrt из интернета. Запуск на роутере:
#     wget -O- https://github.com/@REPO@/releases/latest/download/install.sh | sh
#
# Сам определяет apk или opkg, системные пакеты берёт из репозитория роутера, программу
# скачивает из GitHub Releases и сверяет контрольную сумму. Модем при установке не трогается.
# Настройки: FM350_BASE_URL откуда качать, FM350_FORCE=1 ставить на неподдерживаемую версию.
set -e

VERSION="@VERSION@"
BASE="${FM350_BASE_URL:-https://github.com/@REPO@/releases/download/v$VERSION}"
TAR="fm350backup-$VERSION.tar.gz"
R="${FM350_ROOT:-}"                # пустой на роутере, папка в автотестах
SHARE="$R/usr/share/fm350backup"
KIT="$R/etc/fm350backup/kit"
MIN=2305                           # 23.05
MAX=2512                           # 25.12
NEED_PYTHON_KB=17000               # Python около 13 МБ, замер на 25.12, остальное запас
NEED_APP_KB=3000                   # программа и файл DA около 2 МБ
REQUIRED="python3-light python3-logging python3-ctypes libusb-1.0-0"
OPTIONAL="kmod-usb-serial-option kmod-usb-storage kmod-fs-vfat kmod-fs-exfat block-mount"

say() { echo "$*"; }
die() { echo "ОШИБКА: $*" >&2; exit 1; }

check_release() {
	[ -r "$R/etc/openwrt_release" ] || die "это не OpenWrt: нет /etc/openwrt_release"
	release=$(sed -n "s/^DISTRIB_RELEASE='\(.*\)'/\1/p" "$R/etc/openwrt_release")
	major=$(echo "$release" | sed -n 's/^\([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\1/p')
	minor=$(echo "$release" | sed -n 's/^\([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\2/p')
	if [ -z "$major" ]; then
		say "ВНИМАНИЕ: OpenWrt $release, такую сборку программа не проверяла."
		return 0
	fi
	number=$((major * 100 + minor))
	if [ "$number" -lt "$MIN" ]; then
		[ -n "$FM350_FORCE" ] || die "OpenWrt $release слишком старый, нужен 23.05 или новее"
		say "ВНИМАНИЕ: OpenWrt $release не поддерживается, продолжаю по FM350_FORCE."
	elif [ "$number" -gt "$MAX" ]; then
		say "ВНИМАНИЕ: OpenWrt $release новее проверенных, продолжаю."
	fi
	say "OpenWrt $release"
}

detect_manager() {
	if command -v apk >/dev/null 2>&1; then
		MANAGER=apk
	elif command -v opkg >/dev/null 2>&1; then
		MANAGER=opkg
	else
		die "нет ни apk, ни opkg"
	fi
	say "Менеджер пакетов: $MANAGER"
}

pkg_update() { if [ "$MANAGER" = apk ]; then apk update; else opkg update; fi; }
pkg_add() { if [ "$MANAGER" = apk ]; then apk add "$@"; else opkg install "$@"; fi; }
pkg_present() {
	if [ "$MANAGER" = apk ]; then
		apk info -e "$1" >/dev/null 2>&1
	else
		opkg status "$1" 2>/dev/null | grep -q 'Status:.* installed'
	fi
}
# запоминаем только то, чего раньше не было: удаление не должно ломать чужое
remember_added() {
	mkdir -p "$R/etc/fm350backup"
	echo "$1" >> "$R/etc/fm350backup/added-packages"
}

check_busy() {
	pid=$(sed -n 1p "$R/tmp/fm350backup/dump.pid" 2>/dev/null || true)
	if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
		die "сейчас снимается дамп, дождись конца"
	fi
}

check_space() {
	need=$NEED_APP_KB
	command -v python3 >/dev/null 2>&1 || need=$((need + NEED_PYTHON_KB))
	free=$(df -k "$R/" | awk 'NR==2 {print $4}')
	[ -z "$free" ] || [ "$free" -ge "$need" ] || die "мало места: свободно $free КБ, нужно $need КБ"
}

fetch() {
	if command -v curl >/dev/null 2>&1; then
		curl -fsSL -o "$2" "$1"
	elif command -v wget >/dev/null 2>&1; then
		wget -q -O "$2" "$1"
	elif command -v uclient-fetch >/dev/null 2>&1; then
		uclient-fetch -q -O "$2" "$1"
	else
		die "нет curl, wget и uclient-fetch"
	fi || die "не удалось скачать $1. Проверь интернет на роутере. Для https нужны пакеты ca-bundle и libustream-mbedtls"
}

download() {
	TMP=$(mktemp -d "${TMPDIR:-/tmp}/fm350-install.XXXXXX")
	trap 'rm -rf "$TMP"' EXIT
	say "Скачиваю FM350 Backup $VERSION"
	fetch "$BASE/$TAR" "$TMP/$TAR"
	fetch "$BASE/SHA256SUMS" "$TMP/SHA256SUMS"
	want=$(awk -v f="$TAR" '$2 == f {print $1}' "$TMP/SHA256SUMS")
	[ -n "$want" ] || die "в SHA256SUMS нет $TAR"
	have=$(sha256sum "$TMP/$TAR" | cut -d' ' -f1)
	[ "$want" = "$have" ] || die "контрольная сумма не совпала, файл повреждён или подменён. Ничего не изменено"
	say "Контрольная сумма совпала"
	mkdir "$TMP/unpacked"
	tar -xzf "$TMP/$TAR" -C "$TMP/unpacked"
	[ -f "$TMP/unpacked/VERSION" ] || die "в архиве нет программы"
}

install_packages() {
	say "Ставлю системные пакеты из репозитория роутера"
	pkg_update || say "ВНИМАНИЕ: не удалось обновить список пакетов"
	missing=""
	for p in $REQUIRED; do
		pkg_present "$p" || missing="$missing $p"
	done
	pkg_add $REQUIRED || die "не удалось поставить $REQUIRED"
	for p in $missing; do
		remember_added "$p"
	done
	for p in $OPTIONAL; do
		was=1
		pkg_present "$p" || was=""
		if pkg_add "$p"; then
			[ -n "$was" ] || remember_added "$p"
		else
			say "ВНИМАНИЕ: нет пакета $p. Без него может не работать флешка или диагностика"
		fi
	done
}

install_app() {
	say "Ставлю программу"
	u="$TMP/unpacked"
	mkdir -p "$SHARE" "$KIT"
	# старые версии держали DA в /usr/share: файлы пользователя переносим, а не удаляем
	if [ -d "$SHARE/kit" ]; then
		for f in "$SHARE"/kit/*; do
			[ -e "$f" ] && mv "$f" "$KIT/"
		done
	fi
	[ ! -d "$u/kit" ] || cp -a "$u"/kit/. "$KIT/"
	rm -rf "$SHARE/pylib" "$SHARE/mtkclient" "$SHARE/kit"
	cp -a "$u/pylib" "$u/mtkclient" "$SHARE/"
	cp "$u/VERSION" "$SHARE/VERSION"
	mkdir -p "$R/usr/bin"
	cp "$u/uninstall.sh" "$R/usr/bin/fm350-uninstall"
	chmod 0755 "$R/usr/bin/fm350-uninstall"
	rm -f "$SHARE/uninstall.sh"
	rm -rf "$R/www/luci-static/resources/view/fm350backup"
	cp -a "$u"/files/. "$R/"
	chmod 0755 "$R/usr/libexec/fm350-backup" "$R/usr/libexec/rpcd/luci.fm350backup"
	conf="$R/etc/sysupgrade.conf"
	touch "$conf"
	sed -i.old -e '/cgi-fm350/d' -e '\#^/usr/share/fm350backup/#d' -e '\#^/etc/fm350backup/#d' "$conf"
	rm -f "$conf.old"
	for f in /usr/bin/fm350-uninstall /usr/libexec/fm350-backup /usr/libexec/rpcd/luci.fm350backup \
		/usr/share/rpcd/acl.d/luci-app-fm350backup.json \
		/usr/share/luci/menu.d/luci-app-fm350backup.json \
		/www/luci-static/resources/view/fm350backup \
		/usr/share/fm350backup /etc/config/fm350backup /etc/fm350backup; do
		grep -qxF "$f" "$conf" || echo "$f" >> "$conf"
	done
	rm -f "$R"/tmp/luci-indexcache* 2>/dev/null || true
}

finish() {
	[ -z "$R" ] || return 0
	/etc/init.d/rpcd restart 2>/dev/null || /etc/init.d/rpcd reload 2>/dev/null || say "ВНИМАНИЕ: не удалось перезапустить rpcd"
	/usr/libexec/fm350-backup status >/dev/null || die "программа поставилась, но не запускается"
	[ -d /www/luci-static ] || say "ВНИМАНИЕ: нет LuCI, страницы программы не будет"
}

check_release
detect_manager
check_busy
check_space
download
[ -n "$FM350_SKIP_PACKAGES" ] || install_packages
install_app
finish

say ""
say "Готово: FM350 Backup $VERSION. Страница: LuCI, Modem, FM350 Backup."
if ! ls "$KIT"/*.bin >/dev/null 2>&1; then
	say "Для работы нужен файл DA из пакета прошивки твоего модема. Его нет в программе: скопируй его на роутер в /etc/fm350backup/kit/"
fi
say "Удалить программу, когда дамп больше не нужен: fm350-uninstall"
