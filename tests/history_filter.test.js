const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../static/js/history-filter.js'), 'utf8');

function harness(fromValue = '', toValue = '') {
    const nodes = Object.fromEntries(['history-period', 'history-time-fields', 'time-from', 'time-to'].map(id => [id, {
        value: '', disabled: false, hidden: false, listeners: {},
        addEventListener(type, fn) { this.listeners[type] = fn; },
        emit(type) { this.listeners[type]?.(); },
    }]));
    nodes['time-from'].value = fromValue;
    nodes['time-to'].value = toValue;
    const picker = nodes['history-period'];
    const options = { '': { dataset: {} }, custom: { dataset: {} }, '1': { dataset: { start: '05:00', end: '12:59' } } };
    Object.defineProperty(picker, 'selectedOptions', { get: () => [options[picker.value]] });
    vm.runInNewContext(script, { document: { getElementById: id => nodes[id] } });
    return { picker, fields: nodes['history-time-fields'], from: nodes['time-from'], to: nodes['time-to'] };
}

test('hour fields start hidden and open when clicking or focusing the period picker', () => {
    const h = harness();
    assert.equal(h.fields.hidden, true);
    assert.equal(h.from.disabled, true);
    h.picker.emit('pointerdown');
    assert.equal(h.fields.hidden, false);
    assert.equal(h.from.disabled, false);
    const keyboard = harness();
    keyboard.picker.emit('focus');
    assert.equal(keyboard.fields.hidden, false);
});

test('preset fills both hours, manual input selects custom, and All clears hidden values', () => {
    const h = harness();
    h.picker.value = '1'; h.picker.emit('change');
    assert.equal(h.from.value, '05:00');
    assert.equal(h.to.value, '12:59');
    assert.equal(h.fields.hidden, false);
    h.from.value = '07:00'; h.from.emit('input');
    assert.equal(h.picker.value, 'custom');
    h.picker.value = ''; h.picker.emit('change');
    assert.equal(h.fields.hidden, true);
    assert.equal(h.from.value, '');
    assert.equal(h.to.value, '');
    assert.equal(h.from.disabled, true);
    h.picker.emit('click');
    assert.equal(h.fields.hidden, true);
});

test('an applied range remains visible on loading filtered results', () => {
    const h = harness('22:00', '04:59');
    assert.equal(h.fields.hidden, false);
    assert.equal(h.from.disabled, false);
    assert.equal(h.from.value, '22:00');
    assert.equal(h.to.value, '04:59');
});
