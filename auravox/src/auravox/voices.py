"""Character voice factory: permanent voice identities for original fictional characters.

create -> audition (several candidate settings, each measured) -> approve (locks the profile; its sha256 is stored)
-> every later line is generated from the locked profile and tagged with that hash. Changing an approved voice
requires a new approval; nothing changes it silently.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import analysis, perform
from .router import route

AUDITION_LINE = "Hello! This is how I sound when I'm happy, and this is how I sound when I'm thinking."


class VoiceLocked(RuntimeError):
    pass


def profile_sha(p: dict) -> str:
    core = {k: p[k] for k in sorted(p) if k not in ("notes",)}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:16]


def from_character(c: dict) -> dict:
    """Map a character bible (HUMANVERSE cast file or AURAVOX character json) to a voice brief."""
    age = int(c.get("age", 30))
    v = c.get("voice", {})
    hv = v.get("espeak_voice", "")
    pres = c.get("presentation") or ("female" if "+f" in hv else "male" if "+m" in hv else "neutral")
    pitch = v.get("pitch", 82 if age < 13 else 60 if age < 18 else 30 if age > 65 else 52 if pres == "female" else 42)
    return {"character_id": c["id"], "name": c.get("name", c["id"]), "presentation": pres, "age": age,
            "language": v.get("language", "en-us"), "accent": v.get("accent", "General American"),
            "pitch": pitch, "rate_wpm": v.get("rate", 160 if age < 13 else 128 if age > 65 else 150),
            "range": v.get("range", 75 if age < 13 else 50 if age > 65 else 60),
            "texture": v.get("texture", "bright" if age < 13 else "warm, slightly rough" if age > 65 else "clear"),
            "resonance": v.get("resonance", "head" if age < 18 else "chest"), "articulation": v.get("articulation", "clear"),
            "emotional_range": v.get("emotional_range", list(perform.EMOTION)), "pronunciation": v.get("pronunciation", {}),
            "variant": hv.split("+")[1] if "+" in hv else None}


def create(studio, brief: dict) -> str:
    vid = f"AVX-VOICE-{brief['character_id']}"
    old = studio.db.one("SELECT * FROM voices WHERE voice_id = ?", (vid,))
    if old and old["status"] == "approved":
        raise VoiceLocked(f"{vid} is approved; a new design needs `avx voices redesign` and a new approval")
    studio.db.insert("voices", {"voice_id": vid, "character_id": brief["character_id"], "name": brief["name"], "profile": brief,
                                "profile_sha": None, "status": "design", "created": time.time()})
    return vid


def candidates(studio, brief: dict, n: int = 4) -> list[dict]:
    """Concrete engine settings to audition, from the engines the router accepts for this brief."""
    r = route(studio, {"language": brief["language"], "presentation": brief["presentation"], "emotion": "happy", "need_timing": True})
    out = []
    for acc in r["ranked"]:
        eng = acc["engine"]
        if eng == "espeak-ng":
            from .engines.espeak import VARIANTS
            vs = VARIANTS.get(brief["presentation"], VARIANTS["neutral"])
            pref = [brief["variant"]] if brief.get("variant") in vs else []
            for i, var in enumerate((pref + [v for v in vs if v not in pref])[:n]):
                out.append({"engine": eng, "language": brief["language"], "variant": var, "pitch": max(0, min(99, brief["pitch"] + (i % 2) * 4 - 2 * (i // 2))),
                            "rate_wpm": brief["rate_wpm"], "range": brief["range"]})
        elif eng == "piper":
            for m in studio.store.installed("piper")[:n]:
                for sid in list((m["meta"].get("speakers") or {}).values())[:2] or [None]:
                    out.append({"engine": eng, "language": brief["language"], "model": m["key"], "speaker_id": sid, "length_scale": 1.0,
                                "noise_scale": 0.667})
    return out[: max(n, 1) * 2], r


def audition(studio, vid: str, n: int = 4) -> list[dict]:
    v = studio.db.one("SELECT * FROM voices WHERE voice_id = ?", (vid,))
    if v["status"] == "approved":
        raise VoiceLocked(f"{vid} is approved")
    brief = v["profile"]
    cands, routing = candidates(studio, brief, n)
    if not cands:
        raise RuntimeError(f"no engine can voice {vid}: {routing['rejected']}")
    results = []
    for i, cand in enumerate(cands):
        eng = studio.engines[cand["engine"]]
        tid = studio.db.next_id("AVX-TAKE")
        out = studio.home / "auditions" / vid / f"{tid}.wav"
        c = perform.direct({"text": AUDITION_LINE, "emotion": "happy"})
        g = eng.generate(c["text"], cand, c, out)
        m = analysis.measure(out, AUDITION_LINE, cand.get("rate_wpm", 150))
        studio.db.insert("takes", {"take_id": tid, "line_id": "AUDITION", "voice_id": vid, "version": 1, "kind": "audition", "path": str(out),
                                   "sha256": g["sha256"], "settings": cand, "metrics": m, "defects": m["defects"], "score": m["score"],
                                   "status": "candidate", "created": time.time()})
        results.append({"take_id": tid, "settings": cand, "score": m["score"], "defects": [d["code"] for d in m["defects"]], "path": str(out)})
    studio.db.update("voices", "voice_id", vid, status="auditioned")
    return results


def approve(studio, vid: str, take_id: str, by: str) -> dict:
    t = studio.db.one("SELECT * FROM takes WHERE take_id = ? AND voice_id = ?", (take_id, vid))
    if not t:
        raise ValueError(f"{take_id} is not an audition of {vid}")
    v = studio.db.one("SELECT * FROM voices WHERE voice_id = ?", (vid,))
    if v["status"] == "approved":
        raise VoiceLocked(f"{vid} is already approved")
    prof = {**v["profile"], **t["settings"]}
    if prof["engine"] == "piper":
        prof["model_version"] = studio.store.get(prof["model"])["sha256"][:16]
    else:
        import importlib.metadata as md
        prof["model_version"] = "espeak-ng via espeakng-loader " + md.version("espeakng-loader")
    sha = profile_sha(prof)
    studio.db.update("voices", "voice_id", vid, profile=prof, profile_sha=sha, engine=prof["engine"], model=prof.get("model") or prof.get("variant"),
                     model_version=prof["model_version"], status="approved", approved_by=by, approved_at=time.time(), audition_take=take_id)
    studio.db.update("takes", "take_id", take_id, selected=1, status="approved_audition")
    for k, val in (prof.get("pronunciation") or {}).items():
        studio.db.insert("pronunciations", {"word": k, "lang": prof["language"], "respell": val, "note": f"from {vid}"})
    return studio.db.one("SELECT * FROM voices WHERE voice_id = ?", (vid,))


def approved(studio, character_id: str) -> dict:
    v = studio.db.one("SELECT * FROM voices WHERE character_id = ? AND status = 'approved'", (character_id,))
    if not v:
        raise VoiceLocked(f"no approved voice for {character_id}: audition and approve one first")
    if profile_sha(v["profile"]) != v["profile_sha"]:
        raise VoiceLocked(f"{v['voice_id']} profile changed after approval (hash mismatch): blocked")
    return v


def redesign(studio, vid: str, by: str, reason: str) -> None:
    """An approved design change: the old identity is retired (kept), a new design starts."""
    v = studio.db.one("SELECT * FROM voices WHERE voice_id = ?", (vid,))
    studio.db.insert("voices", {**{k: v[k] for k in v}, "voice_id": f"{vid}@retired-{int(time.time())}", "status": "retired"})
    studio.db.update("voices", "voice_id", vid, status="design", profile_sha=None, approved_by=None, approved_at=None)
    studio.db.event(f"{vid} redesign approved by {by}: {reason}")


def export_profile(studio, vid: str, out: Path) -> Path:
    v = studio.db.one("SELECT * FROM voices WHERE voice_id = ?", (vid,))
    out.write_text(json.dumps({k: v[k] for k in ("voice_id", "character_id", "name", "profile", "profile_sha", "engine", "model",
                                                 "model_version", "status", "approved_by", "audition_take")}, indent=2))
    return out


def select_cast(studio, vids: list[str], by: str, min_sep: float = 0.15) -> dict:
    """Pick one audition per voice so the cast is distinguishable: maximise the smallest pitch separation between any
    two voices (median F0, measured), then the total score. Voices with the same presentation also get different
    engine variants where possible. Approves the chosen takes."""
    import itertools

    from . import analysis
    opts = {}
    for vid in vids:
        rows = [t for t in studio.db.q("SELECT * FROM takes WHERE voice_id=? AND kind='audition'", (vid,)) if not analysis.blocking(t["metrics"])]
        for t in rows:
            t["f0"] = analysis.f0_median(Path(t["path"]))
        opts[vid] = [t for t in rows if t["f0"]]
        if not opts[vid]:
            raise RuntimeError(f"{vid}: no usable audition")
    best, best_key = None, None
    for combo in itertools.product(*opts.values()):
        f0 = sorted(t["f0"] for t in combo)
        sep = min((b - a) / a for a, b in zip(f0, f0[1:])) if len(f0) > 1 else 1.0
        variants = [t["settings"].get("variant") or t["settings"].get("model") for t in combo]
        dup = len(variants) - len(set(variants))
        key = (sep >= min_sep, -dup, round(sep, 3), sum(t["score"] for t in combo))
        if best_key is None or key > best_key:
            best, best_key = combo, key
    approved = {}
    for vid, t in zip(opts, best):
        approve(studio, vid, t["take_id"], by)
        approved[vid] = {"take": t["take_id"], "f0_hz": t["f0"], "score": t["score"], "settings": {k: t["settings"].get(k) for k in ("engine", "variant", "pitch", "model")}}
    f0 = sorted(v["f0_hz"] for v in approved.values())
    return {"approved": approved, "min_pitch_separation": round(min((b - a) / a for a, b in zip(f0, f0[1:])), 3) if len(f0) > 1 else None,
            "distinct": best_key[0], "duplicate_variants": -best_key[1]}
