'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const template = fs.readFileSync(process.argv[2] || path.join(__dirname,'../templates/marketplace_seller_shipping.html'),'utf8');
const script = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');
assert.ok(script.includes('function decimal'), 'unit conversion script is present');
function fixture(spec) {
  const nodes = Object.fromEntries(Object.entries(spec).map(([name,[value,base]]) => [name,{
    value, dataset:base===undefined?{}:{unitBase:base}, events:{},
    addEventListener(type,fn){(this.events[type] ||= []).push(fn);}
  }]));
  const form = {elements:{namedItem:name=>nodes[name] || null},events:{},
    addEventListener(type,fn){(this.events[type] ||= []).push(fn);}};
  vm.runInNewContext(script,{document:{querySelectorAll:()=>[form]}});
  return {nodes,change(name,value){nodes[name].value=value;for(const fn of nodes[name].events.change||[])fn();},
    submit(){for(const fn of form.events.submit||[])fn();}};
}
let checks=0;
function check(name,fn){fn();checks++;console.log('PASS',name);}
const parcel = ()=>fixture({distance_unit:['cm'],mass_unit:['g'],length:['16.51','165100'],
  width:['12.065','120650'],height:['0.635','6350'],packaging_weight:['2.835','2835']});
check('inch and millimetre switching preserves physical dimensions',()=>{
  const f=parcel();f.change('distance_unit','in');assert.equal(f.nodes.height.value,'0.25');
  assert.equal(f.nodes.length.value,'6.5');f.change('distance_unit','mm');
  assert.equal(f.nodes.height.value,'6.35');f.submit();assert.equal(f.nodes.height.value,'0.635');
});
check('repeated mass switches and submits preserve stored milligrams',()=>{
  const f=parcel();for(let i=0;i<20;i++){f.change('mass_unit','oz');f.change('mass_unit','lb');f.change('mass_unit','g');}
  f.change('mass_unit','oz');f.submit();f.submit();assert.equal(f.nodes.packaging_weight.value,'2.835');
});
check('smallest stored measurements survive rounded unit displays',()=>{
  const f=fixture({distance_unit:['cm'],mass_unit:['g'],length:['0.0001','1'],width:['0.0001','1'],
    height:['0.0001','1'],packaging_weight:['0.001','1']});
  f.change('distance_unit','in');f.change('mass_unit','lb');f.submit();
  assert.equal(f.nodes.length.value,'0.0001');assert.equal(f.nodes.packaging_weight.value,'0.001');
});
check('manual edits after switching units use the chosen unit',()=>{
  const f=parcel();f.change('distance_unit','in');f.nodes.height.value='0.5';f.submit();
  assert.equal(f.nodes.height.value,'1.27');
});
check('blank new presets can choose units before entering measurements',()=>{
  const f=fixture({distance_unit:['cm'],length:[''],width:[''],height:['']});f.change('distance_unit','in');
  f.nodes.length.value='6.5';f.nodes.width.value='4.75';f.nodes.height.value='2.5e-1';f.submit();
  assert.equal(f.nodes.length.value,'16.51');assert.equal(f.nodes.width.value,'12.065');assert.equal(f.nodes.height.value,'0.635');
});
check('variation weights round upward once to the supported milligram',()=>{
  const f=fixture({mass_unit:['g'],weight:['']});f.change('mass_unit','oz');f.nodes.weight.value='0.24';
  f.submit();assert.equal(f.nodes.weight.value,'6.804');f.change('mass_unit','lb');f.submit();
  assert.equal(f.nodes.weight.value,'6.804');
});
check('zero packaging and invalid input are not turned into positive measurements',()=>{
  const f=fixture({mass_unit:['g'],packaging_weight:['0','0']});f.change('mass_unit','oz');f.submit();
  assert.equal(f.nodes.packaging_weight.value,'0');f.nodes.packaging_weight.value='-1';f.change('mass_unit','lb');
  f.submit();assert.equal(f.nodes.packaging_weight.value,'-1');
});
console.log(checks,'shipping unit browser-script regressions passed');
