#!/bin/bash
# Проверки без роутера и модема: синтаксис всех частей и автотесты. Запускать перед каждой сборкой.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
JSC=/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc
PAGE=files/www/luci-static/resources/view/fm350backup/backup.js
# файлы LuCI выполняются как тело функции, поэтому return на верхнем уровне допустим
if [ -x "$JSC" ]; then
  "$JSC" -e "new Function(read(\"$PAGE\"))"
else
  node -e "new Function(require('fs').readFileSync('$PAGE', 'utf8'))"
fi
for f in files/etc/config/fm350backup files/usr/share/luci/menu.d/*.json files/usr/share/rpcd/acl.d/*.json; do
  case "$f" in *.json) python3 -m json.tool "$f" >/dev/null ;; esac
done
for f in install.sh uninstall.sh files/usr/libexec/rpcd/luci.fm350backup scripts/*.sh; do
  case "$(head -1 "$f")" in
    *python*) ;;
    *bash*) bash -n "$f" ;;
    *) sh -n "$f" ;;
  esac
done
echo "Проверки пройдены."
