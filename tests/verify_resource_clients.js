/* Error responses preserve drafts and never silently repeat writes. No browser/network required. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = process.argv[2];
const reactionSource = fs.readFileSync(path.join(root, 'static/js/reactions.js'), 'utf8');
const template = fs.readFileSync(path.join(root, 'templates/partials/posts.html'), 'utf8');
let checks = 0;
(async () => {
  for (const [code, message] of [[503, 'Please wait, check your change, then retry.'], [507, 'Storage is full. Keep your text.']]) {
    let click, fetches = 0;
    const status = {textContent: ''};
    const box = {dataset: {csrfToken: 'fixture'}, querySelector: () => status};
    const button = {disabled: false, dataset: {emoji: 'x', postId: 'fixture', reactionUrl: '/fixture'}, closest: () => box};
    const document = {addEventListener: (_, callback) => {click = callback;}};
    vm.runInNewContext(reactionSource, {document, Set, JSON, Error, fetch: async () => {fetches++; return {ok: false, status: code, json: async () => ({message})};}});
    await click({target: {closest: () => button}, preventDefault() {}});
    assert.equal(status.textContent, message); checks++;
    assert.equal(button.disabled, false); checks++;
    assert.equal(fetches, 1); checks++;
  }
  const start = template.indexOf('async function submitComment(');
  const end = template.indexOf("window.addEventListener('DOMContentLoaded'", start);
  assert(start >= 0 && end > start);
  const commentSource = template.slice(start, end).replace(/{{[\s\S]*?}}/g, value => value.includes('request.endpoint') ? 'true' : JSON.stringify('/feed'));
  for (const [code, message] of [[503, 'Wait and check before retrying.'], [507, 'Keep a copy of your text.']]) {
    let fetches = 0, shown;
    const form = {action: '/create_comment', text: 'An unsaved comment draft'};
    const context = {FormData: class {constructor(value) {this.form = value;}}, Error, URL, console: {error() {}}, alert: message => {shown = message;}, fetch: async () => {fetches++; return {ok: false, status: code, json: async () => ({message})};}, location: {reload() {throw Error('Unexpected reload');}, assign() {throw Error('Unexpected navigation');}}};
    vm.runInNewContext(commentSource, context);
    await context.submitComment({preventDefault() {}}, form);
    assert.equal(shown, message); checks++;
    assert.equal(form.text, 'An unsaved comment draft'); checks++;
    assert.equal(fetches, 1); checks++;
  }
  console.log(checks + ' client recovery checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
