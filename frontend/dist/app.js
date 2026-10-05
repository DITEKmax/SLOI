"use strict";
class SignalField {
    constructor(canvas, state) {
        this.width = 1;
        this.height = 1;
        this.frame = 0;
        this.reduced = matchMedia('(prefers-reduced-motion: reduce)');
        this.dead = false;
        this.force = true;
        this.lastSignature = '';
        this.xs = new Float32Array(53);
        this.ys = new Float32Array(53);
        this.visibilityChanged = () => {
            this.stopScheduled();
            if (!document.hidden) {
                this.force = true;
                this.schedule(0);
            }
        };
        this.motionChanged = () => { this.stopScheduled(); this.lastSignature = ''; this.refresh(); };
        this.tick = (now) => {
            this.frame = 0;
            if (this.dead || document.hidden || !this.context)
                return;
            const snapshot = this.state();
            if (this.reduced.matches) {
                // No animation under reduced motion: redraw only when visible data changes.
                const signature = [snapshot.theme, snapshot.accent, snapshot.progress, snapshot.active, this.width, this.height, snapshot.map.join(',')].join('|');
                if (this.force || signature !== this.lastSignature) {
                    this.draw(0, snapshot);
                    this.lastSignature = signature;
                }
            }
            else
                this.draw(now / 1000, snapshot);
            this.force = false;
            // Idle visuals use eight frames per second; active processing retains 30 fps.
            // Hidden pages schedule nothing, and reduced motion needs only a light fallback check.
            this.schedule(this.reduced.matches ? 500 : snapshot.active ? 1000 / 30 : 125);
        };
        this.canvas = canvas;
        this.context = canvas.getContext('2d', { alpha: true });
        this.state = state;
        this.observer = new ResizeObserver(() => this.resize());
        this.observer.observe(canvas);
        document.addEventListener('visibilitychange', this.visibilityChanged);
        this.reduced.addEventListener('change', this.motionChanged);
        this.resize();
        this.schedule(0);
    }
    resize() {
        const rect = this.canvas.getBoundingClientRect(), width = Math.max(1, rect.width), height = Math.max(1, rect.height);
        const dpr = Math.min(devicePixelRatio, 1.5), pixelsW = Math.round(width * dpr), pixelsH = Math.round(height * dpr);
        if (this.canvas.width === pixelsW && this.canvas.height === pixelsH && this.width === width && this.height === height)
            return;
        this.width = width;
        this.height = height;
        this.canvas.width = pixelsW;
        this.canvas.height = pixelsH;
        this.context?.setTransform(dpr, 0, 0, dpr, 0, 0);
        this.refresh();
    }
    // State changes can request an immediate static redraw without enabling motion.
    refresh() { this.force = true; if (!this.dead && !document.hidden)
        this.schedule(0); }
    stopScheduled() { window.clearTimeout(this.timer); this.timer = undefined; if (this.frame)
        cancelAnimationFrame(this.frame); this.frame = 0; }
    schedule(delay) {
        if (this.dead || document.hidden || !this.context)
            return;
        if (this.frame)
            return;
        window.clearTimeout(this.timer);
        this.timer = window.setTimeout(() => { this.timer = undefined; this.frame = requestAnimationFrame(this.tick); }, delay);
    }
    draw(time, { theme, accent, progress, active, map }) {
        const ctx = this.context;
        if (!ctx)
            return;
        const w = this.width, h = this.height;
        ctx.clearRect(0, 0, w, h);
        const paper = theme === 'paper', signal = theme === 'signal';
        const phase = active ? time * .28 : time * .045;
        const fraction = progress == null ? .38 : Math.max(0, Math.min(1, progress / 100));
        const rows = paper ? 19 : signal ? 30 : 26, cols = signal ? 53 : 48;
        const tint = paper ? '#817e72' : signal ? '#a5a0ba' : '#758078', left = w * .04, right = w * .97;
        ctx.lineCap = paper ? 'butt' : 'round';
        for (let row = 0; row < rows; row++) {
            const rowFrac = row / (rows - 1);
            ctx.beginPath();
            for (let col = 0; col < cols; col++) {
                const t = col / (cols - 1), data = map.length ? map[Math.min(map.length - 1, Math.floor(t * map.length))] : .52;
                const envelope = Math.pow(Math.sin(t * Math.PI), .75);
                const warp = Math.sin(t * 6.3 + rowFrac * 3 + phase) * Math.sin(rowFrac * Math.PI), fold = Math.cos(t * 4.8 - rowFrac * 4.2 + phase * .4);
                const x = left + (right - left) * t + Math.sin(rowFrac * 3.3 + t * 4 + phase * .2) * w * .025;
                const y = h * .5 + (rowFrac - .5) * h * .49 + envelope * (warp * h * .145 + fold * h * .06) * (0.65 + data * .35);
                this.xs[col] = x;
                this.ys[col] = y;
                if (col === 0)
                    ctx.moveTo(x, y);
                else
                    ctx.lineTo(x, y);
            }
            ctx.strokeStyle = tint;
            ctx.globalAlpha = paper ? .19 : signal ? .12 : .19;
            ctx.lineWidth = paper ? .55 : .65;
            ctx.stroke();
            for (let col = 0; col < cols; col++) {
                const t = col / (cols - 1), processed = t < fraction;
                ctx.fillStyle = processed ? accent : tint;
                ctx.globalAlpha = processed ? .9 : .5;
                if (paper)
                    ctx.fillRect(this.xs[col], this.ys[col], 2.3, 1);
                else {
                    const radius = signal ? 1.05 + Math.pow(Math.sin(t * Math.PI), .75) * 1.05 : .95;
                    ctx.beginPath();
                    ctx.arc(this.xs[col], this.ys[col], radius, 0, Math.PI * 2);
                    ctx.fill();
                }
            }
        }
        if (signal) {
            ctx.globalAlpha = .1;
            ctx.strokeStyle = accent;
            ctx.lineWidth = 1;
            for (let i = 0; i < 3; i++) {
                ctx.beginPath();
                ctx.ellipse(w * .5, h * .53, w * (.24 + i * .06), h * (.26 + i * .01), -.23, 0, Math.PI * 2);
                ctx.stroke();
            }
        }
        ctx.globalAlpha = 1;
        if (active && progress !== null) {
            const x = left + (right - left) * fraction;
            ctx.strokeStyle = accent;
            ctx.globalAlpha = .3;
            ctx.setLineDash([2, 6]);
            ctx.beginPath();
            ctx.moveTo(x, h * .18);
            ctx.lineTo(x, h * .83);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.globalAlpha = 1;
            ctx.fillStyle = accent;
            ctx.fillRect(x - 2, h * .83, 4, 4);
        }
    }
    destroy() { this.dead = true; this.stopScheduled(); this.observer.disconnect(); document.removeEventListener('visibilitychange', this.visibilityChanged); this.reduced.removeEventListener('change', this.motionChanged); }
}
const themes = {
    carbon: { name: 'CARBON', description: 'Точный измерительный инструмент', accent: '#c6f36b', presets: ['#c6f36b', '#6fbcff', '#ff925c', '#c4a1ff', '#f07b87'] },
    paper: { name: 'PAPER', description: 'Типографика, чернила и воздух', accent: '#b74326', presets: ['#b74326', '#2a4ca6', '#287258', '#724e9f', '#206c7b'] },
    signal: { name: 'SIGNAL', description: 'Кинетическая структура сигнала', accent: '#a798ff', presets: ['#a798ff', '#81d8ff', '#ff9ad4', '#d1f476', '#ffb272'] }
};
Vue.createApp({ render: SloiRender, setup() {
        const { ref, reactive, computed, onMounted, onBeforeUnmount, watch, nextTick } = Vue;
        const state = reactive({ version: '1.0.0-rc1', queue: { jobs: [], active_id: null, running: false, pause_after_current: false }, telemetry: {}, models: [], native_available: false });
        const connected = ref(false), appearance = ref(false), error = ref(''), info = ref(''), busyNative = ref(false), dropHover = ref(false), dragJob = ref(''), selectedId = ref(''), follow = ref(true), pending = reactive(new Set());
        const theme = ref('carbon'), accent = ref(themes.carbon.accent), defaultModel = ref('whisper'), defaultLanguage = ref('auto'), fieldCanvas = ref(null), fileInput = ref(null);
        const previewDialog = ref(null), cancelDialog = ref(null), previewJob = ref(null), previewText = ref(''), previewLoading = ref(false), previewError = ref(''), cancelId = ref('');
        const upload = reactive({ busy: false, name: '', index: 0, total: 0, percent: 0, phase: '', cancelled: false });
        const extensions = new Set('wav mp3 m4a aac flac ogg opus wma mp4 mov mkv webm avi m4v aiff aif mka mpga'.split(' '));
        let csrf = '', socket = null, retryTimer, pollTimer, saveTimer, noticeTimer, stopped = false, initialized = false, booting = false, field = null, xhr = null, dragDepth = 0, previewVersion = 0, lastFocus = null;
        const allJobs = computed(() => state.queue.jobs), active = computed(() => state.queue.jobs.find((j) => j.id === state.queue.active_id) || null);
        const selected = computed(() => !follow.value && state.queue.jobs.find((j) => j.id === selectedId.value) || active.value || state.queue.jobs.find((j) => j.id === selectedId.value) || [...state.queue.jobs].reverse().find((j) => j.status === 'COMPLETE') || state.queue.jobs[0] || null);
        const waiting = computed(() => allJobs.value.filter((j) => j.status === 'WAITING')), completed = computed(() => allJobs.value.filter((j) => j.status === 'COMPLETE'));
        const percentage = computed(() => selected.value && ['TRANSCRIBING', 'FINALIZING', 'COMPLETE'].includes(selected.value.status) ? selected.value.progress : null);
        const anyInstalled = computed(() => state.models.some((m) => m.installed)), waitingInstalled = computed(() => waiting.value.every((j) => state.models.find((m) => m.id === j.model)?.installed));
        const defaultInstalled = computed(() => !!state.models.find((m) => m.id === defaultModel.value)?.installed);
        const themeList = Object.entries(themes).map(([id, t]) => ({ id, ...t })), presets = computed(() => themes[theme.value].presets);
        const totalDuration = computed(() => waiting.value.reduce((a, j) => a + (j.duration || 0), 0));
        const isProcessing = (job) => !!job && ['PREPARING', 'LOADING_MODEL', 'ANALYSING', 'TRANSCRIBING', 'FINALIZING'].includes(job.status);
        const isRecoverable = (job) => ['FAILED', 'CANCELLED', 'INTERRUPTED', 'SOURCE_MISSING'].includes(job.status);
        const statusText = (status) => ({ WAITING: 'В очереди', PREPARING: 'Подготовка', ANALYSING: 'Анализ речи', LOADING_MODEL: 'Загрузка модели', TRANSCRIBING: 'Распознавание', FINALIZING: 'Сохранение текста', COMPLETE: 'Готово', FAILED: 'Ошибка', CANCELLED: 'Отменено', INTERRUPTED: 'Прервано', SOURCE_MISSING: 'Исходник недоступен' }[status || ''] || 'Готов к работе');
        const stageDescription = computed(() => ({ WAITING: 'Проверьте модель и язык записи, затем запустите очередь.', PREPARING: 'Читаем аудиодорожку. Исходный файл остаётся без изменений.', LOADING_MODEL: 'Первый запуск модели может занять больше времени. Следующие записи используют её повторно.', ANALYSING: 'Находим участки речи. Процент распознавания появится на следующем этапе.', TRANSCRIBING: 'Процент показывает обработанную речь. Очередь продолжает работать при закрытой вкладке.', FINALIZING: 'Собираем текст и сохраняем Markdown.', COMPLETE: 'Текст сохранён. Откройте его здесь или скачайте Markdown.', FAILED: 'Проверьте причину ниже. Повторный запуск начнёт эту запись сначала.', CANCELLED: 'Обработка остановлена. Запись можно повторно добавить в очередь.', INTERRUPTED: 'Приложение было закрыто во время обработки. Добавьте запись в очередь повторно.', SOURCE_MISSING: 'Найдите исходный файл, чтобы продолжить.' }[selected.value?.status || ''] || 'Добавьте аудио или видео. Выберите модель и язык, затем запустите очередь.'));
        const startReason = computed(() => !connected.value ? 'Ожидаем связь с приложением.' : !waitingInstalled.value ? 'Для части очереди не установлена модель. Измените её в строке записи или запустите install.bat.' : !waiting.value.length && !active.value ? 'Добавьте записи или повторите прерванную задачу.' : '');
        const progressCaption = computed(() => selected.value?.status === 'COMPLETE' ? 'РАСШИФРОВКА ГОТОВА' : selected.value?.status === 'ANALYSING' ? 'АНАЛИЗ РЕЧИ' : selected.value?.status === 'LOADING_MODEL' ? 'ЗАГРУЗКА МОДЕЛИ' : 'РАСПОЗНАНО');
        const time = (v) => { if (v == null || !Number.isFinite(v))
            return '—:—'; const s = Math.max(0, Math.floor(v)); return (s >= 3600 ? Math.floor(s / 3600) + ':' : '') + String(Math.floor(s / 60) % 60).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); };
        const metric = (v, d = 1) => v == null || !Number.isFinite(v) ? '—' : v.toFixed(d), gb = (v, d = 2) => metric(v == null ? null : v / 1024, d), ratio = (a, b) => a != null && b ? Math.max(0, Math.min(100, a / b * 100)) : 0;
        const size = (b) => b >= 1024 ** 3 ? (b / 1024 ** 3).toFixed(2) + ' ГБ' : (b / 1024 ** 2).toFixed(1) + ' МБ';
        const languageText = (l) => l === 'ru' ? 'Русский' : l === 'en' ? 'Английский' : 'Автоопределение';
        const modelName = (id) => state.models.find((m) => m.id === id)?.name || id;
        const trackLabel = (t) => ['Дорожка ' + t.index, t.title, t.language, t.channels ? t.channels + ' кан.' : null, t.default ? 'по умолчанию' : null].filter(Boolean).join(' · ');
        const spark = (key, max, w = 300, h = 35) => { const hist = state.telemetry.history || []; if (!hist.some((r) => r[key] != null))
            return ''; let down = false; return hist.map((r, i) => { if (r[key] == null) {
            down = false;
            return '';
        } const x = i / Math.max(1, hist.length - 1) * w, y = h - 2 - Math.min(1, Math.max(0, r[key] / max)) * (h - 4); const a = (down ? 'L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1); down = true; return a; }).join(' '); };
        function applyTheme() { document.documentElement.dataset.theme = theme.value; document.documentElement.style.setProperty('--accent', accent.value); const rgb = accent.value.match(/\w\w/g)?.map((v) => parseInt(v, 16)) || [190, 240, 90]; const lum = rgb.map((v) => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }), l = .2126 * lum[0] + .7152 * lum[1] + .0722 * lum[2]; document.documentElement.style.setProperty('--on-accent', l > .179 ? '#10120f' : '#ffffff'); const bg = theme.value === 'paper' ? .857 : theme.value === 'signal' ? .0075 : .0076, contrast = (Math.max(l, bg) + .05) / (Math.min(l, bg) + .05); document.documentElement.style.setProperty('--accent-ink', contrast < 4.5 ? (theme.value === 'paper' ? '#242824' : '#edeff0') : accent.value); field?.refresh(); }
        function notify(message) { info.value = message; window.clearTimeout(noticeTimer); noticeTimer = window.setTimeout(() => { info.value = ''; }, 9000); }
        async function api(path, method = 'GET', data) { const r = await fetch(path, { method, headers: { ...(data !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(method === 'GET' ? {} : { 'X-Sloi-Csrf': csrf }) }, body: data === undefined ? undefined : JSON.stringify(data) }); if (!r.ok) {
            let detail = {};
            try {
                detail = await r.json();
            }
            catch { }
            ;
            if (r.status === 401) {
                connected.value = false;
                void bootstrap();
            }
            throw new Error(detail.message || (r.status === 422 ? 'Проверьте параметры записи и повторите действие.' : 'Ошибка запроса ' + r.status));
        } return r.headers.get('content-type')?.includes('application/json') ? await r.json() : null; }
        function accept(data) { state.version = data.version; state.queue = data.queue; state.telemetry = data.telemetry; state.models = data.models; state.native_available = data.native_available; connected.value = true; if (!initialized) {
            theme.value = data.preferences.theme;
            accent.value = data.preferences.accent;
            defaultModel.value = data.defaults.model;
            defaultLanguage.value = data.defaults.language;
            initialized = true;
            applyTheme();
        } }
        async function refresh() { try {
            accept(await api('/api/state'));
            return true;
        }
        catch {
            connected.value = false;
            return false;
        } }
        async function execute(key, work) { if (pending.has(key))
            return; pending.add(key); try {
            error.value = '';
            await work();
            await refresh();
        }
        catch (e) {
            error.value = e instanceof Error ? e.message : String(e);
            await refresh();
        }
        finally {
            pending.delete(key);
        } }
        function connect() { if (stopped || socket?.readyState === WebSocket.OPEN)
            return; socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`); socket.onmessage = e => { try {
            accept(JSON.parse(e.data));
        }
        catch {
            error.value = 'Не удалось обновить состояние. Переподключаемся.';
            socket?.close();
        } }; socket.onclose = () => { connected.value = false; if (!stopped)
            retryTimer = window.setTimeout(bootstrap, 1800); }; socket.onerror = () => socket?.close(); }
        async function bootstrap() { if (stopped || booting)
            return; booting = true; window.clearTimeout(retryTimer); try {
            const s = await api('/api/session');
            csrf = s.csrf;
            if (await refresh())
                connect();
            else
                retryTimer = window.setTimeout(bootstrap, 2200);
        }
        catch {
            connected.value = false;
            if (!stopped)
                retryTimer = window.setTimeout(bootstrap, 2200);
        }
        finally {
            booting = false;
        } }
        function persistPreferences() { applyTheme(); window.clearTimeout(saveTimer); if (!initialized)
            return; saveTimer = window.setTimeout(() => execute('preferences', () => api('/api/preferences', 'PUT', { theme: theme.value, accent: accent.value, default_model: defaultModel.value, default_language: defaultLanguage.value })), 400); }
        function chooseTheme(id) { theme.value = id; accent.value = themes[id].accent; persistPreferences(); }
        function setAccent(v) { if (/^#[0-9a-f]{6}$/i.test(v)) {
            accent.value = v;
            persistPreferences();
        } }
        async function addSources(sources) { if (!sources.length)
            return; const data = await api('/api/jobs', 'POST', { source_ids: sources.map(s => s.id), model: defaultModel.value, language: defaultModel.value === 'gigaam' && defaultLanguage.value === 'en' ? 'ru' : defaultLanguage.value }); if (!active.value) {
            selectedId.value = data.job_ids?.[0] || '';
            follow.value = false;
        } }
        async function nativeFiles(mode) { if (busyNative.value || !connected.value || !state.native_available)
            return; busyNative.value = true; await execute('native', async () => { try {
            const d = await api('/api/native/' + mode, 'POST');
            await addSources(d.sources || []);
            if (d.errors?.length)
                error.value = d.errors.map((e) => e.name + ': ' + e.message).join('\n');
            if (d.sources?.length)
                notify('Добавлено без копии: ' + d.sources.length + '. Проверьте настройки и запустите очередь.');
        }
        finally {
            busyNative.value = false;
        } }); }
        function pickBrowser() { fileInput.value?.click(); }
        function inputFiles(event) { const input = event.target; void uploadFiles(Array.from(input.files || [])); input.value = ''; }
        function sendFile(file, model, language) { return new Promise((resolve, reject) => { const request = new XMLHttpRequest(); xhr = request; request.open('POST', '/api/files/upload?name=' + encodeURIComponent(file.name) + '&model=' + encodeURIComponent(model) + '&language=' + language); request.setRequestHeader('X-Sloi-Csrf', csrf); request.setRequestHeader('Content-Type', 'application/octet-stream'); request.upload.onprogress = e => { if (e.lengthComputable) {
            upload.percent = Math.min(100, e.loaded / e.total * 100);
            if (e.loaded === e.total)
                upload.phase = 'Проверяем запись…';
        } }; request.onload = () => { xhr = null; let d = {}; try {
            d = JSON.parse(request.responseText);
        }
        catch { } ; request.status >= 200 && request.status < 300 ? resolve(d) : reject(new Error(d.message || 'Не удалось добавить файл: ' + request.status)); }; request.onerror = () => { xhr = null; reject(new Error('Перенос прервался. Проверьте связь с приложением.')); }; request.onabort = () => { xhr = null; reject(new Error('Перенос отменён.')); }; request.send(file); }); }
        async function uploadFiles(files) { if (!files.length)
            return; if (upload.busy) {
            notify('Дождитесь завершения переноса или отмените его.');
            return;
        } if (!connected.value) {
            error.value = 'Дождитесь подключения к приложению.';
            return;
        } if (!defaultInstalled.value) {
            error.value = 'Выберите установленную модель для новых файлов.';
            return;
        } const valid = files.filter(f => extensions.has(f.name.split('.').pop()?.toLowerCase() || '')); const rejected = files.length - valid.length; if (!valid.length) {
            error.value = 'Выберите аудио или видео: MP3, WAV, M4A, FLAC, MP4, MOV, MKV или WEBM.';
            return;
        } upload.busy = true; upload.total = valid.length; upload.cancelled = false; error.value = ''; const model = defaultModel.value, lang = defaultLanguage.value; let added = 0, failures = []; try {
            for (let i = 0; i < valid.length && !upload.cancelled; i++) {
                upload.index = i + 1;
                upload.name = valid[i].name;
                upload.percent = 0;
                upload.phase = 'Переносим во временную папку…';
                try {
                    const d = await sendFile(valid[i], model, lang);
                    added++;
                    if (!active.value) {
                        selectedId.value = d.job_id;
                        follow.value = false;
                    }
                    await refresh();
                }
                catch (e) {
                    if (!upload.cancelled)
                        failures.push(valid[i].name + ': ' + (e instanceof Error ? e.message : String(e)));
                }
            }
        }
        finally {
            upload.busy = false;
            xhr = null;
            await refresh();
            if (failures.length)
                error.value = failures.join('\n');
            notify((added ? 'Добавлено: ' + added + '. ' : '') + (upload.cancelled ? 'Перенос остановлен. Уже добавленные записи остались в очереди.' : rejected ? 'Пропущено неподдерживаемых файлов: ' + rejected + '.' : 'Проверьте настройки и запустите очередь.'));
        } }
        function cancelUpload() { upload.cancelled = true; xhr?.abort(); }
        function onDragEnter(e) { if (!dragJob.value && e.dataTransfer?.types.includes('Files')) {
            dragDepth++;
            dropHover.value = true;
        } }
        function onDragOver(e) { if (!dragJob.value && e.dataTransfer?.types.includes('Files')) {
            if (e.dataTransfer)
                e.dataTransfer.dropEffect = 'copy';
            dropHover.value = true;
        } }
        function onDragLeave() { if (dragJob.value)
            return; dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth)
            dropHover.value = false; }
        function onDrop(e) { dragDepth = 0; dropHover.value = false; if (dragJob.value)
            return; void uploadFiles(Array.from(e.dataTransfer?.files || [])); }
        const changeModel = (j, m) => execute(j.id, () => api('/api/jobs/' + j.id, 'PUT', { model: m, language: m === 'gigaam' && j.language === 'en' ? 'ru' : j.language }));
        const changeLanguage = (j, l) => execute(j.id, () => api('/api/jobs/' + j.id, 'PUT', { model: j.model, language: l }));
        const changeTrack = (j, index) => execute(j.id, () => api('/api/jobs/' + j.id, 'PUT', { model: j.model, language: j.language, audio_stream_index: Number(index) }));
        const applyDefaults = () => execute('batch', async () => { for (const job of [...waiting.value])
            await api('/api/jobs/' + job.id, 'PUT', { model: defaultModel.value, language: defaultLanguage.value }); notify('Модель и язык применены к ожидающим записям.'); });
        const removeJob = (j) => execute(j.id, () => api('/api/jobs/' + j.id, 'DELETE'));
        const retryJob = (j) => execute(j.id, async () => { await api('/api/jobs/' + j.id + '/retry', 'POST'); notify('Запись возвращена в очередь.' + (state.queue.running && !state.queue.pause_after_current ? ' Она начнётся по порядку.' : ' Нажмите «Запустить очередь».')); });
        const queueAction = (action) => execute('queue', () => api('/api/queue/' + action, 'POST'));
        async function cancelCurrent() { if (!active.value || active.value.cancelling || active.value.status === 'FINALIZING')
            return; cancelId.value = active.value.id; lastFocus = document.activeElement; await nextTick(); cancelDialog.value?.showModal(); }
        function closeDialog(which) { (which === 'cancel' ? cancelDialog.value : previewDialog.value)?.close(); }
        function restoreFocus() { lastFocus?.focus(); lastFocus = null; }
        async function confirmCancel() { closeDialog('cancel'); if (active.value?.id !== cancelId.value || active.value?.status === 'FINALIZING') {
            notify('Эта запись уже завершилась.');
            return;
        } await queueAction('cancel'); }
        async function moveJob(j, dir) { const ids = waiting.value.map((x) => x.id), i = ids.indexOf(j.id), to = i + dir; if (i < 0 || to < 0 || to >= ids.length)
            return; [ids[i], ids[to]] = [ids[to], ids[i]]; await execute('order', () => api('/api/queue/order', 'PUT', { ids })); }
        function rowDragStart(e, j) { if (j.status !== 'WAITING' || !connected.value || pending.has('order')) {
            e.preventDefault();
            return;
        } dragJob.value = j.id; e.dataTransfer?.setData('text/plain', j.id); if (e.dataTransfer)
            e.dataTransfer.effectAllowed = 'move'; }
        async function rowDrop(j, e) { if (e.dataTransfer?.types.includes('Files')) {
            onDrop(e);
            return;
        } const ids = waiting.value.map((x) => x.id), from = ids.indexOf(dragJob.value), to = ids.indexOf(j.id); dragJob.value = ''; if (from < 0 || to < 0 || from === to)
            return; ids.splice(to, 0, ids.splice(from, 1)[0]); await execute('order', () => api('/api/queue/order', 'PUT', { ids })); }
        function selectJob(j) { selectedId.value = j.id; follow.value = false; }
        function followActive() { follow.value = true; }
        function download(j) { const a = document.createElement('a'); a.href = '/api/results/' + j.id + '/download'; a.click(); }
        function downloadAll() { const a = document.createElement('a'); a.href = '/api/results.zip'; a.click(); }
        const reveal = (j) => execute(j.id, () => api('/api/results/' + j.id + '/reveal', 'POST'));
        const copyText = (j) => execute('copy-' + j.id, async () => { const d = await api('/api/results/' + j.id + '/text'); try {
            await navigator.clipboard.writeText(d.text);
            notify('Текст скопирован без метаданных.');
        }
        catch {
            await openPreview(j);
            notify('Выделите текст в окне результата и скопируйте его вручную.');
        } });
        async function loadPreview() { if (!previewJob.value)
            return; const id = previewJob.value.id, version = ++previewVersion; previewLoading.value = true; previewError.value = ''; try {
            const d = await api('/api/results/' + id + '/text');
            if (version === previewVersion)
                previewText.value = d.text;
        }
        catch (e) {
            if (version === previewVersion)
                previewError.value = e instanceof Error ? e.message : String(e);
        }
        finally {
            if (version === previewVersion)
                previewLoading.value = false;
        } }
        async function openPreview(j) { lastFocus = document.activeElement; previewJob.value = j; previewText.value = ''; await nextTick(); if (!previewDialog.value?.open)
            previewDialog.value?.showModal(); await loadPreview(); }
        const locate = (j) => { if (busyNative.value || !state.native_available)
            return; busyNative.value = true; return execute(j.id, async () => { try {
            const d = await api('/api/native/picker', 'POST');
            if (!d.sources?.length)
                return;
            if (d.sources.length !== 1) {
                notify('Для замены исходника выберите один файл.');
                return;
            }
            await api('/api/jobs/' + j.id + '/relocate', 'POST', { source_id: d.sources[0].id });
            await api('/api/jobs/' + j.id + '/retry', 'POST');
            notify('Исходник найден. Запись возвращена в очередь.');
        }
        finally {
            busyNative.value = false;
        } }); };
        function dismissAppearance(e) { if (!e.target?.closest('.appearance-panel,.appearance-button'))
            appearance.value = false; }
        function escape(e) { if (e.key === 'Escape')
            appearance.value = false; }
        watch(defaultModel, (id) => { if (id === 'gigaam' && defaultLanguage.value === 'en')
            defaultLanguage.value = 'ru'; persistPreferences(); });
        watch(defaultLanguage, () => persistPreferences());
        onMounted(async () => { applyTheme(); await nextTick(); if (fieldCanvas.value)
            field = new SignalField(fieldCanvas.value, () => ({ theme: theme.value, accent: accent.value, progress: percentage.value, active: isProcessing(selected.value), map: selected.value?.speech_map || [], gpu: state.telemetry.gpu_utilization_pct })); void bootstrap(); pollTimer = window.setInterval(() => { if (!socket || socket.readyState !== WebSocket.OPEN)
            void refresh(); }, 6000); document.addEventListener('click', dismissAppearance); document.addEventListener('keydown', escape); });
        onBeforeUnmount(() => { stopped = true; [retryTimer, saveTimer, noticeTimer].forEach(t => window.clearTimeout(t)); window.clearInterval(pollTimer); socket?.close(); xhr?.abort(); field?.destroy(); document.removeEventListener('click', dismissAppearance); document.removeEventListener('keydown', escape); });
        return { selectJob, followActive, theme, accent, themeList, presets, appearance, connected, error, info, busyNative, dropHover, dragJob, fieldCanvas, fileInput, defaultModel, defaultLanguage, allJobs, active, selected, waiting, completed, percentage, progressCaption, stageDescription, anyInstalled, waitingInstalled, defaultInstalled, totalDuration, startReason, pending, upload, previewDialog, cancelDialog, previewJob, previewText, previewLoading, previewError, ...Vue.toRefs(state), statusText, time, metric, gb, ratio, size, languageText, modelName, trackLabel, spark, chooseTheme, setAccent, nativeFiles, pickBrowser, inputFiles, cancelUpload, onDragEnter, onDragOver, onDragLeave, onDrop, changeModel, changeLanguage, changeTrack, applyDefaults, removeJob, retryJob, queueAction, cancelCurrent, confirmCancel, closeDialog, restoreFocus, moveJob, rowDragStart, rowDrop, download, downloadAll, reveal, copyText, locate, isProcessing, isRecoverable, openPreview, loadPreview, bootstrap };
    } }).mount('#app');
