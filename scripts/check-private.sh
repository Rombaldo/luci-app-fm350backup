#!/bin/bash
# Не пускает в сборку личные данные.
#   check-private.sh <папка или архив>   проверить папку или содержимое архива
#   check-private.sh --before            проверить исходники
#
# Значения читаются из файла вне репозитория, в git их нет:
#   ~/.fm350-private    по одному значению в строке (IMEI, серийный номер, ID чипа, пароль, почта)
# Без него проверки нет, поэтому сборка останавливается. Только на GitHub Actions (CI=true) идёт одна
# проверка по общим шаблонам: номера вроде IMEI, почта. Значений там нет, и это слабее настоящей
# проверки, поэтому релиз перед публикацией проверяется на своём компьютере.
set -euo pipefail
cd "$(dirname "$0")/.."
LIST="$HOME/.fm350-private"
if [ "$1" = "--before" ]; then
  # всё, что в git: забытый в корне файл уйдёт в публикацию так же, как код
  TARGETS=()
  while IFS= read -r f; do TARGETS+=("$f"); done < <(git ls-files)
else
  TARGETS=("$1")
fi
TMP=""
trap '[ -z "$TMP" ] || rm -rf "$TMP"' EXIT
if [ -f "${TARGETS[0]}" ] && case "${TARGETS[0]}" in *.tar.gz) true;; *) false;; esac; then
  TMP="$(mktemp -d)"
  tar -xzf "${TARGETS[0]}" -C "$TMP"
  TARGETS=("$TMP")
fi
found=0
python3 scripts/check-patterns.py "${TARGETS[@]}" || found=1
if [ -f "$LIST" ]; then
  if grep -rliaF -f "$LIST" --exclude=check-private.sh --exclude-dir=__pycache__ "${TARGETS[@]}"; then found=1; fi
elif [ "${CI:-}" = "true" ]; then
  echo "ПРЕДУПРЕЖДЕНИЕ: нет $LIST, проверены только общие шаблоны"
else
  echo "ОШИБКА: нет $LIST, проверить личные данные нечем"
  exit 1
fi
if [ "$found" = 1 ]; then echo "ОШИБКА: в файлах выше найдены личные данные"; exit 1; fi
echo "Личных данных не найдено."
