"""dhfactory command line.

  dhfactory doctor                                   environment + provider health (read-only, spends nothing)
  dhfactory init-job --script FILE [--job ID] [--voice P --avatar P --image P --video P] [--duration S] [--size WxH]
  dhfactory run --job ID [--approve-spend]           run / resume the 14-step pipeline
  dhfactory status --job ID
  dhfactory qc --video FILE [--size WxH --duration S]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .agents import ALL_AGENTS, Context
from .agents.production_manager import ProductionManagerAgent
from .agents.quality_control import check_video
from .config import PROVIDER_ENV, Settings
from .errors import DHFError, ProviderNotConfigured
from .providers.base import REGISTRY, get_provider
from .state import ProductionState
from .utils.files import safe_id
from .utils.redaction import redact


def _size(text: str) -> tuple[int, int]:
    w, h = text.lower().split("x")
    return int(w), int(h)


def doctor(settings: Settings) -> dict:
    def ver(cmd):
        try:
            return subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=20).stdout.strip().splitlines()[0]
        except Exception:  # noqa: BLE001
            return None

    get_provider("mock", settings)  # load registry
    env = {"python": platform.python_version(), "platform": f"{platform.system()} {platform.machine()}", "dhfactory": __version__,
           "ffmpeg": ver(["ffmpeg", "-version"]), "gpu": ver(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"]) if shutil.which("nvidia-smi") else None,
           "higgsfield_cli": ver(["higgsfield", "version"]) if shutil.which("higgsfield") else None}
    providers = {}
    for name in sorted(REGISTRY):
        p = get_provider(name, settings)
        row = {"capabilities": sorted(p.capabilities), "paid": p.paid, "env": p.env_var}
        try:
            row.update(status="PASS", **p.health())
        except ProviderNotConfigured as e:
            row.update(status="BLOCKED", detail=e.needs)
        except DHFError as e:
            row.update(status="BLOCKED" if getattr(e, "status", "") == "blocked" else "FAIL", detail=redact(str(e)))
        except Exception as e:  # noqa: BLE001
            row.update(status="FAIL", detail=redact(f"{type(e).__name__}: {e}")[:300])
        providers[name] = row
    agents = {cls.name: cls.description for cls in ALL_AGENTS}
    return {"environment": env, "credentials_present": {k: bool(settings.key(k)) for k in PROVIDER_ENV}, "providers": providers, "agents": agents}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dhfactory", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    ij = sub.add_parser("init-job")
    ij.add_argument("--script", required=True)
    ij.add_argument("--job")
    for cap, default in (("voice", "mock"), ("avatar", "mock"), ("image", "mock"), ("video", "none")):
        ij.add_argument(f"--{cap}", default=default)
    ij.add_argument("--duration", type=float, default=10.0)
    ij.add_argument("--size", default="1080x1920")
    ij.add_argument("--language", default="en")
    r = sub.add_parser("run")
    r.add_argument("--job", required=True)
    r.add_argument("--approve-spend", action="store_true", help="allow paid provider calls for this run (still capped by DHF_MAX_SPEND_USD)")
    st = sub.add_parser("status")
    st.add_argument("--job", required=True)
    q = sub.add_parser("qc")
    q.add_argument("--video", required=True)
    q.add_argument("--size", default="1080x1920")
    q.add_argument("--duration", type=float)
    a = ap.parse_args(argv)
    settings = Settings()

    if a.cmd == "doctor":
        print(json.dumps(doctor(settings), indent=2))
        return 0
    if a.cmd == "init-job":
        script = Path(a.script).read_text(encoding="utf-8")
        job = safe_id(a.job or Path(a.script).stem)
        for cap in ("voice", "avatar", "image", "video"):
            name = getattr(a, cap)
            if name != "none":
                get_provider(name, settings)   # unknown provider names fail here, not mid-run
        state = ProductionState(job_id=job, script=script, duration_target=a.duration, resolution=_size(a.size), language=a.language,
                                providers={"voice": a.voice, "avatar": a.avatar, "image": a.image, "video": a.video})
        path = settings.root / "jobs" / job / "state.json"
        if path.exists():
            print(f"job {job} already exists: {path}", file=sys.stderr)
            return 2
        state.save(path)
        print(json.dumps({"job": job, "state": str(path), "providers": state.providers}))
        return 0
    if a.cmd in ("run", "status"):
        path = settings.root / "jobs" / safe_id(a.job) / "state.json"
        if not path.is_file():
            print(f"no job {a.job}: run init-job first", file=sys.stderr)
            return 2
        state = ProductionState.load(path)
        if a.cmd == "status":
            print(json.dumps(ProductionManagerAgent(Context.for_job(settings, state.job_id)).report(state), indent=2))
            return 0
        state.spend_approved = bool(a.approve_spend)
        manager = ProductionManagerAgent(Context.for_job(settings, state.job_id))
        res = asyncio.run(manager.run(state, "manager"))
        rep = res.metadata
        for k, v in rep["steps"].items():
            print(f"{v['status']:26s} {k:32s} {v['detail'][:110]}")
        print(json.dumps({"final_video": rep["final_video"], "qc": rep["qc"], "spent_usd": rep["spent_usd"], "report": res.artifact_paths[0]}, indent=2))
        return 0 if rep["final_video"] and rep["qc"] in ("PASS", "BLOCKED") else 1
    if a.cmd == "qc":
        w, h = _size(a.size)
        rep = check_video(Path(a.video), width=w, height=h, duration_target=a.duration)
        print(json.dumps(rep, indent=2))
        return 0 if rep["overall"] != "FAIL" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
