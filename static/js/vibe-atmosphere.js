/* Optional CSS motion, always subordinate to device and visitor preferences. */
(() => {
  const device = matchMedia('(prefers-reduced-motion: reduce)');
  const pref = window.NEON_ATMOSPHERE_PREFS || {logo_motion:'system'};
  const gifs = window.NEON_MEDIA_PREFS || {gif_mode:'system'};
  document.querySelectorAll('[data-vibe-logo-motion]').forEach(group => {
    const image = group.querySelector('.vibe-logo');
    const button = group.querySelector('.vibe-logo-pause');
    const status = group.querySelector('.vibe-logo-status');
    if (!image || !button) return;
    let paused = false;
    function update() {
      const blocked = device.matches || pref.logo_motion==='off' || gifs.gif_mode==='off';
      image.classList.toggle('vibe-logo-moving', !blocked && !paused && !document.hidden);
      button.disabled = blocked;
      button.setAttribute('aria-pressed', String(paused || blocked));
      button.textContent = paused ? 'Resume logo animation' : 'Pause logo animation';
      status.textContent = device.matches ? 'Reduced motion enabled.' : blocked ? 'Logo animation is off in your media settings.' : '';
    }
    button.addEventListener('click', () => { paused = !paused; update(); });
    device.addEventListener('change', update);
    document.addEventListener('visibilitychange', update);
    update();
  });
})();
