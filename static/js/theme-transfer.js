/* Versioned style-only JSON. Import changes the form; Save remains explicit. */
(function (root) {
  'use strict';
  const limits = {custom_css:100000,bg_color:7,text_color:7,glow_color:7,
    background_layers:4000,blend_mode:200,font_stack:500};
  const colors = ['bg_color','text_color','glow_color'];
  function validateThemeFile(data, mode) {
    if (!data || typeof data !== 'object' || Array.isArray(data) ||
        Object.keys(data).some(key => !['format','version','mode','style'].includes(key)) ||
        data.format!=='neonrest-theme' || data.version!==1 || data.mode!==mode ||
        !data.style || typeof data.style!=='object' || Array.isArray(data.style))
      throw new Error('Choose a Neonrest theme version 1 file for '+mode+' mode.');
    const result = {};
    for (const [key,value] of Object.entries(data.style)) {
      if (!Object.hasOwn(limits,key)) throw new Error('Unknown theme field: '+key);
      if (value!==null && (typeof value!=='string' || value.length>limits[key]))
        throw new Error('Invalid or oversized field: '+key);
      if (colors.includes(key) && value!==null && !/^#[0-9a-f]{3}(?:[0-9a-f]{3})?$/i.test(value))
        throw new Error('Use a hex color or null for '+key+'.');
      if (typeof value==='string' && /<\/?(?:script|style|iframe|object|embed)\b/i.test(value))
        throw new Error('HTML is not supported in theme fields.');
      result[key]=value;
    }
    return result;
  }
  if (typeof module!=='undefined' && module.exports) module.exports={validateThemeFile,limits};
  if (!root.document) return;
  const form=root.document.getElementById('theme-editor-form');
  if (!form) return;
  const mode=form.dataset.themeMode;
  const status=root.document.getElementById('theme-transfer-status');
  root.document.getElementById('theme-export').addEventListener('click', () => {
    const style={};
    for (const key of Object.keys(limits)) {
      style[key]=colors.includes(key) && form.elements['null_'+key].checked ? null : form.elements[key].value;
    }
    const data={format:'neonrest-theme',version:1,mode,style};
    try {
      validateThemeFile(data,mode);
      if (!form.reportValidity()) return;
      const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)+'\n'],{type:'application/json'}));
      const link=root.document.createElement('a');link.href=url;link.download='neonrest-theme-'+mode+'.json';
      link.click();root.setTimeout(()=>URL.revokeObjectURL(url),1000);
      status.textContent='Exported current '+mode+' style, including unsaved edits. Shared Vibe identity is excluded.';
    } catch(error) { status.textContent=error.message; }
  });
  root.document.getElementById('theme-import').addEventListener('change', async event => {
    const file=event.target.files[0];
    if (!file) return;
    try {
      if (file.size>131072) throw new Error('Theme file must be 128 KiB or smaller.');
      const style=validateThemeFile(JSON.parse(await file.text()),mode);
      for (const [key,value] of Object.entries(style)) {
        const field=form.elements[key];
        if (colors.includes(key)) {
          if (value!==null) {
            const hex=value.length===4?'#'+[...value.slice(1)].map(x=>x+x).join(''):value;
            field.value=hex;root.document.getElementById(key+'_hex').value=hex;
          }
          form.elements['null_'+key].checked=value===null;
        } else {
          if (field.tagName==='SELECT' && value && !Array.from(field.options).some(option=>option.value===value)) {
            const option=root.document.createElement('option');option.value=value;option.textContent=value;field.append(option);
          }
          field.value=value || '';
        }
        field.setCustomValidity('');
      }
      form.dispatchEvent(new Event('change',{bubbles:true}));
      status.textContent='Imported into unsaved '+mode+' edits. Missing fields were kept. Review and Save changes to publish; Undo edit reverses this import.';
    } catch(error) { status.textContent='Import failed: '+error.message; }
    event.target.value='';
  });
})(typeof window!=='undefined'?window:globalThis);
