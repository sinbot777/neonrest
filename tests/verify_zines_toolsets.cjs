'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const policy=require('../static/zines_toolsets.js');
let checks=0;
const check=(value,message)=>{assert.ok(value,message);checks++;};
const chosen=['layers','precision'];
for(const tool of policy.tools){
 check(!policy.visible('standard',chosen,tool),'Standard hides optional group '+tool);
 check(policy.visible('advanced',[],tool),'Advanced includes every group '+tool);
 check(policy.visible('custom',chosen,tool)===chosen.includes(tool),'Custom honors chosen group '+tool);
}
for(const mode of ['standard','custom','advanced'])check(policy.visible(mode,[],null),'Core tools available in '+mode);
const raw={mode:'custom',tools:['layers','unknown','layers','portable'],page:{text:'must not become a preference'}};
const restored=policy.preferences(JSON.parse(JSON.stringify(raw)));
check(restored.mode==='custom','Custom mode restored');
assert.deepEqual(restored.tools,['layers','portable']);checks++;
check(!('page' in restored),'Page content excluded from preference data');
check(policy.preferences({mode:'administrator',tools:'all'}).mode==='standard','Unknown mode falls back');
check(policy.preferences(null).tools.length===0,'Custom begins with core tools');
check(policy.preferences({mode:'advanced',tools:[]}).mode==='advanced','Advanced does not depend on Custom selection');
const page={version:1,background:'#ffffff',blocks:[{id:'one',type:'text',text:'Preserve me',size:42,x:27,y:62,w:310,h:120,locked:true}]};
const before=JSON.stringify(page);
for(const mode of ['advanced','standard','custom','standard','advanced'])for(const tool of policy.tools)policy.visible(mode,chosen,tool);
check(JSON.stringify(page)===before,'Changing visibility never converts or resets content');
const html=fs.readFileSync(require('node:path').join(__dirname,'../templates/zines.html'),'utf8');
for(const tool of policy.tools)check(html.includes('data-tool="'+tool+'"'),'Selectable group exists in actual UI: '+tool);
check(html.includes('data-preference-key="neonrest-zine-tools-v1-{{ session.user_id }}"'),'Preferences scoped to signed-in account');
console.log('PASS',checks,'toolset preference and visibility checks');
