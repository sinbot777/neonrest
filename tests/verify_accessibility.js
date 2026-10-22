// Exercise motion choices without a browser or changing any visitor preferences.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
let checks = 0;
function check(value) {assert.ok(value); checks++;}
function fixture({reduced=false, saved=false, nestedMain=false}={}) {
  const listeners={},motionListeners={},buttonListeners={},timers=new Map(),storage={};
  let next=0;
  const main={role:null,querySelector:()=>nestedMain, setAttribute(_,value){this.role=value;}};
  const footer={textContent:'Initial footer'};
  const button={hidden:true,textContent:'',disabled:false,title:'',addEventListener:(key,value)=>buttonListeners[key]=value};
  const document={hidden:false,getElementById:id=>({'main-content':main,'footer-tagline':footer,'footer-motion-toggle':button}[id]),addEventListener:(key,value)=>listeners[key]=value};
  const motion={matches:reduced,addEventListener:(key,value)=>motionListeners[key]=value};
  vm.runInNewContext(source,{document,window:{matchMedia:()=>motion},localStorage:{getItem:()=>saved?'1':'0',setItem:(key,value)=>storage[key]=value},setInterval:fn=>{timers.set(++next,fn);return next;},clearInterval:id=>timers.delete(id)});
  return {main,footer,button,document,motion,listeners,motionListeners,buttonListeners,timers,storage};
}
let f=fixture();
check(f.main.role==='main' && !f.button.hidden && f.timers.size===1);
f.timers.values().next().value();check(f.footer.textContent!=='Initial footer');
f.buttonListeners.click();check(f.timers.size===0 && f.button.textContent==='Rotate footer messages' && f.storage['neonrest-pause-footer']==='1');
f.buttonListeners.click();check(f.timers.size===1 && f.storage['neonrest-pause-footer']==='0');
f.document.hidden=true;f.listeners.visibilitychange();check(f.timers.size===0);
f.document.hidden=false;f.listeners.visibilitychange();check(f.timers.size===1);
f.motion.matches=true;f.motionListeners.change();check(f.timers.size===0 && f.button.disabled);
f.motion.matches=false;f.motionListeners.change();check(f.timers.size===1 && !f.button.disabled);
f=fixture({reduced:true});check(f.timers.size===0 && f.button.disabled);
f=fixture({saved:true});check(f.timers.size===0 && f.button.textContent==='Rotate footer messages');
f=fixture({nestedMain:true});check(f.main.role===null);
console.log('ACCESSIBILITY_MOTION_CHECKS',checks);
