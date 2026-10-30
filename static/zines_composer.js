/* Structured composition editor. User content is always inserted with textContent. */
(() => {
'use strict';
const W=396,H=612,copy=v=>JSON.parse(JSON.stringify(v));
for (const root of document.querySelectorAll('[data-zc-editor]')) {
 const form=root.closest('form'),q=s=>root.querySelector(s),all=s=>[...root.querySelectorAll(s)];
 const json=q('[data-zc-json]'),canvas=q('.zc-edit-canvas'),design=form.elements.namedItem('design'),policy=window.ZineToolsets;
 let prefs=policy.preferences(null);
 try { prefs=policy.preferences(JSON.parse(localStorage.getItem(root.dataset.preferenceKey))); } catch {}
 function remember(){prefs.mode=mode;try {localStorage.setItem(root.dataset.preferenceKey,JSON.stringify(prefs));}catch{q('[data-zc-preference-status]').textContent='Preferences apply for this visit; browser storage is unavailable.';}}
 function toolVisibility(){const b=active();for(const el of all('[data-tool]'))el.hidden=!policy.visible(mode,prefs.tools,el.dataset.tool)||(el.dataset.for&&(!b||el.dataset.for!==b.type));}
 let page={version:1,background:'#ffffff',blocks:[]},selected=null,mode='standard',undo=[],redo=[],drag=null;
 try { if(json.value.trim())page=JSON.parse(json.value); } catch { q('[data-zc-notice]').textContent='Stored composition could not be read. Preserve the JSON before editing.'; }
 const assets=new Map(all('[data-prop="image"] option[data-src]').map(o=>[o.value,o.dataset.src]));
 const value=n=>form.elements.namedItem(n)?.value||'';
 const id=()=> 'e'+Math.random().toString(36).slice(2,12);
 function base(type,x=24,y=24,w=180,h=100){return {id:id(),type,x,y,w,h,locked:false,fill:type==='box'||type==='ellipse'?'#b52525':'transparent',color:'#171717',stroke:'#171717',stroke_width:0,...(type==='text'?{text:'Your text here',font:'sans',size:12,leading:1.35,align:'left'}:type==='image'?{image:'',alt:'',fit:'contain'}:{})};}
 function clamp(b){b.w=Math.min(W,Math.max(12,Number(b.w)||12));b.h=Math.min(H,Math.max(12,Number(b.h)||12));b.x=Math.min(W-b.w,Math.max(0,Number(b.x)||0));b.y=Math.min(H-b.h,Math.max(0,Number(b.y)||0));for(const k of ['x','y','w','h'])b[k]=Math.round(b[k]*100)/100;}
 function checkpoint(){undo.push(copy(page));if(undo.length>50)undo.shift();redo=[];}
 function dirty(){json.value=JSON.stringify(page);json.dispatchEvent(new Event('input',{bubbles:true}));}
 function active(){return page.blocks.find(b=>b.id===selected);}
 function enable(){design.value='composition';design.dispatchEvent(new Event('change',{bubbles:true}));form.querySelector('.zc-legacy').open=false;}
 function setMode(next){
  if(!['standard','custom','advanced'].includes(next))return;
  mode=next;
  for(const b of all('[data-mode]'))b.setAttribute('aria-pressed',String(b.dataset.mode===mode));
  q('[data-zc-custom-tools]').hidden=mode!=='custom';
  for(const box of all('[data-custom-tool]'))box.checked=prefs.tools.includes(box.dataset.customTool);
  q('[data-zc-mode-help]').textContent={standard:'Standard: layout starters, text and images, simple formatting, dragging, resizing and undo. Select an element to edit it.',custom:'Custom: every Standard tool plus the Advanced groups you select in Choose your Custom tools.',advanced:'Advanced: every implemented tool, including shapes, layers, typography, snapping, exact measurements and layout JSON.'}[mode];
  remember();render();
 }

 function style(el,b){Object.assign(el.style,{left:(b.x/W*100)+'%',top:(b.y/H*100)+'%',width:(b.w/W*100)+'%',height:(b.h/H*100)+'%',color:b.color,background:b.fill,border:`${b.stroke_width/W*100}cqw solid ${b.stroke}`,fontFamily:b.font==='mono'?'monospace':'DejaVu Sans, sans-serif',fontWeight:b.font==='bold'?'700':'400',fontSize:(b.size||12)/W*100+'cqw',lineHeight:String(b.leading||1.35),textAlign:b.align||'left'});}
 function render(sync=true){
  canvas.replaceChildren();canvas.style.background=page.background;canvas.classList.toggle('zc-guides',q('[data-guides]').checked);q('[data-page-color]').value=page.background;
  for(const b of page.blocks){const el=document.createElement('div');el.className='zc-element zc-type-'+b.type+(b.id===selected?' zc-selected':'');el.dataset.id=b.id;style(el,b);el.setAttribute('aria-label',b.type+' element');
   if(b.type==='text')el.textContent=b.text;
   else if(b.type==='image'){if(assets.has(b.image)){const img=document.createElement('img');img.src=assets.get(b.image);img.alt=b.alt;img.style.objectFit=b.fit;img.draggable=false;el.append(img);}else{el.textContent='Select artwork';el.classList.add('zc-placeholder');}}
   else if(b.type==='rule'){const line=document.createElement('span');line.style.borderTop=`${Math.max(1,b.stroke_width)/W*100}cqw solid ${b.color}`;el.append(line);}
   if(selected===b.id&&!b.locked){const handle=document.createElement('span');handle.className='zc-resize';handle.dataset.resize='1';handle.title='Drag to resize';el.append(handle);}
   canvas.append(el);
  }
  const layers=q('[data-zc-layers]');layers.replaceChildren();for(const b of [...page.blocks].reverse()){const btn=document.createElement('button');btn.type='button';btn.dataset.select=b.id;btn.textContent=(b.locked?'🔒 ':'')+b.type+' · '+(b.text||b.alt||b.id).slice(0,36);btn.setAttribute('aria-pressed',String(b.id===selected));layers.append(btn);}
  const b=active();q('[data-zc-inspector]').hidden=!b;q('[data-zc-empty]').hidden=!!b;
  if(b&&sync){for(const el of all('[data-prop]')){if(el.type==='checkbox')el.checked=!!b[el.dataset.prop];else el.value=b[el.dataset.prop]==='transparent'?'#ffffff':b[el.dataset.prop]??'';}for(const el of all('[data-for]'))el.hidden=el.dataset.for!==b.type;}
  toolVisibility();
  q('[data-zc-action="undo"]').disabled=!undo.length;q('[data-zc-action="redo"]').disabled=!redo.length;
  requestAnimationFrame(()=>{const over=[...canvas.querySelectorAll('.zc-type-text')].filter(e=>e.scrollHeight>e.clientHeight+1||e.scrollWidth>e.clientWidth+1);q('[data-zc-notice]').textContent=over.length?`${over.length} text box(es) may overflow. Enlarge them or reduce type size. PDF export also checks text fit.`:`${page.blocks.length} / 32 elements · ${design.value==='composition'?'Visual composition is active.':'Legacy preset is active; choose Use visual composition to activate this canvas.'}`;});
 }
 function commit(){enable();dirty();render();}
 function starter(name){
  const heading=value('heading')||'YOUR HEADLINE',text=value('text')||'Write your story here. Select this text box to replace the sample copy.',image=value('image');const blocks=[];
  const txt=(x,y,w,h,t,size=12,font='sans',color='#171717')=>({...base('text',x,y,w,h),text:t,size,font,color});
  const pic=(x,y,w,h)=>({...base('image',x,y,w,h),image,alt:value('caption')});
  if(name==='article'){blocks.push(txt(24,24,348,96,heading,28,'bold'),{...base('rule',24,126,348,12)},txt(24,150,348,330,text));if(image)blocks.push(pic(24,492,348,96));}
  if(name==='columns'){blocks.push(txt(24,24,348,90,heading,26,'bold'),txt(24,132,168,450,text.slice(0,Math.ceil(text.length/2))),txt(204,132,168,450,text.slice(Math.ceil(text.length/2))));}
  if(name==='photo'){blocks.push(txt(24,24,348,72,heading,24,'bold'),pic(24,108,348,300),txt(24,432,348,156,text,11));}
  if(name==='poster'){page.background='#171717';blocks.push({...base('box',0,180,396,100),fill:'#b52525'},txt(24,30,348,138,heading,36,'bold','#f7f3e8'),txt(24,198,348,72,value('pullquote')||'MAKE SOME NOISE.',24,'bold','#ffffff'),pic(24,306,348,150),txt(24,480,348,108,text,12,'bold','#f7f3e8'));}
  if(name==='collage'){blocks.push({...base('box',12,12,372,588),fill:'#f7f3e8'},txt(24,24,348,96,heading,28,'bold'),pic(24,138,216,228),pic(252,138,120,150),txt(252,312,120,270,text,10),txt(24,390,216,192,value('pullquote')||'Your pull quote',22,'bold'));}
  return blocks;
 }
 function validate(raw){
  if(!raw||Object.getPrototypeOf(raw)!==Object.prototype||raw.version!==1||!Array.isArray(raw.blocks)||raw.blocks.length>32||!/^#[\da-f]{6}$/i.test(raw.background))throw Error('Use version 1, a six-digit page color, and at most 32 elements.');
  if(Object.keys(raw).some(k=>!['version','background','blocks'].includes(k)))throw Error('Unsupported page property.');
  const ids=new Set();let chars=0;
  for(const b of raw.blocks){if(!b||Object.getPrototypeOf(b)!==Object.prototype||!['text','image','box','ellipse','rule'].includes(b.type)||!/^[-\w]{1,40}$/.test(b.id)||ids.has(b.id))throw Error('Invalid or duplicate element.');ids.add(b.id);
   if(Object.keys(b).some(k=>!['id','type','x','y','w','h','text','image','alt','font','size','leading','align','color','fill','stroke','stroke_width','fit','locked'].includes(k)))throw Error('Unsupported element property.');
   for(const k of ['x','y','w','h'])if(typeof b[k]!=='number'||!Number.isFinite(b[k]))throw Error('Element coordinates must be finite numbers.');
   if(b.x<0||b.y<0||b.w<12||b.h<12||b.x+b.w>W||b.y+b.h>H)throw Error('Keep elements inside the page.');
   if(typeof b.locked!=='boolean')throw Error('Element locked must be true or false.');
   for(const k of ['color','stroke','fill'])if(!(k==='fill'&&b[k]==='transparent')&&!/^#[\da-f]{6}$/i.test(b[k]))throw Error('Use six-digit colors.');
   if(typeof b.stroke_width!=='number'||!Number.isFinite(b.stroke_width)||b.stroke_width<0||b.stroke_width>8)throw Error('Border must be 0–8 pt.');
   if(b.type==='image'&&(!['contain','cover'].includes(b.fit)||typeof b.alt!=='string'||b.alt.length>300||typeof b.image!=='string'||(b.image&&!assets.has(b.image))))throw Error('Choose artwork from this publication.');
   if(b.type==='text'){if(typeof b.text!=='string'||!['sans','bold','mono'].includes(b.font)||!['left','center','right'].includes(b.align)||typeof b.size!=='number'||!Number.isFinite(b.size)||b.size<6||b.size>72||typeof b.leading!=='number'||!Number.isFinite(b.leading)||b.leading<1||b.leading>2)throw Error('Invalid text typography.');chars+=b.text.length;}
  }if(chars>6000)throw Error('Use at most 6000 text characters.');return copy(raw);
 }
 root.addEventListener('click',e=>{
  const modeButton=e.target.closest('button[data-mode]');if(modeButton){setMode(modeButton.dataset.mode);return;}
  const layer=e.target.closest('[data-select]');if(layer){selected=layer.dataset.select;render();return;}
  const add=e.target.closest('[data-add]');if(add){if(page.blocks.length>=32)return;checkpoint();const b=base(add.dataset.add);page.blocks.push(b);selected=b.id;commit();return;}
  const action=e.target.closest('[data-zc-action]')?.dataset.zcAction;if(!action)return;
  if(action==='all-tools'||action==='basic-tools'){prefs.tools=action==='all-tools'?[...policy.tools]:[];setMode('custom');return;}
  const b=active();
  if(action==='export'){q('[data-zc-transfer]').value=JSON.stringify(page,null,2);return;}
  if(action==='import'){try{const next=validate(JSON.parse(q('[data-zc-transfer]').value));checkpoint();page=next;selected=null;commit();}catch(err){q('[data-zc-notice]').textContent=err.message;}return;}
  if(action==='undo'||action==='redo'){const from=action==='undo'?undo:redo,to=action==='undo'?redo:undo;if(from.length){to.push(copy(page));page=from.pop();selected=null;commit();}return;}
  if(action==='enable'){commit();return;}
  if(action==='template'){if(page.blocks.length&&!q('[data-replace]').checked){q('[data-zc-notice]').textContent='Check Replace existing composition elements to apply a starter. Your legacy content is retained.';return;}checkpoint();page.background='#ffffff';page.blocks=starter(q('[data-template]').value);selected=page.blocks.find(x=>x.type==='text')?.id;commit();return;}
  if(!b)return;
  checkpoint();const index=page.blocks.indexOf(b);
  if(action==='duplicate'){if(page.blocks.length>=32){undo.pop();return;}const dupe=copy(b);dupe.id=id();dupe.x+=6;dupe.y+=6;dupe.locked=false;clamp(dupe);page.blocks.splice(index+1,0,dupe);selected=dupe.id;}
  if(action==='remove'){page.blocks.splice(index,1);selected=null;}
  if(action==='forward'&&index<page.blocks.length-1)[page.blocks[index],page.blocks[index+1]]=[page.blocks[index+1],page.blocks[index]];
  if(action==='backward'&&index>0)[page.blocks[index],page.blocks[index-1]]=[page.blocks[index-1],page.blocks[index]];
  if(action==='clear-fill')b.fill='transparent';
  if(!b.locked){if(action==='align-left')b.x=24;if(action==='align-center')b.x=(W-b.w)/2;if(action==='align-right')b.x=Math.max(0,W-24-b.w);clamp(b);}
  commit();
 });
 root.addEventListener('input',e=>{const el=e.target;if(el.matches('[data-zc-preference]')){e.stopPropagation();prefs.tools=all('[data-custom-tool]:checked').map(b=>b.dataset.customTool);remember();render();return;}if(el.matches('[data-zc-json],[data-zc-transfer]'))return;if(el.matches('[data-page-color]')){checkpoint();page.background=el.value;commit();return;}
  if(el.dataset.prop){const b=active();if(!b)return;const key=el.dataset.prop;if(b.locked&&['x','y','w','h'].includes(key))return;checkpoint();b[key]=el.type==='checkbox'?el.checked:el.type==='number'?Number(el.value):el.value;clamp(b);if(key==='size')b.size=Math.min(72,Math.max(6,b.size||12));if(key==='leading')b.leading=Math.min(2,Math.max(1,b.leading||1.35));if(key==='stroke_width')b.stroke_width=Math.min(8,Math.max(0,b.stroke_width||0));enable();dirty();render(false);}
 });
 root.addEventListener('change',e=>{if(e.target.matches('[data-zc-preference]'))e.stopPropagation();if(e.target.matches('[data-guides]'))render();});
 design.addEventListener('change',()=>render());
 canvas.addEventListener('pointerdown',e=>{const target=e.target.closest('[data-id]');if(!target)return;selected=target.dataset.id;const b=active();const resize=!!e.target.closest('[data-resize]');render();if(b.locked)return;checkpoint();drag={x:e.clientX,y:e.clientY,b:copy(b),resize};canvas.setPointerCapture(e.pointerId);e.preventDefault();});
 canvas.addEventListener('pointermove',e=>{if(!drag)return;const rect=canvas.getBoundingClientRect(),dx=(e.clientX-drag.x)/rect.width*W,dy=(e.clientY-drag.y)/rect.height*H,b=active();if(!b)return;const snap=n=>policy.visible(mode,prefs.tools,'snapping')&&q('[data-snap]').checked?Math.round(n/6)*6:n;if(drag.resize){b.w=snap(drag.b.w+dx);b.h=snap(drag.b.h+dy);}else{b.x=snap(drag.b.x+dx);b.y=snap(drag.b.y+dy);}clamp(b);enable();dirty();render();});
 const endDrag=()=>{drag=null;};canvas.addEventListener('pointerup',endDrag);canvas.addEventListener('pointercancel',endDrag);
 canvas.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;const b=active();if(!b||b.locked)return;e.preventDefault();checkpoint();const n=e.shiftKey?6:1;b.x+=e.key==='ArrowRight'?n:e.key==='ArrowLeft'?-n:0;b.y+=e.key==='ArrowDown'?n:e.key==='ArrowUp'?-n:0;clamp(b);commit();});
 form.addEventListener('submit',e=>{if(design.value!=='composition')return;try{page=validate(page);json.value=JSON.stringify(page);}catch(err){e.preventDefault();q('[data-zc-notice]').textContent=err.message;}});
 q('[data-zc-controls]').hidden=false;json.hidden=true;setMode(prefs.mode);
}
})();
