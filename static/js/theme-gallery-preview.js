(() => {
  const frame = document.getElementById('gallery-theme-preview');
  const data = document.getElementById('gallery-theme-data');
  if (!frame || !data || !window.NeonrestThemePreview) return;
  const preview = JSON.parse(data.textContent);
  frame.srcdoc = window.NeonrestThemePreview(preview.slug, preview.mode, preview.style);
})();
