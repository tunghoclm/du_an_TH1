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
    const overlay = $('camera-overlay');
    const snapshot = $('camera-snapshot');
    const select = $('camera-select');
    const status = $('camera-status');
    const startButton = $('camera-start');
    const stopButton = $('camera-stop');
    const refreshButton = $('camera-refresh');
    const recognizeButton = $('recognize-button');
    const imageRecognizeButton = $('image-recognize-button');
    const confirmButton = $('confirm-button');
    const tokenInput = $('gate-token');
    const checkedPlate = $('checked-plate');
    const cameraUrl = form.dataset.cameraUrl;
    const storageKey = 'smart-parking-camera-' + form.dataset.direction;
    let hasPreview = recognizeButton.dataset.hasPreview === 'true';
    let canConfirm = !confirmButton.disabled;
    let stream = null, generation = 0, opening = false, scanning = false, submitting = false;
    let scanTimer = null, activeRequest = null, lastResult = null;
    let candidate = '', candidateHits = 0, failures = 0;
    let acceptedPreviewUrl = snapshot.getAttribute('src') || '';
    let uploadPreviewUrl = null;

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
        try { return localStorage.getItem(storageKey) || ''; } catch (_) { return ''; }
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
        startButton.disabled = opening || scanning || submitting;
        stopButton.disabled = (!stream && !opening) || submitting;
        select.disabled = opening || submitting;
        refreshButton.disabled = opening || submitting;
        recognizeButton.disabled = scanning;
        recognizeButton.hidden = !hasPreview;
        recognizeButton.textContent = 'Cập nhật biển số';
        imageRecognizeButton.disabled = scanning || !image.files.length;
        confirmButton.disabled = submitting || scanning || !canConfirm || image.files.length > 0 || !syncSlotOptions();
        const plate = $('plate');
        if (plate) plate.readOnly = scanning;
    }
    function clearUploadPreview() {
        if (uploadPreviewUrl) URL.revokeObjectURL(uploadPreviewUrl);
        uploadPreviewUrl = null;
    }
    function showPreview() {
        const url = source() === 'upload' && uploadPreviewUrl ? uploadPreviewUrl : acceptedPreviewUrl;
        if (url) snapshot.src = url;
        else snapshot.removeAttribute('src');
        snapshot.hidden = !url;
        $('camera-placeholder').hidden = !!url;
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
        acceptedPreviewUrl = data.preview_url;
        clearUploadPreview();
        snapshot.src = acceptedPreviewUrl;
        $('media-caption').textContent = 'Ảnh đã nhận diện · ' + (data.plate || 'Chưa đọc rõ biển số');
        hasPreview = true;
        canConfirm = data.can_confirm;
        discard(previous);
    }
    function stopCamera(review = false, showMessage = true) {
        generation += 1;
        scanning = false;
        opening = false;
        clearTimeout(scanTimer);
        scanTimer = null;
        activeRequest?.controller.abort();
        activeRequest = null;
        if (review && lastResult) applyResult(lastResult);
        if (lastResult) discard(lastResult.token);
        lastResult = null;
        const previousStream = stream;
        stream = null;
        previousStream?.getTracks().forEach(track => track.stop());
        video.srcObject = null;
        video.hidden = true;
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
        if (!supported()) return;
        try {
            const cameras = (await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === 'videoinput');
            const wanted = preferredId ?? select.value;
            select.replaceChildren(new Option('Camera mặc định', ''));
            cameras.forEach((device, index) => {
                if (device.deviceId) select.add(new Option(device.label || 'Camera ' + (index + 1), device.deviceId));
            });
            select.value = cameras.some(device => device.deviceId === wanted) ? wanted : '';
            const activeId = stream?.getVideoTracks()[0]?.getSettings().deviceId;
            if (activeId && !cameras.some(device => device.deviceId === activeId)) {
                stopCamera(true, false);
                message('Camera đã ngắt kết nối. Hãy chọn camera khác rồi bấm Bắt đầu.', true);
            }
        } catch (_) {
            message('Không đọc được danh sách camera. Hãy kiểm tra quyền truy cập rồi thử lại.', true);
        }
    }
    function scheduleScan(epoch, delay = 150) {
        if (!scanning || epoch !== generation || scanTimer !== null) return;
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
        context.strokeStyle = '#22e65b';
        context.lineWidth = Math.max(3, Math.round(data.width / 320));
        context.strokeRect(x, y, width, height);
        if (data.plate) {
            context.font = 'bold ' + fontSize + 'px Arial';
            const textY = y >= fontSize + 10 ? y - 6 : Math.min(data.height - 6, y + height + fontSize + 6);
            context.fillStyle = 'rgba(0,0,0,.7)';
            context.fillRect(x, textY - fontSize, context.measureText(data.plate).width + 10, fontSize + 5);
            context.fillStyle = '#ffed63';
            context.fillText(data.plate, x + 5, textY);
        }
    }
    async function scanFrame(epoch) {
        if (!scanning || epoch !== generation || activeRequest) return;
        if (video.readyState < 2 || !video.videoWidth) { scheduleScan(epoch, 250); return; }
        const request = { epoch, controller: new AbortController() };
        activeRequest = request;
        let timeout;
        let retryDelay = 150;
        try {
            const canvas = document.createElement('canvas');
            const scale = Math.min(1, 1280 / Math.max(video.videoWidth, video.videoHeight));
            canvas.width = Math.round(video.videoWidth * scale);
            canvas.height = Math.round(video.videoHeight * scale);
            canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
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
            if (Number.isFinite(data.elapsed_ms)) {
                $('media-caption').textContent = 'Đang quét · ' + data.elapsed_ms + ' ms / lần'
                    + (data.confidence ? ' · Độ tin cậy ' + Math.round(data.confidence * 100) + '%' : '');
            }
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
            if (scanning && epoch === generation) scheduleScan(epoch, retryDelay);
        }
    }
    async function startCamera() {
        if (submitting) return;
        if (!supported()) {
            message(window.isSecureContext
                ? 'Trình duyệt này chưa hỗ trợ camera. Hãy dùng Chrome hoặc Edge mới, hoặc chọn Tải ảnh.'
                : 'Để dùng camera, hãy mở http://localhost:5000 trên máy này hoặc dùng HTTPS.', true);
            return;
        }
        stopCamera(false, false);
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
            const constraints = { width: { ideal: 1280 }, height: { ideal: 720 } };
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
            $('camera-placeholder').hidden = true;
            $('media-caption').textContent = 'Camera đang hoạt động · Giữ biển số trong khung hình';
            await video.play();
            if (epoch !== generation) return;
            const id = track.getSettings().deviceId || '';
            remember(id);
            await refreshCameras(id);
            if (epoch !== generation) return;
            opening = false;
            message('Đang nhận diện từ ' + (track.label || 'camera đã chọn') + '… Đưa biển số vào khung hình.');
            scheduleScan(epoch, 0);
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
        $('media-source-label').textContent = useCamera ? 'Camera' : 'Ảnh tải lên';
        $('media-placeholder-icon').textContent = useCamera ? '📷' : '🖼️';
        $('media-placeholder-title').textContent = useCamera ? 'Camera sẵn sàng' : 'Chưa có hình ảnh';
        $('media-placeholder-text').textContent = useCamera
            ? 'Bấm Bắt đầu và đưa biển số vào khung hình.'
            : 'Chọn ảnh có biển số rõ nét để bắt đầu nhận diện.';
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
        image.value = '';
        clearUploadPreview();
        $('media-caption').textContent = hasPreview ? 'Ảnh đã giữ để xác nhận.' : 'Ảnh nhận diện sẽ xuất hiện tại đây.';
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
            $('media-caption').textContent = file.name + ' · Chưa nhận diện';
        } else {
            $('media-caption').textContent = hasPreview ? 'Ảnh đã giữ để xác nhận.' : 'Ảnh nhận diện sẽ xuất hiện tại đây.';
        }
        showPreview();
        updateControls();
    });
    startButton.addEventListener('click', () => { void startCamera(); });
    stopButton.addEventListener('click', () => stopCamera(true));
    refreshButton.addEventListener('click', () => { void refreshCameras(); });
    select.addEventListener('change', () => {
        remember(select.value);
        if (scanning || opening) void startCamera();
    });
    video.addEventListener('loadeddata', () => {
        if (scanning && !opening) scheduleScan(generation, 0);
    });
    form.addEventListener('submit', event => {
        if (submitting || scanning) {
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
    window.addEventListener('pagehide', () => { stopCamera(false, false); clearUploadPreview(); });
    window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
    document.addEventListener('visibilitychange', () => { if (document.hidden) stopCamera(true); });
    navigator.mediaDevices?.addEventListener('devicechange', () => { if (source() === 'camera') void refreshCameras(); });
    syncSource();
    if (source() === 'camera') void refreshCameras(remembered());
    setTimeout(() => {
        document.querySelectorAll('.toast').forEach(toast => {
            toast.classList.add('out');
            setTimeout(() => toast.remove(), 400);
        });
    }, 6000);
})();
