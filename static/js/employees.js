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

  // Desktop collapsible sidebar toggle
  var workspace = document.querySelector('.employee-page .invoice-workspace');
  var collapseBtn = document.getElementById('employee-sidebar-collapse');
  var SIDEBAR_KEY = 'sp_employee_sidebar_collapsed';
  if (workspace && collapseBtn) {
    try {
      if (localStorage.getItem(SIDEBAR_KEY) === '1') {
        workspace.classList.add('is-sidebar-collapsed');
      }
    } catch (e) {}
    collapseBtn.addEventListener('click', function () {
      var collapsed = workspace.classList.toggle('is-sidebar-collapsed');
      collapseBtn.setAttribute('aria-label', collapsed ? 'Mở rộng bộ lọc' : 'Thu gọn bộ lọc');
      try {
        localStorage.setItem(SIDEBAR_KEY, collapsed ? '1' : '0');
      } catch (e) {}
    });
  }

  // Kendo-style MultiSelect Tag-Chip Combobox (Cổng làm việc)
  function parseGateList(csv) {
    return (csv || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
  }

  function initGateMultiselect(root) {
    var hiddenInput = root.querySelector('input[type="hidden"][name="work_branch"]');
    var box = root.querySelector('.kv-multiselect-box');
    var tagsWrap = root.querySelector('[data-gate-tags]');
    var searchInput = root.querySelector('[data-gate-search]');
    var dropdown = root.querySelector('[data-gate-dropdown]');
    if (!hiddenInput || !box || !tagsWrap || !searchInput || !dropdown) return;

    var autoSubmit = root.dataset.autoSubmit === 'true';
    var allowAll = root.dataset.allowAll === 'true';

    function getSelected() {
      return parseGateList(hiddenInput.value);
    }

    function setSelected(list, shouldSubmit) {
      var deduped = [];
      list.forEach(function (item) {
        if (item && deduped.indexOf(item) === -1) deduped.push(item);
      });
      hiddenInput.value = deduped.join(', ');
      render();
      if (shouldSubmit && autoSubmit) {
        form.requestSubmit();
      }
    }

    function render() {
      var selected = getSelected();
      tagsWrap.innerHTML = '';
      selected.forEach(function (gate) {
        var chip = document.createElement('span');
        chip.className = 'kv-tag-chip';
        chip.textContent = gate;
        var rm = document.createElement('button');
        rm.type = 'button';
        rm.className = 'kv-tag-chip-remove';
        rm.setAttribute('aria-label', 'Bỏ ' + gate);
        rm.textContent = '×';
        rm.addEventListener('click', function (ev) {
          ev.stopPropagation();
          setSelected(selected.filter(function (g) { return g !== gate; }), true);
        });
        chip.appendChild(rm);
        tagsWrap.appendChild(chip);
      });

      dropdown.querySelectorAll('[data-gate-option]').forEach(function (opt) {
        var val = opt.dataset.gateOption;
        if (val === '__ALL__') {
          opt.classList.toggle('is-selected', selected.length === 0);
        } else {
          var isMatch = selected.some(function (s) { return s.toLowerCase() === val.toLowerCase(); });
          opt.classList.toggle('is-selected', isMatch);
        }
      });
    }

    function openDropdown() {
      document.querySelectorAll('.kv-multiselect.is-open').forEach(function (other) {
        if (other !== root) {
          other.classList.remove('is-open');
          var d = other.querySelector('[data-gate-dropdown]');
          var b = other.querySelector('.kv-multiselect-box');
          if (d) d.hidden = true;
          if (b) b.setAttribute('aria-expanded', 'false');
        }
      });
      root.classList.add('is-open');
      dropdown.hidden = false;
      box.setAttribute('aria-expanded', 'true');
    }

    function closeDropdown() {
      root.classList.remove('is-open');
      dropdown.hidden = true;
      box.setAttribute('aria-expanded', 'false');
    }

    box.addEventListener('click', function () {
      if (dropdown.hidden) openDropdown();
      searchInput.focus();
    });

    searchInput.addEventListener('focus', openDropdown);
    searchInput.addEventListener('input', function () {
      var q = (searchInput.value || '').trim().toLowerCase();
      dropdown.querySelectorAll('[data-gate-option]').forEach(function (opt) {
        var val = opt.dataset.gateOption;
        if (val === '__ALL__') {
          opt.hidden = q.length > 0;
        } else {
          opt.hidden = q.length > 0 && val.toLowerCase().indexOf(q) === -1;
        }
      });
      if (dropdown.hidden) openDropdown();
    });

    dropdown.querySelectorAll('[data-gate-option]').forEach(function (opt) {
      opt.addEventListener('click', function (ev) {
        ev.stopPropagation();
        var val = opt.dataset.gateOption;
        if (val === '__ALL__' && allowAll) {
          setSelected([], true);
          closeDropdown();
          return;
        }
        var current = getSelected();
        var idx = -1;
        for (var i = 0; i < current.length; i++) {
          if (current[i].toLowerCase() === val.toLowerCase()) { idx = i; break; }
        }
        if (idx >= 0) current.splice(idx, 1);
        else current.push(val);
        searchInput.value = '';
        dropdown.querySelectorAll('[data-gate-option]').forEach(function (o) { o.hidden = false; });
        setSelected(current, true);
      });
    });

    root._syncGateValue = function (csv) {
      hiddenInput.value = csv || '';
      render();
    };
    render();
  }

  document.querySelectorAll('[data-gate-multiselect]').forEach(initGateMultiselect);

  document.addEventListener('click', function (ev) {
    if (!ev.target.closest('.kv-multiselect')) {
      document.querySelectorAll('.kv-multiselect.is-open').forEach(function (ms) {
        ms.classList.remove('is-open');
        var d = ms.querySelector('[data-gate-dropdown]');
        var b = ms.querySelector('.kv-multiselect-box');
        if (d) d.hidden = true;
        if (b) b.setAttribute('aria-expanded', 'false');
      });
    }
  });

  // Inline "+ Tạo mới" for Phòng ban & Chức danh
  document.querySelectorAll('[data-quick-create]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var kind = btn.dataset.quickCreate;
      var group = btn.closest('.invoice-filter-group');
      if (!group) return;
      var existing = group.querySelector('.kv-quick-create-row');
      if (existing) { existing.remove(); return; }
      var row = document.createElement('div');
      row.className = 'kv-quick-create-row';
      var inp = document.createElement('input');
      inp.type = 'text';
      inp.placeholder = kind === 'department' ? 'Tên phòng ban mới...' : 'Tên chức danh mới...';
      var ok = document.createElement('button');
      ok.type = 'button';
      ok.textContent = 'Thêm';
      function commit() {
        var val = (inp.value || '').trim();
        if (!val) return;
        var sel = group.querySelector('select');
        var dl = document.getElementById(kind === 'department' ? 'employee-dept-list' : 'employee-pos-list');
        if (dl) {
          var optDl = document.createElement('option');
          optDl.value = val;
          dl.appendChild(optDl);
        }
        if (sel) {
          var optSel = document.createElement('option');
          optSel.value = val;
          optSel.textContent = val;
          optSel.selected = true;
          sel.appendChild(optSel);
        }
        row.remove();
      }
      ok.addEventListener('click', commit);
      inp.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); commit(); }
        if (e.key === 'Escape') row.remove();
      });
      row.appendChild(inp);
      row.appendChild(ok);
      group.appendChild(row);
      inp.focus();
    });
  });

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

  // Auto-apply Mẫu lương defaults when selected in add/edit modal
  document.querySelectorAll('[data-salary-template-select]').forEach(function (sel) {
    sel.addEventListener('change', function () {
      var opt = sel.options[sel.selectedIndex];
      var dlg = sel.closest('dialog');
      if (!opt || !dlg || !opt.dataset.tplType) return;
      var st = dlg.querySelector('[name="salary_type"]');
      var sa = dlg.querySelector('[name="salary_amount"]');
      var aen = dlg.querySelector('[name="allowance_enabled"]');
      var aamt = dlg.querySelector('[name="allowance_amount"]');
      var den = dlg.querySelector('[name="deduction_enabled"]');
      var damt = dlg.querySelector('[name="deduction_amount"]');
      if (st) st.value = opt.dataset.tplType;
      if (sa) sa.value = opt.dataset.tplAmount || '';
      if (aen) { aen.checked = opt.dataset.tplAen === '1'; aen.dispatchEvent(new Event('change')); }
      if (aamt) aamt.value = opt.dataset.tplAamt || '';
      if (den) { den.checked = opt.dataset.tplDen === '1'; den.dispatchEvent(new Event('change')); }
      if (damt) damt.value = opt.dataset.tplDamt || '';
    });
  });

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
        'start_date', 'department', 'position', 'work_branch', 'pay_branch', 'username', 'role',
        'attendance_code', 'customer_note', 'bank_account', 'bank_name',
        'bank_holder', 'id_card', 'dob', 'email', 'address',
        'salary_type', 'salary_amount', 'salary_template', 'allowance_amount',
        'deduction_amount', 'deduction_note'
      ];
      fieldMap.forEach(function (name) {
        var el = formEl.querySelector('[name="' + name + '"]');
        if (el) el.value = btn.dataset[name] || '';
      });
      var gateMs = formEl.querySelector('[data-gate-multiselect]');
      if (gateMs && typeof gateMs._syncGateValue === 'function') {
        gateMs._syncGateValue(btn.dataset.work_branch || 'Cổng chính');
      }

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
  var exportXlsxSelected = document.getElementById('employee-export-selected-xlsx');
  var exportXlsxBase = document.getElementById('employee-export-xlsx');
  var payrollXlsxSelected = document.getElementById('employee-payroll-export-xlsx');
  var payrollXlsxBase = document.getElementById('employee-payroll-xlsx');
  var payrollPdfSelected = document.getElementById('employee-payroll-export-pdf');
  var payrollPdfBase = document.getElementById('employee-payroll-pdf');

  function appendIds(baseLink, targetLink, ids) {
    if (!targetLink || !baseLink) return;
    var sep = baseLink.href.indexOf('?') >= 0 ? '&' : '?';
    targetLink.href = baseLink.href + sep + 'ids=' + encodeURIComponent(ids.join(','));
  }

  function syncSelection() {
    var ids = rowChecks.filter(function (cb) { return cb.checked; }).map(function (cb) { return cb.dataset.selectEmployee; });
    if (selectionBar) selectionBar.hidden = ids.length === 0;
    if (selectedCount) selectedCount.textContent = String(ids.length);
    if (selectAll) {
      selectAll.checked = rowChecks.length > 0 && ids.length === rowChecks.length;
      selectAll.indeterminate = ids.length > 0 && ids.length < rowChecks.length;
    }
    appendIds(exportBase, exportSelected, ids);
    appendIds(exportXlsxBase, exportXlsxSelected, ids);
    appendIds(payrollXlsxBase, payrollXlsxSelected, ids);
    appendIds(payrollPdfBase, payrollPdfSelected, ids);
  }

  document.addEventListener('click', function (event) {
    document.querySelectorAll('.employee-payroll-menu[open]').forEach(function (menu) {
      if (!menu.contains(event.target)) menu.removeAttribute('open');
    });
  });

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
