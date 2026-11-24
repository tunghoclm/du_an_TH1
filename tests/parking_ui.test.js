const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../static/js/parking.js'), 'utf8');

function harness() {
    const elements = new Map();
    function element(id) {
        if (!elements.has(id)) elements.set(id, {
            dataset: {}, value: '', hidden: false, disabled: false, listeners: {},
            addEventListener(type, fn) { this.listeners[type] = fn; },
            click() { this.listeners.click?.(); },
            showModal() { this.open = true; }, close() { this.open = false; },
            classList: { toggle() {} },
        });
        return elements.get(id);
    }
    const slot = element('slot-button');
    slot.dataset = { name: 'A01', status: 'occupied', plate: '51F-12345', area: '1', recordId: '17',
        moveUrl: '/parking/A01/move', removeUrl: '/parking/A01/remove', maintenanceUrl: '/parking/A01/maintenance',
        saveUrl: '/parking/A01/save', deleteUrl: '/parking/A01/delete', reason: '' };
    const edit = element('edit-area');
    edit.dataset = { id: '1', name: 'Xe máy', type: '3' };
    const add = element('add-slot'); add.dataset = { id: '1', name: 'Xe máy' };
    const del = element('delete-slot'); del.dataset = { name: 'A02', url: '/parking/A02/delete' };
    const delArea = element('delete-area'); delArea.dataset = { name: 'D', count: '10', url: '/parking/areas/4/delete' };
    const all = element('all'); all.dataset.area = 'all';
    const area1 = element('area1'); area1.dataset.area = '1';
    const sections = [element('section1'), element('section2')];
    sections[0].dataset.area = '1'; sections[1].dataset.area = '2';
    element('close').closest = () => element('maintenance-dialog');
    element('target-slot').options = [{ value: '', textContent: '' },
        { value: 'A02', dataset: { area: '1' } }, { value: 'B01', dataset: { area: '2' } }];
    const selectors = { '#area-filter .chip': [all, area1], '.parking-section': sections,
        '[data-close]': [element('close')], '[data-edit-area]': [edit], '[data-add-slot]': [add],
        '[data-delete-area]': [delArea], '[data-open-slot]': [slot] };
    vm.runInNewContext(script, { document: { getElementById: element, querySelectorAll: selector => selectors[selector] || [] } });
    return { element, slot, edit, add, del, delArea, all, area1, sections };
}

test('occupied slot opens correct record and only offers destinations in its area', () => {
    const h = harness();
    h.element('remove-reason').value = 'Previous reason';
    h.slot.click();
    assert.equal(h.element('slot-actions-dialog').open, true);
    h.element('slot-menu-vehicle').click();
    assert.equal(h.element('vehicle-dialog').open, true);
    assert.equal(h.element('move-form').action, '/parking/A01/move');
    assert.equal(h.element('remove-form').action, '/parking/A01/remove');
    assert.equal(h.element('move-record-id').value, '17');
    assert.equal(h.element('remove-record-id').value, '17');
    assert.equal(h.element('remove-reason').value, '');
    assert.equal(h.element('target-slot').options[1].disabled, false);
    assert.equal(h.element('target-slot').options[2].disabled, true);
    assert.equal(h.element('move-submit').disabled, false);
});

test('missing matching record disables destructive vehicle actions', () => {
    const h = harness();
    h.slot.dataset.recordId = '';
    h.slot.click();
    h.element('slot-menu-vehicle').click();
    assert.equal(h.element('move-submit').disabled, true);
    assert.equal(h.element('remove-submit').disabled, true);
});

test('maintenance dialog distinguishes start, update and finish and preserves the reason', () => {
    const h = harness();
    h.slot.dataset.status = 'available';
    h.slot.dataset.recordId = '';
    h.slot.click();
    h.element('slot-menu-maintenance').click();
    assert.equal(h.element('maintenance-form').action, '/parking/A01/maintenance');
    assert.equal(h.element('maintenance-save').value, 'start');
    assert.equal(h.element('maintenance-finish').hidden, true);
    h.slot.dataset.status = 'maintenance';
    h.slot.dataset.reason = 'Sửa nền';
    h.slot.click();
    h.element('slot-menu-maintenance').click();
    assert.equal(h.element('maintenance-save').value, 'update');
    assert.equal(h.element('maintenance-reason').value, 'Sửa nền');
    assert.equal(h.element('maintenance-finish').hidden, false);
    h.element('close').click();
    assert.equal(h.element('maintenance-dialog').open, false);
});

test('admin dialogs retain area identifiers, restrictions and exact deletion URL', () => {
    const h = harness();
    h.edit.click();
    assert.equal(h.element('area-id').value, '1');
    assert.equal(h.element('area-name').value, 'Xe máy');
    assert.equal(h.element('area-type').value, '3');
    h.add.click();
    assert.equal(h.element('slot-add-area').value, '1');
    h.slot.dataset.status = 'available'; h.slot.dataset.recordId = '';
    h.slot.click();
    h.element('slot-menu-delete').click();
    assert.equal(h.element('slot-delete-form').action, '/parking/A01/delete');
    assert.equal(h.element('slot-delete-dialog').open, true);
    h.delArea.click();
    assert.equal(h.element('area-delete-form').action, '/parking/areas/4/delete');
    assert.match(h.element('area-delete-description').textContent, /10 ô/);
});

test('new area requires count with sequential preview while editing does not regenerate slots', () => {
    const h = harness();
    h.edit.dataset = { id: '', name: 'D', type: '' };
    h.edit.click();
    assert.equal(h.element('area-slot-count').required, true);
    assert.equal(h.element('area-slot-count').disabled, false);
    assert.match(h.element('area-slot-preview').textContent, /D01 đến D10/);
    h.edit.dataset.id = '4';
    h.edit.click();
    assert.equal(h.element('area-count-field').hidden, true);
    assert.equal(h.element('area-slot-count').disabled, true);
});

test('clicking occupied slot offers edit but blocks physical deletion and maintenance', () => {
    const h = harness();
    h.slot.click();
    assert.equal(h.element('slot-menu-delete').disabled, true);
    assert.equal(h.element('slot-menu-maintenance').disabled, true);
    h.element('slot-menu-delete').click();
    assert.notEqual(h.element('slot-delete-dialog').open, true);
    h.element('slot-menu-edit').click();
    assert.equal(h.element('slot-edit-form').action, '/parking/A01/save');
    assert.equal(h.element('slot-edit-status').value, 'occupied');
    assert.equal(h.element('slot-edit-record').value, '17');
    assert.equal(h.element('slot-actions-dialog').open, false);
});

test('area filter works with dynamic identifiers and restores all areas', () => {
    const h = harness();
    h.area1.click();
    assert.equal(h.sections[0].hidden, false);
    assert.equal(h.sections[1].hidden, true);
    h.all.click();
    assert.equal(h.sections[1].hidden, false);
});
