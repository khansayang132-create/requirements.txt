"""Production control centre: a local web page over the real database and queue (stdlib only, 127.0.0.1).

Every number on the page is read from auravox.db, the engines table, /proc or nvidia-smi at request time; every
button calls the real queue. Nothing is mocked.
"""

from __future__ import annotations

import json
import mimetypes
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import production
from .queue import Queue, mem_available_mb

_worker = {"thread": None, "started": None}


def system_state() -> dict:
    load = None
    try:
        load = open("/proc/loadavg").read().split()[:3]
    except OSError:
        pass
    total = None
    try:
        total = int(next(ln for ln in open("/proc/meminfo") if ln.startswith("MemTotal")).split()[1]) // 1024
    except (OSError, StopIteration):
        pass
    gpu = "none detected"
    if shutil.which("nvidia-smi"):
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total", "--format=csv,noheader"],
                             capture_output=True, text=True).stdout.strip() or gpu
    import os
    return {"load": load, "cpu_cores": os.cpu_count(), "mem_total_mb": total, "mem_available_mb": round(mem_available_mb()), "gpu": gpu}


def state(studio) -> dict:
    db = studio.db
    jobs = db.q("SELECT id, kind, title, status, attempts, max_attempts, priority, created, started, finished, error FROM jobs ORDER BY id DESC LIMIT 200")
    prods = []
    for d in sorted((studio.home / "productions").glob("*")):
        files = [str(p.relative_to(studio.home)) for p in sorted(d.glob("*")) if p.is_file()]
        prods.append({"name": d.name, "files": files})
    takes = db.q("SELECT take_id, line_id, voice_id, kind, score, status, path, created FROM takes WHERE selected=1 ORDER BY created DESC LIMIT 30")
    for t in takes:
        t["path"] = str(Path(t["path"]).relative_to(studio.home)) if t["path"] and t["path"].startswith(str(studio.home)) else t["path"]
    return {"at": time.time(), "queue": Queue(studio).summary(), "jobs": jobs,
            "engines": db.q("SELECT name, status, detail, checked_at FROM engines ORDER BY name"),
            "models": db.q("SELECT key, engine, license, status, bytes FROM models"),
            "voices": db.q("SELECT voice_id, name, status, engine, model, profile_sha, approved_by FROM voices WHERE status != 'retired' ORDER BY voice_id"),
            "takes": takes, "productions": prods, "system": system_state(),
            "worker": {"running": bool(_worker["thread"] and _worker["thread"].is_alive()), "started": _worker["started"]},
            "events": db.q("SELECT at, job_id, level, msg FROM events ORDER BY id DESC LIMIT 25"),
            "skills": db.q("SELECT name, target, status FROM skills")}


def start_worker(studio, workers=2):
    if _worker["thread"] and _worker["thread"].is_alive():
        return False
    t = threading.Thread(target=lambda: Queue(studio).run(production.HANDLERS, workers=workers, until_idle=True, log=lambda *_: None), daemon=True)
    t.start()
    _worker.update(thread=t, started=time.time())
    return True


class Handler(BaseHTTPRequestHandler):
    studio = None

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=str).encode())

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if u.path == "/api/state":
            return self._json(state(self.studio))
        if u.path.startswith("/files/"):
            p = (self.studio.home / unquote(u.path[7:])).resolve()
            if not p.is_relative_to(self.studio.home.resolve()) or not p.is_file():
                return self._json({"error": "not found"}, 404)
            return self._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")
        if u.path.startswith("/api/export/"):
            name = unquote(u.path.rsplit("/", 1)[1])
            d = (self.studio.home / "productions" / name).resolve()
            if d.parent != (self.studio.home / "productions").resolve() or not d.is_dir():
                return self._json({"error": "not found"}, 404)
            z = shutil.make_archive(str(self.studio.home / "exports" / name), "zip", d)
            return self._send(200, Path(z).read_bytes(), "application/zip")
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        q = Queue(self.studio)
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] in ("cancel", "pause", "resume", "retry"):
            if not q.get(parts[2]):
                return self._json({"error": "no such job"}, 404)
            getattr(q, parts[3])(parts[2])
            return self._json(q.get(parts[2]))
        if parts == ["api", "worker", "start"]:
            return self._json({"started": start_worker(self.studio)})
        self._json({"error": "unknown action"}, 404)


def serve(studio, port: int = 8765, host: str = "127.0.0.1"):
    Handler.studio = studio
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"AURAVOX control centre on http://{host}:{port}")
    httpd.serve_forever()


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AURAVOX Control Centre</title>
<style>
/* Direction: "broadcast booth" - cool slate paper, ink, an on-air red for running/failed, signal teal for PASS.
   Layout idea: a sticky status rail of live meters over a jobs board and an asset column. */
:root { --bg:#F3F5F7; --panel:#FFFFFF; --ink:#16212B; --muted:#55626F; --line:#D9DFE5; --onair:#C4202F; --signal:#0B6E69; --amber:#8A5A00;
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px; --r:10px;
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; --mono: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace; }
@media (prefers-color-scheme: dark) { :root { --bg:#0D1319; --panel:#151D25; --ink:#E5ECF2; --muted:#9AA8B5; --line:#2A3540; --onair:#FF6B76; --signal:#4FD1C5; --amber:#F2B84B; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 var(--sans); }
header { position:sticky; top:0; z-index:2; background:var(--panel); border-bottom:1px solid var(--line); padding:var(--s3) var(--s4); }
.bar { display:flex; flex-wrap:wrap; align-items:center; gap:var(--s3) var(--s5); max-width:1280px; margin:0 auto; }
h1 { font-size:18px; margin:0; letter-spacing:.02em; }
h1 .dot { display:inline-block; width:10px; height:10px; border-radius:50%; background:var(--muted); margin-right:var(--s2); vertical-align:middle; }
h1 .dot.live { background:var(--onair); }
.meter { font:13px var(--mono); color:var(--muted); }
.meter b { color:var(--ink); font-weight:600; }
main { max-width:1280px; margin:0 auto; padding:var(--s4); display:grid; grid-template-columns: minmax(0,1.6fr) minmax(0,1fr); gap:var(--s4); }
@media (max-width: 900px) { main { grid-template-columns: minmax(0,1fr); } }
section { background:var(--panel); border:1px solid var(--line); border-radius:var(--r); padding:var(--s4); min-width:0; }
h2 { font-size:15px; margin:0 0 var(--s3); display:flex; justify-content:space-between; align-items:center; gap:var(--s2); }
h2 small { font-weight:400; color:var(--muted); font-size:13px; }
.scroll { overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th { text-align:left; color:var(--muted); font-weight:500; padding:var(--s1) var(--s2); border-bottom:1px solid var(--line); white-space:nowrap; }
td { padding:var(--s2); border-bottom:1px solid var(--line); vertical-align:top; }
td.id, .mono { font-family:var(--mono); font-size:12px; white-space:nowrap; }
.st { font:600 11px var(--mono); padding:2px 6px; border-radius:4px; border:1px solid currentColor; white-space:nowrap; }
.st.succeeded, .st.PASS, .st.approved { color:var(--signal); }
.st.failed, .st.FAIL, .st.running { color:var(--onair); }
.st.blocked, .st.BLOCKED, .st.paused, .st.auditioned { color:var(--amber); }
.st.queued, .st.cancelled, .st.design { color:var(--muted); }
.err { color:var(--muted); font-size:12px; max-width:280px; overflow-wrap:anywhere; }
button { font:inherit; font-size:13px; min-height:44px; min-width:44px; padding:0 var(--s3); border-radius:8px; border:1px solid var(--line);
  background:var(--panel); color:var(--ink); cursor:pointer; }
button.primary { background:var(--ink); color:var(--panel); border-color:var(--ink); }
button:focus-visible, a:focus-visible { outline:3px solid var(--signal); outline-offset:2px; }
.acts { display:flex; gap:var(--s1); flex-wrap:wrap; }
.stack { min-width:0; }
.stack > * + * { margin-top:var(--s4); }
audio { width:100%; height:36px; }
a { color:var(--signal); }
.empty { color:var(--muted); font-size:13px; margin:0; }
.files a { display:inline-block; margin:0 var(--s2) var(--s1) 0; font:12px var(--mono); padding:var(--s2) 0; }
</style>
</head>
<body>
<header><div class="bar">
  <h1><span class="dot" id="live"></span>AURAVOX Control Centre</h1>
  <span class="meter" id="queue">queue: loading</span>
  <span class="meter" id="sys">system: loading</span>
  <button class="primary" id="startw">Start worker</button>
</div></header>
<main>
  <div class="stack">
    <section><h2>Jobs <small id="jobsub"></small></h2><div class="scroll"><table id="jobs"><thead><tr><th>Job</th><th>Kind</th><th>Title</th><th>Status</th><th>Try</th><th>Error</th><th>Control</th></tr></thead><tbody></tbody></table></div></section>
    <section><h2>Recent events</h2><div class="scroll"><table id="events"><thead><tr><th>Time</th><th>Job</th><th>Message</th></tr></thead><tbody></tbody></table></div></section>
  </div>
  <div class="stack">
    <section><h2>Engines</h2><div class="scroll"><table id="engines"><thead><tr><th>Engine</th><th>Status</th><th>Evidence</th></tr></thead><tbody></tbody></table></div></section>
    <section><h2>Voices</h2><div class="scroll"><table id="voices"><thead><tr><th>Voice</th><th>Status</th><th>Engine</th><th>Hash</th></tr></thead><tbody></tbody></table></div></section>
    <section><h2>Productions</h2><div id="prods"></div></section>
    <section><h2>Selected takes</h2><div id="takes"></div></section>
    <section><h2>Models</h2><div class="scroll"><table id="models"><thead><tr><th>Model</th><th>Licence</th><th>Status</th></tr></thead><tbody></tbody></table></div></section>
  </div>
</main>
<script>
const $ = (s) => document.querySelector(s);
function el(tag, attrs, ...kids) { const e = document.createElement(tag); for (const [k, v] of Object.entries(attrs || {})) { if (k === 'class') e.className = v; else e.setAttribute(k, v); }
  for (const k of kids) e.append(k instanceof Node ? k : document.createTextNode(k == null ? '' : String(k))); return e; }
function badge(s) { return el('span', {class: 'st ' + s}, s); }
function rows(tbody, items, cells) { const tb = $(tbody + ' tbody'); tb.replaceChildren(...items.map(it => el('tr', {}, ...cells(it).map(c => c instanceof Node && c.tagName === 'TD' ? c : el('td', {}, c))))); }
function ago(t) { if (!t) return ''; const s = Math.round(Date.now() / 1000 - t); return s < 60 ? s + 's ago' : s < 3600 ? Math.round(s / 60) + 'm ago' : Math.round(s / 3600) + 'h ago'; }
async function act(id, a) { await fetch('/api/jobs/' + encodeURIComponent(id) + '/' + a, {method: 'POST'}); refresh(); }
function controls(j) { const b = []; const add = (a, label) => { const x = el('button', {type: 'button', 'aria-label': label + ' ' + j.id}, label); x.onclick = () => act(j.id, a); b.push(x); };
  if (j.status === 'queued') { add('pause', 'Pause'); add('cancel', 'Cancel'); }
  if (j.status === 'paused') { add('resume', 'Resume'); add('cancel', 'Cancel'); }
  if (['failed', 'blocked', 'cancelled'].includes(j.status)) add('retry', 'Retry');
  return el('td', {}, el('div', {class: 'acts'}, ...b)); }
async function refresh() {
  let s; try { s = await (await fetch('/api/state')).json(); } catch (e) { $('#queue').textContent = 'server unreachable'; return; }
  const q = s.queue; $('#queue').replaceChildren('queue: ', ...['running', 'queued', 'succeeded', 'blocked', 'failed'].flatMap(k => [el('b', {}, q[k] || 0), ' ' + k + '  ']));
  const sy = s.system; $('#sys').textContent = `load ${sy.load ? sy.load.join(' ') : 'n/a'} / ${sy.cpu_cores} cores · memory free ${sy.mem_available_mb} of ${sy.mem_total_mb} MB · GPU ${sy.gpu}`;
  $('#live').classList.toggle('live', !!(q.running)); $('#startw').textContent = s.worker.running ? 'Worker running' : 'Start worker'; $('#startw').disabled = s.worker.running;
  $('#jobsub').textContent = s.jobs.length + ' most recent';
  rows('#jobs', s.jobs, j => [el('td', {class: 'id'}, j.id), j.kind, j.title, badge(j.status), `${j.attempts}/${j.max_attempts}`, el('td', {class: 'err'}, j.error || ''), controls(j)]);
  rows('#events', s.events, e => [ago(e.at), el('td', {class: 'id'}, e.job_id || ''), el('td', {class: 'err'}, e.msg)]);
  rows('#engines', s.engines, e => [e.name, badge(e.status), el('td', {class: 'err'}, e.detail)]);
  rows('#voices', s.voices, v => [el('td', {}, v.name, el('br'), el('span', {class: 'mono'}, v.voice_id)), badge(v.status), `${v.engine || ''} ${v.model || ''}`, el('td', {class: 'id'}, v.profile_sha || '')]);
  rows('#models', s.models, m => [el('td', {class: 'id'}, m.key), m.license, badge(m.status)]);
  if (!s.models.length) $('#models tbody').replaceChildren(el('tr', {}, el('td', {colspan: 3, class: 'empty'}, 'No downloaded voice models yet. Piper voices come from huggingface.co: avx models install <key>.')));
  $('#prods').replaceChildren(...(s.productions.length ? s.productions.map(p => el('div', {class: 'files'}, el('strong', {}, p.name), ' ',
    el('a', {href: '/api/export/' + encodeURIComponent(p.name)}, 'export .zip'), el('br'), ...p.files.map(f => el('a', {href: '/files/' + f.split('/').map(encodeURIComponent).join('/')}, f.split('/').pop())),
    ...p.files.filter(f => f.endsWith('master.mp3')).map(f => el('audio', {controls: '', preload: 'none', src: '/files/' + f, 'aria-label': 'master of ' + p.name}))))
    : [el('p', {class: 'empty'}, 'No productions yet. Run avx produce SCREENPLAY --name NAME, then start the worker.')]));
  $('#takes').replaceChildren(...(s.takes.length ? s.takes.slice(0, 8).map(t => el('div', {}, el('span', {class: 'mono'}, `${t.line_id} · ${t.voice_id} · score ${t.score}`),
    el('audio', {controls: '', preload: 'none', src: '/files/' + t.path, 'aria-label': 'take ' + t.take_id}))) : [el('p', {class: 'empty'}, 'No selected takes yet.')]));
}
$('#startw').onclick = async () => { await fetch('/api/worker/start', {method: 'POST'}); refresh(); };
refresh(); setInterval(refresh, 2000);
</script>
</body>
</html>
"""
