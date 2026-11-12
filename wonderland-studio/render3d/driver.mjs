// Node driver for the 3D character renderer.
//
// Starts headless Chromium (SwiftShader WebGL2, no GPU needed), loads scene.js + three.js into a
// page that has NO network access (every request is answered from local files or aborted), then
// speaks a line protocol on stdin/stdout:
//
//   -> {"cmd":"init","width":1080,"height":1920}           <- {"ok":true,"info":{...}}
//   -> {"cmd":"chars","specs":[...]}                        <- {"ok":true}
//   -> {"cmd":"lights","preset":{...}}                      <- {"ok":true}
//   -> {"cmd":"frame","actors":[...],"opts":{...}}          <- {"ok":true,"box":[x,y,w,h],"anchors":{...},"runs":n}
//                                                              followed by one line of base64 RLE pixels
//   -> {"cmd":"quit"}
//
// Pixels are premultiplied RGBA rows bottom-up (WebGL order) run-length encoded as
// (count:uint32, rgba:uint32) pairs. Errors come back as {"ok":false,"error":"..."}.
//
//   node driver.mjs --smoke        one frame, prints timing, exits 0 on success

import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
import readline from 'readline';
import { fileURLToPath, pathToFileURL } from 'url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

function loadPlaywright() {
  const tried = [];
  for (const base of [path.join(HERE, 'package.json'), '/opt/node-tools/node_modules/', process.env.WONDERLAND_PLAYWRIGHT_DIR]) {
    if (!base) continue;
    try { return createRequire(base)('playwright'); } catch (e) { tried.push(base); }
  }
  throw new Error('playwright not found (looked in ' + tried.join(', ') + '); run npm ci in render3d/');
}

function threePath() {
  for (const base of [path.join(HERE, 'package.json'), '/opt/node-tools/node_modules/']) {
    try { const p = createRequire(base).resolve('three'); return path.join(path.dirname(p), 'three.module.min.js'); } catch (e) { /* next */ }
  }
  throw new Error('three not found; run npm ci in render3d/');
}

const HTML = `<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0;background:transparent">
<canvas id="c"></canvas>
<script type="importmap">{"imports":{"three":"/three.js"}}</script>
<script type="module">
import * as S from '/scene.js';
window.S = S; window.READY = true;
</script></body></html>`;

export async function startRenderer(width = 1080, height = 1920, opts = {}) {
  const { chromium } = loadPlaywright();
  const threeSrc = fs.readFileSync(threePath(), 'utf8');
  const sceneSrc = fs.readFileSync(path.join(HERE, 'scene.js'), 'utf8');
  const browser = await chromium.launch({
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist',
      '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage({ viewport: { width: 64, height: 64 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.route('**/*', r => {
    const u = new URL(r.request().url());
    if (u.pathname === '/three.js') return r.fulfill({ contentType: 'text/javascript', body: threeSrc });
    if (u.pathname === '/scene.js') return r.fulfill({ contentType: 'text/javascript', body: sceneSrc });
    if (u.pathname === '/index.html') return r.fulfill({ contentType: 'text/html', body: HTML });
    return r.abort();
  });
  await page.goto('http://render3d.local/index.html');
  await page.waitForFunction('window.READY === true', null, { timeout: 30000 }).catch(() => {
    throw new Error('scene did not load: ' + errors.join(' | '));
  });
  const info = await page.evaluate(([w, h, o]) => window.S.init(w, h, o), [width, height, opts]);
  return { browser, page, info, errors };
}

async function serve() {
  const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  let R = null;
  const out = (o) => process.stdout.write(JSON.stringify(o) + '\n');
  for await (const line of rl) {
    if (!line.trim()) continue;
    let msg;
    try { msg = JSON.parse(line); } catch (e) { out({ ok: false, error: 'bad json' }); continue; }
    try {
      if (msg.cmd === 'init') {
        R = await startRenderer(msg.width || 1080, msg.height || 1920, msg.opts || {});
        out({ ok: true, info: R.info });
      } else if (msg.cmd === 'chars') {
        await R.page.evaluate(s => window.S.setCharacters(s), msg.specs);
        out({ ok: true });
      } else if (msg.cmd === 'lights') {
        await R.page.evaluate(p => window.S.setLights(p), msg.preset || {});
        out({ ok: true });
      } else if (msg.cmd === 'frame') {
        const res = await R.page.evaluate(([a, o]) => window.S.renderFrame(a, o), [msg.actors, msg.opts || {}]);
        const data = res.data; delete res.data;
        res.ok = true;
        process.stdout.write(JSON.stringify(res) + '\n' + data + '\n');
      } else if (msg.cmd === 'quit') {
        break;
      } else out({ ok: false, error: 'unknown cmd ' + msg.cmd });
    } catch (e) {
      out({ ok: false, error: String((e && e.message) || e).slice(0, 600) + (R && R.errors.length ? ' | ' + R.errors.slice(-3).join(' | ') : '') });
    }
  }
  if (R) await R.browser.close().catch(() => {});
  process.exit(0);
}

async function smoke() {
  const t0 = Date.now();
  const R = await startRenderer(1080, 1920);
  const spec = { id: 'bobo', species: 'bunny', colors: { body: '#B9A7F2', belly: '#FFF6E3', inner_ear: '#FFB3C7', accent: '#FFD95A', nose: '#FF8FAB' }, clothing: { accessory: 'scarf' } };
  await R.page.evaluate(s => window.S.setCharacters(s), [spec]);
  const res = await R.page.evaluate(() => window.S.renderFrame([{ id: 'bobo', x: 540, y: 1340, scale: 0.9, side: 1, yaw: 0, arm_l: 18, arm_r: 18 }], {}));
  console.log(JSON.stringify({ ok: res.runs > 10, info: R.info, box: res.box, runs: res.runs, ms: Date.now() - t0 }));
  await R.browser.close();
  process.exit(res.runs > 10 ? 0 : 1);
}

const MAIN = process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
if (!MAIN) { /* imported as a module */ }
else if (process.argv.includes('--smoke')) smoke().catch(e => { console.error(String(e)); process.exit(1); });
else serve().catch(e => { process.stdout.write(JSON.stringify({ ok: false, error: String(e) }) + '\n'); process.exit(1); });
