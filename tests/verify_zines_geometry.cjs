'use strict';
const assert=require('node:assert/strict'),g=require('../static/zines_geometry.js');let checks=0;
const near=(a,b,label)=>{assert.ok(Math.abs(a-b)<.02,label+': '+a+' vs '+b);checks++;};
const block=(x,y,w=40,h=30)=>({x,y,w,h,rotation:0,locked:false});
let b=block(30,40);assert.deepEqual(g.bounds(b),{x:30,y:40,w:40,h:30});checks++;
b.rotation=90;near(g.bounds(b).w,30,'quarter-turn width');near(g.bounds(b).h,40,'quarter-turn height');
let items=[block(10,30),block(200,100)];g.translate(items,-200,700);near(items[0].x,0,'group left clamp');near(items[1].x-items[0].x,190,'relative x preserved');near(items[1].y+items[1].h,612,'group bottom clamp');near(items[1].y-items[0].y,70,'relative y preserved');
items=[block(20,30),block(100,200)];items[1].locked=true;const old=JSON.stringify(items);assert.equal(g.translate(items,10,10),false);assert.equal(JSON.stringify(items),old);checks+=2;
items=[block(10,20),block(130,150),block(270,300)];g.align(items,'left');for(const b of items)near(b.x,10,'selection left');g.align(items,'bottom',true);for(const b of items)near(b.y+b.h,588,'page bottom margin');
items=[block(10,20,30),block(90,80,50),block(280,200,40)];g.distribute(items,'horizontal');near(items[1].x-(items[0].x+items[0].w),items[2].x-(items[1].x+items[1].w),'equal horizontal gaps');near(items[0].x,10,'first stays');near(items[2].x,280,'last stays');
items=[block(10,20,30,30),block(90,80,50,90),block(280,400,40,40)];g.distribute(items,'vertical');near(items[1].y-(items[0].y+items[0].h),items[2].y-(items[1].y+items[1].h),'equal vertical gaps');
for(const rotation of [-180,-90,-45,0,30,90,180])for(const [w,h] of [[12,612],[396,612],[300,200]]){b=block(-10,800,w,h);b.rotation=rotation;g.fit(b);const bb=g.bounds(b);assert.ok(bb.x>=-.02&&bb.y>=-.02&&bb.x+bb.w<=396.02&&bb.y+bb.h<=612.02,JSON.stringify(b));checks++;}
console.log('PASS',checks,'composition geometry checks');
