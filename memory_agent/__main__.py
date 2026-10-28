
"""CLI for the Claude Memory Agent.

  python3 -m memory_agent serve                 MCP server on stdio (what .mcp.json starts)
  python3 -m memory_agent context               SessionStart hook: import the snapshot, print the session summary
  python3 -m memory_agent export                Stop hook: write the git snapshot (only rewrites on change)
  python3 -m memory_agent import [FILE]         merge a snapshot into the database
  python3 -m memory_agent search QUERY          search (this project + global)
  python3 -m memory_agent list [--kind K]       list
  python3 -m memory_agent show ID               one record
  python3 -m memory_agent add --kind K --title T --content C [--key K] [--tags a,b] [--scope global]
  python3 -m memory_agent delete ID --yes       delete one record
  python3 -m memory_agent purge-project NAME --confirm NAME
  python3 -m memory_agent backup [NAME] | restore FILE --yes | doctor | stats

Database: CLAUDE_MEMORY_DB (default <repo>/.claude/memory/memory.db, gitignored).
Snapshot: CLAUDE_MEMORY_SNAPSHOT (default <repo>/.claude/memory/snapshot.jsonl, committed; "" turns it off).
Project:  CLAUDE_MEMORY_PROJECT (default owner/repo from the git remote).
"""
import argparse
import json
import os
import sys
from pathlib import Path

from . import security as sec
from .store import MemoryStore, NotFound, StorageError, project_root


def snapshot_path() -> Path | None:
    value = os.environ.get("CLAUDE_MEMORY_SNAPSHOT")
    if value == "":
        return None
    return Path(value) if value else project_root() / ".claude" / "memory" / "snapshot.jsonl"


def out(obj) -> None:
    print(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="memory_agent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", help="project id (default: owner/repo of this git repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    sub.add_parser("context")
    sub.add_parser("export")
    p = sub.add_parser("import")
    p.add_argument("file", nargs="?")
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)
    p = sub.add_parser("list")
    p.add_argument("--kind")
    p.add_argument("--state")
    p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("show")
    p.add_argument("id", type=int)
    p = sub.add_parser("add")
    p.add_argument("--kind", required=True, choices=sec.KINDS)
    p.add_argument("--title", required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--scope", default="project", choices=sec.SCOPES)
    p.add_argument("--key")
    p.add_argument("--tags", default="")
    p.add_argument("--source", default="cli")
    p.add_argument("--confidence", default="confirmed", choices=sec.CONFIDENCE)
    p.add_argument("--importance", type=int, default=3)
    p.add_argument("--state", choices=sec.TASK_STATES)
    p.add_argument("--private", action="store_true")
    p = sub.add_parser("delete")
    p.add_argument("id", type=int)
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("purge-project")
    p.add_argument("name")
    p.add_argument("--confirm", default="")
    p = sub.add_parser("backup")
    p.add_argument("name", nargs="?")
    p = sub.add_parser("restore")
    p.add_argument("file")
    p.add_argument("--yes", action="store_true")
    sub.add_parser("doctor")
    sub.add_parser("stats")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        from .mcp_server import Server, serve
        serve(server=Server(lambda: MemoryStore(project=a.project)))
        return 0

    # Hooks must never break a session: report the problem in one line and carry on.
    if a.cmd in ("context", "export"):
        try:
            store = MemoryStore(project=a.project)
            snap = snapshot_path()
            if a.cmd == "context":
                if snap:
                    res = store.import_snapshot(snap)
                    for err in res["errors"][:5]:
                        print(f"memory snapshot: skipped {err}", file=sys.stderr)
                out(store.context())
            elif snap:
                store.export_snapshot(snap)
            return 0
        except (StorageError, sec.ValidationError, OSError) as e:
            print(f"Claude Memory Agent unavailable: {sec.redact(str(e))}", file=sys.stderr)
            return 1

    try:
        store = MemoryStore(project=a.project)
        if a.cmd == "import":
            src = Path(a.file) if a.file else snapshot_path()
            out(store.import_snapshot(src) if src else {"imported": 0})
        elif a.cmd == "search":
            for d in store.search(a.query, limit=a.limit):
                out(f"#{d['id']} [{d['kind']}/{d['status']}] {d['title']} (score {d['score']}): {d['content'][:200]}")
        elif a.cmd == "list":
            for d in store.list_memories(kind=a.kind, state=a.state, limit=a.limit):
                state = f" ({d['state']})" if d["state"] else ""
                out(f"#{d['id']} [{d['kind']}/{d['status']}]{state} {d['title']}")
        elif a.cmd == "show":
            out(store.get(a.id))
        elif a.cmd == "add":
            out(store.save(a.title, a.content, kind=a.kind, scope=a.scope, key=a.key, tags=a.tags, source=a.source,
                           confidence=a.confidence, importance=a.importance, state=a.state, private=a.private))
        elif a.cmd == "delete":
            if not a.yes:
                out(store.get(a.id))
                print("Not deleted. Re-run with --yes to delete this memory.", file=sys.stderr)
                return 2
            store.delete(a.id)
            out({"deleted": a.id})
        elif a.cmd == "purge-project":
            out({"deleted": store.purge_project(a.name, a.confirm)})
        elif a.cmd == "backup":
            out({"backup": str(store.backup(a.name))})
        elif a.cmd == "restore":
            if not a.yes:
                print(f"This replaces {store.path} with {a.file} (current data is backed up first). Re-run with --yes.",
                      file=sys.stderr)
                return 2
            out({"restored_from": a.file, "previous_data_backed_up_to": str(store.restore(a.file))})
        elif a.cmd == "doctor":
            res = store.doctor()
            out(res)
            return 0 if res["ok"] else 1
        elif a.cmd == "stats":
            out(store.stats())
        return 0
    except (StorageError, sec.ValidationError, NotFound) as e:
        print(f"Error: {sec.redact(str(e))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
