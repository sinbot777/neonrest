(() => {
  'use strict';
  const app = document.getElementById('dm-app');
  if (!app) return;
  const log = document.getElementById('dm-log');
  const status = document.getElementById('dm-live-status');
  const compose = document.getElementById('dm-compose');
  const csrf = app.dataset.csrf;
  let polling = false;
  let overviewPolling = false;
  let sending = false;
  let lastRead = '';
  let lastPresence = 0;
  const say = text => { if (status) status.textContent = text; };
  const visible = () => document.visibilityState === 'visible';
  const nearBottom = () => !log || log.scrollHeight - log.scrollTop - log.clientHeight < 90;
  const lastKey = () => log?.querySelector('[data-message-key]:last-of-type')?.dataset.messageKey || '';
  const post = (url, body) => fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'Accept': 'application/json', 'X-CSRF-Token': csrf}, body});
  function updateBadge(count) {
    document.querySelectorAll('[data-message-badge]').forEach(node => {
      node.textContent = count >= 100 ? '99+' : String(count);
      node.hidden = !count;
    });
  }
  async function markRead() {
    const through = lastKey();
    if (!visible() || !nearBottom() || !through || through === lastRead || !app.dataset.readUrl) return;
    const body = new URLSearchParams({through});
    try {
      const response = await post(app.dataset.readUrl, body);
      if (response.ok && !response.redirected) {
        const data = await response.json();
        updateBadge(data.unread);
        const notifications = document.querySelector('.notifications-link');
        if (notifications) {
          const count = notifications.querySelector('.notification-count');
          if (count) { count.hidden = !data.notifications; count.textContent = String(data.notifications); }
          notifications.setAttribute('aria-label', data.notifications ? `Notifications, ${data.notifications} unread` : 'Notifications');
        }
        lastRead = through;
        const fallback = document.querySelector('.dm-read-form');
        if (fallback) fallback.hidden = true;
      }
    } catch (_) { /* The plain form remains available when the connection fails. */ }
  }
  function reportForm(url) {
    const details = document.createElement('details'); details.className = 'dm-report';
    const summary = document.createElement('summary'); summary.textContent = 'Report this message'; details.append(summary);
    const form = document.createElement('form'); form.method = 'post'; form.action = url;
    const token = document.createElement('input'); token.type = 'hidden'; token.name = 'theme_csrf_token'; token.value = csrf;
    const label = document.createElement('label'); label.textContent = 'Why are you reporting it?';
    const reason = document.createElement('textarea'); reason.name = 'reason'; reason.maxLength = 1000; reason.required = true; reason.rows = 2; label.append(reason);
    const explanation = document.createElement('p'); explanation.className = 'dm-small'; explanation.textContent = 'This message and your explanation will be preserved for staff review. Other messages are not included.';
    const button = document.createElement('button'); button.textContent = 'Submit report';
    form.append(token, label, explanation, button); details.append(form); return details;
  }
  function appendMessage(message) {
    if (!/^[A-Za-z0-9]{16}$/.test(message.key) || log.querySelector(`[data-message-key="${message.key}"]`)) return;
    const article = document.createElement('article'); article.className = `dm-message ${message.mine ? 'dm-mine' : 'dm-theirs'}`; article.dataset.messageKey = message.key;
    const header = document.createElement('header'); const author = document.createElement('strong'); author.textContent = message.mine ? 'You' : app.dataset.peer;
    const timestamp = document.createElement('time'); timestamp.textContent = `${message.created} UTC`; header.append(author, timestamp);
    const text = document.createElement('p'); text.className = 'dm-message-body'; text.textContent = message.body;
    article.append(header, text);
    if (!message.mine && message.report_url) article.append(reportForm(message.report_url));
    log.querySelector('.dm-empty')?.remove(); log.append(article);
  }
  async function poll() {
    if (!visible() || polling || !log || !app.dataset.updatesUrl || app.dataset.history === 'yes') return;
    polling = true;
    try {
      const url = new URL(app.dataset.updatesUrl, location.origin);
      if (lastKey()) url.searchParams.set('after', lastKey());
      const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}});
      if (!response.ok || response.redirected || !response.headers.get('Content-Type')?.includes('application/json')) {
        say(response.status === 429 ? 'Updates paused briefly. Please wait.' : 'Updates paused. Refresh to check your session and conversation permissions.');
        return;
      }
      const data = await response.json();
      if (data.state !== app.dataset.state) { location.reload(); return; }
      const follow = nearBottom();
      data.messages.forEach(appendMessage);
      (data.removed || []).forEach(key => {
        if (!/^[A-Za-z0-9]{16}$/.test(key)) return;
        const text = log.querySelector(`[data-message-key="${key}"] .dm-message-body`);
        if (text) text.textContent = '[Message removed by staff]';
      });
      if (compose) compose.querySelector('fieldset').disabled = !data.can_send;
      if (follow) log.scrollTop = log.scrollHeight;
      say(data.more ? 'More messages are available. Refresh for the latest conversation.' : data.messages.length && !follow ? 'New messages below.' : '');
      updateBadge(data.unread);
      await markRead();
    } catch (_) { say('Connection interrupted. Your conversation is saved; updates will retry.'); }
    finally { polling = false; }
  }
  async function heartbeat() {
    if (!visible() || app.dataset.presence === 'invisible' || Date.now() - lastPresence < 55000) return;
    lastPresence = Date.now();
    try { await post(app.dataset.presenceUrl, new URLSearchParams()); } catch (_) { /* Presence expires automatically. */ }
  }
  async function overview() {
    if (!visible() || overviewPolling || app.dataset.sidebar === 'no') return;
    overviewPolling = true;
    try {
      const response = await fetch(app.dataset.overviewUrl, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}});
      if (!response.ok || response.redirected || !response.headers.get('Content-Type')?.includes('application/json')) return;
      const data = await response.json(); updateBadge(data.unread);
      document.querySelectorAll('[data-buddy]').forEach(button => {
        const buddy = data.buddies.find(item => item.handle === button.dataset.buddy);
        const dot = button.querySelector('.dm-status'); const text = button.querySelector('small');
        const presence = buddy?.presence || {status: 'offline', label: 'Offline', away: ''};
        if (dot) dot.className = `dm-status dm-status-${presence.status}`;
        if (text) text.textContent = presence.label + (presence.away ? ' · ' + presence.away : '');
      });
    } catch (_) { /* Refresh remains available; no presence history is synthesized. */ }
    finally { overviewPolling = false; }
  }
  function openMessenger(url, chat = false) {
    const target = new URL(url, location.origin);
    if (target.origin !== location.origin) return;
    const name = chat ? 'afterglow-chat-' + target.pathname.split('/').pop().replace(/[^a-zA-Z0-9_-]/g, '') : 'afterglow-buddies';
    const popup = window.open(target.href, name, `popup,width=${chat ? 420 : 280},height=${chat ? 480 : 450},resizable=yes,scrollbars=yes`);
    if (popup) { popup.opener = null; popup.focus(); }
    else location.assign(target.href);
  }
  document.querySelectorAll('[data-messenger-popup],[data-chat-popup]').forEach(link => link.addEventListener('click', event => {
    if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); openMessenger(link.href, link.hasAttribute('data-chat-popup'));
  }));
  document.querySelectorAll('[data-buddy]').forEach(button => button.addEventListener('click', () => {
    if (app.dataset.compact === 'yes') {
      const url = new URL(app.dataset.composeUrl, location.origin); url.searchParams.set('to', button.dataset.buddy);
      openMessenger(url.href, true); return;
    }
    const recipient = document.getElementById('dm-recipient'); recipient.value = button.dataset.buddy;
    document.getElementById('dm-start').scrollIntoView({behavior: 'smooth', block: 'center'}); recipient.focus();
  }));
  if (compose) compose.addEventListener('submit', async event => {
    event.preventDefault();
    if (sending || !compose.reportValidity()) return;
    sending = true;
    const button = compose.querySelector('button'); button.disabled = true;
    try {
      const response = await post(compose.action, new FormData(compose));
      if (!response.ok || response.redirected || !response.headers.get('Content-Type')?.includes('application/json')) {
        say(response.status === 429 ? 'You are sending quickly. Wait a moment and try again.' : 'The message was not sent. Check your session or refresh to see the current conversation settings.');
        return;
      }
      compose.querySelector('[name="body"]').value = '';
      compose.querySelector('[name="nonce"]').value = crypto.randomUUID().replaceAll('-', '');
      say('Message sent.');
      void poll();
    } catch (_) { say('Delivery is unconfirmed. Your text is still here; retrying will not send a duplicate.'); }
    finally { sending = false; button.disabled = false; }
  });
  if (log) {
    log.scrollTop = log.scrollHeight;
    log.addEventListener('scroll', () => { markRead(); }, {passive: true});
    markRead();
  }
  document.addEventListener('visibilitychange', () => { if (visible()) { poll(); heartbeat(); markRead(); overview(); } });
  heartbeat();
  setInterval(poll, 3000);
  setInterval(heartbeat, 60000);
  setInterval(overview, 30000);
})();
