/* Local recovery never submits a page or stores credentials. */
(()=>{'use strict';
const account=document.querySelector('[data-zine-atmosphere]')?.dataset.backdropPreference;
if(!account)return;
const exclude=new Set(['theme_csrf_token','revision','action','studio_action','item_id','page_id','workspace_tab','workspace_page']);
// Server JSON formatting and object key order do not constitute unsaved edits.
function fingerprint(values){
 const ordered=value=>Array.isArray(value)?value.map(ordered):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,ordered(value[key])])):value;
 const normalized={...values};
 if(typeof normalized.composition==='string')try{normalized.composition=JSON.parse(normalized.composition);}catch{}
 return JSON.stringify(ordered(normalized));
}
for(const [index,form] of [...document.querySelectorAll('form[data-zine-editor]')].entries()){
 const field=n=>form.elements.namedItem(n)?.value||'';
 const key='zine-recovery-v1:'+account+':'+location.pathname+':'+[field('action')||field('studio_action'),field('page_id')||field('item_id')||index].join(':');
 const revision=field('revision');
 const submissionKey='zine-recovery-v1:'+account+':'+location.pathname+':submitted';
 function read(){const values={};for(const el of form.elements){if(!el.name||exclude.has(el.name)||['file','submit','button'].includes(el.type))continue;if(el.type==='checkbox'){if(!values[el.name])values[el.name]=[];if(el.checked)values[el.name].push(el.value);}else values[el.name]=el.value;}return values;}
 const baseline=fingerprint(read());let timer,dirty=false,conflict=false,submitted=false;
 const bar=document.createElement('div');bar.className='zine-recovery-bar';
 const status=document.createElement('span');status.setAttribute('role','status');status.textContent='Local recovery ready · Save commits to Neonrest.';
 const restore=document.createElement('button'),discard=document.createElement('button');restore.type=discard.type='button';restore.textContent='Review recovered draft';discard.textContent='Discard recovery';restore.hidden=discard.hidden=true;bar.append(status,restore,discard);form.prepend(bar);
 let recovered;
 function stored(){try{const raw=localStorage.getItem(key);if(!raw)return null;if(raw.length>180000)return null;const value=JSON.parse(raw);return value&&value.version===1&&value.values&&typeof value.values==='object'&&!Array.isArray(value.values)?value:null;}catch{return null;}}
 // A successful add redirects from the new-page form to a different page form.
 // Clear only this tab's acknowledged submission, never another unsaved draft.
 try{
  const pending=JSON.parse(sessionStorage.getItem(submissionKey)||'null');
  const prefix='zine-recovery-v1:'+account+':'+location.pathname+':';
  if(new URLSearchParams(location.search).get('saved')==='1'&&pending&&typeof pending.key==='string'&&pending.key.startsWith(prefix)&&Number.isFinite(Number(pending.revision))&&Number(revision)>Number(pending.revision)){
   localStorage.removeItem(pending.key);sessionStorage.removeItem(pending.key+':pending');sessionStorage.removeItem(submissionKey);
  }
 }catch{}
 recovered=stored();
 try{if(new URLSearchParams(location.search).get('saved')==='1'&&sessionStorage.getItem(key+':pending')===recovered?.revision&&Number(revision)>Number(recovered.revision)){localStorage.removeItem(key);sessionStorage.removeItem(key+':pending');recovered=null;}}catch{}
 if(recovered&&fingerprint(recovered.values)!==baseline){status.textContent='An unsaved local draft is available'+(recovered.revision!==revision?' from a different server revision. Review before restoring.':'.');restore.hidden=discard.hidden=false;}else if(recovered){try{localStorage.removeItem(key);}catch{}}
 function save(){clearTimeout(timer);if(!dirty||conflict||!restore.hidden)return;try{const value={version:1,revision,at:Date.now(),values:read()};if(JSON.stringify(value).length>175000)throw Error();localStorage.setItem(key,JSON.stringify(value));status.textContent='Recovery saved in this browser at '+new Date().toLocaleTimeString()+'. Save commits to Neonrest.';discard.hidden=false;}catch{status.textContent='Local recovery unavailable. Save to Neonrest or copy your work before leaving.';}}
 const changed=e=>{if(e.target?.matches('[data-zc-preference],[data-zc-mode]'))return;dirty=true;submitted=false;if(recovered&&!restore.hidden){status.textContent='Existing recovery kept. Review or discard it before replacing it.';return;}clearTimeout(timer);timer=setTimeout(save,700);};
 form.addEventListener('input',changed);form.addEventListener('change',changed);
 form.addEventListener('submit',e=>{queueMicrotask(()=>{submitted=!e.defaultPrevented;dirty=true;save();if(submitted)try{sessionStorage.setItem(key+':pending',revision);sessionStorage.setItem(submissionKey,JSON.stringify({key,revision}));}catch{}});});
 const flush=()=>{if(dirty&&!conflict&&restore.hidden)save();};addEventListener('pagehide',flush);document.addEventListener('visibilitychange',()=>{if(document.hidden)flush();});
 addEventListener('beforeunload',e=>{if(dirty&&!submitted){e.preventDefault();e.returnValue='';}});
 addEventListener('storage',e=>{if(e.key===key&&e.newValue){conflict=true;status.textContent='Another tab changed this recovery. Save or copy your work; this tab will not overwrite its backup.';}});
 const dialog=document.createElement('dialog');dialog.setAttribute('aria-label','Review recovered draft');const title=document.createElement('h2');title.textContent='Review recovered draft';const note=document.createElement('p');note.textContent='Restoring changes this editor only. Save explicitly to commit to Neonrest. Current server revision is kept, so stale saves are still rejected.';const preview=document.createElement('textarea');preview.readOnly=true;preview.rows=12;preview.setAttribute('aria-label','Recovered draft contents');const accept=document.createElement('button'),cancel=document.createElement('button');accept.type=cancel.type='button';accept.textContent='Restore into editor';cancel.textContent='Cancel';dialog.append(title,note,preview,accept,cancel);document.body.append(dialog);
 restore.onclick=()=>{recovered=stored();if(!recovered)return;preview.value=JSON.stringify(recovered.values,null,2);dialog.showModal();};cancel.onclick=()=>dialog.close();
 accept.onclick=()=>{try{const values=recovered.values;const event=new CustomEvent('zine:recover',{detail:values,cancelable:true});if(!form.dispatchEvent(event))throw Error('Composition recovery was rejected. Copy the recovery text to preserve it.');for(const el of form.elements){if(!el.name||exclude.has(el.name)||!(el.name in values))continue;const value=values[el.name];if(el.type==='checkbox')el.checked=Array.isArray(value)&&value.includes(el.value);else if(typeof value==='string'&&el.type!=='file')el.value=value;}form.dispatchEvent(new Event('input',{bubbles:true}));form.querySelector('[name="design"]')?.dispatchEvent(new Event('change',{bubbles:true}));restore.hidden=true;conflict=false;dirty=true;save();dialog.close();status.textContent='Recovered into editor. Review your page, then Save to Neonrest.';}catch(err){status.textContent=err.message;}};
 discard.onclick=()=>{clearTimeout(timer);dirty=fingerprint(read())!==baseline;try{localStorage.removeItem(key);}catch{}recovered=null;restore.hidden=discard.hidden=true;conflict=false;status.textContent='Local recovery discarded. Current editor contents are unchanged.';};
}
})();
