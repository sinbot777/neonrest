(() => {
  const dialog = document.createElement('dialog');
  dialog.className = 'image-viewer';
  dialog.setAttribute('aria-label', 'Image viewer');
  dialog.innerHTML = '<div class="image-viewer__toolbar"><span class="image-viewer__caption"></span><button type="button" class="image-viewer__zoom">View full size</button><button type="button" class="image-viewer__close" aria-label="Close image viewer">Close ×</button></div><div class="image-viewer__viewport"><img class="image-viewer__image" alt="" tabindex="0" role="button" aria-label="View full size"></div><p class="image-viewer__hint" aria-live="polite">Click the image again to view its full saved size.</p>';
  document.body.append(dialog);
  const image = dialog.querySelector('.image-viewer__image');
  const viewport = dialog.querySelector('.image-viewer__viewport');
  const zoom = dialog.querySelector('.image-viewer__zoom');
  const hint = dialog.querySelector('.image-viewer__hint');
  let opener;
  const toggleZoom = () => {
    if (!image.naturalWidth) return;
    const full = dialog.classList.toggle('image-viewer--full');
    image.style.width = full ? `${image.naturalWidth}px` : '';
    zoom.textContent = full ? 'Fit to screen' : 'View full size';
    image.setAttribute('aria-label', zoom.textContent);
    hint.textContent = full ? `Full saved size: ${image.naturalWidth} × ${image.naturalHeight} pixels. Scroll to explore; click again to fit.` : 'Click the image again to view its full saved size.';
    viewport.scrollTop = 0; viewport.scrollLeft = 0;
  };
  zoom.addEventListener('click', toggleZoom);
  image.addEventListener('click', toggleZoom);
  image.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); toggleZoom();}
  });
  dialog.querySelector('.image-viewer__close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  dialog.addEventListener('close', () => {image.removeAttribute('src'); opener?.focus();});
  document.addEventListener('click', event => {
    const link = event.target.closest('a.post-image-link');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); opener = link;
    const preview = link.querySelector('img');
    image.src = link.href; image.alt = preview.alt;
    dialog.querySelector('.image-viewer__caption').textContent = preview.alt;
    dialog.classList.remove('image-viewer--full'); image.style.width = '';
    image.setAttribute('aria-label','View full size'); zoom.textContent = 'View full size';
    hint.textContent = 'Click the image again to view its full saved size.';
    dialog.showModal(); viewport.scrollTop = 0; viewport.scrollLeft = 0;
  });
})();
