/* Install jsdom outside the repository, then set NODE_PATH to that node_modules. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {JSDOM} = require('jsdom');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'neonrest-theme-'));
(async () => {
try {
  const html = path.join(dir,'editor.html');
  execFileSync('python',[path.join(__dirname,'verify_theme_restoration.py')],
    {env:{...process.env,NEONREST_THEME_TEST_HTML:html}});
  const dom = new JSDOM(fs.readFileSync(html,'utf8'),
    {runScripts:'dangerously',url:'https://fixture.invalid/themes/edit/fixture/day'});
  const w=dom.window, d=w.document;
  assert.doesNotMatch(d.title, /<script|theme-history|theme-preview/, 'Studio tab title contains only its title');
  w.eval(fs.readFileSync(path.join(__dirname,'../static/js/theme-visual-colors.js'),'utf8'));
  w.eval(fs.readFileSync(path.join(__dirname,'../static/js/theme-history.js'),'utf8'));
  const css=d.getElementById('custom_css'), original=css.value;
  const undo=d.getElementById('theme-undo'), redo=d.getElementById('theme-redo');
  assert.equal(undo.disabled,true);
  css.value='edited';css.dispatchEvent(new w.Event('input',{bubbles:true}));
  assert.equal(undo.disabled,false);
  let unload=new w.Event('beforeunload',{cancelable:true});w.dispatchEvent(unload);
  assert.equal(unload.defaultPrevented,true,'Unsaved navigation is guarded');
  d.querySelector('.studio-vibe-picker').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  unload=new w.Event('beforeunload',{cancelable:true});w.dispatchEvent(unload);
  assert.equal(unload.defaultPrevented,true,'Vibe switching retains dirty-navigation guard');
  undo.click();assert.equal(css.value,original);
  redo.click();assert.equal(css.value,'edited');
  const nullBg=d.querySelector('[name="null_bg_color"]');
  assert.equal(nullBg.checked,true);
  const bg=d.getElementById('bg_color');bg.value='#123456';bg.dispatchEvent(new w.Event('input',{bubbles:true}));
  assert.equal(nullBg.checked,false);
  undo.click();assert.equal(nullBg.checked,true,'Undo preserves Unset');
  redo.click();assert.equal(bg.value,'#123456');
  d.getElementById('theme-discard').click();
  assert.equal(css.value,original);assert.equal(nullBg.checked,true);
  assert.equal(d.getElementById('theme-discard').disabled,true);
  undo.click();assert.equal(css.value,'edited','Discard can be undone');
  css.selectionStart=0;css.selectionEnd=0;
  css.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));
  assert.equal(css.value,'  edited');undo.click();assert.equal(css.value,'edited','Tab indentation joins undo history');
  assert.match(d.getElementById('vibe-contrast-warning').textContent,/Contrast check|Text contrast/);
  assert.equal(d.querySelectorAll('#theme-editor-form [name="theme_csrf_token"]').length,1);
  const panel=d.getElementById('visual-panel');
  panel.value='#123456';panel.dispatchEvent(new w.Event('input',{bubbles:true}));
  assert.match(css.value,/--vibe-panel: #123456/);
  undo.click();assert.equal(css.value,'edited','Visual color is one undoable CSS edit');
  assert.equal(panel.closest('[data-visual-color]').querySelector('[type="checkbox"]').checked,true);
  w.eval(fs.readFileSync(path.join(__dirname,'../static/js/theme-transfer.js'),'utf8'));
  w.eval(fs.readFileSync(path.join(__dirname,'../static/js/theme-preview.js'),'utf8'));
  const file=d.getElementById('theme-import');
  async function importData(data) {
    const text=JSON.stringify(data);
    Object.defineProperty(file,'files',{configurable:true,value:[{size:text.length,text:async()=>text}]});
    file.dispatchEvent(new w.Event('change',{bubbles:true}));
    await new Promise(resolve=>setTimeout(resolve,0));
  }
  await importData({format:'neonrest-theme',version:1,mode:'day',style:{custom_css:'imported CSS',bg_color:null,font_stack:null}});
  assert.equal(css.value,'imported CSS');assert.equal(nullBg.checked,true);
  assert.equal(d.getElementById('font_stack').value,'','Null font clears to inheritance');
  undo.click();assert.equal(css.value,'edited','Entire import is one undo operation');
  redo.click();assert.equal(css.value,'imported CSS');
  assert.match(d.getElementById('theme-live-preview').srcdoc,/imported CSS/);
  assert.equal(d.getElementById('theme-live-preview').getAttribute('sandbox'),'');
  await importData({format:'neonrest-theme',version:1,mode:'night',style:{custom_css:'wrong mode'}});
  assert.equal(css.value,'imported CSS','Invalid import changes nothing');
  assert.match(d.getElementById('theme-transfer-status').textContent,/Import failed/);
  let exported;
  w.Blob=Blob;w.URL.createObjectURL=blob=>{exported=blob;return 'blob:fixture'};w.URL.revokeObjectURL=()=>{};
  d.addEventListener('click',event=>{if(event.target.tagName==='A')event.preventDefault();});
  d.getElementById('theme-export').click();
  const result=JSON.parse(await exported.text());
  assert.equal(result.style.custom_css,'imported CSS');assert.equal(result.style.bg_color,null);
  assert.equal(result.mode,'day');assert.equal('theme_csrf_token' in result.style,false);
  assert.equal('logo_url' in result.style,false,'Shared identity excluded');
  dom.window.close();
  console.log('Actual editor DOM: undo/redo/discard/null colors/Tab/navigation/contrast/CSRF passed');
} finally { fs.rmSync(dir,{recursive:true,force:true}); }

})().catch(error=>{console.error(error);process.exitCode=1;});
