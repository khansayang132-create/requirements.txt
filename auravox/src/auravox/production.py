"""Dialogue production: screenplay -> job graph -> takes -> evaluation/refinement -> assembly -> lip-sync data.

The refinement loop never edits a source file: every take and every processed version is a new file and a new row
in `takes`, linked to its parent. A line that cannot pass within its attempt budget is BLOCKED with its reasons.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

import numpy as np

from . import analysis, perform, voices
from .engines.base import SR, MissingModel, Unsupported, sha256, write_wav
from .queue import Blocked, Queue

TAKES = 3
MAX_ATTEMPTS = 6


# ------------------------------------------------------------------------------------------------ parsing
def parse_screenplay(path: Path) -> dict:
    """HUMANVERSE screenplay.json, or text lines `NAME (emotion): text` with `# SCENE id` headings."""
    p = Path(path)
    if p.suffix == ".json":
        sp = json.loads(p.read_text())
        lines = [ln | {"scene_id": s["scene_id"]} for s in sp["scenes"] for ln in s["lines"]]
        return {"title": sp.get("title", p.stem), "lines": lines}
    lines, scene, n = [], "S01", 0
    for raw in p.read_text().splitlines():
        if raw.startswith("# SCENE"):
            scene = raw.split()[-1]
            continue
        m = re.match(r"^\s*([A-Z0-9_-]+)\s*(?:\(([^)]+)\))?\s*:\s*(.+)$", raw)
        if m:
            n += 1
            lines.append({"line_id": f"L{n:02d}", "character_id": m.group(1), "emotion": (m.group(2) or "neutral").strip(), "text": m.group(3).strip(),
                          "scene_id": scene})
    return {"title": p.stem, "lines": lines}


# ------------------------------------------------------------------------------------------------ takes
def _record(studio, job_id, line, vid, sha, version, kind, path, settings, metrics, parent=None, status="candidate"):
    tid = studio.db.next_id("AVX-TAKE")
    studio.db.insert("takes", {"take_id": tid, "job_id": job_id, "line_id": line["line_id"], "voice_id": vid, "profile_sha": sha, "version": version,
                               "kind": kind, "path": str(path), "sha256": sha256(path), "settings": settings, "metrics": metrics,
                               "defects": metrics["defects"], "score": metrics["score"], "status": status, "parent_take": parent, "created": time.time()})
    return tid


def process(src: Path, dst: Path, fixes: list[str]) -> Path:
    """Non-destructive processing: trim edges (keep 80 ms), remove DC, set peak to -1 dBFS, 48 kHz mono."""
    x, sr, ch = analysis.read_wav(src)
    x = x.mean(axis=1) if x.ndim == 2 else x
    if sr != SR:
        x = np.interp(np.arange(int(len(x) * SR / sr)) * sr / SR, np.arange(len(x)), x).astype(np.float32)
    if "highpass" in fixes or "dc_offset" in fixes:
        x = x - float(x.mean())
    if "trim" in fixes:
        hop = int(SR * 0.02)
        fr = np.sqrt((x[: len(x) // hop * hop].reshape(-1, hop) ** 2).mean(axis=1) + 1e-12)
        thr = max(np.percentile(fr, 10) * 4, 10 ** (-42 / 20))
        v = np.nonzero(fr > thr)[0]
        if len(v):
            a = max(0, v[0] * hop - int(0.08 * SR))
            b = min(len(x), (v[-1] + 1) * hop + int(0.12 * SR))
            x = x[a:b]
    peak = float(np.abs(x).max()) or 1.0
    x = x / peak * 10 ** (-1 / 20)
    fade = int(0.01 * SR)
    if len(x) > 2 * fade:
        x[:fade] *= np.linspace(0, 1, fade)
        x[-fade:] *= np.linspace(1, 0, fade)
    return write_wav(dst, x)


def produce_line(studio, job: dict, line: dict, takes: int = TAKES, max_attempts: int = MAX_ATTEMPTS) -> dict:
    v = voices.approved(studio, line["character_id"])             # raises if no approved / tampered voice
    prof, vid, vsha = v["profile"], v["voice_id"], v["profile_sha"]
    eng = studio.engines[prof["engine"]]
    st, detail = studio.engine_health(prof["engine"])
    if st != "PASS":
        # the approved identity is bound to this engine; switching would change the voice, so it is not done silently
        raise Blocked(f"{vid} needs {prof['engine']} which is {st}: {detail}")
    rules = {**studio.db.pronunciations(prof["language"]), **(prof.get("pronunciation") or {})}
    text, pron = perform.apply_pronunciation(line["text"], rules)
    base = perform.direct(line | {"text": text})
    out_dir = studio.home / "takes" / line["line_id"]
    made, attempts = [], 0
    plan = [perform.variation(base, i, line["line_id"]) for i in range(takes)]
    while plan and attempts < max_attempts:
        c = plan.pop(0)
        attempts += 1
        tid_path = out_dir / f"{line['line_id']}_v{attempts:02d}.wav"
        try:
            g = eng.generate(c["text"], prof, c, tid_path)
        except (Unsupported, MissingModel) as e:
            raise Blocked(str(e)) from e
        m = analysis.measure(tid_path, c["text"], prof.get("rate_wpm", 150) * c["rate_pct"] / 100)
        tid = _record(studio, job["id"], line, vid, vsha, attempts, "raw", tid_path, {**c, "phonemes": g["phonemes"], "alignment": g["alignment"]}, m)
        made.append((tid, tid_path, m, c, g))
        bad = analysis.blocking(m)
        if bad and not plan and attempts < max_attempts:
            plan.append(perform.correct(c, bad[0]))              # targeted regeneration, bounded by max_attempts
    usable = [t for t in made if not analysis.blocking(t[2])]
    if not usable:
        for tid, p, _m, _c, _g in made:                            # keep failed artifacts, visibly
            rej = studio.home / "rejected" / Path(p).name
            rej.write_bytes(Path(p).read_bytes())
            studio.db.update("takes", "take_id", tid, status="rejected")
        reasons = sorted({d for t in made for d in analysis.blocking(t[2])})
        raise Blocked(f"{line['line_id']}: no usable take in {attempts} attempts ({', '.join(reasons)})")
    best = max(usable, key=lambda t: (t[2]["score"], -abs(1 - (t[2].get("duration_ratio") or 1))))
    tid, path, m, c, g = best
    fixes = sorted({d["fix"] for d in m["defects"]} | {"trim"})
    final = out_dir / f"{line['line_id']}_final.wav"
    process(path, final, fixes)
    m2 = analysis.measure(final, c["text"], prof.get("rate_wpm", 150) * c["rate_pct"] / 100)
    lead = m["leading_silence_s"] - m2["leading_silence_s"]
    ph = [(round(a - lead, 3), round(b - lead, 3), s) for a, b, s in (g["phonemes"] or []) if b - lead > 0]
    ftid = _record(studio, job["id"], line, vid, vsha, attempts + 1, "processed", final, {**c, "fixes": fixes, "phonemes": ph,
                                                                                         "alignment": g["alignment"]}, m2, parent=tid, status="selected")
    for t in made:
        studio.db.update("takes", "take_id", t[0], status="selected_source" if t[0] == tid else "alternative")
    studio.db.update("takes", "take_id", ftid, selected=1)
    return {"line_id": line["line_id"], "take_id": ftid, "source_take": tid, "voice_id": vid, "profile_sha": vsha, "path": str(final),
            "duration_s": m2["duration_s"], "score": m2["score"], "defects_left": [d["code"] for d in m2["defects"]], "attempts": attempts,
            "alternatives": [t[0] for t in made if t[0] != tid], "phonemes": ph, "alignment": g["alignment"], "pronunciation": pron,
            "controls": {k: c[k] for k in ("emotion", "rate_pct", "pitch_shift_pct", "range_mul", "volume_pct", "pause_before", "pause_after", "emphasis")}}


# ------------------------------------------------------------------------------------------------ planning
def plan_production(studio, screenplay: Path, name: str, gap_s: float = 0.35, master: bool = True) -> dict:
    sp = parse_screenplay(screenplay)
    q = Queue(studio)
    missing = sorted({ln["character_id"] for ln in sp["lines"]} - {v["character_id"] for v in studio.db.q("SELECT character_id FROM voices WHERE status='approved'")})
    if missing:
        raise Blocked(f"no approved voice for {missing}: run the voice factory first")
    root = q.enqueue("production.root", {"name": name, "screenplay": str(screenplay), "lines": len(sp["lines"])}, title=name, priority=80)
    line_jobs = [q.enqueue("dialogue.line", {"line": ln, "production": name}, title=f"{name} {ln['line_id']} {ln['character_id']}", priority=60,
                           parent=root, mem_mb=250) for ln in sp["lines"]]
    asm = q.enqueue("dialogue.assemble", {"production": name, "lines": [ln["line_id"] for ln in sp["lines"]], "line_jobs": line_jobs, "gap_s": gap_s,
                                          "title": sp["title"]}, title=f"{name} assemble", priority=55, depends_on=line_jobs, parent=root)
    jobs = {"root": root, "lines": line_jobs, "assemble": asm}
    if master:
        jobs["master"] = q.enqueue("audio.master", {"production": name}, title=f"{name} master", priority=50, depends_on=[asm], parent=root, mem_mb=500)
        jobs["lipsync"] = q.enqueue("lipsync.validate", {"production": name}, title=f"{name} lip-sync report", priority=50, depends_on=[asm], parent=root)
    return jobs


# ------------------------------------------------------------------------------------------------ handlers
def h_root(studio, job):
    return {"note": "container job"}


def h_line(studio, job):
    return produce_line(studio, job, job["payload"]["line"])


def h_assemble(studio, job):
    p = job["payload"]
    out = studio.home / "productions" / p["production"]
    out.mkdir(parents=True, exist_ok=True)
    rows, track, t = [], [], 0.0
    gap = np.zeros(int(p["gap_s"] * SR), np.float32)
    for jid in p["line_jobs"]:
        r = Queue(studio).get(jid)["result"]
        line = Queue(studio).get(jid)["payload"]["line"]
        v = voices.approved(studio, line["character_id"])
        if r["voice_id"] != v["voice_id"] or r["profile_sha"] != v["profile_sha"]:   # speaker substitution guard
            raise Blocked(f"{r['line_id']}: take voice {r['voice_id']}/{r['profile_sha']} != approved {v['voice_id']}/{v['profile_sha']}")
        tk = studio.db.one("SELECT * FROM takes WHERE take_id=?", (r["take_id"],))
        if sha256(Path(tk["path"])) != tk["sha256"]:
            raise Blocked(f"{r['take_id']} changed on disk after selection")
        x, sr, _ch = analysis.read_wav(Path(r["path"]))
        dur = len(x) / sr
        rows.append({"line_id": r["line_id"], "scene_id": line.get("scene_id"), "character_id": line["character_id"], "voice_id": r["voice_id"],
                     "take_id": r["take_id"], "text": line["text"], "emotion": line.get("emotion", "neutral"), "start_s": round(t, 3),
                     "end_s": round(t + dur, 3), "duration_s": round(dur, 3), "wav": r["path"], "phonemes": r["phonemes"], "alignment": r["alignment"],
                     "pronunciation": r["pronunciation"], "controls": r["controls"], "score": r["score"]})
        track += [x, gap]
        t += dur + p["gap_s"]
    full = out / "dialogue.wav"
    write_wav(full, np.concatenate(track) if track else np.zeros(1, np.float32))
    meta = {"production": p["production"], "title": p.get("title"), "sample_rate": SR, "lines": rows, "dialogue_wav": str(full),
            "speakers": sorted({r["character_id"] for r in rows}), "created": time.time()}
    (out / "dialogue.json").write_text(json.dumps(meta, indent=2))
    srt = "".join(f"{i}\n{_ts(r['start_s'])} --> {_ts(r['end_s'])}\n{r['character_id']}: {r['text']}\n\n" for i, r in enumerate(rows, 1))
    (out / "dialogue.srt").write_text(srt)
    for r in rows:                                                   # per-line stems at their timeline position
        st = np.zeros(int(t * SR) + 1, np.float32)
        x, _sr, _ = analysis.read_wav(Path(r["wav"]))
        a = int(r["start_s"] * SR)
        st[a:a + len(x)] = x[: len(st) - a]
        write_wav(out / "stems" / f"dialogue_{r['character_id']}_{r['line_id']}.wav", st)
    return {"dialogue_wav": str(full), "metadata": str(out / "dialogue.json"), "lines": len(rows), "seconds": round(t, 2)}


def _ts(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def h_lipsync(studio, job):
    from .lipsync import validate
    out = studio.home / "productions" / job["payload"]["production"]
    rep = validate(json.loads((out / "dialogue.json").read_text()))
    (out / "lipsync_report.json").write_text(json.dumps(rep, indent=2))
    if rep["status"] != "PASS":
        raise Blocked("lip-sync validation failed: " + "; ".join(r["line_id"] for r in rep["lines"] if r["status"] != "PASS"))
    return {"report": str(out / "lipsync_report.json"), "status": rep["status"]}


def h_master(studio, job):
    from .master import master_production
    return master_production(studio, job["payload"]["production"])


def h_model_install(studio, job):
    from .models import ApprovalRequired
    try:
        m = studio.store.install(job["payload"]["key"], approve=job["payload"].get("approve", False))
    except ApprovalRequired as e:
        raise Blocked(str(e)) from e
    studio.engine_health("piper", max_age=0)
    return {"key": m["key"], "license": m["license"], "bytes": m["bytes"]}


HANDLERS = {"production.root": h_root, "dialogue.line": h_line, "dialogue.assemble": h_assemble, "lipsync.validate": h_lipsync,
            "audio.master": h_master, "model.install": h_model_install}


def export_humanverse_lines(meta: dict, dest: Path) -> Path:
    """Write HUMANVERSE's audio/lines/lines.json schema so `hv storyboard`/`hv scenes` use AURAVOX dialogue directly."""
    rows = []
    for r in meta["lines"]:
        x, sr, _ = analysis.read_wav(Path(r["wav"]))
        rows.append({"line_id": r["line_id"], "character_id": r["character_id"], "text": r["text"], "emotion": r["emotion"],
                     "scene_id": r.get("scene_id"), "wav": r["wav"], "duration": r["duration_s"],
                     "rms": round(float(np.sqrt((x ** 2).mean())), 4), "engine": "auravox:" + r["voice_id"], "phonemes": r["phonemes"],
                     "take_id": r["take_id"], "voice_id": r["voice_id"]})
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(rows, indent=2))
    return dest


def subprocess_ok(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False).returncode == 0
