(function () {
  'use strict';
  const section = document.getElementById('ai-settings');
  if (!section) return;
  const el = id => document.getElementById('ai-' + id);
  let config = null, documents = [], selected = null, busy = false, edited = false;
  function tell(message, error = false) {
    el('settings-feedback').textContent = message;
    el('settings-feedback').hidden = !message;
    el('settings-feedback').classList.toggle('is-error', error);
  }
  function controls() {
    section.querySelectorAll('input,textarea,select,button').forEach(item => {
      if (item !== el('settings-retry')) item.disabled = busy || !config;
    });
    el('delete').disabled = busy || selected === null;
    el('train').disabled = busy || !config || !config.enabled_count || edited;
    el('test').disabled = busy || !config || !config.configured;
    section.setAttribute('aria-busy', String(busy));
  }
  function render(data) {
    config = data;
    el('name').value = data.name; el('enabled').checked = data.enabled;
    el('threshold').value = data.threshold; el('fallback').value = data.fallback;
    el('config-status').textContent = data.configured ? 'Đang chạy nội bộ' : 'Đang tắt';
    el('config-status').className = 'badge ' + (data.configured ? 'badge-green' : 'badge-amber');
    el('summary-name').textContent = data.name;
    el('summary-documents').textContent = data.knowledge_count + ' mục · ' + data.enabled_count + ' đang bật';
    el('summary-version').textContent = data.model ? 'v' + data.model.id + ' · ' + data.model.document_count + ' mục' : 'Chưa huấn luyện';
    el('summary-samples').textContent = data.model ? data.model.sample_count : '—';
    el('summary-trained').textContent = data.model ? new Date(data.model.trained_at).toLocaleString('vi-VN') : '—';
    el('training-note').textContent = data.needs_training ? 'Có thay đổi chưa huấn luyện. Chat vẫn dùng phiên bản trước.' : 'Phiên bản hiện tại đã học toàn bộ thay đổi đã lưu.';
    el('test-result').hidden = true;
    controls();
  }
  function renderList() {
    const query = el('knowledge-search').value.toLocaleLowerCase('vi-VN').trim();
    const items = documents.filter(item => (item.title + ' ' + item.questions.join(' ')).toLocaleLowerCase('vi-VN').includes(query));
    el('knowledge-select').replaceChildren(...items.map(item => {
      const option = document.createElement('option'); option.value = item.id;
      option.textContent = item.title + (item.enabled ? '' : ' · Đã tắt'); return option;
    }));
    el('knowledge-select').value = selected === null ? '' : String(selected);
  }
  function edit(item = null) {
    selected = item ? item.id : null; edited = false;
    el('editor-heading').textContent = item ? 'Chỉnh sửa kiến thức' : 'Thêm kiến thức mới';
    el('knowledge-title').value = item ? item.title : '';
    el('questions').value = item ? item.questions.join('\n') : '';
    el('answer').value = item ? item.answer : '';
    el('knowledge-enabled').checked = item ? item.enabled : true;
    renderList(); controls();
  }
  async function request(path, body) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), path === '/ai/train' ? 60000 : 15000);
    try {
      const response = await fetch('/api/support' + path, {
        method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', signal: controller.signal,
        headers: body === undefined ? {} : {'Content-Type': 'application/json', 'X-Support-CSRF': section.dataset.csrf},
        body: body === undefined ? undefined : JSON.stringify(body)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Chưa hoàn tất yêu cầu. Vui lòng thử lại.');
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('Máy chủ chưa phản hồi. Tải lại trạng thái trước khi thử lại.');
      if (error instanceof TypeError) throw new Error('Chưa kết nối được với máy chủ.');
      throw error;
    } finally { window.clearTimeout(timer); }
  }
  async function run(action) {
    if (busy) return;
    busy = true; controls(); tell('');
    try { await action(); }
    catch (error) { tell(error.message, true); }
    finally { busy = false; controls(); }
  }
  async function reloadDocuments(id = null) {
    documents = (await request('/ai/knowledge')).documents;
    edit(documents.find(item => item.id === id) || null);
  }
  function changed() { document.dispatchEvent(new Event('support-config-changed')); }
  el('settings-form').addEventListener('submit', event => {
    event.preventDefault();
    if (!config || !event.target.reportValidity()) return;
    const data = {action: 'save', name: el('name').value, enabled: el('enabled').checked,
      threshold: Number(el('threshold').value), fallback: el('fallback').value};
    run(async () => { render(await request('/ai/settings', data)); tell('Đã lưu cấu hình trợ lý nội bộ.'); changed(); });
  });
  el('knowledge-form').addEventListener('submit', event => {
    event.preventDefault();
    if (!config || !event.target.reportValidity()) return;
    const data = {title: el('knowledge-title').value, questions: el('questions').value.split(/\r?\n/).map(item => item.trim()).filter(Boolean),
      answer: el('answer').value, enabled: el('knowledge-enabled').checked};
    if (selected !== null) data.id = selected;
    run(async () => {
      const result = await request('/ai/knowledge', data);
      render(result.settings); await reloadDocuments(result.id);
      tell('Đã lưu kiến thức. Bấm Huấn luyện để áp dụng cho chat.');
    });
  });
  el('knowledge-form').addEventListener('input', () => { edited = true; controls(); });
  el('knowledge-select').addEventListener('change', () => {
    if (edited) { el('knowledge-select').value = selected === null ? '' : String(selected); tell('Lưu kiến thức hoặc bấm Hủy sửa trước khi chọn mục khác.', true); return; }
    edit(documents.find(item => item.id === Number(el('knowledge-select').value)) || null);
  });
  el('knowledge-search').addEventListener('input', renderList);
  el('new').addEventListener('click', () => {
    if (edited) { tell('Lưu kiến thức hoặc bấm Hủy sửa trước khi thêm mục mới.', true); return; }
    edit(); el('knowledge-title').focus();
  });
  el('cancel').addEventListener('click', () => { edit(documents.find(item => item.id === selected) || null); tell(''); });
  el('delete').addEventListener('click', () => {
    if (selected === null) return;
    run(async () => {
      const result = await request('/ai/knowledge/' + selected + '/delete', {});
      render(result.settings); await reloadDocuments(); tell('Đã xóa khỏi kho biên soạn. Bấm Huấn luyện để áp dụng.');
    });
  });
  el('train').addEventListener('click', () => run(async () => {
    const button = el('train'); button.textContent = 'Đang huấn luyện…';
    try { render(await request('/ai/train', {})); tell('Huấn luyện thành công. Chat đã dùng phiên bản mới.'); changed(); }
    finally { button.textContent = 'Huấn luyện'; }
  }));
  el('test-form').addEventListener('submit', event => {
    event.preventDefault();
    if (!config || !event.target.reportValidity()) return;
    const text = el('test-question').value;
    run(async () => {
      el('test-result').hidden = true;
      const result = await request('/ai/test', {text});
      el('test-answer').textContent = result.answer;
      el('test-meta').textContent = result.source === 'parking_data' ?
        result.title + ' · ' + (result.matched ? 'Dữ liệu hệ thống vừa tra cứu' : 'Cần làm rõ câu hỏi') :
        'v' + result.model_version + ' · ' + (result.matched ? result.title : 'Chưa nhận diện chắc chắn') + ' · Độ tương đồng ' + Math.round(result.confidence * 100) + '%';
      el('test-result').hidden = false;
    });
  });
  el('import').addEventListener('click', () => {
    if (edited) { tell('Lưu kiến thức hoặc bấm Hủy sửa trước khi nhập tệp.', true); return; }
    el('import-file').click();
  });
  el('import-file').addEventListener('change', event => {
    const file = event.target.files[0]; event.target.value = '';
    if (!file) return;
    run(async () => {
      if (file.size > 8 * 1024 * 1024) throw new Error('Tệp JSON có kích thước tối đa 8 MB.');
      let body;
      try { body = JSON.parse(await file.text()); } catch (_) { throw new Error('Tệp JSON chưa hợp lệ.'); }
      const result = await request('/ai/knowledge/import', body);
      render(result.settings); await reloadDocuments(); tell('Đã nhập ' + result.imported + ' mục. Bấm Huấn luyện để áp dụng.');
    });
  });
  async function load() {
    el('settings-retry').hidden = true;
    await run(async () => {
      try {
        const [data, corpus] = await Promise.all([request('/ai/settings'), request('/ai/knowledge')]);
        documents = corpus.documents; render(data); edit();
      } catch (error) { el('settings-retry').hidden = false; throw error; }
    });
  }
  el('settings-retry').addEventListener('click', load);
  load();
})();
