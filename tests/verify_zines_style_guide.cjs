/* Actual rendered controls: previews must never rewrite or submit page content. */
const {JSDOM}=require('jsdom'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const dom=new JSDOM(fs.readFileSync('/tmp/zine-dom-fixture.html','utf8'),{url:'https://example.test/editor',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window,d=w.document;let checks=0,submits=0;
for(const f of ['zines_toolsets.js','zines_geometry.js','zines_workspace.js','zines_flow.js','zines_composer.js','zines_style_guide.js'])w.eval(fs.readFileSync(path.join(__dirname,'../static',f),'utf8'));
const guide=d.querySelector('[data-style-guide]'),form=guide.closest('form'),q=s=>guide.querySelector(s),check=(ok,label)=>{assert.ok(ok,label);checks++;};form.addEventListener('submit',()=>submits++);
const content=form.querySelector('[data-zc-json]').value;
function change(name,value,type='input'){form.elements.namedItem(name).value=value;form.elements.namedItem(name).dispatchEvent(new w.Event(type,{bubbles:true}));}
const tick=()=>new Promise(resolve=>w.requestAnimationFrame(resolve));
(async()=>{
 change('design','punk','change');change('accent','forest','change');change('highlight','42');change('highlight_label','Readers');change('pullquote','<img src=x onerror=alert(1)>');await tick();
 check(!q('[data-style-sample="punk"]').hidden&&q('[data-style-sample="classic"]').hidden,'Selection shows matching example');check(q('.zine-art-punk').classList.contains('zine-accent-forest'),'Accent visible in actual Punk example');check(q('.punk-highlight').textContent==='42'&&q('.punk-highlight-label').textContent==='Readers','Highlight and label update');check(!q('.punk-pullquote img')&&q('.punk-pullquote').textContent.includes('<img'),'User text remains literal');
 change('design','classic','change');await tick();check(q('[data-style-help]').textContent.includes('do not affect Classic'),'Inactive preset controls explained');check(form.elements.namedItem('section').closest('label').classList.contains('zine-style-unused'),'Unused graphic controls indicated');
 change('design','composition','change');await tick();check(q('[data-style-composition] .zc-page'),'Composition uses actual canvas snapshot');check(!q('[data-style-composition] .zc-resize'),'Preview removes editor handles');check(form.querySelector('[data-zc-json]').value===content,'Style previews preserve composition data');
 q('[data-style-zoom]').click();check(guide.classList.contains('zine-style-expanded'),'Example enlarges without saving');check(submits===0,'Preview never submits the page');
 for(const kind of ['cover','back']){
  const sample=new JSDOM(fs.readFileSync('/tmp/zine-style-'+kind+'.html','utf8'),{runScripts:'outside-only',pretendToBeVisual:true}),sw=sample.window,sg=sw.document.querySelector('[data-style-guide]'),sf=sg.closest('form');sw.eval(fs.readFileSync(path.join(__dirname,'../static/zines_style_guide.js'),'utf8'));sf.elements.namedItem('design').value='punk';sf.elements.namedItem('design').dispatchEvent(new sw.Event('change',{bubbles:true}));await new Promise(resolve=>sw.requestAnimationFrame(resolve));
  check(sg.querySelector('[data-style-effect]').textContent.includes(kind==='cover'?'Front cover:':'Back cover:'),'Correct cover explanation '+kind);check(sf.elements.namedItem('highlight').closest('label').classList.contains('zine-style-unused'),'Cover highlight marked unused '+kind);sample.window.close();
 }
 console.log('PASS',checks,'style explanation and preview checks');dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1;dom.window.close();});
