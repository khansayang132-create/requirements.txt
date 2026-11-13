"""Capability-based engine routing. Engines are chosen by verified capability, health and licence; never by name.

route() returns every engine with the reason it was accepted or rejected, best first. A language an engine does
not support is a rejection, never a silent substitution.
"""

from __future__ import annotations


def lang_ok(engine_langs: list[str], want: str) -> bool:
    w = want.lower().replace("_", "-")
    base = w.split("-")[0]
    for lg in engine_langs:
        lg = lg.lower().replace("_", "-")
        if lg == w or lg == base or lg.split("-")[0] == base:
            return True
    return False


def route(studio, req: dict) -> dict:
    """req: language, presentation (female|male|neutral|any), emotion, need_timing, commercial_use, prefer"""
    accepted, rejected = [], []
    want_lang = req.get("language", "en")
    for name, eng in studio.engines.items():
        st, detail = studio.engine_health(name)
        if st != "PASS":
            rejected.append({"engine": name, "reason": f"health {st}: {detail}"})
            continue
        caps = eng.capabilities()
        reasons, penalty = [], 0
        if not lang_ok(caps["languages"], want_lang):
            rejected.append({"engine": name, "reason": f"no '{want_lang}' language (has {len(caps['languages'])})"})
            continue
        reasons.append(f"supports {want_lang}")
        if req.get("need_timing") and not caps["phoneme_timing"]:
            rejected.append({"engine": name, "reason": "no phoneme timing (needed for lip sync)"})
            continue
        emo = req.get("emotion", "neutral")
        if emo != "neutral":
            if caps["emotion"] == "none":
                rejected.append({"engine": name, "reason": f"no emotion control for '{emo}'"})
                continue
            if not caps["emotion"].startswith(("prosody", "model", "reference")):
                penalty += 15
                reasons.append(f"emotion only approximated ({caps['emotion']})")
            else:
                reasons.append(f"emotion via {caps['emotion']}")
        if req.get("commercial_use") and caps["commercial_use"] == "no":
            rejected.append({"engine": name, "reason": "licence forbids commercial use"})
            continue
        if req.get("commercial_use") and caps["commercial_use"].startswith("check"):
            ok_models = [m for m in studio.store.installed(name) if not any(t in (m["license"] or "").upper() for t in ("NC", "NON-COMMERCIAL", "SEE MODEL_CARD"))]
            if not ok_models:
                rejected.append({"engine": name, "reason": "no installed model with a licence that allows commercial use"})
                continue
            reasons.append("commercial-use model available")
        pres = req.get("presentation", "any")
        if pres != "any" and name == "espeak-ng" and not any(v.startswith(pres) for v in caps["voices"]):
            rejected.append({"engine": name, "reason": f"no {pres} voice"})
            continue
        if req.get("prefer") == name:
            penalty -= 100
        accepted.append({"engine": name, "score": eng.quality_rank - penalty, "reasons": reasons})
    accepted.sort(key=lambda r: -r["score"])
    return {"request": req, "ranked": accepted, "rejected": rejected, "selected": accepted[0]["engine"] if accepted else None}
