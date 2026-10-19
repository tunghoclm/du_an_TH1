/* Run with: node --test tests/gate_camera.test.js */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../static/js/gate.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

class Element {
    constructor() {
        this.listeners = {};
        this.disabled = false;
        this.hidden = false;
        this.value = '';
        this.files = [];
        this.dataset = {};
        this.options = [];
        this.attributes = {};
        this.classes = new Set();
        this.classList = {
            toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name),
            add: name => this.classes.add(name),
        };
    }
    addEventListener(name, fn) { (this.listeners[name] ??= []).push(fn); }
    emit(name, event = {}) { return Promise.all((this.listeners[name] || []).map(fn => fn(event))); }
    replaceChildren(...options) { this.options = options; this.value = options[0]?.value || ''; }
    add(option) { this.options.push(option); }
    set value(value) { this._value = value; if (this.isFile && value === '') this.files = []; }
    get value() { return this._value; }
    setAttribute(name, value) { this.attributes[name] = value; }
    getAttribute(name) { return name === 'src' ? this.src : this.attributes[name]; }
    removeAttribute(name) { delete this.attributes[name]; if (name === 'src') delete this.src; }
}

function harness({ secure = true, preview = false, initialSource = 'upload' } = {}) {
    const ids = ['gate-form', 'image', 'source-select', 'camera-video', 'camera-overlay', 'camera-snapshot',
        'camera-select', 'camera-status', 'camera-start', 'camera-stop', 'camera-refresh', 'recognize-button',
        'confirm-button', 'camera-placeholder', 'upload-panel', 'camera-panel', 'camera-controls',
        'gate-token', 'checked-plate', 'gate-result', 'plate', 'image-recognize-button',
        'media-source-label', 'media-placeholder-icon', 'media-placeholder-title', 'media-placeholder-text',
        'media-caption', 'source-camera', 'source-upload'];
    const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
    const $ = id => elements[id];
    const form = $('gate-form');
    $('image').isFile = true;
    const sourceButtons = [$('source-camera'), $('source-upload')];
    sourceButtons[0].dataset.source = 'camera';
    sourceButtons[1].dataset.source = 'upload';
    $('source-select').value = initialSource;
    const requests = [], streams = [], posts = [], frames = [], discarded = [], responses = [], drawings = [];
    const timers = new Map();
    let timerId = 0;
    const saved = new Map();
    const cameras = [
        { kind: 'videoinput', deviceId: 'built-in', label: 'Integrated webcam' },
        { kind: 'videoinput', deviceId: 'usb', label: 'USB camera' },
        { kind: 'audioinput', deviceId: 'mic', label: 'Microphone' },
    ];
    const media = new Element();
    media.enumerateDevices = async () => cameras;
    function makeStream(id = 'built-in') {
        const track = new Element();
        track.readyState = 'live';
        track.label = cameras.find(camera => camera.deviceId === id)?.label;
        track.getSettings = () => ({ deviceId: id });
        track.stop = () => { track.readyState = 'ended'; };
        const stream = { getTracks: () => [track], getVideoTracks: () => [track] };
        streams.push(stream);
        return stream;
    }
    media.getUserMedia = async constraints => {
        requests.push(constraints);
        return makeStream(constraints.video.deviceId?.exact || 'built-in');
    };
    form.dataset.direction = 'entry';
    form.dataset.cameraUrl = '/gate/entry/camera';
    $('recognize-button').dataset.hasPreview = String(preview);
    $('recognize-button').value = 'recognize';
    $('image-recognize-button').value = 'recognize';
    $('confirm-button').value = 'confirm';
    $('confirm-button').disabled = !preview;
    $('gate-token').value = preview ? 'accepted-old' : '';
    $('checked-plate').value = preview ? '30A-54321' : '';
    $('plate').value = preview ? '30A-54321' : '';
    if (preview) $('camera-snapshot').src = '/tmp-preview/old.jpg';
    let resultHtml = '';
    Object.defineProperty($('gate-result'), 'innerHTML', {
        get: () => resultHtml,
        set: html => {
            resultHtml = html;
            $('plate').value = /value="([^"]*)"/.exec(html)?.[1] || '';
        }
    });
    form.querySelectorAll = selector => selector === '[data-source]' ? sourceButtons : Object.values(elements);
    form.requestSubmit = submitter => {
        const event = { submitter, prevented: false, preventDefault() { this.prevented = true; } };
        void form.emit('submit', event);
        // Trình duyệt bỏ qua submitter bị disabled khi tạo dữ liệu form.
        if (!event.prevented) posts.push({ action: submitter.disabled ? undefined : submitter.value,
            token: $('gate-token').value, source: $('source-select').value,
            plate: $('plate').value, checked_plate: $('checked-plate').value });
    };
    const video = $('camera-video');
    video.readyState = 2;
    video.videoWidth = 1920;
    video.videoHeight = 1080;
    video.play = async () => {};
    const drawingContext = {
        clearRect() {}, drawImage() {}, fillRect() {}, fillText() {},
        strokeRect: (...rect) => drawings.push(rect), measureText: text => ({ width: text.length * 12 }),
    };
    $('camera-overlay').getContext = () => drawingContext;
    let lastCanvas;
    const document = new Element();
    document.getElementById = $;
    document.querySelectorAll = () => [];
    document.createElement = () => {
        lastCanvas = { getContext: () => drawingContext,
            toBlob: callback => callback(new Blob(['jpeg-frame'], { type: 'image/jpeg' })) };
        return lastCanvas;
    };
    const window = new Element();
    window.isSecureContext = secure;
    const context = {
        document, window, navigator: { mediaDevices: secure ? media : undefined },
        localStorage: { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) },
        Option: class { constructor(text, value) { Object.assign(this, { text, value }); } },
        Blob, File, FormData, AbortController, URL,
        setTimeout: (callback, delay) => { const id = ++timerId; timers.set(id, { callback, delay }); return id; },
        clearTimeout: id => timers.delete(id), location: { reload() {} },
        fetch: async (url, options) => {
            if (options.body.get('action') === 'discard') {
                discarded.push(options.body.get('token'));
                return { status: 204, ok: true };
            }
            frames.push(options);
            const next = responses.shift();
            const spec = typeof next === 'function' ? await next() : (next || {});
            const plate = spec.plate ?? '51F-12345';
            const data = {
                token: String(frames.length).padStart(12, '0'), plate,
                plate_key: plate.replace(/[^A-Z0-9]/g, ''), valid: true, can_confirm: true,
                checked_plate: plate, rect: [20, 30, 200, 90], width: 1280, height: 720,
                preview_url: '/tmp-preview/frame' + frames.length + '.jpg',
                html: '<input id="plate" value="' + plate + '">', ...spec,
            };
            return { status: spec.status || 200, redirected: !!spec.redirected,
                ok: !spec.status || spec.status === 200, json: async () => data };
        },
    };
    vm.runInNewContext(script, context);
    async function useSource(value) {
        $('source-select').value = value;
        await $('source-select').emit('change');
        await tick();
    }
    async function start() {
        await useSource('camera');
        await $('camera-start').emit('click');
        await tick();
    }
    async function runScan() {
        const found = [...timers.entries()].find(([, timer]) => timer.delay < 1000);
        if (!found) return false;
        timers.delete(found[0]);
        found[1].callback();
        await tick();
        return true;
    }
    return { $, form, media, requests, streams, posts, cameras, document, window, saved, frames, responses,
        drawings, discarded, useSource, start, runScan, makeStream, canvas: () => lastCanvas, timers };
}

test('camera starts only after Start and remembers device selection', async () => {
    const h = harness({ initialSource: 'camera' });
    await tick();
    assert.equal(h.requests.length, 0);
    await h.start();
    assert.equal(h.$('camera-select').options.length, 3);
    assert.equal(h.requests[0].audio, false);
    h.$('camera-select').value = 'usb';
    await h.$('camera-select').emit('change');
    await tick();
    assert.equal(h.requests[1].video.deviceId.exact, 'usb');
    assert.equal(h.streams[0].getTracks()[0].readyState, 'ended');
    assert.equal(h.saved.get('smart-parking-camera-entry'), 'usb');
});

test('automatically scans two matching frames, draws a box, fills the form and waits for confirmation', async () => {
    const h = harness();
    await h.start();
    await h.runScan();
    assert.equal(h.$('confirm-button').disabled, true);
    assert.deepEqual(h.drawings[0], [20, 30, 200, 90]);
    await h.runScan();
    assert.equal(h.frames.length, 2);
    assert.equal(h.frames[0].body.get('image').type, 'image/jpeg');
    assert.equal(h.canvas().width, 1280);
    assert.equal(h.posts.length, 0);
    assert.equal(h.$('gate-token').value, '000000000002');
    assert.equal(h.$('plate').value, '51F-12345');
    assert.equal(h.$('checked-plate').value, '51F-12345');
    assert.equal(h.$('confirm-button').disabled, false);
    assert.equal(h.$('camera-snapshot').hidden, false);
    assert.equal(h.streams[0].getTracks()[0].readyState, 'ended');
    assert.ok(h.discarded.includes('000000000001'));
    assert.ok(!h.discarded.includes('000000000002'));
    assert.equal(await h.runScan(), false);
});

test('confirming a camera result submits action=confirm and keeps the accepted token', async () => {
    const h = harness();
    await h.start();
    await h.runScan();
    await h.runScan();
    h.form.requestSubmit(h.$('confirm-button'));
    assert.equal(h.posts.length, 1);
    assert.equal(h.posts[0].action, 'confirm');
    assert.equal(h.posts[0].token, '000000000002');
    assert.equal(h.posts[0].source, 'camera');
    assert.equal(h.posts[0].plate, '51F-12345');
    assert.ok(!h.discarded.includes('000000000002'));
});

test('manual correction keeps action=recognize during form submission', async () => {
    const h = harness({ preview: true });
    h.$('plate').value = '29A-11111';
    h.form.requestSubmit(h.$('recognize-button'));
    assert.equal(h.posts[0].action, 'recognize');
    assert.equal(h.posts[0].plate, '29A-11111');
});

test('does not send overlapping OCR requests', async () => {
    const h = harness();
    let resolveFrame;
    h.responses.push(() => new Promise(resolve => { resolveFrame = resolve; }));
    await h.start();
    await h.runScan();
    assert.equal(await h.runScan(), false);
    assert.equal(h.frames.length, 1);
    resolveFrame({});
    await tick();
    assert.equal(await h.runScan(), true);
    assert.equal(h.frames.length, 2);
});

test('a late OCR response after Stop is discarded and cannot change the form', async () => {
    const h = harness();
    let resolveFrame;
    h.responses.push(() => new Promise(resolve => { resolveFrame = resolve; }));
    await h.start();
    await h.runScan();
    await h.$('camera-stop').emit('click');
    resolveFrame({});
    await tick();
    assert.equal(h.$('gate-token').value, '');
    assert.equal(h.$('confirm-button').disabled, true);
    assert.ok(h.discarded.includes('000000000001'));
    assert.equal(h.$('camera-video').srcObject, null);
});

test('Stop keeps the last unclear frame for manual correction', async () => {
    const h = harness();
    h.responses.push({ plate: '', valid: false, can_confirm: false, checked_plate: '' });
    await h.start();
    await h.runScan();
    await h.$('camera-stop').emit('click');
    assert.equal(h.$('gate-token').value, '000000000001');
    assert.equal(h.$('confirm-button').disabled, true);
    assert.equal(h.$('recognize-button').hidden, false);
    assert.equal(h.$('plate').readOnly, false);
    assert.ok(!h.discarded.includes('000000000001'));
});

test('different candidate plates cannot be accepted as a stable result', async () => {
    const h = harness();
    h.responses.push({ plate: '30A-54321' }, { plate: '51F-12345' }, { plate: '51F-12345' });
    await h.start();
    await h.runScan();
    await h.runScan();
    assert.equal(h.$('gate-token').value, '');
    await h.runScan();
    assert.equal(h.$('plate').value, '51F-12345');
    assert.equal(h.frames.length, 3);
});

test('a valid plate in the wrong direction does not enable confirmation', async () => {
    const h = harness();
    h.responses.push({ can_confirm: false }, { can_confirm: false });
    await h.start();
    await h.runScan();
    await h.runScan();
    assert.equal(h.$('confirm-button').disabled, true);
    assert.equal(h.$('camera-start').disabled, false);
    assert.equal(h.$('gate-token').value, '000000000002');
});

test('switching to uploads preserves the previously accepted photo and plate', async () => {
    const h = harness({ preview: true });
    await h.start();
    await h.runScan();
    await h.useSource('upload');
    assert.equal(h.$('gate-token').value, 'accepted-old');
    assert.equal(h.$('plate').value, '30A-54321');
    assert.equal(h.$('camera-panel').hidden, false);
    assert.equal(h.$('camera-controls').hidden, true);
    assert.equal(h.streams[0].getTracks()[0].readyState, 'ended');
    assert.equal(h.$('confirm-button').disabled, false);
    assert.ok(h.discarded.includes('000000000001'));
});

test('permission rejection allows another Start attempt', async () => {
    const h = harness();
    h.media.getUserMedia = async () => { throw Object.assign(new Error(), { name: 'NotAllowedError' }); };
    await h.start();
    assert.ok(h.$('camera-status').classes.has('error'));
    assert.equal(h.$('camera-start').disabled, false);
    assert.equal(h.$('camera-stop').disabled, true);
});

test('camera permission arriving after Stop releases the new stream', async () => {
    const h = harness();
    let resolveOpen;
    h.media.getUserMedia = () => new Promise(resolve => { resolveOpen = resolve; });
    await h.start();
    await h.$('camera-stop').emit('click');
    resolveOpen(h.makeStream());
    await tick();
    assert.equal(h.streams[0].getTracks()[0].readyState, 'ended');
    assert.equal(h.$('camera-video').srcObject, null);
});

test('device disconnection and hidden pages release the camera', async () => {
    const h = harness();
    await h.start();
    h.cameras.splice(0, 1);
    await h.media.emit('devicechange');
    await tick();
    assert.equal(h.streams[0].getTracks()[0].readyState, 'ended');
    assert.equal(h.$('camera-start').disabled, false);
    await h.start();
    h.document.hidden = true;
    await h.document.emit('visibilitychange');
    assert.equal(h.streams[1].getTracks()[0].readyState, 'ended');
});

test('HTTP LAN remains on a clear error without breaking image uploads', async () => {
    const h = harness({ secure: false });
    await h.start();
    assert.match(h.$('camera-status').textContent, /localhost:5000/);
    assert.equal(h.requests.length, 0);
    await h.useSource('upload');
    assert.equal(h.$('upload-panel').hidden, false);
});

test('source buttons switch the controls and their pressed state without opening the camera', async () => {
    const h = harness();
    await h.$('source-camera').emit('click');
    await tick();
    assert.equal(h.$('source-select').value, 'camera');
    assert.equal(h.$('source-camera').getAttribute('aria-pressed'), 'true');
    assert.equal(h.$('source-upload').getAttribute('aria-pressed'), 'false');
    assert.equal(h.$('camera-controls').hidden, false);
    assert.equal(h.$('upload-panel').hidden, true);
    assert.equal(h.requests.length, 0);
    await h.$('source-upload').emit('click');
    assert.equal(h.$('upload-panel').hidden, false);
    assert.equal(h.$('camera-controls').hidden, true);
});

test('a selected image is previewed and the recognition submitter survives serialization', async () => {
    const h = harness();
    h.$('image').files = [new File(['image-data'], 'vehicle.jpg', { type: 'image/jpeg' })];
    await h.$('image').emit('change');
    assert.equal(h.$('camera-snapshot').hidden, false);
    assert.match(h.$('camera-snapshot').src, /^blob:/);
    assert.equal(h.$('image-recognize-button').disabled, false);
    assert.equal(h.$('confirm-button').disabled, true);
    h.form.requestSubmit(h.$('image-recognize-button'));
    assert.equal(h.posts[0].action, 'recognize');
    assert.equal(h.posts[0].source, 'upload');
    await h.window.emit('pagehide');
});

test('a repeated confirmation cannot send a second POST while the first is submitting', async () => {
    const h = harness({ preview: true });
    h.form.requestSubmit(h.$('confirm-button'));
    h.form.requestSubmit(h.$('confirm-button'));
    assert.equal(h.posts.length, 1);
    assert.equal(h.posts[0].action, 'confirm');
});

test('low confidence repeated text does not freeze the camera', async () => {
    const h = harness();
    h.responses.push({ confidence: 0.3 }, { confidence: 0.3 });
    await h.start();
    await h.runScan();
    await h.runScan();
    assert.equal(h.$('gate-token').value, '');
    assert.equal(h.$('confirm-button').disabled, true);
    assert.equal(h.streams[0].getTracks()[0].readyState, 'live');
    await h.$('camera-stop').emit('click');
    assert.equal(h.$('gate-token').value, '000000000002'); // vẫn giữ ảnh để sửa tay
});

test('next scan waits 150 ms and displays server processing time', async () => {
    const h = harness();
    h.responses.push({ confidence: 0.95, elapsed_ms: 230 });
    await h.start();
    await h.runScan();
    assert.ok([...h.timers.values()].some(timer => timer.delay === 150));
    assert.match(h.$('media-caption').textContent, /230 ms/);
});

test('busy OCR backs off without accepting or overlapping frames', async () => {
    const h = harness();
    h.responses.push({ status: 429 });
    await h.start();
    await h.runScan();
    assert.equal(h.frames.length, 1);
    assert.equal(h.$('gate-token').value, '');
    assert.ok([...h.timers.values()].some(timer => timer.delay === 600));
});

test('changing vehicle type hides incompatible slots and clears an invalid selection', async () => {
    const h = harness({ preview: true });
    const type = new Element(), slots = new Element(), hint = new Element();
    type.id = 'vehicle_type_id'; type.value = '1'; slots.value = 'B01';
    slots.options = [{ value: '' }, { value: 'A01', dataset: { vehicleType: '1' } },
        { value: 'B01', selected: true, dataset: { vehicleType: '2' } },
        { value: 'C01', dataset: { vehicleType: '' } }];
    slots.querySelectorAll = () => [];
    const get = h.document.getElementById;
    h.document.getElementById = id => ({ vehicle_type_id: type, 'slot-name': slots, 'slot-compatibility': hint }[id] || get(id));
    await h.form.emit('change', { target: type });
    assert.equal(slots.options[1].disabled, false);
    assert.equal(slots.options[2].disabled, true);
    assert.equal(slots.value, '');
    assert.equal(slots.options[3].disabled, false);
    assert.match(hint.textContent, /2 ô trống/);
    assert.equal(h.$('confirm-button').disabled, false);
    slots.options.pop();
    type.value = '99';
    slots.options[2].selected = false;
    await h.form.emit('change', { target: type });
    assert.equal(h.$('confirm-button').disabled, true);
});
