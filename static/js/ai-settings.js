(function () {
  'use strict';
  const section = document.getElementById('ai-settings');
  if (!section) return;
  const form = document.getElementById('ai-settings-form');
  const key = document.getElementById('ai-api-key');
  const model = document.getElementById('ai-model');
  const provider = document.getElementById('ai-provider');
  const base = document.getElementById('ai-base-url');
  const save = document.getElementById('ai-save');
  const test = document.getElementById('ai-test');
  const disconnect = document.getElementById('ai-disconnect');
  const toggle = document.getElementById('ai-key-toggle');
  const status = document.getElementById('ai-config-status');
  const feedback = document.getElementById('ai-settings-feedback');
  const retry = document.getElementById('ai-settings-retry');
  let config = null, busy = false;

  function tell(message, error=false) {
    feedback.textContent = message; feedback.hidden = !message; feedback.classList.toggle('is-error',error);
  }
  function sameConnection() { return config && provider.value === config.provider && base.value.trim().replace(/\/+$/,'') === config.base_url; }
  function dirty() { return config && (!sameConnection() || key.value.trim() || model.value.trim() !== config.model); }
  function controls() {
    [key,model,provider,base,toggle,save].forEach(control => { control.disabled = busy || !config; });
    const canTest = config && model.value.trim() && base.value.trim() && (key.value.trim() || (config.configured && sameConnection()));
    test.disabled = busy || !canTest;
    test.title = dirty() ? 'Lưu cấu hình vừa nhập rồi kiểm tra kết nối.' : 'Kiểm tra cấu hình đã lưu';
    if (!busy) test.textContent = dirty() ? 'Lưu & kiểm tra' : 'Kiểm tra kết nối';
    disconnect.disabled = busy || !config || (!config.configured && !config.error);
    key.required = !config || !config.configured || !sameConnection();
    key.placeholder = config && config.configured && sameConnection() ? 'Để trống để giữ khóa hiện tại' : 'Nhập khóa API của nhà cung cấp này';
    document.getElementById('ai-key-hint').textContent = config && !sameConnection() ?
      'Nhập khóa mới khi đổi nhà cung cấp hoặc địa chỉ API. Khóa cũ không được tự động dùng lại.' :
      'Khóa được lưu mã hóa và không hiển thị lại sau khi lưu.';
    form.setAttribute('aria-busy',String(busy));
  }
  function providerInfo() {
    const item = config.providers.find(item => item.id === provider.value);
    base.readOnly = item.id !== 'compatible';
    document.getElementById('ai-base-hint').textContent = item.id === 'compatible' ?
      'Nhập Base URL HTTPS công khai, ví dụ https://api.example.com/v1. Hệ thống gọi /chat/completions.' :
      'Địa chỉ chính thức của ' + item.label + '. Chọn Tùy chỉnh nếu bạn dùng cổng API khác.';
    document.getElementById('ai-provider-hint').textContent = item.protocol === 'gemini' ? 'Kết nối trực tiếp Google AI Studio.' :
      item.protocol === 'anthropic' ? 'Kết nối theo chuẩn Anthropic Messages.' : 'Kết nối theo chuẩn OpenAI Chat Completions.';
    const link = document.getElementById('ai-key-link');
    link.hidden = !item.docs_url;
    if (item.docs_url) link.href = item.docs_url; else link.removeAttribute('href');
    model.placeholder = item.default_model || 'Nhập mã model từ nhà cung cấp';
  }
  function render(data) {
    config = data;
    provider.replaceChildren(...data.providers.map(item => { const option=document.createElement('option'); option.value=item.id; option.textContent=item.label; return option; }));
    provider.value = data.provider; model.value = data.model; base.value = data.base_url;
    key.value = ''; key.type = 'password'; toggle.textContent = 'Hiện';
    toggle.setAttribute('aria-pressed','false'); toggle.setAttribute('aria-label','Hiện khóa vừa nhập');
    providerInfo();
    status.textContent = data.error ? 'Cần kiểm tra cấu hình' : data.configured ? 'Đã có khóa API' : data.source === 'disabled' ? 'Đã ngắt kết nối' : 'Chưa kết nối';
    status.className = 'badge ' + (data.configured ? 'badge-green' : 'badge-amber');
    document.getElementById('ai-config-source').textContent = data.error || (data.source === 'environment' ?
      'Đang dùng cấu hình từ biến môi trường máy chủ. Lưu tại đây để thay thế.' : data.configured ?
      'Để trống ô khóa nếu chỉ đổi model. Bấm Kiểm tra kết nối để xác nhận cấu hình đã lưu.' :
      'Lưu cấu hình để bật trợ lý AI cho các tài khoản trong hệ thống.');
    const selected = data.providers.find(item => item.id === data.provider);
    document.getElementById('ai-summary-provider').textContent = data.configured ? selected.label : 'Chưa có kết nối hoạt động';
    document.getElementById('ai-summary-model').textContent = data.configured ? data.model : '—';
    document.getElementById('ai-summary-host').textContent = data.configured ? new URL(data.base_url).host : '—';
    retry.hidden = true; controls();
  }
  async function request(path, body) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(),path === '/ai/test' ? 90000 : 12000);
    try {
      const response = await fetch('/api/support' + path,{method:body === undefined ? 'GET' : 'POST', credentials:'same-origin',
        signal:controller.signal, headers:body === undefined ? {} : {'Content-Type':'application/json','X-Support-CSRF':section.dataset.csrf},
        body:body === undefined ? undefined : JSON.stringify(body)});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Chưa hoàn tất yêu cầu. Vui lòng thử lại.');
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('Máy chủ chưa hoàn tất kiểm tra. Vui lòng thử lại sau.');
      if (error instanceof TypeError) throw new Error('Chưa kết nối được với máy chủ. Vui lòng thử lại.');
      throw error;
    } finally { window.clearTimeout(timeout); }
  }
  async function perform(action) {
    const needsSave = action === 'test' && Boolean(dirty());
    const settingsBody = {action:'save',api_key:key.value,model:model.value,provider:provider.value,base_url:base.value};
    busy = true; controls(); tell('');
    const label = action === 'test' ? test : action === 'disconnect' ? disconnect : save;
    const oldLabel = label.textContent;
    label.textContent = action === 'test' && !needsSave ? 'Đang kiểm tra…' : 'Đang lưu…';
    try {
      if (action === 'test') {
        if (needsSave) {
          render(await request('/ai/settings',settingsBody));
          document.dispatchEvent(new Event('support-config-changed'));
          label.textContent = 'Đang kiểm tra…';
        }
        const data = await request('/ai/test',{}); tell(data.message);
      } else {
        const data = await request('/ai/settings',action === 'disconnect' ? {action:'disconnect'} :
          settingsBody);
        render(data);
        tell(action === 'disconnect' ? 'Đã ngắt kết nối AI. Chat với đội ngũ vẫn hoạt động.' : 'Đã lưu cấu hình AI. Bấm Kiểm tra kết nối để xác nhận khóa, model và địa chỉ API.');
        document.dispatchEvent(new Event('support-config-changed'));
      }
    } catch (error) { tell(error.message,true); }
    finally { busy = false; label.textContent = oldLabel; controls(); }
  }
  provider.addEventListener('change',() => {
    const item = config.providers.find(item => item.id === provider.value);
    base.value = item.base_url; model.value = item.default_model; key.value = ''; key.type = 'password';
    toggle.textContent = 'Hiện'; toggle.setAttribute('aria-pressed','false'); toggle.setAttribute('aria-label','Hiện khóa vừa nhập');
    tell(''); providerInfo(); controls();
  });
  [key,model,base].forEach(input => input.addEventListener('input',controls));
  toggle.addEventListener('click',() => {
    const show = key.type === 'password'; key.type = show ? 'text' : 'password';
    toggle.textContent = show ? 'Ẩn' : 'Hiện'; toggle.setAttribute('aria-pressed',String(show));
    toggle.setAttribute('aria-label',show ? 'Ẩn khóa vừa nhập' : 'Hiện khóa vừa nhập'); key.focus();
  });
  form.addEventListener('submit',event => { event.preventDefault(); if (!busy && config && form.reportValidity()) perform('save'); });
  test.addEventListener('click',() => { if (!test.disabled && form.reportValidity()) perform('test'); });
  disconnect.addEventListener('click',() => { if (!disconnect.disabled) perform('disconnect'); });
  function load() { tell(''); retry.hidden=true; request('/ai/settings').then(render).catch(error => { status.textContent='Chưa tải được cấu hình'; tell(error.message,true); retry.hidden=false; }); }
  retry.addEventListener('click',load);
  load();
})();
