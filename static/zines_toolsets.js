/* Tool visibility is an editor preference, never a page-content conversion. */
(function (scope) {
 'use strict';
 const tools = Object.freeze(['shapes','layers','typography','precision','snapping','portable']);
 function preferences(raw) {
  const value=raw&&typeof raw==='object'?raw:{};
  return {mode:['standard','custom','advanced'].includes(value.mode)?value.mode:'standard',tools:tools.filter(tool=>Array.isArray(value.tools)&&value.tools.includes(tool))};
 }
 function visible(mode, selected, tool) {
  return !tool || mode==='advanced' || (mode==='custom'&&selected.includes(tool));
 }
 const api=Object.freeze({tools,preferences,visible});
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
 else scope.ZineToolsets=api;
})(typeof window!=='undefined'?window:this);
