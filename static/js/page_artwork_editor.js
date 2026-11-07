/* Non-destructive Page artwork controls. All persisted values are also validated server-side. */
(() => {
  'use strict';
  const form = document.getElementById('page-artwork-editor');
  if (!form) return;
  const preview = form.querySelector('[data-art-preview]');
  const viewport = form.querySelector('.art-preview-viewport');
  const status = form.querySelector('[data-art-status]');
  const slots = {};
  const defaults = slot => ({mode: slot === 'avatar' ? 'logo' : 'portrait', shape: slot === 'avatar' ? 'rounded' : 'square',
    zoom: 1, x: 50, y: 50, padding: 0, background: 'transparent', trim: slot === 'avatar'});
  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
  const clone = x => JSON.parse(JSON.stringify(x));
  function resize() {
    const mobile = form.querySelector('[data-art-size]').value === 'mobile';
    const width = mobile ? 390 : 1120;
    preview.dataset.size = mobile ? 'mobile' : 'desktop';
    preview.style.width = `${width}px`;
    const scale = Math.min(1, viewport.clientWidth / width);
    preview.style.transform = `scale(${scale})`;
    viewport.style.height = `${Math.ceil(preview.offsetHeight * scale)}px`;
  }
  function sync(slot) {
    const item = slots[slot], cfg = item.cfg;
    item.state.value = JSON.stringify(cfg);
    for (const input of item.controls.querySelectorAll('[data-art-setting]')) {
      const key = input.dataset.artSetting;
      if (input.type === 'checkbox') input.checked = cfg[key];
      else input.value = key === 'background' && cfg.background === 'transparent' ? '#ffffff' : cfg[key];
      input.disabled = (['trim', 'padding'].includes(key) && cfg.mode !== 'logo') ||
        (key === 'background' && cfg.background === 'transparent');
    }
    const transparent = item.controls.querySelector('[data-art-transparent]');
    if (transparent) transparent.checked = cfg.background === 'transparent';
    for (const output of item.controls.querySelectorAll('[data-art-output]')) {
      const key = output.dataset.artOutput;
      output.value = key === 'zoom' ? `${Number(cfg[key]).toFixed(2)}×` : `${Math.round(cfg[key])}%`;
    }
    const target = item.target;
    target.style.setProperty('--art-fit', cfg.mode === 'logo' ? 'contain' : 'cover');
    target.style.setProperty('--art-zoom', cfg.zoom);
    target.style.setProperty('--art-x', `${cfg.x}%`);
    target.style.setProperty('--art-y', `${cfg.y}%`);
    target.style.setProperty('--art-padding', `${cfg.mode === 'logo' ? cfg.padding : 0}%`);
    target.style.setProperty('--art-background', cfg.background);
    target.style.borderRadius = {square:'0',rounded:'1rem',circle:'50%'}[cfg.shape];
    const src = cfg.mode === 'logo' && cfg.trim ? item.trimmed : item.source;
    item.image.hidden = !src || item.remove.checked;
    if (src && item.image.getAttribute('src') !== src) item.image.src = src;
    const initial = target.querySelector('.art-preview-initial');
    if (initial) initial.hidden = !item.image.hidden;
    resize();
  }
  async function load(slot, source) {
    const item = slots[slot], generation = ++item.generation;
    item.source = source; item.trimmed = source;
    if (!source) { sync(slot); return; }
    const image = new Image();
    image.src = source;
    try {
      await image.decode();
      if (generation !== item.generation) return;
      if (image.naturalWidth * image.naturalHeight > 16000000) throw new Error('large');
      if (slot === 'avatar') {
        const canvas = document.createElement('canvas');
        canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
        const context = canvas.getContext('2d', {willReadFrequently:true});
        context.drawImage(image,0,0);
        const pixels = context.getImageData(0,0,canvas.width,canvas.height).data;
        let left=canvas.width, top=canvas.height, right=-1, bottom=-1;
        for (let y=0;y<canvas.height;y++) for (let x=0;x<canvas.width;x++) {
          if (pixels[(y*canvas.width+x)*4+3]) {left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);}
        }
        if (right>=left && bottom>=top) {
          const cropped=document.createElement('canvas');
          cropped.width=right-left+1;cropped.height=bottom-top+1;
          cropped.getContext('2d').drawImage(canvas,left,top,cropped.width,cropped.height,0,0,cropped.width,cropped.height);
          item.trimmed=cropped.toDataURL('image/png');
        }
      }
      status.textContent = '';
      sync(slot);
    } catch (_) {
      if (generation !== item.generation) return;
      status.textContent = 'This image could not be previewed. Choose a valid image under 1.8 MB and 16 megapixels.';
      item.source='';item.trimmed='';sync(slot);
    }
  }
  for (const controls of form.querySelectorAll('[data-art-slot]')) {
    const slot=controls.dataset.artSlot;
    const state=controls.querySelector('[data-art-state]');
    let cfg=defaults(slot);
    try { cfg={...cfg,...JSON.parse(state.value)}; } catch (_) { /* Server will validate on save. */ }
    const file=form.querySelector(`input[type=file][name=${slot}]`);
    const remove=form.querySelector(`input[name=remove_${slot}]`) || {checked:false};
    const target=preview.querySelector(`[data-art-target=${slot}]`);
    slots[slot]={controls,state,cfg,initial:clone(cfg),file,remove,target,image:target.querySelector('img'),
      original:preview.dataset[`${slot}Source`],source:'',trimmed:'',objectURL:null,generation:0};
    controls.addEventListener('input', event => {
      const input=event.target, item=slots[slot];
      if (input.matches('[data-art-transparent]')) item.cfg.background=input.checked ? 'transparent' : controls.querySelector('[data-art-setting=background]').value;
      else if (input.dataset.artSetting) {
        const key=input.dataset.artSetting;
        item.cfg[key]=input.type==='checkbox' ? input.checked : input.type==='range' ? Number(input.value) : input.value;
      } else return;
      sync(slot);
    });
    controls.querySelector('[data-art-reset]').addEventListener('click',()=>{
      slots[slot].cfg=defaults(slot);sync(slot);status.textContent='Framing reset in the preview. Save to apply it.';
    });
    file.addEventListener('change',()=>{
      const item=slots[slot];
      if (item.objectURL) URL.revokeObjectURL(item.objectURL);
      item.objectURL=null;
      if (!file.files[0]) {load(slot,item.original);return;}
      if (file.files[0].size>1800*1024) {
        status.textContent='Choose an image under 1.8 MB. The current image is unchanged.';file.value='';return;
      }
      item.remove.checked=false;item.cfg=defaults(slot);
      item.objectURL=URL.createObjectURL(file.files[0]);load(slot,item.objectURL);
    });
    if (remove.addEventListener) remove.addEventListener('change',()=>sync(slot));
    let drag=null;
    target.addEventListener('pointerdown',e=>{
      if (e.button!==0 || slots[slot].image.hidden) return;
      drag={x:e.clientX,y:e.clientY,cfg:clone(slots[slot].cfg)};target.setPointerCapture(e.pointerId);e.preventDefault();
    });
    target.addEventListener('pointermove',e=>{
      if (!drag) return;
      const rect=target.getBoundingClientRect(), cfg=slots[slot].cfg;
      cfg.x=clamp(drag.cfg.x-(e.clientX-drag.x)/rect.width*100,0,100);
      cfg.y=clamp(drag.cfg.y-(e.clientY-drag.y)/rect.height*100,0,100);sync(slot);
    });
    target.addEventListener('pointerup',()=>{drag=null;});target.addEventListener('pointercancel',()=>{drag=null;});
    target.addEventListener('keydown',e=>{
      const moves={ArrowLeft:['x',-1],ArrowRight:['x',1],ArrowUp:['y',-1],ArrowDown:['y',1]};
      if (!moves[e.key]) return;
      e.preventDefault();const [key,delta]=moves[e.key];
      slots[slot].cfg[key]=clamp(slots[slot].cfg[key]+delta*(e.shiftKey?10:1),0,100);sync(slot);
    });
  }
  for (const slot of Object.keys(slots)) load(slot,slots[slot].original);
  form.querySelector('[data-art-size]').addEventListener('change',resize);
  form.querySelector('[data-art-cancel]').addEventListener('click',()=>{
    form.reset();
    preview.querySelector('[data-art-tagline]').textContent=form.querySelector('[name=tagline]').value;
    for (const [slot,item] of Object.entries(slots)) {
      if (item.objectURL) URL.revokeObjectURL(item.objectURL);
      item.objectURL=null;item.cfg=clone(item.initial);load(slot,item.original);
    }
    status.textContent='Unsaved changes cancelled.';
  });
  form.querySelector('[name=tagline]').addEventListener('input',e=>{preview.querySelector('[data-art-tagline]').textContent=e.target.value;resize();});
  new ResizeObserver(resize).observe(viewport);
  window.addEventListener('pagehide',()=>{for(const item of Object.values(slots))if(item.objectURL)URL.revokeObjectURL(item.objectURL);});
})();
