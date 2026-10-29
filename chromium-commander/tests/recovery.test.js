// TEST I (recovery): failures are reported with evidence, never turned into success.
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { makeCommander, startServer } from './helpers.js';

let srv;
before(async () => {
  srv = await startServer();
});
after(async () => {
  await srv.close();
});

test('I: a page timeout is reported as FAILED/TIMEOUT with a retry count', async () => {
  const { commander } = makeCommander({ timeouts: { action: 500, navigation: 700, download: 1000 }, maxRetries: 1 });
  try {
    const r = await commander.execute('open_url', { url: `${srv.base}/slow?ms=4000` });
    assert.equal(r.status, 'FAILED');
    assert.equal(r.ok, false);
    assert.equal(r.error.code, 'TIMEOUT');
    assert.equal(r.retries, 1, 'idempotent navigation is retried once');
    assert.ok(r.recovery.browser_connected);
  } finally {
    await commander.close();
  }
});

test('I: a missing target fails after bounded retries and says whether it exists', async () => {
  const { commander } = makeCommander({ timeouts: { action: 300, navigation: 5000, download: 1000 }, maxRetries: 2 });
  try {
    await commander.execute('open_url', { url: `${srv.base}/` });
    const r = await commander.execute('click_element', { target: { role: 'button', name: 'Does not exist' } });
    assert.equal(r.status, 'FAILED');
    assert.equal(r.error.code, 'TARGET_NOT_FOUND');
    assert.equal(r.retries, 2);
    assert.equal(r.failed_phase, 'locate');
    assert.equal(r.recovery.target_matches, 0);
    assert.equal(r.recovery.page_changed, false);
  } finally {
    await commander.close();
  }
});

test('I: an ambiguous target is an error, not a guess', async () => {
  const { commander } = makeCommander();
  try {
    await commander.execute('open_url', { url: `${srv.base}/` });
    const r = await commander.execute('click_element', { target: { role: 'button', name: 'Again' } });
    assert.equal(r.error.code, 'AMBIGUOUS_TARGET');
    assert.equal(r.retries, 0);
    const ok = await commander.execute('click_element', { target: { role: 'button', name: 'Again', nth: 1 } });
    assert.equal(ok.status, 'EXECUTED_UNVERIFIED');
  } finally {
    await commander.close();
  }
});

test('I: a click that fails mid-act is not repeated', async () => {
  const { commander } = makeCommander({ timeouts: { action: 400, navigation: 5000, download: 1000 }, maxRetries: 2 });
  try {
    await commander.execute('open_url', { url: `${srv.base}/` });
    // Cover the button so the click itself (act phase) times out.
    await commander.mgr.page().evaluate(() => {
      const shield = document.createElement('div');
      shield.style.cssText = 'position:fixed;inset:0;z-index:9;background:transparent';
      document.body.append(shield);
    });
    const r = await commander.execute('click_element', { target: { role: 'button', name: 'Say hello' } });
    assert.equal(r.status, 'FAILED');
    assert.equal(r.failed_phase, 'act');
    assert.equal(r.retries, 0, 'non-idempotent action must not be retried after it started');
    assert.equal(r.executed, null, 'outcome reported as unknown');
    assert.ok(r.notes.some((n) => /NOT repeated/.test(n)));
  } finally {
    await commander.close();
  }
});

test('I: a crashed browser is detected and relaunched on the next action', async () => {
  const { commander } = makeCommander();
  try {
    await commander.execute('open_url', { url: `${srv.base}/` });
    await commander.mgr.browser.close();
    const state = (await commander.execute('browser_state')).observed;
    assert.equal(state.connected, false);
    const r = await commander.execute('open_url', { url: `${srv.base}/page2.html` });
    assert.equal(r.status, 'VERIFIED', JSON.stringify(r));
    assert.ok(r.notes.some((n) => /relaunched/.test(n)));
  } finally {
    await commander.close();
  }
});

test('I: a visible browser without a display fails with an actionable error', async () => {
  const saved = process.env.DISPLAY;
  delete process.env.DISPLAY;
  const savedW = process.env.WAYLAND_DISPLAY;
  delete process.env.WAYLAND_DISPLAY;
  const { commander } = makeCommander({ headless: false });
  try {
    if (process.platform !== 'linux') return;
    const r = await commander.execute('open_url', { url: `${srv.base}/` });
    assert.equal(r.status, 'FAILED');
    assert.equal(r.error.code, 'NO_DISPLAY');
    assert.match(r.error.hint, /xvfb-run/);
  } finally {
    if (saved !== undefined) process.env.DISPLAY = saved;
    if (savedW !== undefined) process.env.WAYLAND_DISPLAY = savedW;
    await commander.close();
  }
});
