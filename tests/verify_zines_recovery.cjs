/* Exercise the real recovery script with a minimal DOM/storage adapter. */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../static/zines_recovery.js'),'utf8');
function run(server,local,extra={}){
 const created=[];
 const element=()=>({children:[],hidden:false,textContent:'',append(...es){this.children.push(...es);},setAttribute(){},addEventListener(){}});
 const fields=Object.entries({revision:'2',action:'save_page',page_id:'qa',composition:server,heading:'QA'}).map(([name,value])=>({name,value,type:'text'}));
 fields.namedItem=name=>fields.find(e=>e.name===name);
 const form={elements:fields,prepend(){},addEventListener(){}};
 const key='zine-recovery-v1:qa:/sandbox/zines/qa/edit:save_page:qa';
 const storage=new Map([[key,JSON.stringify({version:1,revision:'1',values:{composition:local,heading:'QA',...extra}})]]);
 const document={querySelector:()=>({dataset:{backdropPreference:'qa'}}),querySelectorAll:()=>[form],createElement:()=>{const e=element();created.push(e);return e;},addEventListener(){},body:{append(){}}};
 vm.runInNewContext(source,{document,location:{pathname:'/sandbox/zines/qa/edit',search:''},localStorage:{getItem:k=>storage.get(k)||null,removeItem:k=>storage.delete(k)},sessionStorage:{getItem:()=>null},URLSearchParams,addEventListener(){},clearTimeout(){},setTimeout(){},queueMicrotask});
 return {status:created[1].textContent,restore:created[2],storage,key};
}
let checks=0;
function check(ok,label){assert.ok(ok,label);checks++;}
const compact='{"version":1,"blocks":[{"text":"Keep  two spaces","x":24,"insets":[{"at":0,"mode":"inline"}]}]}';
const formatted=JSON.stringify({blocks:[{insets:[{mode:'inline',at:0}],x:24,text:'Keep  two spaces'}],version:1},null,2);
let result=run(formatted,compact);
check(result.restore.hidden,'Formatting and object key order do not trigger recovery');
check(!result.storage.has(result.key),'Equivalent stale recovery is removed');
result=run(formatted,compact.replace('24','25'));
check(!result.restore.hidden,'Real position change remains recoverable');
check(result.storage.has(result.key),'Different content is preserved');
check(result.status.includes('different server revision'),'Stale revision warning remains');
check(!run(formatted,compact.replace('Keep  two','Keep two')).restore.hidden,'Text whitespace remains significant');
check(!run('{"blocks":[1,2]}','{"blocks":[2,1]}').restore.hidden,'Array order remains significant');
check(!run(formatted,'{invalid').restore.hidden,'Malformed JSON remains recoverable');
check(!run(formatted,compact,{heading:'Changed title'}).restore.hidden,'Non-composition fields remain significant');
check(run('', '').restore.hidden,'Empty legacy composition still compares correctly');
console.log('PASS',checks,'recovery regression checks');
