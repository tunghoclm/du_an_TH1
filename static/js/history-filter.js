(() => {
    'use strict';
    const picker = document.getElementById('history-period');
    if (!picker) return;
    const fields = document.getElementById('history-time-fields');
    const from = document.getElementById('time-from'), to = document.getElementById('time-to');
    function show(visible) {
        fields.hidden = !visible;
        from.disabled = to.disabled = !visible;
    }
    picker.addEventListener('focus', () => show(true));
    // Open before the native option picker; a closing click must not undo the
    // change handler that just cleared and collapsed the All selection.
    picker.addEventListener('pointerdown', () => show(true));
    picker.addEventListener('blur', () => { if (!picker.value && !from.value && !to.value) show(false); });
    picker.addEventListener('change', () => {
        const option = picker.selectedOptions[0];
        if (picker.value !== 'custom') {
            from.value = option.dataset.start || '';
            to.value = option.dataset.end || '';
        }
        show(!!picker.value);
    });
    [from, to].forEach(input => input.addEventListener('input', () => { picker.value = 'custom'; }));
    show(!!(from.value || to.value));
})();
