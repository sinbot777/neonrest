'use strict';
(() => {
  const root = document.querySelector('.user-guide');
  if (!root) return;
  const box = root.querySelector('.guide-search');
  const input = root.querySelector('#guide-search');
  const clear = root.querySelector('#guide-clear');
  const status = root.querySelector('#guide-search-status');
  const empty = root.querySelector('#guide-no-results');
  const sections = Array.from(root.querySelectorAll('.guide-section'));
  const links = Array.from(root.querySelectorAll('[data-guide-topic]'));
  function filter() {
    const terms = input.value.trim().toLocaleLowerCase().split(/\s+/u).filter(Boolean);
    let count = 0;
    for (const section of sections) {
      const text = section.textContent.toLocaleLowerCase();
      section.hidden = !terms.every(term => text.includes(term));
      if (!section.hidden) count++;
      for (const link of links) if (link.dataset.guideTopic === section.id) link.parentElement.hidden = section.hidden;
      for (const detail of section.querySelectorAll('details')) if (terms.length) detail.open = !section.hidden;
    }
    clear.hidden = !input.value;
    empty.hidden = count !== 0;
    status.textContent = terms.length ? count + ' of ' + sections.length + ' topics shown.' : '';
  }
  input.addEventListener('input', filter);
  clear.addEventListener('click', () => { input.value = ''; filter(); input.focus(); });
  input.addEventListener('keydown', event => { if (event.key === 'Escape') { input.value = ''; filter(); } });
  window.addEventListener('hashchange', () => { if (input.value) { input.value = ''; filter(); } });
  box.hidden = false;
})();
