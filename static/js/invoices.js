(function () {
  'use strict';
  var form = document.getElementById('invoice-filters');
  if (!form) return;
  var range = document.getElementById('invoice-range');
  var dates = document.getElementById('invoice-custom-dates');
  var filterToggle = document.getElementById('invoice-filter-toggle');
  var sidebar = document.getElementById('invoice-filter-sidebar');
  var quickRadio = document.getElementById('invoice-time-quick');
  var customRadio = document.getElementById('invoice-time-custom');
  var quickButton = document.getElementById('invoice-period-toggle');
  var customButton = document.getElementById('invoice-custom-toggle');
  var periodPopover = document.getElementById('invoice-period-popover');
  var quickRange = range.value === 'custom' ? 'today' : range.value;
  var paymentPicker = document.getElementById('invoice-method-picker');
  var paymentMethod = document.getElementById('invoice-payment-method');
  function positionPaymentPicker() {
    if (!paymentPicker.open) return;
    var trigger = paymentPicker.querySelector('summary').getBoundingClientRect();
    var height = paymentPicker.querySelector('.invoice-method-options').offsetHeight;
    paymentPicker.classList.toggle('opens-up', trigger.bottom + height + 6 > window.innerHeight && trigger.top > height + 12);
  }
  paymentPicker.addEventListener('toggle', positionPaymentPicker);
  window.addEventListener('resize', positionPaymentPicker);
  window.addEventListener('scroll', positionPaymentPicker, true);

  paymentPicker.querySelectorAll('[data-invoice-payment]').forEach(function (button) {
    button.addEventListener('click', function (event) {
      event.preventDefault();
      paymentMethod.value = paymentMethod.value === button.dataset.invoicePayment ? '' : button.dataset.invoicePayment;
      paymentPicker.open = false;
      form.requestSubmit();
    });
  });

  function setTimeMode(custom) {
    quickRadio.checked = !custom;
    customRadio.checked = custom;
    range.value = custom ? 'custom' : quickRange;
    dates.hidden = !custom;
    dates.querySelectorAll('input').forEach(function (input) {
      input.required = custom;
      input.disabled = !custom;
    });
    quickButton.classList.toggle('is-selected', !custom);
    customButton.classList.toggle('is-selected', custom);
    customButton.setAttribute('aria-expanded', String(custom));
  }
  function closePeriods() {
    if (periodPopover.matches(':popover-open')) periodPopover.hidePopover();
  }
  function positionPeriods() {
    if (!periodPopover.matches(':popover-open')) return;
    var anchor = quickButton.getBoundingClientRect();
    var box = periodPopover.getBoundingClientRect();
    var left = window.innerWidth > 800 ? anchor.right + 14 : (window.innerWidth - box.width) / 2;
    left = Math.max(12, Math.min(left, window.innerWidth - box.width - 12));
    var top = Math.max(12, Math.min(anchor.top + anchor.height / 2 - box.height / 2, window.innerHeight - box.height - 12));
    periodPopover.style.left = left + 'px';
    periodPopover.style.top = top + 'px';
    periodPopover.style.setProperty('--period-anchor-y', Math.max(18, Math.min(anchor.top + anchor.height / 2 - top, box.height - 18)) + 'px');
  }
  quickButton.addEventListener('click', function (event) {
    event.preventDefault();
    setTimeMode(false);
    if (periodPopover.matches(':popover-open')) {
      closePeriods();
    } else {
      periodPopover.showPopover();
      positionPeriods();
      var selected = periodPopover.querySelector('[aria-pressed="true"]') || periodPopover.querySelector('[data-invoice-period]');
      selected.focus({ preventScroll: true });
    }
  });
  periodPopover.addEventListener('toggle', function () {
    quickButton.setAttribute('aria-expanded', String(periodPopover.matches(':popover-open')));
  });
  quickRadio.addEventListener('change', function () {
    setTimeMode(false);
    closePeriods();
    form.requestSubmit();
  });
  function chooseCustom() {
    setTimeMode(true);
    closePeriods();
    document.getElementById('invoice-from').focus();
  }
  customRadio.addEventListener('change', chooseCustom);
  customButton.addEventListener('click', chooseCustom);
  periodPopover.querySelectorAll('[data-invoice-period]').forEach(function (button) {
    button.addEventListener('click', function (event) {
      event.preventDefault();
      quickRange = button.dataset.invoicePeriod;
      setTimeMode(false);
      closePeriods();
      form.requestSubmit();
    });
  });
  setTimeMode(customRadio.checked);
  window.addEventListener('resize', positionPeriods);
  window.addEventListener('scroll', positionPeriods, true);
  document.querySelectorAll('[data-invoice-auto-submit]').forEach(function (input) {
    input.addEventListener('change', function () { form.requestSubmit(); });
  });
  filterToggle.addEventListener('click', function () {
    var open = sidebar.classList.toggle('is-open');
    filterToggle.setAttribute('aria-expanded', String(open));
  });

  function closeInvoice(id) {
    var row = document.querySelector('[data-invoice-row="' + id + '"]');
    var detail = document.getElementById('invoice-detail-' + id);
    detail.hidden = true;
    row.classList.remove('is-expanded');
    row.querySelector('[data-toggle-invoice]').setAttribute('aria-expanded', 'false');
  }
  function toggleInvoice(id) {
    var detail = document.getElementById('invoice-detail-' + id);
    var opening = detail.hidden;
    document.querySelectorAll('.invoice-row.is-expanded').forEach(function (row) {
      closeInvoice(row.dataset.invoiceRow);
    });
    if (opening) {
      detail.hidden = false;
      var row = document.querySelector('[data-invoice-row="' + id + '"]');
      row.classList.add('is-expanded');
      row.querySelector('[data-toggle-invoice]').setAttribute('aria-expanded', 'true');
    }
  }
  document.querySelectorAll('[data-invoice-row]').forEach(function (row) {
    row.addEventListener('click', function (event) {
      if (!event.target.closest('input, a')) toggleInvoice(row.dataset.invoiceRow);
    });
  });
  document.querySelectorAll('[data-close-invoice]').forEach(function (button) {
    button.addEventListener('click', function () {
      var id = button.dataset.closeInvoice;
      closeInvoice(id);
      document.querySelector('[data-toggle-invoice="' + id + '"]').focus();
    });
  });
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') return;
    if (periodPopover.matches(':popover-open')) {
      closePeriods();
      quickButton.focus();
      return;
    }
    if (paymentPicker.open) {
      paymentPicker.open = false;
      paymentPicker.querySelector('summary').focus();
      return;
    }
    var row = document.querySelector('.invoice-row.is-expanded');
    if (row) {
      closeInvoice(row.dataset.invoiceRow);
      row.querySelector('[data-toggle-invoice]').focus();
    }
    document.querySelectorAll('.invoice-column-picker[open]').forEach(function (picker) { picker.open = false; });
  });

  var checkboxes = Array.from(document.querySelectorAll('[data-select-invoice]'));
  var selectAll = document.getElementById('invoice-select-all');
  var selection = document.getElementById('invoice-selection');
  function updateSelection() {
    var ids = checkboxes.filter(function (input) { return input.checked; }).map(function (input) { return input.dataset.selectInvoice; });
    selection.hidden = ids.length === 0;
    document.getElementById('invoice-selected-count').textContent = ids.length;
    selectAll.checked = ids.length > 0 && ids.length === checkboxes.length;
    selectAll.indeterminate = ids.length > 0 && ids.length < checkboxes.length;
    var url = new URL(document.getElementById('invoice-export').href);
    url.searchParams.set('ids', ids.join(','));
    document.getElementById('invoice-export-selected').href = url.toString();
  }
  selectAll.disabled = checkboxes.length === 0;
  selectAll.addEventListener('change', function () {
    checkboxes.forEach(function (input) { input.checked = selectAll.checked; });
    updateSelection();
  });
  checkboxes.forEach(function (input) { input.addEventListener('change', updateSelection); });
  document.querySelectorAll('[data-invoice-column]').forEach(function (input) {
    input.addEventListener('change', function () {
      document.querySelectorAll('[data-column="' + input.dataset.invoiceColumn + '"]').forEach(function (cell) { cell.hidden = !input.checked; });
      var hidden = document.querySelectorAll('[data-invoice-column]:not(:checked)').length;
      document.querySelector('[data-invoice-summary-colspan]').colSpan = 7 - hidden;
      document.querySelectorAll('[data-invoice-detail-colspan]').forEach(function (cell) { cell.colSpan = 9 - hidden; });
    });
  });
  document.addEventListener('click', function (event) {
    if (!paymentPicker.contains(event.target)) paymentPicker.open = false;
    document.querySelectorAll('.invoice-column-picker[open]').forEach(function (picker) {
      if (!picker.contains(event.target)) picker.open = false;
    });
  });
})();
