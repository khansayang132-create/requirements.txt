"""Build the design library: 5 original characters per style, every reference, QC, rejection and bounded regeneration.

    cartoon-studio design build [--styles 01-cinematic-3d,06-anime] [--per-style 5]
    cartoon-studio design compare --character <id> --styles a,b,c,d,e

Output (design-library/, large images git-ignored; regenerate with the command):
    <style>/<character>/views/{front,three-quarter,side,back}.png   transparent turnaround references
    <style>/<character>/{turnaround,expression_sheet,proportions,palette,pose_sheet,character_sheet}.png
    <style>/<character>/{character.json,qc_report.json}
    <style>/{environment_concept.png,style_lineup.png,style_report.json}
    rejected/<style>/<character>-attemptN/   designs that failed QC, kept with their report (never silently dropped)
    library.json   every accepted character, its QC verdict and file hashes; distinctness between styles
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from . import engine as E
from . import qc
from .styles import STYLES

MAX_ATTEMPTS = 3
EXISTING_NAMES = {"Bobo", "Mimi", "Toto", "Zuzu", "Lolo", "Pipkin", "Brindle", "Morrow", "Tilli", "Oakley"}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build_style(sid: str, root: Path, n: int, taken: set[str], log=print) -> dict:
    st = STYLES[sid]
    out = root / sid
    out.mkdir(parents=True, exist_ok=True)
    accepted, rejected = [], []
    seed = 1
    pending = E.generate(sid, n, seed, taken)
    attempts: dict[int, int] = {}
    slot_chars = dict(enumerate(pending))
    while slot_chars:
        r = E.Renderer(list(slot_chars.values()))
        try:
            for slot, c in list(slot_chars.items()):
                t0 = time.time()
                try:
                    res = E.render_character(c, out, r)
                    rep = qc.check_character(Path(res["dir"]))
                except Exception as e:  # noqa: BLE001 - a render error is a rejected design, recorded
                    res, rep = {"dir": str(out / c.id)}, {"status": "FAIL", "checks": {"render": {"status": "FAIL", "detail": str(e)}}}
                attempts[slot] = attempts.get(slot, 0) + 1
                if rep["status"] == "PASS":
                    accepted.append(res | {"id": c.id, "name": c.name, "seconds": round(time.time() - t0, 1)})
                    log(f"  {sid} {c.name:8} {c.species:8} PASS ({time.time() - t0:.0f}s)")
                    del slot_chars[slot]
                    continue
                bad = {k: v["detail"] for k, v in rep["checks"].items() if v["status"] != "PASS"}
                dst = root / "rejected" / sid / f"{c.id}-attempt{attempts[slot]}"
                dst.parent.mkdir(parents=True, exist_ok=True)
                if Path(res["dir"]).exists():
                    shutil.rmtree(dst, ignore_errors=True)
                    shutil.move(res["dir"], dst)
                rejected.append({"id": c.id, "name": c.name, "attempt": attempts[slot], "failed": bad, "kept_at": str(dst)})
                log(f"  {sid} {c.name:8} REJECTED attempt {attempts[slot]}: {list(bad)}")
                if attempts[slot] >= MAX_ATTEMPTS:
                    del slot_chars[slot]
                    continue
                seed += 1
                slot_chars[slot] = E.generate(sid, slot + 1, seed * 100 + slot, taken)[slot]   # a new design for this slot
        finally:
            r.close()
    chars = [E.Character(**{k: v for k, v in json.loads((Path(a["dir"]) / "character.json").read_text()).items()
                            if k in E.Character.__dataclass_fields__}) for a in accepted]
    extras = {}
    if chars:
        r = E.Renderer(chars)
        try:
            extras["environment"] = str(E.environment(st, chars, r, out))
        finally:
            r.close()
        extras["lineup"] = str(E.lineup(st, accepted, out))
    report = {"style": sid, "name": st.name, "summary": st.summary, "accepted": len(accepted), "wanted": n,
              "status": "PASS" if len(accepted) == n else "FAIL", "characters": accepted, "rejected": rejected} | extras
    (out / "style_report.json").write_text(json.dumps(report, indent=2))
    return report


def build(root: Path, styles: list[str] | None = None, n: int = 5, log=print) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    taken = set(EXISTING_NAMES)
    for p in root.glob("*/*/character.json"):              # names already used in this library stay unique
        taken.add(json.loads(p.read_text())["name"])
    reports = {}
    for sid in styles or list(STYLES):
        log(f"{sid}: {STYLES[sid].name}")
        reports[sid] = build_style(sid, root, n, taken, log)
    lib = root / "library.json"
    old = json.loads(lib.read_text()) if lib.exists() else {"styles": {}}
    old["styles"].update({sid: {k: v for k, v in r.items() if k != "characters"} | {
        "characters": [{"id": c["id"], "name": c["name"],
                        "files": {f: _sha(Path(c["dir"]) / f) for f in c["files"]}} for c in r["characters"]]}
        for sid, r in reports.items()})
    done = {sid: [{"dir": str(root / sid / c["id"])} for c in v["characters"]] for sid, v in old["styles"].items()}
    old["distinctness"] = qc.style_distinctness(done) if len(done) > 1 else {}
    names = [c["name"] for v in old["styles"].values() for c in v["characters"]]
    old["unique_names"] = len(names) == len(set(names))
    lib.write_text(json.dumps(old, indent=2))
    return old


def previews(root: Path, width: int = 1600) -> list[Path]:
    """Compact JPEG previews of every style lineup, environment concept and comparison (committed as evidence)."""
    from PIL import Image

    out = root / "previews"
    out.mkdir(exist_ok=True)
    made = []
    for src in sorted([*root.glob("*/style_lineup.png"), *root.glob("*/environment_concept.png"),
                       *root.glob("comparisons/*.png"), *root.glob("*/*/character_sheet.png")]):
        if "rejected" in src.parts:
            continue
        im = Image.open(src).convert("RGB")
        w = width if "character_sheet" not in src.name else 1200
        im.thumbnail((w, w * 2))
        name = "__".join(src.relative_to(root).with_suffix(".jpg").parts)
        dst = out / name
        im.save(dst, quality=82, optimize=True)
        made.append(dst)
    return made


def reindex(root: Path) -> dict:
    """Rebuild library.json from every style on disk, re-running the current QC on each accepted character, so the
    index never mixes verdicts from older rules. A character that now fails is reported, not hidden."""
    styles = {}
    for rp in sorted(root.glob("*/style_report.json")):
        rep = json.loads(rp.read_text())
        chars = []
        for c in rep["characters"]:
            d = Path(c["dir"])
            q = qc.check_character(d)
            chars.append({"id": c["id"], "name": c["name"], "qc": q["status"],
                          "files": {f: _sha(d / f) for f in c["files"]}})
        ok = sum(ch["qc"] == "PASS" for ch in chars)
        styles[rep["style"]] = {"name": rep["name"], "summary": rep["summary"], "accepted": ok, "wanted": rep["wanted"],
                                "status": "PASS" if ok == rep["wanted"] else "FAIL", "characters": chars,
                                "rejected_during_build": len(rep["rejected"])}
    done = {sid: [{"dir": str(root / sid / c["id"])} for c in v["characters"]] for sid, v in styles.items()}
    names = [c["name"] for v in styles.values() for c in v["characters"]]
    lib = {"styles": styles, "unique_names": len(names) == len(set(names)), "characters": len(names),
           "distinctness": qc.style_distinctness(done)}
    (root / "library.json").write_text(json.dumps(lib, indent=2))
    return lib
