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
    $('cabin-menu-close')?.addEventListener('click', () => {
        closeMenu();
        menuButton?.focus();
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

    const cabinSettingsDlg = $('cabin-settings-dialog');
    const CABIN_PREFS_KEY = 'cabin_settings_v1';
    const DEFAULT_SHORTCUTS = {
        new_entry: 'F1',
        search_slot: 'F2',
        quick_exit: 'F3',
        capture_scan: 'F8',
        confirm_pay: 'F9',
        refresh_cabin: 'F5',
    };
    function getCabinPrefs() {
        try { return JSON.parse(localStorage.getItem(CABIN_PREFS_KEY) || '{}'); }
        catch (_) { return {}; }
    }
    function getPrefBool(key, defaultVal) {
        const saved = getCabinPrefs();
        return key in saved ? Boolean(saved[key]) : defaultVal;
    }
    function getPrefStr(key, defaultVal) {
        const saved = getCabinPrefs();
        return (key in saved && saved[key]) ? String(saved[key]) : defaultVal;
    }
    function applyPaymentAndDiscountPrefs(root = document) {
        const defPay = getPrefStr('default_payment', 'cash');
        const discUnit = getPrefStr('discount_unit', 'vnd');
        root.querySelectorAll('[data-default-payment-select]').forEach(sel => {
            if (Array.from(sel.options).some(o => o.value === defPay)) {
                sel.value = defPay;
            }
        });
        root.querySelectorAll('[data-discount-unit-label]').forEach(lbl => {
            lbl.textContent = discUnit === 'percent' ? '%' : 'VND';
        });
        root.querySelectorAll('[data-exit-discount-unit]').forEach(hid => {
            hid.value = discUnit;
        });
        root.querySelectorAll('[data-exit-discount-input]').forEach(inp => {
            inp.max = discUnit === 'percent' ? '100' : '';
            inp.oninput = () => {
                const strong = inp.closest('.gate-result-box')?.querySelector('#exit-fee-strong');
                if (!strong) return;
                const base = parseInt(strong.dataset.baseFee || '0', 10);
                const raw = Math.max(0, parseFloat(inp.value || '0') || 0);
                const u = getPrefStr('discount_unit', 'vnd');
                const finalFee = u === 'percent'
                    ? Math.max(0, Math.round(base * (1 - Math.min(100, raw) / 100)))
                    : Math.max(0, base - Math.round(raw));
                strong.textContent = finalFee.toLocaleString('vi-VN') + ' VNĐ';
            };
        });
    }
    function getCabinShortcuts() {
        const saved = getCabinPrefs().shortcuts || {};
        return { ...DEFAULT_SHORTCUTS, ...saved };
    }
    function syncShortcutBadges(shortcuts = getCabinShortcuts()) {
        document.querySelectorAll('[data-shortcut-badge]').forEach(kbd => {
            const key = kbd.dataset.shortcutBadge;
            if (shortcuts[key]) kbd.textContent = shortcuts[key];
        });
        document.querySelectorAll('[data-cabin-shortcut-input]').forEach(inp => {
            const key = inp.dataset.cabinShortcutInput;
            if (shortcuts[key]) inp.value = shortcuts[key];
        });
    }
    function loadCabinPrefs() {
        const saved = getCabinPrefs();
        document.querySelectorAll('[data-cabin-pref]').forEach(el => {
            const key = el.dataset.cabinPref;
            if (key in saved) el.checked = !!saved[key];
        });
        document.querySelectorAll('[data-cabin-pref-radio]').forEach(el => {
            const key = el.dataset.cabinPrefRadio;
            if (key in saved) el.checked = (el.value === saved[key]);
        });
        syncShortcutBadges({ ...DEFAULT_SHORTCUTS, ...(saved.shortcuts || {}) });
    }
    loadCabinPrefs();
    function saveCabinPrefs() {
        try {
            const data = getCabinPrefs();
            document.querySelectorAll('[data-cabin-pref]').forEach(el => {
                data[el.dataset.cabinPref] = !!el.checked;
            });
            document.querySelectorAll('[data-cabin-pref-radio]:checked').forEach(el => {
                data[el.dataset.cabinPrefRadio] = el.value;
            });
            const shortcuts = { ...DEFAULT_SHORTCUTS, ...(data.shortcuts || {}) };
            document.querySelectorAll('[data-cabin-shortcut-input]').forEach(inp => {
                const actionKey = inp.dataset.cabinShortcutInput;
                const val = (inp.value || '').trim();
                if (val && val !== 'Nhấn phím...') shortcuts[actionKey] = val;
            });
            data.shortcuts = shortcuts;
            localStorage.setItem(CABIN_PREFS_KEY, JSON.stringify(data));
            syncShortcutBadges(shortcuts);
            window.dispatchEvent(new CustomEvent('cabin:prefs-updated', { detail: data }));
        } catch (_) { /* ignore storage errors */ }
    }

    function formatKeyCombo(event) {
        if (['Control', 'Shift', 'Alt', 'Meta'].includes(event.key)) return '';
        const parts = [];
        if (event.ctrlKey) parts.push('Ctrl');
        if (event.altKey) parts.push('Alt');
        if (event.shiftKey) parts.push('Shift');
        let k = event.key;
        if (k === ' ') k = 'Space';
        else if (k.length === 1) k = k.toUpperCase();
        else if (/^f\d{1,2}$/i.test(k)) k = k.toUpperCase();
        parts.push(k);
        return parts.join('+');
    }

    // Ghi nhận phím tắt mới khi người dùng bấm vào ô phím tắt trong Cài đặt chung
    document.querySelectorAll('[data-cabin-shortcut-input]').forEach(inp => {
        let prevVal = inp.value;
        inp.addEventListener('focus', () => {
            prevVal = inp.value;
            inp.classList.add('is-recording');
            inp.value = 'Nhấn phím...';
        });
        inp.addEventListener('blur', () => {
            inp.classList.remove('is-recording');
            if (!inp.value || inp.value === 'Nhấn phím...') inp.value = prevVal;
        });
        inp.addEventListener('keydown', event => {
            event.preventDefault();
            event.stopPropagation();
            if (event.key === 'Escape') {
                inp.value = prevVal;
                inp.blur();
                return;
            }
            const combo = formatKeyCombo(event);
            if (!combo) return;
            // Nếu trùng với một hành động khác thì hoán đổi phím của 2 hành động đó
            document.querySelectorAll('[data-cabin-shortcut-input]').forEach(other => {
                if (other !== inp && other.value.toUpperCase() === combo.toUpperCase()) {
                    other.value = prevVal;
                }
            });
            inp.value = combo;
            prevVal = combo;
            saveCabinPrefs();
            inp.blur();
        });
    });

    $('reset-cabin-shortcuts')?.addEventListener('click', () => {
        document.querySelectorAll('[data-cabin-shortcut-input]').forEach(inp => {
            const key = inp.dataset.cabinShortcutInput;
            if (DEFAULT_SHORTCUTS[key]) inp.value = DEFAULT_SHORTCUTS[key];
        });
        saveCabinPrefs();
    });
    // Gạt công tắc là áp dụng ngay (không bắt buộc bấm Lưu).
    document.querySelectorAll('[data-cabin-pref], [data-cabin-pref-radio]').forEach(el => {
        el.addEventListener('change', saveCabinPrefs);
    });
    $('open-cabin-settings')?.addEventListener('click', () => {
        closeMenu();
        loadCabinPrefs();
        if (!cabinSettingsDlg) return;
        if (typeof cabinSettingsDlg.showModal === 'function') cabinSettingsDlg.showModal();
        else cabinSettingsDlg.setAttribute('open', '');
    });
    $('save-cabin-settings')?.addEventListener('click', () => {
        saveCabinPrefs();
        if (!cabinSettingsDlg) return;
        if (typeof cabinSettingsDlg.close === 'function') cabinSettingsDlg.close();
        else cabinSettingsDlg.removeAttribute('open');
    });
    ['close-cabin-settings', 'cancel-cabin-settings'].forEach(btnId => {
        $(btnId)?.addEventListener('click', () => {
            if (!cabinSettingsDlg) return;
            if (typeof cabinSettingsDlg.close === 'function') cabinSettingsDlg.close();
            else cabinSettingsDlg.removeAttribute('open');
        });
    });

    // ===== Modal Báo cáo cuối ngày (KiotViet POS Cashier End-of-Day Report) =====
    const eodDlg = $('cabin-eod-dialog');
    const eodDateInput = $('eod-date-input');
    const eodDateDisplay = $('eod-date-display');
    const eodTemplateSelect = $('eod-template-select');
    const eodReceiverSelect = $('eod-receiver-select');
    const eodCreatorSelect = $('eod-creator-select');
    const eodTrvMenubar = $('eod-trv-menubar');
    const eodThermalMenubar = $('eod-thermal-menubar');
    const eodZoomStage = $('eod-zoom-stage');
    const eodReportBody = $('eod-report-body');
    const eodExportMenu = $('eod-export-menu');
    let eodZoom = 1;
    let eodFitPage = false;

    const fmtDot = n => Number(n || 0).toLocaleString('vi-VN');
    const fmtComma = n => Number(n || 0).toLocaleString('en-US');

    function setEodTemplate(tpl) {
        ['a4', 'k80', 'thermal'].forEach(key => {
            const view = $(`eod-view-${key}`);
            if (view) view.hidden = (key !== tpl);
        });
        const isThermal = (tpl === 'thermal');
        if (eodTrvMenubar) eodTrvMenubar.hidden = isThermal;
        if (eodThermalMenubar) eodThermalMenubar.hidden = !isThermal;
        eodZoom = 1;
        eodFitPage = false;
        $('eod-btn-fit-page')?.classList.remove('is-active');
        eodReportBody?.classList.remove('is-fit-page');
        if (eodZoomStage) eodZoomStage.style.transform = '';
    }

    function renderEodReport(r) {
        if (!r) return;
        if (eodDateDisplay && r.date_vdate) eodDateDisplay.value = r.date_vdate;
        if (eodDateInput && r.date_iso) eodDateInput.value = r.date_iso;

        document.querySelectorAll('[data-eod-field="generated_at"]').forEach(el => { el.textContent = r.generated_at || ''; });
        document.querySelectorAll('[data-eod-field="date_vdate"]').forEach(el => { el.textContent = r.date_vdate || ''; });
        document.querySelectorAll('[data-eod-field="branch_name"]').forEach(el => { el.textContent = r.branch_name || 'Trung tâm (Tất cả cổng)'; });
        document.querySelectorAll('[data-eod-field="creator_name"]').forEach(el => { el.textContent = r.creator_name || ''; });
        document.querySelectorAll('[data-eod-field="receiver_filter"]').forEach(el => { el.textContent = r.receiver_filter || ''; });
        document.querySelectorAll('[data-eod-field="creator_filter"]').forEach(el => { el.textContent = r.creator_filter || ''; });

        const recLine = $('eod-a4-receiver-line');
        if (recLine) recLine.hidden = !r.receiver_filter;
        const creLine = $('eod-a4-creator-line');
        if (creLine) creLine.hidden = !r.creator_filter;

        // Cập nhật link xuất PDF / Excel theo ngày đang chọn
        const pdfLink = $('eod-export-pdf');
        const xlsxLink = $('eod-export-xlsx');
        if (pdfLink && r.date_iso) pdfLink.href = `/statistics/export/pdf?range=custom&from=${encodeURIComponent(r.date_iso)}&to=${encodeURIComponent(r.date_iso)}`;
        if (xlsxLink && r.date_iso) xlsxLink.href = `/statistics/export/xlsx?range=custom&from=${encodeURIComponent(r.date_iso)}&to=${encodeURIComponent(r.date_iso)}`;

        const setTxt = (id, val) => { const el = $(id); if (el) el.textContent = val; };

        // 1. Khổ A4 (giống Telerik KiotViet: Xe đang gửi + Hóa đơn + Trạng thái trống)
        const a4Tbody = $('eod-a4-tbody');
        if (a4Tbody) {
            const srvList = r.serving_items || [];
            const invList = r.invoices || [];
            if (!srvList.length && !invList.length) {
                a4Tbody.innerHTML = `<tr class="kv-eod-a4-empty"><td colspan="9">Báo cáo không có dữ liệu</td></tr>`;
            } else {
                const rowsHtml = [`<tr class="kv-eod-a4-spacer"><td colspan="9"></td></tr>`];

                if (srvList.length > 0) {
                    rowsHtml.push(`
                      <tr class="kv-eod-a4-summary">
                        <td colspan="4" class="left">Xe đang gửi: ${srvList.length}</td>
                        <td class="right">${fmtDot(r.serving_est_total)}</td>
                        <td class="right">0</td>
                        <td class="right">0</td>
                        <td class="right">0</td>
                        <td class="right">0</td>
                      </tr>
                    `);
                    srvList.forEach((item, idx) => {
                        const rowKey = `srv-${idx}`;
                        rowsHtml.push(`
                          <tr class="kv-eod-a4-group" data-eod-toggle-row="${rowKey}">
                            <td class="left">
                              <button type="button" class="kv-eod-plus-btn" data-eod-plus="${rowKey}" aria-expanded="false">+</button>
                              <span class="kv-eod-group-link">${item.date_only_str}<br>${item.time_hm}</span>
                            </td>
                            <td class="center">${item.time_hm}</td>
                            <td class="center">${item.slot_name} · <b>${item.plate_number}</b></td>
                            <td class="center">${item.qty}</td>
                            <td class="right">${fmtDot(item.revenue)}</td>
                            <td class="right">0</td>
                            <td class="right">0</td>
                            <td class="right">0</td>
                            <td class="right">0</td>
                          </tr>
                          <tr class="kv-eod-a4-detail-row" id="eod-detail-${rowKey}" hidden>
                            <td colspan="9" class="kv-eod-a4-detail-box">
                              <div class="kv-eod-a4-detail-pills">
                                <span>Mã phiếu: <b>${item.code}</b></span>
                                <span>Biển số: <b>${item.plate_number}</b></span>
                                <span>Loại xe: <b>${item.vehicle_type_name}</b></span>
                                <span>Ô đỗ: <b>${item.slot_name}</b></span>
                                <span>Giờ vào: <b>${item.date_time_str}</b></span>
                                <span>Cổng: <b>${item.gate}</b></span>
                                <span>Tạm tính: <b>${fmtDot(item.revenue)} ₫</b></span>
                              </div>
                            </td>
                          </tr>
                        `);
                    });
                }

                if (invList.length > 0) {
                    rowsHtml.push(`
                      <tr class="kv-eod-a4-summary">
                        <td colspan="4" class="left">Hóa đơn: ${invList.length}</td>
                        <td class="right">${fmtDot(r.total_revenue)}</td>
                        <td class="right">0</td>
                        <td class="right">0</td>
                        <td class="right">0</td>
                        <td class="right">${fmtDot(r.total_revenue)}</td>
                      </tr>
                    `);
                    invList.forEach((inv, idx) => {
                        const rowKey = `inv-${idx}`;
                        rowsHtml.push(`
                          <tr class="kv-eod-a4-group" data-eod-toggle-row="${rowKey}">
                            <td class="left">
                              <button type="button" class="kv-eod-plus-btn" data-eod-plus="${rowKey}" aria-expanded="false">+</button>
                              <span class="kv-eod-group-link">${inv.date_only_str}<br>${inv.time_hm}</span>
                            </td>
                            <td class="center">${inv.time_hm}</td>
                            <td class="center">${inv.slot_name} · <b>${inv.plate_number}</b></td>
                            <td class="center">${inv.qty}</td>
                            <td class="right">${fmtDot(inv.revenue)}</td>
                            <td class="right">0</td>
                            <td class="right">0</td>
                            <td class="right">0</td>
                            <td class="right">${fmtDot(inv.paid)}</td>
                          </tr>
                          <tr class="kv-eod-a4-detail-row" id="eod-detail-${rowKey}" hidden>
                            <td colspan="9" class="kv-eod-a4-detail-box">
                              <div class="kv-eod-a4-detail-pills">
                                <span>Mã HĐ: <b>${inv.code}</b></span>
                                <span>Biển số: <b>${inv.plate_number}</b></span>
                                <span>Loại xe: <b>${inv.vehicle_type_name}</b></span>
                                <span>Ô đỗ: <b>${inv.slot_name}</b></span>
                                <span>Vào: <b>${inv.entry_hm}</b> → Ra: <b>${inv.time_hm}</b></span>
                                <span>Hình thức: <b>${inv.payment_label}</b></span>
                                <span>Đã thu: <b>${fmtDot(inv.paid)} ₫</b></span>
                              </div>
                            </td>
                          </tr>
                        `);
                    });
                }

                a4Tbody.innerHTML = rowsHtml.join('');
                a4Tbody.querySelectorAll('[data-eod-toggle-row]').forEach(tr => {
                    tr.addEventListener('click', () => {
                        const key = tr.dataset.eodToggleRow;
                        const detailRow = $(`eod-detail-${key}`);
                        const btn = tr.querySelector(`[data-eod-plus="${key}"]`);
                        if (!detailRow) return;
                        const open = detailRow.hidden;
                        detailRow.hidden = !open;
                        if (btn) {
                            btn.textContent = open ? '−' : '+';
                            btn.setAttribute('aria-expanded', String(open));
                        }
                    });
                });
            }
        }

        // 2. Khổ K80
        setTxt('eod-k80-total-in', fmtDot(r.net_revenue_with_other));
        setTxt('eod-k80-net', fmtDot(r.net_revenue_with_other));
        setTxt('eod-k80-cash', fmtDot(r.cash_total));
        setTxt('eod-k80-transfer', fmtDot(r.transfer_total));
        setTxt('eod-k80-card', fmtDot(r.card_total));
        setTxt('eod-k80-month', fmtDot(r.other_revenue));
        setTxt('eod-k80-inv-count', r.invoice_count);
        setTxt('eod-k80-inv-val', fmtDot(r.total_revenue));
        setTxt('eod-k80-inv-qty', `${r.invoice_count} (${r.distinct_types_out} loại xe)`);
        setTxt('eod-k80-inv-cust', r.invoice_count);
        setTxt('eod-k80-srv-count', r.serving_count);
        setTxt('eod-k80-srv-val', fmtDot(r.serving_est_total));
        setTxt('eod-k80-srv-qty', `${r.serving_count} (${r.distinct_types_in} loại xe)`);
        setTxt('eod-k80-srv-cust', r.serving_count);
        setTxt('eod-k80-cancel-qty', `${r.cancel_count} (0 loại xe)`);

        // 3. Báo cáo cuối ngày (K80) - Thermal
        setTxt('eod-th-gross', fmtComma(r.total_revenue));
        setTxt('eod-th-other', fmtComma(r.other_revenue));
        setTxt('eod-th-net-with', fmtComma(r.net_revenue_with_other));
        setTxt('eod-th-net-no', `${fmtComma(r.net_revenue_no_other)} (100%)`);
        setTxt('eod-th-inv-count', r.invoice_count);
        setTxt('eod-th-cust-count', r.serving_count);
        setTxt('eod-th-avg', fmtComma(r.avg_per_invoice));
        setTxt('eod-th-sales-in', fmtComma(r.total_revenue));
        setTxt('eod-th-sales-cash', fmtComma(r.cash_total));
        const trRow = $('eod-th-sales-transfer-row');
        if (trRow) {
            trRow.hidden = !(r.transfer_total > 0);
            setTxt('eod-th-sales-transfer', fmtComma(r.transfer_total));
        }
        const cardRow = $('eod-th-sales-card-row');
        if (cardRow) {
            cardRow.hidden = !(r.card_total > 0);
            setTxt('eod-th-sales-card', fmtComma(r.card_total));
        }
        setTxt('eod-th-receipt-in', fmtComma(r.other_revenue));
        setTxt('eod-th-actual-in', fmtComma(r.net_revenue_with_other));
        setTxt('eod-th-actual-cash', fmtComma((r.cash_total || 0) + (r.other_revenue || 0)));
        setTxt('eod-th-cancel-qty', r.cancel_count);
    }

    async function fetchEodReport() {
        const dateVal = eodDateInput?.value || '';
        const receiverVal = eodReceiverSelect?.value || '';
        const creatorVal = eodCreatorSelect?.value || '';
        const qs = new URLSearchParams({ date: dateVal, receiver: receiverVal, creator: creatorVal });
        try {
            const res = await fetch(`/api/cabin/eod-report?${qs.toString()}`);
            const data = await res.json();
            if (data && data.ok && data.report) {
                renderEodReport(data.report);
            }
        } catch (_) { /* ignore network errors */ }
    }

    function closeAllEodDropdowns() {
        document.querySelectorAll('[data-eod-dd]').forEach(wrap => {
            wrap.classList.remove('is-open');
            const menu = wrap.querySelector('.kv-eod-dd-menu');
            const btn = wrap.querySelector('.kv-eod-dd-trigger');
            if (menu) menu.hidden = true;
            if (btn) btn.setAttribute('aria-expanded', 'false');
        });
    }

    // Gắn sự kiện cho 3 custom Kendo Dropdowns (Khổ A4, Người tiếp nhận, Người thu phí)
    document.querySelectorAll('[data-eod-dd]').forEach(wrap => {
        const ddType = wrap.dataset.eodDd;
        const hiddenInput = wrap.querySelector('input[type="hidden"]');
        const trigger = wrap.querySelector('.kv-eod-dd-trigger');
        const labelEl = wrap.querySelector('[data-eod-dd-label]');
        const menu = wrap.querySelector('.kv-eod-dd-menu');

        trigger?.addEventListener('click', e => {
            e.stopPropagation();
            const isOpen = !menu.hidden;
            closeAllEodDropdowns();
            closeEodCalendar();
            if (eodExportMenu) eodExportMenu.hidden = true;
            if (!isOpen) {
                menu.hidden = false;
                wrap.classList.add('is-open');
                trigger.setAttribute('aria-expanded', 'true');
            }
        });

        wrap.querySelectorAll('.kv-eod-dd-item').forEach(item => {
            item.addEventListener('click', e => {
                e.stopPropagation();
                const val = item.dataset.val ?? '';
                const text = item.querySelector('span')?.textContent || '';
                if (hiddenInput) hiddenInput.value = val;
                if (labelEl) labelEl.textContent = text;
                wrap.querySelectorAll('.kv-eod-dd-item').forEach(it => it.classList.toggle('is-selected', it === item));
                closeAllEodDropdowns();
                if (ddType === 'template') {
                    setEodTemplate(val);
                } else {
                    fetchEodReport();
                }
            });
        });
    });

    function openEodDialog() {
        closeMenu();
        if (!eodDlg) return;
        if (typeof eodDlg.showModal === 'function') eodDlg.showModal();
        else eodDlg.setAttribute('open', '');
        fetchEodReport();
    }

    function closeEodDialog() {
        if (!eodDlg) return;
        if (eodExportMenu) eodExportMenu.hidden = true;
        closeAllEodDropdowns();
        closeEodCalendar();
        if (typeof eodDlg.close === 'function') eodDlg.close();
        else eodDlg.removeAttribute('open');
    }

    $('open-cabin-eod-report')?.addEventListener('click', openEodDialog);
    $('close-cabin-eod')?.addEventListener('click', closeEodDialog);
    eodDlg?.addEventListener('click', e => {
        if (e.target === eodDlg) closeEodDialog();
        if (eodExportMenu && !eodExportMenu.hidden && !e.target.closest('.kv-trv-export-wrap')) {
            eodExportMenu.hidden = true;
        }
        if (eodCalPopover && !eodCalPopover.hidden && !e.target.closest('#eod-date-field')) {
            closeEodCalendar();
        }
        if (!e.target.closest('[data-eod-dd]')) {
            closeAllEodDropdowns();
        }
    });

    // ===== Lịch chọn ngày 3 cấp kiểu KiotViet (Day -> Month -> Decade/Year, ẩn ngày tương lai) =====
    const VN_MONTH_NAMES = [
        'Tháng Một', 'Tháng Hai', 'Tháng Ba', 'Tháng Tư',
        'Tháng Năm', 'Tháng Sáu', 'Tháng Bảy', 'Tháng Tám',
        'Tháng Chín', 'Tháng Mười', 'Tháng Mười Một', 'Tháng Mười Hai'
    ];
    const eodDateField = $('eod-date-field');
    const eodCalPopover = $('eod-cal-popover');
    const eodCalTitle = $('eod-cal-title');
    const eodCalWeekdays = $('eod-cal-weekdays');
    const eodCalGrid = $('eod-cal-grid');
    const eodCalTodayBtn = $('eod-cal-today');
    const eodCalPrev = $('eod-cal-prev');
    const eodCalNext = $('eod-cal-next');

    function isoToParts(iso) {
        const m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (!m) {
            const now = new Date();
            return { y: now.getFullYear(), m: now.getMonth() + 1, d: now.getDate() };
        }
        return { y: parseInt(m[1], 10), m: parseInt(m[2], 10), d: parseInt(m[3], 10) };
    }
    function partsToIso(y, m, d) {
        return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    }
    function partsToVdate(y, m, d) {
        return `${String(d).padStart(2, '0')}/${String(m).padStart(2, '0')}/${y}`;
    }

    const initialParts = isoToParts(eodDateInput?.value);
    let calViewYear = initialParts.y;
    let calViewMonth = initialParts.m; // 1..12
    let calViewMode = 'day'; // 'day' | 'month' | 'decade'

    function renderEodCalendar() {
        if (!eodCalGrid) return;
        const selectedParts = isoToParts(eodDateInput?.value);
        const selectedIso = partsToIso(selectedParts.y, selectedParts.m, selectedParts.d);
        const now = new Date();
        const todayParts = { y: now.getFullYear(), m: now.getMonth() + 1, d: now.getDate() };
        const todayIso = partsToIso(todayParts.y, todayParts.m, todayParts.d);

        if (eodCalTodayBtn) {
            eodCalTodayBtn.textContent = `${todayParts.d} ${VN_MONTH_NAMES[todayParts.m - 1]} ${todayParts.y}`;
        }

        if (calViewMode === 'month') {
            if (eodCalWeekdays) eodCalWeekdays.hidden = true;
            eodCalGrid.className = 'kv-cal-grid is-months';
            if (eodCalTitle) eodCalTitle.textContent = `${calViewYear}`;
            if (eodCalNext) eodCalNext.disabled = (calViewYear >= todayParts.y);

            const items = [];
            for (let m = 1; m <= 12; m++) {
                const isFuture = (calViewYear > todayParts.y) || (calViewYear === todayParts.y && m > todayParts.m);
                const isCur = (calViewYear === todayParts.y && m === todayParts.m);
                const isSel = (calViewYear === selectedParts.y && m === selectedParts.m);
                const cls = [
                    'kv-cal-cell-wide',
                    isFuture ? 'is-blank' : '',
                    isCur ? 'is-current' : '',
                    isSel ? 'is-selected' : '',
                ].filter(Boolean).join(' ');
                items.push(`<button type="button" class="${cls}" data-pick-month="${m}" ${isFuture ? 'disabled' : ''}>Thg${m}</button>`);
            }
            eodCalGrid.innerHTML = items.join('');
            eodCalGrid.querySelectorAll('[data-pick-month]').forEach(btn => {
                btn.addEventListener('click', e => {
                    e.stopPropagation();
                    calViewMonth = parseInt(btn.dataset.pickMonth, 10);
                    calViewMode = 'day';
                    renderEodCalendar();
                });
            });
            return;
        }

        if (calViewMode === 'decade') {
            if (eodCalWeekdays) eodCalWeekdays.hidden = true;
            eodCalGrid.className = 'kv-cal-grid is-months';
            const startDecade = Math.floor(calViewYear / 10) * 10;
            const endDecade = Math.min(startDecade + 9, todayParts.y);
            if (eodCalTitle) eodCalTitle.textContent = `${startDecade}-${endDecade}`;
            if (eodCalNext) eodCalNext.disabled = (startDecade + 10 > todayParts.y);

            const items = [];
            for (let i = -1; i <= 10; i++) {
                const y = startDecade + i;
                const isFuture = y > todayParts.y;
                const isOutside = (i === -1 || i === 10);
                const isCur = (y === todayParts.y);
                const isSel = (y === selectedParts.y);
                const cls = [
                    'kv-cal-cell-wide',
                    isFuture ? 'is-blank' : '',
                    isOutside ? 'is-outside' : '',
                    isCur ? 'is-current' : '',
                    isSel ? 'is-selected' : '',
                ].filter(Boolean).join(' ');
                items.push(`<button type="button" class="${cls}" data-pick-year="${y}" ${isFuture ? 'disabled' : ''}>${y}</button>`);
            }
            eodCalGrid.innerHTML = items.join('');
            eodCalGrid.querySelectorAll('[data-pick-year]').forEach(btn => {
                btn.addEventListener('click', e => {
                    e.stopPropagation();
                    calViewYear = parseInt(btn.dataset.pickYear, 10);
                    calViewMode = 'month';
                    renderEodCalendar();
                });
            });
            return;
        }

        // Level 1: Day View
        if (eodCalWeekdays) eodCalWeekdays.hidden = false;
        eodCalGrid.className = 'kv-cal-grid';
        if (eodCalTitle) {
            eodCalTitle.textContent = `${VN_MONTH_NAMES[calViewMonth - 1]} ${calViewYear}`;
        }
        if (eodCalNext) {
            eodCalNext.disabled = (calViewYear > todayParts.y) || (calViewYear === todayParts.y && calViewMonth >= todayParts.m);
        }

        const firstDayJs = new Date(calViewYear, calViewMonth - 1, 1).getDay();
        const startOffset = (firstDayJs + 6) % 7;
        const daysInMonth = new Date(calViewYear, calViewMonth, 0).getDate();
        const prevMonthDays = new Date(calViewYear, calViewMonth - 1, 0).getDate();

        const cells = [];
        for (let i = startOffset - 1; i >= 0; i--) {
            const d = prevMonthDays - i;
            const pm = calViewMonth === 1 ? 12 : calViewMonth - 1;
            const py = calViewMonth === 1 ? calViewYear - 1 : calViewYear;
            cells.push({ y: py, m: pm, d, outside: true });
        }
        for (let d = 1; d <= daysInMonth; d++) {
            cells.push({ y: calViewYear, m: calViewMonth, d, outside: false });
        }
        const totalCells = cells.length <= 35 ? 35 : 42;
        let nextDay = 1;
        while (cells.length < totalCells) {
            const nm = calViewMonth === 12 ? 1 : calViewMonth + 1;
            const ny = calViewMonth === 12 ? calViewYear + 1 : calViewYear;
            cells.push({ y: ny, m: nm, d: nextDay++, outside: true });
        }

        eodCalGrid.innerHTML = cells.map(c => {
            const iso = partsToIso(c.y, c.m, c.d);
            const isFuture = iso > todayIso;
            const isSel = iso === selectedIso;
            const isToday = iso === todayIso;
            const cls = [
                'kv-cal-day',
                isFuture ? 'is-blank' : '',
                c.outside ? 'is-outside' : '',
                isSel ? 'is-selected' : '',
                isToday ? 'is-today' : '',
            ].filter(Boolean).join(' ');
            return `<button type="button" class="${cls}" data-cal-iso="${iso}" data-cal-y="${c.y}" data-cal-m="${c.m}" data-cal-d="${c.d}" ${isFuture ? 'disabled' : ''}>${c.d}</button>`;
        }).join('');

        eodCalGrid.querySelectorAll('[data-cal-iso]').forEach(btn => {
            btn.addEventListener('click', e => {
                e.stopPropagation();
                const y = parseInt(btn.dataset.calY, 10);
                const m = parseInt(btn.dataset.calM, 10);
                const d = parseInt(btn.dataset.calD, 10);
                selectEodDate(y, m, d);
            });
        });
    }

    function selectEodDate(y, m, d) {
        const iso = partsToIso(y, m, d);
        const vdate = partsToVdate(y, m, d);
        if (eodDateInput) eodDateInput.value = iso;
        if (eodDateDisplay) eodDateDisplay.value = vdate;
        calViewYear = y;
        calViewMonth = m;
        calViewMode = 'day';
        closeEodCalendar();
        fetchEodReport();
    }

    function openEodCalendar() {
        if (!eodCalPopover) return;
        closeAllEodDropdowns();
        const cur = isoToParts(eodDateInput?.value);
        calViewYear = cur.y;
        calViewMonth = cur.m;
        calViewMode = 'day';
        renderEodCalendar();
        eodCalPopover.hidden = false;
        eodDateField?.classList.add('is-open');
        $('eod-calendar-btn')?.setAttribute('aria-expanded', 'true');
    }

    function closeEodCalendar() {
        if (!eodCalPopover) return;
        eodCalPopover.hidden = true;
        eodDateField?.classList.remove('is-open');
        $('eod-calendar-btn')?.setAttribute('aria-expanded', 'false');
    }

    function parseVdateToParts(str) {
        const m = String(str || '').trim().match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
        if (!m) return null;
        const d = parseInt(m[1], 10);
        const mo = parseInt(m[2], 10);
        const y = parseInt(m[3], 10);
        if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
        return { y, m: mo, d };
    }

    $('eod-calendar-btn')?.addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        if (eodCalPopover?.hidden) openEodCalendar();
        else closeEodCalendar();
    });
    eodDateDisplay?.addEventListener('click', e => {
        e.stopPropagation();
        openEodCalendar();
    });
    eodCalTitle?.addEventListener('click', e => {
        e.stopPropagation();
        if (calViewMode === 'day') calViewMode = 'month';
        else if (calViewMode === 'month') calViewMode = 'decade';
        renderEodCalendar();
    });
    eodCalPrev?.addEventListener('click', e => {
        e.stopPropagation();
        if (calViewMode === 'day') {
            if (calViewMonth === 1) { calViewMonth = 12; calViewYear -= 1; }
            else calViewMonth -= 1;
        } else if (calViewMode === 'month') {
            calViewYear -= 1;
        } else {
            calViewYear -= 10;
        }
        renderEodCalendar();
    });
    eodCalNext?.addEventListener('click', e => {
        e.stopPropagation();
        if (calViewMode === 'day') {
            if (calViewMonth === 12) { calViewMonth = 1; calViewYear += 1; }
            else calViewMonth += 1;
        } else if (calViewMode === 'month') {
            calViewYear += 1;
        } else {
            calViewYear += 10;
        }
        renderEodCalendar();
    });
    eodCalTodayBtn?.addEventListener('click', e => {
        e.stopPropagation();
        const now = new Date();
        selectEodDate(now.getFullYear(), now.getMonth() + 1, now.getDate());
    });
    eodDateDisplay?.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const parts = parseVdateToParts(eodDateDisplay.value);
            if (parts) selectEodDate(parts.y, parts.m, parts.d);
        } else if (e.key === 'Escape') {
            closeEodCalendar();
        }
    });
    eodDateDisplay?.addEventListener('blur', () => {
        const parts = parseVdateToParts(eodDateDisplay.value);
        if (parts && eodDateInput) {
            const iso = partsToIso(parts.y, parts.m, parts.d);
            eodDateDisplay.value = partsToVdate(parts.y, parts.m, parts.d);
            if (eodDateInput.value !== iso) {
                eodDateInput.value = iso;
                fetchEodReport();
            }
        }
    });
    $('eod-btn-refresh')?.addEventListener('click', fetchEodReport);

    // Menu Xuất PDF / Excel
    $('eod-btn-export')?.addEventListener('click', e => {
        e.stopPropagation();
        closeAllEodDropdowns();
        closeEodCalendar();
        if (!eodExportMenu) return;
        eodExportMenu.hidden = !eodExportMenu.hidden;
    });

    // Nút In báo cáo (in đúng phần đang xem trong modal)
    function printCurrentEodView() {
        const activeView = document.querySelector('.kv-eod-view:not([hidden])');
        if (!activeView) { window.print(); return; }
        const w = window.open('', '_blank', 'width=860,height=720');
        if (!w) { window.print(); return; }
        w.document.write(`<!DOCTYPE html><html lang="vi"><head><meta charset="UTF-8"><title>Báo cáo cuối ngày</title>
          <link rel="stylesheet" href="/css/cabin.css">
          <style>body{margin:18px;background:#fff;font-family:Arial,sans-serif;} .kv-eod-plus-btn{display:none;}</style>
        </head><body>${activeView.outerHTML}</body></html>`);
        w.document.close();
        w.onload = () => { w.focus(); w.print(); };
    }
    $('eod-btn-print')?.addEventListener('click', printCurrentEodView);
    $('eod-btn-print-thermal')?.addEventListener('click', printCurrentEodView);

    // Chế độ xem trang in (Page Layout) & Phóng to / Thu nhỏ & Thu phóng vừa trang (Kính lúp phải cùng)
    $('eod-btn-layout')?.addEventListener('click', e => {
        const active = eodReportBody?.classList.toggle('is-page-preview');
        e.currentTarget.classList.toggle('is-active', Boolean(active));
    });
    $('eod-btn-zoom-in')?.addEventListener('click', () => {
        eodFitPage = false;
        $('eod-btn-fit-page')?.classList.remove('is-active');
        eodReportBody?.classList.remove('is-fit-page');
        eodZoom = Math.min(1.5, +(eodZoom + 0.1).toFixed(2));
        if (eodZoomStage) eodZoomStage.style.transform = `scale(${eodZoom})`;
    });
    $('eod-btn-zoom-out')?.addEventListener('click', () => {
        eodFitPage = false;
        $('eod-btn-fit-page')?.classList.remove('is-active');
        eodReportBody?.classList.remove('is-fit-page');
        eodZoom = Math.max(0.55, +(eodZoom - 0.1).toFixed(2));
        if (eodZoomStage) eodZoomStage.style.transform = eodZoom === 1 ? '' : `scale(${eodZoom})`;
    });
    $('eod-btn-fit-page')?.addEventListener('click', e => {
        eodFitPage = !eodFitPage;
        e.currentTarget.classList.toggle('is-active', eodFitPage);
        eodReportBody?.classList.toggle('is-fit-page', eodFitPage);
        eodZoom = eodFitPage ? 0.56 : 1;
        if (eodZoomStage) eodZoomStage.style.transform = eodFitPage ? 'scale(0.56)' : '';
    });

    // ===== Thực thi phím tắt toàn cục trên tất cả các trang Cabin (/gate, /gate/lanes, /entry, /exit) =====
    function runCabinShortcut(action) {
        const page = document.body.dataset.cabinPage || '';
        if (action === 'new_entry') {
            if (page === 'lanes') {
                const resetBtn = document.querySelector('[data-lane-reset="entry"]');
                resetBtn?.click();
                const plateIn = document.querySelector('[data-lane-plate="entry"]');
                if (plateIn) { plateIn.focus(); plateIn.select?.(); }
            } else if (page === 'entry') {
                const plateEl = $('plate');
                if (plateEl) { plateEl.focus(); plateEl.select?.(); }
            } else {
                const newBtn = document.querySelector('.cabin-new-ticket');
                location.assign(newBtn?.href || '/entry');
            }
            return;
        }
        if (action === 'search_slot') {
            const target = $('cabin-search') || $('lanes-quick-filter') || $('plate');
            if (target) { target.focus(); target.select?.(); }
            return;
        }
        if (action === 'quick_exit') {
            if (page === 'lanes') {
                const lookup = $('lanes-plate-lookup') || document.querySelector('[data-lane-plate="exit"]');
                if (lookup) { lookup.focus(); lookup.select?.(); }
            } else if (page === 'exit') {
                const plateEl = $('plate');
                if (plateEl) { plateEl.focus(); plateEl.select?.(); }
            } else {
                const primaryBtn = $('cabin-primary-action');
                const activeSlot = document.querySelector('[data-cabin-slot][aria-pressed="true"]');
                if (primaryBtn && !primaryBtn.disabled && activeSlot?.dataset.status === 'occupied') {
                    primaryBtn.click();
                } else {
                    const exitTab = document.querySelector('.cabin-tab.exit');
                    location.assign(exitTab?.href || '/exit');
                }
            }
            return;
        }
        if (action === 'capture_scan') {
            if (page === 'lanes') {
                const activeLane = document.activeElement?.closest?.('[data-lane-form]')?.dataset?.laneForm;
                const dirs = activeLane ? [activeLane] : ['entry', 'exit'];
                for (const dir of dirs) {
                    const capBtn = document.querySelector(`[data-lane-capture="${dir}"]`);
                    const startBtn = document.querySelector(`[data-lane-start="${dir}"]`);
                    const recBtn = document.querySelector(`[data-lane-recognize="${dir}"]`);
                    const upCtrl = document.querySelector(`[data-lane-controls-upload="${dir}"]`);
                    if (upCtrl && !upCtrl.hidden && recBtn && !recBtn.disabled) {
                        recBtn.click();
                        return;
                    }
                    if (capBtn && !capBtn.disabled) {
                        capBtn.click();
                        return;
                    }
                    if (startBtn) {
                        startBtn.click();
                        return;
                    }
                }
            } else if (page === 'entry' || page === 'exit') {
                const capBtn = $('camera-capture');
                const startBtn = $('camera-start');
                const imgRecBtn = $('image-recognize-button');
                const upPanel = $('upload-panel');
                if (upPanel && !upPanel.hidden && imgRecBtn) {
                    imgRecBtn.click();
                } else if (capBtn && !capBtn.disabled) {
                    capBtn.click();
                } else if (startBtn) {
                    startBtn.click();
                }
            }
            return;
        }
        if (action === 'confirm_pay') {
            // Nếu modal thanh toán POS đang mở trên trang Xe ra
            const posModal = $('pos-payment-modal');
            const posConfirm = $('pos-modal-confirm-btn');
            if (posModal && !posModal.hidden && posConfirm && !posConfirm.disabled) {
                posConfirm.click();
                return;
            }
            if (page === 'lanes') {
                const activeLane = document.activeElement?.closest?.('[data-lane-form]')?.dataset?.laneForm;
                const candidates = activeLane
                    ? [
                        document.querySelector(`[data-lane-submit="${activeLane}"][data-submit-action="pay"]`),
                        document.querySelector(`[data-lane-submit="${activeLane}"][data-submit-action="confirm"]`),
                    ]
                    : [
                        document.querySelector('[data-lane-submit="exit"][data-submit-action="pay"]'),
                        document.querySelector('[data-lane-submit="exit"][data-submit-action="confirm"]'),
                        document.querySelector('[data-lane-submit="entry"][data-submit-action="confirm"]'),
                    ];
                const btn = candidates.find(b => b && !b.disabled);
                btn?.click();
            } else if (page === 'entry' || page === 'exit') {
                const payBtn = $('pay-button');
                const confirmBtn = $('confirm-button');
                if (payBtn && !payBtn.disabled) payBtn.click();
                else if (confirmBtn && !confirmBtn.disabled) confirmBtn.click();
            } else {
                const primaryBtn = $('cabin-primary-action');
                if (primaryBtn && !primaryBtn.disabled) primaryBtn.click();
            }
            return;
        }
        if (action === 'refresh_cabin') {
            location.reload();
        }
    }

    document.addEventListener('keydown', event => {
        if (event.target?.matches?.('[data-cabin-shortcut-input]')) return;
        if (cabinSettingsDlg?.open || eodDlg?.open) return;
        const combo = formatKeyCombo(event);
        if (!combo) return;
        const shortcuts = getCabinShortcuts();
        const matchedAction = Object.keys(shortcuts).find(
            act => (shortcuts[act] || '').toUpperCase() === combo.toUpperCase()
        );
        if (!matchedAction) return;
        // Nếu người dùng gán phím chỉ gồm 1 ký tự chữ/số đơn lẻ thì không kích hoạt khi đang gõ trong input/textarea
        const isSingleChar = combo.length === 1 && !event.ctrlKey && !event.altKey;
        const isTyping = event.target?.matches?.('input, textarea, select, [contenteditable="true"]');
        if (isSingleChar && isTyping) return;
        event.preventDefault();
        closeMenu();
        runCabinShortcut(matchedAction);
    });

    // Bấm chuột trực tiếp vào từng dòng trong menu "Phím tắt" cũng thực thi ngay thao tác đó
    document.querySelectorAll('[data-run-shortcut]').forEach(btn => {
        btn.addEventListener('click', () => {
            closeMenu();
            runCabinShortcut(btn.dataset.runShortcut);
        });
    });

    // Cảnh báo khi bãi xe sắp hết chỗ trống (nếu bật trong Cài đặt chung)
    function checkLowSlotsWarning() {
        const existingBanner = $('cabin-low-slots-banner');
        if (!getPrefBool('warn_low_slots', true)) {
            existingBanner?.remove();
            return;
        }
        let availCount = null;
        const countEl = document.querySelector('[data-cabin-count="available"]');
        if (countEl) {
            availCount = parseInt(countEl.textContent || '', 10);
        } else {
            const kpiSub = document.querySelector('#lanes-kpi-bar .lanes-kpi-sub');
            const m = kpiSub?.textContent?.match(/(\d+)\s*chỗ còn trống/i);
            if (m) availCount = parseInt(m[1], 10);
        }
        if (availCount !== null && !Number.isNaN(availCount) && availCount <= 3) {
            if (!existingBanner) {
                const bar = document.createElement('div');
                bar.id = 'cabin-low-slots-banner';
                bar.style.cssText = 'position:fixed;bottom:14px;left:16px;z-index:90;padding:8px 14px;border-radius:10px;background:#fff4e5;border:1px solid #f59e0b;color:#92400e;font-size:12px;font-weight:600;box-shadow:0 6px 18px rgba(0,0,0,0.15);';
                bar.textContent = availCount === 0
                    ? '⚠️ Bãi xe đã hết chỗ trống (0 chỗ trống)!'
                    : `⚠️ Cảnh báo: Bãi xe sắp đầy, chỉ còn ${availCount} chỗ trống!`;
                document.body.appendChild(bar);
            } else {
                existingBanner.textContent = availCount === 0
                    ? '⚠️ Bãi xe đã hết chỗ trống (0 chỗ trống)!'
                    : `⚠️ Cảnh báo: Bãi xe sắp đầy, chỉ còn ${availCount} chỗ trống!`;
            }
        } else {
            existingBanner?.remove();
        }
    }
    applyPaymentAndDiscountPrefs();
    checkLowSlotsWarning();
    window.addEventListener('cabin:prefs-updated', () => {
        applyPaymentAndDiscountPrefs();
        checkLowSlotsWarning();
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
        if (isLanesPage) return;
        details.forEach(item => { item.hidden = !slot || item.dataset.cabinDetail !== slot.dataset.cabinSlot; });
        const emptyEl = $('cabin-ticket-empty');
        if (emptyEl) emptyEl.hidden = !!slot;
        const footerEl = $('cabin-ticket-footer');
        if (footerEl) footerEl.hidden = !slot;
        const occupied = slot?.dataset.status === 'occupied';
        const available = slot?.dataset.status === 'available';
        if (exit) exit.disabled = !slot;
        if (primary) primary.disabled = !(occupied || available);
        const primaryLabel = $('cabin-primary-label');
        if (primaryLabel) primaryLabel.textContent = available ? 'Nhận xe vào ô này' : 'Xử lý xe ra & Thu phí';
        const totalLabel = $('cabin-total-label');
        if (totalLabel) totalLabel.textContent = occupied ? 'Phí tạm tính' : (available ? 'Trạng thái' : 'Bảo trì');
        if (totalCount) totalCount.textContent = occupied ? '1' : '0';
        if (tabLabel) tabLabel.textContent = slot ? slot.dataset.cabinSlot : '1-5';
        const totalEl = $('cabin-total');
        if (totalEl) {
            totalEl.textContent = occupied
                ? (Number(slot.dataset.fee || 0).toLocaleString('vi-VN') + ' đ')
                : (available ? 'Ô trống' : 'Ngừng nhận xe');
        }
    }
    function filterLanesRows(query) {
        const q = normalize((query || '').trim());
        document.querySelectorAll('[data-lane-item]').forEach(row => {
            row.hidden = q !== '' && !normalize(row.dataset.laneItem || '').includes(q);
        });
    }
    function filterSlots() {
        if (isLanesPage) {
            filterLanesRows($('lanes-quick-filter')?.value || search?.value || '');
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
    document.querySelectorAll('[data-cabin-deselect]').forEach(btn => {
        btn.addEventListener('click', () => selectSlot(null));
    });
    document.querySelectorAll('[data-pick-slot-btn]').forEach(btn => {
        btn.addEventListener('click', () => {
            const target = slots.find(s => s.dataset.cabinSlot === btn.dataset.pickSlotBtn);
            if (!target) return;
            target.hidden = false;
            setGridVisible(true);
            selectSlot(target);
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
    });
    $('cabin-note-btn')?.addEventListener('click', () => continueTransaction(false));
    function isIpCameraSource(val) {
        if (!val) return false;
        const s = String(val).trim();
        return /^(https?|rtsps?):\/\//i.test(s) || /^[a-zA-Z0-9._-]+:\d{2,5}(\/.*)?$/.test(s);
    }
    function ipStreamUrl(slot, rawUrl) {
        return `/gate/camera-stream/${slot}?url=${encodeURIComponent(rawUrl.trim())}&t=${Date.now()}`;
    }

    const overviewStreams = new Map();
    const overviewIpActive = new Set();
    document.querySelectorAll('[data-overview-toggle]').forEach(btn => {
        btn.addEventListener('click', async event => {
            event.stopPropagation();
            const dir = btn.dataset.overviewToggle;
            const video = document.querySelector(`[data-overview-video="${dir}"]`);
            const streamImg = document.querySelector(`[data-overview-stream="${dir}"]`);
            const empty = document.querySelector(`[data-overview-empty="${dir}"]`);
            const existing = overviewStreams.get(dir);
            if (existing || overviewIpActive.has(dir)) {
                if (existing) {
                    existing.getTracks().forEach(t => t.stop());
                    overviewStreams.delete(dir);
                }
                overviewIpActive.delete(dir);
                if (video) { video.srcObject = null; video.hidden = true; }
                if (streamImg) { streamImg.onload = null; streamImg.onerror = null; streamImg.src = ''; streamImg.hidden = true; }
                if (empty) empty.hidden = false;
                btn.textContent = 'Bật toàn cảnh';
                btn.setAttribute('aria-pressed', 'false');
                return;
            }
            const defaultCam = (btn.dataset.defaultDevice || '').trim();
            if (isIpCameraSource(defaultCam) && streamImg) {
                const small = empty?.querySelector('small');
                if (small) small.textContent = 'Đang kết nối camera IP…';
                overviewIpActive.add(dir);
                streamImg.hidden = false;
                if (video) video.hidden = true;
                if (empty) empty.hidden = true;
                btn.textContent = 'Tắt toàn cảnh';
                btn.setAttribute('aria-pressed', 'true');
                streamImg.onload = () => {
                    if (!overviewIpActive.has(dir)) return;
                    streamImg.hidden = false;
                    if (empty) empty.hidden = true;
                };
                streamImg.onerror = () => {
                    overviewIpActive.delete(dir);
                    streamImg.src = '';
                    streamImg.hidden = true;
                    if (empty) empty.hidden = false;
                    if (small) small.textContent = 'Không kết nối được camera IP (kiểm tra Start server & Wi-Fi)';
                    btn.textContent = 'Bật toàn cảnh';
                    btn.setAttribute('aria-pressed', 'false');
                };
                streamImg.src = ipStreamUrl(`${dir}_overview`, defaultCam);
                return;
            }
            if (!navigator.mediaDevices?.getUserMedia) {
                const small = empty?.querySelector('small');
                if (small) small.textContent = 'Trình duyệt không hỗ trợ camera trực tiếp';
                return;
            }
            try {
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

    if (isLanesPage) {
        if (slots.length > 0) selectSlot(slots[0]);

        // Simultaneous dual-lane workstation controller (entry + exit inline)
        // Mỗi làn (entry / exit) có trạng thái riêng: camera, yêu cầu đang chạy, kết quả mới nhất.
        // Hai làn không dùng chung biến trạng thái nên có thể thao tác vào / ra cùng lúc.
        const laneStreams = new Map();
        const laneIpStreams = new Map();
        const laneStarting = new Set();    // dir đang trong quá trình mở camera (tránh gọi trùng)
        const laneTimers = new Map();
        const laneBusy = new Map();        // dir -> true khi làn đang gửi yêu cầu
        const laneCanConfirm = new Map();  // dir -> kết quả đối chiếu cho phép xác nhận
        const laneSeq = new Map();         // dir -> số thứ tự yêu cầu, bỏ phản hồi cũ

        function nextLaneSeq(dir) {
            const n = (laneSeq.get(dir) || 0) + 1;
            laneSeq.set(dir, n);
            return n;
        }
        const isLatestLaneSeq = (dir, n) => laneSeq.get(dir) === n;
        const laneCameraOn = dir => laneStreams.has(dir) || laneIpStreams.has(dir);

        function refreshLaneControls(dir) {
            const busy = Boolean(laneBusy.get(dir));
            document.querySelectorAll(`[data-lane-submit="${dir}"]`).forEach(b => {
                b.disabled = busy || !laneCanConfirm.get(dir);
            });
            document.querySelectorAll(`[data-lane-recognize="${dir}"], [data-lane-recheck="${dir}"]`).forEach(b => {
                b.disabled = busy;
            });
            const capBtn = document.querySelector(`[data-lane-capture="${dir}"]`);
            if (capBtn) capBtn.disabled = busy || !laneCameraOn(dir);
        }

        function setLaneBusy(dir, busy) {
            laneBusy.set(dir, busy);
            const form = document.querySelector(`[data-lane-form="${dir}"]`);
            if (form) {
                form.classList.toggle('is-busy', busy);
                form.setAttribute('aria-busy', String(busy));
            }
            refreshLaneControls(dir);
        }

        async function readLaneJson(res) {
            try { return await res.json(); } catch (_) { return { ok: false, error: `Máy chủ trả lỗi (${res.status}).` }; }
        }

        async function populateLaneCameras() {
            let devices = [];
            if (navigator.mediaDevices?.enumerateDevices) {
                try {
                    devices = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'videoinput');
                } catch (_) { /* ignore permission errors before camera starts */ }
            }
            document.querySelectorAll('[data-lane-camera-select]').forEach((select, idx) => {
                const dir = select.dataset.laneCameraSelect;
                const savedCam = (() => { try { return localStorage.getItem('smart-parking-camera-' + dir) || ''; } catch (_) { return ''; } })();
                const current = select.value;
                const configured = (select.dataset.defaultDevice || '').trim();
                const rawIpList = (select.dataset.ipCameras || '').split('|').map(s => s.trim()).filter(Boolean);
                if (configured) rawIpList.unshift(configured);
                const seenIp = new Set();
                const ipList = rawIpList.filter(item => {
                    if (!isIpCameraSource(item) || seenIp.has(item)) return false;
                    seenIp.add(item);
                    return true;
                });
                select.innerHTML = '';
                ipList.forEach(ipUrl => {
                    const ipOpt = document.createElement('option');
                    ipOpt.value = ipUrl;
                    ipOpt.textContent = `Camera IP (${ipUrl})`;
                    select.appendChild(ipOpt);
                });
                devices.forEach((dev, i) => {
                    const opt = document.createElement('option');
                    opt.value = dev.deviceId;
                    opt.textContent = dev.label || `Camera ${i + 1}`;
                    select.appendChild(opt);
                });
                if (!select.options.length) {
                    select.innerHTML = '<option value="">Không có camera</option>';
                    return;
                }
                if (current && Array.from(select.options).some(o => o.value === current)) {
                    select.value = current;
                } else if (configured && Array.from(select.options).some(o => o.value === configured)) {
                    select.value = configured;
                } else if (savedCam && Array.from(select.options).some(o => o.value === savedCam)) {
                    select.value = savedCam;
                } else if (devices[idx]) {
                    select.value = devices[idx].deviceId;
                }
            });
        }
        const initialCamerasReady = populateLaneCameras();

        function showLaneFeedback(dir, type, text) {
            const box = document.querySelector(`[data-lane-feedback="${dir}"]`);
            if (!box) return;
            if (!text) { box.hidden = true; box.textContent = ''; box.className = 'lane-feedback'; return; }
            box.hidden = false;
            box.className = `lane-feedback is-${type}`;
            box.textContent = text;
        }

        function setLaneButtonsEnabled(dir, enabled) {
            laneCanConfirm.set(dir, Boolean(enabled));
            refreshLaneControls(dir);
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
            if (resultWrap && data.html !== undefined) {
                resultWrap.innerHTML = data.html;
                applyPaymentAndDiscountPrefs(resultWrap);
            }
            if (data.preview_url && previewImg && !laneStreams.get(dir) && !laneIpStreams.get(dir)) {
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
            laneIpStreams.delete(dir);
            const video = document.querySelector(`[data-lane-video="${dir}"]`);
            const streamImg = document.querySelector(`[data-lane-stream="${dir}"]`);
            const overlay = document.querySelector(`[data-lane-overlay="${dir}"]`);
            const startBtn = document.querySelector(`[data-lane-start="${dir}"]`);
            const capBtn = document.querySelector(`[data-lane-capture="${dir}"]`);
            const camStatus = document.querySelector(`[data-lane-cam-status="${dir}"]`);
            const camEmpty = document.querySelector(`[data-lane-cam-empty="${dir}"]`);
            const previewImg = document.querySelector(`[data-lane-preview="${dir}"]`);
            if (video) { video.srcObject = null; video.hidden = true; }
            if (streamImg) { streamImg.onload = null; streamImg.onerror = null; streamImg.src = ''; streamImg.hidden = true; }
            if (overlay) overlay.hidden = true;
            if (startBtn) startBtn.textContent = 'Bật camera';
            if (capBtn) capBtn.disabled = true;
            if (camStatus) camStatus.textContent = 'CHỜ BẬT';
            if (camEmpty && (!previewImg || previewImg.hidden)) camEmpty.hidden = false;
        }

        async function startLaneCamera(dir, { forceOn = false } = {}) {
            if (laneStarting.has(dir)) return;
            if (laneStreams.get(dir) || laneIpStreams.get(dir)) {
                if (!forceOn) stopLaneCamera(dir);
                return;
            }
            const select = document.querySelector(`[data-lane-camera-select="${dir}"]`);
            const video = document.querySelector(`[data-lane-video="${dir}"]`);
            const streamImg = document.querySelector(`[data-lane-stream="${dir}"]`);
            const overlay = document.querySelector(`[data-lane-overlay="${dir}"]`);
            const previewImg = document.querySelector(`[data-lane-preview="${dir}"]`);
            const camEmpty = document.querySelector(`[data-lane-cam-empty="${dir}"]`);
            const startBtn = document.querySelector(`[data-lane-start="${dir}"]`);
            const camStatus = document.querySelector(`[data-lane-cam-status="${dir}"]`);
            const deviceId = (select?.value || select?.dataset.defaultDevice || '').trim();

            if (isIpCameraSource(deviceId) && streamImg) {
                laneIpStreams.set(dir, deviceId);
                if (camStatus) camStatus.textContent = 'ĐANG KẾT NỐI...';
                if (startBtn) startBtn.textContent = 'Dừng camera';
                streamImg.hidden = false;
                if (video) video.hidden = true;
                if (previewImg) previewImg.hidden = true;
                if (camEmpty) camEmpty.hidden = true;
                showLaneFeedback(dir, '', '');
                streamImg.onload = () => {
                    if (!laneIpStreams.has(dir)) return;
                    streamImg.hidden = false;
                    refreshLaneControls(dir);
                    if (camStatus) camStatus.textContent = 'ĐANG CHẠY';
                    scheduleAutoRecognize(dir);
                };
                streamImg.onerror = () => {
                    stopLaneCamera(dir);
                    showLaneFeedback(dir, 'error', 'Không kết nối được camera điện thoại. Kiểm tra lại IP Webcam đã bấm Start server và cùng Wi-Fi.');
                };
                streamImg.src = ipStreamUrl(`${dir}_plate`, deviceId);
                return;
            }

            if (!navigator.mediaDevices?.getUserMedia || !video) {
                showLaneFeedback(dir, 'error', 'Trình duyệt không hỗ trợ bật camera trực tiếp.');
                return;
            }
            laneStarting.add(dir);
            try {
                let stream = null;
                // Nếu làn còn lại đang mở cùng một webcam (hoặc máy chỉ có 1 webcam), clone stream để 2 làn chạy song song không xung đột phần cứng.
                const otherDir = dir === 'entry' ? 'exit' : 'entry';
                const otherStream = laneStreams.get(otherDir);
                if (otherStream) {
                    const otherTrack = otherStream.getVideoTracks()[0];
                    const otherDevId = otherTrack?.getSettings?.()?.deviceId || '';
                    if (!deviceId || !otherDevId || deviceId === otherDevId) {
                        stream = otherStream.clone();
                    }
                }
                if (!stream) {
                    const constraints = { video: deviceId ? { deviceId: { exact: deviceId } } : true, audio: false };
                    try {
                        stream = await navigator.mediaDevices.getUserMedia(constraints);
                    } catch (err) {
                        if (otherStream) {
                            stream = otherStream.clone();
                        } else if (deviceId) {
                            stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
                        } else {
                            throw err;
                        }
                    }
                }
                laneStreams.set(dir, stream);
                video.srcObject = stream;
                video.hidden = false;
                if (overlay) overlay.hidden = false;
                if (previewImg) previewImg.hidden = true;
                if (camEmpty) camEmpty.hidden = true;
                if (startBtn) startBtn.textContent = 'Dừng camera';
                refreshLaneControls(dir);
                if (camStatus) camStatus.textContent = 'ĐANG CHẠY';
                showLaneFeedback(dir, '', '');
                await populateLaneCameras();
                scheduleAutoRecognize(dir);
            } catch (_) {
                showLaneFeedback(dir, 'error', 'Không mở được camera. Kiểm tra quyền trình duyệt hoặc chọn camera khác.');
            } finally {
                laneStarting.delete(dir);
            }
        }

        async function captureLaneFrame(dir, auto = false) {
            if (laneBusy.get(dir)) return;
            const form = document.querySelector(`[data-lane-form="${dir}"]`);
            const video = document.querySelector(`[data-lane-video="${dir}"]`);
            const streamImg = document.querySelector(`[data-lane-stream="${dir}"]`);
            const usingIp = laneIpStreams.has(dir);
            const sourceEl = usingIp ? streamImg : video;
            const width = usingIp ? (streamImg?.naturalWidth || 0) : (video?.videoWidth || 0);
            const height = usingIp ? (streamImg?.naturalHeight || 0) : (video?.videoHeight || 0);
            if (!form || !sourceEl || !width || !height) return;
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            canvas.getContext('2d').drawImage(sourceEl, 0, 0);
            const seq = nextLaneSeq(dir);
            setLaneBusy(dir, true);
            const camStatus = document.querySelector(`[data-lane-cam-status="${dir}"]`);
            const idleStatus = () => (laneCameraOn(dir) ? (autoOn() ? 'TỰ ĐỘNG QUÉT' : 'ĐANG CHẠY') : 'CHỜ BẬT');
            if (camStatus) camStatus.textContent = 'ĐANG QUÉT...';
            try {
                const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.92));
                if (!blob) return;
                const fd = new FormData();
                fd.append('image', blob, `${dir}_frame.jpg`);
                fd.append('profile', 'capture');
                // Bỏ ảnh tạm của lần quét trước trên chính làn này (không ảnh hưởng làn kia).
                const oldToken = document.querySelector(`[data-lane-token="${dir}"]`)?.value;
                const res = await fetch(form.dataset.cameraUrl, { method: 'POST', body: fd });
                const data = await readLaneJson(res);
                if (!isLatestLaneSeq(dir, seq)) {
                    if (data.token) discardLaneToken(form, data.token);
                    return;
                }
                if (!res.ok) {
                    // Chế độ tự động: khung hình chưa có xe là chuyện bình thường -> im lặng quét tiếp.
                    if (!auto) showLaneFeedback(dir, 'error', data.error || 'Không nhận diện được khung hình.');
                    if (camStatus) camStatus.textContent = idleStatus();
                    return;
                }
                if (auto) {
                    const plateKey = (data.plate || '').replace(/[^A-Z0-9]/gi, '').toUpperCase();
                    const recent = laneLastPlate.get(dir);
                    const isRepeat = recent && recent.key === plateKey && (Date.now() - recent.at) < AUTO_REPEAT_MS;
                    if (!plateKey || isRepeat) {
                        // Không thấy biển số, hoặc vẫn là xe vừa xử lý xong còn đứng trước camera.
                        if (data.token) discardLaneToken(form, data.token);
                        if (camStatus) camStatus.textContent = idleStatus();
                        return;
                    }
                    laneLastPlate.set(dir, { key: plateKey, at: Date.now() });
                }
                if (oldToken && oldToken !== data.token) discardLaneToken(form, oldToken);
                applyLaneResult(dir, { ok: true, ...data });
                if (data.plate) playDetectBeep();
                if (camStatus && !data.plate) camStatus.textContent = idleStatus();
            } catch (_) {
                if (!auto && isLatestLaneSeq(dir, seq)) showLaneFeedback(dir, 'error', 'Lỗi kết nối khi gửi khung hình nhận diện.');
            } finally {
                setLaneBusy(dir, false);
                scheduleAutoRecognize(dir);
            }
        }

        // ===== Tự động nhận diện (không cần bấm "Chụp & quét") =====
        const AUTO_INTERVAL_MS = 2000;   // chu kỳ quét khung hình
        const AUTO_REPEAT_MS = 20000;    // bỏ qua cùng một biển số trong 20 giây (xe vừa xử lý xong)
        const laneLastPlate = new Map(); // dir -> { key, at }
        const autoOn = () => Boolean(getCabinPrefs().auto_recognize);

        let beepCtx = null;
        function playDetectBeep() {
            if (getCabinPrefs().beep_on_detect === false) return;
            try {
                beepCtx = beepCtx || new (window.AudioContext || window.webkitAudioContext)();
                const osc = beepCtx.createOscillator();
                const gain = beepCtx.createGain();
                osc.type = 'sine';
                osc.frequency.value = 880;
                gain.gain.setValueAtTime(0.15, beepCtx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.001, beepCtx.currentTime + 0.25);
                osc.connect(gain).connect(beepCtx.destination);
                osc.start();
                osc.stop(beepCtx.currentTime + 0.25);
            } catch (_) { /* trình duyệt chặn âm thanh -> bỏ qua */ }
        }

        function laneHasPendingPlate(dir) {
            const token = document.querySelector(`[data-lane-token="${dir}"]`)?.value;
            const plate = document.querySelector(`[data-lane-plate="${dir}"]`)?.value;
            return Boolean(token && plate);
        }

        function scheduleAutoRecognize(dir, delay = AUTO_INTERVAL_MS) {
            const prev = laneTimers.get(dir);
            if (prev) { clearTimeout(prev); laneTimers.delete(dir); }
            if (!autoOn() || !laneCameraOn(dir)) return;
            const camStatus = document.querySelector(`[data-lane-cam-status="${dir}"]`);
            if (camStatus && !laneBusy.get(dir) && !laneHasPendingPlate(dir)) camStatus.textContent = 'TỰ ĐỘNG QUÉT';
            const timer = setTimeout(() => {
                laneTimers.delete(dir);
                if (!autoOn() || !laneCameraOn(dir)) return;
                const typing = document.activeElement?.matches?.(`[data-lane-plate="${dir}"], [data-lane-note="${dir}"]`);
                // Đang có biển số chờ nhân viên xác nhận / đang gõ tay -> chờ, không ghi đè kết quả.
                if (laneBusy.get(dir) || laneHasPendingPlate(dir) || typing) {
                    scheduleAutoRecognize(dir);
                } else {
                    captureLaneFrame(dir, true);
                }
            }, delay);
            laneTimers.set(dir, timer);
        }

        let lastAutoStartPref = Boolean(getCabinPrefs().auto_start_camera);
        async function applyAutoPrefs() {
            await initialCamerasReady;
            const prefs = getCabinPrefs();
            const currentAutoStart = Boolean(prefs.auto_start_camera);
            const turnedOffAutoStart = lastAutoStartPref && !currentAutoStart;
            lastAutoStartPref = currentAutoStart;

            for (const dir of ['entry', 'exit']) {
                if (!document.querySelector(`[data-lane-form="${dir}"]`)) continue;
                const capBtn = document.querySelector(`[data-lane-capture="${dir}"]`);
                if (capBtn) capBtn.textContent = autoOn() ? 'Quét ngay' : 'Chụp & quét';
                const src = document.querySelector(`[data-lane-source="${dir}"]`)?.value || 'camera';
                if (turnedOffAutoStart && laneCameraOn(dir)) {
                    stopLaneCamera(dir);
                } else if (currentAutoStart && !laneCameraOn(dir) && src === 'camera') {
                    await startLaneCamera(dir, { forceOn: true });
                } else {
                    scheduleAutoRecognize(dir);
                }
                if (!autoOn()) {
                    const camStatus = document.querySelector(`[data-lane-cam-status="${dir}"]`);
                    if (camStatus && camStatus.textContent === 'TỰ ĐỘNG QUÉT') {
                        camStatus.textContent = laneCameraOn(dir) ? 'ĐANG CHẠY' : 'CHỜ BẬT';
                    }
                }
            }
        }

        window.addEventListener('cabin:prefs-updated', applyAutoPrefs);
        applyAutoPrefs();

        function discardLaneToken(form, token) {
            if (!token || !form?.dataset.cameraUrl) return;
            const fd = new FormData();
            fd.append('action', 'discard');
            fd.append('token', token);
            fetch(form.dataset.cameraUrl, { method: 'POST', body: fd }).catch(() => {});
        }

        let boardRefreshSeq = 0;
        async function refreshLanesBoardData() {
            // Hai làn có thể cùng xác nhận gần như đồng thời -> chỉ áp dụng lần làm mới mới nhất.
            const seq = ++boardRefreshSeq;
            try {
                const res = await fetch('/gate/lanes', { headers: { 'X-Requested-With': 'fetch' } });
                if (!res.ok || seq !== boardRefreshSeq) return;
                const html = await res.text();
                if (seq !== boardRefreshSeq) return;
                const doc = new DOMParser().parseFromString(html, 'text/html');
                const kpiNew = doc.getElementById('lanes-kpi-bar');
                const actNew = doc.getElementById('lanes-activity');
                if (kpiNew && $('lanes-kpi-bar')) $('lanes-kpi-bar').innerHTML = kpiNew.innerHTML;
                if (actNew && $('lanes-activity')) {
                    const activeTab = document.querySelector('.lanes-tab.active')?.dataset.lanesTab || 'in';
                    const prevQuery = $('lanes-quick-filter')?.value || '';
                    $('lanes-activity').innerHTML = actNew.innerHTML;
                    const newFilter = $('lanes-quick-filter');
                    if (newFilter && prevQuery) newFilter.value = prevQuery;
                    bindActivityControls();
                    const targetTab = document.querySelector(`[data-lanes-tab="${activeTab}"]`);
                    targetTab?.click();
                    if (prevQuery) filterLanesRows(prevQuery);
                }
            } catch (_) { /* silent refresh fallback */ }
        }

        async function submitLaneAction(dir, action) {
            const form = document.querySelector(`[data-lane-form="${dir}"]`);
            if (!form || laneBusy.get(dir)) return;   // chống bấm 2 lần trên cùng một làn
            const fd = new FormData(form);
            fd.set('action', action);
            fd.set('inline', '1');
            const seq = nextLaneSeq(dir);
            setLaneBusy(dir, true);
            try {
                const res = await fetch(form.action, { method: 'POST', body: fd });
                const data = await readLaneJson(res);
                const latest = isLatestLaneSeq(dir, seq);
                if (action === 'recognize' || !data.ok) {
                    if (latest) applyLaneResult(dir, data);
                    return;
                }
                // Đã ghi nhận vào / ra trong DB: kiểm tra tùy chọn Tự động làm mới làn & Tự động mở in hóa đơn
                if (getPrefBool('auto_reset_lane', true)) {
                    resetLaneCard(dir);
                } else {
                    setLaneButtonsEnabled(dir, false);
                }
                showLaneFeedback(dir, 'success', data.message || 'Đã xác nhận thành công!');
                const shouldPrint = Boolean(data.print_invoice) || (dir === 'exit' && getPrefBool('auto_print_exit', false));
                if (shouldPrint && data.invoice_print_url) {
                    const frame = $('lanes-print-frame');
                    if (frame) frame.src = `${data.invoice_print_url}?autoprint=1`;
                }
                await refreshLanesBoardData();
                checkLowSlotsWarning();
            } catch (_) {
                if (isLatestLaneSeq(dir, seq)) showLaneFeedback(dir, 'error', 'Có lỗi mạng khi xử lý yêu cầu.');
            } finally {
                setLaneBusy(dir, false);
                scheduleAutoRecognize(dir);
            }
        }

        function resetLaneCard(dir) {
            const form = document.querySelector(`[data-lane-form="${dir}"]`);
            if (!form) return;
            nextLaneSeq(dir);   // bỏ qua phản hồi nhận diện còn đang chạy của làn này
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
            if (camEmpty && !laneStreams.get(dir) && !laneIpStreams.get(dir)) camEmpty.hidden = false;
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
        document.querySelectorAll('[data-lane-camera-select]').forEach(select => {
            select.addEventListener('change', () => {
                const dir = select.dataset.laneCameraSelect;
                select.dataset.defaultDevice = select.value || '';
                try { localStorage.setItem('smart-parking-camera-' + dir, select.value || ''); } catch (_) {}
                fetch('/api/camera/select-lane', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ direction: dir, device: select.value || '' })
                }).catch(() => {});
                if (laneCameraOn(dir)) {
                    stopLaneCamera(dir);
                    startLaneCamera(dir, { forceOn: true });
                }
            });
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
        // Nhấn Enter trong ô biển số: chỉ cập nhật làn đó qua AJAX, không gửi form cả trang
        // (gửi form thường sẽ tải lại trang và làm mất dữ liệu đang xử lý ở làn còn lại).
        document.querySelectorAll('[data-lane-form]').forEach(form => {
            form.addEventListener('submit', event => {
                event.preventDefault();
                const dir = form.dataset.laneForm;
                if (document.activeElement?.matches?.(`[data-lane-plate="${dir}"]`)) {
                    submitLaneAction(dir, 'recognize');
                }
            });
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

        const detailDialog = $('lanes-detail-dialog');
        function openHistoryDetail(item) {
            if (!detailDialog || !item) return;
            const d = item.dataset;
            const isIn = d.status === 'IN';
            document.querySelectorAll('[data-history-detail]').forEach(el => {
                el.setAttribute('aria-pressed', String(el === item));
            });
            $('lanes-detail-title').textContent = `Chi tiết lượt gửi #${d.recordId || ''}`;
            const statusEl = $('lanes-detail-status');
            if (statusEl) {
                statusEl.textContent = isIn ? 'Đang trong bãi' : 'Đã ra bãi';
                statusEl.className = `lanes-detail-status ${isIn ? 'is-in' : 'is-out'}`;
            }
            $('lanes-detail-plate').textContent = d.plate || '—';
            $('lanes-detail-slot').textContent = d.slot || '—';
            $('lanes-detail-type').textContent = d.vehicleType || '—';
            $('lanes-detail-fee-label').textContent = isIn ? 'Tạm tính' : 'Phí đã thu';
            const feeEl = $('lanes-detail-fee');
            if (feeEl) {
                feeEl.textContent = d.fee || '—';
                feeEl.classList.toggle('is-paid', !isIn);
            }
            $('lanes-detail-in').textContent = d.timeIn || '—';
            $('lanes-detail-out-label').textContent = isIn ? 'Thời gian gửi' : 'Thời gian ra';
            $('lanes-detail-out').textContent = isIn ? (d.duration || '—') : (d.timeOut || '—');
            $('lanes-detail-note').textContent = d.note || 'Không có ghi chú';

            const imgIn = $('lanes-detail-img-in');
            const empIn = $('lanes-detail-empty-in');
            if (imgIn && empIn) {
                if (d.imageIn) {
                    imgIn.src = d.imageIn;
                    imgIn.hidden = false;
                    empIn.hidden = true;
                } else {
                    imgIn.hidden = true;
                    imgIn.removeAttribute('src');
                    empIn.hidden = false;
                }
            }
            const imgOut = $('lanes-detail-img-out');
            const empOut = $('lanes-detail-empty-out');
            if (imgOut && empOut) {
                if (d.imageOut) {
                    imgOut.src = d.imageOut;
                    imgOut.hidden = false;
                    empOut.hidden = true;
                } else {
                    imgOut.hidden = true;
                    imgOut.removeAttribute('src');
                    empOut.textContent = isIn ? 'Xe chưa ra khỏi bãi' : 'Không có ảnh xe ra';
                    empOut.hidden = false;
                }
            }

            const fillBtn = $('lanes-detail-fill-exit');
            const printLink = $('lanes-detail-print');
            if (fillBtn) {
                fillBtn.hidden = !isIn;
                fillBtn.dataset.plate = d.plate || '';
            }
            if (printLink) {
                printLink.hidden = isIn || !d.invoiceUrl;
                if (d.invoiceUrl) printLink.href = d.invoiceUrl;
            }
            if (typeof detailDialog.showModal === 'function') detailDialog.showModal();
        }

        if (detailDialog) {
            const closeDetail = () => detailDialog.close();
            $('lanes-detail-close')?.addEventListener('click', closeDetail);
            $('lanes-detail-close-btn')?.addEventListener('click', closeDetail);
            detailDialog.addEventListener('click', e => {
                if (e.target === detailDialog) closeDetail();
            });
            $('lanes-detail-fill-exit')?.addEventListener('click', e => {
                const plate = e.currentTarget.dataset.plate;
                closeDetail();
                fillExitLane(plate);
            });
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
            document.querySelectorAll('[data-history-detail]').forEach(item => {
                item.addEventListener('click', e => {
                    if (e.target.closest('a, button')) return;
                    openHistoryDetail(item);
                });
                item.addEventListener('keydown', e => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        openHistoryDetail(item);
                    }
                });
            });
            const quickFilter = $('lanes-quick-filter');
            quickFilter?.addEventListener('input', () => {
                if (search) search.value = quickFilter.value;
                filterLanesRows(quickFilter.value);
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
