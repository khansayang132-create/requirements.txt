"""Command line for the engineering agency.

    python -m agency run health                         # plan + run a playbook, print the report
    python -m agency run change --param request="..." --param paths=bot.py --param branch=fix-x
    python -m agency run patch --param patch=@my.diff --param branch=fix-y [--param role=docs]
    python -m agency run ship --param branch=fix-x      # push agency/fix-x (needs approval)
    python -m agency ask "make /ping show the model"   # LLM planner -> plan waiting for approve-plan
    python -m agency missions | show ID | report ID --out FILE
    python -m agency approve TASK_ID | approve-plan ID | cancel ID | retry ID | resume ID
    python -m agency worker --every 3600 --playbook health
    python -m agency roles | tools | playbooks
    python -m agency dashboard [--port 8790] [--actions]

Exit codes for run/resume/ask: 0 every task PASS, 1 a check failed, 2 blocked or waiting for approval.
"""
from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path

from . import orchestrator as orch
from . import planner
from .dashboard import serve
from .providers import ProviderError, ProviderUnavailable
from .report import markdown
from .roles import ROLES, VERIFIER, playbooks_using
from .store import Store
from .tools import Toolbox
from .worker import Worker

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "agency" / "out" / "agency.db"
EXIT = {"COMPLETED": 0, "FAILED": 1}


def _load_env(root: Path) -> None:
    """Read .env like the bot does, so AGENCY_LLM_* / OMNIROUTE_* keys reach the LLM tools. Never printed."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(root / ".env")


def _params(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise SystemExit(f"--param needs name=value, got {pair!r}")
        out[key] = Path(value[1:]).read_text() if value.startswith("@") else value
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agency", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--root", type=Path, default=ROOT, help="repository the tools act on")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="plan and run a playbook")
    r.add_argument("playbook", choices=orch.playbook_names())
    r.add_argument("--param", action="append", default=[], help="name=value (value @file reads a file)")
    a = sub.add_parser("ask", help="LLM planner: plan a request from registered roles and tools")
    a.add_argument("request")
    for p in (r, a):
        p.add_argument("--concurrency", type=int, default=4)
        p.add_argument("--budget", type=int, default=50, help="max tool calls for the mission")
    for name in ("show", "report", "cancel", "retry", "resume", "approve-plan"):
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
    d.add_argument("--actions", action="store_true", help="enable CSRF-protected buttons")
    w = sub.add_parser("worker", help="resume approved missions and run a playbook on a schedule")
    w.add_argument("--playbook", choices=orch.playbook_names(), default=None)
    w.add_argument("--every", type=float, default=3600, help="seconds between scheduled runs")
    w.add_argument("--poll", type=float, default=30, help="seconds between checks for resumable missions")
    w.add_argument("--once", action="store_true", help="one iteration, then exit")
    args = ap.parse_args(argv)

    _load_env(args.root)
    toolbox = Toolbox(args.root)
    who = getpass.getuser()
    prices = toolbox.config.get("token_prices_per_million", {})

    if args.cmd == "roles":
        for role in ROLES.values():
            used = ", ".join(playbooks_using(role.id, orch.PLAYBOOKS)) or "planner / ask only"
            owns = f"; owns {', '.join(role.owns)}" if role.owns else ""
            print(f"{role.id:12} {role.title}\n{'':12} tools: {', '.join(sorted(role.tools))}; "
                  f"verified by {VERIFIER[role.id]}; playbooks: {used}{owns}")
        return 0
    if args.cmd == "tools":
        for t in toolbox.tools.values():
            params = ", ".join(f"{k}:{p.type.__name__}{'' if p.required else '?'}" for k, p in t.params.items())
            print(f"{t.name:18} [{t.permission}, {t.timeout:.0f}s{', approval' if t.requires_approval else ''}] "
                  f"({params}) {t.description}")
        return 0
    if args.cmd == "playbooks":
        for name in orch.playbook_names():
            pb = orch.PLAYBOOKS.get(name) or orch.dynamic_playbook(name, toolbox)
            assert pb is not None
            print(f"{name}: {pb.title}")
            for s in pb.steps:
                after = f" after {', '.join(s.after)}" if s.after else ""
                print(f"  {s.id:11} {s.role:12} {s.tool}{after}")
        return 0

    store = Store(args.db)
    try:
        return _stateful(args, store, toolbox, who, prices)
    except orch.PlanError as e:
        print(f"plan rejected: {e}")
        return 2


def _stateful(args, store: Store, toolbox: Toolbox, who: str, prices: dict) -> int:
    if args.cmd == "missions":
        for m in store.missions():
            print(f"{m['id']}  {m['state']:15} {m['playbook']:12} {m['title']}")
        return 0
    if args.cmd == "run":
        mid = orch.plan(store, toolbox, args.playbook, call_budget=args.budget, params=_params(args.param))
        print(f"mission {mid} planned; running with concurrency {args.concurrency}", flush=True)
        state = orch.Orchestrator(store, toolbox, args.concurrency).run(mid)
        print(markdown(store, mid, prices=prices))
        return EXIT.get(state, 2)
    if args.cmd == "ask":
        try:
            provider = toolbox.provider_factory(toolbox.env)
            pb, llm_usage = planner.propose(args.request, toolbox, provider)
        except (ProviderUnavailable, ProviderError, orch.PlanError) as e:
            print(f"planner: {e}")
            return 2
        mid = orch.plan_steps(store, toolbox, "llm", pb, args.budget, requires_approval=True,
                              planner_usage=llm_usage)
        print(markdown(store, mid, prices=prices))
        print(f"Plan saved, not run. Check the steps above, then: python -m agency approve-plan {mid}")
        return 2
    if args.cmd == "approve-plan":
        orch.approve_mission(store, args.mission, who)
        print(f"plan approved; run `python -m agency resume {args.mission}`")
        return 0
    if args.cmd == "resume":
        state = orch.Orchestrator(store, toolbox, args.concurrency).run(args.mission)
        print(markdown(store, args.mission, prices=prices))
        return EXIT.get(state, 2)
    if args.cmd in ("show", "report"):
        text = markdown(store, args.mission, prices=prices)
        if args.cmd == "report" and args.out:
            args.out.write_text(text)
            print(f"wrote {args.out}")
        else:
            print(text)
        return 0
    if args.cmd == "approve":
        orch.approve(store, args.task, who)
        print(f"approved {args.task}; run `python -m agency resume {store.task(args.task)['mission_id']}`")
        return 0
    if args.cmd == "cancel":
        orch.cancel(store, args.mission, who)
        print(f"cancelled {args.mission}")
        return 0
    if args.cmd == "retry":
        print(json.dumps({"requeued": orch.retry(store, args.mission, who)}))
        return 0
    if args.cmd == "worker":
        wk = Worker(store, toolbox, args.playbook, args.every)
        if args.once:
            for mid, state in wk.tick():
                print(f"{mid}: {state}")
            return 0
        wk.forever(poll=args.poll)
        return 0
    if args.cmd == "dashboard":
        srv = serve(store, toolbox, args.host, args.port, actions=args.actions)
        mode = "actions enabled" if args.actions else "read-only"
        print(f"Engineering Command Center on http://{args.host}:{args.port} ({mode}; Ctrl+C to stop)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    return 2
