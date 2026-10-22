(() => {
  'use strict';
  const main = document.getElementById('main-content');
  if (main && !main.querySelector('main,[role="main"]')) main.setAttribute('role', 'main');
  const menus = '.post-dropdown,.comment-dropdown';
  const controls = '.post-actions,.comment-actions';
  function close(menu, restore) {
    menu.style.display = 'none';
    const trigger = menu.previousElementSibling;
    trigger?.setAttribute('aria-expanded', 'false');
    if (restore) trigger?.focus();
  }
  document.addEventListener('keydown', event => {
    const group = event.target.closest(controls);
    if (event.key === 'Escape' && group) {
      const menu = group.querySelector(menus);
      if (menu && menu.style.display !== 'none') {event.preventDefault(); close(menu, true);}
    }
    if (event.key === 'ArrowDown' && group && event.target.matches('.icon-button')) {
      event.preventDefault();
      if (event.target.getAttribute('aria-expanded') !== 'true') event.target.click();
      group.querySelector('a[href],.link-button')?.focus();
    }
  });
  document.addEventListener('click', event => {
    const group = event.target.closest(controls);
    document.querySelectorAll(menus).forEach(menu => {
      if (!group || !group.contains(menu)) close(menu, false);
    });
  });
  document.addEventListener('focusin', event => {
    document.querySelectorAll(menus).forEach(menu => {
      if (!menu.parentElement.contains(event.target)) close(menu, false);
    });
  });
  // Pause animation automatically for reduced motion, background tabs or a saved choice.
  const footer = document.getElementById('footer-tagline');
  const toggle = document.getElementById('footer-motion-toggle');
  if (!footer || !toggle) return;
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let paused = false;
  try {paused = localStorage.getItem('neonrest-pause-footer') === '1';} catch (_) {}
  const taglines = ['✨ Stay human, stay weird ✨', '🎵 Mixtapes not metrics', '🛋️ Come vibe with us', '📼 Rewind your feed', '💬 Honest posts, real people', "💀 I want to get off Mr. Bones's Wild Ride!", '🗺️ Splicing Reticulations 🦙.', 'This machine kills fascists'];
  let timer, index = 0;
  function update() {
    clearInterval(timer);
    const stopped = paused || motion.matches;
    toggle.textContent = stopped ? 'Rotate footer messages' : 'Pause footer messages';
    toggle.disabled = motion.matches;
    toggle.title = motion.matches ? 'Rotation is off because your device prefers reduced motion.' : '';
    if (!stopped && !document.hidden) timer = setInterval(() => {index = (index + 1) % taglines.length; footer.textContent = taglines[index];}, 4000);
  }
  toggle.hidden = false;
  toggle.addEventListener('click', () => {paused = !paused; try {localStorage.setItem('neonrest-pause-footer', paused ? '1' : '0');} catch (_) {} update();});
  motion.addEventListener('change', update);
  document.addEventListener('visibilitychange', update);
  update();
})();
