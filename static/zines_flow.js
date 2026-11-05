/* Anchored figures remain plain structured content, never user HTML. */
(function(scope){
'use strict';
const chars=s=>Array.from(s);
function render(el,b,assets,onload){
 el.classList.add('zc-flow-text');let start=0;const text=chars(b.text);
 for(const image of b.insets||[]){
  el.append(document.createTextNode(text.slice(start,image.at).join('')));start=image.at;
  const figure=document.createElement('span');figure.className='zc-inline-figure zc-flow-'+image.mode;
  const percent=image.mode==='full'?100:image.width;figure.style.width='calc('+percent+'% - '+(2*image.gap*percent/100/396*100)+'cqw)';figure.style.setProperty('--zc-flow-gap',image.gap/396*100+'cqw');
  const art=document.createElement('img');art.alt=image.alt;art.draggable=false;art.style.height=image.height/396*100+'cqw';
  if(assets.has(image.image)){art.src=assets.get(image.image);if(onload)art.addEventListener('load',onload,{once:true});}
  else {art.alt=image.alt||'Select artwork';figure.classList.add('zc-placeholder');}
  figure.append(art);
  if(image.caption||image.credit){const caption=document.createElement('span');caption.className='zc-inline-caption';caption.textContent=[image.caption,image.credit].filter(Boolean).join('\n');figure.append(caption);}
  el.append(figure);
 }
 el.append(document.createTextNode(text.slice(start).join('')));
}
function moveAnchors(oldText,newText,images){
 const before=chars(oldText),after=chars(newText);let prefix=0,suffix=0;
 while(prefix<before.length&&prefix<after.length&&before[prefix]===after[prefix])prefix++;
 while(suffix<before.length-prefix&&suffix<after.length-prefix&&before[before.length-1-suffix]===after[after.length-1-suffix])suffix++;
 const end=before.length-suffix,delta=after.length-before.length;
 for(const image of images||[])image.at=image.at<=prefix?image.at:image.at>=end?image.at+delta:prefix;
}
function validate(images,b,assets){
 if(!Array.isArray(images)||images.length>6)throw Error('Use at most six images per text frame.');
 let previous=0;
 for(const i of images){
  if(!i||Object.getPrototypeOf(i)!==Object.prototype||Object.keys(i).some(k=>!['at','image','alt','mode','width','height','gap','caption','credit'].includes(k)))throw Error('Unsupported anchored image.');
  if(!Number.isInteger(i.at)||i.at<previous||i.at>chars(b.text).length)throw Error('Place images within the text in order.');previous=i.at;
  if(typeof i.image!=='string'||i.image.length>60||i.image&&!assets.has(i.image))throw Error('Choose artwork from this publication.');
  if(!['inline','wrap-left','wrap-right','full'].includes(i.mode))throw Error('Choose a supported image placement.');
  for(const [key,max] of [['alt',300],['caption',200],['credit',160]])if(typeof i[key]!=='string'||i[key].length>max)throw Error('Image '+key+' is too long.');
  for(const [key,min,max] of [['width',5,100],['height',6,180],['gap',0,24]])if(typeof i[key]!=='number'||!Number.isFinite(i[key])||i[key]<min||i[key]>max)throw Error('Image '+key+' is outside its allowed range.');
 }
}
scope.ZineFlow={render,moveAnchors,validate};
})(window);
