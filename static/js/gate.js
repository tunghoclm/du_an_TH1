/* Tự quét từng khung hình, chờ OCR xong rồi mới gửi khung tiếp theo. */
(() => {
    'use strict';
    const $ = id => document.getElementById(id);
    const form = $('gate-form');
    if (!form) return;
    const sourceSelect = $('source-select');
    const sourceButtons = form.querySelectorAll('[data-source]');
    const image = $('image');
    const video = $('camera-video');
    const ipStreamImg = $('camera-ip-stream');
    const overlay = $('camera-overlay');
    const snapshot = $('camera-snapshot');
    const select = $('camera-select');
    const status = $('camera-status');
    const startButton = $('camera-start');
    const captureButton = $('camera-capture');
    const refreshButton = $('camera-refresh');
    const recognizeButton = $('recognize-button');
    const imageRecognizeButton = $('image-recognize-button');
    const confirmButton = $('confirm-button');
    const payButton = $('pay-button');
    const tokenInput = $('gate-token');
    const checkedPlate = $('checked-plate');
    const cameraUrl = form.dataset.cameraUrl;
    const storageKey = 'smart-parking-camera-' + form.dataset.direction;
    const defaultDevice = () => (select?.dataset?.defaultDevice || '').trim();
    const isIpCameraSource = val => {
        if (!val) return false;
        const s = String(val).trim();
        return /^(https?|rtsps?):\/\//i.test(s) || /^[a-zA-Z0-9._-]+:\d{2,5}(\/.*)?$/.test(s);
    };
    let hasPreview = recognizeButton.dataset.hasPreview === 'true';
    let canConfirm = !confirmButton.disabled;
    let stream = null, ipActive = false, generation = 0, opening = false, scanning = false, submitting = false, capturing = false;
    let scanTimer = null, activeRequest = null, lastResult = null;
    let candidate = '', candidateHits = 0, failures = 0;
    let acceptedPreviewUrl = snapshot.getAttribute('src') || '';
    let uploadPreviewUrl = null;
    let capturePreviewUrl = null;

    const source = () => sourceSelect.value;
    const message = (text, error = false) => {
        status.textContent = text;
        status.classList.toggle('error', error);
    };
    const supported = () => window.isSecureContext && navigator.mediaDevices?.getUserMedia
        && navigator.mediaDevices?.enumerateDevices;
    function remember(id) {
        try { localStorage.setItem(storageKey, id); } catch (_) { /* lưu cài đặt có thể bị chặn */ }
    }
    function remembered() {
        const cfg = defaultDevice();
        if (cfg) return cfg;
        try { return localStorage.getItem(storageKey) || ''; } catch (_) { return ''; }
    }
    function configuredIpCameras() {
        const raw = (select?.dataset?.ipCameras || '').split('|').map(s => s.trim()).filter(Boolean);
        const cfg = defaultDevice();
        if (cfg) raw.unshift(cfg);
        const seen = new Set();
        return raw.filter(item => {
            if (!isIpCameraSource(item) || seen.has(item)) return false;
            seen.add(item);
            return true;
        });
    }
    function getCabinPrefs() {
        try { return JSON.parse(localStorage.getItem('cabin_settings_v1') || '{}'); }
        catch (_) { return {}; }
    }
    function autoRecognizeEnabled() {
        const prefs = getCabinPrefs();
        return 'auto_recognize' in prefs ? Boolean(prefs.auto_recognize) : true;
    }
    function syncSlotOptions() {
        const type = $('vehicle_type_id'), slots = $('slot-name');
        if (!type || !slots) return true;
        let count = 0;
        Array.from(slots.options).forEach(option => {
            if (!option.value) return;
            const allowed = option.dataset.vehicleType;
            const compatible = !allowed || allowed === type.value;
            option.hidden = option.disabled = !compatible;
            if (!compatible && option.selected) slots.value = '';
            if (compatible) count += 1;
        });
        slots.querySelectorAll('optgroup').forEach(group => {
            group.hidden = !Array.from(group.children).some(option => !option.disabled);
        });
        const hint = $('slot-compatibility');
        if (hint) hint.textContent = type.value ? count + ' ô trống phù hợp với loại xe đã chọn.' : 'Chọn loại xe để lọc các ô phù hợp.';
        return count > 0;
    }
    function updateControls() {
        // Giữ nguyên các control cho tới khi trình duyệt gom xong dữ liệu POST,
        // đặc biệt name=action của nút Xác nhận. Chỉ khóa ở task kế tiếp.
        if (submitting) return;
        const running = opening || scanning || !!stream || ipActive;
        startButton.disabled = capturing;
        startButton.textContent = running ? 'Dừng' : 'Bắt đầu';
        startButton.setAttribute('aria-pressed', String(running));
        startButton.classList.toggle('is-running', running);
        captureButton.disabled = (!stream && !ipActive) || opening || capturing;
        $('camera-capture-label').textContent = capturing ? 'Đang đọc…' : 'Chụp';
        select.disabled = opening || capturing;
        refreshButton.disabled = opening || capturing;
        recognizeButton.disabled = scanning || capturing;
        recognizeButton.hidden = !hasPreview;
        recognizeButton.textContent = 'Cập nhật biển số';
        imageRecognizeButton.disabled = scanning || capturing || !image.files.length;
        const disableConfirm = scanning || capturing || !canConfirm || image.files.length > 0 || !syncSlotOptions();
        confirmButton.disabled = disableConfirm;
        if (payButton) payButton.disabled = disableConfirm;
        const plate = $('plate');
        if (plate) plate.readOnly = scanning || capturing;
    }
    function clearUploadPreview() {
        if (uploadPreviewUrl) URL.revokeObjectURL(uploadPreviewUrl);
        uploadPreviewUrl = null;
    }
    function showPreview() {
        const url = capturePreviewUrl || (source() === 'upload' && uploadPreviewUrl ? uploadPreviewUrl : acceptedPreviewUrl);
        if (url) snapshot.src = url;
        else snapshot.removeAttribute('src');
        snapshot.hidden = !url;
    }
    function clearCapturePreview() {
        if (capturePreviewUrl) URL.revokeObjectURL(capturePreviewUrl);
        capturePreviewUrl = null;
    }
    function discard(token) {
        if (!token || token === tokenInput.value) return;
        const body = new FormData();
        body.set('action', 'discard');
        body.set('token', token);
        void fetch(cameraUrl, { method: 'POST', body, keepalive: true }).catch(() => {});
    }
    function applyResult(data) {
        const previous = tokenInput.value;
        $('gate-result').innerHTML = data.html;
        tokenInput.value = data.token;
        checkedPlate.value = data.checked_plate;
        // Ô biển số nằm ngoài #gate-result nên phải điền trực tiếp từ kết quả camera
        const plateField = $('plate');
        if (plateField && data.plate && data.valid !== false) plateField.value = data.plate;
        acceptedPreviewUrl = data.preview_url;
        clearUploadPreview();
        clearCapturePreview();
        snapshot.src = acceptedPreviewUrl;
        hasPreview = true;
        canConfirm = data.can_confirm && data.valid !== false;
        discard(previous);
    }
    function stopCamera(review = false, showMessage = true, keepRequest = false) {
        generation += 1;
        scanning = false;
        opening = false;
        capturing = false;
        clearTimeout(scanTimer);
        scanTimer = null;
        if (!keepRequest) {
            activeRequest?.controller.abort();
            activeRequest = null;
        }
        if (review && lastResult) applyResult(lastResult);
        if (lastResult) discard(lastResult.token);
        lastResult = null;
        const previousStream = stream;
        stream = null;
        ipActive = false;
        previousStream?.getTracks().forEach(track => track.stop());
        video.srcObject = null;
        video.hidden = true;
        if (ipStreamImg) { ipStreamImg.onload = null; ipStreamImg.onerror = null; ipStreamImg.removeAttribute('src'); ipStreamImg.hidden = true; }
        overlay.hidden = true;
        showPreview();
        updateControls();
        if (showMessage) message(hasPreview
            ? 'Camera đã tắt. Kiểm tra biển số bên dưới rồi xác nhận; có thể bấm Bắt đầu để nhận diện lại.'
            : 'Camera đã tắt. Bấm Bắt đầu để nhận diện.');
    }
    function cameraError(error) {
        return ({
            NotAllowedError: 'Chưa được phép dùng camera. Hãy cho phép camera trong trình duyệt rồi bấm Bắt đầu.',
            SecurityError: 'Trình duyệt đang chặn camera. Hãy kiểm tra quyền truy cập của trang.',
            NotFoundError: 'Không tìm thấy camera. Hãy kết nối thiết bị rồi bấm Tìm camera.',
            OverconstrainedError: 'Camera đã chọn không còn khả dụng. Hãy tìm và chọn camera khác.',
            NotReadableError: 'Không mở được camera. Hãy đóng ứng dụng khác đang dùng camera hoặc chọn thiết bị khác.',
            AbortError: 'Camera bị gián đoạn. Hãy bấm Bắt đầu để thử lại.'
        })[error.name] || 'Không mở được camera. Hãy kiểm tra kết nối và chọn lại thiết bị.';
    }
    async function refreshCameras(preferredId) {
        const cfg = defaultDevice();
        const ipList = configuredIpCameras();
        const wanted = preferredId ?? (select.value || cfg || remembered());
        if (!supported() && !ipList.length) return;
        try {
            const cameras = supported()
                ? (await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === 'videoinput')
                : [];
            select.replaceChildren(new Option('Camera mặc định', ''));
            ipList.forEach(ipUrl => {
                select.add(new Option('Camera IP (' + ipUrl + ')', ipUrl));
            });
            cameras.forEach((device, index) => {
                if (device.deviceId) select.add(new Option(device.label || 'Camera ' + (index + 1), device.deviceId));
            });
            const hasWanted = ipList.includes(wanted) || cameras.some(device => device.deviceId === wanted);
            const fallback = (cfg && (ipList.includes(cfg) || cameras.some(d => d.deviceId === cfg))) ? cfg : '';
            select.value = hasWanted ? wanted : fallback;
            const activeId = stream?.getVideoTracks()[0]?.getSettings().deviceId;
            if (activeId && !cameras.some(device => device.deviceId === activeId)) {
                stopCamera(true, false);
                message('Camera đã ngắt kết nối. Hãy chọn camera khác rồi bấm Bắt đầu.', true);
            }
        } catch (_) {
            message('Không đọc được danh sách camera. Hãy kiểm tra quyền truy cập rồi thử lại.', true);
        }
    }
    function scheduleScan(epoch, delay = 80) {
        if (!scanning || !autoRecognizeEnabled() || epoch !== generation || scanTimer !== null) return;
        scanTimer = setTimeout(() => {
            scanTimer = null;
            void scanFrame(epoch);
        }, delay);
    }
    function drawDetection(data) {
        overlay.width = data.width;
        overlay.height = data.height;
        const context = overlay.getContext('2d');
        context.clearRect(0, 0, overlay.width, overlay.height);
        overlay.hidden = false;
        if (!data.rect) return;
        const [x, y, width, height] = data.rect;
        const fontSize = Math.max(18, Math.round(data.width / 45));
        context.strokeStyle = data.valid ? '#22e65b' : '#f5bf49';
        context.lineWidth = Math.max(3, Math.round(data.width / 320));
        context.strokeRect(x, y, width, height);
        if (data.plate && data.valid) {
            context.font = 'bold ' + fontSize + 'px Arial';
            const textY = y >= fontSize + 10 ? y - 6 : Math.min(data.height - 6, y + height + fontSize + 6);
            context.fillStyle = 'rgba(0,0,0,.7)';
            context.fillRect(x, textY - fontSize, context.measureText(data.plate).width + 10, fontSize + 5);
            context.fillStyle = '#ffed63';
            context.fillText(data.plate, x + 5, textY);
        }
    }
    async function scanFrame(epoch) {
        if (!scanning || !autoRecognizeEnabled() || epoch !== generation || activeRequest) return;
        const sourceEl = ipActive && ipStreamImg ? ipStreamImg : video;
        const srcW = ipActive && ipStreamImg ? (ipStreamImg.naturalWidth || 0) : video.videoWidth;
        const srcH = ipActive && ipStreamImg ? (ipStreamImg.naturalHeight || 0) : video.videoHeight;
        if ((!ipActive && video.readyState < 2) || !srcW) { scheduleScan(epoch, 250); return; }
        const request = { epoch, controller: new AbortController() };
        request.done = new Promise(resolve => { request.finish = resolve; });
        activeRequest = request;
        let timeout;
        let retryDelay = 80;
        try {
            const canvas = document.createElement('canvas');
            const scale = Math.min(1, 1280 / Math.max(srcW, srcH));
            canvas.width = Math.round(srcW * scale);
            canvas.height = Math.round(srcH * scale);
            canvas.getContext('2d').drawImage(sourceEl, 0, 0, canvas.width, canvas.height);
            const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.9));
            if (epoch !== generation || !scanning) return;
            if (!blob) throw new Error('Không lấy được ảnh camera. Hãy bấm Bắt đầu để thử lại.');
            const body = new FormData();
            body.set('image', blob, 'camera.jpg');
            body.set('source', 'camera');
            timeout = setTimeout(() => request.controller.abort(), 30000);
            const response = await fetch(cameraUrl, { method: 'POST', body, signal: request.controller.signal });
            if (response.redirected) throw new Error('Phiên đăng nhập đã hết hoặc bạn không có quyền. Hãy tải lại trang.');
            if (response.status === 429) { retryDelay = 600; return; }
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Không nhận diện được ảnh camera.');
            if (epoch !== generation || !scanning) { discard(data.token); return; }
            failures = 0;
            drawDetection(data);
            const previous = lastResult;
            lastResult = data;
            if (previous) discard(previous.token);
            const reliable = data.valid && (data.confidence === undefined || data.confidence >= 0.65);
            if (reliable && data.plate_key === candidate) candidateHits += 1;
            else { candidate = reliable ? data.plate_key : ''; candidateHits = reliable ? 1 : 0; }
            if (candidateHits >= 2) {
                applyResult(data);
                stopCamera(false, false);
                message('Đã nhận diện: ' + data.plate + (data.can_confirm
                    ? '. Kiểm tra thông tin bên dưới rồi bấm Xác nhận.'
                    : '. Kiểm tra thông báo bên dưới hoặc bấm Bắt đầu để nhận diện lại.'), !data.can_confirm);
                return;
            }
            message(reliable
                ? 'Đang kiểm tra biển số ' + data.plate + '… Giữ biển số ổn định.'
                : 'Đang nhận diện… Đưa biển số rõ và đủ sáng vào khung hình.');
        } catch (error) {
            if (epoch !== generation || !scanning) return;
            failures += 1;
            retryDelay = Math.min(3000, failures * 600);
            candidate = '';
            candidateHits = 0;
            const text = error.name === 'AbortError' ? 'Nhận diện mất quá lâu, đang thử lại…' : error.message;
            if (failures >= 3 || text.includes('Phiên đăng nhập')) stopCamera(true, false);
            message(text, true);
        } finally {
            clearTimeout(timeout);
            if (activeRequest === request) activeRequest = null;
            request.finish();
            if (scanning && epoch === generation) scheduleScan(epoch, retryDelay);
        }
    }
    async function captureFrame() {
        const sourceEl = ipActive && ipStreamImg ? ipStreamImg : video;
        const srcW = ipActive && ipStreamImg ? (ipStreamImg.naturalWidth || 0) : video.videoWidth;
        const srcH = ipActive && ipStreamImg ? (ipStreamImg.naturalHeight || 0) : video.videoHeight;
        if ((!stream && !ipActive) || opening || capturing || submitting || (!ipActive && video.readyState < 2) || !srcW) return;
        const canvas = document.createElement('canvas');
        const scale = Math.min(1, 1920 / Math.max(srcW, srcH));
        canvas.width = Math.round(srcW * scale);
        canvas.height = Math.round(srcH * scale);
        canvas.getContext('2d').drawImage(sourceEl, 0, 0, canvas.width, canvas.height);
        const pending = activeRequest;
        // Freeze the clicked frame immediately, then wait for the current OCR
        // request to finish so the single server worker is not overloaded.
        stopCamera(false, false, true);
        const epoch = generation;
        capturing = true;
        canConfirm = false;
        updateControls();
        message('Đã chụp khung hình. Đang đọc biển số…');
        let request, timeout;
        try {
            const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.96));
            if (epoch !== generation) return;
            if (!blob) throw new Error('Không chụp được ảnh. Hãy bấm Bắt đầu và chụp lại.');
            const oldToken = tokenInput.value;
            tokenInput.value = '';
            checkedPlate.value = '';
            acceptedPreviewUrl = '';
            hasPreview = false;
            if ($('plate')) $('plate').value = '';
            discard(oldToken);
            updateControls();
            clearCapturePreview();
            capturePreviewUrl = URL.createObjectURL(blob);
            showPreview();
            if (pending) await pending.done;
            if (epoch !== generation) return;
            request = { epoch, controller: new AbortController() };
            activeRequest = request;
            const body = new FormData();
            body.set('image', blob, 'camera-capture.jpg');
            body.set('source', 'camera');
            body.set('profile', 'capture');
            timeout = setTimeout(() => request.controller.abort(), 30000);
            let data;
            for (let attempt = 0; attempt < 3; attempt++) {
                const response = await fetch(cameraUrl, { method:'POST', body, signal:request.controller.signal });
                if (response.redirected) throw new Error('Phiên đăng nhập đã hết hoặc bạn không có quyền. Hãy tải lại trang.');
                if (response.status === 429 && attempt < 2) {
                    await new Promise(resolve => setTimeout(resolve, 300));
                    if (epoch !== generation) return;
                    continue;
                }
                data = await response.json();
                if (!response.ok) throw new Error(data.error || 'Không nhận diện được ảnh vừa chụp.');
                break;
            }
            if (epoch !== generation) { discard(data?.token); return; }
            applyResult(data);
            snapshot.hidden = false;
            message(data.valid ? 'Đã chụp và nhận diện: ' + data.plate + '. Kiểm tra thông tin rồi xác nhận.' :
                'Đã chụp ảnh nhưng biển số chưa đủ rõ. Kiểm tra hoặc sửa biển số rồi bấm Cập nhật biển số.', !data.valid);
        } catch (error) {
            if (epoch === generation) message(error.name === 'AbortError' ? 'Nhận diện ảnh chụp mất quá lâu. Hãy bắt đầu và chụp lại.' : error.message, true);
        } finally {
            clearTimeout(timeout);
            if (activeRequest === request) activeRequest = null;
            if (epoch === generation) { capturing = false; updateControls(); }
        }
    }
    async function startCamera() {
        if (submitting) return;
        const chosen = (select.value || defaultDevice()).trim();
        if (isIpCameraSource(chosen) && ipStreamImg) {
            stopCamera(false, false);
            clearCapturePreview();
            const epoch = generation;
            opening = true;
            scanning = true;
            ipActive = true;
            candidate = '';
            candidateHits = 0;
            failures = 0;
            snapshot.hidden = true;
            updateControls();
            message('Đang kết nối camera IP…');
            ipStreamImg.onload = () => {
                if (epoch !== generation || !ipActive) return;
                opening = false;
                ipStreamImg.hidden = false;
                remember(chosen);
                updateControls();
                if (autoRecognizeEnabled()) {
                    message('Đang nhận diện từ Camera IP… Đưa biển số vào khung hình.');
                    scheduleScan(epoch, 0);
                } else {
                    message('Camera IP đang chạy. Bấm "Chụp" để nhận diện biển số.');
                }
            };
            ipStreamImg.onerror = () => {
                if (epoch !== generation) return;
                stopCamera(false, false);
                message('Không kết nối được camera IP. Kiểm tra lại địa chỉ IP Webcam và Wi-Fi.', true);
            };
            ipStreamImg.src = `/gate/camera-stream/${form.dataset.direction}_plate?url=${encodeURIComponent(chosen)}&t=${Date.now()}`;
            return;
        }
        if (!supported()) {
            message(window.isSecureContext
                ? 'Trình duyệt này chưa hỗ trợ camera. Hãy dùng Chrome hoặc Edge mới, hoặc chọn Tải ảnh.'
                : 'Để dùng camera, hãy mở http://localhost:5000 trên máy này hoặc dùng HTTPS.', true);
            return;
        }
        stopCamera(false, false);
        clearCapturePreview();
        const epoch = generation;
        opening = true;
        scanning = true;
        candidate = '';
        candidateHits = 0;
        failures = 0;
        snapshot.hidden = true;
        updateControls();
        message('Đang mở camera… Hãy cho phép truy cập nếu trình duyệt yêu cầu.');
        try {
            const constraints = { width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal:30, max:30 } };
            if (select.value) constraints.deviceId = { exact: select.value };
            else constraints.facingMode = { ideal: 'environment' };
            const opened = await navigator.mediaDevices.getUserMedia({ video: constraints, audio: false });
            if (epoch !== generation || source() !== 'camera') { opened.getTracks().forEach(track => track.stop()); return; }
            stream = opened;
            const track = opened.getVideoTracks()[0];
            track.addEventListener('ended', () => {
                if (stream !== opened) return;
                stopCamera(true, false);
                message('Camera đã ngắt. Hãy kiểm tra thiết bị rồi bấm Bắt đầu.', true);
            });
            video.srcObject = opened;
            video.hidden = false;
            await video.play();
            if (epoch !== generation) return;
            const id = track.getSettings().deviceId || '';
            remember(id);
            await refreshCameras(id);
            if (epoch !== generation) return;
            opening = false;
            if (autoRecognizeEnabled()) {
                message('Đang nhận diện từ ' + (track.label || 'camera đã chọn') + '… Đưa biển số vào khung hình.');
                scheduleScan(epoch, 0);
            } else {
                message('Camera ' + (track.label || 'đã chọn') + ' đang chạy. Bấm "Chụp" để nhận diện biển số.');
            }
        } catch (error) {
            if (epoch !== generation) return;
            stopCamera(false, false);
            message(cameraError(error), true);
        } finally { updateControls(); }
    }
    function syncSource() {
        const useCamera = source() === 'camera';
        $('upload-panel').hidden = useCamera;
        $('camera-controls').hidden = !useCamera;
        status.hidden = !useCamera;
        $('media-source-label').textContent = useCamera ? 'Camera' : 'Ảnh tải lên';
        sourceButtons.forEach(button => {
            const active = button.dataset.source === source();
            button.classList.toggle('active', active);
            button.setAttribute('aria-pressed', String(active));
        });
        showPreview();
        updateControls();
    }
    function changeSource() {
        if (submitting) return;
        stopCamera(false, false);
        clearCapturePreview();
        image.value = '';
        clearUploadPreview();
        syncSource();
        if (source() === 'camera') void refreshCameras(remembered());
    }
    sourceSelect.addEventListener('change', changeSource);
    form.addEventListener('change', event => { if (event.target?.id === 'vehicle_type_id') updateControls(); });
    sourceButtons.forEach(button => {
        button.addEventListener('click', () => {
            if (submitting || button.dataset.source === source()) return;
            sourceSelect.value = button.dataset.source;
            changeSource();
        });
    });
    image.addEventListener('change', () => {
        clearUploadPreview();
        const file = image.files[0];
        if (file) {
            uploadPreviewUrl = URL.createObjectURL(file);
        }
        showPreview();
        updateControls();
    });
    startButton.addEventListener('click', () => { if (stream || ipActive || opening || scanning) stopCamera(true); else void startCamera(); });
    captureButton.addEventListener('click', () => { void captureFrame(); });
    refreshButton.addEventListener('click', () => { void refreshCameras(); });
    select.addEventListener('change', () => {
        remember(select.value);
        if (select.dataset) select.dataset.defaultDevice = select.value;
        if (form.dataset.direction) {
            void fetch('/api/camera/select-lane', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ direction: form.dataset.direction, device: select.value })
            }).catch(() => {});
        }
        if (scanning || opening || ipActive) void startCamera();
    });
    video.addEventListener('loadeddata', () => {
        if (scanning && !opening) scheduleScan(generation, 0);
    });
    form.addEventListener('submit', event => {
        if (submitting || scanning || capturing) {
            event.preventDefault();
            return;
        }
        if (!event.submitter) {
            event.preventDefault();
            form.requestSubmit(recognizeButton);
            return;
        }
        submitting = true;
        form.setAttribute('aria-busy', 'true');
        stopCamera(false, false);
        setTimeout(() => {
            form.querySelectorAll('button, select').forEach(control => { control.disabled = true; });
            event.submitter.textContent = 'Đang xử lý…';
        }, 0);
    });
    window.addEventListener('pagehide', () => { stopCamera(false, false); clearUploadPreview(); clearCapturePreview(); });
    window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
    document.addEventListener('visibilitychange', () => { if (document.hidden) stopCamera(true); });
    navigator.mediaDevices?.addEventListener('devicechange', () => { if (source() === 'camera') void refreshCameras(); });
    syncSource();
    if (source() === 'camera') void refreshCameras(remembered());

    function getCabinPrefs() {
        try { return JSON.parse(localStorage.getItem('cabin_settings_v1') || '{}'); }
        catch (_) { return {}; }
    }
    let lastAutoStart = Boolean(getCabinPrefs().auto_start_camera);
    async function applyGateAutoPrefs() {
        const prefs = getCabinPrefs();
        const shouldStart = Boolean(prefs.auto_start_camera);
        const turnedOff = lastAutoStart && !shouldStart;
        lastAutoStart = shouldStart;
        if (turnedOff && (stream || ipActive || opening || scanning)) {
            stopCamera(true);
            return;
        }
        if ((stream || ipActive) && !opening) {
            if (autoRecognizeEnabled()) {
                scheduleScan(generation, 0);
            } else {
                clearTimeout(scanTimer);
                scanTimer = null;
                activeRequest?.controller.abort();
                activeRequest = null;
                message('Camera đang chạy. Bấm "Chụp" để nhận diện biển số.');
            }
        }
        if (shouldStart && !submitting && !capturing && !hasPreview) {
            if (source() !== 'camera') {
                sourceSelect.value = 'camera';
                syncSource();
            }
            if (!stream && !ipActive && !opening && !scanning) {
                await refreshCameras(remembered());
                if (!stream && !ipActive && !opening && !scanning && source() === 'camera') {
                    void startCamera();
                }
            }
        }
    }
    if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
        window.addEventListener('cabin:prefs-updated', () => { void applyGateAutoPrefs(); });
    }
    void applyGateAutoPrefs();
    const printFrame = $('invoice-print-frame');
    if (printFrame) {
        let printed = false;
        const doPrint = () => {
            if (printed) return;
            printed = true;
            setTimeout(() => {
                try {
                    printFrame.contentWindow.focus();
                    printFrame.contentWindow.print();
                } catch (err) {
                    console.error('Lỗi in hóa đơn:', err);
                }
            }, 300);
        };
        printFrame.addEventListener('load', doPrint);
        if (printFrame.contentDocument && printFrame.contentDocument.readyState === 'complete') {
            doPrint();
        }
    }

    if (window.history && window.history.replaceState) {
        try {
            const currentUrl = new URL(window.location.href);
            if (currentUrl.searchParams.has('print_invoice')) {
                currentUrl.searchParams.delete('print_invoice');
                setTimeout(() => {
                    window.history.replaceState({}, document.title, currentUrl.toString());
                }, 1000);
            }
        } catch (_) {}
    }

    // ============================================================
    // KIOTVIET FNB POS PAYMENT MODAL INTERACTION & CALCULATOR
    // ============================================================
    const posModal = $('pos-payment-modal');
    if (posModal && payButton) {
        let currentMethod = 'cash';
        let discountUnit = 'vnd';
        const feeBox = $('pos-fee-display');
        const getBaseFee = () => (feeBox ? parseInt(feeBox.dataset.fee || '0', 10) : 0);
        const getDiscountedFee = () => {
            const base = getBaseFee();
            const discInput = $('pos-discount-input');
            const raw = discInput ? Math.max(0, parseFloat(discInput.value.replace(/[^0-9.]/g, '') || '0') || 0) : 0;
            if (discountUnit === 'percent') {
                return Math.max(0, Math.round(base * (1 - Math.min(100, raw) / 100)));
            }
            return Math.max(0, base - Math.round(raw));
        };
        const getFee = () => getDiscountedFee();
        const formatMoney = num => Math.max(0, num).toLocaleString('vi-VN') + ' VNĐ';

        function updateDiscountUI() {
            const unitTxt = $('pos-discount-unit-text');
            const unitBtn = $('pos-discount-unit-btn');
            const label = discountUnit === 'percent' ? '%' : 'VND';
            if (unitTxt) unitTxt.textContent = label;
            if (unitBtn) unitBtn.textContent = label;
            const netFee = getFee();
            if (feeBox) feeBox.innerHTML = `${netFee.toLocaleString('vi-VN')} <small>VNĐ</small>`;
            const qrAmount = $('pos-qr-amount-text');
            if (qrAmount) qrAmount.textContent = formatMoney(netFee);
            const prefs = getCabinPrefs();
            const autoFill = 'auto_fill_pay' in prefs ? Boolean(prefs.auto_fill_pay) : true;
            const cashInput = $('pos-cash-given');
            if (cashInput && autoFill) {
                cashInput.value = netFee > 0 ? netFee.toLocaleString('vi-VN') : '0';
            }
            updateChangeDue();
        }

        function updateChangeDue() {
            const fee = getFee();
            const input = $('pos-cash-given');
            const changeBox = $('pos-change-box');
            const changeVal = $('pos-change-val');
            if (!input || !changeVal) return;
            const rawVal = input.value.replace(/[^0-9]/g, '');
            const given = parseInt(rawVal || '0', 10);
            if (rawVal) {
                input.value = given.toLocaleString('vi-VN');
            }
            const diff = given - fee;
            if (diff >= 0) {
                changeBox.classList.remove('negative');
                changeBox.querySelector('span').textContent = 'Tiền thừa trả khách:';
                changeVal.textContent = formatMoney(diff);
            } else {
                changeBox.classList.add('negative');
                changeBox.querySelector('span').textContent = 'Còn thiếu:';
                changeVal.textContent = formatMoney(Math.abs(diff));
            }
        }

        function switchPosMethod(method) {
            currentMethod = method;
            posModal.querySelectorAll('[data-pos-method]').forEach(tab => {
                const active = tab.dataset.posMethod === method;
                tab.classList.toggle('active', active);
                tab.setAttribute('aria-selected', String(active));
            });
            ['cash', 'transfer'].forEach(m => {
                const content = $('pos-tab-' + m);
                if (content) content.hidden = (m !== method);
            });
            const mainSelect = $('exit-payment-method');
            if (mainSelect) mainSelect.value = method;
        }

        function openPosModal() {
            const plateInput = $('plate');
            const curPlate = plateInput ? plateInput.value.trim() : '';
            const plateDisp = $('pos-plate-display');
            if (plateDisp && curPlate) plateDisp.textContent = curPlate;

            const fee = getFee();
            const cleanPlate = curPlate.replace(/[^A-Za-z0-9]/g, '').toUpperCase();

            // Dynamic VietQR Configuration from System Settings
            const qrBin = form.dataset.vietqrBin || '970407';
            const qrBankName = form.dataset.vietqrBankName || 'Techcombank';
            const qrAccount = form.dataset.vietqrAccount || '19036888888';
            const qrName = form.dataset.vietqrName || 'SMART PARKING';
            const qrTemplate = form.dataset.vietqrTemplate || 'compact2';

            const qrImg = $('pos-vietqr-img');
            const qrBankEl = posModal.querySelector('.pos-qr-bank');
            const qrNameEl = posModal.querySelector('.pos-qr-name');
            const qrAmount = $('pos-qr-amount-text');
            const qrMemo = $('pos-qr-memo-text');

            if (qrBankEl) qrBankEl.textContent = qrBankName + ' · ' + qrAccount;
            if (qrNameEl) qrNameEl.textContent = qrName;
            if (qrImg) {
                qrImg.src = 'https://img.vietqr.io/image/' + qrBin + '-' + encodeURIComponent(qrAccount)
                    + '-' + qrTemplate + '.png?amount=' + fee
                    + '&addInfo=' + encodeURIComponent('XE ' + cleanPlate)
                    + '&accountName=' + encodeURIComponent(qrName);
            }
            if (qrAmount) qrAmount.textContent = formatMoney(fee);
            if (qrMemo) qrMemo.textContent = 'Nội dung: XE ' + cleanPlate;

            // Áp dụng Tùy chọn cài đặt Cabin (Thanh toán & Phiếu xe)
            const prefs = getCabinPrefs();
            const autoFill = 'auto_fill_pay' in prefs ? Boolean(prefs.auto_fill_pay) : true;
            const defaultMethod = (prefs.default_payment === 'transfer') ? 'transfer' : 'cash';
            discountUnit = (prefs.discount_unit === 'percent') ? 'percent' : 'vnd';
            const discInput = $('pos-discount-input');
            const inlineDisc = $('exit-discount-input');
            if (discInput) discInput.value = (inlineDisc && inlineDisc.value) ? inlineDisc.value : '0';
            updateDiscountUI();

            const printReceiptCb = $('pos-print-receipt-cb');
            if (printReceiptCb && 'auto_print_exit' in prefs) {
                printReceiptCb.checked = Boolean(prefs.auto_print_exit);
            }

            // Reset Tiền khách đưa theo tùy chọn Tự động điền giá trị khách thanh toán
            const netFee = getFee();
            const cashInput = $('pos-cash-given');
            if (cashInput) {
                cashInput.value = autoFill ? (netFee > 0 ? netFee.toLocaleString('vi-VN') : '0') : '';
                updateChangeDue();
            }

            switchPosMethod(defaultMethod);
            posModal.removeAttribute('hidden');
            setTimeout(() => { if (cashInput) cashInput.focus(); }, 100);
        }

        function closePosModal() {
            posModal.setAttribute('hidden', '');
        }

        let isPosSubmitting = false;

        payButton.addEventListener('click', event => {
            if (isPosSubmitting) {
                return; // Let the real submission through
            }
            if (canConfirm) {
                event.preventDefault();
                openPosModal();
            }
        });

        const closeBtn = $('pos-modal-close-btn');
        if (closeBtn) closeBtn.addEventListener('click', closePosModal);
        const cancelBtn = $('pos-modal-cancel-btn');
        if (cancelBtn) cancelBtn.addEventListener('click', closePosModal);

        posModal.addEventListener('click', event => {
            if (event.target === posModal) closePosModal();
        });

        document.addEventListener('keydown', event => {
            if (!posModal.hasAttribute('hidden')) {
                if (event.key === 'Escape') {
                    closePosModal();
                } else if (event.key === 'F9') {
                    event.preventDefault();
                    confirmPosPayment();
                }
            }
        });

        // Tabs
        posModal.querySelectorAll('[data-pos-method]').forEach(tab => {
            tab.addEventListener('click', () => switchPosMethod(tab.dataset.posMethod));
        });

        // Chips
        posModal.querySelectorAll('.pos-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const cashInput = $('pos-cash-given');
                if (cashInput) {
                    cashInput.value = chip.dataset.amount;
                    updateChangeDue();
                }
            });
        });

        const exactBtn = $('pos-exact-btn');
        if (exactBtn) {
            exactBtn.addEventListener('click', () => {
                const cashInput = $('pos-cash-given');
                if (cashInput) {
                    cashInput.value = getFee().toString();
                    updateChangeDue();
                }
            });
        }

        const cashInput = $('pos-cash-given');
        if (cashInput) {
            cashInput.addEventListener('input', updateChangeDue);
        }
        const discInput = $('pos-discount-input');
        if (discInput) {
            discInput.addEventListener('input', updateDiscountUI);
        }
        const discUnitBtn = $('pos-discount-unit-btn');
        if (discUnitBtn) {
            discUnitBtn.addEventListener('click', () => {
                discountUnit = discountUnit === 'percent' ? 'vnd' : 'percent';
                updateDiscountUI();
            });
        }

        function confirmPosPayment() {
            const confirmBtn = $('pos-modal-confirm-btn');
            if (confirmBtn) {
                confirmBtn.classList.add('is-loading');
                confirmBtn.disabled = true;
                const label = $('pos-confirm-label');
                if (label) label.textContent = 'Đang thanh toán…';
            }

            const mainSelect = $('exit-payment-method');
            if (mainSelect) mainSelect.value = currentMethod;
            const inlineDisc = $('exit-discount-input');
            const modalDisc = $('pos-discount-input');
            if (inlineDisc && modalDisc) {
                inlineDisc.value = modalDisc.value.replace(/[^0-9]/g, '') || '0';
            }
            const unitHid = document.querySelector('[data-exit-discount-unit]');
            if (unitHid) unitHid.value = discountUnit;

            const printReceipt = $('pos-print-receipt-cb');
            const shouldPrint = !printReceipt || printReceipt.checked;

            isPosSubmitting = true;
            closePosModal();

            // Submit using payButton (value="pay") or confirmButton (value="confirm")
            const targetBtn = shouldPrint ? payButton : confirmButton;
            form.requestSubmit(targetBtn);
        }

        const modalConfirmBtn = $('pos-modal-confirm-btn');
        if (modalConfirmBtn) {
            modalConfirmBtn.addEventListener('click', confirmPosPayment);
        }
    }

    setTimeout(() => {
        document.querySelectorAll('.toast').forEach(toast => {
            toast.classList.add('out');
            setTimeout(() => toast.remove(), 400);
        });
    }, 6000);
})();
