/* Selection is view state. Lock edits clone the page and preserve every other field. */
(function(scope){'use strict';
function find(page,selected,activeId,kind){
 const current=new Set(selected),active=page.blocks.find(b=>b.id===activeId&&current.has(b.id));let matches;
 if(kind==='invert')matches=b=>!current.has(b.id);
 else if(kind==='locked')matches=b=>b.locked===true;
 else if(kind==='unlocked')matches=b=>b.locked!==true;
 else{
  if(!active)throw Error('Select a reference element first.');
  if(kind==='type')matches=b=>b.type===active.type;
  else if(kind==='fill')matches=b=>b.fill===active.fill;
  else if(kind==='color'){if(!['text','rule'].includes(active.type))throw Error('Select text or a rule to match its color.');matches=b=>['text','rule'].includes(b.type)&&b.color===active.color;}
  else if(kind==='font'){
   if(active.type!=='text')throw Error('Select a text element to match its formatting.');
   const keys=['font','size','leading','align'];matches=b=>b.type==='text'&&keys.every(k=>b[k]===active[k]);
  }else if(kind==='image'){
   if(active.type!=='image'||!active.image)throw Error('Select an image frame with artwork first.');
   matches=b=>b.type==='image'&&b.image===active.image;
  }else throw Error('Unsupported selection command.');
 }
 return page.blocks.filter(matches).map(b=>b.id);
}
function setLocked(page,selected,locked){
 if(typeof locked!=='boolean')throw Error('Choose a valid lock state.');
 const ids=new Set(selected);if(!page.blocks.some(b=>ids.has(b.id)))throw Error('Select elements to lock or unlock.');
 const next=JSON.parse(JSON.stringify(page));for(const b of next.blocks)if(ids.has(b.id))b.locked=locked;return next;
}
const api=Object.freeze({find,setLocked});if(typeof module!=='undefined'&&module.exports)module.exports=api;else scope.ZineSelection=api;
})(typeof window!=='undefined'?window:this);
