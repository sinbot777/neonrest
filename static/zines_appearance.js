/* Screen atmosphere is deliberately independent of document composition and print. */
(() => {
  'use strict';
  const darkTone = rgb => rgb.map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0) < .179;
  const shell = document.querySelector('[data-zine-atmosphere]');
  if (!shell) return;
  const chooser = shell.querySelector('[data-reader-backdrop]');
  const key = shell.dataset.backdropPreference;
  if (chooser) {
    const original = {pattern: shell.dataset.zinePattern, tone: shell.dataset.zineTone};
    const variables = ['--zine-ground', '--zine-pattern-ink', '--zine-pattern-step', '--zine-pattern-opacity'];
    const savedStyle = variables.map(name => shell.style.getPropertyValue(name));
    function applyReadingBackdrop(value) {
      const option = Array.from(chooser.options).find(o => o.value === value);
      if (!option) value = 'publication';
      chooser.value = value;
      shell.classList.toggle('zine-plain-background', value === 'plain');
      shell.dataset.zinePattern = original.pattern;
      shell.dataset.zineTone = original.tone;
      variables.forEach((name, i) => shell.style.setProperty(name, savedStyle[i]));
      if (option && option.dataset.readerPreset) {
        const preset = JSON.parse(option.dataset.readerPreset);
        shell.dataset.zinePattern = preset.pattern;
        const rgb = preset.color.slice(1).match(/../g).map(n => parseInt(n, 16));
        shell.dataset.zineTone = darkTone(rgb) ? 'dark' : 'light';
        [preset.color, preset.ink, (16*preset.scale/100)+'px', String(preset.intensity/100)]
          .forEach((v, i) => shell.style.setProperty(variables[i], v));
      }
    }
    let preference = 'publication';
    try { preference = localStorage.getItem(key) || preference; } catch (_) {}
    applyReadingBackdrop(preference);
    chooser.addEventListener('change', () => {
      applyReadingBackdrop(chooser.value);
      try { localStorage.setItem(key, chooser.value); } catch (_) {}
    });
  }
  shell.querySelectorAll('[data-backdrop-form]').forEach(form => {
    const preview = form.querySelector('[data-backdrop-preview]');
    const options = form.querySelector('[data-backdrop-options]');
    const source = form.elements.namedItem('backdrop_mode');
    function update() {
      const inherited = source && source.value === 'inherit';
      options.disabled = !!inherited;
      form.querySelector('[data-backdrop-status]').textContent = inherited ? 'Following the publication backdrop. Save to remove this issue’s override.' : 'Unsaved preview. Save the backdrop to apply it.';
      const publication = JSON.parse(form.dataset.backdropInherited);
      const get = name => inherited ? publication[name] : form.elements.namedItem('backdrop_' + name).value;
      preview.dataset.zinePattern = get('pattern');
      const rgb = get('color').slice(1).match(/../g).map(n => parseInt(n, 16));
      preview.style.color = darkTone(rgb) ? '#ffffff' : '#000000';
      preview.style.setProperty('--zine-ground', get('color'));
      preview.style.setProperty('--zine-pattern-ink', get('ink'));
      preview.style.setProperty('--zine-pattern-step', (16 * Number(get('scale')) / 100) + 'px');
      preview.style.setProperty('--zine-pattern-opacity', String(Number(get('intensity')) / 100));
      ['scale', 'intensity'].forEach(n => form.querySelector('[data-backdrop-' + n + ']').textContent = get(n) + '%');
    }
    const cards = Array.from(form.querySelectorAll('[data-backdrop-preset]'));
    const keys = ['pattern','color','ink','scale','intensity'];
    function markPreset() {
      cards.forEach(card => {
        const preset = JSON.parse(card.dataset.backdropPreset);
        card.setAttribute('aria-pressed', String(keys.every(k => String(preset[k]) === form.elements.namedItem('backdrop_' + k).value)));
      });
    }
    cards.forEach(card => card.addEventListener('click', () => {
      const preset = JSON.parse(card.dataset.backdropPreset);
      keys.forEach(k => { form.elements.namedItem('backdrop_' + k).value = String(preset[k]); });
      update();
      markPreset();
      form.querySelector('[data-backdrop-status]').textContent = preset.name + ' previewed. Save the backdrop to apply it.';
    }));
    const grid = form.querySelector('[data-backdrop-preset-grid]');
    if (grid) grid.hidden = false;
    form.addEventListener('input', markPreset);
    form.addEventListener('change', markPreset);
    markPreset();
    form.addEventListener('input', update);
    form.addEventListener('change', update);
    if (source) options.disabled = source.value === 'inherit';
  });
})();
