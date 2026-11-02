/* Illustrative preset previews only. Form values and saved layouts are untouched. */
(() => {
'use strict';
for(const guide of document.querySelectorAll('[data-style-guide]')){
 const form=guide.closest('form'),q=s=>guide.querySelector(s),kind=guide.dataset.pageKind||'page';if(!form)continue;
 const value=(name,fallback='')=>form.elements.namedItem(name)?.value||fallback;
 const put=(node,text)=>{if(node&&node.textContent!==text)node.textContent=text;};
 const paragraphs=text=>text.split(/\n\s*\n/).filter(Boolean);
 function prose(node,text){if(!node)return;node.replaceChildren();for(const part of paragraphs(text)){const p=document.createElement('p');p.textContent=part;node.append(p);}}
 function update(){
  const design=value('design','classic'),accent=['red','cobalt','purple','forest'].includes(value('accent'))?value('accent'):'red';
  const heading=value('heading','Make some pages'),text=value('text','Your story goes here. Write an article, share an idea, or start a conversation.\n\nText stays readable and editable.'),quote=value('pullquote','A voice worth sharing.');
  for(const pane of guide.querySelectorAll('[data-style-sample]'))pane.hidden=pane.dataset.styleSample!==design;
  const classic=q('[data-style-sample="classic"]');put(classic.querySelector('h2'),heading);put(classic.querySelector('.zine-prose'),text);
  const punk=q('[data-style-sample="punk"] .zine-art-punk');
  for(const c of [...punk.classList])if(c.startsWith('zine-accent-'))punk.classList.remove(c);punk.classList.add('zine-accent-'+accent);
  put(punk.querySelector('.punk-title'),kind==='cover'?heading.replaceAll(' & ','\n&\n'):heading);put(punk.querySelector('.punk-section'),value('section','SECTION LABEL'));
  put(punk.querySelector('.punk-highlight'),value('highlight','01'));put(punk.querySelector('.punk-highlight-label'),value('highlight_label','YOUR HIGHLIGHT LABEL'));
  put(punk.querySelector('.punk-pullquote,.punk-cover-banner'),quote);prose(punk.querySelector('.punk-prose'),text);
  if(kind==='cover'){
   const blocks=paragraphs(text);put(punk.querySelector('.punk-tagline'),blocks[0]||'');const copy=punk.querySelector('.punk-cover-copy');copy.replaceChildren();
   const rest=blocks.slice(1).filter(block=>block.replace(/\s+/g,' ').trim()!==quote.replace(/\s+/g,' ').trim());
   rest.forEach((block,index)=>{const p=document.createElement('p');if(index===rest.length-1){p.className='punk-cover-footer';const lines=block.split('\n');p.textContent=lines.shift();copy.append(p);if(lines.length){const small=document.createElement('small');small.textContent=lines.join('\n');copy.append(small);}}else{p.textContent=block;copy.append(p);}});
  }
  if(design==='composition'){
   const canvas=form.querySelector('.zc-edit-canvas');if(canvas){const preview=canvas.cloneNode(true);preview.classList.remove('zc-edit-canvas','zc-guides');preview.removeAttribute('tabindex');preview.setAttribute('aria-label','Current composition example');for(const el of preview.querySelectorAll('.zc-selected'))el.classList.remove('zc-selected');for(const el of preview.querySelectorAll('.zc-resize'))el.remove();q('[data-style-composition]').replaceChildren(preview);}
  }
  const help={classic:'Classic uses your heading, body text and artwork in a traditional reading layout. The Punk graphic fields below do not affect Classic.',punk:'Punk adds bold display type, accent panels and poster-style covers. The example shows how the graphic fields are used.',composition:'Visual composition uses the canvas above. These preset graphic fields do not change its individual text, images or shapes.'};
  put(q('[data-style-help]'),help[design]||help.classic);
  const effect=design==='punk'?(kind==='cover'?'Front cover: section strip, large heading, banner and artwork or waveform. Highlight fields are not used.':kind==='back'?'Back cover: section strip, poster heading, accent rule and body text. Pull quote and highlight fields are not used.':'Interior page: section strip, accent highlight and label, article text and pull-quote panel.'):design==='composition'?'Edit the live canvas to change composition elements. Switching styles does not erase the saved composition.':'Graphic labels, banners, highlights and accent colors are Punk-only settings.';
  put(q('[data-style-effect]'),effect);
  for(const name of ['accent','section','pullquote','highlight','highlight_label']){const field=form.elements.namedItem(name);field?.closest('label')?.classList.toggle('zine-style-unused',design!=='punk'||kind==='back'&&['pullquote','highlight','highlight_label'].includes(name)||kind==='cover'&&['highlight','highlight_label'].includes(name));}
 }
 let queued=false;function schedule(){if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;update();});}
 form.addEventListener('input',schedule);form.addEventListener('change',schedule);update();
 const zoom=document.createElement('button');zoom.type='button';zoom.dataset.styleZoom='';zoom.textContent='Enlarge example';zoom.setAttribute('aria-expanded','false');q('.zine-style-example-note').after(zoom);
 zoom.addEventListener('click',()=>{const expanded=guide.classList.toggle('zine-style-expanded');zoom.setAttribute('aria-expanded',String(expanded));zoom.textContent=expanded?'Compact example':'Enlarge example';});
}
})();
