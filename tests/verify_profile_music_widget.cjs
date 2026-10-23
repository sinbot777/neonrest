const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync(__dirname+'/../static/js/profile_now_playing.js','utf8');
let checks=0;
async function run(payload,fail=false){
 const make=()=>({textContent:'',children:[],style:{},addEventListener(name, fn){this[name]=fn;},replaceChildren(...nodes){this.children=nodes;this.textContent=nodes.map(n=>n.textContent).join('');}});
 const text=make(),art=make(),label=make();text.textContent='Loading music…';text.dataset={nowPlayingUrl:'/sandbox/now_playing/fictional'};
 let resolve,reject,calls=0;const pending=new Promise((a,b)=>{resolve=a;reject=b;});
 const context={document:{getElementById:id=>id==='now-playing-text'?text:id==='now-playing-label'?label:art,createElement:make},location:{origin:'https://www.neonrest.com'},URL,AbortController,setTimeout,clearTimeout,fetch:(url)=>{calls++;assert.equal(url,'https://www.neonrest.com/sandbox/now_playing/fictional');return pending;}};
 vm.runInNewContext(code,context);assert.equal(calls,1);assert.equal(text.textContent,'Loading music…');checks+=2;
 if(fail)reject(new Error('Simulated offline'));else resolve({ok:true,redirected:false,json:async()=>payload});
 await new Promise(r=>setImmediate(r));return{text,art,label};
}
(async()=>{
 let r=await run({is_now_playing:true,track:'Artist <script> – Song',url:'https://www.last.fm/music/test',album_art:'https://example.invalid/art.png'});assert.equal(r.text.children[0].textContent,'Artist <script> – Song');assert.equal(r.text.children[0].rel,'noopener noreferrer');assert.equal(r.art.children.length,1);assert.equal(r.label.textContent,'Now playing'); r.art.children[0].error(); assert.equal(r.art.children.length,0);checks+=5;
 r=await run({track:'Plain text',url:'javascript:alert(1)',album_art:'data:image/svg+xml,<svg/>'});assert.equal(r.label.textContent,'Last played');checks++;assert.equal(r.text.textContent,'Plain text');assert.equal(r.text.children.length,0);assert.equal(r.art.children.length,0);checks+=3;
 r=await run({track:null});assert.equal(r.text.textContent,'No recent track available.');checks++;
 r=await run(null,true);assert.equal(r.text.textContent,'Music temporarily unavailable.');checks++;
 console.log(JSON.stringify({checks,passed:true}));
})();

