/* Task-based workspace; move real controls without duplicating form values. */
(()=>{'use strict';
const shell=document.querySelector('.zine-shell'),sizeDialog=document.querySelector('[data-issue-size-dialog]');
for(const root of document.querySelectorAll('[data-zc-editor]')){
 const controls=root.querySelector('[data-zc-controls]');if(!controls)continue;
 const chrome=document.createElement('div');chrome.className='zc-command-bar';
 const tabs=document.createElement('div');tabs.className='zc-task-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Editing tasks');
 const panels=document.createElement('div');panels.className='zc-task-panels';
 const contents={};const uid='zc-task-'+[...document.querySelectorAll('[data-zc-editor]')].indexOf(root);
 for(const name of ['Insert','Text','Layout','Arrange','Review']){
  const button=document.createElement('button'),panel=document.createElement('div');button.type='button';button.textContent=name;button.setAttribute('role','tab');button.id=uid+'-'+name;button.setAttribute('aria-controls',button.id+'-panel');panel.id=button.id+'-panel';panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',button.id);contents[name]=panel;
  button.onclick=()=>{for(const b of tabs.children)b.setAttribute('aria-selected',String(b===button));for(const p of panels.children)p.hidden=p!==panel;};tabs.append(button);panels.append(panel);button.setAttribute('aria-selected',String(name==='Text'));panel.hidden=name!=='Text';
 }
 const mode=root.querySelector('.zc-mode');chrome.append(tabs,mode);root.querySelector('[data-zc-mode-help]').after(chrome,panels);
 const common=controls.querySelector('.zc-toolbar');common.classList.add('zc-common-tools');chrome.before(common);
 const save=root.closest('form').querySelector('.zine-save-bar button');if(save)common.append(save);
 const adds=controls.querySelector('[aria-label="Add elements"]');contents.Insert.append(adds);
 const note=document.createElement('p');note.textContent='Select text, artwork or a shape on the page. Its controls appear in the inspector.';contents.Text.append(note);
 const inspector=root.querySelector('.zc-inspector');
 for(const section of [...inspector.children]){
  const label=section.querySelector('summary')?.textContent||'';
  if(/Layout starters|Reusable layouts/.test(label))contents.Layout.append(section);
  else if(/Selection & grouping|Arrange selected|Layers/.test(label))contents.Arrange.append(section);
  else if(/page checks/i.test(label))contents.Review.append(section);
  else if(/Portable layout/.test(label))contents.Layout.append(section);
 }
 const legacy=root.closest('form').querySelector('.zc-legacy'),style=legacy?.querySelector('[data-style-guide]');
 if(style){const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Style & graphic elements';details.append(summary,style);contents.Layout.append(details);}
 if(sizeDialog){const button=document.createElement('button');button.type='button';button.textContent='Issue page size…';const form=root.closest('form'),fingerprint=()=>JSON.stringify([...new FormData(form)].filter(([key])=>!['composition'].includes(key)));const initial=fingerprint(),initialComposition=root.querySelector('[data-zc-json]').value;button.onclick=()=>{if(fingerprint()!==initial||root.querySelector('[data-zc-json]').value!==initialComposition){root.querySelector('[data-zc-notice]').textContent='Save page changes before changing the issue size.';return;}sizeDialog.showModal();};contents.Layout.prepend(button);}
 const color=common.querySelector('[data-page-color]')?.closest('label');if(color)contents.Layout.append(color);
 // Keep source fields available, but out of the composition area until requested.
 if(legacy)legacy.open=false;
 if(shell?.dataset.issueWidth){const w=+shell.dataset.issueWidth,h=+shell.dataset.issueHeight,k=+shell.dataset.contentScale;const wrap=root.querySelector('.zc-stage-wrap'),canvas=root.querySelector('.zc-edit-canvas');wrap.classList.add('zc-sized-stage');wrap.style.aspectRatio=w+'/'+h;canvas.style.width=396*k/w*100+'%';canvas.style.position='absolute';canvas.style.left=(1-396*k/w)*50+'%';canvas.style.top=(1-612*k/h)*50+'%';}
}
if(sizeDialog){const f=sizeDialog.querySelector('form'),get=n=>f.elements.namedItem(n),presets={business:[252,144],postcard:[432,288],a6:[297.6378,419.5276],a5:[419.5276,595.2756],'half-letter':[396,612],letter:[612,792],a4:[595.2756,841.8898]};let previousUnit='in';
 const preview=()=>{const custom=get('page_preset').value==='custom';for(const n of ['page_width','page_height','page_units'])get(n).closest('label').hidden=!custom;let [w,h]=custom?[+get('page_width').value,+get('page_height').value].map(v=>v*(get('page_units').value==='mm'?72/25.4:72)):presets[get('page_preset').value];[w,h]=[Math.min(w,h),Math.max(w,h)];if(get('page_orientation').value==='landscape')[w,h]=[h,w];const scale=get('resize_content').value==='keep'?(+shell.dataset.contentScale||1):Math.min(w/396,h/612);const valid=Number.isFinite(w+h)&&Math.min(w,h)>=143.99&&Math.max(w,h)>=251.99&&Math.max(w,h)<=1296&&396*scale<=w+.01&&612*scale<=h+.01;f.querySelector('[data-size-save]').disabled=!valid;const out=f.querySelector('[data-size-description]');out.textContent=valid?(w/72).toFixed(2)+' × '+(h/72).toFixed(2)+' in · '+(w/72*25.4).toFixed(1)+' × '+(h/72*25.4).toFixed(1)+' mm':'Choose a valid size with enough room for the content.';const paper=f.querySelector('.zine-size-preview');paper.style.aspectRatio=valid?w+'/'+h:'1';paper.style.width=valid?Math.min(200,260*w/h)+'px':'160px';const content=f.querySelector('[data-size-content]');content.style.width=valid?396*scale/w*100+'%':'100%';content.style.height=valid?612*scale/h*100+'%':'100%';};
 f.addEventListener('input',preview);f.addEventListener('change',e=>{if(e.target===get('page_units')){const next=get('page_units').value,factor=next===previousUnit?1:next==='mm'?25.4:1/25.4;for(const n of ['page_width','page_height'])get(n).value=(+get(n).value*factor).toFixed(3);previousUnit=next;}preview();});const reset=()=>{f.reset();previousUnit='in';preview();};sizeDialog.addEventListener('cancel',reset);f.querySelector('[data-size-cancel]').onclick=()=>{reset();sizeDialog.close();};preview();}
})();
