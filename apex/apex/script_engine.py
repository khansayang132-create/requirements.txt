"""Scriptwriting: LLM providers, deterministic review, bounded revision, and script locking."""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from .models import SCENE_TEMPLATES, CAMERA_MOVES, ProductionSpec, Script
from .timing import estimate_seconds
from .tts import normalize_for_speech


class ProviderUnavailable(RuntimeError):
    """The provider cannot be used (no credentials, unreachable). Not retryable without setup."""


class LLMProvider(Protocol):
    name: str

    def complete(self, prompt: str) -> str: ...


def _post_json(url: str, payload: dict, headers: dict, timeout: float = 180) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    # The provider URL comes from the owner's own .env.
    with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310
        return json.loads(r.read().decode())


class OpenAICompatibleProvider:
    """Any /v1/chat/completions endpoint: OmniRoute, OpenAI, and similar gateways."""

    def __init__(self, base_url: str, api_key: str, model: str):
        if not api_key:
            raise ProviderUnavailable("no API key for OpenAI-compatible provider")
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.name = f"openai-compatible:{model}@{self.base_url}"

    def complete(self, prompt: str) -> str:
        data = _post_json(f"{self.base_url}/chat/completions",
                          {"model": self.model, "messages": [{"role": "user", "content": prompt}]},
                          {"authorization": f"Bearer {self.api_key}"})
        return data["choices"][0]["message"]["content"] or ""


class AnthropicProvider:
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.anthropic.com"):
        if not api_key:
            raise ProviderUnavailable("ANTHROPIC_API_KEY is not set")
        self.api_key, self.model, self.base_url = api_key, model, base_url.rstrip("/")
        self.name = f"anthropic:{model}"

    def complete(self, prompt: str) -> str:
        data = _post_json(f"{self.base_url}/v1/messages",
                          {"model": self.model, "max_tokens": 4000,
                           "messages": [{"role": "user", "content": prompt}]},
                          {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"})
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


class FallbackProvider:
    """Try providers in order; move on only when one can't be reached (e.g. a stopped Headroom proxy)."""

    def __init__(self, providers: list):
        self.providers = providers
        self.name = " -> ".join(p.name for p in providers)

    def complete(self, prompt: str) -> str:
        for i, p in enumerate(self.providers):
            try:
                return p.complete(prompt)
            except urllib.error.HTTPError:
                raise  # the endpoint answered; a 4xx/5xx is a real error, not a reason to switch
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                if i == len(self.providers) - 1:
                    raise
        raise ProviderUnavailable("no providers")


def _openai_compatible(base_url: str, api_key: str, model: str) -> LLMProvider:
    """Route through Headroom first when HEADROOM_BASE_URL is set, falling back to the direct URL."""
    direct = OpenAICompatibleProvider(base_url, api_key, model)
    headroom = os.getenv("HEADROOM_BASE_URL", "")
    if not headroom:
        return direct
    via = OpenAICompatibleProvider(headroom, api_key, model)
    via.name = f"headroom:{model}@{via.base_url}"
    return FallbackProvider([via, direct])


def provider_from_env() -> LLMProvider:
    """Pick a provider from environment variables; raise ProviderUnavailable if none is configured."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return AnthropicProvider(os.environ["ANTHROPIC_API_KEY"], os.getenv("APEX_ANTHROPIC_MODEL", "claude-sonnet-5-5"))
    if os.getenv("OMNIROUTE_API_KEY"):
        return _openai_compatible(os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1"),
                                  os.environ["OMNIROUTE_API_KEY"], os.getenv("OMNIROUTE_MODEL", "auto"))
    if os.getenv("OPENAI_API_KEY"):
        return _openai_compatible("https://api.openai.com/v1", os.environ["OPENAI_API_KEY"],
                                  os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    raise ProviderUnavailable("no LLM provider configured (set ANTHROPIC_API_KEY, OMNIROUTE_API_KEY or OPENAI_API_KEY)")


def extract_json(text: str) -> dict:
    """Parse a JSON object from a model reply (bare, fenced, or with a sentence around it)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(candidate)


def script_prompt(spec: ProductionSpec, feedback: list[str] | None = None, previous: Script | None = None) -> str:
    lang = {"id": "Bahasa Indonesia", "en": "English"}[spec.language]
    words = int(spec.target_seconds * {"id": 2.3, "en": 2.6}[spec.language] * 0.85)
    parts = [
        "You are a senior short-form video scriptwriter.",
        f"Write a {spec.target_seconds:.0f}-second {spec.aspect_ratio} {spec.platform} video in {lang}.",
        f"Topic: {spec.topic}\nAudience: {spec.audience}\nObjective: {spec.objective}\nEmotion: {spec.emotion}",
        f"Call to action: {spec.call_to_action or 'a natural closing question'}",
        f"Total narration about {words} words. First 1-3 seconds: a hook tied to the real content, no greeting, no misleading clickbait.",
        "Never invent statistics, quotes or sources. Arithmetic examples are fine if clearly illustrative.",
        f"Each scene's visual must use one template from: {', '.join(SCENE_TEMPLATES)}; camera_move from: {', '.join(CAMERA_MOVES)}.",
        "Template params: coin_stack {\"stacks\": [heights 1-12]}, bar_chart {\"values\": [1-12 numbers]}, "
        "hero_coin {}, coffee_cup {}, piggy_bank {\"coins\": 0-20}.",
        'Reply with only JSON: {"title","concept","hook","caption","hashtags":[4-7],"thumbnail_concept",'
        '"scenes":[{"scene_id":"s01","purpose","narration","on_screen_text","template","camera_move","params":{},"music_cue"}]}',
    ]
    if previous and feedback:
        parts += ["Revise this script to fix the problems below. Keep what works.",
                  "Problems:\n- " + "\n- ".join(feedback),
                  "Previous script:\n" + previous.model_dump_json(exclude={"provenance"})]
    return "\n\n".join(parts)


GREETING = re.compile(r"^\s*(halo|hai|hi|hello|hey|selamat (pagi|siang|sore|malam))\b", re.I)


def review_script(script: Script, spec: ProductionSpec) -> list[str]:
    """Deterministic checks. Returns a list of problems; empty means it passed."""
    problems = []
    # Estimate from the spoken form: "Rp25.000" is read as five words, not one.
    spoken = [normalize_for_speech(s.narration, spec.language) for s in script.scenes]
    total = sum(estimate_seconds(t, spec.language) + 0.45 for t in spoken)
    if abs(total - spec.target_seconds) > spec.tolerance_seconds + 2:
        problems.append(f"estimated narration {total:.1f}s is far from the {spec.target_seconds:.0f}s target")
    if GREETING.search(script.scenes[0].narration):
        problems.append("opening line starts with a greeting instead of a hook")
    if estimate_seconds(spoken[0], spec.language) > 4.5:
        problems.append("hook line is too long to land in the first 3 seconds")
    for s, text in zip(script.scenes, spoken):
        if estimate_seconds(text, spec.language) > 9:
            problems.append(f"{s.scene_id} narration is too long for one shot; split it")
        if len(s.on_screen_text) > 40:
            problems.append(f"{s.scene_id} on-screen text over 40 characters is hard to read on a phone")
    if script.hashtags and not 4 <= len(script.hashtags) <= 7:
        problems.append("use 4-7 hashtags")
    if re.search(r"\b\d{1,3}(\.\d+)?\s?%", " ".join(s.narration for s in script.scenes)):
        problems.append("contains a percentage statistic; remove it unless a source is recorded")
    return problems


def write_script(spec: ProductionSpec, provider: LLMProvider, max_revisions: int = 2) -> tuple[Script, list[dict]]:
    """Generate, review, and revise up to max_revisions times. Returns the script and the review log."""
    log, script, feedback = [], None, None
    for attempt in range(max_revisions + 1):
        raw = provider.complete(script_prompt(spec, feedback, script))
        data = extract_json(raw)
        data["provenance"] = f"generated by {provider.name}, attempt {attempt + 1}"
        script = Script.model_validate(data)
        feedback = review_script(script, spec)
        log.append({"attempt": attempt + 1, "version": script.version_hash, "problems": feedback})
        if not feedback:
            break
    return script, log


def lock_script(script: Script, project_dir: Path) -> dict:
    """Save an approved version. If a different version was locked before, report which scenes changed."""
    d = project_dir / "scripts"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"script_{script.version_hash}.json"
    path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    pointer = d / "approved.json"
    changed: list[str] = []
    previous = None
    if pointer.exists():
        previous = json.loads(pointer.read_text())["version"]
        if previous != script.version_hash:
            old = Script.model_validate_json((d / f"script_{previous}.json").read_text())
            old_by_id = {s.scene_id: _scene_hash(s) for s in old.scenes}
            changed = [s.scene_id for s in script.scenes if old_by_id.get(s.scene_id) != _scene_hash(s)]
    pointer.write_text(json.dumps({"version": script.version_hash, "previous": previous,
                                   "scenes_needing_regeneration": changed}, indent=2))
    return {"version": script.version_hash, "path": str(path), "previous": previous,
            "scenes_needing_regeneration": changed}


def _scene_hash(scene) -> str:
    return hashlib.sha256(scene.model_dump_json().encode()).hexdigest()[:12]
