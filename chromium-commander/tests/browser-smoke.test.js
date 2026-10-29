// TEST A (launch), C (page inspection), G (screenshot).
import assert from 'node:assert/strict';
import fs from 'node:fs';
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

test('A: launches real Chromium with an open page', async () => {
  const r = await commander.execute('open_url', { url: `${srv.base}/` });
  assert.equal(r.status, 'VERIFIED', JSON.stringify(r));
  const state = (await commander.execute('browser_state')).observed;
  assert.equal(state.connected, true);
  assert.equal(state.mode, 'isolated');
  assert.match(state.browser_version, /^\d+\./);
  assert.equal(state.tabs.length, 1);
  assert.equal(state.tabs[0].url, `${srv.base}/`);
});

test('C: inspect_page reads title, headings, text, controls and forms', async () => {
  const r = await commander.execute('inspect_page');
  assert.equal(r.status, 'OK');
  const o = r.observed;
  assert.equal(o.untrusted_page_content, true);
  assert.equal(o.title, 'Commander Fixture');
  assert.deepEqual(o.headings[0], { level: 1, text: 'Fixture Home' });
  assert.match(o.visible_text.text, /Nothing clicked/);
  const hello = o.controls.find((c) => c.role === 'button' && c.name === 'Say hello');
  assert.deepEqual(hello.target, { role: 'button', name: 'Say hello' });
  const agains = o.controls.filter((c) => c.name === 'Again');
  assert.deepEqual(agains.map((c) => c.target.nth), [0, 1], 'duplicate controls get nth');
  assert.ok(o.controls.some((c) => c.role === 'textbox' && c.name === 'Search'));
  const order = o.forms.find((f) => f.id === 'order');
  assert.equal(order.method, 'post');
  assert.equal(order.fields.find((f) => f.nameAttr === 'pw').secret, true);
  assert.match(o.aria_snapshot, /heading "Fixture Home"/);
});

test('C: every suggested target resolves to exactly one element', async () => {
  const { controls } = (await commander.execute('inspect_interactive_elements')).observed;
  const page = commander.mgr.page();
  const { buildLocator } = await import('../src/targets.js');
  for (const c of controls) {
    const loc = buildLocator(page, c.target);
    const count = await loc.count();
    if (c.target.nth === undefined) assert.equal(count, 1, `${JSON.stringify(c.target)} matched ${count}`);
    else assert.ok(count > c.target.nth);
  }
});

test('G: capture_screenshot writes a real PNG with metadata', async () => {
  const r = await commander.execute('capture_screenshot', { label: 'home' });
  assert.equal(r.status, 'VERIFIED', JSON.stringify(r));
  const file = r.evidence.screenshot;
  assert.ok(fs.existsSync(file));
  assert.ok(fs.statSync(file).size > 1000);
  const meta = JSON.parse(fs.readFileSync(file.replace(/\.png$/, '.json'), 'utf8'));
  assert.equal(meta.url, `${srv.base}/`);
  assert.equal(meta.title, 'Commander Fixture');
  const el = await commander.execute('capture_screenshot', { target: { role: 'heading', name: 'Fixture Home' }, label: 'heading' });
  assert.equal(el.status, 'VERIFIED');
});
