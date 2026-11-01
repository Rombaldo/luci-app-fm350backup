# Что изменено в mtkclient

`third_party/mtkclient` основан на [mtkclient](https://github.com/bkerler/mtkclient) (B. Kerler), лицензия GPLv3, текст в `third_party/mtkclient/LICENSE`. Изменённая версия распространяется на тех же условиях.

## Правки поведения

- Настройка DA как у SPFT (`FM350_RUNTIME_PARAMETER`), без неё чтение в 6 раз медленнее.
- Нет запроса `DA.SLA` для чипа `0x992`: модем не отвечает, пауза 107 с.
- `FM350_QUEUE` ограничивает очередь при потоковой выдаче, `FM350_PARTTBL` сохраняет таблицу разделов.

## Что убрано

Остались только соединение с модемом, загрузка штатного DA и чтение (`ro`, `multi`).

- Чужие DA (`Loader`), окно, файлы для Windows, примеры, служебное.
- `Exploit`, `pltools`, `exploit_handler`, `payloads`, правки DA и загрузчика (`extension`, `patch_preloader_*`): приёмы обхода защиты не запускаются и в программе их нет.
- Другие форматы DA: `xflash`, `legacy`. Поддерживается только XML DA.
- `Filesystem`, `meta`, `Hardware`, `mtk_crypto`, `cryptutils`, `mtk_api`, `mtk_tcpip_*`, `stage2`.
- Все команды записи, стирания и разблокировки: `w`, `wf`, `wl`, `wo`, `e`, `es`, `ess`, `seccfg` и другие, а также их обмен с DA.
