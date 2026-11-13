"""avx: AURAVOX X command line.

  avx doctor                                   environment, engines, technology registry -> reports/
  avx models catalog|list|install KEY [--approve]|verify KEY|remove KEY
  avx voices from-humanverse CAST_DIR | create CHARACTER.json | audition VID [-n 4] | approve VID TAKE --by NAME
             | list | redesign VID --by NAME --reason TEXT | export VID
  avx pron add WORD RESPELL [--lang en-us] | list
  avx produce SCREENPLAY --name NAME           plan the job graph (lines -> assemble -> master + lip-sync report)
  avx work [--workers 2] [--max-seconds N]     run queued jobs until idle (resumes after a crash)
  avx queue [list|cancel|pause|resume|retry JOB]
  avx humanverse-export NAME HV_PROJECT        write HUMANVERSE audio/lines/lines.json from a production
  avx skills scan PATH | install PATH --target claude|codex --project DIR | rollback NAME --target T --project DIR | list
  avx serve [--port 8765]                      production control centre (127.0.0.1)
  avx say TEXT --character ID [--emotion E]    one line through the full take/evaluate/refine loop
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import production, registry, voices
from .queue import Queue
from .studio import Studio


def jp(x):
    print(json.dumps(x, indent=2, ensure_ascii=False, default=str))


def cmd_doctor(s: Studio, a):
    health = s.refresh_engines()
    gpu = None
    if shutil.which("nvidia-smi"):
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
    from .queue import mem_available_mb
    env = {"os": platform.platform(), "python": platform.python_version(), "cpu_cores": __import__("os").cpu_count(),
           "memory_available_mb": round(mem_available_mb()), "gpu": gpu or "none detected",
           "disk_free_mb": round(s.store.disk_free_mb()), "ffmpeg": shutil.which("ffmpeg"), "home": str(s.home)}
    reg = registry.status({"espeak-ng": health["espeak-ng"], "piper": health["piper"]})
    rep = s.home / "reports"
    rep.mkdir(exist_ok=True)
    (rep / "environment.md").write_text("# Environment\n\n" + "\n".join(f"- **{k}**: {v}" for k, v in env.items()) + "\n")
    (rep / "engines.md").write_text("# Engines\n\n| Engine | Status | Evidence |\n|---|---|---|\n" +
                                    "\n".join(f"| {k} | {v[0]} | {v[1]} |" for k, v in health.items()) + "\n")
    (rep / "technology-registry.md").write_text(
        f"# Voice technology registry (checked {registry.CHECKED})\n\nNothing here is installed automatically.\n\n"
        "| Technology | Capabilities | Code licence | Weights licence | Hardware | Installed here | Status | Limits |\n|---|---|---|---|---|---|---|---|\n" +
        "\n".join(f"| [{t['name']}]({t['source']}) | {', '.join(t['caps'])} | {t['licence']} | {t['weights']} | {t['hardware']} | {t['local']} | "
                  f"{t['status']} | {t['limits']} |" for t in reg) + "\n")
    jp({"environment": env, "engines": health, "reports": [str(p) for p in sorted(rep.glob("*.md"))]})


def cmd_models(s: Studio, a):
    if a.op == "catalog":
        try:
            jp(s.store.catalog.stats())
        except Exception as e:  # noqa: BLE001
            jp({"status": "BLOCKED", "reason": str(e)})
            sys.exit(2)
    elif a.op == "list":
        jp([{k: m[k] for k in ("key", "engine", "license", "status", "bytes")} for m in s.db.q("SELECT * FROM models")])
    elif a.op == "install":
        jid = Queue(s).enqueue("model.install", {"key": a.key, "approve": a.approve}, title=f"install {a.key}", priority=90, max_attempts=2)
        Queue(s).run(production.HANDLERS, workers=1)
        jp(Queue(s).get(jid))
    elif a.op == "verify":
        jp(s.store.verify(a.key))
    elif a.op == "remove":
        jp({"removed": s.store.remove(a.key)})


def cmd_voices(s: Studio, a):
    if a.op == "from-humanverse":
        out = []
        for p in sorted(Path(a.arg).glob("*.json")):
            c = json.loads(p.read_text())
            try:
                out.append(voices.create(s, voices.from_character(c)))
            except voices.VoiceLocked as e:
                out.append(f"kept {e}")
        jp(out)
    elif a.op == "create":
        jp(voices.create(s, voices.from_character(json.loads(Path(a.arg).read_text()))))
    elif a.op == "audition":
        jp(voices.audition(s, a.arg, a.n))
    elif a.op == "approve":
        v = voices.approve(s, a.arg, a.take, a.by)
        jp({k: v[k] for k in ("voice_id", "status", "profile_sha", "engine", "model", "approved_by")})
    elif a.op == "list":
        jp([{k: v[k] for k in ("voice_id", "character_id", "name", "status", "engine", "model", "profile_sha", "approved_by")}
            for v in s.db.q("SELECT * FROM voices ORDER BY voice_id")])
    elif a.op == "redesign":
        voices.redesign(s, a.arg, a.by, a.reason)
        jp({"redesign": a.arg})
    elif a.op == "export":
        jp(str(voices.export_profile(s, a.arg, s.home / "exports" / f"{a.arg}.json")))
    elif a.op == "select-cast":
        vids = [v["voice_id"] for v in s.db.q("SELECT voice_id FROM voices WHERE status='auditioned' ORDER BY voice_id")]
        jp(voices.select_cast(s, vids, a.by or "Voice Design Agent"))


def cmd_produce(s: Studio, a):
    jp(production.plan_production(s, Path(a.screenplay), a.name, a.gap))


def cmd_work(s: Studio, a):
    jp(Queue(s).run(production.HANDLERS, workers=a.workers, max_seconds=a.max_seconds))
    jp(Queue(s).summary())


def cmd_queue(s: Studio, a):
    q = Queue(s)
    if a.op == "list":
        for j in s.db.q("SELECT id, kind, title, status, attempts, error FROM jobs ORDER BY id"):
            print(f"{j['id']}  {j['status']:10} {j['attempts']}  {j['kind']:18} {j['title'][:44]:44} {(j['error'] or '')[:70]}")
        jp(q.summary())
    else:
        getattr(q, a.op)(a.job)
        jp(q.get(a.job))


def cmd_hv_export(s: Studio, a):
    meta = json.loads((s.home / "productions" / a.name / "dialogue.json").read_text())
    jp(str(production.export_humanverse_lines(meta, Path(a.hv_project) / "audio" / "lines" / "lines.json")))


def cmd_pron(s: Studio, a):
    if a.op == "add":
        s.db.insert("pronunciations", {"word": a.word, "lang": a.lang, "respell": a.respell, "note": "manual"})
    jp(s.db.q("SELECT * FROM pronunciations"))


def cmd_skills(s: Studio, a):
    from . import skills
    if a.op == "scan":
        jp(skills.scan(Path(a.path)))
    elif a.op == "install":
        jp(skills.install(s, Path(a.path), a.target, Path(a.project), replace=a.replace))
    elif a.op == "rollback":
        jp(skills.rollback(s, a.path, a.target, Path(a.project)))
    elif a.op == "list":
        jp(s.db.q("SELECT name, target, path, status, installed_at FROM skills"))


def cmd_serve(s: Studio, a):
    from .server import serve
    serve(s, a.port)


def cmd_say(s: Studio, a):
    jid = Queue(s).enqueue("dialogue.line", {"line": {"line_id": f"SAY{int(time.time())}", "character_id": a.character, "text": a.text,
                                                      "emotion": a.emotion}}, title="say")
    Queue(s).run(production.HANDLERS, workers=1)
    jp(Queue(s).get(jid))


def main(argv=None):
    p = argparse.ArgumentParser(prog="avx", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--home", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    m = sub.add_parser("models")
    m.add_argument("op", choices=["catalog", "list", "install", "verify", "remove"])
    m.add_argument("key", nargs="?")
    m.add_argument("--approve", action="store_true")
    m.set_defaults(fn=cmd_models)
    v = sub.add_parser("voices")
    v.add_argument("op", choices=["from-humanverse", "create", "audition", "approve", "list", "redesign", "export", "select-cast"])
    v.add_argument("arg", nargs="?")
    v.add_argument("take", nargs="?")
    v.add_argument("-n", type=int, default=4)
    v.add_argument("--by", default=None)
    v.add_argument("--reason", default="")
    v.set_defaults(fn=cmd_voices)
    pr = sub.add_parser("produce")
    pr.add_argument("screenplay")
    pr.add_argument("--name", required=True)
    pr.add_argument("--gap", type=float, default=0.35)
    pr.set_defaults(fn=cmd_produce)
    w = sub.add_parser("work")
    w.add_argument("--workers", type=int, default=2)
    w.add_argument("--max-seconds", type=float, default=None)
    w.set_defaults(fn=cmd_work)
    q = sub.add_parser("queue")
    q.add_argument("op", nargs="?", default="list", choices=["list", "cancel", "pause", "resume", "retry"])
    q.add_argument("job", nargs="?")
    q.set_defaults(fn=cmd_queue)
    h = sub.add_parser("humanverse-export")
    h.add_argument("name")
    h.add_argument("hv_project")
    h.set_defaults(fn=cmd_hv_export)
    pn = sub.add_parser("pron")
    pn.add_argument("op", choices=["add", "list"])
    pn.add_argument("word", nargs="?")
    pn.add_argument("respell", nargs="?")
    pn.add_argument("--lang", default="en-us")
    pn.set_defaults(fn=cmd_pron)
    sk = sub.add_parser("skills")
    sk.add_argument("op", choices=["scan", "install", "rollback", "list"])
    sk.add_argument("path", nargs="?")
    sk.add_argument("--target", default="claude", choices=["claude", "codex"])
    sk.add_argument("--project", default=".")
    sk.add_argument("--replace", action="store_true")
    sk.set_defaults(fn=cmd_skills)
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8765)
    sv.set_defaults(fn=cmd_serve)
    sy = sub.add_parser("say")
    sy.add_argument("text")
    sy.add_argument("--character", required=True)
    sy.add_argument("--emotion", default="neutral")
    sy.set_defaults(fn=cmd_say)
    a = p.parse_args(argv)
    a.fn(Studio(a.home), a)


if __name__ == "__main__":
    main()
