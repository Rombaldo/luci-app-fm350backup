"""Диагностика модема Fibocom FM350-GL. Один и тот же файл в программе для Mac и в приложении роутера.

Только чтение: COMMANDS содержит лишь запросы состояния, настройки модема они не меняют. Транспорт
(USB на Mac, tty на роутере) снаружи: сюда приходит словарь {команда: ответ}. У каждого вывода есть
источник: мануал AT V2.10, сообщение темы 4PDA или проверенный случай. Подробно: docs/diagnostics-sources.md.
"""
import re

COMMANDS = ["ATI", "AT+GTPKGVER?", "AT+CGSN", "AT+CFSN", "AT+CFUN?", "AT+CPIN?", "AT+SIMTYPE?", "AT+GTDUALSIM?",
            "AT+CSQ", "AT+COPS?", "AT+CREG?", "AT+CGREG?", "AT+CEREG?", "AT+CGATT?", "AT+CGPADDR=1", "AT+CGDCONT?",
            "AT+GTCCINFO?", "AT+GTCAINFO?", "AT+GTUSBMODE?", "AT+GTDIPCMODE?", "AT+GTFCCLOCKMODE?",
            "AT+GTFCCLOCKSTATE?", "AT+GTFCCEFFSTATUS?", "AT+GTSENRDTEMP=1", "AT+GTRXPATHEN?", "AT+GTCURCAR?", "AT+CEER"]

OPERATORS = {"25001": "МТС", "25002": "MegaFon", "25011": "Yota", "25020": "T2", "25099": "Билайн"}
RAT = {"0": "2G", "2": "3G", "7": "LTE", "11": "5G", "12": "5G", "13": "LTE + 5G"}
REG_OK = {"1", "5"}
LEVELS = ("ok", "info", "warn", "bad")
MODE_BY_PID = {"7127": "working", "7126": "working", "00ad": "fallback", "2000": "bootloader", "2001": "bootloader", "0003": "brom"}
MANUAL = "мануал AT V2.10"


def _first(pattern, text, default=None):
    m = re.search(pattern, text or "")
    return m.group(1).strip() if m else default


def band_name(code):
    """Код диапазона из мануала: 103 = LTE B3, 5078 = NR n78."""
    code = str(code)
    if code.startswith("50") and len(code) > 2:
        return "n" + code[2:]
    if len(code) == 3 and code.startswith("1"):
        return "B%d" % int(code[1:])
    return code


# Диапазоны LTE по номеру частоты EARFCN (3GPP TS 36.101): в простое модем не называет band в +GTCCINFO
EARFCN_BANDS = ((0, 599, 1), (600, 1199, 2), (1200, 1949, 3), (1950, 2399, 4), (2400, 2649, 5), (2750, 3449, 7),
                (3450, 3799, 8), (6150, 6449, 20), (9210, 9659, 28), (37750, 38249, 38), (38650, 39649, 40), (39650, 41589, 41))


def band_from_earfcn(v):
    for low, high, band in EARFCN_BANDS:
        if v is not None and low <= v <= high:
            return "B%d" % band
    return None


def _num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _serving(text):
    """Обслуживающие соты из +GTCCINFO: LTE и, при EN-DC, NR (поля по мануалу, раздел 11.1.15)."""
    cells = []
    for line in (text or "").splitlines():
        f = [x.strip() for x in re.sub(r"^\s*\+GTCCINFO:\s*", "", line).split(",")]
        if len(f) < 14 or f[0] != "1" or f[1] not in ("4", "9"):
            continue
        nr = f[1] == "9"
        rsrp, rsrq, snr, bw = _num(f[12]), _num(f[13]), _num(f[10]), _num(f[9])
        cells.append({
            "rat": "5G" if nr else "LTE", "band": band_name(f[8]) if f[8] else (None if nr else band_from_earfcn(_num(f[6]))), "cell": f[5], "tac": f[4], "pci": f[7],
            "mhz": bw // 5 if bw else None,
            "rsrp": None if rsrp in (None, 255) else rsrp - (157 if nr else 141),
            "rsrq": None if rsrq in (None, 255) or (not nr and rsrq > 46) else rsrq / 2 - (43.5 if nr else 20),
            # LTE: rssnr с шагом 0,5 дБ; NR: шкала ss_sinr из +CESQ
            "sinr": None if snr in (None, 255) else (snr / 2 - 23 if nr else snr / 2),
        })
    return cells


def _carriers(text):
    """Несущие из +GTCAINFO: основная и активные дополнительные."""
    bands, off = [], []
    for line in (text or "").replace("：", ":").splitlines():
        m = re.match(r"\s*(?:\+GTCAINFO:\s*)?(PCC|SCC\d*)\s*:\s*(.+)", line)
        if not m:
            continue
        f = [x.strip() for x in m.group(2).split(",")]
        if m.group(1) == "PCC":
            bands.append(band_name(f[0]))
        elif len(f) > 2 and f[2]:
            (bands if f[0] == "2" else off).append(band_name(f[2]))
    return bands, off


def parse(r):
    """Значения из ответов модема. Пустое значение означает, что модем не ответил или команды нет."""
    g = lambda c: r.get(c, "") or ""
    m = {"answered": any(("OK" in v or "ERROR" in v or "+" in v) for v in r.values() if v)}
    m["model"] = _first(r"Model:\s*(\S+)", g("ATI"))
    m["firmware"] = _first(r'"([^"]+)"', g("AT+GTPKGVER?"))
    m["imei"] = _first(r"\b(\d{15})\b", g("AT+CGSN"))
    m["serial"] = _first(r'\+CFSN:\s*"([^"]*)"', g("AT+CFSN")) or None
    m["cfun"] = _first(r"\+CFUN:\s*(\d+)", g("AT+CFUN?"))
    m["cpin"] = _first(r"\+CPIN:\s*([A-Z0-9 ]+)", g("AT+CPIN?"))
    m["simtype"] = _first(r"\+SIMTYPE:\s*(\d)", g("AT+SIMTYPE?"))
    m["simslot"] = _first(r"\+GTDUALSIM\s*:\s*(\d)", g("AT+GTDUALSIM?"))
    csq = _first(r"\+CSQ:\s*(\d+)", g("AT+CSQ"))
    m["csq"] = None if csq in (None, "99") else int(csq)
    cops = re.search(r'\+COPS:\s*\d+(?:,\d+,"([^"]+)"(?:,(\d+))?)?', g("AT+COPS?"))
    m["plmn"] = cops.group(1) if cops else None
    m["operator"] = OPERATORS.get(m["plmn"], m["plmn"])
    m["rat"] = RAT.get(cops.group(2)) if cops and cops.group(2) else None
    m["creg"] = _first(r"\+CREG:\s*\d+,\s*(\d+)", g("AT+CREG?"))
    m["cgreg"] = _first(r"\+CGREG:\s*\d+,\s*(\d+)", g("AT+CGREG?"))
    m["cereg"] = _first(r"\+CEREG:\s*\d+,\s*(\d+)", g("AT+CEREG?"))
    m["attached"] = _first(r"\+CGATT:\s*(\d)", g("AT+CGATT?"))
    addr = re.findall(r'\+CGPADDR:\s*(\d+),\s*"?([0-9A-Fa-f.:]+)"?', g("AT+CGPADDR=1"))
    m["ip"] = next((a for _, a in addr if a.strip("0.:")), None)
    m["ip_known"] = "OK" in g("AT+CGPADDR=1")     # ERROR значит только то, что адрес не удалось спросить
    m["apn"] = _first(r'\+CGDCONT:\s*\d+,\s*"[^"]*",\s*"([^"]*)"', g("AT+CGDCONT?")) or None
    m["cells"] = _serving(g("AT+GTCCINFO?"))
    m["bands"], m["bands_off"] = _carriers(g("AT+GTCAINFO?"))
    m["usbmode"] = _first(r"\+GTUSBMODE:\s*(\d+)", g("AT+GTUSBMODE?"))
    dipc = _first(r"\+GTDIPCMODE:\s*([\d, ]+)", g("AT+GTDIPCMODE?"))
    m["dipc"] = dipc.replace(" ", "") if dipc else None
    m["fcc_mode"] = _first(r"\+GTFCCLOCKMODE:\s*(\d)", g("AT+GTFCCLOCKMODE?"))
    m["fcc_state"] = _first(r"\+GTFCCLOCKSTATE:\s*(\d)", g("AT+GTFCCLOCKSTATE?"))
    m["fcc_eff"] = _first(r"\+GTFCCEFFSTATUS:\s*(\d+,\s*\d+)", g("AT+GTFCCEFFSTATUS?"))
    t = _first(r"\+GTSENRDTEMP:\s*\d+,\s*(-?\d+)", g("AT+GTSENRDTEMP=1"))
    m["temp_c"] = round(int(t) / 1000) if t else None
    m["rx_lte"] = _first(r"\+GTRXPATHEN\s*:\s*3,\s*(\d+)", g("AT+GTRXPATHEN?"))
    m["carrier"] = _first(r'\+GTCURCAR:\s*\d+,\s*[“"]([^”"]*)[”"]', g("AT+GTCURCAR?")) or None
    m["ceer"] = _first(r'\+CEER:\s*(.+)', g("AT+CEER"))
    return m


def rate_rsrp(v):
    return None if v is None else "отличный" if v >= -85 else "хороший" if v >= -95 else "средний" if v >= -105 \
        else "слабый" if v >= -115 else "очень слабый"


def rate_sinr(v):
    return None if v is None else "отличный" if v >= 20 else "хороший" if v >= 13 else "средний" if v >= 3 \
        else "слабый" if v >= 0 else "очень слабый"


def _f(level, title, detail="", action="", source=""):
    return {"level": level, "title": title, "detail": detail, "action": action, "source": source}


POWER = "Выключи роутер из розетки на 10 секунд и включи."

MODE_FINDINGS = {
    "bootloader": _f("warn", "Модем в режиме загрузчика", "USB 0e8d:2000. Так бывает после дампа. Если он только мигает "
                     "в этом режиме и пропадает, чаще всего виновато питание.", POWER, "проверенный случай, 4PDA #9805, #9831"),
    "fallback": _f("bad", "Аварийный режим", "USB 0e8d:00ad: рабочий USB не поднялся, AT-команды недоступны. Частая причина: "
                   "модем настроен на PCIe, а слот подключён только по USB.", "Сними дамп, затем полностью обесточь модем и проверь снова.",
                   "проверенный случай, 4PDA #9143"),
    "brom": _f("bad", "Режим BROM", "USB 0e8d:0003: загрузчик в памяти не запускается, часто из-за повреждённого preloader.",
               "Нужно восстановление через SP Flash Tool на Windows.", "4PDA #1663, #3965"),
    "none": _f("bad", "Модем не виден на USB", "Он не определился совсем. В журнале роутера это выглядит как ошибки -110 и -62. Помогает "
               "переустановка модема и полное обесточивание.", "Проверь установку в слот и питание, затем обесточь полностью.",
               "проверенный случай"),
}


def findings(m, usb_resets=0, program_reboots=0):
    """Выводы по значениям из parse(). usb_resets: сколько раз модем отваливался от USB, если это известно."""
    out = []
    add = lambda *a, **k: out.append(_f(*a, **k))
    if not m["imei"]:
        add("bad", "Нет IMEI", "Модем не сообщает IMEI. Обычно это след форматирования памяти при прошивке.",
            "Лучше всего вернуть полный дамп этого же модема.", "4PDA #10390, #10580")
    if not m["serial"]:
        add("warn", "Нет серийного номера", "Серийный номер стёрт. Часто он пропадает вместе с IMEI, модем может перезагружаться по кругу.",
            "Лучше всего вернуть полный дамп этого же модема.", "4PDA #10577, #10580")

    fcc = m["fcc_mode"] not in (None, "0") and m["fcc_state"] == "0"
    if fcc:
        add("bad", "FCC-блокировка", "Модем заблокирован для радио: GTFCCLOCKMODE %s, состояние 0. Встречается у модемов из ноутбуков."
            % m["fcc_mode"], "Как её снять, описано в теме FM350-GL на 4PDA. Программа это не делает: это меняет настройку модема.",
            "%s, раздел 17; 4PDA #1608, #3304" % MANUAL)
    if m["cfun"] not in (None, "1"):
        add("bad" if not fcc else "info", "Радио выключено", "CFUN %s, рабочее значение 1." % m["cfun"],
            "Перезапусти модем. Если не помогло, смотри другие пункты: FCC, IMEI.", "мануал AT V2.10")

    sim_ok = m["cpin"] == "READY"
    if m["cpin"] is None:
        add("bad", "SIM-карта не видна", "Модем не видит SIM. Если модем подключён через переходник без SIM, это нормально, сеть в нём и не нужна.",
            "Проверь, что SIM вставлена в активный слот. Модем отвечает слот %s." % m["simslot"] if m["simslot"] else
            "Проверь, что SIM вставлена до конца.", "4PDA #2373, #3045")
    elif not sim_ok:
        add("bad", "SIM не готова: " + m["cpin"], "SIM требует код или заблокирована.", "Проверь SIM в телефоне.", MANUAL)
    if m["simtype"] == "1":
        add("warn", "Активна eSIM", "Модем сейчас работает с eSIM, а не с физической картой.",
            "Если ты вставил обычную SIM, на 4PDA переключают слот командой GTDUALSIM. Программа её не выполняет.", "4PDA #8974, #10175")

    reg = [m["cereg"], m["cgreg"], m["creg"]]
    registered = any(x in REG_OK for x in reg[:2]) or (reg[2] in REG_OK and not any(reg[:2]))
    cell = m["cells"][0] if m["cells"] else {}
    if sim_ok and not fcc and m["cfun"] in (None, "1"):
        if "3" in reg[:2]:
            add("bad", "Сеть отказала в регистрации", "Статус регистрации 3. Сеть видна, но не пускает эту SIM.",
                "Проверь SIM и тариф в телефоне, а также IMEI.", MANUAL)
        elif not registered:
            ceer = m["ceer"] if m["ceer"] and "NONE" not in m["ceer"] else None
            add("bad", "Нет регистрации в сети", "Модем не зарегистрирован, статус %s.%s" % (
                m["cereg"] or m["cgreg"] or "неизвестен", " Причина от модема: %s." % ceer if ceer else ""),
                "Проверь антенны: такие показания бывают, когда не подключены кабели.", "проверенный случай")

    if registered and m["ip_known"] and not m["ip"]:
        add("warn", "Сеть есть, IP-адреса нет", "Зарегистрирован, но передача данных не поднята. APN: %s." % (m["apn"] or "не задан"),
            "Проверь APN и настройку интерфейса на роутере.", MANUAL)

    rsrp, sinr = cell.get("rsrp"), cell.get("sinr")
    if rsrp is not None:
        lvl = "ok" if rsrp >= -105 else "warn" if rsrp >= -115 else "bad"
        add(lvl, "Сигнал: %s" % rate_rsrp(rsrp), "RSRP %d дБм%s." % (rsrp, ", SINR %s дБ (%s)" % (_db(sinr), rate_sinr(sinr)) if sinr is not None else ""),
            "" if lvl == "ok" else "Проверь антенны и их кабели, попробуй другое место.", "общепринятая шкала RSRP")
    elif registered and m["csq"] is not None and m["csq"] < 10:
        add("warn", "Слабый сигнал", "CSQ %d." % m["csq"], "Проверь антенны.", MANUAL)
    if m["rx_lte"] not in (None, "15"):
        add("warn", "Отключены приёмные тракты", "GTRXPATHEN LTE %s, полный приём 4x4 это 15." % m["rx_lte"],
            "Если подключены четыре антенны, значение стоит вернуть. Программа его не меняет.", "4PDA #3294, #9724")

    if m["bands"]:
        n = len(m["bands"])
        add("ok" if n > 1 else "info", "Агрегация: %s" % (" + ".join(m["bands"]) if n > 1 else "нет, работает одна несущая " + m["bands"][0]),
            "Настроены, но не активны: %s." % ", ".join(m["bands_off"]) if m["bands_off"] else "", "", MANUAL)

    if m["dipc"]:
        f = m["dipc"].split(",")
        if f[0] in ("1", "2") or (len(f) > 3 and f[3] == "2"):
            add("bad", "Модем настроен на PCIe", "GTDIPCMODE %s. В слоте только с USB порты могут не появиться, модем уходит в аварийный режим." % m["dipc"],
                "Если модем в USB-слоте, нужна настройка 3,1,1,1,3,15. Сначала сними дамп.", "%s, раздел 13.1.3; проверенный случай; 4PDA #7043" % MANUAL)
        else:
            add("ok", "Настройка USB верна", "GTDIPCMODE %s." % m["dipc"], "", "проверенный случай")
    if m["usbmode"] not in (None, "41"):
        add("warn", "Необычный режим USB", "GTUSBMODE %s, обычное значение 41. После режима 40 у людей оставались только служебные порты." % m["usbmode"],
            "Проверь, все ли порты видны.", "%s, раздел 13.1.1; 4PDA #9534" % MANUAL)

    t = m["temp_c"]
    if t is not None:
        if t >= 80:
            add("bad", "Перегрев: %d °C" % t, "Обычно 40–45 °C и 50–60 °C под нагрузкой. Выше 80 °C падает скорость, модем может перезагружаться.",
                "Нужен радиатор и обдув.", "4PDA #10733, #10320")
        elif t >= 65:
            add("warn", "Модем горячий: %d °C" % t, "Обычно 40–45 °C и 50–60 °C под нагрузкой.", "Поставь радиатор.", "4PDA #10733, #9337")
        else:
            add("ok", "Температура в норме: %d °C" % t, "", "", "4PDA #10733")
    if usb_resets >= 3:                # один-два обрыва дают обычный запуск модема и старт роутера
        add("warn", "Модем отваливался от USB: %d раз" % usb_resets, "Такие обрывы часто связаны с нехваткой питания, особенно при регистрации в сети.",
            "Проверь блок питания роутера или дай модему отдельное питание.", "4PDA #9831, #9834, #10704")

    if program_reboots:
        add("info", "Модем перезагружала программа на роутере: %d раз" % program_reboots,
            "Это сторож пакета 5gmodem: он лечит модем перезагрузкой, когда нет сети. Модем при этом на время пропадает с USB. Без антенн это ожидаемо, с питанием и модемом это не связано.")

    if m["operator"] and m["carrier"] and m["carrier"].lower() not in ("", "generic", "default") and \
            m["operator"].lower() not in m["carrier"].lower() and m["carrier"].lower() not in m["operator"].lower():
        add("info", "Профиль оператора: " + m["carrier"], "Сейчас сеть %s. На работу это обычно не влияет." % m["operator"], "", MANUAL)
    if not any(x["level"] in ("warn", "bad") for x in out):
        out.insert(0, _f("ok", "Проблем не найдено", "Проверены SIM, сеть, сигнал, настройка USB, FCC и температура.", "", ""))
    order = {"bad": 0, "warn": 1, "info": 2, "ok": 3}
    return sorted(out, key=lambda x: order[x["level"]])


def _db(v):
    return ("%.1f" % v).rstrip("0").rstrip(".").replace(".", ",")


def _dipc_label(dipc):
    if not dipc:
        return None
    first = dipc.split(",")[0]
    return "%s, %s" % (dipc, {"1": "настроен на PCIe", "2": "только PCIe", "3": "работает и по USB"}.get(first, "неизвестная настройка"))


def values(m):
    """Показатели для таблицы: [(название, значение)]. Пустые не показываются."""
    cell = m["cells"][0] if m["cells"] else {}
    nr = next((c for c in m["cells"] if c["rat"] == "5G"), None)
    rows = [("Модель", m["model"]), ("IMEI", m["imei"]), ("Серийный номер", m["serial"]), ("Прошивка", m["firmware"]),
            ("SIM", {"READY": "Готова"}.get(m["cpin"], m["cpin"])),
            ("Тип SIM", {"0": "Обычная", "1": "eSIM"}.get(m["simtype"])),
            ("Оператор", m["operator"]), ("Сеть", m["rat"]),
            ("Диапазон", cell.get("band")), ("Ширина канала", "%d МГц" % cell["mhz"] if cell.get("mhz") else None),
            ("RSRP", "%d дБм" % cell["rsrp"] if cell.get("rsrp") is not None else None),
            ("RSRQ", "%s дБ" % _db(cell["rsrq"]) if cell.get("rsrq") is not None else None),
            ("SINR", "%s дБ" % _db(cell["sinr"]) if cell.get("sinr") is not None else None),
            ("Соты 5G", "%s, RSRP %s дБм" % (nr["band"], nr["rsrp"]) if nr else None),
            ("Несущие", " + ".join(m["bands"]) if m["bands"] else None),
            ("APN", m["apn"]), ("IP-адрес", m["ip"]),
            ("Температура", "%d °C" % m["temp_c"] if m["temp_c"] is not None else None),
            ("Приёмные тракты LTE", {"15": "4 из 4"}.get(m["rx_lte"], m["rx_lte"])),
            ("Режим USB", {"41": "41, обычный рабочий режим", "40": "40, без части служебных портов"}.get(m["usbmode"], m["usbmode"])),
            ("Настройка USB/PCIe", _dipc_label(m["dipc"])),
            ("FCC-блокировка", {"0": "Нет"}.get(m["fcc_mode"], "Режим " + m["fcc_mode"] if m["fcc_mode"] else None))]
    return [{"name": n, "value": v} for n, v in rows if v]


def diagnose(mode, responses=None, usb_resets=0, program_reboots=0, rebooting_now=False):
    """Полный отчёт. mode: working, fallback, bootloader, brom, none. Без ответов AT судим только по режиму USB."""
    if mode == "none" and rebooting_now:
        f = _f("info", "Модем перезагружается", "Его только что перезагрузил сторож пакета 5gmodem, потому что нет сети. Это не поломка.",
               "Повтори проверку через минуту.")
        return {"level": f["level"], "findings": [f], "values": []}
    if mode != "working" or not responses:
        f = MODE_FINDINGS.get(mode) or _f("bad", "Модем не отвечает на AT-команды", "USB видит рабочий режим, но порт команд молчит.",
                                          POWER, "проверенный случай")
        return {"level": f["level"], "findings": [f], "values": []}
    m = parse(responses)
    if not m["answered"]:
        return diagnose("silent")
    fs = findings(m, usb_resets, program_reboots)
    return {"level": max((x["level"] for x in fs), key=LEVELS.index), "findings": fs, "values": values(m)}
