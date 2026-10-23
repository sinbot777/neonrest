const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFileSync}=require('node:child_process');
const {JSDOM}=require('jsdom');
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'neonrest-atmosphere-'));
try {
  const html=path.join(dir,'logo.html');
  execFileSync('python',[path.join(__dirname,'verify_vibe_atmosphere.py')],{env:{...process.env,NEONREST_ATMOSPHERE_HTML:html}});
  const script=fs.readFileSync(path.join(__dirname,'../static/js/vibe-atmosphere.js'),'utf8');
  function instance({reduced=false,pref='system',gif='system'}={}) {
    const dom=new JSDOM(fs.readFileSync(html,'utf8'),{runScripts:'outside-only',pretendToBeVisual:true});
    const w=dom.window,device={matches:reduced,addEventListener(type,handler){this.handler=handler;}};
    w.matchMedia=()=>device;w.NEON_ATMOSPHERE_PREFS={logo_motion:pref};w.NEON_MEDIA_PREFS={gif_mode:gif,midi_autoplay:0};
    w.eval(script);
    return {dom,w,device,img:w.document.querySelector('.vibe-logo'),button:w.document.querySelector('.vibe-logo-pause')};
  }
  let x=instance();
  assert.equal(x.img.classList.contains('vibe-logo-moving'),true);
  x.button.click();assert.equal(x.img.classList.contains('vibe-logo-moving'),false);
  assert.equal(x.button.getAttribute('aria-pressed'),'true');
  x.button.click();assert.equal(x.img.classList.contains('vibe-logo-moving'),true);
  x.device.matches=true;x.device.handler();
  assert.equal(x.img.classList.contains('vibe-logo-moving'),false);assert.equal(x.button.disabled,true);
  x.device.matches=false;x.device.handler();assert.equal(x.img.classList.contains('vibe-logo-moving'),true);
  Object.defineProperty(x.w.document,'hidden',{configurable:true,value:true});
  x.w.document.dispatchEvent(new x.w.Event('visibilitychange'));
  assert.equal(x.img.classList.contains('vibe-logo-moving'),false,'Hidden page stops motion');
  x.dom.window.close();
  for(const options of [{reduced:true},{pref:'off'},{gif:'off'}]) {
    x=instance(options);assert.equal(x.img.classList.contains('vibe-logo-moving'),false);
    assert.equal(x.button.disabled,true);x.dom.window.close();
  }
  const css=fs.readFileSync(path.join(__dirname,'../static/css/vibe-atmosphere.css'),'utf8');
  assert.match(css,/@media \(prefers-reduced-motion:reduce\)/);
  assert.match(css,/animation:none !important/);
  console.log('Actual logo widget: pause/resume, visitor/GIF/reduced-motion settings, live preference change and hidden-page pause passed');
} finally {fs.rmSync(dir,{recursive:true,force:true});}
