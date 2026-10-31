/* Structured composition editor. User content is always inserted with textContent. */
(() => {
'use strict';
const geometry=window.ZineGeometry;
const W=396,H=612,copy=v=>JSON.parse(JSON.stringify(v));
for (const root of document.querySelectorAll('[data-zc-editor]')) {
 const form=root.closest('form'),q=s=>root.querySelector(s),all=s=>[...root.querySelectorAll(s)];
 const json=q('[data-zc-json]'),canvas=q('.zc-edit-canvas'),design=form.elements.namedItem('design'),policy=window.ZineToolsets;
 let prefs=policy.preferences(null);
 try { prefs=policy.preferences(JSON.parse(localStorage.getItem(root.dataset.preferenceKey))); } catch {}
 function remember(){prefs.mode=mode;try {localStorage.setItem(root.dataset.preferenceKey,JSON.stringify(prefs));}catch{q('[data-zc-preference-status]').textContent='Preferences apply for this visit; browser storage is unavailable.';}}
 function toolVisibility(){const b=active();for(const el of all('[data-tool]'))el.hidden=!policy.visible(mode,prefs.tools,el.dataset.tool)||(el.dataset.for&&(!b||el.dataset.for!==b.type));}
 let page={version:1,background:'#ffffff',blocks:[]},selected=null,mode='standard',undo=[],redo=[],drag=null,multi=new Set(),clipboard=[],savedLayouts=[];
 let inlineIndex=-1,inlineOwner=null,textCursor=0;
 const flow=window.ZineFlow;
 const libraryKey=root.dataset.preferenceKey+'-layouts';
 try{const stored=JSON.parse(localStorage.getItem(libraryKey));if(Array.isArray(stored))savedLayouts=stored.slice(0,12);}catch{}
 try { if(json.value.trim())page=JSON.parse(json.value); } catch { q('[data-zc-notice]').textContent='Stored composition could not be read. Preserve the JSON before editing.'; }
 const assets=new Map(all('[data-prop="image"] option[data-src]').map(o=>[o.value,o.dataset.src]));
 const value=n=>form.elements.namedItem(n)?.value||'';
 const id=()=> 'e'+Math.random().toString(36).slice(2,12);
 function base(type,x=24,y=24,w=180,h=100){return {id:id(),type,x,y,w,h,locked:false,fill:type==='box'||type==='ellipse'?'#b52525':'transparent',color:'#171717',stroke:'#171717',stroke_width:0,rotation:0,opacity:1,group:'',name:'',...(type==='text'?{text:'Your text here',font:'sans',size:12,leading:1.35,align:'left'}:type==='image'?{image:'',alt:'',fit:'contain',focal_x:50,focal_y:50}:{})};}
 function clamp(b){geometry.fit(b);}
 function selectedBlocks(){return page.blocks.filter(b=>multi.has(b.id));}
 function select(ident,extend=false){
  const b=page.blocks.find(b=>b.id===ident);if(!b)return;
  const ids=policy.visible(mode,prefs.tools,'composition')&&b.group?page.blocks.filter(x=>x.group===b.group).map(x=>x.id):[ident];
  if(!extend)multi.clear();const remove=extend&&ids.every(x=>multi.has(x));for(const x of ids)remove?multi.delete(x):multi.add(x);selected=multi.has(ident)?ident:[...multi].at(-1)||null;
 }
 function updateLibrary(){const list=q('[data-saved-layout]');list.replaceChildren();for(let i=0;i<savedLayouts.length;i++){const o=document.createElement('option');o.value=String(i);o.textContent=savedLayouts[i].name;list.append(o);}}
 function saveLibrary(){try{localStorage.setItem(libraryKey,JSON.stringify(savedLayouts));return true;}catch{q('[data-zc-library-status]').textContent='Unable to save layouts in this browser. Export JSON to keep a copy.';return false;}}
 function issue(message){q('[data-zc-notice]').textContent=message;}
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
  q('[data-zc-mode-help]').textContent={standard:'Standard: layout starters, text and images, simple formatting, dragging, resizing and undo. Select an element to edit it.',custom:'Custom: every Standard tool plus the Advanced groups you select in Choose your Custom tools.',advanced:'Advanced: all available composition tools. Shift-click elements to select several; grouped elements move together. Save page to keep changes.'}[mode];
  remember();render();
 }

 function style(el,b){Object.assign(el.style,{left:(b.x/W*100)+'%',top:(b.y/H*100)+'%',width:(b.w/W*100)+'%',height:(b.h/H*100)+'%',color:b.color,background:b.fill,border:`${b.stroke_width/W*100}cqw solid ${b.stroke}`,fontFamily:b.font==='mono'?'monospace':'DejaVu Sans, sans-serif',fontWeight:b.font==='bold'?'700':'400',fontSize:(b.size||12)/W*100+'cqw',lineHeight:String(b.leading||1.35),textAlign:b.align||'left',transform:`rotate(${b.rotation||0}deg)`,opacity:String(b.opacity??1)});}
 function render(sync=true){
  multi=new Set([...multi].filter(id=>page.blocks.some(b=>b.id===id)));if(selected&&!multi.size)multi.add(selected);
  canvas.replaceChildren();canvas.style.background=page.background;canvas.classList.toggle('zc-guides',q('[data-guides]').checked);q('[data-page-color]').value=page.background;
  for(const b of page.blocks){const el=document.createElement('div');el.className='zc-element zc-type-'+b.type+(multi.has(b.id)?' zc-selected':'');el.dataset.id=b.id;style(el,b);el.setAttribute('aria-label',b.type+' element');
   if(b.type==='text'){if(b.insets?.length)flow.render(el,b,assets,preflight);else el.textContent=b.text;}
   else if(b.type==='image'){if(assets.has(b.image)){const img=document.createElement('img');img.src=assets.get(b.image);img.alt=b.alt;img.style.objectFit=b.fit;img.style.objectPosition=`${b.focal_x??50}% ${b.focal_y??50}%`;img.addEventListener('load',preflight,{once:true});img.draggable=false;el.append(img);}else{el.textContent='Select artwork';el.classList.add('zc-placeholder');}}
   else if(b.type==='rule'){const line=document.createElement('span');line.style.borderTop=`${Math.max(1,b.stroke_width)/W*100}cqw solid ${b.color}`;el.append(line);}
   if(selected===b.id&&!b.locked){const handle=document.createElement('span');handle.className='zc-resize';handle.dataset.resize='1';handle.title='Drag to resize';el.append(handle);}
   canvas.append(el);
  }
  const layers=q('[data-zc-layers]');layers.replaceChildren();for(const b of [...page.blocks].reverse()){const btn=document.createElement('button');btn.type='button';btn.dataset.select=b.id;btn.textContent=(b.locked?'🔒 ':'')+(b.name||b.type)+' · '+(b.text||b.alt||b.id).slice(0,36);btn.setAttribute('aria-pressed',String(multi.has(b.id)));layers.append(btn);}
  const b=active();q('[data-zc-inspector]').hidden=!b;q('[data-zc-empty]').hidden=!!b;
  if(b&&sync){for(const el of all('[data-prop]')){if(el.type==='checkbox')el.checked=!!b[el.dataset.prop];else el.value=b[el.dataset.prop]==='transparent'?'#ffffff':b[el.dataset.prop]??({rotation:0,opacity:1,focal_x:50,focal_y:50,name:''}[el.dataset.prop]??'');}for(const el of all('[data-for]'))el.hidden=el.dataset.for!==b.type;}
  inlineControls(b,sync);toolVisibility();q('[data-zc-selection]').textContent=`${multi.size} selected${selectedBlocks().some(b=>b.locked)?' · locked elements included':''}`;
  q('[data-zc-action="undo"]').disabled=!undo.length;q('[data-zc-action="redo"]').disabled=!redo.length;
  requestAnimationFrame(preflight);
 }
 function inlineControls(b,sync){
  const list=q('[data-inline-selected]');if(!list)return;
  if(inlineOwner!==b?.id){inlineOwner=b?.id;inlineIndex=-1;textCursor=0;}
  const images=b?.insets||[];if(inlineIndex>=images.length)inlineIndex=-1;
  list.replaceChildren();const fresh=document.createElement('option');fresh.value='';fresh.textContent='New image';list.append(fresh);
  images.forEach((image,index)=>{const option=document.createElement('option');option.value=String(index);option.textContent=(index+1)+': '+(image.caption||image.alt||image.mode).slice(0,40);list.append(option);});list.value=inlineIndex<0?'':String(inlineIndex);
  if(sync&&inlineIndex>=0)for(const key of ['image','mode','width','height','gap','alt','caption','credit'])q('[data-inline-'+key+']').value=images[inlineIndex][key];
  q('[data-inline-status]').textContent=images.length+' / 6 attached images. Cursor position '+textCursor+'.';
 }
 function inlineValues(b){
  const image={at:textCursor};for(const key of ['image','mode','alt','caption','credit'])image[key]=q('[data-inline-'+key+']').value;
  for(const key of ['width','height','gap'])image[key]=Number(q('[data-inline-'+key+']').value);
  if(!assets.has(image.image))throw Error('Choose artwork from this publication.');
  image.at=Math.min(Array.from(b.text).length,image.at);
  if(image.mode!=='inline'){const before=Array.from(b.text).slice(0,image.at);image.at=before.lastIndexOf('\n')+1;}
  flow.validate([image],b,assets);return image;
 }
 root.addEventListener('select',e=>{if(e.target.matches('[data-prop="text"]')){textCursor=Array.from(e.target.value.slice(0,e.target.selectionStart)).length;inlineControls(active(),false);}});
 root.addEventListener('keyup',e=>{if(e.target.matches('[data-prop="text"]'))textCursor=Array.from(e.target.value.slice(0,e.target.selectionStart)).length;});
 function preflight(){
  const list=q('[data-zc-checks]');list.replaceChildren();let count=0;
  const warn=(b,msg)=>{count++;const li=document.createElement('li'),button=document.createElement('button');button.type='button';button.dataset.select=b.id;button.textContent=(b.name||b.type)+': '+msg;li.append(button);list.append(li);};
  const luminance=hex=>{const rgb=hex.slice(1).match(/../g).map(x=>parseInt(x,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;};
  for(const b of page.blocks){const el=[...canvas.children].find(el=>el.dataset.id===b.id),bb=geometry.bounds(b);
   if(b.type==='text'){
    if(el&&(el.scrollHeight>el.clientHeight+1||el.scrollWidth>el.clientWidth+1))warn(b,'text may overflow; enlarge the frame or reduce type size.');
    if(b.text&&b.size<9)warn(b,'small print text (below 9 pt).');
    if(b.text){const bg=b.fill==='transparent'?page.background:b.fill,l1=luminance(b.color),l2=luminance(bg),ratio=(Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05);if(ratio<(b.size>=18||b.font==='bold'&&b.size>=14?3:4.5))warn(b,'low contrast against its fill/page color; check overlapping artwork separately.');}
   }
   for(const inset of b.insets||[]){if(!inset.image)warn(b,'an attached image needs artwork.');else if(!inset.alt.trim())warn(b,'add a description to attached artwork.');}
   if(b.type==='image'){
    if(!b.image)warn(b,'no artwork selected.');else {if(!b.alt.trim())warn(b,'add an image description.');const img=el?.querySelector('img');if(img?.naturalWidth){const ratio=(b.fit==='cover'?Math.min:Math.max)(img.naturalWidth/b.w,img.naturalHeight/b.h),dpi=Math.round(72*ratio);if(dpi<150)warn(b,`artwork is about ${dpi} DPI at logical print size; use a larger source or smaller frame.`);}}
   }
   if(b.type==='text'&&b.text&&(bb.x<18||bb.y<18||bb.x+bb.w>W-18||bb.y+bb.h>H-18))warn(b,'text is within 18 pt of the page edge.');
  }
  if(!count){const li=document.createElement('li');li.textContent='No issues detected by these page checks.';list.append(li);}
  q('[data-zc-check-summary]').textContent=`${count} page check${count===1?'':'s'} to review`;
  issue(`${page.blocks.length} / 32 elements · ${multi.size} selected · ${design.value==='composition'?'Visual composition active.':'Legacy preset active; choose Use visual composition.'} ${count?'Open Page checks for details.':''}`);
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
   if(Object.keys(b).some(k=>!['id','type','x','y','w','h','text','image','alt','font','size','leading','align','color','fill','stroke','stroke_width','fit','locked','rotation','opacity','group','name','focal_x','focal_y','insets'].includes(k)))throw Error('Unsupported element property.');
   for(const k of ['x','y','w','h'])if(typeof b[k]!=='number'||!Number.isFinite(b[k]))throw Error('Element coordinates must be finite numbers.');
   if(b.x<0||b.y<0||b.w<12||b.h<12||b.x+b.w>W||b.y+b.h>H)throw Error('Keep elements inside the page.');
   for(const [k,low,high,fallback] of [['rotation',-180,180,0],['opacity',.05,1,1],['focal_x',0,100,50],['focal_y',0,100,50]])if(b[k]!==undefined&&(typeof b[k]!=='number'||!Number.isFinite(b[k])||b[k]<low||b[k]>high))throw Error('Invalid '+k);
   if(b.group!==undefined&&(typeof b.group!=='string'||b.group&&!/^[-\w]{1,40}$/.test(b.group)))throw Error('Invalid group.');
   if(b.name!==undefined&&(typeof b.name!=='string'||b.name.length>80))throw Error('Element name is too long.');
   const bb=geometry.bounds(b);if(bb.x<-.02||bb.y<-.02||bb.x+bb.w>W+.02||bb.y+bb.h>H+.02)throw Error('Keep rotated elements inside the page.');
   if(typeof b.locked!=='boolean')throw Error('Element locked must be true or false.');
   for(const k of ['color','stroke','fill'])if(!(k==='fill'&&b[k]==='transparent')&&!/^#[\da-f]{6}$/i.test(b[k]))throw Error('Use six-digit colors.');
   if(typeof b.stroke_width!=='number'||!Number.isFinite(b.stroke_width)||b.stroke_width<0||b.stroke_width>8)throw Error('Border must be 0–8 pt.');
   if(b.type==='image'&&(!['contain','cover'].includes(b.fit)||typeof b.alt!=='string'||b.alt.length>300||typeof b.image!=='string'||(b.image&&!assets.has(b.image))))throw Error('Choose artwork from this publication.');
   if(b.type==='text'){if(typeof b.text!=='string'||!['sans','bold','mono'].includes(b.font)||!['left','center','right'].includes(b.align)||typeof b.size!=='number'||!Number.isFinite(b.size)||b.size<6||b.size>72||typeof b.leading!=='number'||!Number.isFinite(b.leading)||b.leading<1||b.leading>2)throw Error('Invalid text typography.');chars+=b.text.length;if(b.insets!==undefined){flow.validate(b.insets,b,assets);chars+=b.insets.reduce((n,i)=>n+i.caption.length+i.credit.length,0);}}else if(b.insets!==undefined)throw Error('Only text frames can contain attached images.');
  }if(raw.blocks.reduce((n,b)=>n+(b.insets?.length||0),0)>16)throw Error('Use at most sixteen attached images on a page.');if(chars>6000)throw Error('Use at most 6000 text characters.');return copy(raw);
 }
 root.addEventListener('click',e=>{
  const modeButton=e.target.closest('button[data-mode]');if(modeButton){setMode(modeButton.dataset.mode);return;}
  const layer=e.target.closest('[data-select]');if(layer){select(layer.dataset.select,e.shiftKey);render();return;}
  const add=e.target.closest('[data-add]');if(add){if(page.blocks.length>=32)return;checkpoint();const b=base(add.dataset.add);page.blocks.push(b);select(b.id);commit();return;}
  const action=e.target.closest('[data-zc-action]')?.dataset.zcAction;if(!action)return;
  if(action==='all-tools'||action==='basic-tools'){prefs.tools=action==='all-tools'?[...policy.tools]:[];setMode('custom');return;}
  const b=active(),selection=selectedBlocks();
  if(action.startsWith('inline-')){
   if(!b||b.type!=='text'){issue('Select a text frame first.');return;}
   try{
    const next=copy(b.insets||[]);
    if(action==='inline-remove'){if(inlineIndex<0)return;next.splice(inlineIndex,1);}
    else {const image=inlineValues(b);
     if(action==='inline-insert'){if(next.length>=6)throw Error('Use at most six images per text frame.');next.push(image);}
     else if(inlineIndex<0)throw Error('Choose an attached image to update or move.');
     else if(action==='inline-move')next[inlineIndex].at=image.at;
     else next[inlineIndex]={...image,at:next[inlineIndex].at};
    }
    next.sort((a,b)=>a.at-b.at);flow.validate(next,b,assets);checkpoint();b.insets=next;inlineIndex=-1;commit();issue('Attached artwork updated. Save page to keep it.');
   }catch(err){issue(err.message);}return;
  }
  if(action==='select-all'){multi=new Set(page.blocks.map(b=>b.id));selected=page.blocks.at(-1)?.id||null;render();return;}
  if(action==='deselect'){multi.clear();selected=null;render();return;}
  if(action==='copy-selection'){clipboard=copy(selection);issue('Selection copied within this editor.');return;}
  if(action==='paste-selection'){
   if(!clipboard.length||page.blocks.length+clipboard.length>32){issue('Copy elements first; keep at most 32 elements.');return;}
   checkpoint();const groupIds=new Map();const clones=copy(clipboard);for(const b of clones){b.id=id();b.locked=false;if(b.group){if(!groupIds.has(b.group))groupIds.set(b.group,id());b.group=groupIds.get(b.group);}}geometry.translate(clones,6,6);page.blocks.push(...clones);multi=new Set(clones.map(b=>b.id));selected=clones.at(-1).id;commit();return;
  }
  if(action==='save-layout'){
   const name=q('[data-layout-name]').value.trim().slice(0,60);if(!name){issue('Give the layout a name.');return;}
   const entry={name,page:copy(page)};for(const b of entry.page.blocks){if(b.type==='image'){b.image='';b.alt='';}for(const inset of b.insets||[]){inset.image='';inset.alt='';inset.credit='';}}
   const next=savedLayouts.filter(x=>x.name!==name);next.unshift(entry);const old=savedLayouts;savedLayouts=next.slice(0,12);if(!saveLibrary())savedLayouts=old;else q('[data-zc-library-status]').textContent='Layout saved in this browser for your account. Artwork references are cleared in reusable layouts.';updateLibrary();return;
  }
  if(action==='load-layout'){
   const entry=savedLayouts[Number(q('[data-saved-layout]').value)];if(!entry)return;if(page.blocks.length&&!q('[data-replace]').checked){issue('Check Replace existing composition elements first.');return;}
   try{const next=validate(entry.page);checkpoint();page=next;selected=null;multi.clear();commit();}catch(err){issue(err.message);}return;
  }
  if(action==='delete-layout'){const index=Number(q('[data-saved-layout]').value);if(!savedLayouts[index])return;const old=savedLayouts;savedLayouts=savedLayouts.filter((_,i)=>i!==index);if(!saveLibrary())savedLayouts=old;updateLibrary();return;}
  if(action==='apply-type-style'){
   const styles={headline:{font:'bold',size:28,leading:1.15,align:'left'},subhead:{font:'bold',size:18,leading:1.25,align:'left'},body:{font:'sans',size:12,leading:1.35,align:'left'},caption:{font:'sans',size:9,leading:1.25,align:'left'},quote:{font:'bold',size:22,leading:1.2,align:'left'}};
   if(!selection.some(b=>b.type==='text'))return;checkpoint();for(const b of selection)if(b.type==='text')Object.assign(b,styles[q('[data-type-style]').value]);commit();return;
  }
  if(action==='replace-artwork'){
   if(!b||b.type!=='image'||!b.image)return;const next=q('[data-replacement-artwork]').value;if(!assets.has(next)){issue('Choose replacement artwork.');return;}checkpoint();const previous=b.image;for(const item of page.blocks){if(item.type==='image'&&item.image===previous)item.image=next;for(const inset of item.insets||[])if(inset.image===previous)inset.image=next;}commit();return;
  }
  if(action==='group'||action==='ungroup'){
   if(selection.length<2&&action==='group')return;checkpoint();const group=action==='group'?id():'';for(const item of selection)item.group=group;commit();return;
  }
  if(action.startsWith('objects-')||action.startsWith('distribute-')){
   if(!selection.length)return;if(selection.some(b=>b.locked)){issue('Unlock all selected elements before arranging them.');return;}checkpoint();if(action.startsWith('objects-'))geometry.align(selection,action.slice(8),q('[data-align-page]').checked);else geometry.distribute(selection,action.slice(11));commit();return;
  }
  if(action==='export'){q('[data-zc-transfer]').value=JSON.stringify(page,null,2);return;}
  if(action==='import'){try{const next=validate(JSON.parse(q('[data-zc-transfer]').value));checkpoint();page=next;selected=null;multi.clear();commit();}catch(err){q('[data-zc-notice]').textContent=err.message;}return;}
  if(action==='undo'||action==='redo'){const from=action==='undo'?undo:redo,to=action==='undo'?redo:undo;if(from.length){to.push(copy(page));page=from.pop();selected=null;multi.clear();commit();}return;}
  if(action==='enable'){commit();return;}
  if(action==='template'){if(page.blocks.length&&!q('[data-replace]').checked){q('[data-zc-notice]').textContent='Check Replace existing composition elements to apply a starter. Your legacy content is retained.';return;}checkpoint();page.background='#ffffff';page.blocks=starter(q('[data-template]').value);selected=page.blocks.find(x=>x.type==='text')?.id;multi=new Set(selected?[selected]:[]);commit();return;}
  if(!b)return;
  if(['duplicate','remove'].includes(action)&&selection.length>1){
   if(action==='duplicate'){clipboard=copy(selection);q('[data-zc-action="paste-selection"]').click();return;}
   checkpoint();page.blocks=page.blocks.filter(b=>!multi.has(b.id));multi.clear();selected=null;commit();return;
  }
  checkpoint();const index=page.blocks.indexOf(b);
  if(action==='duplicate'){if(page.blocks.length>=32){undo.pop();return;}const dupe=copy(b);dupe.id=id();dupe.x+=6;dupe.y+=6;dupe.locked=false;clamp(dupe);page.blocks.splice(index+1,0,dupe);selected=dupe.id;multi=new Set([dupe.id]);}
  if(action==='remove'){page.blocks.splice(index,1);selected=null;multi.clear();}
  if(action==='forward'&&index<page.blocks.length-1)[page.blocks[index],page.blocks[index+1]]=[page.blocks[index+1],page.blocks[index]];
  if(action==='backward'&&index>0)[page.blocks[index],page.blocks[index-1]]=[page.blocks[index-1],page.blocks[index]];
  if(action==='clear-fill')b.fill='transparent';
  if(!b.locked){if(action==='align-left')b.x=24;if(action==='align-center')b.x=(W-b.w)/2;if(action==='align-right')b.x=Math.max(0,W-24-b.w);clamp(b);}
  commit();
 });
 root.addEventListener('input',e=>{const el=e.target;if(el.matches('[data-zc-preference]')){e.stopPropagation();prefs.tools=all('[data-custom-tool]:checked').map(b=>b.dataset.customTool);remember();render();return;}if(el.matches('[data-zc-json],[data-zc-transfer]'))return;if(el.matches('[data-page-color]')){checkpoint();page.background=el.value;commit();return;}
  if(el.dataset.prop){const b=active();if(!b)return;const key=el.dataset.prop;if(b.locked&&['x','y','w','h','rotation'].includes(key))return;checkpoint();if(key==='text'&&b.insets?.length)flow.moveAnchors(b.text,el.value,b.insets);b[key]=el.type==='checkbox'?el.checked:el.type==='number'?Number(el.value):el.value;if(key==='rotation')b.rotation=Math.min(180,Math.max(-180,b.rotation||0));if(key==='opacity')b.opacity=Math.min(1,Math.max(.05,b.opacity||1));if(['focal_x','focal_y'].includes(key))b[key]=Math.min(100,Math.max(0,b[key]||0));clamp(b);if(key==='size')b.size=Math.min(72,Math.max(6,b.size||12));if(key==='leading')b.leading=Math.min(2,Math.max(1,b.leading||1.35));if(key==='stroke_width')b.stroke_width=Math.min(8,Math.max(0,b.stroke_width||0));if(key==='text')textCursor=Array.from(el.value.slice(0,el.selectionStart)).length;enable();dirty();render(false);}
 });
 root.addEventListener('change',e=>{if(e.target.matches('[data-inline-selected]')){inlineIndex=e.target.value===''?-1:Number(e.target.value);inlineControls(active(),true);} if(e.target.matches('[data-zc-preference]'))e.stopPropagation();if(e.target.matches('[data-guides]'))render();});
 design.addEventListener('change',()=>render());
 canvas.addEventListener('pointerdown',e=>{const target=e.target.closest('[data-id]');if(!target){multi.clear();selected=null;render();return;}
  const ident=target.dataset.id,resize=!!e.target.closest('[data-resize]');if(e.shiftKey){select(ident,true);render();e.preventDefault();return;}if(!multi.has(ident))select(ident);else selected=ident;const b=active();render();const selection=selectedBlocks();if(selection.some(b=>b.locked))return;checkpoint();drag={x:e.clientX,y:e.clientY,blocks:copy(selection),resize:resize&&selection.length===1,b:copy(b)};canvas.setPointerCapture(e.pointerId);e.preventDefault();});
 canvas.addEventListener('pointermove',e=>{if(!drag)return;const rect=canvas.getBoundingClientRect();let dx=(e.clientX-drag.x)/rect.width*W,dy=(e.clientY-drag.y)/rect.height*H;const snap=n=>policy.visible(mode,prefs.tools,'snapping')&&q('[data-snap]').checked?Math.round(n/6)*6:n;
  if(drag.resize){const b=active();b.w=snap(drag.b.w+dx);b.h=snap(drag.b.h+dy);clamp(b);}else{const selection=selectedBlocks();for(const b of selection){const old=drag.blocks.find(x=>x.id===b.id);b.x=old.x;b.y=old.y;}geometry.translate(selection,snap(drag.b.x+dx)-drag.b.x,snap(drag.b.y+dy)-drag.b.y);}enable();dirty();render();});
 const endDrag=()=>{drag=null;};canvas.addEventListener('pointerup',endDrag);canvas.addEventListener('pointercancel',endDrag);
 canvas.addEventListener('keydown',e=>{
  if(e.key==='Escape'){multi.clear();selected=null;render();return;}
  if((e.ctrlKey||e.metaKey)&&['a','c','v','z','y'].includes(e.key.toLowerCase())){e.preventDefault();const action={a:'select-all',c:'copy-selection',v:'paste-selection',z:e.shiftKey?'redo':'undo',y:'redo'}[e.key.toLowerCase()];q(`[data-zc-action="${action}"]`).click();return;}
  if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;const selection=selectedBlocks();if(!selection.length||selection.some(b=>b.locked))return;e.preventDefault();checkpoint();const n=e.shiftKey?6:1;geometry.translate(selection,e.key==='ArrowRight'?n:e.key==='ArrowLeft'?-n:0,e.key==='ArrowDown'?n:e.key==='ArrowUp'?-n:0);commit();});
 form.addEventListener('submit',e=>{if(design.value!=='composition')return;try{page=validate(page);json.value=JSON.stringify(page);}catch(err){e.preventDefault();q('[data-zc-notice]').textContent=err.message;}});
 updateLibrary();q('[data-zc-controls]').hidden=false;json.hidden=true;setMode(prefs.mode);
}
})();
