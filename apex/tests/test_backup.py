"""Backups of the queue database, policy and plan: consistent, hashed, verifiable, rotated."""
import json
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

from apex.autopilot import AutopilotPolicy, save_policy
from apex.backup import backup, verify
from apex.jobs import JobQueue

APEX_ROOT = Path(__file__).resolve().parent.parent


def test_backup_roundtrip_and_tamper_detection(tmp_path):
    q = JobQueue(tmp_path / "jobs.db")
    job = q.enqueue("k", "produce_video", {"spec": {"topic": "Tes backup"}})
    save_policy(AutopilotPolicy(paused=True), tmp_path / "autopilot.json")
    dest = backup(tmp_path / "jobs.db", tmp_path / "b", [tmp_path / "autopilot.json", tmp_path / "missing.json"])
    assert verify(dest) == []
    assert sorted(json.loads((dest / "manifest.json").read_text())["files"]) == ["autopilot.json", "jobs.db"]
    assert JobQueue(dest / "jobs.db").get(job.id).payload["spec"]["topic"] == "Tes backup"
    (dest / "autopilot.json").write_text("{}")
    assert verify(dest) == ["hash mismatch autopilot.json"]
    (dest / "jobs.db").unlink()
    assert "missing jobs.db" in verify(dest)


def test_backup_is_consistent_while_writing(tmp_path):
    db = tmp_path / "jobs.db"
    JobQueue(db)
    stop = threading.Event()

    def writer():
        wq = JobQueue(db)
        i = 0
        while not stop.is_set():
            wq.enqueue(f"k{i}", "produce_video", {"spec": {"topic": f"topik {i}"}})
            i += 1

    t = threading.Thread(target=writer)
    t.start()
    try:
        dests = [backup(db, tmp_path / "b", keep=0) for _ in range(5)]
    finally:
        stop.set()
        t.join()
    for d in dests:
        assert verify(d) == []
        con = sqlite3.connect(d / "jobs.db")
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_rotation_keeps_newest(tmp_path):
    JobQueue(tmp_path / "jobs.db")
    made = [backup(tmp_path / "jobs.db", tmp_path / "b", keep=3) for _ in range(5)]
    left = sorted(p.name for p in (tmp_path / "b").iterdir())
    assert left == sorted(p.name for p in made[-3:])


def test_cli_backup_and_verify(tmp_path):
    db = tmp_path / "jobs.db"
    JobQueue(db)
    (tmp_path / "plan.json").write_text("[]")
    run = lambda *a: subprocess.run([sys.executable, "-m", "apex.cli", *a], cwd=APEX_ROOT, capture_output=True, text=True)
    r = run("backup", "--db", str(db), "--plan", str(tmp_path / "plan.json"))
    assert r.returncode == 0, r.stderr
    dest = Path(json.loads(r.stdout)["backup"])
    assert dest.parent == tmp_path / "backups" and (dest / "plan.json").exists()
    assert run("verify-backup", "--dir", str(dest)).returncode == 0
    (dest / "plan.json").write_text("[1]")
    r = run("verify-backup", "--dir", str(dest))
    assert r.returncode == 1 and "hash mismatch plan.json" in r.stdout
