(function () {
  'use strict';
  var form = document.getElementById('customer-filters');
  if (!form) return;
  var periods = [];
  function closePeriods(except) {
    periods.forEach(function (period) { if (period !== except && period.popover.matches(':popover-open')) period.popover.hidePopover(); });
  }
  document.querySelectorAll('[data-customer-period-filter]').forEach(function (fieldset) {
    var input = fieldset.querySelector('[data-period-value]');
    var quick = fieldset.querySelector('[data-period-quick]');
    var custom = fieldset.querySelector('[data-period-custom]');
    var trigger = fieldset.querySelector('[data-period-trigger]');
    var customTrigger = fieldset.querySelector('[data-period-custom-trigger]');
    var dates = fieldset.querySelector('[data-period-dates]');
    var popover = fieldset.querySelector('[popover]');
    var quickRange = input.value === 'custom' ? 'all' : input.value;
    var period = { popover: popover, trigger: trigger };
    periods.push(period);
    function mode(isCustom) {
      input.value = isCustom ? 'custom' : quickRange;
      quick.checked = !isCustom;
      custom.checked = isCustom;
      trigger.classList.toggle('is-selected', !isCustom);
      customTrigger.classList.toggle('is-selected', isCustom);
      customTrigger.setAttribute('aria-expanded', String(isCustom));
      dates.hidden = !isCustom;
      dates.querySelectorAll('input').forEach(function (field) { field.disabled = !isCustom; field.required = isCustom; });
    }
    function position() {
      if (!popover.matches(':popover-open')) return;
      var anchor = trigger.getBoundingClientRect(), box = popover.getBoundingClientRect();
      var left = window.innerWidth > 800 ? anchor.right + 14 : (window.innerWidth - box.width) / 2;
      left = Math.max(12, Math.min(left, window.innerWidth - box.width - 12));
      var top = Math.max(12, Math.min(anchor.top + anchor.height / 2 - box.height / 2, window.innerHeight - box.height - 12));
      popover.style.left = left + 'px';
      popover.style.top = top + 'px';
      popover.style.setProperty('--period-anchor-y', Math.max(18, Math.min(anchor.top + anchor.height / 2 - top, box.height - 18)) + 'px');
    }
    trigger.addEventListener('click', function (event) {
      event.preventDefault();
      mode(false);
      if (popover.matches(':popover-open')) { popover.hidePopover(); return; }
      closePeriods(period);
      popover.showPopover();
      position();
      (popover.querySelector('[aria-pressed="true"]') || popover.querySelector('[data-customer-period]')).focus({preventScroll:true});
    });
    popover.addEventListener('toggle', function () { trigger.setAttribute('aria-expanded', String(popover.matches(':popover-open'))); });
    quick.addEventListener('change', function () { mode(false); closePeriods(); form.requestSubmit(); });
    function customMode() { mode(true); closePeriods(); dates.querySelector('input').focus(); }
    custom.addEventListener('change', customMode);
    customTrigger.addEventListener('click', customMode);
    popover.querySelectorAll('[data-customer-period]').forEach(function (button) {
      button.addEventListener('click', function (event) {
        event.preventDefault(); quickRange = button.dataset.customerPeriod; mode(false); closePeriods(); form.requestSubmit();
      });
    });
    mode(custom.checked);
    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);
  });
  document.querySelectorAll('[data-customer-auto-submit]').forEach(function (field) { field.addEventListener('change', function () { form.requestSubmit(); }); });
  var filterToggle = document.getElementById('customer-filter-toggle');
  filterToggle.addEventListener('click', function () {
    filterToggle.setAttribute('aria-expanded', String(document.getElementById('customer-filter-sidebar').classList.toggle('is-open')));
  });

  function closeCustomer(id) {
    document.getElementById('customer-detail-' + id).hidden = true;
    var row = document.querySelector('[data-customer-row="' + id + '"]');
    row.classList.remove('is-expanded');
    row.querySelector('[data-toggle-customer]').setAttribute('aria-expanded','false');
  }
  function toggleCustomer(id) {
    var detail = document.getElementById('customer-detail-' + id);
    if (!detail) return;
    var open = detail.hidden;
    document.querySelectorAll('.customer-row.is-expanded').forEach(function (row) { closeCustomer(row.dataset.customerRow); });
    if (open) {
      detail.hidden = false;
      var row = document.querySelector('[data-customer-row="' + id + '"]');
      row.classList.add('is-expanded');
      row.querySelector('[data-toggle-customer]').setAttribute('aria-expanded','true');
    }
  }
  document.querySelectorAll('[data-customer-row]').forEach(function (row) {
    row.addEventListener('click', function (event) { if (!event.target.closest('input,a')) toggleCustomer(row.dataset.customerRow); });
  });
  document.querySelectorAll('[data-close-customer]').forEach(function (button) {
    button.addEventListener('click', function () { closeCustomer(button.dataset.closeCustomer); document.querySelector('[data-toggle-customer="' + button.dataset.closeCustomer + '"]').focus(); });
  });
  function chooseTab(tab, focus) {
    var detail = tab.closest('.customer-detail');
    detail.querySelectorAll('[data-customer-tab]').forEach(function (button) {
      var selected = button === tab;
      button.setAttribute('aria-selected',String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    detail.querySelectorAll('[data-customer-panel]').forEach(function (panel) { panel.hidden = panel.dataset.customerPanel !== tab.dataset.customerTab; });
    if (focus) tab.focus();
  }
  document.querySelectorAll('[data-customer-tab]').forEach(function (tab) {
    tab.addEventListener('click', function () { chooseTab(tab); });
    tab.addEventListener('keydown', function (event) {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      var tabs = Array.from(tab.parentElement.querySelectorAll('[data-customer-tab]'));
      var index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 :
        (tabs.indexOf(tab) + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      chooseTab(tabs[index], true);
    });
  });

  var addDialog = document.getElementById('add-customer-dialog');
  var editDialog = document.getElementById('edit-customer-dialog');
  var vehicleRows = document.getElementById('vehicle-rows');
  function syncVehicleRow(row) {
    var hasPlate = Boolean(row.querySelector('[name="plate"]').value.trim());
    var monthly = row.querySelector('[name="ticket_type"]').value === 'month';
    var months = row.querySelector('[name="months"]');
    row.classList.toggle('is-monthly', monthly);
    row.querySelector('[data-customer-months]').hidden = !monthly;
    // Keep one months value per row, including turn tickets, for the server's paired lists.
    months.type = monthly ? 'number' : 'hidden';
    months.required = monthly && hasPlate;
    row.querySelector('[name="vehicle_type_id"]').required = hasPlate;
  }
  function numberVehicleRows() {
    vehicleRows.querySelectorAll('[data-vehicle-row]').forEach(function (row, index) {
      row.querySelectorAll('[data-customer-vehicle-field]').forEach(function (field) {
        var key = field.dataset.customerVehicleField;
        field.id = 'customer-vehicle-' + (index + 1) + '-' + key;
        row.querySelector('[data-vehicle-label="' + key + '"]').htmlFor = field.id;
      });
      row.querySelector('[data-remove-vrow]').setAttribute('aria-label', 'Xóa phương tiện ' + (index + 1));
    });
  }
  function bindVehicleRow(row) {
    row.addEventListener('input', function () { syncVehicleRow(row); });
    row.addEventListener('change', function () { syncVehicleRow(row); });
    row.querySelector('[data-remove-vrow]').addEventListener('click', function () {
      if (vehicleRows.children.length > 1) {
        row.remove();
      } else {
        row.querySelector('[name="plate"]').value = '';
        row.querySelector('[name="vehicle_type_id"]').value = '';
        row.querySelector('[name="ticket_type"]').value = 'turn';
        row.querySelector('[name="months"]').value = '1';
        syncVehicleRow(row);
      }
      numberVehicleRows();
      vehicleRows.querySelector('[name="plate"]').focus();
    });
    syncVehicleRow(row);
  }
  vehicleRows.querySelectorAll('[data-vehicle-row]').forEach(bindVehicleRow);
  document.getElementById('add-vehicle-row').addEventListener('click', function () {
    var row = vehicleRows.firstElementChild.cloneNode(true);
    row.querySelector('[name="plate"]').value = '';
    row.querySelector('[name="vehicle_type_id"]').value = '';
    row.querySelector('[name="ticket_type"]').value = 'turn';
    row.querySelector('[name="months"]').value = '1';
    vehicleRows.appendChild(row);
    bindVehicleRow(row);
    numberVehicleRows();
    row.querySelector('[name="plate"]').focus();
  });
  document.querySelectorAll('.customer-dialog form').forEach(function (dialogForm) {
    dialogForm.addEventListener('invalid', function (event) {
      var section = event.target.closest('details');
      if (section) section.open = true;
    }, true);
  });
  document.getElementById('open-add-customer').addEventListener('click', function () { addDialog.showModal(); });
  document.querySelectorAll('[data-close-dialog]').forEach(function (button) { button.addEventListener('click', function () { button.closest('dialog').close(); }); });
  function updateAvatar(dialog) {
    var words = dialog.querySelector('[data-customer-name]').value.trim().split(/\s+/).filter(Boolean);
    dialog.querySelector('[data-customer-avatar]').textContent = words.length > 1 ? (words[0][0] + words[words.length-1][0]).toUpperCase() : (words[0] || 'KH').slice(0,2).toUpperCase();
  }
  document.querySelectorAll('[data-customer-name]').forEach(function (input) { input.addEventListener('input', function () { updateAvatar(input.closest('dialog')); }); });
  document.querySelectorAll('[data-edit-customer]').forEach(function (button) {
    button.addEventListener('click', function () {
      var editForm = editDialog.querySelector('form');
      editForm.action = button.dataset.action;
      ['fullname','phone','email','address','customer_note'].forEach(function (name) { editForm.elements.namedItem(name).value = button.dataset[name === 'customer_note' ? 'customerNote' : name] || ''; });
      editForm.querySelector('[data-profile-code]').value = button.dataset.code;
      editForm.querySelector('[data-profile-username]').value = button.dataset.username;
      editDialog.querySelectorAll('[role="alert"]').forEach(function (alert) { alert.hidden = true; });
      updateAvatar(editDialog);
      editDialog.showModal();
    });
  });
  document.querySelectorAll('[data-confirm-action]').forEach(function (actionForm) {
    actionForm.addEventListener('submit', function (event) { if (!window.confirm(actionForm.dataset.confirmAction)) event.preventDefault(); });
  });
  document.querySelectorAll('dialog[data-open-on-load]').forEach(function (dialog) { updateAvatar(dialog); dialog.showModal(); });
  var openId = document.querySelector('.customer-page').dataset.openCustomer;
  if (openId !== '0') toggleCustomer(openId);

  var selection = document.getElementById('customer-selection');
  var selectAll = document.getElementById('customer-select-all');
  var checkboxes = Array.from(document.querySelectorAll('[data-select-customer]'));
  function updateSelection() {
    var ids = checkboxes.filter(function (box) { return box.checked; }).map(function (box) { return box.dataset.selectCustomer; });
    selection.hidden = ids.length === 0;
    document.getElementById('customer-selected-count').textContent = ids.length;
    selectAll.checked = ids.length > 0 && ids.length === checkboxes.length;
    selectAll.indeterminate = ids.length > 0 && ids.length < checkboxes.length;
    var url = new URL(document.getElementById('customer-export').href);
    url.searchParams.set('ids',ids.join(','));
    document.getElementById('customer-export-selected').href = url.toString();
  }
  selectAll.disabled = !checkboxes.length;
  selectAll.addEventListener('change', function () { checkboxes.forEach(function (box) { box.checked = selectAll.checked; }); updateSelection(); });
  checkboxes.forEach(function (box) { box.addEventListener('change',updateSelection); });
  document.querySelectorAll('[data-customer-column]').forEach(function (box) {
    box.addEventListener('change', function () {
      document.querySelectorAll('[data-customer-cell="' + box.dataset.customerColumn + '"]').forEach(function (cell) { cell.hidden = !box.checked; });
      var hidden = document.querySelectorAll('[data-customer-column]:not(:checked)').length;
      document.querySelector('[data-customer-summary-leading]').colSpan = document.querySelector('[data-customer-column="phone"]').checked ? 4 : 3;
      document.querySelectorAll('[data-customer-colspan]').forEach(function (cell) { cell.colSpan = 8 - hidden; });
    });
  });
  document.addEventListener('click', function (event) { document.querySelectorAll('.customer-column-picker[open]').forEach(function (picker) { if (!picker.contains(event.target)) picker.open = false; }); });
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape' || document.querySelector('dialog[open]')) return;
    var openPeriod = periods.find(function (period) { return period.popover.matches(':popover-open'); });
    if (openPeriod) { closePeriods(); openPeriod.trigger.focus(); return; }
    var picker = document.querySelector('.customer-column-picker[open]');
    if (picker) { picker.open = false; picker.querySelector('summary').focus(); return; }
    var row = document.querySelector('.customer-row.is-expanded');
    if (row) { closeCustomer(row.dataset.customerRow); row.querySelector('[data-toggle-customer]').focus(); }
  });
})();
