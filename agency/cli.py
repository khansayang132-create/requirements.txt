"""Command line for the engineering agency.

    python -m agency run health            # plan + run a playbook, print the report
    python -m agency missions | show ID | report ID --out FILE
    python -m agency approve TASK_ID | cancel ID | retry ID | resume ID
    python -m agency roles | tools | playbooks
    python -m agency dashboard [--port 8790]

Exit codes for run/resume: 0 every task PASS, 1 a check failed, 2 blocked or waiting for approval.
"""
from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path

from . import orchestrator as orch
from .dashboard import serve
from .report import markdown
from .roles import ROLES, VERIFIER, playbooks_using
from .store import Store
from .tools import Toolbox

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "agency" / "out" / "agency.db"
EXIT = {"COMPLETED": 0, "FAILED": 1}


def _load_env(root: Path) -> None:
    """Read .env like the bot does, so AGENCY_LLM_* / OMNIROUTE_* keys reach llm_review. Never printed."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(root / ".env")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agency", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--root", type=Path, default=ROOT, help="repository the tools act on")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="plan and run a playbook")
    r.add_argument("playbook", choices=sorted(orch.PLAYBOOKS))
    r.add_argument("--concurrency", type=int, default=4)
    r.add_argument("--budget", type=int, default=50, help="max tool calls for the mission")
    for name in ("show", "report", "cancel", "retry", "resume"):
        p = sub.add_parser(name)
        p.add_argument("mission")
        if name == "report":
            p.add_argument("--out", type=Path)
        if name == "resume":
            p.add_argument("--concurrency", type=int, default=4)
    sub.add_parser("approve").add_argument("task")
    for name in ("missions", "roles", "tools", "playbooks"):
        sub.add_parser(name)
    d = sub.add_parser("dashboard")
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8790)
    a = ap.parse_args(argv)

    _load_env(a.root)
    toolbox = Toolbox(a.root)
    who = getpass.getuser()

    if a.cmd == "roles":
        for role in ROLES.values():
            used = ", ".join(playbooks_using(role.id, orch.PLAYBOOKS)) or "idle"
            print(f"{role.id:12} {role.title}\n{'':12} tools: {', '.join(sorted(role.tools))}; "
                  f"verified by {VERIFIER[role.id]}; playbooks: {used}")
        return 0
    if a.cmd == "tools":
        for t in toolbox.tools.values():
            params = ", ".join(f"{k}:{p.type.__name__}{'' if p.required else '?'}" for k, p in t.params.items())
            print(f"{t.name:18} [{t.permission}, {t.timeout:.0f}s{', approval' if t.requires_approval else ''}] "
                  f"({params}) {t.description}")
        return 0
    if a.cmd == "playbooks":
        for name, pb in orch.PLAYBOOKS.items():
            print(f"{name}: {pb.title}")
            for s in pb.steps:
                after = f" after {', '.join(s.after)}" if s.after else ""
                print(f"  {s.id:11} {s.role:12} {s.tool}{after}")
        return 0

    store = Store(a.db)
    if a.cmd == "missions":
        for m in store.missions():
            print(f"{m['id']}  {m['state']:15} {m['playbook']:8} {m['title']}")
        return 0
    if a.cmd == "run":
        mid = orch.plan(store, toolbox, a.playbook, call_budget=a.budget)
        print(f"mission {mid} planned; running with concurrency {a.concurrency}", flush=True)
        state = orch.Orchestrator(store, toolbox, a.concurrency).run(mid)
        print(markdown(store, mid))
        return EXIT.get(state, 2)
    if a.cmd == "resume":
        state = orch.Orchestrator(store, toolbox, a.concurrency).run(a.mission)
        print(markdown(store, a.mission))
        return EXIT.get(state, 2)
    if a.cmd in ("show", "report"):
        text = markdown(store, a.mission)
        if a.cmd == "report" and a.out:
            a.out.write_text(text)
            print(f"wrote {a.out}")
        else:
            print(text)
        return 0
    if a.cmd == "approve":
        orch.approve(store, a.task, who)
        print(f"approved {a.task}; run `python -m agency resume {store.task(a.task)['mission_id']}`")
        return 0
    if a.cmd == "cancel":
        orch.cancel(store, a.mission, who)
        print(f"cancelled {a.mission}")
        return 0
    if a.cmd == "retry":
        again = orch.retry(store, a.mission, who)
        print(json.dumps({"requeued": again}))
        return 0
    if a.cmd == "dashboard":
        srv = serve(store, toolbox, a.host, a.port)
        print(f"Engineering Command Center on http://{a.host}:{a.port} (read-only; Ctrl+C to stop)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    return 2
