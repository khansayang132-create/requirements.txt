#!/usr/bin/env python3
"""HUMANVERSE STUDIO command line. Every stage writes files, checks them, and only then advances the manifest.

  hv doctor                 environment / capability / dependency reports            -> RESEARCH
  hv design                 validate cast + screenplay; write identity files         -> DESIGN, CHARACTER_DEVELOPMENT
  hv build-cast             model, rig, skin, deformation-test, reference renders    -> MODELING, RIGGING, ANIMATION
  hv voice                  dialogue with phoneme timing (local eSpeak NG)
  hv storyboard [--approve-as NAME]   shot-by-shot storyboard from real line timing  -> STORYBOARD (only when approved)
  hv scenes                 animated scene .blend files                              -> SCENE_PRODUCTION, VOICE
  hv sound                  music, ambience, footsteps, dialogue mix per scene       -> SOUND
  hv render [--scene S01]   resumable Cycles render, PNG-CRC checked                 -> RENDERING
  hv edit                   titles, scenes, credits, subtitles, loudness -> MP4      -> EDITING
  hv qa                     deterministic checks on every deliverable                -> QUALITY_CONTROL
  hv approve --as NAME      director sign-off                                        -> APPROVED
  hv deliver                delivery manifest with hashes                            -> DELIVERED
  hv status                 where the production is

Project folder: $HV_PROJECT (default ./project). Blender: $HV_BLENDER (a `blender` binary) or $HV_BPY_PYTHON
(a Python with the official `bpy` module).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from hvlib import core, media, story  # noqa: E402

PROJ = Path(os.environ.get("HV_PROJECT", "project")).resolve()
BL = HERE / "blender"


def cfg() -> dict:
    p = PROJ / "hv.config.json"
    base = {"fps": 24, "render_resolution": [1280, 720], "deliver_resolution": [1920, 1080], "samples": 14, "output_profile": "YOUTUBE",
            "loudness": {"I": -16.0, "TP": -1.5, "LRA": 11.0}, "chunk": 24}
    if p.exists():
        base.update(json.loads(p.read_text()))
    return base


def manifest() -> core.Manifest:
    return core.Manifest(PROJ / "manifest.json")


def reports() -> Path:
    d = PROJ / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def blender_cmd() -> list[str] | None:
    if os.environ.get("HV_BLENDER") and shutil.which(os.environ["HV_BLENDER"]):
        return [os.environ["HV_BLENDER"], "--background", "--python"]
    if shutil.which("blender"):
        return ["blender", "--background", "--python"]
    py = os.environ.get("HV_BPY_PYTHON") or sys.executable
    r = subprocess.run([py, "-c", "import bpy;print(bpy.app.version_string)"], capture_output=True, text=True, check=False)
    return [py] if r.returncode == 0 else None


def run_blender(script: str, args: list[str], log: Path) -> str:
    cmd = blender_cmd()
    if not cmd:
        raise SystemExit("BLOCKED: no Blender (install Blender, or `pip install bpy` on Python 3.11) - see reports/capability-report.md")
    full = cmd + [str(BL / script), "--"] + [str(a) for a in args]
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as f:
        f.write("$ " + " ".join(full) + "\n")
        p = subprocess.run(full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        f.write(p.stdout)
    if p.returncode != 0 or "Traceback" in p.stdout:
        tail = "\n".join(p.stdout.strip().splitlines()[-12:])
        raise SystemExit(f"FAIL: {script} (see {log})\n{tail}")
    return p.stdout


def cast() -> dict[str, dict]:
    return {json.loads(p.read_text())["id"]: json.loads(p.read_text()) for p in sorted((PROJ / "cast").glob("*.json"))}


def advance(m: core.Manifest, state: str, evidence, note="", criteria=None):
    if core.STATES.index(m.state if m.state != core.BLOCKED else m.data["blocked_at"]) >= core.STATES.index(state) and m.state != core.BLOCKED:
        return
    m.advance(state, evidence, note, criteria)
    print(f"STATE -> {state}")


# ---------------------------------------------------------------------------------------------- doctor
def cmd_doctor(a):
    from hvlib import voice

    def ver(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
            return (r.stdout or r.stderr).strip().splitlines()[0]
        except Exception:  # noqa: BLE001
            return None

    bl = blender_cmd()
    bver = None
    if bl:
        r = subprocess.run(bl[:1] + (["--version"] if bl[0] != sys.executable and "python" not in Path(bl[0]).name else
                                     ["-c", "import bpy;print('Blender', bpy.app.version_string, '(bpy module)')"]),
                           capture_output=True, text=True, check=False)
        bver = (r.stdout.strip().splitlines() or [None])[-1]
    gpu = ver(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"]) if shutil.which("nvidia-smi") else None
    mem = None
    try:
        mem = round(int(next(l for l in open("/proc/meminfo") if l.startswith("MemTotal")).split()[1]) / 1048576, 1)
    except Exception:  # noqa: BLE001
        pass
    env = {"os": platform.platform(), "machine": platform.machine(), "cpu_cores": os.cpu_count(), "ram_gb": mem, "gpu": gpu or "none detected",
           "cuda": bool(shutil.which("nvcc")), "rocm": Path("/opt/rocm").exists(), "metal": platform.system() == "Darwin",
           "disk_free_gb": round(shutil.disk_usage(PROJ.parent).free / 1e9, 1), "python": platform.python_version(),
           "blender": bver, "ffmpeg": ver(["ffmpeg", "-version"]), "ffprobe": bool(shutil.which("ffprobe")),
           "makehuman": bool(shutil.which("makehuman")), "comfyui": bool(os.environ.get("COMFYUI_URL")), "voices": voice.available()}
    prof = "STANDARD" if env["gpu"] != "none detected" else "LOW"
    cap = {
        "Modeling / rigging / animation (Blender Python API)": "PASS" if bver else "BLOCKED: Blender not found",
        "Rendering": ("PASS: Cycles CPU" if env["gpu"] == "none detected" else "PASS: Cycles GPU") if bver else "BLOCKED",
        "Eevee": "NOT TESTED here: needs OpenGL/EGL; without a GPU it only runs on Mesa llvmpipe and is slower than Cycles CPU",
        "Video assembly (FFmpeg)": "PASS" if env["ffmpeg"] else "BLOCKED",
        "Speech (eSpeak NG, phoneme timing)": env["voices"]["espeak-ng"],
        "Speech (Piper, neural)": env["voices"]["piper"],
        "MakeHuman / MPFB base meshes": "NOT USED: not installed; characters are procedural (hvchar.py)",
        "ComfyUI": "NOT USED: no local server configured; nothing in this pipeline needs it",
        "Quality profile chosen": prof + (" (CPU only: Cycles, 12-16 samples + denoiser)" if prof == "LOW" else ""),
    }
    deps = {
        "bpy / Blender": "GPL-2.0-or-later (tool; renders and .blend files you make are yours)",
        "FFmpeg": "LGPL/GPL build from the OS; H.264 via libx264 (GPL)",
        "eSpeak NG": "GPL-3.0 engine via espeakng-loader (MIT); generated speech is unrestricted",
        "numpy / Pillow": "BSD / MIT-CMU",
        "Assets": "none downloaded: all geometry, textures, music and sound effects are generated by this code",
    }
    r = reports()
    (r / "environment-report.md").write_text("# Environment report\n\n" + "\n".join(f"- **{k}**: {v}" for k, v in env.items()) + "\n")
    (r / "capability-report.md").write_text("# Capability report\n\n| Capability | Status |\n|---|---|\n" +
                                            "\n".join(f"| {k} | {v} |" for k, v in cap.items()) + "\n")
    (r / "dependency-report.md").write_text("# Dependency and licence report\n\n| Component | Licence / note |\n|---|---|\n" +
                                            "\n".join(f"| {k} | {v} |" for k, v in deps.items()) + "\n")
    core.atomic_json(r / "environment.json", env)
    print(json.dumps(env, indent=2))
    m = manifest()
    if not (bver and env["ffmpeg"]):
        m.block("Blender or FFmpeg missing", "RESEARCH")
        raise SystemExit(2)
    advance(m, "RESEARCH", [r / "environment-report.md", r / "capability-report.md", r / "dependency-report.md"], "environment inspected")


# ---------------------------------------------------------------------------------------------- design
def cmd_design(a):
    cs = cast()
    sp = json.loads((PROJ / "story" / "screenplay.json").read_text())
    errs = story.validate_screenplay(sp, set(cs))
    req = ("id", "name", "age", "category", "role", "personality", "motivation", "backstory", "appearance", "voice", "animation")
    for cid, c in cs.items():
        errs += [f"{cid}: missing {k}" for k in req if k not in c]
    if errs:
        raise SystemExit("FAIL design:\n" + "\n".join(errs))
    m = manifest()
    advance(m, "DESIGN", [PROJ / "story" / "screenplay.json"] + sorted((PROJ / "cast").glob("*.json")), "screenplay and cast validated",
            {"five_characters": len(cs) >= 5, "screenplay_valid": True})
    ev = []
    for cid, c in cs.items():
        d = PROJ / "characters" / cid
        d.mkdir(parents=True, exist_ok=True)
        ap = c["appearance"]
        files = {
            "character.json": {k: c[k] for k in ("id", "name", "age", "category", "role", "personality", "motivation", "backstory")},
            "appearance.json": {k: v for k, v in ap.items() if k != "palette"},
            "materials.json": {"skin": ap["palette"]["skin"], "hair": ap["palette"]["hair"], "iris": ap["palette"]["iris"],
                               "shader": "Principled BSDF; skin with subsurface 0.15; glossy eyes with emissive catch-light"},
            "wardrobe.json": {"shirt": ap["palette"]["shirt"], "sleeve": ap.get("sleeve", "long"), "pants": ap["palette"]["pants"],
                              "shorts": ap.get("shorts", False), "shoes": ap["palette"]["shoes"],
                              "extras": [k for k in ("apron", "tie", "cap", "glasses", "beard", "mustache") if ap.get(k)]},
            "voice-profile.json": {**c["voice"], "engine": "espeak-ng", "consent": "synthetic voice; no real person cloned"},
            "animation-profile.json": c["animation"],
        }
        for n, data in files.items():
            core.atomic_json(d / n, data)
        bible = [f"# {c['name']} ({cid})", "", f"{c['age']}, {c['category']}, {c['role']}.", "",
                 f"**Personality:** {', '.join(c['personality'])}  ", f"**Wants:** {c['motivation']}  ", f"**Backstory:** {c['backstory']}", "",
                 "## Locked identity", "", f"- height {ap['height']} m, head {ap['head_ratio']:.0%} of height, hair `{ap.get('hair_style')}`",
                 f"- palette: {', '.join(f'{k} {v}' for k, v in ap['palette'].items())}",
                 f"- wardrobe: {files['wardrobe.json']}", f"- voice: {c['voice']}", "",
                 "Any change to face, hair, proportions or clothes needs an approved design change: edit project/cast/"
                 f"{cid}.json, rebuild, and re-approve (the build hashes are recorded in the manifest).", "",
                 "References: refs/front.png, three_quarter.png, side.png, back.png, expr_*.png, deform_*.png"]
        (d / "character-bible.md").write_text("\n".join(bible) + "\n")
        ev.append(d / "character-bible.md")
    advance(m, "CHARACTER_DEVELOPMENT", ev, "identity files written for every character")


# ---------------------------------------------------------------------------------------------- build cast
def cmd_build_cast(a):
    cs = cast()
    m = manifest()
    out = {}
    for cid in cs:
        d = PROJ / "characters" / cid
        src = PROJ / "cast" / f"{cid}.json"
        rep = d / "build_report.json"
        stamp = d / ".source.sha256"
        if a.force or not rep.exists() or not stamp.exists() or stamp.read_text() != core.sha256(src):
            t = time.time()
            run_blender("build_character.py", ["--char", src, "--out", d, "--refs", "--samples", "12"], reports() / f"build_{cid}.log")
            stamp.write_text(core.sha256(src))
            print(f"built {cid} in {time.time() - t:.0f}s")
        r = json.loads(rep.read_text())
        out[cid] = r
        for kind, path in (("blend", d / f"{cid}.blend"), ("glb", d / f"{cid}.glb"), ("fbx", d / f"{cid}.fbx")):
            if path.exists():
                m.register(kind, cid, path, "character-modeling-engineer")
        try:
            from hvlib.sheets import sheet
            refs = d / "refs"
            sheet([refs / f"{n}.png" for n in ("front", "three_quarter", "side", "back")], d / "sheet_views.png", cols=4)
            sheet(sorted(refs.glob("expr_*.png")), d / "sheet_expressions.png", cols=6, cell_w=260)
            sheet(sorted(refs.glob("deform_*.png")), d / "sheet_deform.png", cols=4, cell_w=260)
        except Exception as e:  # noqa: BLE001
            print("contact sheets skipped:", e)
    blends = [PROJ / "characters" / c / f"{c}.blend" for c in cs]
    glbs = [PROJ / "characters" / c / f"{c}.glb" for c in cs]
    advance(m, "MODELING", blends + glbs, "models built and exported",
            {"all_blend": all(p.exists() for p in blends), "all_glb": all(p.exists() for p in glbs),
             "geometry": all(r["vertices"] > 5000 for r in out.values())})
    rigging_ok = {cid: r["bones"] >= 30 and all(s["unweighted_pct"] < 0.5 and s["leak_pct"] < 1.0 for s in r["skinning"])
                  and r["deformation_status"] == "PASS" for cid, r in out.items()}
    advance(m, "RIGGING", [PROJ / "characters" / c / "build_report.json" for c in cs], "rigs, weights and deformation tests", rigging_ok)
    expr = [PROJ / "characters" / c / "refs" / "expr_crying.png" for c in cs]
    advance(m, "ANIMATION", expr, "facial expression library and body animation library tested",
            {c: len(list((PROJ / "characters" / c / "refs").glob("expr_*.png"))) >= 10 for c in cs})


# ---------------------------------------------------------------------------------------------- voice
def cmd_voice(a):
    from hvlib import voice

    cs = cast()
    sp = json.loads((PROJ / "story" / "screenplay.json").read_text())
    lines = [ln | {"scene_id": s["scene_id"]} for s in sp["scenes"] for ln in s["lines"]]
    rows = voice.render_lines(lines, {cid: c["voice"] for cid, c in cs.items()}, PROJ / "audio" / "lines")
    bad = [r["line_id"] for r in rows if r["rms"] < 0.02 or not r["phonemes"]]
    for r in rows:
        print(f"{r['line_id']} {r['character_id']} {r['duration']:.2f}s phonemes={len(r['phonemes'])} rms={r['rms']}")
    if bad:
        raise SystemExit(f"FAIL voice: silent or untimed lines {bad}")


# ---------------------------------------------------------------------------------------------- storyboard
def cmd_storyboard(a):
    c = cfg()
    lines = {r["line_id"]: r for r in json.loads((PROJ / "audio" / "lines" / "lines.json").read_text())}
    spec = importlib.util.spec_from_file_location("blocking", PROJ / "story" / "blocking.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    blends = {cid: str(PROJ / "characters" / cid / f"{cid}.blend") for cid in cast()}
    sb, specs = mod.block(lines, blends, {"resolution": c["render_resolution"], "samples": c["samples"]})
    sbp = PROJ / "storyboard" / "storyboard.json"
    if sbp.exists() and json.loads(sbp.read_text()).get("approved_by") and not a.approve_as:
        old = json.loads(sbp.read_text())
        if {k: v for k, v in old.items() if not k.startswith("approved")} == {k: v for k, v in sb.items() if not k.startswith("approved")}:
            sb["approved"], sb["approved_by"], sb["approved_at"] = True, old["approved_by"], old["approved_at"]
    if a.approve_as:
        sb["approved"], sb["approved_by"], sb["approved_at"] = True, a.approve_as, core.now()
    core.atomic_json(sbp, sb)
    for s in specs:
        core.atomic_json(PROJ / "scenes" / s["scene_id"] / "spec.json", s)
    md = [f"# Storyboard: {sb['title']}", "", f"{len(sb['shots'])} shots, {sb['total_seconds']} s, approved: {sb.get('approved_by', 'NO')}", "",
          "| Shot | Frames | Dur | Characters | Action | Emotion | Camera | Move | Lens | Lighting | Dialogue | SFX | Continuity |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for sh in sb["shots"]:
        md.append("| " + " | ".join(str(x) for x in (sh["shot_id"], f"{sh['frames'][0]}-{sh['frames'][1]}", sh["duration"], ", ".join(sh["character_ids"]),
                                                      sh["action"], sh["emotion"], sh["camera_angle"], sh["camera_movement"], sh["lens"],
                                                      sh["lighting"], "; ".join(d["text"] for d in sh["dialogue"]) or "-",
                                                      ", ".join(sh["sound_effects"]) or "-", sh["continuity_notes"])) + " |")
    (PROJ / "storyboard" / "storyboard.md").write_text("\n".join(md) + "\n")
    errs = story.validate_storyboard(sb)
    print(f"storyboard: {len(sb['shots'])} shots, {sb['total_seconds']} s")
    if errs:
        print("NOT READY:\n  " + "\n  ".join(errs))
        return
    advance(manifest(), "STORYBOARD", [sbp, PROJ / "storyboard" / "storyboard.md"], f"approved by {sb['approved_by']}")


# ---------------------------------------------------------------------------------------------- scenes
def scene_ids():
    return sorted(p.name for p in (PROJ / "scenes").iterdir() if (p / "spec.json").exists())


def cmd_scenes(a):
    sb = json.loads((PROJ / "storyboard" / "storyboard.json").read_text())
    if story.validate_storyboard(sb):
        raise SystemExit("BLOCKED: storyboard incomplete or unapproved; run `hv storyboard --approve-as <director>` after review")
    ids = [a.scene] if a.scene else scene_ids()
    reps = {}
    for sid in ids:
        d = PROJ / "scenes" / sid
        run_blender("build_scene.py", ["--spec", d / "spec.json", "--lines", PROJ / "audio" / "lines" / "lines.json", "--out", d / f"{sid}.blend",
                                       "--report", d / "scene_report.json"], reports() / f"scene_{sid}.log")
        r = json.loads((d / "scene_report.json").read_text())
        reps[sid] = r
        print(sid, "frames", r["frames"], "foot slide (cm)", r["foot_slide_cm"], "tears", r["tears"])
        manifest().register("scene", sid, d / f"{sid}.blend", "executive-director")
    if a.scene:
        return
    worst = max([v for r in reps.values() for s in r["foot_slide_cm"].values() for v in s.values()] or [0])
    advance(manifest(), "SCENE_PRODUCTION", [PROJ / "scenes" / s / f"{s}.blend" for s in reps], "scenes built",
            {"scenes_at_least_3": len(reps) >= 3, f"foot_slide_under_2cm (worst {worst})": worst < 2.0})
    lines = json.loads((PROJ / "audio" / "lines" / "lines.json").read_text())
    advance(manifest(), "VOICE", [PROJ / "audio" / "lines" / "lines.json"] + [Path(ln["wav"]) for ln in lines], "dialogue rendered",
            {"all_lines_non_silent": all(ln["rms"] > 0.02 for ln in lines)})


# ---------------------------------------------------------------------------------------------- sound
SCENE_SOUND = {"park": ("park", "grass"), "park_sunset": ("park", "grass"), "street": ("street", "pavement"), "room": ("room", "wood")}


def cmd_sound(a):
    from hvlib import audio

    sp = json.loads((PROJ / "story" / "screenplay.json").read_text())
    mood = {s["scene_id"]: s.get("mood", "warm") for s in sp["scenes"]}
    weights = {cid: min(1.4, max(0.6, c["appearance"]["height"] / 1.5)) for cid, c in cast().items()}
    ev = []
    for sid in scene_ids():
        d = PROJ / "scenes" / sid
        spec = json.loads((d / "spec.json").read_text())
        rep = json.loads((d / "scene_report.json").read_text())
        amb, surf = SCENE_SOUND[spec["environment"]]
        st, placed = audio.mix_scene(rep["frames"] / rep["fps"], rep["fps"], rep["cues"], mood[sid], amb, surf, seed=hash(sid) % 1000,
                                     character_weight=weights)
        out = audio.write_stereo(d / "mix.wav", st)
        core.atomic_json(d / "mix_report.json", {"placed": placed, "seconds": rep["frames"] / rep["fps"], "mood": mood[sid], "ambience": amb,
                                                 "stats": media.wav_stats(out)})
        print(sid, placed, media.wav_stats(out))
        ev.append(out)
    advance(manifest(), "SOUND", ev, "scene mixes (dialogue, footsteps on animation contacts, music, ambience)")


# ---------------------------------------------------------------------------------------------- render
def cmd_render(a):
    c = cfg()
    ids = [a.scene] if a.scene else scene_ids()
    for sid in ids:
        d = PROJ / "scenes" / sid
        rep = json.loads((d / "scene_report.json").read_text())
        frames_dir = d / "frames"
        last = rep["frames"] if not a.limit else min(rep["frames"], a.limit)
        scan = media.scan_frames(frames_dir, 1, last)
        todo = sorted(scan["missing"] + scan["corrupt"])
        print(f"{sid}: {scan['valid']}/{last} frames valid, {len(todo)} to render")
        ch = c["chunk"]
        for i in range(0, len(todo), ch):
            part = todo[i:i + ch]
            t = time.time()
            run_blender("render.py", ["--blend", d / f"{sid}.blend", "--out", frames_dir, "--frames", ",".join(map(str, part)),
                                     "--samples", c["samples"]] + (["--threads", a.threads] if a.threads else []),
                        reports() / f"render_{sid}.log")
            bad = media.scan_frames(frames_dir, part[0], part[-1])
            if bad["missing"] or bad["corrupt"]:
                raise SystemExit(f"FAIL render integrity {sid}: {bad}")
            print(f"  {sid} frames {part[0]}-{part[-1]} ok ({(time.time() - t) / len(part):.1f}s/frame)", flush=True)
        core.atomic_json(d / "render_ledger.json", {"frames": last, "valid": media.scan_frames(frames_dir, 1, last)["valid"], "at": core.now(),
                                                    "resolution": rep["resolution"], "engine": "CYCLES (CPU)"})
    if not a.scene and not a.limit:
        ok = {sid: json.loads((PROJ / "scenes" / sid / "render_ledger.json").read_text())["valid"] ==
              json.loads((PROJ / "scenes" / sid / "scene_report.json").read_text())["frames"] for sid in scene_ids()}
        advance(manifest(), "RENDERING", [PROJ / "scenes" / s / "render_ledger.json" for s in scene_ids()], "all frames rendered and CRC-checked", ok)


# ---------------------------------------------------------------------------------------------- edit
def cmd_edit(a):
    from hvlib import audio, cards

    c = cfg()
    fps = c["fps"]
    W, H = c["deliver_resolution"]
    out_dir = PROJ / "movie"
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"
    work.mkdir(exist_ok=True)
    sp = json.loads((PROJ / "story" / "screenplay.json").read_text())
    cs = cast()
    title_s, credit_s, fade = 3.0, 5.0, 0.4
    cards.title_card(work / "title.png", sp["title"], "A HUMANVERSE STUDIO original", (W, H))
    cards.credits_card(work / "credits.png", sp["title"], [f"{v['name']} ({k})" for k, v in cs.items()], (W, H))
    segs = [("title", work / "title.png", title_s)]
    for sid in scene_ids():
        rep = json.loads((PROJ / "scenes" / sid / "scene_report.json").read_text())
        segs.append((sid, PROJ / "scenes" / sid / "frames", rep["frames"] / fps))
    segs.append(("credits", work / "credits.png", credit_s))
    # video segments (scaled to the delivery profile, light grade, fades), then concatenated
    parts = []
    for name, src, dur in segs:
        o = work / f"{name}.mp4"
        vf = (f"scale={W}:{H}:flags=lanczos,eq=contrast=1.04:saturation=1.06,fade=t=in:st=0:d={fade},"
              f"fade=t=out:st={dur - fade:.3f}:d={fade},format=yuv420p")
        if src.is_dir():
            inp = ["-framerate", str(fps), "-i", str(src / "%04d.png")]
        else:
            inp = ["-loop", "1", "-framerate", str(fps), "-t", f"{dur}", "-i", str(src)]
        subprocess.run(["ffmpeg", "-y", "-v", "error"] + inp + ["-vf", vf, "-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                                                                 "-t", f"{dur}", str(o)], check=True)
        parts.append(o)
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    video = work / "video.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(video)], check=True)
    # audio: title music, scene mixes, credits music, with the same fades
    import numpy as np
    chunks, t, cues_out = [], 0.0, []
    for name, src, dur in segs:
        if name in ("title", "credits"):
            x = audio.music(dur, "wonder" if name == "title" else "joyful", seed=7)
            st = np.stack([x, x], axis=1) * 0.5
        else:
            st = audio.read_stereo(PROJ / "scenes" / name / "mix.wav", dur)
            rep = json.loads((PROJ / "scenes" / name / "scene_report.json").read_text())
            for cue in rep["cues"]:
                if cue["type"] == "dialogue":
                    cues_out.append((t + (cue["frame"] - 1) / fps, cue["duration"], cue["line_id"]))
        n = len(st)
        k = int(fade * audio.SR)
        env = np.ones(n)
        env[:k] = np.linspace(0, 1, k)
        env[-k:] = np.linspace(1, 0, k)
        chunks.append(st * env[:, None])
        t += dur
    mix = audio.write_stereo(work / "mix_raw.wav", np.concatenate(chunks))
    final_audio = work / "mix_final.wav"
    loud = media.loudnorm_two_pass(mix, final_audio, c["loudness"]["I"], c["loudness"]["TP"], c["loudness"]["LRA"])
    lines = {r["line_id"]: r for r in json.loads((PROJ / "audio" / "lines" / "lines.json").read_text())}
    srt = out_dir / "subtitles.srt"
    srt.write_text("".join(f"{i}\n{cards.ts(s)} --> {cards.ts(s + d)}\n{cs[lines[lid]['character_id']]['name'].split()[0]}: {lines[lid]['text']}\n\n"
                           for i, (s, d, lid) in enumerate(cues_out, 1)), encoding="utf-8")
    final = out_dir / f"{sp['title'].lower().replace(' ', '-')}.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(final_audio), "-i", str(srt), "-map", "0:v", "-map", "1:a", "-map", "2",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
                    "-shortest", "-movflags", "+faststart", str(final)], check=True)
    core.atomic_json(out_dir / "edit_report.json", {"final": str(final), "segments": [(n, d) for n, _s, d in segs], "loudness": loud,
                                                     "dialogue_cues": cues_out, "deliver_resolution": [W, H], "render_resolution": c["render_resolution"]})
    print("final:", final, media.ffprobe(final))
    advance(manifest(), "EDITING", [final, srt], "assembled")


# ---------------------------------------------------------------------------------------------- QA
def cmd_qa(a):
    from hvlib import qa

    rep = qa.full_report(PROJ, cfg(), cast(), scene_ids())
    core.atomic_json(reports() / "qa-report.json", rep)
    (reports() / "qa-report.md").write_text(qa.to_markdown(rep))
    print(qa.to_markdown(rep))
    m = manifest()
    if rep["result"] == "PASS":
        advance(m, "QUALITY_CONTROL", [reports() / "qa-report.json", reports() / "qa-report.md"], "all checks PASS")
    else:
        print("QA result:", rep["result"], "- not advancing")
        raise SystemExit(1)


def cmd_approve(a):
    m = manifest()
    q = json.loads((reports() / "qa-report.json").read_text())
    if q["result"] != "PASS":
        raise SystemExit("cannot approve: QA is " + q["result"])
    note = reports() / "approval.json"
    core.atomic_json(note, {"approved_by": a.as_, "at": core.now(), "qa": q["result"], "notes": a.notes})
    advance(m, "APPROVED", [note], f"approved by {a.as_}")


def cmd_deliver(a):
    m = manifest()
    bad = m.verify_assets()
    files = sorted(set([*(PROJ / "movie").glob("*.mp4"), PROJ / "movie" / "subtitles.srt", PROJ / "storyboard" / "storyboard.json",
                        PROJ / "story" / "screenplay.md", reports() / "qa-report.md"] +
                       [p for cid in cast() for p in (PROJ / "characters" / cid).glob(f"{cid}.*")] +
                       [PROJ / "scenes" / s / f"{s}.blend" for s in scene_ids()] + [PROJ / "scenes" / s / "mix.wav" for s in scene_ids()]))
    dm = {"delivered": core.now(), "changed_since_registration": bad,
          "files": [{"path": str(p.relative_to(PROJ)), "bytes": p.stat().st_size, "sha256": core.sha256(p)} for p in files if p.exists()]}
    core.atomic_json(PROJ / "delivery.json", dm)
    if bad:
        raise SystemExit(f"FAIL deliver: assets changed after registration: {bad}")
    advance(m, "DELIVERED", [PROJ / "delivery.json"], "delivery manifest written")
    print(f"delivered {len(dm['files'])} files")


def cmd_status(a):
    m = manifest()
    print(json.dumps({"state": m.state, "history": [(h["to"], h["at"], h.get("note", "")) for h in m.data["history"]]}, indent=1))


def main():
    ap = argparse.ArgumentParser(prog="hv", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n, f in (("doctor", cmd_doctor), ("design", cmd_design), ("voice", cmd_voice), ("sound", cmd_sound), ("edit", cmd_edit),
                 ("qa", cmd_qa), ("deliver", cmd_deliver), ("status", cmd_status)):
        sub.add_parser(n).set_defaults(fn=f)
    p = sub.add_parser("build-cast")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_build_cast)
    p = sub.add_parser("storyboard")
    p.add_argument("--approve-as", default=None)
    p.set_defaults(fn=cmd_storyboard)
    p = sub.add_parser("scenes")
    p.add_argument("--scene", default=None)
    p.set_defaults(fn=cmd_scenes)
    p = sub.add_parser("render")
    p.add_argument("--scene", default=None)
    p.add_argument("--limit", type=int, default=0, help="only the first N frames (preview)")
    p.add_argument("--threads", type=int, default=0, help="CPU threads for this render process (run several scenes in parallel)")
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("approve")
    p.add_argument("--as", dest="as_", required=True)
    p.add_argument("--notes", default="")
    p.set_defaults(fn=cmd_approve)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
