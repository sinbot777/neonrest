/* Unsaved form history is local to this editor and never writes a revision. */
(function (root) {
  'use strict';
  class ThemeEditHistory {
    constructor(initial, limit = 50) {
      this.baseline = JSON.stringify(initial);
      this.states = [this.baseline];
      this.position = 0;
      this.limit = limit;
    }
    record(value) {
      const state = JSON.stringify(value);
      if (state === this.states[this.position]) return;
      this.states.splice(this.position + 1);
      this.states.push(state);
      if (this.states.length > this.limit) this.states.shift();
      this.position = this.states.length - 1;
    }
    get dirty() { return this.states[this.position] !== this.baseline; }
    get canUndo() { return this.position > 0; }
    get canRedo() { return this.position < this.states.length - 1; }
    undo() { if (this.canUndo) this.position--; return this.current(); }
    redo() { if (this.canRedo) this.position++; return this.current(); }
    current() { return JSON.parse(this.states[this.position]); }
    discard() { this.record(JSON.parse(this.baseline)); return this.current(); }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {ThemeEditHistory};
  if (!root.document) return;
  const form = root.document.getElementById('theme-editor-form');
  if (!form) return;
  const controls = Array.from(form.elements).filter(el =>
    ['INPUT','SELECT','TEXTAREA'].includes(el.tagName) && !el.dataset.derived && el.type !== 'hidden' && el.type !== 'submit' && el.type !== 'file');
  const read = () => controls.map(el => ({value: el.value, checked: el.checked === true}));
  const history = new ThemeEditHistory(read());
  const undo = root.document.getElementById('theme-undo');
  const redo = root.document.getElementById('theme-redo');
  const discard = root.document.getElementById('theme-discard');
  const hint = root.document.getElementById('studio-save-hint');
  const initialHint = hint.textContent;
  let applying = false, submitting = false;
  function refresh(message) {
    undo.disabled = !history.canUndo;
    redo.disabled = !history.canRedo;
    discard.disabled = !history.dirty;
    hint.textContent = message || (history.dirty ? 'Unsaved changes' : initialHint);
  }
  function apply(state, label) {
    applying = true;
    controls.forEach((el, i) => { el.value = state[i].value; el.checked = state[i].checked; el.setCustomValidity(''); });
    // Refresh existing color/contrast UI without creating another undo entry.
    controls.filter(el => el.type === 'color').forEach(el => el.dispatchEvent(new Event('input', {bubbles: true})));
    // Color listeners clear Unset: restore every checkbox after those listeners.
    controls.forEach((el, i) => { el.value = state[i].value; el.checked = state[i].checked; });
    form.dispatchEvent(new Event('change', {bubbles: true}));
    applying = false;
    refresh(label + (history.dirty ? ' — unsaved changes' : ' — matches the loaded version'));
  }
  function record() { if (!applying) { history.record(read()); refresh(); } }
  form.addEventListener('input', record);
  form.addEventListener('change', record);
  undo.addEventListener('click', () => apply(history.undo(), 'Edit undone'));
  redo.addEventListener('click', () => apply(history.redo(), 'Edit redone'));
  discard.addEventListener('click', () => apply(history.discard(), 'Unsaved changes discarded'));
  root.document.addEventListener('submit', event => {
    if (event.target === form && !event.defaultPrevented) submitting = true;
  });
  root.addEventListener('beforeunload', event => {
    if (history.dirty && !submitting) { event.preventDefault(); event.returnValue = ''; }
  });
  refresh();
})(typeof window !== 'undefined' ? window : globalThis);
