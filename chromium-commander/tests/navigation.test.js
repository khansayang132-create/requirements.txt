// TEST B (navigation) plus URL policy.
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { makeCommander, startServer } from './helpers.js';

let srv;
let commander;
before(async () => {
  srv = await startServer();
  ({ commander } = makeCommander());
});
after(async () => {
  await commander.close();
  await srv.close();
});

test('B: open_url verifies URL, title and HTTP status', async () => {
  const r = await commander.execute('open_url', { url: `${srv.base}/page2.html`, expect: { title_contains: 'Second' } });
  assert.equal(r.status, 'VERIFIED', JSON.stringify(r));
  assert.equal(r.observed.http_status, 200);
  assert.equal((await commander.execute('get_current_url')).observed.url, `${srv.base}/page2.html`);
  assert.equal((await commander.execute('get_page_title')).observed.title, 'Second Page');
  assert.equal((await commander.execute('assert_url', { contains: 'page2' })).status, 'VERIFIED');
});

test('B: a 404 is reported as VERIFICATION_FAILED, not success', async () => {
  const r = await commander.execute('open_url', { url: `${srv.base}/missing.html` });
  assert.equal(r.status, 'VERIFICATION_FAILED');
  assert.equal(r.ok, false);
  assert.equal(r.observed.http_status, 404);
});

test('B: link navigation, back, forward, reload, wait_for_navigation', async () => {
  await commander.execute('open_url', { url: `${srv.base}/` });
  const click = await commander.execute('click_element', { target: { role: 'link', name: 'Second page' }, expect: { url_contains: 'page2' } });
  assert.equal(click.status, 'VERIFIED', JSON.stringify(click));
  assert.equal(click.observed.url_changed, true);
  assert.equal((await commander.execute('go_back')).observed.url, `${srv.base}/`);
  assert.equal((await commander.execute('go_forward')).observed.url, `${srv.base}/page2.html`);
  assert.equal((await commander.execute('reload_page')).status, 'VERIFIED');
  const w = await commander.execute('wait_for_navigation', { url_contains: 'page2', timeout: 1000 });
  assert.equal(w.status, 'VERIFIED');
  const nav = await commander.execute('verify_navigation_result', { url_contains: 'page2', title_contains: 'Second', text_visible: 'Page Two' });
  assert.equal(nav.status, 'VERIFIED', JSON.stringify(nav));
  const wrong = await commander.execute('verify_navigation_result', { text_visible: 'Not on this page', timeout: 300 });
  assert.equal(wrong.status, 'VERIFICATION_FAILED');
});

test('B: unsafe schemes are blocked and never run', async () => {
  for (const url of ['javascript:alert(1)', 'file:///etc/passwd', 'chrome://settings', 'data:text/html,<h1>x</h1>']) {
    const r = await commander.execute('open_url', { url });
    assert.equal(r.status, 'BLOCKED', url);
    assert.equal(r.executed, false);
  }
});

test('B: allowedHosts restricts where the browser may go', async () => {
  const { commander: c } = makeCommander({ allowedHosts: ['example.org'] });
  try {
    const r = await c.execute('open_url', { url: `${srv.base}/` });
    assert.equal(r.status, 'BLOCKED');
    assert.match(r.reasons[0], /not in allowedHosts/);
  } finally {
    await c.close();
  }
});

test('B: invalid arguments are rejected before anything runs', async () => {
  const r = await commander.execute('open_url', { link: 'x' });
  assert.equal(r.status, 'FAILED');
  assert.equal(r.error.code, 'INVALID_ARGUMENTS');
  assert.match(r.error.message, /args.url is required/);
});
