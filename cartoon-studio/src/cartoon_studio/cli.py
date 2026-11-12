"""cartoon-studio command line.

  doctor                          providers, tools and the local engine: PASS / BLOCKED / FAIL (no spend)
  agents                          the ten agents
  init-universe --concept TEXT    invent an original universe (five characters)
  import-universe --id ID         bring a v0.3 text universe (e.g. mosslight-valley) into V3; owner files untouched
  init-characters --universe ID   render the character bibles (references, sheets, voices, hash locks)
  write-episode --universe ID     seven-act episode script (--plot, --seconds)
  storyboard --episode ID         shot list
  run --job ID ...                the 13-step resumable production; --approve-spend allows paid providers
  qc --video PATH                 ffprobe + decode check of any video
  init-demo                       the v0.3 text-only sample universe
  integration-audit               Codex / Claude Code integration readiness (v0.3)
"""

from __future__ import annotations

import asyncio
import json
import platform
import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .agents.team import (
    AGENTS,
    UNIVERSE_FILE,
    CartoonCreativeDirectorAgent,
    CharacterDesignerAgent,
    Context,
    ProductionManagerAgent,
    StoryboardArtistAgent,
    StoryWriterAgent,
    save_universe,
)
from .config import Settings
from .errors import StudioError
from .media.probe import probe_video
from .state import ProductionState

app = typer.Typer(no_args_is_help=True, help=__doc__)
console = Console()


def _ctx(workspace: Path | None) -> Context:
    s = Settings()
    if workspace:
        s.cs_workspace = workspace
    return Context(s)


WS = typer.Option(None, "--workspace", help="project folder (default: current folder or CS_WORKSPACE)")


@app.command()
def doctor(workspace: Path | None = WS, json_output: bool = typer.Option(False, "--json")):
    """Read-only checks. Never calls a paid endpoint."""
    from .providers import adapters  # noqa: F401
    from .providers.base import REGISTRY, get_provider

    ctx = _ctx(workspace)
    rows = []
    for name in sorted(REGISTRY):
        try:
            h = get_provider(name, ctx.settings).health()
            rows.append({"component": name, "status": "PASS" if h.get("ok") else "FAIL", "detail": h.get("detail", "")})
        except StudioError as e:
            rows.append({"component": name, "status": "BLOCKED", "detail": str(e)})
        except Exception as e:  # noqa: BLE001 - shown, not hidden
            rows.append({"component": name, "status": "FAIL", "detail": f"{type(e).__name__}: {e}"[:200]})
    s = ctx.settings
    if s.secret("kling_api_key") and not (s.secret("kling_access_key") and s.secret("kling_secret_key")):
        rows.append({"component": "kling (v0.3 KLING_API_KEY)", "status": "BLOCKED",
                     "detail": "Kling's API signs requests with KLING_ACCESS_KEY + KLING_SECRET_KEY; a single KLING_API_KEY is not enough"})
    if s.comfyui_base_url:
        rows.append({"component": "comfyui (local server)", "status": "BLOCKED",
                     "detail": f"COMFYUI_BASE_URL={s.comfyui_base_url} is set, but only Comfy Cloud (COMFY_API_KEY) is driven so far"})
    for tool in ("ffmpeg", "ffprobe"):
        p = shutil.which(tool)
        rows.append({"component": tool, "status": "PASS" if p else "BLOCKED", "detail": p or f"{tool} not found on PATH"})
    rows.append({"component": "python", "status": "PASS", "detail": platform.python_version()})
    rows.append({"component": "agents", "status": "PASS", "detail": f"{len(AGENTS)} agent classes"})
    if json_output:
        console.print_json(json.dumps(rows))
        return
    t = Table("Component", "Status", "Detail")
    for r in rows:
        t.add_row(r["component"], r["status"], r["detail"])
    console.print(t)
    console.print("No credentials printed; no paid or billable request made.")


@app.command()
def agents():
    for cls in AGENTS:
        console.print(f"PASS  {cls.__name__:32} {cls.description}")


@app.command("init-universe")
def init_universe(concept: str = typer.Option(..., "--concept"), seed: str = typer.Option("1", "--seed"), workspace: Path | None = WS):
    u = CartoonCreativeDirectorAgent(_ctx(workspace)).create(concept, seed)
    console.print_json(json.dumps({"universe_id": u.universe_id, "title": u.title, "characters": [c.name for c in u.characters],
                                   "places": u.places, "originality": u.originality}))


@app.command("import-universe")
def import_universe(uid: str = typer.Option(..., "--id"), workspace: Path | None = WS):
    """Convert a v0.3 universe; place names come from its stories. The owner's JSON files are not modified."""
    from .generators.importer import import_legacy

    ctx = _ctx(workspace)
    names: dict[str, int] = {}
    for p in sorted((ctx.root / "stories" / uid).glob("*.json")):
        for s in json.loads(p.read_text(encoding="utf-8")).get("scenes", []):
            names[s.get("location", "")] = 1
    u = import_legacy(ctx.root, uid, {n: 1 for n in names if n})
    save_universe(ctx.root, u)
    console.print_json(json.dumps({"universe_id": uid, "file": f"universes/{uid}/{UNIVERSE_FILE}", "places": u.places,
                                   "bodies": {c.name: c.visual.engine_body for c in u.characters}, "warnings": u.originality["warnings"]}))


@app.command("init-characters")
def init_characters(universe: str = typer.Option(..., "--universe"), backend: str = typer.Option("auto", "--backend"), workspace: Path | None = WS):
    ctx = _ctx(workspace)
    out = CharacterDesignerAgent(ctx).design(ctx.universe(universe), backend)
    console.print_json(json.dumps({cid: {"files": sorted(h)} for cid, h in out.items()}))


@app.command("write-episode")
def write_episode(universe: str = typer.Option(..., "--universe"), plot: str | None = typer.Option(None, "--plot"),
                  seed: str = typer.Option("1", "--seed"), seconds: int = typer.Option(60, "--seconds"), workspace: Path | None = WS):
    e = StoryWriterAgent(_ctx(workspace)).write(universe, plot, seed, seconds)
    console.print_json(json.dumps({"episode_id": e.episode_id, "title": e.title, "scenes": len(e.scenes), "acts": sorted({s.act for s in e.scenes})}))


@app.command()
def storyboard(episode: str = typer.Option(..., "--episode"), universe: str = typer.Option(..., "--universe"), workspace: Path | None = WS):
    st = ProductionState(job_id="storyboard", universe_id=universe, episode_id=episode)
    res = asyncio.run(StoryboardArtistAgent(_ctx(workspace)).run(st))
    console.print_json(res.model_dump_json())


@app.command()
def run(job: str = typer.Option(..., "--job"), universe: str | None = typer.Option(None, "--universe"), episode: str | None = typer.Option(None, "--episode"),
        seconds: int = typer.Option(60, "--seconds"), backend: str = typer.Option("auto", "--backend"),
        video_provider: str = typer.Option("none", "--video-provider"), approve_spend: bool = typer.Option(False, "--approve-spend"),
        width: int = typer.Option(1080, "--width"), height: int = typer.Option(1920, "--height"), workspace: Path | None = WS):
    """Run (or resume) a job. Finished steps are skipped; a paid step never runs without --approve-spend."""
    ctx = _ctx(workspace)
    path = ctx.root / "jobs" / job / "state.json"
    if path.is_file():
        st = ProductionState.load(path)
        st.spend_approved = approve_spend
    else:
        if not (universe and episode):
            raise typer.BadParameter("a new job needs --universe and --episode")
        st = ProductionState(job_id=job, universe_id=universe, episode_id=episode, target_seconds=seconds, backend=backend,
                             video_provider=video_provider, spend_approved=approve_spend, resolution=(width, height))
    res = asyncio.run(ProductionManagerAgent(ctx).run(st))
    t = Table("Step", "Status", "Detail")
    for k, v in st.steps.items():
        t.add_row(k, v.status, v.detail[:110])
    console.print(t)
    console.print(f"final video: {res.metadata.get('final_video')}   QC: {st.qc_status}   spent: ${st.spent_usd:.2f}")
    if not res.metadata.get("final_video"):
        raise typer.Exit(1)


@app.command()
def qc(video: Path = typer.Option(..., "--video")):
    result = probe_video(str(video))
    console.print_json(json.dumps(result))
    if result["status"] != "PASS":
        raise typer.Exit(1)


@app.command("init-demo")
def init_demo(output: Path = typer.Option(Path.cwd(), "--output")):
    from .pipeline.demo import create_demo

    console.print_json(json.dumps(create_demo(output)))


@app.command("integration-audit")
def integration_audit(json_output: bool = typer.Option(False, "--json")):
    """Audit Codex/Claude integration readiness without changing host settings."""
    from .integrations import integration_report

    result = integration_report(Path.cwd())
    if json_output:
        console.print_json(json.dumps(result))
        return
    table = Table("Integration", "Status", "Evidence")
    for row in result["integrations"]:
        table.add_row(row["name"], row["status"], row["detail"])
    console.print(table)
    console.print("Safety: no credentials read; no external or paid calls; no settings changed.")


if __name__ == "__main__":
    app()
