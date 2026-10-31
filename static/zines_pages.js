/* Saved-page overview. Every reorder is checked again by the server. */
(()=>{'use strict';
for(const form of document.querySelectorAll('[data-page-organizer]')){
 const cards=form.querySelector('[data-page-cards]'),field=form.querySelector('[data-page-order]');let dragging=null;
 const interiors=()=>[...cards.children].filter(el=>el.dataset.kind==='page');
 function sync(changed=false){field.value=JSON.stringify(interiors().map(el=>el.dataset.pageCard));[...cards.children].forEach((el,i)=>{el.querySelector('[data-page-number]').textContent=i+1;for(const btn of el.querySelectorAll('[data-page-move]')){btn.disabled=btn.dataset.pageMove==='up'?el===interiors()[0]:el===interiors().at(-1);btn.setAttribute('aria-label',`Move page ${i+1} ${btn.dataset.pageMove==='up'?'earlier':'later'}`);}});if(changed)form.querySelector('[data-page-order-status]').textContent='Order changed — save to keep it.';}
 const editable=!!form.querySelector('button[value="reorder"]');
 for(const card of interiors()){
  card.draggable=editable;
  card.addEventListener('dragstart',e=>{if(!editable)return;dragging=card;e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain','zine-page');});
  card.addEventListener('dragover',e=>{if(dragging&&dragging!==card)e.preventDefault();});
  card.addEventListener('drop',e=>{if(!dragging||dragging===card)return;e.preventDefault();const before=[...cards.children].indexOf(dragging)<[...cards.children].indexOf(card);cards.insertBefore(dragging,before?card.nextSibling:card);dragging=null;sync(true);});card.addEventListener('dragend',()=>{dragging=null;});
 }
 form.addEventListener('click',e=>{const btn=e.target.closest('[data-page-move]');if(!btn)return;const card=btn.closest('[data-page-card]'),items=interiors(),i=items.indexOf(card),target=items[i+(btn.dataset.pageMove==='up'?-1:1)];if(target){cards.insertBefore(card,btn.dataset.pageMove==='up'?target:target.nextSibling);sync(true);}});
 for(const btn of form.closest('section').querySelectorAll('[data-page-view]'))btn.addEventListener('click',()=>{cards.classList.toggle('zine-spreads',btn.dataset.pageView==='spreads');for(const item of form.closest('section').querySelectorAll('[data-page-view]'))item.setAttribute('aria-pressed',String(item===btn));});
 form.addEventListener('submit',()=>sync());sync();
}
})();
