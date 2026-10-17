(() => {
  'use strict';
  const dialog = document.getElementById('neon-share-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const link = document.getElementById('neon-share-link');
  const status = document.getElementById('neon-share-status');
  const device = document.getElementById('neon-share-device');
  let opener;
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-neon-share]');
    if (!button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    const url = new URL(button.dataset.shareUrl, location.origin);
    const compose = new URL(button.dataset.shareCompose, location.origin);
    if (url.origin !== location.origin || compose.origin !== location.origin) return;
    event.preventDefault(); opener = button;
    link.value = url.href;
    document.getElementById('neon-share-compose').href = compose.href;
    document.getElementById('neon-share-notice').textContent = button.dataset.shareNotice;
    document.getElementById('neon-share-heading').textContent = button.textContent.trim();
    status.textContent = '';
    device.hidden = typeof navigator.share !== 'function';
    dialog.showModal();
  });
  document.getElementById('neon-share-copy').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(link.value);
      status.textContent = 'Link copied.';
    } catch (_) {
      link.focus(); link.select();
      status.textContent = 'Copy this selected link using your usual Copy command.';
    }
  });
  device.addEventListener('click', async () => {
    try {
      // Do not put private post text, titles, images or identities into a preview.
      await navigator.share({title:'Neonrest', url:link.value});
      status.textContent = 'Share completed.';
    } catch (error) {
      if (error.name !== 'AbortError') status.textContent = 'Device sharing is unavailable. You can copy the link instead.';
    }
  });
  dialog.addEventListener('close', () => opener?.focus());
})();
