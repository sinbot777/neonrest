/* Clipboard and FileList are native-browser adapters; the event handler is real. */
const {JSDOM}=require('jsdom'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const dom=new JSDOM('<form><input type="file"><textarea data-zine-image-paste></textarea><p data-zine-image-paste-status></p></form>',{runScripts:'outside-only'}),w=dom.window,d=w.document;let selected=[],submitted=0,checks=0;
w.DataTransfer=class{constructor(){this.files=[];this.items={add:file=>this.files.push(file)};}};
Object.defineProperty(d.querySelector('input'),'files',{set:value=>selected=value});d.querySelector('form').addEventListener('submit',()=>submitted++);
w.eval(fs.readFileSync(path.join(__dirname,'../static/zines_workspace.js'),'utf8'));
function paste(file){const e=new w.Event('paste',{bubbles:true,cancelable:true});Object.defineProperty(e,'clipboardData',{value:{files:[file]}});d.querySelector('textarea').dispatchEvent(e);return e;}
function check(ok,label){assert.ok(ok,label);checks++;}
const image=new w.File(['fixture'],'image.png',{type:'image/png'});check(paste(image).defaultPrevented,'Recognized image paste handled');check(selected[0]===image,'Pasted image selected in upload control');check(submitted===0,'Paste never automatically uploads');
selected=[];check(paste(new w.File([new Uint8Array(2*1024*1024+1)],'large.png',{type:'image/png'})).defaultPrevented,'Oversized image paste handled');check(selected.length===0&&d.querySelector('p').textContent.includes('2 MiB'),'Oversized paste rejected with explanation');check(!paste(new w.File(['text'],'text.txt',{type:'text/plain'})).defaultPrevented,'Ordinary clipboard text left alone');
console.log('PASS',checks,'artwork paste event checks');dom.window.close();
