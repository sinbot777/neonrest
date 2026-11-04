'use strict';
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
function fixture(file, options = {}) {
  let now = 1000000, sequence = 0, inflight = 0, maxInflight = 0;
  let key = options.key || '', failure = options.failure;
  const jobs = new Map(), requests = [], listeners = {}, logListeners = {};
  const badges = [{textContent:'7',hidden:false}];
  const data = {csrf:'synthetic',updatesUrl:'/updates',readUrl:'/read',presenceUrl:'/presence',overviewUrl:'/overview',state:'accepted',presence:'available',sidebar:'yes'};
  const app = {dataset:data};
  const log = {scrollTop:0,scrollHeight:100,clientHeight:100,querySelector:selector => selector.includes('last-of-type') && key ? {dataset:{messageKey:key}} : null,addEventListener:(name,fn)=>logListeners[name]=fn};
  const document = {visibilityState:'visible',getElementById:id => ({'dm-app':app,'dm-log':log,'dm-live-status':{}}[id] || null),querySelector:()=>null,querySelectorAll:s => s === '[data-message-badge]' ? badges : [],addEventListener:(name,fn)=>listeners[name]=fn};
  const timers = {setTimeout:(fn,delay=0)=>{const id=++sequence;jobs.set(id,{at:now+Math.max(0,delay),fn});return id;},clearTimeout:id=>jobs.delete(id)};
  function fetch(url,opts={}) {
    const path = new URL(url,'https://example.test').pathname;
    requests.push({at:now,path,url:String(url),body:opts.body?.toString()});
    inflight++;maxInflight=Math.max(inflight,maxInflight);
    return new Promise((resolve,reject)=>{
      let settled=false;
      const finish = (error) => {
        if(settled)return;settled=true;inflight--;
        if(error){reject(error);return;}
        const code = typeof failure === 'function' ? failure(path,requests.length) : failure || 200;
        resolve({ok:code>=200&&code<300,status:code,redirected:false,headers:{get:name=>name==='Content-Type'?'application/json':name==='Retry-After'?options.retryAfter || null:null},json:async()=>({messages:[],removed:[],more:false,state:'accepted',can_send:true,unread:path==='/updates'&&String(url).includes('badge=0')?null:0,notifications:0,buddies:[]})});
      };
      const id=timers.setTimeout(()=>finish(),options.latency ?? 10);
      opts.signal?.addEventListener('abort',()=>{timers.clearTimeout(id);finish(Error('Aborted'));},{once:true});
    });
  }
  const FakeDate = class extends Date {static now(){return now;}};
  const window = {addEventListener:(name,fn)=>listeners[name]=fn};
  const context = {document,window,Date:FakeDate,URL,URLSearchParams,AbortController,fetch,location:{origin:'https://example.test',reload:()=>{throw Error('unexpected reload');}},...timers,setInterval:(fn,delay)=>{function repeat(){fn();timers.setTimeout(repeat,delay);}timers.setTimeout(repeat,delay);}};
  vm.runInNewContext(fs.readFileSync(file,'utf8'),context,{filename:file});
  async function settle(){for(let i=0;i<25;i++)await Promise.resolve();}
  async function advance(ms){const end=now+ms;for(let n=0;n<10000;n++){await settle();let next;for(const [id,job] of jobs){if(job.at<=end&&(!next||job.at<next[1].at))next=[id,job];}if(!next){now=end;await settle();return;}now=next[1].at;jobs.delete(next[0]);next[1].fn();}throw Error('timer runaway');}
  return {requests,badges,advance,get maxInflight(){return maxInflight;},setKey:value=>key=value,setFailure:value=>failure=value,scroll:()=>logListeners.scroll(),hide:()=>{document.visibilityState='hidden';listeners.visibilitychange();},show:()=>{document.visibilityState='visible';listeners.visibilitychange();},activity:()=>listeners.keydown?.(),pagehide:()=>listeners.pagehide?.(),pageshow:()=>listeners.pageshow?.()};
}
(async()=>{
 const checks=[];const ok=(condition,label)=>{assert.ok(condition,label);checks.push(label);};
 const v1=fixture(__dirname+'/fixtures/afterglow-v1.js'),v2=fixture(__dirname+'/../static/js/messaging.js');await v1.advance(180000);await v2.advance(180000);
 const counts=f=>Object.fromEntries(['/updates','/read','/presence','/overview'].map(path=>[path,f.requests.filter(r=>r.path===path).length]));
 ok(counts(v2)['/updates'] < counts(v1)['/updates']*.65,'Idle conversation substantially reduces update checks');
 ok(v2.maxInflight===1,'Background requests are serialized');
 ok(v2.requests.filter(r=>r.path==='/updates').every(r=>r.url.includes('badge=0')),'Update checks omit redundant badge count');
 ok(v2.badges[0].textContent==='0','Null update badge does not erase valid overview badge');
 const idleCounts={v1:counts(v1),v2:counts(v2)};
 const idleCount=v2.requests.length;v2.hide();await v2.advance(60000);ok(v2.requests.length===idleCount,'Hidden tab sends no periodic requests');
 v2.show();await v2.advance(100);ok(v2.requests.length>idleCount,'Visible tab resumes promptly');
 const slow=fixture(__dirname+'/../static/js/messaging.js',{latency:3000,key:'abcdefghijklmnop'});for(let i=0;i<30;i++)slow.scroll();await slow.advance(1100);for(let i=0;i<30;i++)slow.scroll();await slow.advance(5000);
 ok(slow.requests.filter(r=>r.path==='/read').length===1,'Scroll bursts coalesce into one receipt');ok(slow.maxInflight===1,'Slow receipt does not overlap background requests');
 const continuous=fixture(__dirname+'/../static/js/messaging.js',{key:'abcdefghijklmnop'});for(let i=0;i<25;i++){continuous.scroll();await continuous.advance(100);}ok(continuous.requests.some(r=>r.path==='/read'),'Continuous scrolling cannot postpone receipt indefinitely');
 const retry=fixture(__dirname+'/../static/js/messaging.js',{failure:429,retryAfter:'30'});await retry.advance(29000);ok(retry.requests.length===1,'Rate limit respects Retry-After across background tasks');await retry.advance(2000);ok(retry.requests.length===2,'Rate-limited update retries after delay');retry.setFailure(200);await retry.advance(35000);ok(retry.requests.length>2,'Background checks recover after rate limit');
 const broken=fixture(__dirname+'/../static/js/messaging.js',{failure:503});await broken.advance(60000);ok(broken.requests.length<=5,'Repeated server errors back off');
 const hung=fixture(__dirname+'/../static/js/messaging.js',{latency:999999});await hung.advance(21000);ok(hung.requests.length===1,'Hung request times out without overlapping a replacement');await hung.advance(7000);ok(hung.requests.length===2,'Timeout eventually retries');
 const receiptRetry=fixture(__dirname+'/../static/js/messaging.js',{key:'abcdefghijklmnop',failure:path=>path==='/read'?503:200});await receiptRetry.advance(25000);ok(receiptRetry.requests.filter(r=>r.path==='/read').length<=3,'Failed receipt obeys shared backoff');receiptRetry.setFailure(200);await receiptRetry.advance(60000);ok(receiptRetry.requests.filter(r=>r.path==='/read').length>=2,'Pending receipt survives transient error');
 const stop=fixture(__dirname+'/../static/js/messaging.js');await stop.advance(100);stop.pagehide();const stopCount=stop.requests.length;await stop.advance(60000);ok(stop.requests.length===stopCount,'Page departure stops future checks');stop.pageshow();await stop.advance(100);ok(stop.requests.length>stopCount,'Back-forward restore resumes checks');
 const result={complete:true,scope:'Deterministic Node VM with fake DOM, clock, and network; actual messaging.js candidate executed. Not a native browser or live network benchmark.',checks,simulated_idle_180_seconds:{...idleCounts,v2_max_concurrent_background:v2.maxInflight}};
 fs.writeFileSync(__dirname+'/scheduler-results.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});
