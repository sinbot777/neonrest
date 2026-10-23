/* Scriptless, opaque-origin preview with all remote requests blocked by CSP. */
(function (root) {
  'use strict';
  function previewDocument(slug, mode, style) {
    const className='vibe-'+String(slug).replace(/[^a-z0-9_-]/gi,'')+'--'+(mode==='day'?'day':'night');
    const cssText=value=>String(value || '').replace(/</g,'\\3c ');
    const declarations=[];
    for (const [key,property] of [['bg_color','background-color'],['text_color','color'],
        ['background_layers','background-image'],['blend_mode','background-blend-mode'],['font_stack','font-family']]) {
      if (style[key]) declarations.push(property+':'+cssText(style[key]));
    }
    if (style.glow_color) declarations.push('--glow-color:'+cssText(style.glow_color));
    return '<!doctype html><html><head><meta charset="utf-8">'+
      '<meta http-equiv="Content-Security-Policy" content="default-src &apos;none&apos;; style-src &apos;unsafe-inline&apos;; img-src data:; base-uri &apos;none&apos;; form-action &apos;none&apos;">'+
      '<meta name="viewport" content="width=device-width,initial-scale=1">'+
      '<style>body{margin:0;padding:20px;font:16px/1.5 system-ui;background:'+(mode==='day'?'#e9e8ef;color:#272638':'#151622;color:#f5f1fc')+'}'+
      '.post-preview,.vibe-header{padding:16px;margin:0 0 16px;background:var(--vibe-panel,transparent);color:var(--vibe-ink,inherit);border:1px solid var(--vibe-border,currentColor);border-radius:12px}'+
      'h1,h2{color:var(--vibe-accent,inherit);text-shadow:0 0 4px var(--vibe-glow,transparent)}'+
      '.vibe-pill{padding:4px 8px;border-radius:16px;background:var(--vibe-pill,transparent);color:var(--vibe-pill-ink,inherit)}'+
      'body.'+className+'{'+declarations.join(';')+'}\n'+cssText(style.custom_css)+'</style></head>'+
      '<body class="'+className+'"><header class="vibe-header"><h1>Vibe preview</h1><p>A place for your people and ideas.</p></header>'+
      '<article class="post-preview"><h2>Sample post</h2><p>Ordinary text, <strong>emphasis</strong>, and a longer line to check spacing and readability.</p><span class="vibe-pill">Sample Vibe</span>'+
      '<p>👍 3 · 💖 2</p><section class="comments-section"><p class="comment">@sample → @friend: A sample reply.</p></section></article></body></html>';
  }
  if (typeof module!=='undefined' && module.exports) module.exports={previewDocument};
  if (!root.document) return;
  const form=root.document.getElementById('theme-editor-form');
  const frame=root.document.getElementById('theme-live-preview');
  if (!form || !frame) return;
  function update() {
    const style={};
    for (const key of ['custom_css','bg_color','text_color','glow_color','background_layers','blend_mode','font_stack'])
      style[key]=form.elements['null_'+key]?.checked?null:form.elements[key].value;
    frame.srcdoc=previewDocument(form.dataset.themeSlug,form.dataset.themeMode,style);
  }
  let timer;
  form.addEventListener('input',()=>{root.clearTimeout(timer);timer=root.setTimeout(update,120);});
  form.addEventListener('change',update);
  update();
})(typeof window!=='undefined'?window:globalThis);
