const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFileSync}=require('node:child_process');
const {JSDOM}=require('jsdom');
const {validateThemeFile}=require('../static/js/theme-transfer.js');
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'neonrest-gallery-'));
try {
  execFileSync('python',[path.join(__dirname,'verify_theme_gallery.py')],{env:{...process.env,NEONREST_GALLERY_TEST_OUTPUT:dir}});
  const dom=new JSDOM(fs.readFileSync(path.join(dir,'detail.html'),'utf8'),{runScripts:'dangerously',url:'https://fixture.invalid/themes/gallery/fixture'});
  const w=dom.window;
  w.eval(fs.readFileSync(path.join(__dirname,'../static/js/theme-preview.js'),'utf8'));
  w.eval(fs.readFileSync(path.join(__dirname,'../static/js/theme-gallery-preview.js'),'utf8'));
  const frame=w.document.getElementById('gallery-theme-preview');
  assert.equal(frame.getAttribute('sandbox'),'');
  assert.match(frame.srcdoc,/default-src &apos;none&apos;/);
  assert.match(frame.srcdoc,/body.vibe-fixture--day/);
  const data=JSON.parse(fs.readFileSync(path.join(dir,'download.json'),'utf8'));
  const style=validateThemeFile(data,'day');
  assert.match(style.custom_css,/MIT License/);
  assert.match(style.custom_css,/Fixture Author/);
  assert.match(style.custom_css,/vibe-new-vibe--day/);
  dom.window.close();
  console.log('Actual gallery DOM: isolated preview and T20-compatible attributed remix download passed');
} finally {fs.rmSync(dir,{recursive:true,force:true});}
