/* Optional semantic colors persist in a marked CSS block, preserving schema. */
(function(root) {
  'use strict';
  const keys=['panel','ink','accent','glow','border','pill','pill-ink'];
  const block=/\/\* neonrest-visual-start \*\/[\s\S]*?\/\* neonrest-visual-end \*\//g;
  function readVisualColors(css) {
    const managed=String(css).match(block)?.pop() || '';
    const result={};
    for(const key of keys) {
      const match=managed.match(new RegExp('--vibe-'+key+':\\s*(#[0-9a-f]{6})\\s*;','i'));
      if(match) result[key]=match[1].toLowerCase();
    }
    return result;
  }
  function setVisualColor(css,slug,mode,key,color) {
    if(!keys.includes(key) || (color!==null && !/^#[0-9a-f]{6}$/i.test(color))) throw new Error('Invalid visual color');
    const values=readVisualColors(css);
    if(color===null) delete values[key];else values[key]=color.toLowerCase();
    const base=String(css).replace(block,'').trimEnd();
    const rules=keys.filter(k=>values[k]).map(k=>'  --vibe-'+k+': '+values[k]+';').join('\n');
    if(!rules) return base;
    const safeSlug=String(slug).replace(/[^a-z0-9_-]/gi,'');
    return base+'\n\n/* neonrest-visual-start */\nbody.vibe-'+safeSlug+'--'+(mode==='day'?'day':'night')+' {\n'+rules+'\n}\n/* neonrest-visual-end */';
  }
  if(typeof module!=='undefined' && module.exports) module.exports={readVisualColors,setVisualColor};
  if(!root.document) return;
  const form=root.document.getElementById('theme-editor-form');
  if(!form) return;
  const css=form.elements.custom_css;
  const rows=Array.from(form.querySelectorAll('[data-visual-color]'));
  function sync() {
    const values=readVisualColors(css.value);
    for(const row of rows) {
      const key=row.dataset.visualColor, picker=row.querySelector('[type="color"]'), inherit=row.querySelector('[type="checkbox"]');
      inherit.checked=!values[key];
      if(values[key]) picker.value=values[key];
    }
  }
  for(const row of rows) {
    const picker=row.querySelector('[type="color"]'), inherit=row.querySelector('[type="checkbox"]');
    function update(event) {
      if(event.target===picker) inherit.checked=false;
      css.value=setVisualColor(css.value,form.dataset.themeSlug,form.dataset.themeMode,row.dataset.visualColor,inherit.checked?null:picker.value);
      css.dispatchEvent(new Event('input',{bubbles:true}));
    }
    picker.addEventListener('input',update);inherit.addEventListener('change',update);
  }
  css.addEventListener('input',sync);form.addEventListener('change',sync);sync();
})(typeof window!=='undefined'?window:globalThis);
