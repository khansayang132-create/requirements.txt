"""Read-only control center: queue state, job history, QA results, finished videos, autopilot policy.

    python -m apex.cli dashboard --db out/jobs.db --policy out/autopilot.json   # http://127.0.0.1:8787

Read-only on purpose: it changes nothing, so it needs no login. It binds to 127.0.0.1 by default;
expose it beyond the machine only behind your own authentication. Videos are served only from the
`final` path a completed job recorded, never from a path in the URL.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .autopilot import jobs_created_today, load_policy
from .jobs import JobQueue

STYLE = """
:root{--bg:#f7f7f5;--fg:#17191c;--muted:#5f6670;--line:#dfe1e4;--card:#fff;--ok:#1d7a46;--bad:#b42318;--warn:#9a6700}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--fg:#e8eaed;--muted:#9aa1ab;--line:#2a2e34;--card:#1a1d21;
--ok:#4cc38a;--bad:#ff7b72;--warn:#e3b341}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;margin:0;padding:20px max(16px,4vw)}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:24px 0 8px}a{color:inherit}
.muted{color:var(--muted)}.grid{display:flex;flex-wrap:wrap;gap:10px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:110px}
.tile b{display:block;font-size:20px;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);font-weight:600}.wrap{overflow-x:auto}
.pill{font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;border:1px solid currentColor}
.COMPLETED,.PASS{color:var(--ok)}.FAILED,.CANCELLED,.FAIL{color:var(--bad)}
.RUNNING,.QUEUED,.RETRYING,.QUALITY_REVIEW,.WAITING_FOR_PROVIDER{color:var(--warn)}
video{max-width:320px;width:100%;border-radius:10px;background:#000}
"""


def _fmt(ts) -> str:
    return dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else "—"


def _page(title: str, body: str) -> bytes:
    return (f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,"
            f"initial-scale=1'><title>{html.escape(title)}</title><style>{STYLE}</style></head>"
            f"<body>{body}</body></html>").encode()


def overview(queue: JobQueue, policy_path: Path) -> bytes:
    e = html.escape
    policy = load_policy(policy_path)
    counts = queue.counts()
    tiles = "".join(f"<div class=tile><span class='{e(k)}'>{e(k)}</span><b>{v}</b></div>" for k, v in sorted(counts.items()))
    used = jobs_created_today(queue)
    state = "<span class='pill FAILED'>PAUSED (emergency stop)</span>" if policy.paused else "<span class='pill COMPLETED'>RUNNING</span>"
    rows = []
    for r in queue.db.execute("SELECT id, state, attempts, max_attempts, payload, last_error, updated_at FROM jobs "
                              "ORDER BY created_at DESC LIMIT 50"):
        topic = json.loads(r["payload"]).get("spec", {}).get("topic", "")
        rows.append(f"<tr><td><a href='/job/{e(r['id'])}'>{e(r['id'])}</a></td><td><span class='pill {e(r['state'])}'>"
                    f"{e(r['state'])}</span></td><td>{e(topic[:70])}</td><td>{r['attempts']}/{r['max_attempts']}</td>"
                    f"<td class=muted>{e(_fmt(r['updated_at']))}</td><td class=muted>{e((r['last_error'] or '')[:120])}</td></tr>")
    table = ("<div class=wrap><table><tr><th>Job</th><th>State</th><th>Topic</th><th>Attempts</th><th>Updated</th>"
             "<th>Last error</th></tr>" + ("".join(rows) or "<tr><td colspan=6 class=muted>No jobs yet. "
             "Queue one with <code>apex.cli enqueue</code> or <code>apex.cli plan</code>.</td></tr>") + "</table></div>")
    body = (f"<h1>APEX control center</h1><p class=muted>Read-only view of {e(str(queue.path))}</p>"
            f"<h2>Autopilot</h2><div class=grid><div class=tile>State<b>{state}</b></div>"
            f"<div class=tile>Jobs today<b>{used} / {policy.max_jobs_per_day}</b></div>"
            f"<div class=tile>Approval<b>{'required' if policy.require_approval else 'not required'}</b></div></div>"
            f"<h2>Queue</h2><div class=grid>{tiles or '<span class=muted>empty</span>'}</div>"
            f"<h2>Recent jobs</h2>{table}")
    return _page("APEX control center", body)


def job_page(queue: JobQueue, job_id: str) -> bytes | None:
    e = html.escape
    try:
        job = queue.get(job_id)
    except KeyError:
        return None
    events = "".join(f"<tr><td class=muted>{e(_fmt(ev['at']))}</td><td>{e(ev['from_state'] or '—')} → "
                     f"<span class='{e(ev['to_state'])}'>{e(ev['to_state'])}</span></td><td>{e(ev['detail'] or '')}</td></tr>"
                     for ev in queue.events(job_id))
    result = ""
    if job.result:
        qa = job.result.get("qa", {})
        final = job.result.get("final", {})
        result = (f"<h2>Result</h2><p>QA <span class='pill {'PASS' if qa.get('passed') else 'FAIL'}'>"
                  f"{'PASS' if qa.get('passed') else 'FAIL'}</span> technical score {e(str(qa.get('technical_score')))}"
                  f" · creative review: {e(str(qa.get('creative_review', {}).get('status')))}</p>"
                  f"<p class=muted>sha256 {e(str(final.get('sha256', '')))}</p>")
        if final.get("path") and Path(final["path"]).exists():
            result += f"<video controls preload=metadata src='/media/{e(job_id)}'></video>"
    body = (f"<p><a href='/'>← all jobs</a></p><h1>Job {e(job.id)}</h1>"
            f"<p><span class='pill {e(job.state.value)}'>{e(job.state.value)}</span> attempt {job.attempts}/"
            f"{job.max_attempts}</p><p>{e(job.payload.get('spec', {}).get('topic', ''))}</p>"
            + (f"<p class=FAILED>{e(job.last_error)}</p>" if job.last_error else "") + result +
            f"<h2>History</h2><div class=wrap><table><tr><th>When</th><th>Change</th><th>Detail</th></tr>{events}</table></div>")
    return _page(f"Job {job_id}", body)


def make_handler(db: Path, policy_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.send_header("x-content-type-options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _send_video(self, path: Path):
            """Serve with byte-range support: Safari won't play video without it, and seeking needs it."""
            data = path.read_bytes()
            size = len(data)
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("range", "").strip())
            if not m or (not m.group(1) and not m.group(2)):
                self.send_response(200)
                self.send_header("accept-ranges", "bytes")
                self.send_header("content-type", "video/mp4")
                self.send_header("content-length", str(size))
                self.end_headers()
                self.wfile.write(data)
                return
            if m.group(1):
                start, end = int(m.group(1)), int(m.group(2)) if m.group(2) else size - 1
            else:  # suffix range: the last N bytes
                start, end = max(0, size - int(m.group(2))), size - 1
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("content-range", f"bytes */{size}")
                self.send_header("content-length", "0")
                self.end_headers()
                return
            end = min(end, size - 1)
            chunk = data[start:end + 1]
            self.send_response(206)
            self.send_header("accept-ranges", "bytes")
            self.send_header("content-type", "video/mp4")
            self.send_header("content-range", f"bytes {start}-{end}/{size}")
            self.send_header("content-length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)

        def do_GET(self):  # noqa: N802
            queue = JobQueue(db)  # one connection per request: handlers run on separate threads
            path = self.path.split("?", 1)[0]
            if path == "/":
                return self._send(200, overview(queue, policy_path))
            if path == "/health":
                policy = load_policy(policy_path)
                return self._send(200, json.dumps({"ok": True, "paused": policy.paused, "counts": queue.counts()}).encode(),
                                  "application/json")
            m = re.fullmatch(r"/job/([0-9a-f]{6,32})", path)
            if m:
                page = job_page(queue, m.group(1))
                return self._send(200, page) if page else self._send(404, _page("Not found", "<p>No such job.</p>"))
            m = re.fullmatch(r"/media/([0-9a-f]{6,32})", path)
            if m:
                try:
                    final = (queue.get(m.group(1)).result or {}).get("final", {}).get("path")
                except KeyError:
                    final = None
                if final and Path(final).is_file():
                    return self._send_video(Path(final))
            return self._send(404, _page("Not found", "<p>Not found.</p>"))

        def log_message(self, *args):
            pass

    return Handler


def serve(db: Path, policy_path: Path, host: str = "127.0.0.1", port: int = 8787) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(Path(db), Path(policy_path)))
