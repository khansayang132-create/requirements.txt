// Scripted multi-step workflows: task state, approval opt-in, failure stop, cancellation.
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { checkWorkflow, runWorkflow } from '../src/workflow.js';
import { makeCommander, startServer } from './helpers.js';

let srv;
before(async () => {
  srv = await startServer();
});
after(async () => {
  await srv.close();
});

const order = (base, approve) => ({
  objective: 'Fill and submit the order form',
  steps: [
    { action: 'open_url', args: { url: `${base}/` }, description: 'open the shop' },
    { action: 'fill_input', args: { target: { label: 'Full name' }, value: 'Rani' }, description: 'enter name' },
    { action: 'click_element', args: { target: { role: 'button', name: 'Continue' }, expect: { text_visible: 'Order received' } }, description: 'submit', approve },
    { action: 'assert_text_visible', args: { text: 'Order received' }, description: 'confirm received' },
  ],
});

test('workflow stops at a sensitive step that was not approved', async () => {
  srv.posts.length = 0;
  const { commander } = makeCommander();
  try {
    const report = await runWorkflow(commander, order(srv.base, false), { allowSensitive: true });
    assert.equal(report.status, 'needs_approval');
    assert.equal(report.completed_steps.length, 2);
    assert.equal(report.remaining_steps.length, 2);
    assert.equal(srv.posts.length, 0);
  } finally {
    await commander.close();
  }
});

test('workflow marked approve still needs --allow-sensitive', async () => {
  srv.posts.length = 0;
  const { commander } = makeCommander();
  try {
    const report = await runWorkflow(commander, order(srv.base, true), { allowSensitive: false });
    assert.equal(report.status, 'needs_approval');
    assert.equal(srv.posts.length, 0);
  } finally {
    await commander.close();
  }
});

test('workflow completes and is verified when both opt in', async () => {
  srv.posts.length = 0;
  const { commander } = makeCommander();
  try {
    const report = await runWorkflow(commander, order(srv.base, true), { allowSensitive: true });
    assert.equal(report.status, 'completed', JSON.stringify(report.failed_actions));
    assert.equal(report.verification_status, 'verified');
    assert.equal(srv.posts.length, 1);
    assert.equal(report.action_log.length, 5, '4 steps + the confirmed sensitive action');
  } finally {
    await commander.close();
  }
});

test('workflow stops on failure and records it', async () => {
  const { commander } = makeCommander({ timeouts: { action: 300, navigation: 3000, download: 1000 }, maxRetries: 0 });
  try {
    const report = await runWorkflow(commander, {
      objective: 'click something missing',
      steps: [{ action: 'open_url', args: { url: `${srv.base}/` } }, { action: 'click_element', args: { target: { text: 'Nope' } } }, { action: 'get_page_title' }],
    });
    assert.equal(report.status, 'failed');
    assert.equal(report.failed_actions[0].error.code, 'TARGET_NOT_FOUND');
    assert.equal(report.action_log.length, 2, 'later steps did not run');
  } finally {
    await commander.close();
  }
});

test('workflow cancellation stops before the next step', async () => {
  const { commander } = makeCommander();
  const abort = new AbortController();
  try {
    const report = await runWorkflow(commander, {
      objective: 'cancel me',
      steps: [{ action: 'open_url', args: { url: `${srv.base}/` } }, { action: 'get_page_title' }, { action: 'get_current_url' }],
    }, { signal: abort.signal, onStep: (i) => i === 0 && abort.abort() });
    assert.equal(report.status, 'cancelled');
    assert.equal(report.action_log.length, 1);
  } finally {
    await commander.close();
  }
});

test('invalid workflows are rejected before anything runs', () => {
  assert.match(checkWorkflow({ objective: 'x', steps: [{ action: 'rm_rf' }] }).join(), /unknown action rm_rf/);
  assert.match(checkWorkflow({ steps: [] }).join(), /objective is required/);
});
