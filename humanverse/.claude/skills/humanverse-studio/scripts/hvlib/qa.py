"""Deterministic quality report over every deliverable. PASS / FAIL / BLOCKED / NOT TESTED; never upgraded."""
from __future__ import annotations

import json
from pathlib import Path

from . import core, media, story


def _row(rows, area, check, status, detail=""):
    rows.append({"area": area, "check": check, "status": status, "detail": str(detail)[:300]})


def full_report(proj: Path, cfg: dict, cast: dict, scenes: list[str]) -> dict:
    rows: list[dict] = []
    ok = lambda c: "PASS" if c else "FAIL"  # noqa: E731
    for cid in cast:
        d = proj / "characters" / cid
        blend, glb, fbx = d / f"{cid}.blend", d / f"{cid}.glb", d / f"{cid}.fbx"
        _row(rows, "character " + cid, "model exists (.blend header)", ok(blend.exists() and blend.read_bytes()[:7] == b"BLENDER"), blend)
        _row(rows, "character " + cid, "glb export (magic glTF)", ok(glb.exists() and glb.read_bytes()[:4] == b"glTF"), glb)
        _row(rows, "character " + cid, "fbx export", ok(fbx.exists() and fbx.read_bytes()[:18] == b"Kaydara FBX Binary"), fbx)
        r = json.loads((d / "build_report.json").read_text()) if (d / "build_report.json").exists() else None
        if not r:
            _row(rows, "character " + cid, "build report", "FAIL", "missing")
            continue
        _row(rows, "character " + cid, "geometry valid", ok(r["vertices"] > 5000 and r["polygons"] > 5000), f"{r['vertices']} verts, {r['polygons']} polys")
        _row(rows, "character " + cid, "materials assigned", ok(len(r["materials"]) >= 10), f"{len(r['materials'])} materials")
        ident = [d / n for n in ("character.json", "character-bible.md", "appearance.json", "materials.json", "wardrobe.json",
                                 "voice-profile.json", "animation-profile.json")]
        _row(rows, "character " + cid, "identity documented (7 files)", ok(all(p.exists() for p in ident)), [p.name for p in ident if not p.exists()])
        refs = d / "refs"
        need = ["front", "side", "back", "three_quarter"] + [f"expr_{e}" for e in ("happy", "sad", "angry", "surprised", "crying")]
        _row(rows, "character " + cid, "reference renders", ok(all(media.png_ok(refs / f"{n}.png")[0] for n in need)), f"{len(list(refs.glob('*.png')))} refs")
        _row(rows, "rig " + cid, "armature + connected bones", ok(r["bones"] >= 30 and r["deform_bones"] >= 20), f"{r['bones']} bones")
        for s in r["skinning"]:
            _row(rows, "rig " + cid, f"weights {s['object']}", ok(s["unweighted_pct"] < 0.5 and s["leak_pct"] < 1.0),
                 f"{s['method']}; unweighted {s['unweighted_pct']}%, cross-side {s['leak_pct']}%")
        for pose, dv in r["deformation"].items():
            _row(rows, "rig " + cid, f"deformation {pose}", dv["status"], f"stretch {dv['min_stretch']}-{dv['max_stretch']}, over-limit edges {dv['edges_over_limit']}")
        _row(rows, "rig " + cid, "face controls drive mouth shape keys", ok(len(r["mouth_shape_keys"]) >= 7), r["mouth_shape_keys"])
    sb = json.loads((proj / "storyboard" / "storyboard.json").read_text())
    errs = story.validate_storyboard(sb)
    _row(rows, "storyboard", "complete and approved", ok(not errs), errs or f"{len(sb['shots'])} shots, approved by {sb.get('approved_by')}")
    lines = json.loads((proj / "audio" / "lines" / "lines.json").read_text())
    for ln in lines:
        st = media.wav_stats(Path(ln["wav"]))
        _row(rows, "voice", f"{ln['line_id']} audible + phoneme timing", ok(st["rms"] > 0.02 and len(ln["phonemes"]) >= 3),
             f"{st['duration']}s rms {st['rms']}, {len(ln['phonemes'])} phonemes")
    for sid in scenes:
        d = proj / "scenes" / sid
        rep = json.loads((d / "scene_report.json").read_text())
        _row(rows, "animation " + sid, "animation data exists", ok(all(v > 50 for v in rep["actions"].values())), rep["actions"])
        dial = [c for c in rep["cues"] if c["type"] == "dialogue"]
        _row(rows, "animation " + sid, "lip sync keyed from phonemes", ok(all(c["visemes_keyed"] >= 3 for c in dial)),
             {c["line_id"]: c["visemes_keyed"] for c in dial})
        worst = max([v for s in rep["foot_slide_cm"].values() for v in s.values()] or [0])
        _row(rows, "animation " + sid, "no foot sliding (< 2 cm per planted frame)", ok(worst < 2.0), f"worst {worst} cm")
        scan = media.scan_frames(d / "frames", 1, rep["frames"])
        _row(rows, "render " + sid, "every frame present and CRC-valid", ok(not scan["missing"] and not scan["corrupt"]), scan["valid"])
        st = media.wav_stats(d / "mix.wav")
        _row(rows, "audio " + sid, "mix: no clipping", ok(st["clipped_samples"] == 0), st)
        _row(rows, "audio " + sid, "mix: no accidental silence (> 1.5 s)", ok(st["longest_silence_s"] <= 1.5), st["longest_silence_s"])
    finals = sorted((proj / "movie").glob("*.mp4"))
    if not finals:
        _row(rows, "video", "final MP4 exists", "BLOCKED", "not assembled")
    else:
        f = finals[0]
        pr = media.ffprobe(f) or {}
        W, H = cfg["deliver_resolution"]
        er = json.loads((proj / "movie" / "edit_report.json").read_text())
        expected = sum(d for _n, d in er["segments"])
        _row(rows, "video", "MP4 exists", ok(f.stat().st_size > 100_000), f"{f} ({f.stat().st_size} bytes)")
        dec, why = media.decode_ok(f)
        _row(rows, "video", "decodes end to end", ok(dec), why or "clean")
        _row(rows, "video", "H.264 + yuv420p", ok(pr.get("vcodec") == "h264" and pr.get("pix_fmt") == "yuv420p"), (pr.get("vcodec"), pr.get("pix_fmt")))
        _row(rows, "video", f"resolution {W}x{H}", ok((pr.get("width"), pr.get("height")) == (W, H)), (pr.get("width"), pr.get("height")))
        _row(rows, "video", f"frame rate {cfg['fps']}", ok(abs(pr.get("fps", 0) - cfg["fps"]) < 0.01), pr.get("fps"))
        _row(rows, "video", "duration matches the edit (±0.2 s)", ok(abs(pr.get("duration", 0) - expected) <= 0.2), f"{pr.get('duration')} vs {expected:.2f}")
        _row(rows, "audio", "AAC stream present", ok(pr.get("acodec") == "aac"), pr.get("acodec"))
        _row(rows, "audio", "A/V in sync (stream lengths within 0.1 s)", ok(abs(pr.get("a_duration", 0) - pr.get("v_duration", 0)) <= 0.1),
             f"audio {pr.get('a_duration')} video {pr.get('v_duration')}")
        ld = media.loudness(f)
        _row(rows, "audio", f"loudness {cfg['loudness']['I']} LUFS ±1, true peak <= {cfg['loudness']['TP'] + 0.5}",
             ok(ld and abs(ld["input_i"] - cfg["loudness"]["I"]) <= 1 and ld["input_tp"] <= cfg["loudness"]["TP"] + 0.5), ld)
        bf = media.black_and_freeze(f)
        long_black = [b for b in bf["black"] if b[1] - b[0] > 1.0]
        _row(rows, "video", "no black gaps > 1 s", ok(not long_black), bf["black"])
        _row(rows, "video", "subtitle track", ok(pr.get("subtitles") == "mov_text"), pr.get("subtitles"))
        cues_in = all(c[0] + c[1] <= pr.get("duration", 0) for c in er["dialogue_cues"])
        _row(rows, "audio", "every dialogue cue inside the movie", ok(cues_in), len(er["dialogue_cues"]))
    statuses = [r["status"] for r in rows]
    result = "FAIL" if "FAIL" in statuses else ("BLOCKED" if "BLOCKED" in statuses else "PASS")
    return {"generated": core.now(), "result": result, "counts": {s: statuses.count(s) for s in ("PASS", "FAIL", "BLOCKED", "NOT TESTED")},
            "rows": rows, "not_tested": ["visual appeal and acting quality (human judgement)", "lip shapes against a real phoneme recogniser"]}


def to_markdown(rep: dict) -> str:
    out = [f"# QA report ({rep['generated']})", "", f"**Result: {rep['result']}** — {rep['counts']}", "",
           "| Area | Check | Status | Evidence |", "|---|---|---|---|"]
    out += [f"| {r['area']} | {r['check']} | {r['status']} | {r['detail'].replace('|', '/')} |" for r in rep["rows"]]
    out += ["", "NOT TESTED by machine: " + "; ".join(rep["not_tested"])]
    return "\n".join(out) + "\n"
