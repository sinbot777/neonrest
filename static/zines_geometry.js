/* Shared, side-effect-free composition geometry. Logical units are points. */
(function(scope){
'use strict';
const W=396,H=612;
function bounds(b){const a=(b.rotation||0)*Math.PI/180,c=Math.abs(Math.cos(a)),s=Math.abs(Math.sin(a)),w=b.w*c+b.h*s,h=b.w*s+b.h*c;return {x:b.x+b.w/2-w/2,y:b.y+b.h/2-h/2,w,h};}
function union(blocks){if(!blocks.length)return null;const bb=blocks.map(bounds),x=Math.min(...bb.map(b=>b.x)),y=Math.min(...bb.map(b=>b.y));return {x,y,w:Math.max(...bb.map(b=>b.x+b.w))-x,h:Math.max(...bb.map(b=>b.y+b.h))-y};}
function translate(blocks,dx,dy){const bb=union(blocks);if(!bb||blocks.some(b=>b.locked))return false;dx=Math.min(W-bb.x-bb.w,Math.max(-bb.x,dx));dy=Math.min(H-bb.y-bb.h,Math.max(-bb.y,dy));for(const b of blocks){b.x=+(b.x+dx).toFixed(4);b.y=+(b.y+dy).toFixed(4);}return true;}
function align(blocks,kind,toPage=false){if(!blocks.length||blocks.some(b=>b.locked))return false;const bb=toPage?{x:24,y:24,w:348,h:564}:union(blocks);for(const b of blocks){const r=bounds(b);let dx=0,dy=0;if(kind==='left')dx=bb.x-r.x;if(kind==='center')dx=bb.x+bb.w/2-r.x-r.w/2;if(kind==='right')dx=bb.x+bb.w-r.x-r.w;if(kind==='top')dy=bb.y-r.y;if(kind==='middle')dy=bb.y+bb.h/2-r.y-r.h/2;if(kind==='bottom')dy=bb.y+bb.h-r.y-r.h;translate([b],dx,dy);}return true;}
function distribute(blocks,axis){if(blocks.length<3||blocks.some(b=>b.locked))return false;const key=axis==='horizontal'?'x':'y',dim=key==='x'?'w':'h',items=[...blocks].sort((a,b)=>bounds(a)[key]-bounds(b)[key]);const start=bounds(items[0])[key],last=bounds(items.at(-1)),end=last[key]+last[dim],gap=(end-start-items.reduce((v,b)=>v+bounds(b)[dim],0))/(items.length-1);let pos=start;for(const b of items){const bb=bounds(b),d=pos-bb[key];translate([b],key==='x'?d:0,key==='y'?d:0);pos+=bb[dim]+gap;}return true;}
function fit(b){b.w=Math.min(W,Math.max(12,Number(b.w)||12));b.h=Math.min(H,Math.max(12,Number(b.h)||12));let bb=bounds(b);if(bb.w>W||bb.h>H){const factor=Math.min(W/bb.w,H/bb.h);b.w=Math.max(12,b.w*factor);b.h=Math.max(12,b.h*factor);bb=bounds(b);if(bb.w>W+.001||bb.h>H+.001)b.rotation=0;}
 b.x=Math.max(0,Math.min(W-b.w,Number(b.x)||0));b.y=Math.max(0,Math.min(H-b.h,Number(b.y)||0));bb=bounds(b);b.x+=Math.max(0,-bb.x)-Math.max(0,bb.x+bb.w-W);b.y+=Math.max(0,-bb.y)-Math.max(0,bb.y+bb.h-H);for(const k of ['x','y','w','h'])b[k]=+b[k].toFixed(4);return b;}
const api=Object.freeze({bounds,union,translate,align,distribute,fit});if(typeof module!=='undefined'&&module.exports)module.exports=api;else scope.ZineGeometry=api;
})(typeof window!=='undefined'?window:this);
