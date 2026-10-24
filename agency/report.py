"""Evidence-based mission report in Markdown: verdict per task, commands actually run, blockers."""
from __future__ import annotations

import datetime as dt
import json

from .orchestrator import verdict
from .store import Store


def _ts(t) -> str:
    return dt.datetime.fromtimestamp(float(t), dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def markdown(store: Store, mission_id: str, output_lines: int = 15) -> str:
    m = store.mission(mission_id)
    tasks = store.tasks(mission_id)
    calls = store.calls(mission_id)
    counts: dict[str, int] = {}
    for t in tasks:
        counts[verdict(t)] = counts.get(verdict(t), 0) + 1
    out = [f"# Mission {m['id']}: {m['title']}", "",
           f"- Playbook: `{m['playbook']}`; state **{m['state']}**; created {_ts(m['created_at'])}",
           "- Verdicts: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
           f"- Tool calls: {len(calls)} of a budget of {m['call_budget']}", "",
           "| Task | Role → verifier | Tool | Verdict | Result | Verification |",
           "|---|---|---|---|---|---|"]
    for t in tasks:
        out.append(f"| {t['step']} | {t['role']} → {t['verifier']} | `{t['tool']}` | **{verdict(t)}** | "
                   f"{(t['summary'] or '—').replace('|', '/')} | {(t['verification'] or '—').replace('|', '/')} |")
    out += ["", "## Commands actually executed", ""]
    for c in calls:
        argv = json.loads(c["evidence"]).get("argv")
        took = c["finished_at"] - c["started_at"]
        what = " ".join(argv) if argv else f"{c['tool']} (in-process)"
        out.append(f"- `{what}` → {c['status']}, exit {c['exit_code']}, {took:.1f}s (task {c['task_id']}, "
                   f"attempt {c['attempt']})")
    open_items = [t for t in tasks if verdict(t) != "PASS"]
    if open_items:
        out += ["", "## Not passing", ""]
        for t in open_items:
            last = [e for e in store.events(t["id"]) if e["entity_id"] == t["id"]][-1]
            out.append(f"### {t['step']} — {verdict(t)}")
            out.append(f"Last event: {last['to_state']}: {last['detail'] or ''}")
            call = store.last_call(t["id"])
            if call and call["output"].strip():
                tail = call["output"].strip().splitlines()[-output_lines:]
                out += ["```", *tail, "```"]
            out.append("")
    return "\n".join(out).rstrip() + "\n"
