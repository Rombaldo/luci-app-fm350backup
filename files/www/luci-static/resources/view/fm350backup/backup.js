'use strict';
'require view';
'require ui';
'require rpc';

var call = {
	status: rpc.declare({ object: 'luci.fm350backup', method: 'status' }),
	log: rpc.declare({ object: 'luci.fm350backup', method: 'log' }),
	start_dump: rpc.declare({ object: 'luci.fm350backup', method: 'start_dump', params: [ 'path' ] }),
	start_stream: rpc.declare({ object: 'luci.fm350backup', method: 'start_stream' }),
	cancel: rpc.declare({ object: 'luci.fm350backup', method: 'cancel' }),
	delete_backup: rpc.declare({ object: 'luci.fm350backup', method: 'delete_backup', params: [ 'path' ] }),
	download: rpc.declare({ object: 'luci.fm350backup', method: 'download', params: [ 'path' ] }),
	diagnose: rpc.declare({ object: 'luci.fm350backup', method: 'diagnose' }),
	install_da: rpc.declare({ object: 'luci.fm350backup', method: 'install_da', params: [ 'name' ] })
};

var STYLE =
	'.fm{max-width:760px;--fm-line:rgba(128,128,128,.35);--fm-soft:rgba(128,128,128,.12);--fm-muted:#777;--fm-ok:#2e7d32;--fm-warn:#b26a00;--fm-bad:#c62828;--fm-accent:#1f6feb}' +
	'.fm-card{border:1px solid var(--fm-line);border-radius:12px;padding:18px 20px;margin-bottom:14px}' +
	'.fm-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:16px}' +
	'.fm-title{font-size:18px;font-weight:600;margin:0}' +
	'.fm-sub,.fm-k,.fm-hint{color:var(--fm-muted);font-size:12px;margin:0}' +
	'.fm-pill{font-size:12px;padding:3px 10px;border-radius:8px;white-space:nowrap;background:var(--fm-soft)}' +
	'.fm-pill.ok{color:var(--fm-ok)}.fm-pill.warn{color:var(--fm-warn)}.fm-pill.bad{color:var(--fm-bad)}' +
	'.fm-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px 20px}' +
	'.fm-v{font-size:14px;margin:0;overflow-wrap:anywhere}.fm-mono{font-family:monospace;font-size:13px}' +
	'.fm-note{font-size:13px;padding:10px 12px;border-radius:8px;background:var(--fm-soft);margin:14px 0 0}' +
	'.fm-alert{border:2px solid var(--fm-warn);border-radius:12px;padding:18px 20px;margin-bottom:14px;background:var(--fm-soft)}' +
	'.fm-alert b{display:block;font-size:20px;margin-bottom:6px;color:var(--fm-warn)}.fm-alert p{margin:0;font-size:14px}' +
	'.fm-note.warn{color:var(--fm-warn)}.fm-note.bad{color:var(--fm-bad)}.fm-note.ok{color:var(--fm-ok)}' +
	'.fm-opts{display:grid;gap:8px;margin:8px 0 14px}' +
	'.fm-opt{display:block;text-align:left;width:100%;height:auto;background:none;color:inherit;border:1px solid var(--fm-line);border-radius:8px;padding:10px 12px;cursor:pointer;font:inherit}' +
	'.fm-opt.on{border:2px solid var(--fm-accent);padding:9px 11px}.fm-opt[disabled]{cursor:default;opacity:.55}' +
	'.fm-opt b{display:block;font-size:14px;font-weight:600}' +
	'.fm-go{display:block;width:100%;height:44px;font-size:15px;border:0;border-radius:8px;background:var(--fm-accent);color:#fff;cursor:pointer}' +
	'.fm-go[disabled]{opacity:.45;cursor:default}' +
	'.fm-bar{height:8px;border-radius:4px;background:var(--fm-soft);overflow:hidden;margin:8px 0}' +
	'.fm-bar>div{height:100%;background:var(--fm-accent);transition:width .4s}' +
	'.fm-row{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0;border-top:1px solid var(--fm-line)}' +
	'.fm-btns{display:flex;gap:8px;flex-wrap:wrap}' +
	'.fm-log{max-height:260px;overflow:auto;font:12px monospace;white-space:pre-wrap;background:var(--fm-soft);padding:8px;border-radius:8px}' +
	'.fm details summary{cursor:pointer;font-size:13px}.fm-modes{width:100%;font-size:13px}.fm-modes td{padding:3px 8px 3px 0;vertical-align:top;border:0}';

var MODE = {
	working: [ 'ok', 'Модем работает' ],
	fallback: [ 'warn', 'Аварийный режим' ],
	bootloader: [ 'warn', 'Режим загрузчика' ],
	brom: [ 'bad', 'Режим BROM' ],
	none: [ 'bad', 'Модем не найден' ],
	unknown: [ 'warn', 'Неизвестный режим' ]
};

var HINT = {
	fallback: 'Рабочий USB не поднялся, AT-команды недоступны. Дамп снять можно. Если режим не меняется, выключи роутер из розетки на 10 секунд.',
	bootloader: 'Модем остался в загрузчике после дампа. Выключи роутер из розетки на 10 секунд и включи. Если модем в USB-переходнике, достаточно выдернуть и вставить его.',
	brom: 'Самый нижний режим загрузки чипа. Снимать дамп из него эта версия не умеет.',
	none: 'Проверь, что модем установлен, и выключи роутер из розетки на 10 секунд.',
	unknown: 'Модем определился необычно. Выключи роутер из розетки на 10 секунд и проверь снова.'
};

function kv(label, value, mono) {
	return E('div', {}, [
		E('p', { class: 'fm-k' }, label),
		E('p', { class: 'fm-v' + (mono && value ? ' fm-mono' : '') }, value || '—')
	]);
}

function network(c) {
	if (!c.live) return '';
	if (!c.sim) return 'Нет SIM-карты';
	if (!c.operator) return 'Нет регистрации в сети';
	return c.operator + (c.rat ? ', ' + c.rat : '') + (c.signal ? ', сигнал ' + c.signal : '');
}

function usbMode(c) {
	if (!c.dipc) return '';
	return c.dipc_ok ? 'USB, настройка верна' : 'Настроен на PCIe (' + c.dipc + ')';
}

function mb(bytes) { return Math.round((bytes || 0) / 1048576); }

return view.extend({
	handleSaveApply: null,
	handleSave: null,
	handleReset: null,

	dest: 'pc',
	starting: false,
	streamOpened: false,

	load: function () { return call.status(); },

	render: function (st) {
		this.modemBox = E('div', {});
		this.actionBox = E('div', {});
		this.diagBox = E('div', {});
		this.historyBox = E('div', {});
		this.iframe = E('iframe', { style: 'display:none' });
		this.logBox = E('div', { class: 'fm-log' }, 'Журнал появится после запуска.');
		this.details = E('details', { class: 'fm-card' }, [
			E('summary', {}, 'Подробности: журнал и режимы модема'),
			E('p', { class: 'fm-k', style: 'margin:12px 0 6px' }, 'Журнал последнего запуска'),
			this.logBox,
			E('p', { class: 'fm-k', style: 'margin:12px 0 6px' }, 'Режимы модема'),
			E('table', { class: 'fm-modes' }, [
				E('tr', {}, [ E('td', {}, '0e8d:7127'), E('td', {}, 'Рабочий режим') ]),
				E('tr', {}, [ E('td', {}, '0e8d:00ad'), E('td', {}, 'Аварийный режим: рабочий USB не поднялся') ]),
				E('tr', {}, [ E('td', {}, '0e8d:2000'), E('td', {}, 'Загрузчик: так модем выглядит во время и после дампа') ]),
				E('tr', {}, [ E('td', {}, '0e8d:0003'), E('td', {}, 'BROM: память модема не загружается') ])
			])
		]);
		var root = E('div', { class: 'fm' }, [ E('style', {}, STYLE), this.modemBox, this.actionBox, this.diagBox, this.historyBox, this.details, this.iframe ]);
		this.update(st);
		this.tick();
		return root;
	},

	tick: function () {
		var self = this;
		window.setTimeout(function () {
			var jobs = [ call.status().then(function (st) { self.update(st); }) ];
			if (self.details.open)
				jobs.push(call.log().then(function (l) { if (l && l.dump) self.logBox.textContent = l.dump; }));
			Promise.all(jobs).catch(function () {}).then(function () { self.tick(); });
		}, 2000);
	},

	update: function (st) {
		if (!st || st.error) return;
		this.st = st;
		var self = this, last = st.last || {};
		// запуск завершён, когда роутер сообщил о новой работе, даже если она сразу закончилась ошибкой
		if (st.running || (last.started && last.started !== this.startedBefore)) this.starting = false;
		var active = st.running || this.starting;

		if (active && last.dest === 'pc' && last.phase === 'stream-ready' && !this.streamOpened)
			this.openStream(last);

		// страница опрашивает роутер каждые 2 с: перестраиваем только то, что изменилось,
		// иначе закрываются раскрытые списки и пропадает выделение
		this.paint(this.modemBox, [ st.mode, st.pid, st.version, st.card, st.running ], function () { return [ self.modemCard(st) ]; });
		this.paint(this.actionBox, active
			? [ 'run', last.message, last.done, last.total, last.dest, this.streamUrl ]
			: [ 'idle', last.phase, last.message, last.outdir, last.started, this.dismissed, this.dest, st.drives, st.ready, st.mode, st.das, this.daMessage ],
			function () {
				if (active) return (last.action === 'replug' ? [ self.alertCard('Выдерни и вставь модем',
					'Выдерни модем или USB-переходник с ним, подожди 2–3 секунды и вставь обратно. На это есть примерно 3 минуты, дальше программа продолжит сама.') ] : []).concat([ self.progressCard(last) ]);
				var c = [];
				// только пока модем и правда в загрузчике: итог прошлого дампа хранится и после переподключения
				if (last.finished && last.phase === 'done' && st.mode === 'bootloader')
					c.push(self.alertCard('Дамп готов. Верни модем в работу',
						'Модем остался в режиме загрузчика. Выключи роутер из розетки на 10 секунд и включи. Если модем в USB-переходнике, достаточно выдернуть и вставить переходник.'));
				if (last.finished && last.started !== self.dismissed) c.push(self.resultCard(last));
				c.push(self.startCard(st));
				c.push(self.daCard(st));
				return c;
			});
		this.paint(this.diagBox, [ this.diag, this.diagBusy, active ], function () { return [ self.diagCard(st, active) ]; });
		this.paint(this.historyBox, st.backups, function () { var h = self.historyCard(st); return h ? [ h ] : []; });
	},

	paint: function (box, state, build) {
		var key = JSON.stringify(state);
		if (box.fmKey === key) return;
		box.fmKey = key;
		while (box.firstChild) box.removeChild(box.firstChild);
		build().forEach(function (c) { box.appendChild(c); });
	},

	modemCard: function (st) {
		var c = st.card || {}, m = MODE[st.mode] || MODE.unknown, kids = [
			E('div', { class: 'fm-head' }, [
				E('div', {}, [
					E('p', { class: 'fm-title' }, 'FM350 Backup'),
					E('p', { class: 'fm-sub' }, 'Полная копия памяти модема · только чтение · версия ' + st.version)
				]),
				E('span', { class: 'fm-pill ' + m[0] }, m[1])
			]),
			E('div', { class: 'fm-grid' }, [
				kv('Модем', (c.model || 'FM350-GL') + (st.pid ? ', USB 0e8d:' + st.pid : '')),
				kv('IMEI', c.imei, true),
				kv('Серийный номер', c.serial, true),
				kv('Прошивка', c.firmware, true),
				kv('ID чипа', c.me_id || (st.mode === 'working' ? 'Появится после первого дампа' : ''), !!c.me_id),
				kv('Память', 'NAND 511 МБ, 40 разделов'),
				kv('Сеть', network(c)),
				kv('Режим USB', usbMode(c)),
				kv('Температура', c.temp_c ? c.temp_c + ' °C' : '')
			])
		];
		if (!c.live && (c.imei || c.firmware))
			kids.push(E('p', { class: 'fm-hint', style: 'margin-top:10px' }, 'IMEI и прошивка запомнены с прошлого раза: сейчас модем не отвечает на запросы.'));
		if (HINT[st.mode] && !st.running)
			kids.push(E('p', { class: 'fm-note ' + (st.mode === 'brom' || st.mode === 'none' ? 'bad' : 'warn') }, HINT[st.mode]));
		if (c.dipc && !c.dipc_ok)
			kids.push(E('p', { class: 'fm-note warn' }, 'Модем настроен на PCIe. В слоте только с USB его порты могут пропасть.'));
		if (c.temp_c >= 80)
			kids.push(E('p', { class: 'fm-note bad' }, 'Модем перегрет: нужен радиатор и хорошее питание.'));
		return E('div', { class: 'fm-card' }, kids);
	},

	startCard: function (st) {
		var self = this, drives = st.drives || [], can = st.ready && (st.mode === 'working' || st.mode === 'fallback');
		var usable = drives.filter(function (d) { return d.writable && d.free_mb >= 1100; });
		if (this.dest !== 'pc' && !usable.some(function (d) { return d.path === self.dest; })) this.dest = 'pc';

		function opt(id, title, hint, disabled) {
			return E('button', {
				class: 'fm-opt' + (self.dest === id ? ' on' : ''), disabled: disabled ? 'disabled' : null,
				click: function () { self.dest = id; self.update(self.st); }
			}, [ E('b', {}, title), E('span', { class: 'fm-hint' }, hint) ]);
		}

		var opts = [ opt('pc', 'На этот компьютер', 'Скачивается архивом, в нём файлы для сборки полного дампа на Windows, macOS и Linux. На роутере места не занимает') ];
		drives.forEach(function (d) {
			var ok = usable.indexOf(d) >= 0;
			opts.push(opt(d.path, 'На флешку ' + d.path + ', ' + (d.free_mb / 1024).toFixed(1).replace('.', ',') + ' ГБ свободно',
				!d.writable ? 'Открыта только для чтения' : ok ? 'Разделы и готовый образ full_dump.img' : 'Мало места: нужно около 1,1 ГБ', !ok));
		});
		if (!drives.length)
			opts.push(E('p', { class: 'fm-hint' }, 'Вставь флешку, если нужен готовый образ full_dump.img. Она появится здесь сама.'));

		return E('div', { class: 'fm-card' }, [
			E('p', { class: 'fm-k' }, 'Куда сохранить'),
			E('div', { class: 'fm-opts' }, opts),
			st.da_count ? '' : E('p', { class: 'fm-note bad' }, 'Нет файла DA: без него модем не прочитать. Загрузи его кнопкой ниже.'),
			E('button', {
				class: 'fm-go', disabled: can ? null : 'disabled',
				click: function () { self.start(); }
			}, 'Снять полный дамп'),
			E('p', { class: 'fm-hint', style: 'text-align:center;margin-top:8px' },
				(this.dest === 'pc' ? 'Около 3 минут' : 'Около 7 минут') + '. Модем на это время отключится от сети, а потом нужно будет выключить роутер из розетки на 10 секунд или переподключить USB-переходник')
		]);
	},

	daCard: function (st) {
		var self = this, das = st.das || [];
		return E('div', { class: 'fm-card' }, [
			E('div', { class: 'fm-head', style: 'margin-bottom:8px' }, [
				E('p', { class: 'fm-k' }, 'Файлы DA'),
				E('button', { class: 'cbi-button', click: function () { self.uploadDa(); } }, 'Загрузить файл DA')
			]),
			E('p', { class: 'fm-hint' }, das.length
				? das.join(', ')
				: 'Файл DA берётся из пакета прошивки твоего модема, обычно download_agent/DA_BR.bin. В программе его нет.'),
			this.daMessage ? E('p', { class: 'fm-note ' + this.daMessage[0] }, this.daMessage[1]) : ''
		]);
	},

	uploadDa: function () {
		var self = this;
		ui.uploadFile('/tmp/fm350backup-da.upload').then(function (r) {
			return call.install_da(r.name);
		}).then(function (r) {
			self.daMessage = r && r.ok ? [ 'ok', 'Файл ' + r.name + ' готов к работе.' ]
				: [ 'bad', (r && r.error) || 'Роутер не ответил.' ];
			return call.status();
		}).then(function (st) {
			self.update(st);
		}).catch(function (e) {
			// закрытое окно выбора файла это не ошибка
			if (e && e.message === _('Upload has been cancelled')) return;
			self.daMessage = [ 'bad', 'Не удалось загрузить файл: ' + (e && e.message || e) ];
			self.update(self.st);
		});
	},

	speedLine: function (last) {
		var now = Date.now() / 1000, done = last.done || 0;
		if (!this.first && done > 0) this.first = { t: now, done: done };
		var text = mb(done) + ' из ' + mb(last.total) + ' МБ';
		if (this.first && now - this.first.t > 3) {
			var v = (done - this.first.done) / (now - this.first.t);
			if (v > 0)
				text += ' · ' + (v / 1048576).toFixed(1).replace('.', ',') + ' МБ/с · осталось около ' +
					Math.ceil((last.total - done) / v / 60) + ' мин';
		}
		return text;
	},

	alertCard: function (title, text) {
		return E('div', { class: 'fm-alert', role: 'alert' }, [ E('b', {}, title), E('p', {}, text) ]);
	},

	progressCard: function (last) {
		var pct = last.total ? Math.min(100, Math.floor(100 * (last.done || 0) / last.total)) : 0;
		var kids = [
			E('div', { style: 'display:flex;justify-content:space-between' }, [
				E('p', { class: 'fm-v', style: 'font-weight:600' }, last.message || 'Подготовка'),
				E('p', { class: 'fm-v' }, pct + '%')
			]),
			E('div', { class: 'fm-bar' }, [ E('div', { style: 'width:' + pct + '%' }) ]),
			E('p', { class: 'fm-hint' }, this.speedLine(last) + '. Не закрывай страницу и не выключай роутер')
		];
		if (last.dest === 'pc' && this.streamUrl)
			kids.push(E('p', { class: 'fm-hint', style: 'margin-top:8px' }, [
				'Скачивание не началось? ', E('a', { href: this.streamUrl, target: '_blank' }, 'Начать вручную') ]));
		kids.push(E('div', { class: 'fm-btns', style: 'margin-top:12px' }, [
			E('button', { class: 'cbi-button cbi-button-negative', click: function () { call.cancel(); } }, 'Остановить')
		]));
		return E('div', { class: 'fm-card' }, kids);
	},

	resultCard: function (last) {
		var self = this, ok = last.phase === 'done' && last.complete !== false && last.pmt_real !== false;
		// что делать с модемом говорит отдельная табличка, и только когда это нужно
		var text = (last.message || '').split(' Чтобы модем снова заработал')[0];
		var when = last.started ? new Date(last.started * 1000).toLocaleString() + '. ' : '';
		var kids = [ E('p', { class: 'fm-note ' + (ok ? 'ok' : 'bad'), style: 'margin:0' }, (ok ? 'Прошлый дамп, ' + when : '') + text) ];
		if (ok && last.dest === 'usb' && last.outdir)
			kids.push(E('p', { class: 'fm-hint', style: 'margin-top:8px' }, 'Папка: ' + last.outdir));
		if (ok && last.dest === 'pc')
			kids.push(E('p', { class: 'fm-hint', style: 'margin-top:8px' }, 'Распакуй архив и запусти файл для своей системы: он соберёт полный дамп full_dump.img. Подробности в ПРОЧТИ.txt внутри архива.'));
		kids.push(E('div', { class: 'fm-btns', style: 'margin-top:10px' }, [
			E('button', { class: 'cbi-button', click: function () { self.dismissed = last.started; self.update(self.st); } }, 'Скрыть')
		]));
		return E('div', { class: 'fm-card' }, kids);
	},

	diagCard: function (st, active) {
		var self = this, d = this.diag, kids = [
			E('div', { class: 'fm-head', style: 'margin-bottom:8px' }, [
				E('p', { class: 'fm-k' }, 'Диагностика модема'),
				E('button', { class: 'cbi-button', disabled: (active || this.diagBusy) ? 'disabled' : null,
					click: function () { self.runDiag(); } }, this.diagBusy ? 'Проверяю…' : 'Проверить модем')
			])
		];
		if (!d) {
			kids.push(E('p', { class: 'fm-hint' }, 'Покажет, что не так и что делать: SIM, сеть, сигнал, антенны, FCC-блокировка, настройка USB, температура. Только чтение.'));
			return E('div', { class: 'fm-card' }, kids);
		}
		if (d.error) {
			kids.push(E('p', { class: 'fm-note bad' }, d.error));
			return E('div', { class: 'fm-card' }, kids);
		}
		var cls = { bad: 'bad', warn: 'warn', ok: 'ok', info: '' };
		d.findings.forEach(function (f) {
			var box = [ E('b', {}, f.title) ];
			if (f.detail) box.push(E('div', { style: 'color:inherit;opacity:.85;margin-top:2px' }, f.detail));
			if (f.action) box.push(E('div', { style: 'margin-top:2px' }, f.action));
			kids.push(E('div', { class: 'fm-note ' + cls[f.level], style: 'margin:8px 0 0' }, box));
		});
		if (d.values.length)
			kids.push(E('details', { style: 'margin-top:12px', open: this.valuesOpen ? 'open' : null,
				toggle: function (ev) { self.valuesOpen = ev.target.open; } }, [
				E('summary', {}, 'Все показатели'),
				E('table', { class: 'fm-modes' }, d.values.map(function (v) {
					return E('tr', {}, [ E('td', {}, v.name), E('td', { class: 'fm-mono' }, v.value) ]);
				}))
			]));
		return E('div', { class: 'fm-card' }, kids);
	},

	runDiag: function () {
		var self = this;
		this.diagBusy = true;
		this.update(this.st);
		call.diagnose().then(function (r) {
			self.diag = r;
		}).catch(function (e) {
			self.diag = { error: 'Проверка не удалась: ' + e.message };
		}).then(function () {
			self.diagBusy = false;
			self.update(self.st);
		});
	},

	historyCard: function (st) {
		var self = this, list = st.backups || [];
		if (!list.length) return null;
		var rows = list.map(function (b) {
			return E('div', { class: 'fm-row' }, [
				E('div', {}, [
					E('p', { class: 'fm-v' }, b.created || b.name),
					E('p', { class: 'fm-hint' }, b.path + ' · ' + b.size_mb + ' МБ' + (b.complete === false ? ' · неполный' : b.has_image ? ' · есть образ' : ''))
				]),
				E('div', { class: 'fm-btns' }, [
					E('button', { class: 'cbi-button', click: function () { self.download(b); } }, 'Скачать'),
					E('button', { class: 'cbi-button cbi-button-negative', click: function () { self.remove(b); } }, 'Удалить')
				])
			]);
		});
		return E('div', { class: 'fm-card' }, [ E('p', { class: 'fm-k', style: 'margin-bottom:8px' }, 'Сохранённые дампы') ].concat(rows));
	},

	start: function () {
		var self = this, dest = this.dest;
		this.first = null;
		this.streamOpened = false;
		this.streamUrl = null;
		this.starting = true;
		this.startedBefore = (this.st.last || {}).started;
		this.st.last = { phase: 'prepare', message: 'Подготовка', dest: dest === 'pc' ? 'pc' : 'usb' };
		this.update(this.st);
		var run = dest === 'pc' ? call.start_stream() : call.start_dump(dest);
		run.catch(function (e) {
			self.starting = false;
			ui.addNotification(null, E('p', {}, 'Не удалось запустить: ' + e.message));
		});
	},

	fileUrl: function (name, port, token) {
		return 'http://' + window.location.hostname + ':' + port + '/' + name + '?t=' + token;
	},

	openStream: function (last) {
		this.streamOpened = true;
		this.streamUrl = this.fileUrl(last.stream_name, last.stream_port, last.stream_token);
		this.iframe.src = this.streamUrl;
	},

	download: function (b) {
		var self = this;
		call.download(b.path).then(function (r) {
			if (!r || r.error) throw new Error(r ? r.error : 'нет ответа');
			self.iframe.src = self.fileUrl(r.name, r.port, r.token);
		}).catch(function (e) {
			ui.addNotification(null, E('p', {}, 'Не удалось начать скачивание: ' + e.message));
		});
	},

	remove: function (b) {
		ui.showModal('Удалить этот дамп?', [
			E('p', {}, b.path),
			E('p', {}, 'Сначала убедись, что копия есть на компьютере. Отменить удаление нельзя.'),
			E('div', { class: 'right' }, [
				E('button', { class: 'cbi-button', click: ui.hideModal }, 'Отмена'), ' ',
				E('button', { class: 'cbi-button cbi-button-negative', click: function () {
					ui.hideModal();
					call.delete_backup(b.path).then(function (r) {
						if (r && r.error) ui.addNotification(null, E('p', {}, 'Не удалось удалить: ' + r.error));
					});
				} }, 'Удалить')
			])
		]);
	}
});
