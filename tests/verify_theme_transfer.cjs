const assert=require('node:assert/strict');
const {validateThemeFile}=require('../static/js/theme-transfer.js');
const valid=style=>({format:'neonrest-theme',version:1,mode:'day',style});
assert.deepEqual(validateThemeFile(valid({custom_css:'body { color: red; }',bg_color:null}),'day'),{custom_css:'body { color: red; }',bg_color:null});
assert.deepEqual(validateThemeFile(valid({}),'day'),{},'Missing fields preserved by importer');
for(const data of [null,[],{},valid({bg_color:12}),valid({bg_color:'red'}),valid({custom_css:'x'.repeat(100001)}),valid({unknown:'bad'}),valid({custom_css:'</style><script>alert(1)</script>'}),JSON.parse('{"format":"neonrest-theme","version":1,"mode":"day","style":{"__proto__":{}}}')])
  assert.throws(()=>validateThemeFile(data,'day'));
assert.throws(()=>validateThemeFile(valid({}),'night'),'Mode mismatch refused');
assert.deepEqual(validateThemeFile(valid({font_stack:null,bg_color:'#abc'}),'day'),{font_stack:null,bg_color:'#abc'});
console.log('Theme transfer schema/types/limits/null/missing fields/mode/HTML/unknown keys passed');
