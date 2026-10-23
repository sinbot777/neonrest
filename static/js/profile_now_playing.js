(() => {
  'use strict';
  const text = document.getElementById('now-playing-text');
  const label = document.getElementById('now-playing-label');
  const art = document.getElementById('album-art');
  if (!text?.dataset.nowPlayingUrl) return;
  const endpoint = new URL(text.dataset.nowPlayingUrl, location.origin);
  if (endpoint.origin !== location.origin) return;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  const safeURL = value => {
    if (typeof value !== 'string') return null;
    try {
      const url = new URL(value);
      return ['https:', 'http:'].includes(url.protocol) ? url.href : null;
    } catch (_) { return null; }
  };
  fetch(endpoint.href, {credentials: 'same-origin', headers: {Accept: 'application/json'}, signal: controller.signal})
    .then(response => {
      if (!response.ok || response.redirected) throw new Error('Music unavailable');
      return response.json();
    })
    .then(data => {
      if (!data || typeof data.track !== 'string' || !data.track.trim()) {
        text.textContent = 'No recent track available.';
        return;
      }
      if (label) label.textContent = data.is_now_playing === true ? 'Now playing' : 'Last played';
      const title = data.track.slice(0, 500);
      const link = safeURL(data.url);
      if (link) {
        const anchor = document.createElement('a');
        anchor.href = link; anchor.target = '_blank'; anchor.rel = 'noopener noreferrer';
        anchor.title = 'View on Last.fm'; anchor.textContent = title;
        text.replaceChildren(anchor);
      } else text.textContent = title;
      const source = safeURL(data.album_art);
      if (art && source) {
        const image = document.createElement('img');
        image.src = source; image.alt = 'Album art'; image.loading = 'lazy';
        image.style.maxWidth = '100%'; image.style.width = '160px'; image.style.height = 'auto';
        image.addEventListener('error', () => art.replaceChildren(), {once: true});
        art.replaceChildren(image);
      }
    })
    .catch(() => { text.textContent = 'Music temporarily unavailable.'; })
    .finally(() => clearTimeout(timer));
})();

