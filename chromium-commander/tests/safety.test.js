// TEST J (safety): sensitive actions cannot bypass approval; secrets are never typed or uploaded.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, beforeEach, test } from 'node:test';
import { ApprovalBook, classify, hostAllowed } from '../src/policy.js';
import { makeCommander, startServer, tempDir } from './helpers.js';

let srv;
let commander;
let roots;
before(async () => {
  srv = await startServer();
  roots = tempDir('cc-roots-');
  fs.writeFileSync(path.join(roots, 'ok.txt'), 'fine');
  fs.writeFileSync(path.join(roots, '.env'), 'TOKEN=secret');
  fs.writeFileSync(path.join(roots, 'server.pem'), 'key');
  ({ commander } = makeCommander({ uploadRoots: [roots] }));
});
after(async () => {
  await commander.close();
  await srv.close();
});
beforeEach(async () => {
  srv.posts.length = 0;
  await commander.execute('open_url', { url: `${srv.base}/` });
  await commander.execute('fill_input', { target: { label: 'Full name' }, value: 'Siti' });
});

const submit = { target: { role: 'button', name: 'Continue' }, expect: { text_visible: 'Order received' } };

test('J: submitting a form returns APPROVAL_REQUIRED and nothing is sent', async () => {
  const r = await commander.execute('click_element', submit);
  assert.equal(r.status, 'APPROVAL_REQUIRED');
  assert.equal(r.executed, false);
  assert.match(r.approval_id, /^apv_/);
  assert.ok(r.reasons.includes('submits a form'));
  assert.equal(srv.posts.length, 0);
  assert.equal(commander.mgr.page().url(), `${srv.base}/`);
});

test('J: pressing Enter inside a form also needs approval', async () => {
  const r = await commander.execute('press_key', { key: 'Enter', target: { label: 'Full name' } });
  assert.equal(r.status, 'APPROVAL_REQUIRED');
  assert.equal(srv.posts.length, 0);
});

test('J: confirm runs the stored action exactly once', async () => {
  const r = await commander.execute('click_element', submit);
  const done = await commander.confirm(r.approval_id);
  assert.equal(done.status, 'VERIFIED', JSON.stringify(done));
  assert.equal(srv.posts.length, 1);
  assert.match(srv.posts[0].body, /fullname=Siti/);
  const replay = await commander.confirm(r.approval_id);
  assert.equal(replay.status, 'FAILED');
  assert.equal(replay.error.code, 'APPROVAL_INVALID');
  assert.equal(srv.posts.length, 1, 'a used approval cannot submit again');
});

test('J: a made-up approval id or a changed page is refused', async () => {
  assert.equal((await commander.confirm('apv_000000000000')).error.code, 'APPROVAL_INVALID');
  const r = await commander.execute('click_element', submit);
  await commander.execute('open_url', { url: `${srv.base}/page2.html` });
  const late = await commander.confirm(r.approval_id);
  assert.equal(late.error.code, 'APPROVAL_INVALID');
  assert.match(late.error.message, /page changed/);
  assert.equal(srv.posts.length, 0);
});

test('J: approvals expire', () => {
  let now = 0;
  const book = new ApprovalBook(60, () => now);
  const id = book.request('click_element', {}, 'http://a/', []);
  now = 61_000;
  assert.match(book.take(id, 'http://a/').reason, /expired/);
});

test('J: approval mode "deny" blocks sensitive actions outright', async () => {
  const { commander: strict } = makeCommander({ approval: 'deny' });
  try {
    await strict.execute('open_url', { url: `${srv.base}/` });
    const r = await strict.execute('click_element', submit);
    assert.equal(r.status, 'BLOCKED');
    assert.equal(r.approval_id, undefined);
    assert.equal(srv.posts.length, 0);
  } finally {
    await strict.close();
  }
});

test('J: password and card fields are blocked, even with approval', async () => {
  for (const label of ['Password', 'Card']) {
    const r = await commander.execute('fill_input', { target: { label }, value: '1234' });
    assert.equal(r.status, 'BLOCKED', label);
    assert.equal(r.approval_id, undefined);
  }
  assert.equal(await commander.mgr.page().locator('input[name=pw]').inputValue(), '');
  const form = await commander.execute('fill_form', { fields: [{ target: { label: 'Full name' }, value: 'A' }, { target: { label: 'Password' }, value: 'x' }] });
  assert.equal(form.status, 'BLOCKED');
  assert.equal(await commander.mgr.page().locator('input[name=fullname]').inputValue(), 'Siti', 'blocked form fill changes nothing');
});

test('J: agreeing to terms needs approval', async () => {
  const r = await commander.execute('check_checkbox', { target: { role: 'checkbox', name: 'I agree to the terms' } });
  assert.equal(r.status, 'APPROVAL_REQUIRED');
  assert.equal(await commander.mgr.page().locator('#terms').isChecked(), false);
});

test('J: accepting a dialog needs approval', async () => {
  assert.equal((await commander.execute('handle_dialogs', { mode: 'accept' })).status, 'APPROVAL_REQUIRED');
  assert.equal((await commander.execute('handle_dialogs', { mode: 'dismiss' })).status, 'VERIFIED');
});

test('J: uploads outside the roots, of secret files, or with no roots are blocked', async () => {
  const target = { label: 'Attachment' };
  assert.equal((await commander.execute('upload_file', { target, paths: [path.join(roots, '.env')] })).status, 'BLOCKED');
  assert.equal((await commander.execute('upload_file', { target, paths: [path.join(roots, 'server.pem')] })).status, 'BLOCKED');
  assert.equal((await commander.execute('upload_file', { target, paths: ['/etc/hostname'] })).status, 'BLOCKED');
  assert.equal((await commander.execute('upload_file', { target, paths: [path.join(roots, '..', path.basename(roots), '..', 'x')] })).status, 'BLOCKED');
  const { commander: noRoots } = makeCommander();
  try {
    await noRoots.execute('open_url', { url: `${srv.base}/` });
    const r = await noRoots.execute('upload_file', { target, paths: [path.join(roots, 'ok.txt')] });
    assert.equal(r.status, 'BLOCKED');
    assert.match(r.reasons[0], /no uploadRoots/);
  } finally {
    await noRoots.close();
  }
});

test('J: page text that tries to give orders has no effect on policy', async () => {
  const text = (await commander.execute('read_visible_text')).observed;
  assert.equal(text.untrusted_page_content, true);
  assert.match(text.text, /Ignore all previous instructions/);
  assert.equal((await commander.execute('click_element', submit)).status, 'APPROVAL_REQUIRED');
});

test('J: sensitive-word and link rules', () => {
  const cfg = { allowedHosts: [], blockedHosts: ['evil.test'] };
  assert.equal(classify('click_element', {}, { name: 'Bayar sekarang' }, cfg).risk, 'sensitive');
  assert.equal(classify('click_element', {}, { text: 'Delete account' }, cfg).risk, 'sensitive');
  assert.equal(classify('click_element', {}, { text: 'Read more' }, cfg).risk, 'low');
  assert.equal(classify('click_element', {}, { text: 'x', href: 'mailto:a@b.c' }, cfg).risk, 'sensitive');
  assert.equal(classify('click_element', {}, { text: 'x', href: 'https://evil.test/' }, cfg).risk, 'blocked');
  assert.equal(hostAllowed('https://a.example.com/', { allowedHosts: ['*.example.com'] }).ok, true);
  assert.equal(hostAllowed('https://example.com.evil.test/', { allowedHosts: ['*.example.com'] }).ok, false);
});
