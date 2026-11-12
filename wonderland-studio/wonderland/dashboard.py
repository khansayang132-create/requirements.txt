"""Read-only management dashboard, served on 127.0.0.1 only.

Every number on the page is read from the database when the page is requested; nothing is
simulated, cached or rounded into a nicer story. Empty states say what is missing ("no
analytics yet — YouTube not connected"), never show a zero that was not measured.

    python -m wonderland dashboard --port 8095     →  http://127.0.0.1:8095
"""

from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import finance

CSS = """
/* Direction: "studio call sheet" — warm paper, ink type, one meadow-green accent; production-board rows. */
:root{--paper:#FBF6EC;--card:#FFFFFF;--ink:#2E2840;--muted:#5F5873;--line:#E6DDCB;--accent:#2F7A4D;--warn:#9A5B00;--bad:#B3261E;
--good-bg:#E4F2E8;--warn-bg:#FBEFD9;--bad-bg:#FBE4E2;--r:14px;--s:16px;--font:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--mono:ui-monospace,"SF Mono",Menlo,monospace}
@media (prefers-color-scheme:dark){:root{--paper:#1B1824;--card:#25212F;--ink:#F2EEF8;--muted:#B9B2C8;--line:#3A3447;--accent:#7FD3A0;--warn:#F2C26B;
--bad:#FF8A80;--good-bg:#1F3328;--warn-bg:#3A2F1C;--bad-bg:#3D2224}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 var(--font)}
header{padding:20px var(--s) 8px;max-width:1200px;margin:0 auto}h1{font-size:1.6rem;margin:0}header p{margin:4px 0 0;color:var(--muted)}
nav{position:sticky;top:0;background:var(--paper);border-bottom:1px solid var(--line);z-index:2}
nav ul{list-style:none;display:flex;gap:4px;margin:0 auto;padding:6px var(--s);max-width:1200px;overflow-x:auto}
nav a{display:inline-flex;align-items:center;min-height:44px;padding:0 14px;border-radius:999px;color:var(--ink);text-decoration:none;font-weight:700;white-space:nowrap}
nav a:hover,nav a:focus-visible{background:var(--card);outline:2px solid var(--accent)}
main{max-width:1200px;margin:0 auto;padding:var(--s)}section{margin:0 0 28px}h2{font-size:1.25rem;margin:0 0 10px}h3{font-size:1rem;margin:0 0 6px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:14px}
.big{font-size:2rem;font-weight:800;line-height:1.1}.label{color:var(--muted);font-size:.9rem}
.table{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:var(--r)}
table{border-collapse:collapse;width:100%;font-size:.95rem}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:700}tr:last-child td{border-bottom:0}code,.mono{font-family:var(--mono);font-size:.85rem}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-weight:700;font-size:.85rem;white-space:nowrap}
.ok{background:var(--good-bg);color:var(--accent)}.wait{background:var(--warn-bg);color:var(--warn)}.bad{background:var(--bad-bg);color:var(--bad)}
.empty{color:var(--muted);font-style:italic}footer{max-width:1200px;margin:0 auto;padding:0 var(--s) 24px;color:var(--muted);font-size:.9rem}
"""
GOOD = {"published", "produced", "scheduled", "uploaded", "done", "success", "ok"}
BAD = {"failed", "rejected", "error", "degraded"}


def e(x) -> str:
    return html.escape("" if x is None else str(x))


def pill(text: str) -> str:
    cls = "ok" if text in GOOD else "bad" if text in BAD else "wait"
    return f'<span class="pill {cls}">{e(text)}</span>'


def table(headers: list[str], rows: list[list[str]], empty: str) -> str:
    if not rows:
        return f'<p class="empty">{e(empty)}</p>'
    head = "".join(f"<th scope=col>{e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="table"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def render(studio) -> str:
    db = studio.db
    eps = db.episodes(order="publish_at DESC")
    count = lambda st: sum(1 for x in eps if x["status"] == st)  # noqa: E731
    health = db.get("health") or {}
    last = db.get("last_cycle") or {}
    sp = finance.spent(studio)
    lim = finance.limits(studio)
    tiles = [("Published on YouTube", count("published")), ("Scheduled on YouTube", count("scheduled") + count("uploaded")),
             ("Ready (passed every gate)", count("produced")), ("In production", count("in_production") + count("planned")),
             ("Failed or skipped", count("failed") + count("skipped")), ("Needs you", db.scalar("SELECT COUNT(*) FROM tasks WHERE status='blocked'"))]
    overview = "".join(f'<div class="card"><div class="big">{n}</div><div class="label">{e(t)}</div></div>' for t, n in tiles)

    prod_rows = [[f"<span class=mono>{e(x['id'])}</span>", e(x["publish_at"]), e(x["title"] or "—"), e(x["format"] or "—"), pill(x["status"]),
                  e(f"{x['duration']:.1f}s" if x["duration"] else "—"), e((x["error"] or "")[:120])] for x in eps[:40]]
    pub_rows = [[f"<span class=mono>{e(x['id'])}</span>", e(x["title"]), pill(x["status"]),
                 f'<a href="https://youtu.be/{e(x["video_id"])}">{e(x["video_id"])}</a>' if x["video_id"] else "—",
                 e(x["youtube_status"] or "—"), e(x["verified_at"] or "not verified")] for x in eps if x["video_id"] or x["status"] == "produced"]
    blocked = [[f"<span class=mono>{e(t['key'])}</span>", e(t["error"])] for t in db.tasks("status='blocked'")]
    an = db.q("SELECT e.title, a.video_id, SUM(CASE WHEN metric='views' THEN value END) AS views, "
              "SUM(CASE WHEN metric='estimatedMinutesWatched' THEN value END) AS minutes, AVG(CASE WHEN metric='averageViewPercentage' THEN value END) AS avp, "
              "MAX(a.fetched_at) AS fetched FROM analytics a LEFT JOIN episodes e ON e.video_id=a.video_id GROUP BY a.video_id ORDER BY views DESC LIMIT 20")
    an_rows = [[e(r["title"] or r["video_id"]), e(int(r["views"] or 0)), e(round(r["minutes"] or 0, 1)), e(f"{r['avp']:.1f}%" if r["avp"] else "—"), e(r["fetched"])]
               for r in an]
    checks = [[e(c["name"]), pill("ok" if c["ok"] else c["level"]), e(c["detail"])] for c in health.get("checks", [])]
    events = [[e(r["ts"]), e(r["level"]), e(r["source"]), e(r["message"][:160])] for r in db.q("SELECT * FROM events ORDER BY id DESC LIMIT 15")]
    exp = db.q("SELECT name, variable, status, started_at, decision FROM experiments ORDER BY id DESC LIMIT 5")
    exp_rows = [[e(x["name"]), e(x["variable"]), pill(x["status"]), e(x["started_at"]), e(x["decision"] or "—")] for x in exp]

    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Wonderland Studio</title><style>{CSS}</style></head><body>
<header><h1>Wonderland Studio</h1><p>Publishing mode <strong>{e(studio.publish_mode)}</strong> · health {pill(health.get('status', 'not checked'))} ·
last cycle {e(last.get('at', 'never'))} ({e(last.get('ran', 0))} tasks)</p></header>
<nav aria-label="Sections"><ul><li><a href="#overview">Overview</a></li><li><a href="#production">Production</a></li><li><a href="#publishing">Publishing</a></li>
<li><a href="#analytics">Analytics</a></li><li><a href="#system">System</a></li></ul></nav>
<main>
<section id=overview><h2>Overview</h2><div class=grid>{overview}</div>
<h3 style="margin-top:16px">Needs you</h3>{table(["Task", "Why"], blocked, "Nothing is waiting for you.")}</section>
<section id=production><h2>Production</h2>{table(["Episode", "Slot (UTC)", "Title", "Format", "Status", "Length", "Note"], prod_rows, "No episodes planned yet: run python -m wonderland run-cycle.")}</section>
<section id=publishing><h2>Publishing</h2>{table(["Episode", "Title", "Status", "Video", "YouTube says", "Verified"], pub_rows, "Nothing uploaded. Uploads start when publishing mode is review or auto and YouTube is connected.")}</section>
<section id=analytics><h2>Analytics</h2>{table(["Video", "Views", "Minutes watched", "Avg. viewed", "Fetched"], an_rows, "No analytics yet. Numbers appear after videos are public and YouTube Analytics is connected. Nothing is estimated.")}
<h3 style="margin-top:16px">Experiments</h3>{table(["Name", "Variable", "Status", "Started", "Decision"], exp_rows, "No experiment has started.")}</section>
<section id=system><h2>System</h2><div class=grid>
<div class=card><div class=big>${sp['month_usd']:.2f}</div><div class=label>Spent this month (limit ${lim['monthly_usd_limit']:.2f})</div></div>
<div class=card><div class=big>{sp['month_compute_seconds'] / 60:.0f} min</div><div class=label>Compute time this month</div></div>
<div class=card><div class=big>{db.scalar("SELECT COUNT(*) FROM research")}</div><div class=label>Research entries</div></div></div>
<h3 style="margin-top:16px">Health checks</h3>{table(["Check", "Result", "Detail"], checks, "Health has not been checked yet.")}
<h3 style="margin-top:16px">Recent events</h3>{table(["Time", "Level", "Source", "Message"], events, "No events yet.")}</section>
</main><footer>Read-only. Every figure is read from the studio database ({e(studio.db.path)}) when this page loads.</footer></body></html>"""


def serve(studio, port: int = 8095) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] == "/api/status":
                from .__main__ import status
                body, ctype = json.dumps(status(studio), default=str).encode(), "application/json"
            elif self.path.split("?")[0] in ("/", "/index.html"):
                body, ctype = render(studio).encode(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    print(f"Wonderland dashboard on http://127.0.0.1:{port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
