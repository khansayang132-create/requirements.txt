"""Vision-model creative review of the frames QA sampled (one per scene).

    python -m apex.cli review --project out/my-video

A vision model scores each frame against what that scene is meant to show. The model only gives
scores and notes: the verdict is computed here (overall >= 7 and no frame below 5 passes), so a
model that answers "looks great" without scoring can't pass a video. The review is advisory. It is
written into qa/qa_report.json and manifest.json and never changes the technical QA result.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
from pathlib import Path

from pydantic import BaseModel, Field

from .script_engine import ProviderUnavailable, _post_json, extract_json

PASS_OVERALL = 7.0
PASS_FRAME = 5.0


class FrameReview(BaseModel):
    index: int
    score: float = Field(ge=0, le=10)
    matches_scene: bool
    text_readable: bool = True
    issues: list[str] = Field(default_factory=list)


class VisionReply(BaseModel):
    frames: list[FrameReview]
    summary: str = ""


class VisionReviewer:
    """OpenAI-compatible chat endpoint that accepts image_url parts. Tries base URLs in order."""

    def __init__(self, base_urls: list[str], api_key: str, model: str):
        if not api_key:
            raise ProviderUnavailable("no API key for the vision reviewer")
        self.base_urls, self.api_key, self.model = [u.rstrip("/") for u in base_urls], api_key, model
        self.name = f"vision:{model}@{self.base_urls[0]}"

    def complete(self, content: list[dict]) -> str:
        payload = {"model": self.model, "messages": [{"role": "user", "content": content}]}
        for i, base in enumerate(self.base_urls):
            try:
                data = _post_json(f"{base}/chat/completions", payload, {"authorization": f"Bearer {self.api_key}"})
                return data["choices"][0]["message"]["content"] or ""
            except urllib.error.HTTPError:
                raise
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                if i == len(self.base_urls) - 1:
                    raise


def reviewer_from_env() -> VisionReviewer:
    model = os.getenv("APEX_VISION_MODEL", "")
    if os.getenv("OMNIROUTE_API_KEY"):
        key, direct = os.environ["OMNIROUTE_API_KEY"], os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
        model = model or os.getenv("OMNIROUTE_MODEL", "auto")
    elif os.getenv("OPENAI_API_KEY"):
        key, direct, model = os.environ["OPENAI_API_KEY"], "https://api.openai.com/v1", model or "gpt-4.1-mini"
    else:
        raise ProviderUnavailable("no vision reviewer configured (set OMNIROUTE_API_KEY or OPENAI_API_KEY)")
    urls = [u for u in (os.getenv("HEADROOM_BASE_URL", ""), direct) if u]
    return VisionReviewer(urls, key, model)


def _resolve(frame: str, project: Path) -> Path:
    p = Path(frame)
    if p.is_file():
        return p
    alt = project / "qa" / "frames" / p.name  # paths are recorded relative to where the pipeline ran
    if alt.is_file():
        return alt
    raise FileNotFoundError(frame)


def review_prompt(scenes: list[dict], language: str) -> str:
    lines = [f"Frame {i}: scene {s['scene_id']} ({s.get('narrative_purpose', '')}). Narration: "
             f"{s.get('narration_text', '')!r}. On-screen text: {s.get('on_screen_text', '')!r}. "
             f"3D template: {s.get('template', '')}." for i, s in enumerate(scenes)]
    return ("You review frames from a short vertical video (9:16) before publishing. Each frame is the middle "
            "of one scene. For every frame, judge whether the picture supports what the scene says, whether any "
            "on-screen text is readable on a phone and kept clear of the bottom caption area, and whether it looks "
            "clean and intentional. Be strict; do not praise. Score 0-10.\n"
            f"Language of the video: {language}.\n" + "\n".join(lines) +
            '\nReply with only JSON: {"frames": [{"index": 0, "score": 0-10, "matches_scene": true, '
            '"text_readable": true, "issues": ["..."]}], "summary": "one or two sentences"}')


def verdict(reply: VisionReply, expected: int) -> dict:
    scores = {f.index: f.score for f in reply.frames}
    missing = sorted(set(range(expected)) - set(scores))
    overall = round(sum(scores.values()) / len(scores), 2) if scores else 0.0
    weak = sorted(i for i, s in scores.items() if s < PASS_FRAME)
    mismatched = sorted(f.index for f in reply.frames if not f.matches_scene)
    passed = not missing and overall >= PASS_OVERALL and not weak and not mismatched
    reasons = ([f"no review for frames {missing}"] if missing else []) + \
              ([f"overall {overall} < {PASS_OVERALL}"] if overall < PASS_OVERALL else []) + \
              ([f"frames below {PASS_FRAME}: {weak}"] if weak else []) + \
              ([f"frames not matching their scene: {mismatched}"] if mismatched else [])
    return {"status": "PASS" if passed else "NEEDS_WORK", "overall_score": overall, "reasons": reasons}


def review_project(project: Path, reviewer: VisionReviewer | None = None) -> dict:
    project = Path(project)
    qa_path = project / "qa" / "qa_report.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    board = json.loads((project / "storyboard.json").read_text(encoding="utf-8"))
    manifest_path = project / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    language = (manifest or {}).get("spec", {}).get("language", "id")
    frames = [_resolve(f, project) for f in qa.get("sampled_frames", [])]
    scenes = board["scenes"][: len(frames)]
    if not frames:
        raise ValueError("QA saved no sampled frames to review")
    reviewer = reviewer or reviewer_from_env()
    content = [{"type": "text", "text": review_prompt(scenes, language)}]
    for f in frames:
        content.append({"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode()}})
    reply = VisionReply.model_validate(extract_json(reviewer.complete(content)))
    review = {**verdict(reply, len(frames)), "reviewer": reviewer.name, "summary": reply.summary,
              "frames": [{**fr.model_dump(), "scene_id": scenes[fr.index]["scene_id"]}
                         for fr in reply.frames if 0 <= fr.index < len(scenes)]}
    qa["creative_review"] = review
    qa_path.write_text(json.dumps(qa, indent=2, ensure_ascii=False), encoding="utf-8")
    if manifest is not None:
        manifest.setdefault("qa", {})["creative_review"] = review
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return review
