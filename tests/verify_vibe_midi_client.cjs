/* Actual MIDI widget/player: sound remains off unless opted in or clicked. */
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFileSync}=require('node:child_process');
const {JSDOM}=require('jsdom');
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'neonrest-vibe-midi-'));
(async()=>{
try {
  const html=path.join(dir,'widget.html'),midi=path.join(dir,'fixture.mid');
  execFileSync('python',[path.join(__dirname,'verify_vibe_atmosphere.py')],{env:{...process.env,NEONREST_ATMOSPHERE_HTML:html,NEONREST_ATMOSPHERE_MIDI:midi}});
  const source=fs.readFileSync(path.join(__dirname,'../static/js/media.js'),'utf8');
  const bytes=fs.readFileSync(midi);
  async function setup(autoplay) {
    const dom=new JSDOM(fs.readFileSync(html,'utf8'),{runScripts:'outside-only',pretendToBeVisual:true});
    const w=dom.window;let sounds=0,observed=0,callback;
    w.NEON_MEDIA_PREFS={gif_mode:'system',midi_autoplay:autoplay};w.matchMedia=()=>({matches:false});
    w.HTMLCanvasElement.prototype.getContext=()=>({fillRect(){}});
    w.fetch=async()=>({ok:true,arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)});
    w.AudioContext=class {constructor(){sounds++;throw Error('Fixture audio deliberately blocked');}};
    w.IntersectionObserver=class {constructor(fn){callback=fn;}observe(){observed++;}};
    w.eval(source);await new Promise(resolve=>setTimeout(resolve,0));
    return {dom,w,sounds:()=>sounds,observed:()=>observed,intersect:()=>callback([{isIntersecting:true,intersectionRatio:1,target:w.document.querySelector('.midi-card')}])};
  }
  let x=await setup(0);
  assert.equal(x.sounds(),0);assert.equal(x.observed(),0,'Autoplay off does not register automatic playback');
  x.w.document.querySelector('.midi-play').click();await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(x.sounds(),1,'Explicit Play attempts sound');x.dom.window.close();
  x=await setup(1);assert.equal(x.sounds(),0);assert.equal(x.observed(),1,'Existing opt-in controls the Vibe MIDI widget');
  x.intersect();await new Promise(resolve=>setTimeout(resolve,0));assert.equal(x.sounds(),1);
  assert.match(x.w.document.querySelector('.midi-status').textContent,/Click Play/);
  x.intersect();await new Promise(resolve=>setTimeout(resolve,0));assert.equal(x.sounds(),1,'Blocked autoplay does not retry repeatedly');
  x.dom.window.close();
  console.log('Actual Vibe MIDI widget/player: default silence, explicit click, opt-in visibility and browser-blocked retry behavior passed');
} finally {fs.rmSync(dir,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
