"""Bridge from the LSKhan Studio autopilot to NOVA.

The "LSKhan daily video plan" scheduled task writes one plan a day into the LSKhan Studio app
(plans/auto-YYYY-MM-DD). NOVA reads that plan, either the JSON document or the text the Studio's
"Salin naskah" (Copy script) button produces:

    0-2s  Kebaya Indonesia vs shalwar kameez Pakistan… aku coba dua-duanya.
       [TEXT] KEBAYA 🇮🇩 vs SHALWAR KAMEEZ 🇵🇰
    2-5s  Aku nilai tiga hal: …

Spoken lines keep the autopilot's [placeholders] for real personal facts (the autopilot is told
never to invent them). NOVA never voices a placeholder and never fills one itself: every
placeholder must be answered by the creator before a voiceover is made."""
from __future__ import annotations

import json
import re

PLACEHOLDER = re.compile(r"\[([^\[\]]{2,400})\]")
SCENE_LINE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*s\b\s*(.*)$", re.I)
TEXT_LINE = re.compile(r"^\s*\[TEXT\]\s*(.*)$", re.I)
EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF️‍]+")

# Studio content types -> NOVA director emotion for the scene body.
TYPE_EMOTION = {
    "lucu": "happiness", "budaya": "happiness", "keluarga": "happiness", "seri": "neutral",
    "edukasi": "professional", "emosional": "sadness", "misteri": "documentary", "realita": "neutral",
    "debat": "confidence", "islami": "documentary",
}
UPBEAT = {"happiness", "confidence"}


class PlanError(ValueError):
    pass


def _slot(t: str) -> tuple[float | None, float | None]:
    m = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*s?\s*$", t or "")
    if not m:
        return None, None
    a, b = (float(x.replace(",", ".")) for x in m.groups())
    return a, b


def _from_text(text: str) -> dict:
    scenes: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = TEXT_LINE.match(line)
        if m and scenes:
            scenes[-1]["text"] = m.group(1).strip()
            continue
        m = SCENE_LINE.match(line)
        if m:
            scenes.append({"t": f"{m.group(1)}-{m.group(2)}s", "say": m.group(3).strip(), "text": ""})
        elif scenes:  # a wrapped spoken line
            scenes[-1]["say"] = (scenes[-1]["say"] + " " + line.strip()).strip()
    if not scenes:
        raise PlanError("no scenes found: paste the text from \"Salin naskah\" or the plan's JSON")
    return {"title": "", "type": "", "lang": "", "scenes": scenes, "needs": []}


def _from_json(obj: dict) -> dict:
    doc = obj.get("data", obj) if isinstance(obj.get("data"), dict) else obj
    plan = doc.get("plan", doc)
    if not isinstance(plan, dict) or not isinstance(plan.get("scenes"), list):
        raise PlanError("this JSON has no plan.scenes list")
    scenes = [{"t": str(s.get("t", "")), "say": str(s.get("say", "")).strip(), "text": str(s.get("text", ""))}
              for s in plan["scenes"] if isinstance(s, dict)]
    return {"title": str(plan.get("title", "")), "type": str(plan.get("type", "")),
            "lang": str(doc.get("lang", "")), "scenes": scenes,
            "needs": [str(n) for n in plan.get("needs", []) if isinstance(n, str)]}


def clean_say(say: str, lang: str = "") -> str:
    s = say.replace("→", ",").replace("->", ",")
    if lang == "both":  # "Indonesian line (English translation)": voice the Indonesian part only
        s = re.sub(r"\s*\((?=[^()]*[A-Za-z])[^()]{3,}\)", "", s)
    s = EMOJI.sub("", s)
    s = re.sub(r"\s*,\s*,+", ",", s)
    s = re.sub(r"\s+([,.!?…])", r"\1", s)
    return re.sub(r"\s{2,}", " ", s).strip(" ,")


def parse(source) -> dict:
    """source: plan JSON (dict or JSON text) or the Studio's "Salin naskah" text."""
    if isinstance(source, dict):
        plan = _from_json(source)
    else:
        text = str(source or "").strip()
        if not text:
            raise PlanError("nothing to read: paste the script or the plan JSON")
        if text.startswith("{"):
            try:
                plan = _from_json(json.loads(text))
            except json.JSONDecodeError as exc:
                raise PlanError(f"the JSON is not valid: {exc.msg}") from exc
        else:
            plan = _from_text(text)
    out = []
    for i, s in enumerate(plan["scenes"]):
        start, end = _slot(s["t"])
        holes = [{"id": f"s{i}p{k}", "hint": m.group(1).strip()} for k, m in enumerate(PLACEHOLDER.finditer(s["say"]))]
        out.append({"index": i, "t": s["t"], "slot_s": round(end - start, 2) if start is not None else None,
                    "say": s["say"], "text": s["text"], "placeholders": holes})
    if not any(s["say"] for s in out):
        raise PlanError("the plan has no spoken lines")
    plan["scenes"] = out
    plan["placeholder_count"] = sum(len(s["placeholders"]) for s in out)
    plan["emotion"] = TYPE_EMOTION.get(plan["type"].strip().lower(), "neutral")
    return plan


def fill(plan: dict, answers: dict[str, str]) -> list[dict]:
    """Replace every placeholder with the creator's own answer. Missing answers are an error:
    NOVA never voices a placeholder and never makes one up."""
    missing, filled = [], []
    for s in plan["scenes"]:
        say, k = s["say"], 0

        def sub(m: re.Match) -> str:
            nonlocal k
            pid = f"s{s['index']}p{k}"
            k += 1
            ans = (answers.get(pid) or "").strip()
            if not ans or "[" in ans or "]" in ans:
                missing.append({"id": pid, "scene": s["t"], "hint": m.group(1).strip()})
                return m.group(0)
            return ans
        filled.append({**s, "say": PLACEHOLDER.sub(sub, say)})
    if missing:
        raise PlanError(f"{len(missing)} real detail(s) still need your answer", missing)
    return filled


def segments(plan: dict, filled: list[dict]) -> list[dict]:
    base = plan.get("emotion", "neutral")
    segs = []
    for s in filled:
        text = clean_say(s["say"], plan.get("lang", ""))
        if not text:
            continue
        emotion = base
        if s["index"] == 0 and base in UPBEAT:
            emotion = "excitement"  # the hook carries the most energy in upbeat plans
        if text[-1:] not in ".!?…":
            text += "."
        segs.append({"label": s["t"] or f"Scene {s['index'] + 1}", "text": text, "emotion": emotion,
                     "slot_s": s.get("slot_s")})
    if not segs:
        raise PlanError("nothing left to voice after cleaning the lines")
    return segs


def timing_report(manifest: dict, segs: list[dict]) -> list[dict]:
    """Speech per scene vs the plan's time slot (pauses between scenes not counted)."""
    spoken: dict[int, float] = {}
    for r in manifest.get("sentences", []):
        if r.get("scene") is not None:
            spoken[r["scene"]] = spoken.get(r["scene"], 0.0) + r.get("duration_s", 0.0)
    rows = []
    for i, seg in enumerate(segs):
        got, slot = round(spoken.get(i, 0.0), 2), seg.get("slot_s")
        status = "no slot" if not slot else "over" if got > slot * 1.15 else "ok"
        rows.append({"scene": seg["label"], "slot_s": slot, "speech_s": got, "status": status})
    return rows
