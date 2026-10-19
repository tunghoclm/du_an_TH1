(() => {
    'use strict';
    const $ = id => document.getElementById(id);
    let selectedSlot = null;
    const openAction = id => {
        $('slot-actions-dialog').close();
        $(id).showModal();
    };
    document.querySelectorAll('#area-filter .chip').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('#area-filter .chip').forEach(c => c.classList.toggle('active', c === chip));
            document.querySelectorAll('.parking-section').forEach(section => {
                section.hidden = chip.dataset.area !== 'all' && chip.dataset.area !== section.dataset.area;
            });
        });
    });
    document.querySelectorAll('[data-close]').forEach(button => {
        button.addEventListener('click', () => button.closest('dialog').close());
    });
    function previewSlots() {
        const count = Number($('area-slot-count')?.value);
        const name = $('area-name')?.value || '';
        const prefix = name.replace(/[đĐ]/g, 'D').normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
            .toUpperCase().replace(/[^A-Z0-9_-]/g, '').slice(0, 28).replace(/^[_-]+|[_-]+$/g, '');
        $('area-slot-preview').textContent = prefix && Number.isInteger(count) && count > 0 && count <= 1000
            ? count + ' ô: ' + prefix + '01 đến ' + prefix + String(count).padStart(2, '0') + '.'
            : 'Tên ô được tạo tự động theo tên khu và đánh số từ 01.';
    }
    $('area-name')?.addEventListener('input', previewSlots);
    $('area-slot-count')?.addEventListener('input', previewSlots);
    document.querySelectorAll('[data-edit-area]').forEach(button => {
        button.addEventListener('click', () => {
            const editing = !!button.dataset.id;
            $('area-title').textContent = editing ? 'Sửa khu đỗ xe' : 'Thêm khu mới';
            $('area-id').value = button.dataset.id;
            $('area-name').value = button.dataset.name;
            $('area-type').value = button.dataset.type || 'all';
            $('area-count-field').hidden = editing;
            $('area-slot-count').disabled = editing;
            $('area-slot-count').required = !editing;
            $('area-slot-count').value = '10';
            previewSlots();
            $('area-dialog').showModal();
        });
    });
    document.querySelectorAll('[data-delete-area]').forEach(button => {
        button.addEventListener('click', () => {
            $('area-delete-form').action = button.dataset.url;
            $('area-delete-description').textContent = 'Xóa khu ' + button.dataset.name + ' cùng toàn bộ ' + button.dataset.count + ' ô đỗ?';
            $('area-delete-dialog').showModal();
        });
    });
    document.querySelectorAll('[data-add-slot]').forEach(button => {
        button.addEventListener('click', () => {
            $('slot-add-area').value = button.dataset.id;
            $('slot-add-area-label').textContent = 'Khu ' + button.dataset.name;
            $('slot-add-name').value = '';
            $('slot-add-dialog').showModal();
        });
    });
    document.querySelectorAll('[data-open-slot]').forEach(button => {
        button.addEventListener('click', () => {
            selectedSlot = button.dataset;
            const data = selectedSlot, occupied = data.status === 'occupied';
            $('slot-actions-title').textContent = 'Ô ' + data.name;
            $('slot-actions-description').textContent = occupied ? 'Đang đỗ: ' + data.plate
                : data.status === 'maintenance' ? 'Bảo trì: ' + data.reason : 'Ô đang trống';
            $('slot-menu-vehicle').hidden = !occupied;
            $('slot-menu-maintenance').disabled = occupied || !!data.recordId;
            $('slot-menu-maintenance').textContent = data.status === 'maintenance' ? 'Quản lý bảo trì' : 'Bảo trì';
            if ($('slot-menu-delete')) $('slot-menu-delete').disabled = occupied || !!data.recordId;
            if ($('slot-menu-edit')) $('slot-menu-edit').disabled = occupied && !data.recordId;
            $('slot-actions-dialog').showModal();
        });
    });
    $('slot-menu-edit')?.addEventListener('click', () => {
        if (!selectedSlot || (selectedSlot.status === 'occupied' && !selectedSlot.recordId)) return;
        $('slot-edit-form').action = selectedSlot.saveUrl;
        $('slot-edit-name').value = selectedSlot.name;
        $('slot-edit-status').value = selectedSlot.status;
        $('slot-edit-record').value = selectedSlot.recordId;
        openAction('slot-edit-dialog');
    });
    $('slot-menu-delete')?.addEventListener('click', () => {
        if (!selectedSlot || selectedSlot.status === 'occupied' || selectedSlot.recordId) return;
        $('slot-delete-form').action = selectedSlot.deleteUrl;
        $('slot-delete-description').textContent = 'Xóa ô ' + selectedSlot.name + ' khỏi sơ đồ bãi?';
        openAction('slot-delete-dialog');
    });
    $('slot-menu-maintenance')?.addEventListener('click', () => {
        const data = selectedSlot;
        if (!data || data.status === 'occupied' || data.recordId) return;
        const maintenance = data.status === 'maintenance';
        $('maintenance-form').action = data.maintenanceUrl;
        $('maintenance-title').textContent = 'Bảo trì ô ' + data.name;
        $('maintenance-reason').value = data.reason;
        $('maintenance-finish').hidden = $('maintenance-finish').disabled = !maintenance;
        $('maintenance-save').value = maintenance ? 'update' : 'start';
        $('maintenance-save').textContent = maintenance ? 'Lưu lý do' : 'Bắt đầu bảo trì';
        openAction('maintenance-dialog');
    });
    $('slot-menu-vehicle')?.addEventListener('click', () => {
        const data = selectedSlot;
        if (!data || data.status !== 'occupied') return;
        $('vehicle-title').textContent = 'Ô ' + data.name;
        $('vehicle-description').textContent = 'Xe ' + data.plate + (data.recordId ? ''
            : ' · Không tìm thấy lượt gửi tương ứng. Hãy tải lại trang hoặc nhờ admin kiểm tra dữ liệu.');
        $('move-form').action = data.moveUrl;
        $('remove-form').action = data.removeUrl;
        $('move-record-id').value = data.recordId;
        $('remove-record-id').value = data.recordId;
        $('remove-reason').value = '';
        const select = $('target-slot');
        select.value = '';
        let count = 0;
        Array.from(select.options).forEach(option => {
            if (!option.value) return;
            const eligible = option.dataset.area === data.area;
            option.hidden = option.disabled = !eligible;
            if (eligible) count += 1;
        });
        $('move-submit').disabled = !data.recordId || count === 0;
        $('remove-submit').disabled = !data.recordId;
        select.options[0].textContent = count ? '— Chọn ô đích —' : 'Không còn ô trống trong khu';
        openAction('vehicle-dialog');
    });
})();
