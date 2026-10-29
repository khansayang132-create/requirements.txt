"""Evidence-based mission report in Markdown: verdict per task, commands actually run, blockers."""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from .orchestrator import verdict
from .store import Store


def _ts(t) -> str:
    return dt.datetime.fromtimestamp(float(t), dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def usage(store: Store, mission_id: str, prices: dict | None = None) -> dict:
    """LLM usage from provider-reported numbers only (tool evidence + planner). Cost only with a known price."""
    rows = [json.loads(c["evidence"]) for c in store.calls(mission_id)]
    planner = store.mission(mission_id)["planner_usage"]
    if planner:
        rows.append(json.loads(planner))
    total: dict[str, Any] = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0, "unpriced_models": []}
    for ev in rows:
        if not ev.get("llm_calls"):
            continue
        p, c = ev.get("prompt_tokens") or 0, ev.get("completion_tokens") or 0
        total["llm_calls"] += ev["llm_calls"]
        total["prompt_tokens"] += p
        total["completion_tokens"] += c
        price = (prices or {}).get(ev.get("model") or "")
        if price:
            total["cost"] += p / 1e6 * price["input"] + c / 1e6 * price["output"]
        elif ev.get("model") not in total["unpriced_models"]:
            total["unpriced_models"].append(ev.get("model"))
    total["cost"] = round(total["cost"], 6) if not total["unpriced_models"] else None
    return total


def markdown(store: Store, mission_id: str, output_lines: int = 15, prices: dict | None = None) -> str:
    m = store.mission(mission_id)
    tasks = store.tasks(mission_id)
    calls = store.calls(mission_id)
    counts: dict[str, int] = {}
    for t in tasks:
        counts[verdict(t)] = counts.get(verdict(t), 0) + 1
    out = [f"# Mission {m['id']}: {m['title']}", "",
           f"- Playbook: `{m['playbook']}`; state **{m['state']}**; created {_ts(m['created_at'])}",
           "- Verdicts: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
           f"- Tool calls: {len(calls)} of a budget of {m['call_budget']}", *_usage_line(store, mission_id, prices),
           *([f"- Plan approval: {m['approved_by'] or 'pending'}"] if m["requires_approval"] else []), "",
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
    branches = [json.loads(c["evidence"]).get("branch") for c in calls if c["tool"] == "apply_patch"
                and c["status"] == "PASS"]
    if branches:
        out += ["", "## Branches created", "", *[f"- `{b}` (local; push with `run ship --param branch=...`)"
                                                for b in branches]]
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


def _usage_line(store: Store, mission_id: str, prices: dict | None) -> list[str]:
    u = usage(store, mission_id, prices)
    if not u["llm_calls"]:
        return []
    cost = f"${u['cost']:.4f}" if u["cost"] is not None else f"cost unknown (no price for {u['unpriced_models']})"
    return [f"- LLM: {u['llm_calls']} call(s), {u['prompt_tokens']} prompt + {u['completion_tokens']} completion "
            f"tokens (provider-reported), {cost}"]
