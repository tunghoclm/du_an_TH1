(function () {
  'use strict';
  var form = document.getElementById('employee-filters');
  if (!form) return;

  // Auto-submit sidebar filters
  document.querySelectorAll('[data-employee-auto-submit]').forEach(function (field) {
    field.addEventListener('change', function () {
      form.requestSubmit();
    });
  });

  var filterToggle = document.getElementById('employee-filter-toggle');
  var filterSidebar = document.getElementById('employee-filter-sidebar');
  if (filterToggle && filterSidebar) {
    filterToggle.addEventListener('click', function () {
      var expanded = filterSidebar.classList.toggle('is-open');
      filterToggle.setAttribute('aria-expanded', String(expanded));
    });
  }

  // Inline detail row expand / collapse
  function closeEmployee(id) {
    var detail = document.getElementById('employee-detail-' + id);
    var row = document.querySelector('[data-employee-row="' + id + '"]');
    if (detail) detail.hidden = true;
    if (row) {
      row.classList.remove('is-expanded');
      var btn = row.querySelector('[data-toggle-employee]');
      if (btn) btn.setAttribute('aria-expanded', 'false');
    }
  }

  function toggleEmployee(id) {
    var detail = document.getElementById('employee-detail-' + id);
    if (!detail) return;
    var shouldOpen = detail.hidden;
    document.querySelectorAll('.customer-row.is-expanded').forEach(function (r) {
      closeEmployee(r.dataset.employeeRow);
    });
    if (shouldOpen) {
      detail.hidden = false;
      var row = document.querySelector('[data-employee-row="' + id + '"]');
      if (row) {
        row.classList.add('is-expanded');
        var btn = row.querySelector('[data-toggle-employee]');
        if (btn) btn.setAttribute('aria-expanded', 'true');
      }
    }
  }

  document.querySelectorAll('[data-employee-row]').forEach(function (row) {
    row.addEventListener('click', function (event) {
      if (!event.target.closest('input, a, button.invoice-action')) {
        toggleEmployee(row.dataset.employeeRow);
      }
    });
  });

  document.querySelectorAll('[data-close-employee]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var id = btn.dataset.closeEmployee;
      closeEmployee(id);
      var toggle = document.querySelector('[data-toggle-employee="' + id + '"]');
      if (toggle) toggle.focus();
    });
  });

  // Inline detail tabs
  function chooseDetailTab(tab) {
    var detail = tab.closest('.customer-detail');
    if (!detail) return;
    detail.querySelectorAll('[data-employee-tab]').forEach(function (btn) {
      var selected = btn === tab;
      btn.setAttribute('aria-selected', String(selected));
      btn.tabIndex = selected ? 0 : -1;
    });
    detail.querySelectorAll('[data-employee-panel]').forEach(function (panel) {
      panel.hidden = panel.dataset.employeePanel !== tab.dataset.employeeTab;
    });
  }

  document.querySelectorAll('[data-employee-tab]').forEach(function (tab) {
    tab.addEventListener('click', function () {
      chooseDetailTab(tab);
    });
  });

  // Modal tabs (Thông tin | Thiết lập lương)
  function switchModalTab(dialog, tabKey) {
    if (!dialog) return;
    dialog.querySelectorAll('[data-modal-tab]').forEach(function (btn) {
      var selected = btn.dataset.modalTab === tabKey;
      btn.setAttribute('aria-selected', String(selected));
    });
    dialog.querySelectorAll('[data-modal-panel]').forEach(function (panel) {
      panel.hidden = panel.dataset.modalPanel !== tabKey;
    });
  }

  document.querySelectorAll('[data-modal-tab]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      switchModalTab(btn.closest('dialog'), btn.dataset.modalTab);
    });
  });

  // Allowance & Deduction extra field toggles
  function bindExtraToggle(dialog, toggleSelector, extraSelector) {
    if (!dialog) return;
    var toggle = dialog.querySelector(toggleSelector);
    var extra = dialog.querySelector(extraSelector);
    if (!toggle || !extra) return;
    function sync() {
      extra.hidden = !toggle.checked;
    }
    toggle.addEventListener('change', sync);
    sync();
  }

  // Live avatar initials
  function bindAvatarPreview(dialog) {
    if (!dialog) return;
    var input = dialog.querySelector('[data-employee-name]');
    var avatar = dialog.querySelector('[data-employee-avatar]');
    if (!input || !avatar) return;
    function update() {
      var val = (input.value || '').trim();
      if (!val) {
        avatar.textContent = 'NV';
        return;
      }
      var parts = val.split(/\s+/).filter(Boolean);
      avatar.textContent = parts.length >= 2
        ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
        : val.slice(0, 2).toUpperCase();
    }
    input.addEventListener('input', update);
    update();
  }

  // Dialog helpers
  function openDialog(dlg) {
    if (!dlg) return;
    if (typeof dlg.showModal === 'function') dlg.showModal();
    else dlg.setAttribute('open', '');
  }
  function closeDialog(dlg) {
    if (!dlg) return;
    if (typeof dlg.close === 'function') dlg.close();
    else dlg.removeAttribute('open');
  }

  var addDlg = document.getElementById('add-employee-dialog');
  var editDlg = document.getElementById('edit-employee-dialog');
  bindExtraToggle(addDlg, '[data-allowance-toggle]', '[data-allowance-extra]');
  bindExtraToggle(editDlg, '[data-allowance-toggle]', '[data-allowance-extra]');
  bindExtraToggle(addDlg, '[data-deduction-toggle]', '[data-deduction-extra]');
  bindExtraToggle(editDlg, '[data-deduction-toggle]', '[data-deduction-extra]');
  bindAvatarPreview(addDlg);
  bindAvatarPreview(editDlg);

  var openAddBtn = document.getElementById('open-add-account');
  if (openAddBtn && addDlg) {
    openAddBtn.addEventListener('click', function () {
      switchModalTab(addDlg, 'info');
      openDialog(addDlg);
    });
  }

  document.querySelectorAll('[data-close-dialog]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      closeDialog(btn.closest('dialog'));
    });
  });

  // Open edit modal & prefill fields
  document.querySelectorAll('[data-edit-employee]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (!editDlg) return;
      var formEl = editDlg.querySelector('form');
      formEl.action = btn.dataset.action || '';

      var fieldMap = [
        'employee_code', 'fullname', 'phone',
        'start_date', 'department', 'position', 'username', 'role',
        'attendance_code', 'customer_note', 'bank_account', 'bank_name',
        'bank_holder', 'id_card', 'dob', 'email', 'address',
        'salary_type', 'salary_amount', 'salary_template', 'allowance_amount',
        'deduction_amount', 'deduction_note'
      ];
      fieldMap.forEach(function (name) {
        var el = formEl.querySelector('[name="' + name + '"]');
        if (el) el.value = btn.dataset[name] || '';
      });

      var genderVal = btn.dataset.gender || '';
      formEl.querySelectorAll('[name="gender"]').forEach(function (radio) {
        radio.checked = radio.value === genderVal;
      });

      ['allowance_enabled', 'deduction_enabled'].forEach(function (name) {
        var cb = formEl.querySelector('[name="' + name + '"]');
        if (cb) cb.checked = btn.dataset[name] === '1';
      });

      [
        ['[data-allowance-toggle]', '[data-allowance-extra]'],
        ['[data-deduction-toggle]', '[data-deduction-extra]']
      ].forEach(function (pair) {
        var t = editDlg.querySelector(pair[0]);
        var x = editDlg.querySelector(pair[1]);
        if (t && x) x.hidden = !t.checked;
      });

      var avatar = editDlg.querySelector('[data-employee-avatar]');
      var nameInput = editDlg.querySelector('[data-employee-name]');
      if (avatar && nameInput) {
        nameInput.dispatchEvent(new Event('input'));
      }

      switchModalTab(editDlg, btn.dataset.initialTab || 'info');
      openDialog(editDlg);
    });
  });

  // Open modal on load if server returned validation errors
  document.querySelectorAll('dialog[data-open-on-load]').forEach(function (dlg) {
    openDialog(dlg);
  });

  // Auto-open inline detail if ?open=ID
  var page = document.querySelector('.employee-page');
  if (page && page.dataset.openEmployee) {
    toggleEmployee(page.dataset.openEmployee);
  }

  // Row selection & export selected
  var selectAll = document.getElementById('employee-select-all');
  var rowChecks = Array.prototype.slice.call(document.querySelectorAll('[data-select-employee]'));
  var selectionBar = document.getElementById('employee-selection');
  var selectedCount = document.getElementById('employee-selected-count');
  var exportSelected = document.getElementById('employee-export-selected');
  var exportBase = document.getElementById('employee-export');

  function syncSelection() {
    var ids = rowChecks.filter(function (cb) { return cb.checked; }).map(function (cb) { return cb.dataset.selectEmployee; });
    if (selectionBar) selectionBar.hidden = ids.length === 0;
    if (selectedCount) selectedCount.textContent = String(ids.length);
    if (selectAll) {
      selectAll.checked = rowChecks.length > 0 && ids.length === rowChecks.length;
      selectAll.indeterminate = ids.length > 0 && ids.length < rowChecks.length;
    }
    if (exportSelected && exportBase) {
      var sep = exportBase.href.indexOf('?') >= 0 ? '&' : '?';
      exportSelected.href = exportBase.href + sep + 'ids=' + encodeURIComponent(ids.join(','));
    }
  }

  if (selectAll) {
    selectAll.addEventListener('change', function () {
      rowChecks.forEach(function (cb) { cb.checked = selectAll.checked; });
      syncSelection();
    });
  }
  rowChecks.forEach(function (cb) {
    cb.addEventListener('change', syncSelection);
  });

  // Column visibility picker
  var STORAGE_KEY = 'sp_employee_hidden_cols';
  var hiddenCols = [];
  try {
    hiddenCols = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
  } catch (e) {
    hiddenCols = [];
  }

  function applyColumnVisibility() {
    var visibleExtra = 0;
    document.querySelectorAll('[data-employee-column]').forEach(function (cb) {
      var col = cb.dataset.employeeColumn;
      var show = hiddenCols.indexOf(col) === -1;
      cb.checked = show;
      if (show) visibleExtra += 1;
      document.querySelectorAll('[data-employee-cell="' + col + '"]').forEach(function (cell) {
        cell.hidden = !show;
      });
    });
    document.querySelectorAll('[data-employee-colspan]').forEach(function (cell) {
      cell.colSpan = 4 + visibleExtra;
    });
  }

  document.querySelectorAll('[data-employee-column]').forEach(function (cb) {
    cb.addEventListener('change', function () {
      var col = cb.dataset.employeeColumn;
      if (cb.checked) {
        hiddenCols = hiddenCols.filter(function (c) { return c !== col; });
      } else if (hiddenCols.indexOf(col) === -1) {
        hiddenCols.push(col);
      }
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(hiddenCols));
      } catch (e) {}
      applyColumnVisibility();
    });
  });
  applyColumnVisibility();
})();
