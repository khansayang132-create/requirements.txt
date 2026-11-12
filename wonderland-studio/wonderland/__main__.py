"""Command line for the studio.  ``python -m wonderland <command>``

  status                 what is planned, produced, scheduled, published, blocked and failed
  worklist               completed / pending / blocked / failed tasks
  plan                   create today's and the buffer days' episodes (idempotent)
  run-cycle [--wait]     plan, then work the queue until nothing is runnable
                         (default --catch-up ignores the clock; --wait respects the daily schedule)
  daemon                 run-cycle every few minutes forever (phone / server)
  approve EP | reject EP REASON
  episode EP             everything about one episode, including its agent reports
  research [TEXT]        search the research database
  report [daily|weekly|monthly]
  health | backup | channel-kit | finance
  voices doctor | voices install
  dashboard [--port 8095]  read-only web page on 127.0.0.1
"""

from __future__ import annotations

import argparse
import sys
import time

from . import finance, ops
from .ceo import Studio


def _print(o) -> None:
    print(o if isinstance(o, str) else ops.dumps(o))


def status(studio: Studio) -> dict:
    eps = studio.db.episodes(order="publish_at")
    by: dict[str, int] = {}
    for e in eps:
        by[e["status"]] = by.get(e["status"], 0) + 1
    return {
        "publishing_mode": studio.publish_mode,
        "episodes": by,
        "next": [{"id": e["id"], "publish_at": e["publish_at"], "status": e["status"], "title": e["title"], "video": e["video_path"]}
                 for e in eps if e["status"] not in ("published", "failed", "skipped", "rejected")][:8],
        "needs_you": [{"task": t["key"], "why": t["error"]} for t in studio.db.tasks("status='blocked'")],
        "failed": [{"task": t["key"], "error": (t["error"] or "")[:200]} for t in studio.db.tasks("status='failed'", order="finished_at DESC")[:8]],
        "last_cycle": studio.db.get("last_cycle"),
        "health": (studio.db.get("health") or {}).get("status", "not checked yet"),
        "notifications_unread": studio.db.scalar("SELECT COUNT(*) FROM notifications WHERE delivered=0"),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m wonderland", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("status", "worklist", "plan", "health", "backup", "channel-kit", "finance"):
        sub.add_parser(name)
    rc = sub.add_parser("run-cycle")
    rc.add_argument("--wait", action="store_true", help="respect the daily schedule times")
    rc.add_argument("--max-minutes", type=float)
    rc.add_argument("--only", help="comma list of task kinds")
    d = sub.add_parser("daemon")
    d.add_argument("--interval", type=int, default=300)
    a = sub.add_parser("approve")
    a.add_argument("episode")
    r = sub.add_parser("reject")
    r.add_argument("episode")
    r.add_argument("reason")
    e = sub.add_parser("episode")
    e.add_argument("episode")
    rs = sub.add_parser("research")
    rs.add_argument("text", nargs="?", default="")
    rs.add_argument("--tag")
    rp = sub.add_parser("report")
    rp.add_argument("kind", nargs="?", default="daily", choices=["daily", "weekly", "monthly"])
    v = sub.add_parser("voices")
    v.add_argument("action", choices=["doctor", "install"])
    db_ = sub.add_parser("dashboard")
    db_.add_argument("--port", type=int, default=8095)
    args = p.parse_args(argv)

    studio = Studio()
    if args.cmd == "status":
        _print(status(studio))
    elif args.cmd == "worklist":
        _print(studio.worklist())
    elif args.cmd == "plan":
        _print(studio.plan())
    elif args.cmd == "run-cycle":
        kinds = args.only.split(",") if args.only else None
        res = studio.run_cycle(catch_up=not args.wait, max_seconds=args.max_minutes * 60 if args.max_minutes else None, kinds=kinds, log=print)
        _print({k: v for k, v in res.items() if k != "steps"})
        return 1 if res["by_status"].get("failed") else 0
    elif args.cmd == "daemon":
        while True:
            try:
                studio.run_cycle(catch_up=False, log=print)
            except Exception as exc:  # noqa: BLE001 - the daemon keeps going; the error is logged
                studio.db.log("error", "daemon", f"cycle crashed: {exc}", studio.now())
                print("cycle crashed:", exc, file=sys.stderr)
            time.sleep(args.interval)
    elif args.cmd == "approve":
        _print(studio.approve(args.episode)["id"] + " approved")
    elif args.cmd == "reject":
        _print(studio.reject(args.episode, args.reason)["id"] + " rejected")
    elif args.cmd == "episode":
        ep = studio.db.episode(args.episode)
        if not ep:
            print(f"no episode {args.episode}", file=sys.stderr)
            return 2
        ep["reports"] = studio.db.reports("episode_id=?", (args.episode,))
        ep["licences"] = studio.db.q("SELECT kind, name, origin, license, evidence FROM licences WHERE episode_id=?", (args.episode,))
        ep.pop("story", None)
        _print(ep)
    elif args.cmd == "research":
        from .departments.research import search
        _print(search(studio.db, args.text, args.tag))
    elif args.cmd == "report":
        print(ops.build_report(studio, args.kind)["body"])
    elif args.cmd == "health":
        _print(ops.health(studio))
    elif args.cmd == "backup":
        _print(str(ops.backup(studio)))
    elif args.cmd == "finance":
        _print(finance.summary(studio))
    elif args.cmd == "channel-kit":
        from .departments.seo import channel_seo
        _print(channel_seo(studio.universe))
    elif args.cmd == "voices":
        if args.action == "doctor":
            _print(studio.desk.doctor())
        else:
            from .audio.tts import install_kokoro
            _print(install_kokoro(studio.state / "models"))
    elif args.cmd == "dashboard":
        from .dashboard import serve
        serve(studio, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
