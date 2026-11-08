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

    const grid = $('cabin-slot-grid');
    if (!grid) return;
    const scrollWrap = $('cabin-slot-scroll');
    const viewToggle = $('cabin-view-toggle');
    const slots = Array.from(grid.querySelectorAll('[data-cabin-slot]'));
    const details = Array.from(document.querySelectorAll('[data-cabin-detail]'));
    const areaButtons = Array.from(document.querySelectorAll('[data-cabin-area]'));
    const statusInputs = Array.from(document.querySelectorAll('input[name="cabin-status"]'));
    const search = $('cabin-search');
    const ticketSearch = $('cabin-ticket-search');
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
        $('cabin-primary-label').textContent = available ? 'Xe vào' : 'Thanh toán';
        $('cabin-total-label').textContent = 'Tổng tiền';
        if (totalCount) totalCount.textContent = occupied ? '1' : '0';
        if (tabLabel) tabLabel.textContent = slot ? slot.dataset.cabinSlot : '1-5';
        $('cabin-total').textContent = occupied ? Number(slot.dataset.fee || 0).toLocaleString('vi-VN') : '0';
    }
    function filterSlots() {
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
    [search, ticketSearch].filter(Boolean).forEach(input => input.addEventListener('input', () => {
        const other = input === search ? ticketSearch : search;
        if (other) other.value = input.value;
        setGridVisible(true);
        filterSlots();
    }));
    search?.closest('form')?.addEventListener('submit', event => { event.preventDefault(); filterSlots(); });
    slots.forEach(slot => slot.addEventListener('click', () => selectSlot(slot)));
    function continueTransaction() {
        if (selected && selected.dataset.status !== 'maintenance') location.assign(selected.dataset.actionUrl);
    }
    primary?.addEventListener('click', continueTransaction);
    exit?.addEventListener('click', continueTransaction);
    $('cabin-note-btn')?.addEventListener('click', continueTransaction);
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
