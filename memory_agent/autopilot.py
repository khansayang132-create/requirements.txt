"""Autopilot: keep memory current without relying on Claude remembering to.

session_start (SessionStart hook): import the snapshot, print the context, and record a baseline (repo
fingerprint + last memory write) in .claude/memory/state.json (gitignored).

stop (Stop hook), every time Claude finishes a turn:
1. Export the snapshot. With CLAUDE_MEMORY_AUTOCOMMIT=1 and the snapshot changed, commit only that file
   ("memory: update snapshot"), never during a merge, rebase or cherry-pick and never on a detached HEAD.
   Nothing is pushed here.
2. If the repo changed since the baseline (new commits or edits) and no memory was written since, block the
   stop once with a reason that asks Claude to record the work. Claude's next stop has stop_hook_active set,
   and the baseline is moved on either way, so it never loops and never asks twice for the same state.
Every git call has a fixed argv and a timeout; a failure is reported on stderr and never breaks the session.
"""
import hashlib
import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

from .store import MemoryStore

SNAPSHOT_EXCLUDE = ":(exclude).claude/memory"
NUDGE = ("Memory autopilot: the repo changed since memory was last updated, and nothing was saved. Before "
         "stopping, record what a later session needs, using only verified results: "
         "memory_update_project_status (what is done, next action, blockers), memory_save for decisions with "
         "their reason, verified bug fixes or new tasks, and memory_update with state 'done' for finished tasks. "
         "Never save secrets. If nothing here is worth keeping (a trivial edit), say so in one line and stop.")


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=20,  # nosec B603 B607
                          check=False)


def repo_fingerprint(root: Path) -> str:
    """HEAD + uncommitted changes + untracked names, ignoring the memory folder itself."""
    parts = [git(root, "rev-parse", "HEAD").stdout,
             git(root, "diff", "HEAD", "--", ".", SNAPSHOT_EXCLUDE).stdout,
             git(root, "ls-files", "--others", "--exclude-standard", "--", ".", SNAPSHOT_EXCLUDE).stdout]
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def last_write(store: MemoryStore) -> int:
    return store.db.execute("SELECT COALESCE(MAX(id), 0) FROM history WHERE op != 'import'").fetchone()[0]


def state_path(store: MemoryStore) -> Path:
    return store.path.parent / "state.json"


def load_state(store: MemoryStore) -> dict:
    try:
        return json.loads(state_path(store).read_text())
    except (OSError, ValueError):
        return {}


def save_state(store: MemoryStore, root: Path) -> None:
    path = state_path(store)
    path.write_text(json.dumps({"fingerprint": repo_fingerprint(root), "last_write": last_write(store)}))


def autocommit(root: Path, snapshot: Path) -> str:
    for ref in ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD"):
        if git(root, "rev-parse", "-q", "--verify", ref).returncode == 0:
            return f"skipped: {ref} present"
    if git(root, "symbolic-ref", "-q", "HEAD").returncode != 0:
        return "skipped: detached HEAD"
    rel = os.path.relpath(snapshot, root)
    git(root, "add", "--", rel)
    if git(root, "diff", "--cached", "--quiet", "--", rel).returncode == 0:
        return "nothing to commit"
    res = git(root, "commit", "--only", "-m", "memory: update snapshot", "--", rel)
    return "committed" if res.returncode == 0 else f"commit failed: {res.stderr.strip()[:200]}"


def session_start(store: MemoryStore, root: Path, snapshot: Path | None) -> str:
    if snapshot:
        for err in store.import_snapshot(snapshot)["errors"][:5]:
            print(f"memory snapshot: skipped {err}", file=sys.stderr)
    text = store.context()
    save_state(store, root)
    return text


def stop(store: MemoryStore, root: Path, snapshot: Path | None, hook_input: dict) -> dict | None:
    """Returns the hook's JSON answer ({"decision": "block", ...}) or None to let Claude stop."""
    state = load_state(store)
    # Measured before the snapshot commit below, so the autopilot's own commit never counts as a change.
    changed = repo_fingerprint(root) != state.get("fingerprint")
    wrote = last_write(store) > state.get("last_write", 0)
    if snapshot:
        exported = store.export_snapshot(snapshot)
        if os.environ.get("CLAUDE_MEMORY_AUTOCOMMIT") == "1" and (exported["changed"] or exported["records"]):
            result = autocommit(root, snapshot)
            if result.startswith(("skipped", "commit failed")):
                print(f"memory autopilot: {result}", file=sys.stderr)
    save_state(store, root)  # the baseline moves on whatever happens: one nudge per change, never a loop
    if changed and not wrote and not hook_input.get("stop_hook_active") and state:
        return {"decision": "block", "reason": NUDGE}
    return None
