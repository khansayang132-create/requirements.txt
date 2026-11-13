"""Non-stop production: when the queue is empty, plan the next episode from the APPROVED concept list.

    python -m agency produce-next            # plan (and run) one episode if there is an approved, unproduced concept
    python -m agency worker --autoproduce    # the worker does this whenever it has nothing else to do

Rules:
- Only concepts with "approved": true in agency/production-concepts.json are produced. The owner edits that file;
  nothing here approves a concept, invents a new story idea, or publishes anything.
- No duplicate episodes: an episode id that already has a delivered final (a COMPLETED cartoon mission, or the
  `productions` record) or a mission still queued/running is skipped.
- Disk guard: nothing is planned with less than MIN_FREE_GB free; the reason is recorded.
- Every decision (planned, skipped, blocked) is a row in `productions`, so the dashboard shows why.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import orchestrator as orch
from .store import Store
from .tools import Toolbox

CONCEPTS = Path(__file__).with_name("production-concepts.json")
MIN_FREE_GB = 2.0
SCHEMA = """
CREATE TABLE IF NOT EXISTS productions (
  episode TEXT PRIMARY KEY, job TEXT NOT NULL, mission_id TEXT, state TEXT NOT NULL, concept TEXT, at REAL NOT NULL,
  detail TEXT);
CREATE TABLE IF NOT EXISTS production_events (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, kind TEXT, detail TEXT);
"""


def _log(store: Store, kind: str, detail: str) -> None:
    store.db.execute("INSERT INTO production_events (at, kind, detail) VALUES (?,?,?)", (store.clock(), kind, detail))


def concepts(path: Path = CONCEPTS) -> list[dict]:
    data = json.loads(path.read_text()) if path.exists() else {"concepts": []}
    return [c for c in data.get("concepts", []) if c.get("approved") is True]


def _studio_done(root: Path) -> set[str]:
    """Episodes Cartoon Studio delivered outside this queue (its own job records with QC PASS and a final file)."""
    done = set()
    for sp in (root / "cartoon-studio" / "jobs").glob("*/state.json"):
        try:
            st = json.loads(sp.read_text())
        except (OSError, ValueError):
            continue
        if st.get("qc_status") == "PASS" and st.get("final_video") and Path(st["final_video"]).is_file():
            done.add(st["episode_id"])
    return done


def pending(store: Store, toolbox: Toolbox, concept_file: Path = CONCEPTS) -> list[str]:
    """Approved concepts that have not been produced or queued yet, in order."""
    store.db.executescript(SCHEMA)
    done = _produced(store) | _studio_done(toolbox.root)
    eps = [f"{c['universe']}-{c['plot']}-{c.get('seed', '1')}" for c in concepts(concept_file)]
    return [e for e in eps if e not in done]


def _produced(store: Store) -> set[str]:
    rows = store.db.execute("SELECT episode FROM productions WHERE state IN ('QUEUED','RUNNING','COMPLETED')").fetchall()
    done = {r["episode"] for r in rows}
    for m in store.db.execute("SELECT params, state FROM missions WHERE playbook='cartoon'").fetchall():
        p = json.loads(m["params"] or "{}")
        if m["state"] in ("COMPLETED", "READY", "RUNNING", "PLANNED") and p.get("episode"):
            done.add(p["episode"])
    return done


def _next_job(store: Store, studio: Path) -> str:
    used = {r["job"] for r in store.db.execute("SELECT job FROM productions").fetchall()}
    used |= {p.name for p in (studio / "jobs").glob("ep*")}
    n = 1
    while f"ep{n:03d}" in used:
        n += 1
    return f"ep{n:03d}"


def sync(store: Store) -> None:
    """Mirror cartoon missions' outcome into `productions` (COMPLETED / FAILED / BLOCKED)."""
    for r in store.db.execute("SELECT episode, mission_id FROM productions WHERE state IN ('QUEUED','RUNNING')").fetchall():
        if r["mission_id"]:
            st = store.mission(r["mission_id"])["state"]
            new = {"COMPLETED": "COMPLETED", "FAILED": "FAILED", "BLOCKED": "BLOCKED", "CANCELLED": "CANCELLED",
                   "RUNNING": "RUNNING"}.get(st)
            if new:
                store.db.execute("UPDATE productions SET state=?, at=? WHERE episode=?", (new, store.clock(), r["episode"]))


def plan_next(store: Store, toolbox: Toolbox, concept_file: Path = CONCEPTS) -> str | None:
    """Plan one cartoon mission for the next approved, unproduced concept. Returns the mission id or None."""
    store.db.executescript(SCHEMA)
    sync(store)
    busy = store.db.execute("SELECT COUNT(*) FROM missions WHERE state IN ('READY','RUNNING')").fetchone()[0]
    if busy:
        return None
    free = shutil.disk_usage(toolbox.root).free / 1e9
    if free < MIN_FREE_GB:
        _log(store, "blocked", f"only {free:.1f} GB free (< {MIN_FREE_GB} GB); nothing planned")
        return None
    done = _produced(store) | _studio_done(toolbox.root)
    studio = toolbox.root / "cartoon-studio"
    for c in concepts(concept_file):
        episode = f"{c['universe']}-{c['plot']}-{c.get('seed', '1')}"
        if episode in done:
            continue
        job = _next_job(store, studio)
        mid = orch.plan(store, toolbox, "cartoon", params={"job": job, "universe": c["universe"], "episode": episode,
                                                            "plot": c["plot"], "seed": str(c.get("seed", "1"))})
        store.db.execute("INSERT OR REPLACE INTO productions (episode, job, mission_id, state, concept, at, detail) "
                         "VALUES (?,?,?,?,?,?,?)", (episode, job, mid, "QUEUED", c["plot"], store.clock(),
                                                    c.get("note", "")))
        _log(store, "planned", f"{job}: {episode} from approved concept {c['plot']}")
        return mid
    _log(store, "idle", "every approved concept is produced or queued; waiting for the owner to approve more")
    return None


def status(store: Store) -> dict:
    store.db.executescript(SCHEMA)
    sync(store)
    rows = [dict(r) for r in store.db.execute("SELECT * FROM productions ORDER BY at DESC").fetchall()]
    ev = [dict(r) for r in store.db.execute("SELECT * FROM production_events ORDER BY id DESC LIMIT 20").fetchall()]
    return {"productions": rows, "events": ev, "at": time.time()}
