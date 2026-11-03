(function () {
  'use strict';
  const widget = document.getElementById('support-widget');
  if (!widget) return;
  const panel = document.getElementById('support-panel');
  const launcher = document.getElementById('support-launcher');
  const closeButton = document.getElementById('support-close');
  const errorBox = document.getElementById('support-error');
  const screens = {home:document.getElementById('support-home'), team:document.getElementById('support-team'), chat:document.getElementById('support-chat')};
  const input = document.getElementById('support-message-input');
  const form = document.getElementById('support-message-form');
  const sendButton = document.getElementById('support-send');
  const messageArea = document.getElementById('support-messages');
  const messageList = document.getElementById('support-message-list');
  const olderButton = document.getElementById('support-load-older');
  const newButton = document.getElementById('support-new-message');
  const notice = document.getElementById('support-chat-notice');
  const avatar = document.getElementById('support-chat-avatar');
  const aiIcon = avatar.firstElementChild.cloneNode(true);
  const state = {open:false, view:'home', kind:null, thread:null, messages:[], aiMessages:[], aiPending:false,
    aiConfigured:false, aiLabel:'dịch vụ AI đã cấu hình', loaded:false, csrf:widget.dataset.csrf, bootstrap:null, epoch:0, authExpired:false,
    posting:new Set(), drafts:new Map(), retries:new Map(), read:new Map(), reading:new Set(), hasOlder:false};
  let timer, polling = false, bootstrapPending = null, directorySignature = '', interactionVersion = 0;

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function initials(name) {
    const words = (name || 'KH').trim().split(/\s+/);
    return (words.length > 1 ? words[0][0] + words[words.length - 1][0] : words[0].slice(0,2)).toUpperCase();
  }
  function timeLabel(value, full) {
    const stamp = new Date(value);
    if (Number.isNaN(stamp.getTime())) return '';
    return new Intl.DateTimeFormat('vi-VN', full ? {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'} : {hour:'2-digit',minute:'2-digit'}).format(stamp);
  }
  function uuid() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r=Math.floor(Math.random()*16); return (c==='x'?r:(r&3|8)).toString(16); });
  }
  function key() { return state.kind === 'ai' ? 'ai' : 'thread-' + (state.thread ? state.thread.id : ''); }
  function showError(message) { errorBox.textContent = message || ''; errorBox.hidden = !message; }
  async function api(path, body, timeout=12000) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch('/api/support' + path, {method:body === undefined ? 'GET' : 'POST',
        credentials:'same-origin', signal:controller.signal,
        headers:body === undefined ? {} : {'Content-Type':'application/json','X-Support-CSRF':state.csrf},
        body:body === undefined ? undefined : JSON.stringify(body)});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 401) state.authExpired = true;
        const error = new Error(data.error || 'Chưa hoàn tất yêu cầu. Vui lòng thử lại.');
        error.status = response.status;
        throw error;
      }
      return data;
    } catch (error) {
      if (error.status) throw error;
      throw new Error(error.name === 'AbortError' ? 'Kết nối đang chậm. Vui lòng thử lại.' : 'Chưa kết nối được. Vui lòng kiểm tra mạng và thử lại.');
    } finally { window.clearTimeout(timeoutId); }
  }

  function updateBadges(count) {
    widget.querySelectorAll('[data-support-unread]').forEach(badge => { badge.textContent = count > 99 ? '99+' : String(count); badge.hidden = count === 0; });
    launcher.setAttribute('aria-label', count ? 'Mở hỗ trợ, ' + count + ' tin chưa đọc' : 'Mở hỗ trợ');
  }
  function person(item, thread) {
    const button = node('button','support-person');
    button.type = 'button';
    button.dataset[thread ? 'threadId' : 'agentId'] = item.id;
    button.setAttribute('aria-label', (thread ? 'Mở cuộc trò chuyện với ' : 'Trò chuyện với ') + item.name);
    button.append(node('span','support-person-avatar',initials(item.name)));
    const text = node('span');
    text.append(node('b','',item.name),node('small','',thread ? (item.snippet || 'Chưa có tin nhắn') : item.role));
    button.append(text);
    const end = node('span');
    if (thread) {
      const time = node('time','',timeLabel(item.updated_at)); time.dateTime = item.updated_at; end.append(time);
      if (item.unread) end.append(node('span','support-unread',item.unread > 99 ? '99+' : String(item.unread)));
    }
    button.append(end);
    button.addEventListener('click', async () => {
      showError('');
      if (thread) { openThread(item); return; }
      button.disabled = true;
      try {
        const result = await api('/threads',{agent_id:item.id});
        if (state.open && state.view === 'team') openThread(result.thread);
        refreshBootstrap().catch(() => {});
      } catch (error) { showError(error.message); }
      finally { button.disabled = false; }
    });
    return button;
  }
  function renderDirectory(data) {
    const signature = JSON.stringify([data.staff,data.threads,data.me.role]);
    if (signature === directorySignature) return;
    directorySignature = signature;
    const focused = document.activeElement;
    const focusKey = focused && (focused.dataset.threadId ? ['threadId',focused.dataset.threadId] : focused.dataset.agentId ? ['agentId',focused.dataset.agentId] : null);
    const threads = document.getElementById('support-thread-list');
    const staff = document.getElementById('support-staff-list');
    threads.replaceChildren(); staff.replaceChildren();
    document.getElementById('support-inbox-title').textContent = data.me.role === 'user' ? 'Cuộc trò chuyện của bạn' : 'Hộp thư của bạn';
    data.threads.forEach(item => threads.append(person(item,true)));
    data.staff.forEach(item => staff.append(person(item,false)));
    if (!data.threads.length) threads.append(node('p','support-empty','Chưa có cuộc trò chuyện. Hãy chọn người hỗ trợ bên dưới.'));
    if (!data.staff.length) staff.append(node('p','support-empty','Hiện chưa có người hỗ trợ khác. Bạn vẫn có thể xem hộp thư và sử dụng trợ lý AI.'));
    if (focusKey) {
      const match = Array.from(widget.querySelectorAll('.support-person')).find(b => b.dataset[focusKey[0]] === focusKey[1]);
      if (match) match.focus({preventScroll:true});
    }
  }
  function refreshBootstrap() {
    if (bootstrapPending) return bootstrapPending;
    bootstrapPending = api('/bootstrap').then(data => {
      state.bootstrap = data; state.csrf = data.csrf_token; state.aiConfigured = data.ai_configured;
      updateAIIdentity(data);
      updateBadges(data.unread_total); renderDirectory(data);
      if (state.view === 'chat' && state.kind === 'human' && state.thread) {
        const current = data.threads.find(t => t.id === state.thread.id);
        if (current) { state.thread = current; updateCompose(); }
      }
      return data;
    }).finally(() => { bootstrapPending = null; });
    return bootstrapPending;
  }

  function updateAIIdentity(data) {
    if (data.ai && data.ai.label) state.aiLabel = data.ai.label;
    document.getElementById('support-ai-description').textContent = state.aiConfigured ? 'Giải đáp nhanh cùng ' + state.aiLabel : 'Giải đáp thắc mắc về Smart Parking';
    if (state.view === 'chat' && state.kind === 'ai') {
      document.getElementById('support-chat-subtitle').textContent = state.aiConfigured ? 'Được hỗ trợ bởi ' + state.aiLabel : 'Hỗ trợ Smart Parking';
      document.getElementById('support-chat-footnote').textContent = 'Nội dung chat AI được gửi tới ' + state.aiLabel + ' · Shift + Enter để xuống dòng';
    }
  }

  function saveDraft() { if (state.view === 'chat') state.drafts.set(key(),input.value); }
  function view(name) {
    saveDraft(); state.view = name; state.epoch++; showError('');
    Object.keys(screens).forEach(id => { screens[id].hidden = id !== name; });
    const focusTarget = screens[name].querySelector('button,summary');
    if (state.open && focusTarget) focusTarget.focus({preventScroll:true});
  }
  function updateCompose() {
    const busy = state.posting.has(key()) || (state.kind === 'ai' && state.aiPending);
    const available = state.loaded && !state.authExpired && (state.kind === 'ai' ? state.aiConfigured : state.thread && state.thread.can_send);
    input.disabled = !available || busy;
    sendButton.disabled = input.disabled || !input.value.trim();
    document.getElementById('support-typing').hidden = !(state.kind === 'ai' && busy);
    const text = state.kind === 'ai' ? (!state.aiConfigured ? 'Trợ lý AI chưa được kết nối. Bạn có thể chọn Chat với đội ngũ.' : '') :
      (state.thread && !state.thread.can_send ? 'Người nhận hiện không sẵn sàng. Bạn vẫn có thể xem lịch sử trò chuyện.' : '');
    notice.textContent = text; notice.hidden = !text;
  }
  function chatHeader(title, subtitle) {
    document.getElementById('support-chat-title').textContent = title;
    document.getElementById('support-chat-subtitle').textContent = subtitle;
    document.getElementById('support-chat-footnote').textContent = state.kind === 'ai' ? 'Nội dung chat AI được gửi tới ' + state.aiLabel + ' · Shift + Enter để xuống dòng' : 'Tin nhắn riêng với người hỗ trợ · Shift + Enter để xuống dòng';
    if (state.kind === 'ai') avatar.replaceChildren(aiIcon.cloneNode(true)); else avatar.textContent = initials(title);
    input.value = state.drafts.get(key()) || ''; growInput(); updateCompose();
  }
  function atBottom() { return messageArea.scrollHeight - messageArea.scrollTop - messageArea.clientHeight < 80; }
  function bottom() { messageArea.scrollTop = messageArea.scrollHeight; newButton.hidden = true; markRead(); }
  function messageNode(message) {
    const row = node('div','support-message' + (message.mine ? ' mine' : ''));
    row.dataset.messageId = message.id;
    if (!message.mine) row.append(node('span','support-message-sender',state.kind === 'ai' ? 'Trợ lý AI' : message.sender));
    row.append(node('div','bubble',message.text));
    const time = node('time','',timeLabel(message.created_at,true)); time.dateTime = message.created_at || ''; row.append(time);
    return row;
  }
  function renderMessages(messages, forceBottom) {
    const shouldFollow = forceBottom || atBottom();
    const ids = new Set(messages.map(m => String(m.id)));
    messageList.querySelectorAll('[data-message-id]').forEach(row => { if (!ids.has(row.dataset.messageId)) row.remove(); });
    messageList.querySelectorAll('.support-empty').forEach(row => row.remove());
    const existing = new Map(Array.from(messageList.children).map(row => [row.dataset.messageId,row]));
    let previous = null;
    messages.forEach(message => {
      const id = String(message.id);
      let row = existing.get(id);
      if (!row) { row = messageNode(message); messageList.insertBefore(row, previous ? previous.nextSibling : messageList.firstChild); }
      previous = row;
    });
    if (!messages.length) messageList.append(node('p','support-empty',state.kind === 'ai' ? 'Bạn cần hướng dẫn về xe vào/ra, vé tháng hay hóa đơn?' : 'Gửi tin nhắn đầu tiên để bắt đầu trò chuyện. Người hỗ trợ sẽ phản hồi tại đây.'));
    olderButton.hidden = state.kind === 'ai' || !state.hasOlder;
    if (shouldFollow) bottom(); else if (messages.length) newButton.hidden = false;
  }
  function markRead() {
    if (!state.open || document.hidden || state.view !== 'chat' || state.kind !== 'human' || !state.messages.length || !atBottom()) return;
    const id = state.thread.id, last = state.messages[state.messages.length - 1].id;
    if ((state.read.get(id) || 0) >= last || state.reading.has(id)) return;
    state.reading.add(id);
    api('/threads/' + id + '/read',{last_id:last}).then(() => { state.read.set(id,last); refreshBootstrap().catch(() => {}); }).catch(() => {}).finally(() => state.reading.delete(id));
  }
  function mergeMessages(messages) {
    const map = new Map(state.messages.map(m => [m.id,m]));
    messages.forEach(message => map.set(message.id,message));
    state.messages = Array.from(map.values()).sort((a,b) => a.id-b.id);
  }
  function reconcileSend(channel, messages, pending) {
    const retry = state.retries.get(channel);
    if (!retry) return;
    if (messages.some(message => message.mine && message.client_id === retry.client_id)) {
      state.retries.delete(channel); state.drafts.delete(channel);
      if (state.view === 'chat' && key() === channel && input.value.trim() === retry.text) { input.value = ''; growInput(); }
    } else if (channel === 'ai' && !pending && !state.posting.has(channel)) state.retries.delete(channel);
  }
  async function loadThread(initial=false, before=null) {
    const epoch = state.epoch, id = state.thread.id;
    let path = '/threads/' + id + '/messages';
    if (before) path += '?before=' + before;
    else if (!initial && state.messages.length) path += '?after=' + state.messages[state.messages.length-1].id;
    const result = await api(path);
    if (epoch !== state.epoch || state.kind !== 'human') return;
    const oldHeight = messageArea.scrollHeight, oldTop = messageArea.scrollTop;
    state.thread = result.thread;
    if (initial) state.messages = result.messages; else mergeMessages(result.messages);
    reconcileSend('thread-' + id,state.messages,false);
    if (initial || before) state.hasOlder = result.has_older;
    state.loaded = true; updateCompose();
    if (initial || before || result.messages.length) renderMessages(state.messages,initial);
    if (before) messageArea.scrollTop = oldTop + messageArea.scrollHeight - oldHeight;
    if (result.has_more) await loadThread(false);
  }
  function openThread(thread) {
    view('chat'); state.kind = 'human'; state.thread = thread; state.messages = []; state.loaded = false; state.hasOlder = false;
    messageList.replaceChildren(node('p','support-empty','Đang tải cuộc trò chuyện…')); olderButton.hidden = true; newButton.hidden = true;
    chatHeader(thread.name,thread.role + ' · Tin nhắn được lưu lại');
    loadThread(true).catch(error => { if (state.view === 'chat' && state.kind === 'human' && state.thread.id === thread.id) showError(error.message); });
  }
  async function loadAI() {
    const epoch = state.epoch;
    const result = await api('/ai/history');
    state.aiMessages = result.messages; state.aiPending = result.pending; state.aiConfigured = result.configured;
    updateAIIdentity(result);
    reconcileSend('ai',state.aiMessages,state.aiPending);
    if (epoch !== state.epoch || state.kind !== 'ai') return;
    state.loaded = true; updateCompose(); renderMessages(state.aiMessages);
  }
  function openAI() {
    view('chat'); state.kind = 'ai'; state.thread = null; state.loaded = false; state.messages = []; state.hasOlder = false;
    messageList.replaceChildren(); olderButton.hidden = true; newButton.hidden = true;
    chatHeader('Trợ lý AI',state.aiConfigured ? 'Được hỗ trợ bởi ' + state.aiLabel : 'Hỗ trợ Smart Parking');
    loadAI().then(() => { if (state.kind === 'ai') bottom(); }).catch(error => showError(error.message));
  }
  function openTeam() {
    view('team'); state.kind = null;
    if (!state.bootstrap) {
      document.getElementById('support-thread-list').replaceChildren(node('p','support-empty','Đang tải hộp thư…'));
    }
    refreshBootstrap().catch(error => showError(error.message));
  }
  function toggle(open) {
    state.open = open; widget.classList.toggle('is-open',open); panel.inert = !open;
    panel.setAttribute('aria-hidden',String(!open)); launcher.setAttribute('aria-expanded',String(open)); launcher.tabIndex = open ? -1 : 0;
    if (open) { closeButton.focus({preventScroll:true}); refreshBootstrap().catch(error => showError(error.message)); pollSoon(); }
    else { saveDraft(); launcher.focus({preventScroll:true}); pollSoon(); }
  }
  function growInput() { input.style.height = 'auto'; input.style.height = Math.min(100,input.scrollHeight) + 'px'; }

  launcher.addEventListener('click', () => toggle(true));
  closeButton.addEventListener('click', () => toggle(false));
  widget.querySelectorAll('[data-support-action]').forEach(button => button.addEventListener('click', () => {
    const action = button.dataset.supportAction;
    if (action === 'home') { view('home'); state.kind = null; }
    else if (action === 'team') openTeam();
    else if (action === 'ai') openAI();
    else if (action === 'back') { if (state.kind === 'human') openTeam(); else { view('home'); state.kind = null; } }
  }));
  document.addEventListener('pointerdown', () => { interactionVersion++; },true);
  document.addEventListener('keydown', event => {
    interactionVersion++;
    if (event.key === 'Escape' && state.open && (panel.contains(event.target) || event.target === document.body)) {
      event.preventDefault(); event.stopPropagation(); toggle(false);
    }
  },true);
  input.addEventListener('input', () => { state.drafts.set(key(),input.value); growInput(); updateCompose(); });
  input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (!sendButton.disabled) form.requestSubmit(); } });
  messageArea.addEventListener('scroll', () => { if (atBottom()) { newButton.hidden = true; markRead(); } },{passive:true});
  newButton.addEventListener('click',bottom);
  olderButton.addEventListener('click', async () => {
    if (!state.messages.length) return;
    olderButton.disabled = true;
    try { await loadThread(false,state.messages[0].id); } catch (error) { showError(error.message); }
    finally { olderButton.disabled = false; }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const channel = key(), text = input.value.trim();
    if (!text || text.length > 2000 || sendButton.disabled || state.posting.has(channel)) return;
    const kind = state.kind, threadId = state.thread && state.thread.id;
    const submissionInteraction = interactionVersion;
    let retry = state.retries.get(channel);
    if (!retry || retry.text !== text) { retry = {text:text,client_id:uuid()}; state.retries.set(channel,retry); }
    state.posting.add(channel); if (kind === 'ai') state.aiPending = true;
    showError(''); updateCompose();
    try {
      const result = await api(kind === 'ai' ? '/ai/messages' : '/threads/' + threadId + '/messages',retry,kind === 'ai' ? 90000 : 45000);
      state.retries.delete(channel); state.drafts.delete(channel);
      if (kind === 'ai') { state.aiMessages = result.messages; state.aiPending = result.pending; }
      if (state.view === 'chat' && key() === channel) {
        input.value = ''; growInput();
        if (kind === 'ai') renderMessages(state.aiMessages,true);
        else { mergeMessages([result.message]); renderMessages(state.messages,true); }
      }
      refreshBootstrap().catch(() => {});
    } catch (error) {
      if (kind === 'ai') { state.aiPending = false; if (error.status && error.status !== 409) state.retries.delete(channel); }
      if (state.view === 'chat' && key() === channel) showError(error.message);
    } finally {
      state.posting.delete(channel); updateCompose();
      if (state.open && state.view === 'chat' && key() === channel && interactionVersion === submissionInteraction && !input.disabled) input.focus({preventScroll:true});
      if (kind === 'ai' && state.view === 'chat' && state.kind === 'ai') loadAI().catch(() => {});
    }
  });

  function pollSoon() { window.clearTimeout(timer); timer = window.setTimeout(poll, state.open ? 3000 : 15000); }
  async function poll() {
    if (polling || document.hidden || state.authExpired) { pollSoon(); return; }
    polling = true;
    try {
      await refreshBootstrap();
      if (state.open && state.view === 'chat') {
        if (state.kind === 'human') await loadThread(false);
        else if (state.kind === 'ai' && !state.posting.has('ai')) await loadAI();
      }
    } catch (error) { if (state.authExpired && state.open) showError(error.message); }
    finally { polling = false; if (!state.authExpired) pollSoon(); }
  }
  document.addEventListener('visibilitychange', () => { window.clearTimeout(timer); if (!document.hidden) poll(); });
  document.addEventListener('support-config-changed', () => {
    refreshBootstrap().then(() => {
      if (state.view === 'chat' && state.kind === 'ai' && !state.posting.has('ai')) return loadAI();
    }).catch(() => {});
  });
  window.addEventListener('pagehide', () => window.clearTimeout(timer));
  window.addEventListener('pageshow',pollSoon);
  refreshBootstrap().catch(() => {}).finally(pollSoon);
})();
