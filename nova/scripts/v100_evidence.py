#!/usr/bin/env python3
"""Collect real evidence for one NOVA Studio production: API response, stage outputs, logs, file
metadata (ffprobe, sha256), database rows and scheduler records. Usage:
    v100_evidence.py <base_url> <data_dir> <production_id> <out_dir>"""
import hashlib
import json
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

base, data_dir, pid, out = sys.argv[1], Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
out.mkdir(parents=True, exist_ok=True)


def get(path):
    with urllib.request.urlopen(base + path, timeout=60) as r:
        return json.loads(r.read())


p = get(f"/api/v100/productions/{pid}")
(out / "production.json").write_text(json.dumps(p, ensure_ascii=False, indent=1))
(out / "logs.json").write_text(json.dumps(get(f"/api/v100/productions/{pid}/logs"), ensure_ascii=False, indent=1))
files = {}
for a in p["assets"]:
    path = Path(a["path"])
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                       "stream=codec_name,sample_rate,channels:format=duration,size,format_name",
                                       "-of", "json", str(path)], capture_output=True, text=True).stdout)
    dec = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    files[a["format"]] = {"path": str(path), "ffprobe": probe, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "db_sha256": a["sha256"], "full_decode_errors": dec.stderr.strip() or "none"}
for s in p["subtitles"]:
    files[f"subtitles.{s['format']}"] = {"path": s["path"], "bytes": Path(s["path"]).stat().st_size,
                                         "head": Path(s["path"]).read_text(encoding="utf-8")[:400]}
(out / "files.json").write_text(json.dumps(files, ensure_ascii=False, indent=1))
db = sqlite3.connect(data_dir / "studio.db")
db.row_factory = sqlite3.Row
rows = {t: [dict(r) for r in db.execute(q, (pid,))] for t, q in {
    "productions": "SELECT id, status, error, script_version_id, idempotency_key, job_run_id, created_at, updated_at FROM productions WHERE id=?",
    "production_stages": "SELECT stage, status, attempts, started_at, finished_at, error FROM production_stages WHERE production_id=?",
    "audio_assets": "SELECT format, bytes, duration_s, sample_rate, sha256 FROM audio_assets WHERE production_id=?",
    "audio_segments": "SELECT idx, emotion, start_s, end_s, text FROM audio_segments WHERE production_id=? ORDER BY idx",
    "quality_reports": "SELECT passed, created_at FROM quality_reports WHERE production_id=?",
    "job_runs": "SELECT * FROM job_runs WHERE production_id=?",
}.items()}
rows["scheduled_jobs"] = [dict(r) for r in db.execute("SELECT id, name, schedule, timezone, next_run_utc, last_status, idempotency_key FROM scheduled_jobs")]
(out / "db.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
summary = {"id": pid, "status": p["status"], "qa_passed": p["qa_passed"],
           "stages": {s["stage"]: s["status"] for s in p["stages"]},
           "files": {k: (v.get("ffprobe", {}).get("format", {}).get("duration"), v.get("sha256", "")[:12]) for k, v in files.items()}}
print(json.dumps(summary, ensure_ascii=False))
