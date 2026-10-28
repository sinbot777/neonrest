/* Exercise the real shared click handler without a browser or live account. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let handler, calls = [], resolveFetch, fail = false;
const status = {textContent: ''};
const box = {dataset: {csrfToken: 'fixture-token'}, querySelector: () => status};
function button() {
  return {disabled: false, dataset: {postId: 'OpaquePostId12345', emoji: '👍', reactionUrl: '/sandbox/react/OpaquePostId12345'}, closest: () => box,
    classList: {toggle(name, value) {this[name] = value;}}, setAttribute(name, value) {this[name] = value;}, append(node) {this.count = node.textContent;}};
}
const a = button(), duplicate = button();
const document = {addEventListener(type, callback) {assert.equal(type, 'click'); assert.equal(handler, undefined);handler = callback;},
  querySelectorAll: () => [a, duplicate], createElement: () => ({textContent: ''})};
const fetch = async (url, options) => {
  calls.push({url, options});
  if (fail) return {ok: false, json: async () => null};
  return new Promise(resolve => {resolveFetch = resolve;});
};
vm.runInNewContext(fs.readFileSync('static/js/reactions.js', 'utf8'), {document, fetch, Set, JSON, String, Error});
const click = () => handler({target: {closest: () => a}, preventDefault() {}});
(async () => {
  const first = click();
  assert.equal(a.disabled, true);
  await click();
  assert.equal(calls.length, 1, 'Repeated clicks must not toggle a reaction twice');
  assert.equal(calls[0].url, '/sandbox/react/OpaquePostId12345');
  assert.equal(calls[0].options.headers['X-CSRF-Token'], 'fixture-token');
  assert.deepEqual(JSON.parse(calls[0].options.body), {emoji: '👍'});
  resolveFetch({ok: true, json: async () => ({status: 'ok', action: 'added', count: 1})});
  await first;
  assert.equal(a.disabled, false);
  assert.equal(a['aria-pressed'], 'true');
  assert.equal(duplicate.count, '1', 'Copies of the same post update together');
  const second = click();
  resolveFetch({ok: true, json: async () => ({status: 'ok', action: 'removed', count: 0})});
  await second;
  assert.equal(a['aria-pressed'], 'false');
  assert.equal(duplicate.classList.active, false);
  fail = true;
  await click();
  assert.match(status.textContent, /Could not save/);
  assert.equal(a.disabled, false, 'A failed request must allow retry');
  assert.equal(a['aria-pressed'], 'false', 'A failed request must not fake a saved reaction');
  console.log('SHARED REACTION HANDLER PASS: scoped URL, CSRF, single request, add/remove, duplicate controls and failure/retry');
})().catch(error => {console.error(error);process.exitCode = 1;});

