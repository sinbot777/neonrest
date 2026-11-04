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
  let reading = false;
  let pendingRead = false;
  let readDue = 0;
  let timer;
  let cycling = false;
  let stopped = false;
  let nextPoll = 0;
  let nextOverview = 0;
  let retryAt = 0;
  let failures = 0;
  let activityAt = Date.now();
  const activeInterval = () => Date.now() - activityAt < 30000 ? 3000 : Date.now() - activityAt < 120000 ? 6000 : 15000;
  function schedule(delay = 0) {
    clearTimeout(timer);
    if (!stopped) timer = setTimeout(cycle, Math.max(0, delay));
  }
  function queueRead() {
    if (!pendingRead) readDue = Date.now() + 1000;
    pendingRead = true;
    schedule(Math.max(0, readDue - Date.now()));
  }
  function refreshSoon() {
    activityAt = Date.now(); nextPoll = 0; schedule();
  }
  function retryDelay(response) {
    const value = response?.headers.get('Retry-After');
    const seconds = Number(value);
    const suggested = value && Number.isFinite(seconds) ? seconds * 1000 : value ? Date.parse(value) - Date.now() : 0;
    return Math.max(3000, Math.min(120000, Number.isFinite(suggested) ? suggested : 0), Math.min(60000, 3000 * 2 ** Math.min(failures, 5)));
  }
  async function backgroundFetch(url, options) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(url, {...options, signal: controller.signal});
      if (response.status === 429 || response.status >= 500) {
        failures += 1; retryAt = Date.now() + retryDelay(response);
      } else if (response.ok && !response.redirected && response.headers.get('Content-Type')?.includes('application/json')) {
        failures = 0;
      } else {
        retryAt = Date.now() + 60000;
      }
      return response;
    } catch (error) {
      failures += 1; retryAt = Date.now() + retryDelay(); throw error;
    } finally { clearTimeout(timeout); }
  }
  async function backgroundJSON(response) {
    try { return await response.json(); }
    catch (error) { failures += 1; retryAt = Date.now() + retryDelay(); throw error; }
  }
  const backgroundPost = (url, body) => backgroundFetch(url, {method: 'POST', credentials: 'same-origin', headers: {'Accept': 'application/json', 'X-CSRF-Token': csrf}, body});
  async function cycle() {
    if (cycling || stopped || !visible()) return;
    cycling = true;
    try {
      if (Date.now() < retryAt) return;
      if (pendingRead && Date.now() >= readDue) {
        pendingRead = false;
        await markRead();
      }
      if (!visible() || Date.now() < retryAt) return;
      if (Date.now() >= nextPoll) {
        nextPoll = Date.now() + activeInterval();
        await poll();
        nextPoll = Date.now() + activeInterval();
      }
      if (!visible() || Date.now() < retryAt) return;
      if (Date.now() - lastPresence >= 60000) await heartbeat();
      if (!visible() || Date.now() < retryAt) return;
      if (Date.now() >= nextOverview) {
        nextOverview = Date.now() + 60000;
        await overview();
      }
    } finally {
      cycling = false;
      if (visible()) schedule(Math.max(250, retryAt > Date.now() ? retryAt - Date.now() : Math.min(nextPoll - Date.now(), pendingRead ? readDue - Date.now() : 1000, 1000)));
    }
  }
  const say = text => { if (status) status.textContent = text; };
  const visible = () => document.visibilityState === 'visible';
  const nearBottom = () => !log || log.scrollHeight - log.scrollTop - log.clientHeight < 90;
  const lastKey = () => log?.querySelector('[data-message-key]:last-of-type')?.dataset.messageKey || '';
  const post = (url, body) => fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'Accept': 'application/json', 'X-CSRF-Token': csrf}, body});
  function updateBadge(count) {
    if (!Number.isInteger(count) || count < 0) return;
    document.querySelectorAll('[data-message-badge]').forEach(node => {
      node.textContent = count >= 100 ? '99+' : String(count);
      node.hidden = !count;
    });
  }
  async function markRead() {
    const through = lastKey();
    if (reading || !visible() || !nearBottom() || !through || through === lastRead || !app.dataset.readUrl) return;
    reading = true;
    const body = new URLSearchParams({through});
    try {
      const response = await backgroundPost(app.dataset.readUrl, body);
      if (response.ok && !response.redirected) {
        const data = await backgroundJSON(response);
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
    finally { reading = false; if (lastKey() !== lastRead) queueRead(); }
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
      url.searchParams.set('badge', '0');
      const response = await backgroundFetch(url, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}});
      if (!response.ok || response.redirected || !response.headers.get('Content-Type')?.includes('application/json')) {
        say(response.status === 429 ? 'Updates paused briefly. Please wait.' : 'Updates paused. Refresh to check your session and conversation permissions.');
        return;
      }
      const data = await backgroundJSON(response);
      if (data.state !== app.dataset.state) { location.reload(); return; }
      const follow = nearBottom();
      data.messages.forEach(appendMessage);
      if (data.messages.length) activityAt = Date.now();
      (data.removed || []).forEach(key => {
        if (!/^[A-Za-z0-9]{16}$/.test(key)) return;
        const text = log.querySelector(`[data-message-key="${key}"] .dm-message-body`);
        if (text) text.textContent = '[Message removed by staff]';
      });
      if (compose) compose.querySelector('fieldset').disabled = !data.can_send;
      if (follow) log.scrollTop = log.scrollHeight;
      say(data.more ? 'More messages are available. Refresh for the latest conversation.' : data.messages.length && !follow ? 'New messages below.' : '');
      updateBadge(data.unread);
      queueRead();
    } catch (_) { say('Connection interrupted. Your conversation is saved; updates will retry.'); }
    finally { polling = false; }
  }
  async function heartbeat() {
    if (!visible() || app.dataset.presence === 'invisible' || Date.now() - lastPresence < 55000) return;
    lastPresence = Date.now();
    try { await backgroundPost(app.dataset.presenceUrl, new URLSearchParams()); } catch (_) { /* Presence expires automatically. */ }
  }
  async function overview() {
    if (!visible() || overviewPolling || app.dataset.sidebar === 'no') return;
    overviewPolling = true;
    try {
      const response = await backgroundFetch(app.dataset.overviewUrl, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}});
      if (!response.ok || response.redirected || !response.headers.get('Content-Type')?.includes('application/json')) return;
      const data = await backgroundJSON(response); updateBadge(data.unread);
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
      refreshSoon();
    } catch (_) { say('Delivery is unconfirmed. Your text is still here; retrying will not send a duplicate.'); }
    finally { sending = false; button.disabled = false; }
  });
  if (log) {
    log.scrollTop = log.scrollHeight;
    log.addEventListener('scroll', () => { queueRead(); }, {passive: true});
    queueRead();
  }
  document.addEventListener('visibilitychange', () => {
    clearTimeout(timer);
    if (visible()) { activityAt = Date.now(); nextPoll = 0; queueRead(); schedule(); }
  });
  function noteActivity() {
    activityAt = Date.now();
    if (nextPoll > activityAt + 3000) { nextPoll = activityAt + 3000; schedule(); }
  }
  document.addEventListener('pointerdown', noteActivity, {passive: true});
  document.addEventListener('keydown', noteActivity, {passive: true});
  window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); });
  window.addEventListener('pageshow', () => { stopped = false; if (visible()) refreshSoon(); });
  schedule();
})();
