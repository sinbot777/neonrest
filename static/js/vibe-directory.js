'use strict';
document.querySelectorAll('.directory-brand img').forEach(image => {
  function fallback() {
    image.hidden = true;
    const label = image.parentElement.querySelector('.directory-fallback');
    if (label) label.hidden = false;
  }
  image.addEventListener('error', fallback);
  if (image.complete && image.naturalWidth === 0) fallback();
});
