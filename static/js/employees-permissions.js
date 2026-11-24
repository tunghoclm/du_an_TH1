(() => {
  'use strict';

  function initPermissionEditor(rootEl) {
    if (!rootEl) return null;
    const form = rootEl.querySelector('form');
    const jsonInput = rootEl.querySelector('[data-perm-json]');
    const gateListEl = rootEl.querySelector('[data-perm-gate-list]');
    const gateSearchEl = rootEl.querySelector('[data-perm-gate-search]');
    const permSearchEl = rootEl.querySelector('[data-perm-item-search]');
    const roleSel = rootEl.querySelector('[data-perm-role-select]');
    const clearRoleBtn = rootEl.querySelector('[data-perm-clear-role]');
    const scrollWrap = rootEl.querySelector('[data-perm-scroll]');
    const emptyEl = rootEl.querySelector('[data-perm-empty]');
    const groupsWrap = rootEl.querySelector('[data-perm-groups-wrap]');
    const tocBtns = Array.from(rootEl.querySelectorAll('[data-perm-toc]'));
    if (!form || !gateListEl || !roleSel) return null;

    let presets = {};
    let allGates = [];
    try { presets = JSON.parse(rootEl.dataset.presets || '{}'); } catch (e) {}
    try { allGates = JSON.parse(rootEl.dataset.gates || '[]'); } catch (e) {}

    let state = { gates: {}, other: { view_shared_info: false, manage_other_staff_eod: false } };
    let activeGate = allGates[0] || 'Cổng chính';

    function ensureGate(gname) {
      if (!state.gates[gname]) state.gates[gname] = { role_preset: '', perms: [] };
      return state.gates[gname];
    }

    function renderGates() {
      const q = (gateSearchEl && gateSearchEl.value || '').trim().toLowerCase();
      gateListEl.innerHTML = '';
      allGates.forEach(gname => {
        if (q && gname.toLowerCase().indexOf(q) === -1) return;
        const entry = ensureGate(gname);
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'kv-perm-gate-card' + (gname === activeGate ? ' is-active' : '');
        const roleTxt = entry.role_preset || (entry.perms.length ? 'Tùy chỉnh (' + entry.perms.length + ')' : 'Chưa gán vai trò');
        btn.innerHTML = '<b>' + gname + '</b><small class="' + (entry.role_preset || entry.perms.length ? '' : 'is-empty') + '">' + roleTxt + '</small>';
        btn.addEventListener('click', () => {
          activeGate = gname;
          renderGates();
          syncCenter();
        });
        gateListEl.appendChild(btn);
      });
    }

    function syncParentCheckboxes() {
      rootEl.querySelectorAll('.kv-perm-acc').forEach(acc => {
        const parent = acc.querySelector('[data-perm-parent]');
        const children = Array.from(acc.querySelectorAll('[data-perm-key]'));
        if (!parent || !children.length) return;
        const checkedCount = children.filter(c => c.checked).length;
        parent.checked = checkedCount === children.length;
        parent.indeterminate = checkedCount > 0 && checkedCount < children.length;
      });
    }

    function syncCenter() {
      const entry = ensureGate(activeGate);
      const hasRoleOrPerms = Boolean(entry.role_preset || entry.perms.length);
      roleSel.value = entry.role_preset && presets[entry.role_preset] ? entry.role_preset : '';
      if (emptyEl) emptyEl.hidden = hasRoleOrPerms;
      if (groupsWrap) groupsWrap.hidden = !hasRoleOrPerms;

      const permSet = new Set(entry.perms || []);
      rootEl.querySelectorAll('[data-perm-key]').forEach(cb => {
        cb.checked = permSet.has(cb.dataset.permKey);
      });
      syncParentCheckboxes();
    }

    function writeBackPerms() {
      const entry = ensureGate(activeGate);
      entry.perms = Array.from(rootEl.querySelectorAll('[data-perm-key]:checked')).map(cb => cb.dataset.permKey);
      renderGates();
    }

    roleSel.addEventListener('change', () => {
      const val = roleSel.value;
      const entry = ensureGate(activeGate);
      if (!val) {
        entry.role_preset = '';
        entry.perms = [];
      } else {
        entry.role_preset = val;
        entry.perms = (presets[val] || []).slice();
      }
      renderGates();
      syncCenter();
    });

    if (clearRoleBtn) {
      clearRoleBtn.addEventListener('click', () => {
        const entry = ensureGate(activeGate);
        entry.role_preset = '';
        entry.perms = [];
        renderGates();
        syncCenter();
      });
    }

    rootEl.querySelectorAll('.kv-perm-acc-head').forEach(head => {
      head.addEventListener('click', e => {
        if (e.target.closest('label') || e.target.tagName === 'INPUT') return;
        head.closest('.kv-perm-acc').classList.toggle('is-open');
      });
    });

    rootEl.querySelectorAll('[data-perm-parent]').forEach(parent => {
      parent.addEventListener('change', () => {
        const acc = parent.closest('.kv-perm-acc');
        acc.querySelectorAll('[data-perm-key]').forEach(cb => { cb.checked = parent.checked; });
        ensureGate(activeGate).role_preset = '';
        syncParentCheckboxes();
        writeBackPerms();
        syncCenter();
      });
    });

    rootEl.querySelectorAll('[data-perm-key]').forEach(cb => {
      cb.addEventListener('change', () => {
        ensureGate(activeGate).role_preset = '';
        syncParentCheckboxes();
        writeBackPerms();
      });
    });

    if (gateSearchEl) gateSearchEl.addEventListener('input', renderGates);

    if (permSearchEl) {
      permSearchEl.addEventListener('input', () => {
        const q = (permSearchEl.value || '').trim().toLowerCase();
        rootEl.querySelectorAll('.kv-perm-group-card').forEach(card => {
          if (!q) {
            card.hidden = false;
            card.querySelectorAll('.kv-perm-acc').forEach(a => { a.hidden = false; });
            return;
          }
          const match = card.textContent.toLowerCase().indexOf(q) !== -1;
          card.hidden = !match;
          card.querySelectorAll('.kv-perm-acc').forEach(acc => {
            const accMatch = acc.textContent.toLowerCase().indexOf(q) !== -1;
            acc.hidden = !accMatch;
            if (accMatch) acc.classList.add('is-open');
          });
        });
      });
    }

    tocBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        tocBtns.forEach(b => b.classList.toggle('is-active', b === btn));
        const target = rootEl.querySelector('[data-perm-group="' + btn.dataset.permToc + '"]');
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });

    if (scrollWrap) {
      scrollWrap.addEventListener('scroll', () => {
        const cards = Array.from(rootEl.querySelectorAll('.kv-perm-group-card:not([hidden])'));
        let currentId = cards[0] ? cards[0].dataset.permGroup : '';
        const top = scrollWrap.getBoundingClientRect().top + 40;
        cards.forEach(c => {
          if (c.getBoundingClientRect().top <= top) currentId = c.dataset.permGroup;
        });
        tocBtns.forEach(b => b.classList.toggle('is-active', b.dataset.permToc === currentId));
      });
    }

    form.addEventListener('submit', () => {
      if (!jsonInput) return;
      const other = {};
      rootEl.querySelectorAll('[data-other-perm]').forEach(cb => {
        other[cb.dataset.otherPerm] = cb.checked;
      });
      jsonInput.value = JSON.stringify({ gates: state.gates, other });
    });

    return {
      load(nextState) {
        state = {
          gates: nextState && nextState.gates ? JSON.parse(JSON.stringify(nextState.gates)) : {},
          other: nextState && nextState.other ? Object.assign({}, nextState.other) : { view_shared_info: false, manage_other_staff_eod: false },
        };
        activeGate = allGates.find(g => state.gates[g] && (state.gates[g].role_preset || (state.gates[g].perms || []).length)) || allGates[0] || 'Cổng chính';
        if (gateSearchEl) gateSearchEl.value = '';
        if (permSearchEl) {
          permSearchEl.value = '';
          permSearchEl.dispatchEvent(new Event('input'));
        }
        rootEl.querySelectorAll('[data-other-perm]').forEach(cb => {
          cb.checked = Boolean(state.other && state.other[cb.dataset.otherPerm]);
        });
        renderGates();
        syncCenter();
      },
      presets,
      allGates,
    };
  }

  // 1. Standalone Edit Permissions Modal
  const editPermDlg = document.getElementById('edit-permissions-dialog');
  const editPermApi = initPermissionEditor(editPermDlg);
  if (editPermDlg && editPermApi) {
    const tabBtns = Array.from(editPermDlg.querySelectorAll('[data-perm-tab]'));
    const tabPanels = Array.from(editPermDlg.querySelectorAll('[data-perm-tabpanel]'));
    const switchTab = name => {
      tabBtns.forEach(b => b.setAttribute('aria-selected', b.dataset.permTab === name ? 'true' : 'false'));
      tabPanels.forEach(p => { p.hidden = p.dataset.permTabpanel !== name; });
    };
    tabBtns.forEach(b => b.addEventListener('click', () => switchTab(b.dataset.permTab)));

    const titleEl = document.getElementById('perm-modal-title');
    const form = document.getElementById('edit-permissions-form');
    document.querySelectorAll('[data-open-perm-modal]').forEach(btn => {
      btn.addEventListener('click', () => {
        if (form) form.action = btn.dataset.action || '';
        if (titleEl) titleEl.textContent = 'Sửa phân quyền của ' + (btn.dataset.username || '');
        let parsed = {};
        try { parsed = JSON.parse(btn.dataset.permissions || '{}'); } catch (e) {}
        editPermApi.load(parsed);
        switchTab('role');
        if (typeof editPermDlg.showModal === 'function') editPermDlg.showModal();
        else editPermDlg.setAttribute('open', '');
      });
    });
  }

  // 2. Add Employee Modal (4 tabs: info | salary | perm_role | perm_other)
  const addDlg = document.getElementById('add-employee-dialog');
  const addPermApi = initPermissionEditor(addDlg);
  if (addDlg && addPermApi) {
    const resetAddPerms = () => {
      const roleSel = addDlg.querySelector('#new-role');
      const presetName = roleSel && roleSel.value === 'admin' ? 'Quản trị viên' : 'Nhân viên vận hành';
      const wbInp = addDlg.querySelector('#new-work-branch');
      const branches = (wbInp && wbInp.value ? wbInp.value : 'Cổng chính').split(',').map(s => s.trim()).filter(Boolean);
      const gates = {};
      branches.forEach(b => {
        gates[b] = { role_preset: presetName, perms: (addPermApi.presets[presetName] || []).slice() };
      });
      addPermApi.load({
        gates,
        other: { view_shared_info: presetName === 'Quản trị viên', manage_other_staff_eod: presetName === 'Quản trị viên' },
      });
    };
    resetAddPerms();
    document.getElementById('open-add-employee')?.addEventListener('click', resetAddPerms);
    addDlg.querySelectorAll('[data-modal-tab]').forEach(btn => {
      btn.addEventListener('click', () => {
        addDlg.classList.toggle('is-perm-wide', btn.dataset.modalTab === 'perm_role');
      });
    });
  }
})();
