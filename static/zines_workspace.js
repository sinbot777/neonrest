/* Presentation only: preserve the existing forms, controls and composition model. */
(() => {
'use strict';
const reader=document.querySelector('[data-zine-reader]');
if(reader){
 const key=reader.dataset.readerKey,select=reader.querySelector('[data-reading-select]');
 const url=new URL(location.href),valid=['single','spread','scroll'];
 try{
  const stored=localStorage.getItem(key);
  if(!url.searchParams.has('reading')&&valid.includes(stored)&&stored!==reader.dataset.reading){url.searchParams.set('reading',stored);location.replace(url.href);}
  else localStorage.setItem(key,reader.dataset.reading);
 }catch{}
 select.addEventListener('change',()=>{try{localStorage.setItem(key,select.value);}catch{}select.form.requestSubmit();});
 if(reader.dataset.reading==='scroll'&&url.searchParams.has('page')){
  const page=reader.querySelector('#zine-page-'+Number(url.searchParams.get('page')));
  if(page&&Number(url.searchParams.get('page'))>1)requestAnimationFrame(()=>page.scrollIntoView({block:'start'}));
 }
}
const outlineButton=document.querySelector('[data-outline-toggle]');
if(outlineButton){
 const layout=document.querySelector('.zine-workspace-layout'),outline=layout.querySelector('.zine-outline');
 outlineButton.addEventListener('click',()=>{const open=outlineButton.getAttribute('aria-expanded')!=='true';outlineButton.setAttribute('aria-expanded',String(open));outlineButton.textContent=open?'Hide pages':'Show pages';outline.hidden=!open;layout.classList.toggle('zine-outline-hidden',!open);});
}
for(const root of document.querySelectorAll('[data-zc-editor]')){
 const inspector=root.querySelector('.zc-inspector'),controls=root.querySelector('[data-zc-controls]');
 if(!inspector||!controls)continue;
 root.classList.add('zc-focused');
 // Move the actual nodes so existing editor listeners and form values stay intact.
 const starters=root.querySelector('[data-zc-layout-starters]');
 if(starters)inspector.append(starters);
 for(const section of [...controls.children]){
  if(section.matches('details[data-tool]'))inspector.append(section);
  else if(section.matches('.zc-toolbar[data-tool="composition"]')){
   const details=document.createElement('details'),summary=document.createElement('summary');
   details.dataset.tool='composition';summary.textContent='Selection & grouping';details.append(summary,section);inspector.append(details);
  }
 }
 const precision=inspector.querySelector('.zc-control-grid[data-tool="precision"]');
 if(precision){const details=document.createElement('details'),summary=document.createElement('summary');details.dataset.tool='precision';summary.textContent='Position, size & borders';precision.before(details);details.append(summary,precision);}
 const layer=inspector.querySelector('.zc-layer-panel');if(layer)inspector.append(layer);
 // The live canvas is the primary preview. Keep the saved version available on demand.
 const workspace=root.closest('.zine-edit-preview'),saved=workspace?.querySelector('.zine-saved-preview');
 if(saved){const details=document.createElement('details');details.className='zine-saved-comparison';const summary=document.createElement('summary');summary.textContent='Compare with saved page';saved.before(details);details.append(summary,saved);}
}
})();
