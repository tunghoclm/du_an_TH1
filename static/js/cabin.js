(() => {
    'use strict';
    const $ = id => document.getElementById(id);
    const menuButton = $('cabin-menu-toggle');
    const menu = $('cabin-menu');
    function closeMenu() {
        if (!menu) return;
        menu.hidden = true;
        menuButton.setAttribute('aria-expanded', 'false');
    }
    menuButton?.addEventListener('click', () => {
        menu.hidden = !menu.hidden;
        menuButton.setAttribute('aria-expanded', String(!menu.hidden));
    });
    document.addEventListener('click', event => {
        if (menu && !menu.hidden && !event.target.closest('.cabin-menu-wrap')) closeMenu();
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && menu && !menu.hidden) {
            closeMenu();
            menuButton.focus();
        }
    });
    $('cabin-refresh')?.addEventListener('click', () => location.reload());
    const fullscreen = $('cabin-fullscreen');
    if (fullscreen) {
        fullscreen.hidden = !document.fullscreenEnabled;
        fullscreen.addEventListener('click', async () => {
            try {
                if (document.fullscreenElement) await document.exitFullscreen();
                else await document.documentElement.requestFullscreen();
            } catch (_) { /* The browser may decline fullscreen; the normal view remains usable. */ }
        });
        document.addEventListener('fullscreenchange', () => {
            fullscreen.setAttribute('aria-pressed', String(!!document.fullscreenElement));
        });
    }
    $('cabin-dismiss-flash')?.addEventListener('click', event => {
        event.currentTarget.closest('.cabin-flashes').remove();
    });

    const isLanesPage = document.body.dataset.cabinPage === 'lanes';
    const grid = $('cabin-slot-grid');
    if (!grid) return;
    const scrollWrap = $('cabin-slot-scroll');
    const viewToggle = $('cabin-view-toggle');
    const slots = Array.from(document.querySelectorAll('[data-cabin-slot]'));
    const details = Array.from(document.querySelectorAll('[data-cabin-detail]'));
    const areaButtons = Array.from(document.querySelectorAll('[data-cabin-area]'));
    const statusInputs = Array.from(document.querySelectorAll('input[name="cabin-status"]'));
    const search = $('cabin-search');
    const ticketSearch = $('cabin-ticket-search');
    const lanesFilter = $('lanes-quick-filter');
    const primary = $('cabin-primary-action');
    const exit = $('cabin-exit-action');
    const tabLabel = $('cabin-ticket-tab-label');
    const totalCount = $('cabin-total-count');
    let area = 'all', status = 'all', selected = null;
    const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/đ/g, 'd');

    function setGridVisible(visible) {
        if (!scrollWrap) return;
        scrollWrap.hidden = !visible;
        viewToggle?.setAttribute('aria-pressed', String(visible));
    }

    function selectSlot(slot) {
        selected = slot;
        slots.forEach(item => item.setAttribute('aria-pressed', String(item === slot)));
        details.forEach(item => { item.hidden = !slot || item.dataset.cabinDetail !== slot.dataset.cabinSlot; });
        const emptyEl = $('cabin-ticket-empty');
        if (emptyEl) emptyEl.hidden = !!slot;
        const occupied = slot?.dataset.status === 'occupied';
        const available = slot?.dataset.status === 'available';
        exit.disabled = !occupied;
        primary.disabled = !(occupied || available);
        if (isLanesPage) {
            const isEntryLane = slot?.dataset.cabinSlot === 'Làn vào';
            $('cabin-primary-label').textContent = isEntryLane ? 'Nhận diện vào' : 'Thanh toán';
        } else {
            $('cabin-primary-label').textContent = available ? 'Xe vào' : 'Thanh toán';
        }
        $('cabin-total-label').textContent = 'Tổng tiền';
        if (totalCount) totalCount.textContent = occupied ? '1' : '0';
        if (tabLabel) tabLabel.textContent = slot ? slot.dataset.cabinSlot : (isLanesPage ? '2 làn' : '1-5');
        $('cabin-total').textContent = occupied ? Number(slot.dataset.fee || 0).toLocaleString('vi-VN') : '0';
    }
    function filterLanesRows(query) {
        const q = normalize((query || '').trim());
        document.querySelectorAll('[data-lane-item]').forEach(row => {
            row.hidden = q !== '' && !normalize(row.dataset.laneItem || '').includes(q);
        });
    }
    function filterSlots() {
        if (isLanesPage) {
            filterLanesRows(lanesFilter?.value || search?.value || '');
            return;
        }
        const query = normalize((search?.value || '').trim());
        let visible = 0;
        const counts = { all: 0, occupied: 0, available: 0, maintenance: 0 };
        slots.forEach(slot => {
            const matches = (area === 'all' || slot.dataset.area === area) &&
                normalize(slot.dataset.cabinSlot + ' ' + slot.dataset.area + ' ' + slot.dataset.plate).includes(query);
            if (matches) { counts.all++; counts[slot.dataset.status]++; }
            slot.hidden = !matches || (status !== 'all' && slot.dataset.status !== status);
            if (!slot.hidden) visible++;
        });
        document.querySelectorAll('[data-cabin-count]').forEach(label => {
            label.textContent = counts[label.dataset.cabinCount] || 0;
        });
        const noRes = $('cabin-no-results');
        if (noRes) noRes.hidden = visible > 0;
        if (selected?.hidden) selectSlot(null);
    }
    areaButtons.forEach(button => button.addEventListener('click', () => {
        area = button.dataset.cabinArea;
        areaButtons.forEach(item => {
            item.classList.toggle('active', item === button);
            item.setAttribute('aria-pressed', String(item === button));
        });
        setGridVisible(true);
        filterSlots();
    }));
    statusInputs.forEach(input => input.addEventListener('change', () => {
        status = input.value;
        setGridVisible(true);
        filterSlots();
    }));
    [search, ticketSearch, lanesFilter].filter(Boolean).forEach(input => input.addEventListener('input', () => {
        [search, ticketSearch, lanesFilter].filter(Boolean).forEach(other => {
            if (other !== input) other.value = input.value;
        });
        setGridVisible(true);
        filterSlots();
    }));
    search?.closest('form')?.addEventListener('submit', event => {
        if (isLanesPage) {
            event.preventDefault();
            filterSlots();
            return;
        }
        event.preventDefault();
        filterSlots();
    });
    slots.forEach(slot => slot.addEventListener('click', event => {
        if (event.target.closest('a, button')) return;
        selectSlot(slot);
    }));
    function continueTransaction(useExit) {
        if (!selected || selected.dataset.status === 'maintenance') return;
        const target = useExit ? (selected.dataset.exitUrl || selected.dataset.actionUrl) : selected.dataset.actionUrl;
        if (target) location.assign(target);
    }
    primary?.addEventListener('click', () => continueTransaction(false));
    exit?.addEventListener('click', () => continueTransaction(true));
    $('cabin-note-btn')?.addEventListener('click', () => continueTransaction(false));
    if (isLanesPage) {
        if (slots.length > 0) selectSlot(slots[0]);

        const overviewStreams = new Map();
        document.querySelectorAll('[data-overview-toggle]').forEach(btn => {
            btn.addEventListener('click', async event => {
                event.stopPropagation();
                const dir = btn.dataset.overviewToggle;
                const video = document.querySelector(`[data-overview-video="${dir}"]`);
                const empty = document.querySelector(`[data-overview-empty="${dir}"]`);
                const existing = overviewStreams.get(dir);
                if (existing) {
                    existing.getTracks().forEach(t => t.stop());
                    overviewStreams.delete(dir);
                    if (video) { video.srcObject = null; video.hidden = true; }
                    if (empty) empty.hidden = false;
                    btn.textContent = 'Bật toàn cảnh';
                    btn.setAttribute('aria-pressed', 'false');
                    return;
                }
                if (!navigator.mediaDevices?.getUserMedia) {
                    const small = empty?.querySelector('small');
                    if (small) small.textContent = 'Trình duyệt không hỗ trợ camera trực tiếp';
                    return;
                }
                try {
                    const defaultCam = btn.dataset.defaultDevice;
                    const constraints = { video: defaultCam ? { deviceId: { exact: defaultCam } } : true, audio: false };
                    const stream = await navigator.mediaDevices.getUserMedia(constraints);
                    overviewStreams.set(dir, stream);
                    if (video) { video.srcObject = stream; video.hidden = false; }
                    if (empty) empty.hidden = true;
                    btn.textContent = 'Tắt toàn cảnh';
                    btn.setAttribute('aria-pressed', 'true');
                } catch (_) {
                    const small = empty?.querySelector('small');
                    if (small) small.textContent = 'Không truy cập được camera (kiểm tra quyền)';
                }
            });
        });

        // Simultaneous dual-lane workstation controller (entry + exit inline)
        const laneStreams = new Map();
        const laneTimers = new Map();

        async function populateLaneCameras() {
            if (!navigator.mediaDevices?.enumerateDevices) return;
            try {
                const devices = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'videoinput');
                document.querySelectorAll('[data-lane-camera-select]').forEach((select, idx) => {
                    const current = select.value;
                    select.innerHTML = '';
                    if (!devices.length) {
                        select.innerHTML = '<option value="">Không có camera</option>';
                        return;
                    }
                    devices.forEach((dev, i) => {
                        const opt = document.createElement('option');
                        opt.value = dev.deviceId;
                        opt.textContent = dev.label || `Camera ${i + 1}`;
                        select.appendChild(opt);
                    });
                    const configured = select.dataset.defaultDevice;
                    if (current && Array.from(select.options).some(o => o.value === current)) {
                        select.value = current;
                    } else if (configured && Array.from(select.options).some(o => o.value === configured)) {
                        select.value = configured;
                    } else if (devices[idx]) {
                        select.value = devices[idx].deviceId;
                    }
                });
            } catch (_) { /* ignore permission errors before camera starts */ }
        }
        populateLaneCameras();

        function showLaneFeedback(dir, type, text) {
            const box = document.querySelector(`[data-lane-feedback="${dir}"]`);
            if (!box) return;
            if (!text) { box.hidden = true; box.textContent = ''; box.className = 'lane-feedback'; return; }
            box.hidden = false;
            box.className = `lane-feedback is-${type}`;
            box.textContent = text;
        }

        function setLaneButtonsEnabled(dir, enabled) {
            document.querySelectorAll(`[data-lane-submit="${dir}"]`).forEach(b => { b.disabled = !enabled; });
        }

        function applyLaneResult(dir, data) {
            const tokenInput = document.querySelector(`[data-lane-token="${dir}"]`);
            const checkedInput = document.querySelector(`[data-lane-checked="${dir}"]`);
            const plateInput = document.querySelector(`[data-lane-plate="${dir}"]`);
            const resultWrap = document.querySelector(`[data-lane-result="${dir}"]`);
            const previewImg = document.querySelector(`[data-lane-preview="${dir}"]`);
            const camEmpty = document.querySelector(`[data-lane-cam-empty="${dir}"]`);
            const camStatus = document.querySelector(`[data-lane-cam-status="${dir}"]`);

            if (tokenInput && data.token !== undefined) tokenInput.value = data.token || '';
            if (checkedInput && data.checked_plate !== undefined) checkedInput.value = data.checked_plate || '';
            if (plateInput && data.plate !== undefined) plateInput.value = data.plate || '';
            if (resultWrap && data.html !== undefined) resultWrap.innerHTML = data.html;
            if (data.preview_url && previewImg && !laneStreams.get(dir)) {
                previewImg.src = data.preview_url;
                previewImg.hidden = false;
                if (camEmpty) camEmpty.hidden = true;
            }
            if (camStatus && data.plate) camStatus.textContent = data.plate;
            setLaneButtonsEnabled(dir, Boolean(data.can_confirm && data.token));
            if (data.message) showLaneFeedback(dir, data.ok ? 'success' : 'error', data.message);
            else if (data.error) showLaneFeedback(dir, 'error', data.error);
            else showLaneFeedback(dir, '', '');
        }

        function stopLaneCamera(dir) {
            const timer = laneTimers.get(dir);
            if (timer) { clearTimeout(timer); laneTimers.delete(dir); }
            const stream = laneStreams.get(dir);
            if (stream) {
                stream.getTracks().forEach(t => t.stop());
                laneStreams.delete(dir);
            }
            const video = document.querySelector(`[data-lane-video="${dir}"]`);
            const overlay = document.querySelector(`[data-lane-overlay="${dir}"]`);
            const startBtn = document.querySelector(`[data-lane-start="${dir}"]`);
            const capBtn = document.querySelector(`[data-lane-capture="${dir}"]`);
            const camStatus = document.querySelector(`[data-lane-cam-status="${dir}"]`);
            const camEmpty = document.querySelector(`[data-lane-cam-empty="${dir}"]`);
            const previewImg = document.querySelector(`[data-lane-preview="${dir}"]`);
            if (video) { video.srcObject = null; video.hidden = true; }
            if (overlay) overlay.hidden = true;
            if (startBtn) startBtn.textContent = 'Bật camera';
            if (capBtn) capBtn.disabled = true;
            if (camStatus) camStatus.textContent = 'CHỜ BẬT';
            if (camEmpty && (!previewImg || previewImg.hidden)) camEmpty.hidden = false;
        }

        async function startLaneCamera(dir) {
            if (laneStreams.get(dir)) { stopLaneCamera(dir); return; }
            const select = document.querySelector(`[data-lane-camera-select="${dir}"]`);
            const video = document.querySelector(`[data-lane-video="${dir}"]`);
            const overlay = document.querySelector(`[data-lane-overlay="${dir}"]`);
            const previewImg = document.querySelector(`[data-lane-preview="${dir}"]`);
            const camEmpty = document.querySelector(`[data-lane-cam-empty="${dir}"]`);
            const startBtn = document.querySelector(`[data-lane-start="${dir}"]`);
            const capBtn = document.querySelector(`[data-lane-capture="${dir}"]`);
            const camStatus = document.querySelector(`[data-lane-cam-status="${dir}"]`);
            if (!navigator.mediaDevices?.getUserMedia || !video) {
                showLaneFeedback(dir, 'error', 'Trình duyệt không hỗ trợ bật camera trực tiếp.');
                return;
            }
            try {
                const deviceId = select?.value;
                const constraints = { video: deviceId ? { deviceId: { exact: deviceId } } : true, audio: false };
                const stream = await navigator.mediaDevices.getUserMedia(constraints);
                laneStreams.set(dir, stream);
                video.srcObject = stream;
                video.hidden = false;
                if (overlay) overlay.hidden = false;
                if (previewImg) previewImg.hidden = true;
                if (camEmpty) camEmpty.hidden = true;
                if (startBtn) startBtn.textContent = 'Dừng camera';
                if (capBtn) capBtn.disabled = false;
                if (camStatus) camStatus.textContent = 'ĐANG CHẠY';
                showLaneFeedback(dir, '', '');
                populateLaneCameras();
            } catch (_) {
                showLaneFeedback(dir, 'error', 'Không mở được camera. Kiểm tra quyền trình duyệt hoặc chọn camera khác.');
            }
        }

        async function captureLaneFrame(dir) {
            const form = document.querySelector(`[data-lane-form="${dir}"]`);
            const video = document.querySelector(`[data-lane-video="${dir}"]`);
            if (!form || !video || !video.videoWidth) return;
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext('2d').drawImage(video, 0, 0);
            const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.92));
            if (!blob) return;
            const fd = new FormData();
            fd.append('image', blob, `${dir}_frame.jpg`);
            fd.append('profile', 'capture');
            const camStatus = document.querySelector(`[data-lane-cam-status="${dir}"]`);
            if (camStatus) camStatus.textContent = 'ĐANG QUÉT...';
            try {
                const res = await fetch(form.dataset.cameraUrl, { method: 'POST', body: fd });
                const data = await res.json();
                if (!res.ok) {
                    showLaneFeedback(dir, 'error', data.error || 'Không nhận diện được khung hình.');
                    if (camStatus) camStatus.textContent = 'ĐANG CHẠY';
                    return;
                }
                applyLaneResult(dir, { ok: true, ...data });
            } catch (_) {
                showLaneFeedback(dir, 'error', 'Lỗi kết nối khi gửi khung hình nhận diện.');
            }
        }

        async function refreshLanesBoardData() {
            try {
                const res = await fetch('/gate/lanes', { headers: { 'X-Requested-With': 'fetch' } });
                if (!res.ok) return;
                const html = await res.text();
                const doc = new DOMParser().parseFromString(html, 'text/html');
                const kpiNew = doc.getElementById('lanes-kpi-bar');
                const actNew = doc.getElementById('lanes-activity');
                const ticketNew = doc.getElementById('lanes-ticket-content');
                if (kpiNew && $('lanes-kpi-bar')) $('lanes-kpi-bar').innerHTML = kpiNew.innerHTML;
                if (actNew && $('lanes-activity')) {
                    const activeTab = document.querySelector('.lanes-tab.active')?.dataset.lanesTab || 'in';
                    $('lanes-activity').innerHTML = actNew.innerHTML;
                    bindActivityControls();
                    const targetTab = document.querySelector(`[data-lanes-tab="${activeTab}"]`);
                    targetTab?.click();
                }
                if (ticketNew && $('lanes-ticket-content')) $('lanes-ticket-content').innerHTML = ticketNew.innerHTML;
            } catch (_) { /* silent refresh fallback */ }
        }

        async function submitLaneAction(dir, action) {
            const form = document.querySelector(`[data-lane-form="${dir}"]`);
            if (!form) return;
            const fd = new FormData(form);
            fd.set('action', action);
            fd.set('inline', '1');
            try {
                const res = await fetch(form.action, { method: 'POST', body: fd });
                const data = await res.json();
                if (action === 'recognize') {
                    applyLaneResult(dir, data);
                    return;
                }
                if (!data.ok) {
                    applyLaneResult(dir, data);
                    return;
                }
                resetLaneCard(dir);
                showLaneFeedback(dir, 'success', data.message || 'Đã xác nhận thành công!');
                if (data.print_invoice && data.invoice_print_url) {
                    const frame = $('lanes-print-frame');
                    if (frame) frame.src = `${data.invoice_print_url}?autoprint=1`;
                }
                refreshLanesBoardData();
            } catch (_) {
                showLaneFeedback(dir, 'error', 'Có lỗi mạng khi xử lý yêu cầu.');
            }
        }

        function resetLaneCard(dir) {
            const form = document.querySelector(`[data-lane-form="${dir}"]`);
            if (!form) return;
            const tokenInput = document.querySelector(`[data-lane-token="${dir}"]`);
            const checkedInput = document.querySelector(`[data-lane-checked="${dir}"]`);
            const plateInput = document.querySelector(`[data-lane-plate="${dir}"]`);
            const noteInput = document.querySelector(`[data-lane-note="${dir}"]`);
            const fileInput = document.querySelector(`[data-lane-file="${dir}"]`);
            const previewImg = document.querySelector(`[data-lane-preview="${dir}"]`);
            const camEmpty = document.querySelector(`[data-lane-cam-empty="${dir}"]`);
            const resultWrap = document.querySelector(`[data-lane-result="${dir}"]`);
            if (tokenInput) tokenInput.value = '';
            if (checkedInput) checkedInput.value = '';
            if (plateInput) plateInput.value = '';
            if (noteInput) noteInput.value = '';
            if (fileInput) fileInput.value = '';
            if (previewImg) { previewImg.hidden = true; previewImg.src = ''; }
            if (camEmpty && !laneStreams.get(dir)) camEmpty.hidden = false;
            if (resultWrap) {
                resultWrap.innerHTML = `<div class="lane-result-placeholder">Chụp từ camera hoặc tải ảnh để nhận diện biển số làn ${dir === 'entry' ? 'vào' : 'ra'}.</div>`;
            }
            setLaneButtonsEnabled(dir, false);
            showLaneFeedback(dir, '', '');
        }

        document.querySelectorAll('[data-lane-mode]').forEach(btn => {
            btn.addEventListener('click', () => {
                const dir = btn.dataset.laneDir;
                const mode = btn.dataset.laneMode;
                document.querySelectorAll(`[data-lane-mode][data-lane-dir="${dir}"]`).forEach(b => {
                    const active = b === btn;
                    b.classList.toggle('is-active', active);
                    b.setAttribute('aria-pressed', String(active));
                });
                const camCtrl = document.querySelector(`[data-lane-controls-camera="${dir}"]`);
                const upCtrl = document.querySelector(`[data-lane-controls-upload="${dir}"]`);
                const srcInput = document.querySelector(`[data-lane-source="${dir}"]`);
                if (camCtrl) camCtrl.hidden = mode !== 'camera';
                if (upCtrl) upCtrl.hidden = mode !== 'upload';
                if (srcInput) srcInput.value = mode;
                if (mode === 'upload') stopLaneCamera(dir);
            });
        });

        document.querySelectorAll('[data-lane-start]').forEach(btn => {
            btn.addEventListener('click', () => startLaneCamera(btn.dataset.laneStart));
        });
        document.querySelectorAll('[data-lane-capture]').forEach(btn => {
            btn.addEventListener('click', () => captureLaneFrame(btn.dataset.laneCapture));
        });
        document.querySelectorAll('[data-lane-recognize]').forEach(btn => {
            btn.addEventListener('click', () => submitLaneAction(btn.dataset.laneRecognize, 'recognize'));
        });
        document.querySelectorAll('[data-lane-recheck]').forEach(btn => {
            btn.addEventListener('click', () => submitLaneAction(btn.dataset.laneRecheck, 'recognize'));
        });
        document.querySelectorAll('[data-lane-submit]').forEach(btn => {
            btn.addEventListener('click', () => submitLaneAction(btn.dataset.laneSubmit, btn.dataset.submitAction || 'confirm'));
        });
        document.querySelectorAll('[data-lane-reset]').forEach(btn => {
            btn.addEventListener('click', () => resetLaneCard(btn.dataset.laneReset));
        });

        function fillExitLane(plate) {
            const clean = (plate || '').trim().toUpperCase();
            if (!clean) return;
            const plateInput = document.querySelector('[data-lane-plate="exit"]');
            const tokenInput = document.querySelector('[data-lane-token="exit"]');
            if (plateInput) {
                plateInput.value = clean;
                plateInput.focus();
            }
            if (tokenInput?.value) {
                submitLaneAction('exit', 'recognize');
            } else {
                showLaneFeedback('exit', 'success', `Đã điền biển số ${clean} vào Làn ra. Hãy chụp camera hoặc tải ảnh để xác nhận.`);
            }
        }

        function bindActivityControls() {
            const laneTabs = Array.from(document.querySelectorAll('[data-lanes-tab]'));
            const lanePanels = Array.from(document.querySelectorAll('[data-lanes-panel]'));
            laneTabs.forEach(tab => tab.addEventListener('click', () => {
                const target = tab.dataset.lanesTab;
                laneTabs.forEach(t => {
                    const active = t === tab;
                    t.classList.toggle('active', active);
                    t.setAttribute('aria-selected', String(active));
                });
                lanePanels.forEach(panel => { panel.hidden = panel.dataset.lanesPanel !== target; });
            }));
            document.querySelectorAll('[data-fill-exit-plate]').forEach(btn => {
                btn.addEventListener('click', e => {
                    e.stopPropagation();
                    fillExitLane(btn.dataset.fillExitPlate);
                });
            });
        }
        bindActivityControls();

        $('lanes-quick-lookup-form')?.addEventListener('submit', e => {
            e.preventDefault();
            fillExitLane($('lanes-plate-lookup')?.value);
        });
    }
    $('cabin-search-focus')?.addEventListener('click', () => search?.focus());
    viewToggle?.addEventListener('click', () => {
        if (scrollWrap) setGridVisible(scrollWrap.hidden);
    });
    $('cabin-reset-filter')?.addEventListener('click', () => {
        if (search) search.value = '';
        if (ticketSearch) ticketSearch.value = '';
        areaButtons[0]?.click();
        if (statusInputs[0]) statusInputs[0].checked = true;
        status = 'all';
        setGridVisible(true);
        filterSlots();
        search?.focus();
    });
    setGridVisible(true);
    filterSlots();
})();
