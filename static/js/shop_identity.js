/* Keep the shop identity and optional Page selection consistent. */
(() => {
  'use strict';
  for (const form of document.querySelectorAll('[data-shop-identity-form]')) {
    const kind = form.querySelector('[name=identity_kind]');
    const page = form.querySelector('[name=linked_page_id]');
    const help = form.querySelector('[data-shop-identity-help]');
    const sync = () => {
      page.required = kind.value === 'page';
      if (help) help.textContent = kind.value === 'page'
        ? 'Select a Page you own, then save the identity link.'
        : 'Choosing a Page switches the identity type automatically.';
    };
    page.addEventListener('change', () => {
      if (page.value) kind.value = 'page';
      sync();
    });
    kind.addEventListener('change', () => {
      if (kind.value !== 'page') page.value = '';
      sync();
    });
    sync();
  }
})();
