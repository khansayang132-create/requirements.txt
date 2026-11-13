"""OVERLORD production tools: the departments' real work, as agency tools.

Each tool runs an existing project's own program in that project's own environment (HUMANVERSE's Blender
Python, AURAVOX's `avx`, Cartoon Studio's CLI, ffmpeg/ffprobe) with a fixed argv, a timeout and no shell, and
returns PASS / FAIL / BLOCKED / ERROR like every other agency tool. Nothing here reimplements those projects:
OVERLORD orchestrates, the projects produce.

Output goes under agency/out/production/<name>/ so two missions never write the same asset: `name` is unique per
mission (the playbook fills it from the mission id) and a tool refuses to reuse a folder that already holds a
finished result.

Integration probes report one of VERIFIED / FAILED / BLOCKED / NOT INSTALLED / NOT TESTED in
evidence["integration_status"]. VERIFIED needs real work done (a frame rendered, speech measured, a file decoded),
never just an import or a config file. Paid services are only checked with read-only, free requests, and only
when their credential is already in the environment; no credential means BLOCKED, never a guess.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .tools import Param, Tool, ToolResult, _kill_group

NAME = r"[a-z0-9][a-z0-9._-]{0,60}"
CHAR = r"CHAR-[A-Z]{3}-\d{3}"
OUT = "agency/out/production"

INTEGRATIONS = ("blender", "ffmpeg", "ffprobe", "espeak_ng", "piper", "comfyui", "claude_cli", "codex_cli", "node",
                "cartoon_studio", "digital_human_factory", "elevenlabs", "heygen", "higgsfield")

# Credentials are looked up by name only; their values never leave this process except in the request header.
CREDENTIALS = {"elevenlabs": ("ELEVENLABS_API_KEY",), "heygen": ("HEYGEN_API_KEY",),
               "higgsfield": ("HF_KEY", "HF_API_KEY")}


def _venv(tb, project: str, exe: str = "python") -> str:
    return str(tb.root / project / ".venv" / "bin" / exe)


def _status(result: ToolResult, integration_status: str) -> ToolResult:
    result.evidence["integration_status"] = integration_status
    return result


def probe_media(tb, path: str, need_audio: bool = True, min_seconds: float = 0.5) -> tuple[bool, dict]:
    """ffprobe + a full decode. Shared by media_verify and by the verifier's independent re-check."""
    p = (tb.root / path).resolve() if not Path(path).is_absolute() else Path(path)
    ev: dict = {"path": str(p)}
    if not p.is_file() or p.stat().st_size == 0:
        return False, ev | {"problem": "missing or empty file"}
    ev["bytes"] = p.stat().st_size
    code, out, blocked = tb._run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(p)],
                                 tb.root, 60)
    if blocked or code != 0:
        return False, ev | {"problem": "ffprobe could not read the file"}
    info = json.loads(out)
    kinds = [s["codec_type"] for s in info.get("streams", [])]
    dur = float(info.get("format", {}).get("duration") or 0)
    ev |= {"streams": kinds, "duration_s": round(dur, 3)}
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if video:
        ev["resolution"] = [video.get("width"), video.get("height")]
    code, out, _ = tb._run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "null", "-"], tb.root, 600)
    ev["decode_errors"] = out.strip()[:500]
    # Black and silent stretches (blackdetect >= 1 s, silencedetect < -50 dB for >= 2 s). Reported as findings;
    # only an entirely black picture, or silence throughout when audio is required, fails the file.
    filt = ["-vf", "blackdetect=d=1:pix_th=0.10"] + (["-af", "silencedetect=n=-50dB:d=2"] if "audio" in kinds else [])
    _, ana, _ = tb._run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(p), *filt, "-f", "null", "-"], tb.root, 600)
    black = [float(x) for x in re.findall(r"black_duration:([\d.]+)", ana)]
    silent = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", ana)]
    ev["black_s"], ev["silent_s"] = round(sum(black), 2), round(sum(silent), 2)
    ev["black_segments"], ev["silent_segments"] = len(black), len(silent)
    problems = [m for m, bad in (("no video stream", video is None), ("no audio stream", need_audio and "audio" not in kinds),
                                 (f"duration {dur:.2f}s under {min_seconds}s", dur < min_seconds),
                                 ("decode errors", code != 0 or bool(out.strip())),
                                 ("picture is black throughout", dur > 0 and ev["black_s"] >= dur * 0.95),
                                 ("audio is silent throughout", need_audio and dur > 0 and ev["silent_s"] >= dur * 0.95)) if bad]
    if problems:
        ev["problem"] = "; ".join(problems)
    return not problems, ev


def build(tb) -> list[Tool]:
    """The production tools, bound to one Toolbox (its root, environment and cancel switch)."""

    def run(argv, cwd=None, timeout=600, env_extra=None):
        """Like Toolbox._run (no shell, secrets stripped, killed on timeout or cancel) with per-call extra env,
        so concurrent tasks never see each other's variables."""
        argv = [str(a) for a in argv]
        search = os.pathsep.join([str(Path(sys.executable).parent), tb.env.get("PATH", os.defpath)])
        exe = argv[0] if Path(argv[0]).is_file() else shutil.which(argv[0], path=search)
        if exe is None:
            return None, "", ToolResult("BLOCKED", f"{argv[0]} is not installed", evidence={"argv": argv})
        p = subprocess.Popen([exe, *argv[1:]], cwd=cwd or tb.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, env=tb._child_env() | (env_extra or {}), start_new_session=True)
        deadline = time.monotonic() + timeout
        while True:
            try:
                out, _ = p.communicate(timeout=0.5)
                return p.returncode, out, None
            except subprocess.TimeoutExpired:
                reason = ("cancelled" if tb.cancel_event.is_set()
                          else f"timed out after {timeout:.0f}s" if time.monotonic() > deadline else "")
                if reason:
                    _kill_group(p)
                    return None, "", ToolResult("ERROR", reason, evidence={"argv": argv})

    def workdir(name: str) -> Path:
        d = tb.root / OUT / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def claim(d: Path, what: str) -> ToolResult | None:
        """Exclusive writer lock on an asset folder. A live holder means another agent is writing it: BLOCKED.
        A stale lock (its process is gone) is taken over, so a retried task can resume its own asset."""
        lock = d / f".{what}.lock"
        for _ in range(2):
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return None
            except FileExistsError:
                try:
                    holder = int(lock.read_text() or 0)
                    os.kill(holder, 0)
                except (ValueError, ProcessLookupError, FileNotFoundError):
                    lock.unlink(missing_ok=True)          # stale: its writer died
                    continue
                except PermissionError:
                    pass
                return ToolResult("BLOCKED", f"{d.name}/{what} is being written by process {holder}; not overwriting it",
                                  evidence={"lock": str(lock)})
        return ToolResult("BLOCKED", f"could not lock {lock}")

    def locked(d: Path, what: str, fn):
        busy = claim(d, what)
        if busy:
            return busy
        try:
            return fn()
        finally:
            (d / f".{what}.lock").unlink(missing_ok=True)

    # ------------------------------------------------------------ integrations
    def integration_probe(name: str) -> ToolResult:
        tmp = Path(tempfile.mkdtemp(prefix="overlord-probe-"))
        try:
            return _probe(name, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _probe(name: str, tmp: Path) -> ToolResult:
        if name == "blender":
            py = _venv(tb, "humanverse")
            if not Path(py).exists():
                return _status(ToolResult("BLOCKED", "HUMANVERSE venv with bpy is missing (humanverse/.venv)"), "NOT INSTALLED")
            script = tmp / "probe.py"
            script.write_text(
                "import bpy, sys\nsc = bpy.context.scene\nbpy.ops.mesh.primitive_uv_sphere_add()\n"
                "sc.render.engine = 'CYCLES'\nsc.cycles.samples = 1\nsc.render.resolution_x = sc.render.resolution_y = 32\n"
                "cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))\nsc.collection.objects.link(cam)\n"
                "cam.location = (0, -6, 0)\ncam.rotation_euler = (1.5708, 0, 0)\nsc.camera = cam\n"
                f"sc.render.filepath = {str(tmp / 'f.png')!r}\nbpy.ops.render.render(write_still=True)\n"
                "print('BLENDER', bpy.app.version_string)\n")
            code, out, blocked = run([py, script], timeout=180)
            if blocked:
                return _status(blocked, "NOT INSTALLED")
            ok = code == 0 and (tmp / "f.png").is_file() and (tmp / "f.png").stat().st_size > 0
            ver = next((ln.split(" ", 1)[1] for ln in out.splitlines() if ln.startswith("BLENDER ")), "?")
            return _status(ToolResult("PASS" if ok else "FAIL", f"bpy {ver}: rendered a Cycles frame" if ok
                                      else "Blender ran but no frame was written", out[-2000:], code,
                                      {"version": ver}), "VERIFIED" if ok else "FAILED")
        if name in ("ffmpeg", "ffprobe"):
            mp4 = tmp / "t.mp4"
            code, out, blocked = run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=12:d=1",
                                      "-f", "lavfi", "-i", "sine=f=440:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                                      "-c:a", "aac", "-shortest", mp4], timeout=60)
            if blocked:
                return _status(blocked, "NOT INSTALLED")
            ok, ev = probe_media(tb, str(mp4), True, 0.5)
            return _status(ToolResult("PASS" if ok else "FAIL", f"{name}: encoded, probed and decoded a 1 s A/V clip"
                                      if ok else f"{name}: {ev.get('problem')}", out, code, ev), "VERIFIED" if ok else "FAILED")
        if name in ("espeak_ng", "piper"):
            py = _venv(tb, "auravox")
            if not Path(py).exists():
                return _status(ToolResult("BLOCKED", "AURAVOX venv missing (auravox/.venv)"), "NOT INSTALLED")
            engine = "espeak-ng" if name == "espeak_ng" else "piper"
            code, out, blocked = run([py, "-c", "import json,sys;from pathlib import Path;from auravox.studio import Studio;"
                                      f"s=Studio(Path(sys.argv[1]));print(json.dumps(s.engine_health({engine!r},max_age=0)))",
                                      tmp / "home"], timeout=180)
            if blocked:
                return _status(blocked, "NOT INSTALLED")
            try:
                st, detail = json.loads(out.strip().splitlines()[-1])
            except (ValueError, IndexError):
                return _status(ToolResult("ERROR", "engine health did not report", out[-2000:], code), "FAILED")
            mapped = {"PASS": ("PASS", "VERIFIED"), "BLOCKED": ("BLOCKED", "BLOCKED")}.get(st, ("FAIL", "FAILED"))
            return _status(ToolResult(mapped[0], f"{engine}: {detail}", out[-2000:], code, {"engine": engine}), mapped[1])
        if name == "comfyui":
            for url in ("http://127.0.0.1:8188/system_stats",):
                try:
                    with urllib.request.urlopen(url, timeout=3) as r:
                        return _status(ToolResult("PASS", f"ComfyUI answered at {url}", r.read(2000).decode(errors="replace"),
                                                  evidence={"url": url}), "VERIFIED")
                except (urllib.error.URLError, OSError):
                    pass
            found = shutil.which("comfy") or (tb.root / "ComfyUI").is_dir()
            return _status(ToolResult("BLOCKED", "ComfyUI is installed but not running on 127.0.0.1:8188" if found else
                                      "ComfyUI is not installed (no `comfy` CLI, no ComfyUI folder, nothing on :8188)"),
                           "NOT TESTED" if found else "NOT INSTALLED")
        if name in ("claude_cli", "codex_cli", "node"):
            prog = {"claude_cli": "claude", "codex_cli": "codex", "node": "node"}[name]
            code, out, blocked = run([prog, "--version"], timeout=30)
            if blocked:
                return _status(blocked, "NOT INSTALLED")
            ok = code == 0 and bool(out.strip())
            if ok and prog == "codex":                      # a CLI that can't authenticate can't do any work
                lc, lout, _ = run(["codex", "login", "status"], timeout=30)
                if lc != 0 or "not logged in" in lout.lower():
                    return _status(ToolResult("BLOCKED", f"{out.strip()[:40]} installed, not logged in (`codex login` "
                                              "needs the owner's OpenAI account)", lout, lc), "BLOCKED")
            return _status(ToolResult("PASS" if ok else "FAIL", f"{prog} {out.strip()[:60]}", out, code),
                           "VERIFIED" if ok else "FAILED")
        if name in ("cartoon_studio", "digital_human_factory"):
            proj, exe = {"cartoon_studio": ("cartoon-studio", "cartoon-studio"),
                         "digital_human_factory": ("digital-human-factory", "dhfactory")}[name]
            cli = _venv(tb, proj, exe)
            if not Path(cli).exists():
                return _status(ToolResult("BLOCKED", f"{proj}/.venv is not installed"), "NOT INSTALLED")
            code, out, blocked = run([cli, "doctor"], cwd=tb.root / proj, timeout=300)
            if blocked:
                return _status(blocked, "NOT INSTALLED")
            return _status(ToolResult("PASS" if code == 0 else "FAIL", f"{exe} doctor exit {code}", out[-4000:], code),
                           "VERIFIED" if code == 0 else "FAILED")
        if name in CREDENTIALS:
            key_name = next((k for k in CREDENTIALS[name] if tb.env.get(k)), None)
            if not key_name:
                needs = " or ".join(CREDENTIALS[name])
                return _status(ToolResult("BLOCKED", f"{name}: no credential in the environment ({needs}); "
                                          "nothing was called", evidence={"needs": list(CREDENTIALS[name])}), "BLOCKED")
            if name == "elevenlabs":                                  # free, read-only: list the account's models
                req = urllib.request.Request("https://api.elevenlabs.io/v1/models", headers={"xi-api-key": tb.env[key_name]})
            elif name == "heygen":                                    # free, read-only: remaining quota
                req = urllib.request.Request("https://api.heygen.com/v2/user/remaining_quota",
                                             headers={"X-Api-Key": tb.env[key_name]})
            else:
                return _status(ToolResult("BLOCKED", "higgsfield: credential present, but no free read-only check is "
                                          "implemented, so it is not called (no spend without approval)"), "NOT TESTED")
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return _status(ToolResult("PASS", f"{name}: authenticated read-only request HTTP {r.status}",
                                              evidence={"http_status": r.status}), "VERIFIED")
            except urllib.error.HTTPError as e:
                return _status(ToolResult("BLOCKED" if e.code in (401, 403) else "FAIL", f"{name}: HTTP {e.code}",
                                          evidence={"http_status": e.code}), "BLOCKED" if e.code in (401, 403) else "FAILED")
            except (urllib.error.URLError, OSError) as e:
                return _status(ToolResult("BLOCKED", f"{name}: unreachable from here ({getattr(e, 'reason', e)})"), "BLOCKED")
        return ToolResult("FAIL", f"unknown integration {name}")

    # ------------------------------------------------------------ media
    def media_verify(path: str, need_audio: bool = True) -> ToolResult:
        ok, ev = probe_media(tb, path, need_audio)
        ev["media"] = ev["path"]
        return ToolResult("PASS" if ok else "FAIL", (f"{ev['duration_s']}s, streams {ev['streams']}, {ev['bytes']} bytes, "
                          "decodes cleanly") if ok else ev.get("problem", "invalid media"), evidence=ev)

    # ------------------------------------------------------------ HUMANVERSE department
    def build_character(character: str, name: str) -> ToolResult:
        return locked(workdir(name), f"character-{character}", lambda: _build_character(character, name))

    def _build_character(character: str, name: str) -> ToolResult:
        py = _venv(tb, "humanverse")
        cast = tb.root / "humanverse/project/cast" / f"{character}.json"
        if not Path(py).exists():
            return ToolResult("BLOCKED", "humanverse/.venv (Blender Python) is missing")
        if not cast.is_file():
            return ToolResult("FAIL", f"no cast entry {cast.relative_to(tb.root)}")
        out = workdir(name) / "characters" / character
        code, log, blocked = run([py, tb.root / "humanverse/.claude/skills/humanverse-studio/scripts/blender/build_character.py",
                                  "--", "--char", cast, "--out", out], timeout=600)
        if blocked:
            return blocked
        rep_p = out / "build_report.json"
        if code != 0 or not rep_p.is_file():
            return ToolResult("FAIL", f"character build exit {code}, no build report", log[-3000:], code)
        rep = json.loads(rep_p.read_text())
        deform = {k: v.get("status") for k, v in rep.get("deformation", {}).items()}
        checks = {"geometry": rep.get("vertices", 0) > 1000, "skeleton": rep.get("bones", 0) >= 20,
                  "facial_rig": {"open", "smile", "round", "closed"} <= set(rep.get("face_controls", [])),
                  "skinning": all(s.get("unweighted_pct", 100) < 0.5 for s in rep.get("skinning", [])),
                  "deformation": bool(deform) and all(v == "PASS" for v in deform.values()),
                  "exports": "glb" in rep.get("exports", []), "blend": (out / f"{character}.blend").is_file()}
        ev = {"character": character, "dir": str(out), "checks": checks, "vertices": rep.get("vertices"),
              "bones": rep.get("bones"), "face_controls": rep.get("face_controls"), "deformation": deform,
              "character_dir": str(out.parent)}
        bad = [k for k, v in checks.items() if not v]
        return ToolResult("FAIL" if bad else "PASS", f"{character}: {rep.get('vertices')} vertices, {rep.get('bones')} bones, "
                          f"{len(rep.get('face_controls', []))} face controls" + (f"; failed {bad}" if bad else ""),
                          log[-2000:], code, ev)

    # ------------------------------------------------------------ AUDIO department
    def voice_dialogue(screenplay: str, name: str) -> ToolResult:
        avx = _venv(tb, "auravox", "avx")
        if not Path(avx).exists():
            return ToolResult("BLOCKED", "auravox/.venv is missing")
        sp = tb._path(screenplay)
        home = {"AVX_HOME": str(tb.root / "auravox/data")}         # the studio that holds the approved, locked voices
        prod = tb.root / "auravox/data/productions" / name
        if (prod / "master.wav").exists():
            return ToolResult("FAIL", f"production {name} already exists; refusing to overwrite another mission's asset")
        code, out, blocked = run([avx, "produce", sp, "--name", name], cwd=tb.root / "auravox", env_extra=home, timeout=120)
        if blocked:
            return blocked
        if code != 0:
            return ToolResult("FAIL", f"avx produce exit {code}", out[-3000:], code)
        code, out2, _ = run([avx, "work", "--workers", "2"], cwd=tb.root / "auravox", env_extra=home, timeout=1800)
        out += out2
        meta_p, lip_p, rep_p = prod / "dialogue.json", prod / "lipsync_report.json", prod / "master_report.json"
        if not (meta_p.is_file() and rep_p.is_file()):
            return ToolResult("FAIL", "AURAVOX did not produce the dialogue and master (see `avx queue`)", out[-3000:], code)
        lip = json.loads(lip_p.read_text())["status"] if lip_p.is_file() else "NOT TESTED"
        loud = json.loads(rep_p.read_text())["loudness"]
        ev = {"production": name, "dialogue": str(meta_p), "master": str(prod / "master.wav"), "lipsync": lip,
              "lufs": loud["after_lufs"], "true_peak": loud["after_true_peak"],
              "lines": len(json.loads(meta_p.read_text())["lines"])}
        ok = lip == "PASS"
        return ToolResult("PASS" if ok else "FAIL", f"{ev['lines']} line(s), lip-sync data {lip}, {ev['lufs']} LUFS",
                          out[-2000:], code, ev)

    # ------------------------------------------------------------ VIDEO department
    def talking_scene(production: str, name: str, character_dir: str = "", scene: str = "S01",
                      res: str = "960x540", samples: str = "4") -> ToolResult:
        return locked(workdir(name), "scene", lambda: _talking_scene(production, name, character_dir, scene, res, samples))

    def _talking_scene(production, name, character_dir, scene, res, samples) -> ToolResult:
        py = _venv(tb, "auravox")
        out = workdir(name) / "scene"
        argv = [py, tb.root / "auravox/demo/gate4/gate4.py", "--production", production, "--scene", scene, "--out", out,
                "--min-speakers", "1", "--res", res, "--samples", samples]
        if character_dir:
            argv += ["--character-dir", character_dir]
        code, log, blocked = run(argv, env_extra={"AVX_HOME": str(tb.root / "auravox/data")}, timeout=6 * 3600)
        if blocked:
            return blocked
        rep_p = out / "gate4_report.json"
        if not rep_p.is_file():
            return ToolResult("FAIL", f"scene render exit {code}, no report", log[-3000:], code)
        rep = json.loads(rep_p.read_text())
        return ToolResult("PASS" if rep["status"] == "PASS" else "FAIL", f"{rep['frames']} frames, {rep['duration_s']:.2f}s, "
                          f"checks {rep['checks']}", log[-2000:], code, {"media": rep["mp4"], "report": str(rep_p)} | rep)

    def cartoon_episode(job: str, universe: str, episode: str) -> ToolResult:
        cli = _venv(tb, "cartoon-studio", "cartoon-studio")
        if not Path(cli).exists():
            return ToolResult("BLOCKED", "cartoon-studio/.venv is missing")
        cwd = tb.root / "cartoon-studio"
        code, out, blocked = run([cli, "run", "--job", job, "--universe", universe, "--episode", episode], cwd=cwd,
                                 timeout=3 * 3600)
        if blocked:
            return blocked
        final = cwd / "rendered-videos" / job / "final.mp4"
        if code != 0 or not final.is_file():
            return ToolResult("FAIL", f"cartoon-studio run exit {code}; no final.mp4", out[-3000:], code)
        code2, qc, _ = run([cli, "qc", "--video", final], cwd=cwd, timeout=600)
        return ToolResult("PASS" if code2 == 0 else "FAIL", f"episode {job}: final.mp4 written, studio QC exit {code2}",
                          (out[-1500:] + "\n--- qc ---\n" + qc[-1500:]), code2, {"media": str(final), "job": job})

    # ------------------------------------------------------------ TECHNICAL department
    def project_tests(project: str) -> ToolResult:
        py = _venv(tb, project)
        if not Path(py).exists():
            return ToolResult("BLOCKED", f"{project}/.venv is not installed")
        args = {"humanverse": [".claude/skills/humanverse-studio/tests"]}.get(project, [])
        code, out, blocked = run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=tb.root / project, timeout=1800)
        if blocked:
            return blocked
        tail = out.strip().splitlines()[-1] if out.strip() else ""
        return ToolResult("PASS" if code == 0 else "FAIL", f"{project}: {tail}", out[-4000:], code, {"project": project})

    S = Param(str)
    return [
        Tool("integration_probe", "Prove one integration works by doing real work with it (render a frame, encode and "
             "decode a clip, speak and measure, or a free read-only API call with an existing credential).",
             {"name": Param(str, choices=INTEGRATIONS)}, "network", 400, False, integration_probe),
        Tool("media_verify", "ffprobe and fully decode a media file: exists, non-empty, video stream, audio stream "
             "when required, valid duration, no decode errors.",
             {"path": Param(str, pattern=r"[\w./-]+"), "need_audio": Param(bool, required=False)}, "read", 700, False,
             media_verify),
        Tool("build_character", "HUMANVERSE: build a rigged 3D human (geometry, skeleton, skin weights, facial rig, "
             "deformation test, GLB/FBX) from its cast entry, into agency/out/production/<name>.",
             {"character": Param(str, pattern=CHAR), "name": Param(str, pattern=NAME)}, "execute", 700, False,
             build_character),
        Tool("voice_dialogue", "AURAVOX: produce a screenplay with the approved, locked character voices (takes, QA, "
             "retries, master, lip-sync data) as production <name>.",
             {"screenplay": Param(str, pattern=r"[\w./-]+"), "name": Param(str, pattern=NAME)}, "execute", 1900, False,
             voice_dialogue),
        Tool("talking_scene", "Blender: build a scene from an AURAVOX production with phoneme lip sync on the "
             "characters' rigs, render it with Cycles and mux the mastered audio to MP4.",
             {"production": Param(str, pattern=NAME), "name": Param(str, pattern=NAME),
              "character_dir": Param(str, required=False, pattern=r"[\w./-]+"),
              "scene": Param(str, required=False, pattern=r"S\d\d"),
              "res": Param(str, required=False, pattern=r"\d{2,4}x\d{2,4}"),
              "samples": Param(str, required=False, pattern=r"\d{1,3}")},
             "execute", 6 * 3600 + 60, False, talking_scene),
        Tool("cartoon_episode", "Cartoon Studio: run (or resume) its 13-step episode pipeline and its own QC.",
             {"job": S, "universe": S, "episode": S}, "execute", 3 * 3600 + 700, False, cartoon_episode),
        Tool("project_tests", "Run a production project's own test suite in its own environment.",
             {"project": Param(str, choices=("auravox", "humanverse", "cartoon-studio", "digital-human-factory"))},
             "execute", 1900, False, project_tests),
    ]


def recheck(task, call, toolbox) -> tuple[bool, str] | None:
    """Verifier side: re-probe a media file a PASS claims to have produced, instead of trusting the runner."""
    ev = json.loads(call["evidence"] or "{}")
    media = ev.get("media")
    if call["status"] != "PASS" or not media:
        return None
    ok, pev = probe_media(toolbox, media, need_audio=ev.get("streams") is None or "audio" in ev.get("streams", ["audio"]))
    return ok, (f"re-probed {Path(media).name}: {pev.get('duration_s')}s {pev.get('streams')}" if ok
                else f"re-probe of {media} failed: {pev.get('problem')}")

