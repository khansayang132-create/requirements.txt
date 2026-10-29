// The MCP server as Claude Code runs it: a child process speaking JSON-RPC over stdio.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import path from 'node:path';
import readline from 'node:readline';
import { fileURLToPath } from 'node:url';
import { after, before, test } from 'node:test';
import { startServer, tempDir } from './helpers.js';

const SERVER = path.join(path.dirname(fileURLToPath(import.meta.url)), '../src/mcp-server.js');
let srv;
let child;
let nextId = 1;
const waiting = new Map();

function rpc(method, params) {
  const id = nextId++;
  child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id, method, params })}\n`);
  return new Promise((resolve) => waiting.set(id, resolve));
}
const call = async (name, args = {}) => {
  const res = await rpc('tools/call', { name, arguments: args });
  return { ...res.result, json: JSON.parse(res.result.content[0].text) };
};

before(async () => {
  srv = await startServer();
  const dir = tempDir();
  child = spawn(process.execPath, [SERVER], {
    env: { ...process.env, CC_HEADLESS: '1', CC_ARTIFACTS_DIR: path.join(dir, 'a'), CC_DOWNLOADS_DIR: path.join(dir, 'd') },
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  readline.createInterface({ input: child.stdout }).on('line', (line) => {
    const msg = JSON.parse(line);
    waiting.get(msg.id)?.(msg);
    waiting.delete(msg.id);
  });
});
after(async () => {
  child.stdin.end();
  await new Promise((r) => child.once('exit', r));
  await srv.close();
});

test('MCP: initialize and list tools', async () => {
  const init = await rpc('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'test', version: '0' } });
  assert.equal(init.result.protocolVersion, '2025-06-18');
  assert.equal(init.result.serverInfo.name, 'chromium-commander');
  assert.match(init.result.instructions, /untrusted/);
  child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' })}\n`);
  const { result } = await rpc('tools/list', {});
  const names = result.tools.map((t) => t.name);
  for (const n of ['browser_open_url', 'browser_inspect_page', 'browser_click_element', 'browser_fill_input', 'browser_capture_screenshot',
    'browser_list_tabs', 'browser_download_file', 'browser_upload_file', 'browser_confirm_action', 'browser_state', 'browser_close', 'task_start', 'task_finish']) {
    assert.ok(names.includes(n), n);
  }
  for (const t of result.tools) assert.equal(t.inputSchema.type, 'object', t.name);
  assert.equal((await rpc('nope', {})).error.code, -32601);
});

test('MCP: a task drives the real browser and reports verified evidence', async () => {
  await call('task_start', { objective: 'Say hello on the fixture page', plan: ['open page', 'click hello', 'screenshot'] });
  const open = await call('browser_open_url', { url: `${srv.base}/` });
  assert.equal(open.json.status, 'VERIFIED');
  const page = await call('browser_inspect_page', { include: ['controls'] });
  const hello = page.json.observed.controls.find((c) => c.name === 'Say hello');
  const click = await call('browser_click_element', { target: hello.target, expect: { text_visible: 'Button clicked' } });
  assert.equal(click.json.status, 'VERIFIED');
  assert.equal(click.isError, false);
  await call('task_note', { observation: 'greeting shown', step_done: true });
  const shot = await call('browser_capture_screenshot', { label: 'mcp' });
  assert.equal(shot.json.status, 'VERIFIED');
  const image = shot.content.find((c) => c.type === 'image');
  assert.equal(image.mimeType, 'image/png');
  assert.ok(Buffer.from(image.data, 'base64').subarray(1, 4).toString() === 'PNG');
  const report = (await call('task_finish', { outcome: 'completed', summary: 'done' })).json;
  assert.equal(report.status, 'completed');
  assert.equal(report.verification_status, 'verified');
  assert.equal(report.evidence.screenshots.length, 1);
});

test('MCP: the approval gate holds over the protocol', async () => {
  await call('browser_open_url', { url: `${srv.base}/` });
  await call('browser_fill_input', { target: { label: 'Full name' }, value: 'Ali' });
  const req = await call('browser_click_element', { target: { role: 'button', name: 'Continue' } });
  assert.equal(req.json.status, 'APPROVAL_REQUIRED');
  assert.equal(srv.posts.length, 0);
  const state = await call('browser_state');
  assert.equal(state.json.observed.pending_approvals[0].approval_id, req.json.approval_id);
  const done = await call('browser_confirm_action', { approval_id: req.json.approval_id });
  assert.equal(done.json.executed, true);
  assert.equal(srv.posts.length, 1);
  const blocked = await call('browser_fill_input', { target: { label: 'Password' }, value: 'x' });
  assert.equal(blocked.isError, true);
});

test('MCP: unfinished task claims are downgraded', async () => {
  await call('task_start', { objective: 'nothing verified' });
  await call('browser_get_current_url');
  const report = (await call('task_finish', { outcome: 'completed' })).json;
  assert.equal(report.status, 'completed_unverified');
});
