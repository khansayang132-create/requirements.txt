"""Read-only Engineering Command Center: roles, playbooks, missions, task states, evidence and audit log.

    python -m agency dashboard            # http://127.0.0.1:8790

Everything shown is read from the SQLite store; there are no simulated statuses. It changes nothing, so it
needs no login, and it binds to 127.0.0.1. Actions (run, approve, cancel, retry) are CLI-only for now and the
page says so. All stored text (tool output, LLM reviews) is HTML-escaped: it is data, never markup.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .orchestrator import PLAYBOOKS, verdict
from .roles import ROLES, VERIFIER, playbooks_using
from .store import Store
from .tools import Toolbox

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
.pill{font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;border:1px solid currentColor;white-space:nowrap}
.COMPLETED,.PASS{color:var(--ok)}.FAILED,.CANCELLED,.FAIL{color:var(--bad)}
.RUNNING,.READY,.REVIEWING,.VERIFYING,.BLOCKED,.NEEDS_APPROVAL{color:var(--warn)}
pre{white-space:pre-wrap;word-break:break-word;background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:10px;max-height:340px;overflow:auto;font-size:12px}
details{margin:6px 0}code{font-size:12px}
"""
e = html.escape


def _ts(t) -> str:
    return dt.datetime.fromtimestamp(float(t), dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC") if t else "—"


def _pill(s: str) -> str:
    return f"<span class='pill {e(s)}'>{e(s)}</span>"


def _page(title: str, body: str) -> bytes:
    return (f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,"
            f"initial-scale=1'><title>{e(title)}</title><style>{STYLE}</style></head><body>{body}</body></html>"
            ).encode()


def overview(store: Store, toolbox: Toolbox) -> bytes:
    missions = store.missions()
    counts: dict[str, int] = {}
    for m in missions:
        counts[m["state"]] = counts.get(m["state"], 0) + 1
    tiles = "".join(f"<div class=tile><span class='{e(k)}'>{e(k)}</span><b>{v}</b></div>" for k, v in sorted(counts.items()))
    mrows = "".join(
        f"<tr><td><a href='/mission/{e(m['id'])}'>{e(m['id'])}</a></td><td>{e(m['playbook'])}</td>"
        f"<td>{_pill(m['state'])}</td><td>{e(m['title'])}</td><td>{_ts(m['updated_at'])}</td></tr>" for m in missions)
    rrows = "".join(
        f"<tr><td><b>{e(r.title)}</b><br><span class=muted>{e(r.mission)}</span></td>"
        f"<td>{', '.join(f'<code>{e(t)}</code>' for t in sorted(r.tools))}</td><td>{e(VERIFIER[r.id])}</td>"
        f"<td>{e(', '.join(playbooks_using(r.id, PLAYBOOKS))) or '<span class=muted>idle: no playbook yet</span>'}</td></tr>"
        for r in ROLES.values())
    trows = "".join(
        f"<tr><td><code>{e(t.name)}</code></td><td>{e(t.description)}</td><td>{e(t.permission)}</td>"
        f"<td>{t.timeout:.0f}s</td><td>{'yes' if t.requires_approval else 'no'}</td></tr>" for t in toolbox.tools.values())
    prows = "".join(f"<tr><td><code>{e(n)}</code></td><td>{e(p.title)}</td><td>{len(p.steps)}</td></tr>"
                    for n, p in PLAYBOOKS.items())
    body = (f"<h1>Engineering Command Center</h1><p class=muted>Read from {e(str(store.path))}. "
            "Run, approve, cancel and retry from the CLI (<code>python -m agency --help</code>); the page "
            "has no write actions yet.</p>"
            f"<h2>Missions</h2><div class=grid>{tiles or '<span class=muted>no missions yet</span>'}</div>"
            f"<div class=wrap><table><tr><th>Mission</th><th>Playbook</th><th>State</th><th>Title</th><th>Updated</th>"
            f"</tr>{mrows}</table></div>"
            f"<h2>Playbooks</h2><div class=wrap><table><tr><th>Name</th><th>Title</th><th>Steps</th></tr>{prows}"
            "</table></div>"
            f"<h2>Specialist roles ({len(ROLES)})</h2><div class=wrap><table><tr><th>Role</th><th>Permitted tools</th>"
            f"<th>Verified by</th><th>Used by</th></tr>{rrows}</table></div>"
            f"<h2>Tools</h2><div class=wrap><table><tr><th>Tool</th><th>What</th><th>Permission</th><th>Timeout</th>"
            f"<th>Approval</th></tr>{trows}</table></div>"
            "<h2>Not implemented</h2><p class=muted>Token cost for runs without provider usage data, deployment "
            "health, file editing by agents, MCP connections. See agency/STATUS.md.</p>")
    return _page("Engineering Command Center", body)


def mission_page(store: Store, mission_id: str) -> bytes:
    m = store.mission(mission_id)
    trows = "".join(
        f"<tr><td>{_pill(verdict(t))} {e(t['step'])}<br><span class=muted>{e(t['title'])}</span></td><td>{e(t['role'])} → "
        f"{e(t['verifier'])}</td><td><code>{e(t['tool'])}</code></td><td>{_pill(t['state'])}</td>"
        f"<td>{t['attempts']}/{t['max_attempts']}</td><td>{e(', '.join(json.loads(t['depends_on'])) or '—')}</td>"
        f"<td>{e(t['summary'] or '—')}<br><span class=muted>{e(t['verification'] or '')}</span></td></tr>"
        for t in store.tasks(mission_id))
    calls = "".join(
        f"<details><summary><code>{e(c['tool'])}</code> by {e(c['role'])} (task {e(c['task_id'])}, attempt "
        f"{c['attempt']}) → {_pill(c['status'])} exit {e(str(c['exit_code']))}, "
        f"{c['finished_at'] - c['started_at']:.1f}s — {e(c['summary'])}</summary>"
        f"<p class=muted>args {e(c['args'])}<br>evidence {e(c['evidence'][:600])}</p><pre>{e(c['output'])}</pre></details>"
        for c in store.calls(mission_id))
    events = "".join(f"<tr><td>{_ts(ev['at'])}</td><td>{e(ev['entity_id'])}</td><td>{e(ev['from_state'] or '—')} → "
                     f"{e(ev['to_state'])}</td><td>{e(ev['detail'] or '')}</td></tr>" for ev in store.events(mission_id))
    body = (f"<p><a href='/'>← all missions</a></p><h1>{e(m['id'])}: {e(m['title'])}</h1>"
            f"<p>{_pill(m['state'])} <span class=muted>playbook {e(m['playbook'])}, tool-call budget "
            f"{m['call_budget']}</span></p>"
            f"<h2>Tasks</h2><div class=wrap><table><tr><th>Step</th><th>Role → verifier</th><th>Tool</th>"
            f"<th>State</th><th>Attempts</th><th>After</th><th>Result</th></tr>{trows}</table></div>"
            f"<h2>Tool calls (audit log, redacted)</h2>{calls or '<p class=muted>none</p>'}"
            f"<h2>State history</h2><div class=wrap><table><tr><th>At</th><th>Entity</th><th>Transition</th>"
            f"<th>Detail</th></tr>{events}</table></div>")
    return _page(f"Mission {mission_id}", body)


def make_handler(store: Store, toolbox: Toolbox):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            try:
                if path == "/":
                    self._send(200, overview(store, toolbox))
                elif path == "/health":
                    self._send(200, json.dumps({"ok": True, "missions": len(store.missions())}).encode(),
                               "application/json")
                elif m := re.fullmatch(r"/mission/(m-[0-9a-f]{10})", path):
                    self._send(200, mission_page(store, m.group(1)))
                else:
                    self._send(404, _page("Not found", "<p>Not found. <a href='/'>Home</a></p>"))
            except KeyError:
                self._send(404, _page("Not found", "<p>No such mission. <a href='/'>Home</a></p>"))

        def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return Handler


def serve(store: Store, toolbox: Toolbox, host: str = "127.0.0.1", port: int = 8790) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(store, toolbox))
