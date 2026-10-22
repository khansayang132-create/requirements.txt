"""Idea generation for the content planner.

An LLM proposes ideas; deterministic checks reject weak or unsafe ones; survivors are appended to the
plan file with "approved": false. Nothing generated here is ever approved automatically, so the
autopilot's approval rule still decides what gets produced.
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from .autopilot import AutopilotPolicy, topic_violations
from .jobs import JobQueue
from .models import ProductionSpec
from .script_engine import LLMProvider, extract_json

DEFAULT_NICHE = (
    "LSKhan 🌏💞 Cinta Beda Negara: a real Indonesian wife and Pakistani husband sharing their "
    "cross-border Islamic marriage — culture differences, family, long distance, food, language, "
    "funny moments and unexpected realities. Audience: Indonesian TikTok users."
)
ANGLES = ("emotional", "controversial", "mystery", "educational", "funny", "cultural", "family", "reality",
          "debate", "islamic")
SLOW_OPENERS = ("halo guys", "hai guys", "hello guys", "hari ini aku mau", "hari ini saya mau", "assalamualaikum guys")
SIMILAR = 0.82  # difflib ratio above which two topics count as the same idea


class Idea(BaseModel):
    topic: str = Field(min_length=8, max_length=160)
    angle: str
    hook: str = Field(min_length=8, max_length=200)
    emotion: str = "curious"
    objective: str = "entertain and connect"
    target_seconds: float = Field(30, ge=15, le=90)
    call_to_action: str = ""
    why: str = ""


def idea_prompt(niche: str, count: int, avoid: list[str], language: str = "id") -> str:
    avoid_txt = "\n".join(f"- {t}" for t in avoid[-40:]) or "- (none yet)"
    return f"""You plan short vertical videos for this channel:
{niche}

Propose {count} fresh video ideas. Rules:
- Use different angles across the batch, chosen from: {", ".join(ANGLES)}.
- The hook is the first 1-2 seconds and must create curiosity (statement, question, surprise, mystery).
  Never open with a slow greeting such as "Halo guys, hari ini aku mau cerita".
- Curiosity without lying, emotion without overacting. No fake drama, no invented serious events.
- Never make the husband look stupid or the wife look cruel. Keep Islamic and family topics respectful.
- target_seconds: 15-35 for strong viral concepts, up to 90 only when the story needs it.
- call_to_action: one natural question connected to the story, not engagement bait.
- Write topic, hook and call_to_action in {"Bahasa Indonesia" if language == "id" else "English"}.
- Do not repeat these existing ideas:
{avoid_txt}

Reply with only JSON:
{{"ideas": [{{"topic": "...", "angle": "one of the angles", "hook": "...", "emotion": "...",
  "objective": "...", "target_seconds": 30, "call_to_action": "...", "why": "one line: why people keep watching"}}]}}"""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def is_duplicate(topic: str, existing: list[str]) -> bool:
    t = _norm(topic)
    return any(difflib.SequenceMatcher(None, t, _norm(e)).ratio() >= SIMILAR for e in existing)


def review_idea(idea: Idea, policy: AutopilotPolicy, existing: list[str], angle_counts: Counter) -> list[str]:
    problems = []
    hook = idea.hook.lower()
    if any(hook.startswith(o) or o in hook[:40] for o in SLOW_OPENERS):
        problems.append("hook opens with a slow greeting")
    if idea.angle.lower() not in ANGLES:
        problems.append(f"unknown angle {idea.angle!r}")
    elif angle_counts[idea.angle.lower()] >= 2:
        problems.append(f"too many {idea.angle} ideas in this batch")
    if is_duplicate(idea.topic, existing):
        problems.append("too similar to an existing idea")
    problems += topic_violations(policy, ProductionSpec(topic=idea.topic))
    return problems


def existing_topics(plan: list[dict], queue: JobQueue | None) -> list[str]:
    topics = [e.get("spec", {}).get("topic", "") for e in plan if isinstance(e.get("spec"), dict)]
    if queue is not None:
        for r in queue.db.execute("SELECT payload FROM jobs"):
            topics.append(json.loads(r["payload"]).get("spec", {}).get("topic", ""))
    return [t for t in topics if t]


def _slug(text: str, taken: set[str]) -> str:
    base = "-".join(_norm(text).split()[:6]) or "idea"
    slug, n = f"{dt.date.today():%Y%m%d}-{base}", 2
    while slug in taken:
        slug, n = f"{dt.date.today():%Y%m%d}-{base}-{n}", n + 1
    return slug


def generate_ideas(provider: LLMProvider, plan_path: Path, policy: AutopilotPolicy, count: int = 5,
                   queue: JobQueue | None = None, niche: str = DEFAULT_NICHE, language: str = "id") -> dict:
    """Ask the provider for ideas, keep the ones that pass review, append them unapproved to the plan."""
    plan_path = Path(plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else []
    existing = existing_topics(plan, queue)
    raw = extract_json(provider.complete(idea_prompt(niche, count, existing, language)))
    added, rejected, angles = [], [], Counter()
    taken = {str(e.get("id")) for e in plan}
    for item in raw.get("ideas", [])[: count * 2]:
        try:
            idea = Idea.model_validate(item)
        except ValidationError as e:
            rejected.append({"idea": item, "reasons": [err["msg"] for err in e.errors()][:3]})
            continue
        problems = review_idea(idea, policy, existing, angles)
        if problems:
            rejected.append({"topic": idea.topic, "reasons": problems})
            continue
        if len(added) >= count:
            break
        angles[idea.angle.lower()] += 1
        existing.append(idea.topic)
        eid = _slug(idea.topic, taken)
        taken.add(eid)
        entry = {"id": eid, "approved": False, "source": f"ideas:{provider.name}", "angle": idea.angle.lower(),
                 "hook": idea.hook, "why": idea.why,
                 "spec": {"topic": idea.topic, "language": language, "emotion": idea.emotion,
                          "objective": idea.objective, "target_seconds": idea.target_seconds,
                          "call_to_action": idea.call_to_action}}
        ProductionSpec.model_validate(entry["spec"])
        plan.append(entry)
        added.append(entry)
    if added:
        tmp = plan_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(plan_path)
    return {"added": added, "rejected": rejected, "plan": str(plan_path)}
