// TEST D (click), E (input), F (tabs), H (download), plus forms, dialogs, scrolling, upload.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, beforeEach, test } from 'node:test';
import { makeCommander, startServer, tempDir } from './helpers.js';

let srv;
let commander;
let uploads;
before(async () => {
  srv = await startServer();
  uploads = tempDir('cc-uploads-');
  fs.writeFileSync(path.join(uploads, 'photo.txt'), 'pretend photo');
  ({ commander } = makeCommander({ uploadRoots: [uploads] }));
});
after(async () => {
  await commander.close();
  await srv.close();
});
beforeEach(async () => {
  await commander.execute('open_url', { url: `${srv.base}/` });
});

test('D: click a button and verify the page changed', async () => {
  const r = await commander.execute('click_element', { target: { role: 'button', name: 'Say hello' }, expect: { text_visible: 'Button clicked' } });
  assert.equal(r.status, 'VERIFIED', JSON.stringify(r));
  assert.equal(r.observed.page_text_changed, true);
  const plain = await commander.execute('click_element', { target: { role: 'button', name: 'Say hello' } });
  assert.equal(plain.status, 'EXECUTED_UNVERIFIED', 'no expect -> not claimed as verified');
});

test('D: waits for an element that appears later', async () => {
  await commander.execute('click_element', { target: { role: 'button', name: 'Load more' } });
  const r = await commander.execute('assert_element_visible', { target: { role: 'button', name: 'Late button' } });
  assert.equal(r.status, 'VERIFIED', JSON.stringify(r));
});

test('E: fill_input, select_option, check/uncheck verify the resulting state', async () => {
  const f = await commander.execute('fill_input', { target: { label: 'Search' }, value: 'nikah beda negara' });
  assert.equal(f.status, 'VERIFIED', JSON.stringify(f));
  assert.equal(await commander.mgr.page().locator('#q').inputValue(), 'nikah beda negara');
  const byPlaceholder = await commander.execute('fill_input', { target: { placeholder: 'Type here' }, value: 'x' });
  assert.equal(byPlaceholder.status, 'VERIFIED');
  const s = await commander.execute('select_option', { target: { role: 'combobox', name: 'Size' }, labels: ['Medium'] });
  assert.equal(s.status, 'VERIFIED');
  assert.deepEqual(s.observed.selected_values, ['m']);
  assert.equal((await commander.execute('check_checkbox', { target: { role: 'checkbox', name: 'Newsletter' } })).status, 'VERIFIED');
  assert.equal((await commander.execute('uncheck_checkbox', { target: { role: 'checkbox', name: 'Newsletter' } })).status, 'VERIFIED');
  const k = await commander.execute('press_key', { key: 'End', target: { label: 'Search' } });
  assert.equal(k.status, 'EXECUTED_UNVERIFIED');
});

test('E: fill_form fills several fields and inspect/validate_form_state report validity', async () => {
  const before = await commander.execute('validate_form_state', { form_index: 0 });
  assert.equal(before.observed.valid, false);
  const r = await commander.execute('fill_form', { fields: [{ target: { label: 'Full name' }, value: 'Siti' }] });
  assert.equal(r.status, 'VERIFIED', JSON.stringify(r));
  const afterFill = await commander.execute('validate_form_state', { form_index: 0 });
  assert.equal(afterFill.observed.valid, true);
  assert.equal(srv.posts.length, 0, 'filling never submits');
});

test('F: tabs open, switch, follow popups and close', async () => {
  const pop = await commander.execute('click_element', { target: { role: 'link', name: 'Open in new tab' } });
  assert.equal(pop.observed.new_tabs, 1, JSON.stringify(pop));
  let tabs = (await commander.execute('list_tabs')).observed.tabs;
  assert.equal(tabs.length, 2);
  const active = tabs.find((t) => t.active);
  await commander.mgr.page().waitForLoadState();
  assert.equal(await commander.mgr.page().title(), 'Second Page');
  const first = tabs.find((t) => !t.active).id;
  const sw = await commander.execute('switch_tab', { tab_id: first });
  assert.equal(sw.status, 'VERIFIED');
  assert.equal(sw.observed.title, 'Commander Fixture');
  const open = await commander.execute('open_tab', { url: `${srv.base}/page2.html` });
  assert.equal(open.status, 'VERIFIED');
  assert.equal((await commander.execute('close_tab', { tab_id: open.observed.tab_id })).status, 'VERIFIED');
  assert.equal((await commander.execute('close_tab', { tab_id: active.id })).status, 'VERIFIED');
  tabs = (await commander.execute('list_tabs')).observed.tabs;
  assert.equal(tabs.length, 1);
  assert.equal((await commander.execute('switch_tab', { tab_id: 'nope' })).error.code, 'TAB_NOT_FOUND');
});

test('H: download_file saves into the downloads folder and verifies size', async () => {
  const r = await commander.execute('download_file', { target: { role: 'link', name: 'Get report' } });
  assert.equal(r.status, 'VERIFIED', JSON.stringify(r));
  assert.ok(r.observed.path.startsWith(commander.cfg.downloadsDir));
  assert.equal(fs.readFileSync(r.observed.path, 'utf8'), 'quarterly report\n');
  const again = await commander.execute('download_file', { target: { role: 'link', name: 'Get report' } });
  assert.match(path.basename(again.observed.path), /^report \(1\)\.txt$/, 'duplicate names do not overwrite');
  assert.equal((await commander.execute('assert_download_exists', { name: 'report.txt' })).status, 'VERIFIED');
  const empty = await commander.execute('download_file', { target: { role: 'link', name: 'Get empty file' } });
  assert.equal(empty.status, 'VERIFICATION_FAILED', 'an empty file is not silently accepted');
  assert.equal((await commander.execute('list_downloads')).observed.downloads.length, 3);
});

test('dialogs are dismissed by default and recorded', async () => {
  const r = await commander.execute('click_element', { target: { role: 'button', name: 'Open dialog' }, expect: { text_visible: 'dialog dismissed' } });
  assert.equal(r.status, 'VERIFIED', JSON.stringify(r));
  assert.equal(r.observed.dialogs_opened, 1);
  const d = (await commander.execute('list_dialogs')).observed.dialogs.at(-1);
  assert.deepEqual([d.type, d.message, d.handled], ['confirm', 'Really?', 'dismissed']);
});

test('scroll_page moves the viewport and scrolls elements into view', async () => {
  const down = await commander.execute('scroll_page', { direction: 'down', amount: 500 });
  assert.equal(down.status, 'VERIFIED');
  assert.equal(down.observed.scroll_y_after, 500);
  assert.equal((await commander.execute('scroll_page', { target: { css: '#bottom' } })).status, 'VERIFIED');
  await commander.execute('scroll_page', { direction: 'top' });
  const up = await commander.execute('scroll_page', { direction: 'up' });
  assert.equal(up.status, 'VERIFICATION_FAILED', 'already at the top is reported, not hidden');
  assert.equal((await commander.execute('hover_element', { target: { role: 'link', name: 'Second page' } })).status, 'EXECUTED_UNVERIFIED');
});

test('upload_file attaches an allowed file only after approval', async () => {
  const req = await commander.execute('upload_file', { target: { label: 'Attachment' }, paths: [path.join(uploads, 'photo.txt')] });
  assert.equal(req.status, 'APPROVAL_REQUIRED');
  const done = await commander.confirm(req.approval_id);
  assert.equal(done.status, 'VERIFIED', JSON.stringify(done));
  assert.deepEqual(done.observed.attached, ['photo.txt']);
});
