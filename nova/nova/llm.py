"""Optional LLM over any OpenAI-compatible endpoint: llama.cpp `llama-server -m model.gguf`,
Ollama, LM Studio or OmniRoute. Off unless NOVA_LLM_BASE_URL is set. Its output is untrusted
text: callers validate it (see enhance.meaning_check) before using it."""
from __future__ import annotations

import httpx

from .config import Settings

MODE_BRIEF = {
    "natural": "relaxed, human, conversational delivery",
    "professional": "polished studio narration and commercial delivery",
    "expressive": "emotionally engaging storytelling",
}


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.base = settings.llm_base_url.rstrip("/")
        self.model = settings.llm_model
        self.key = settings.llm_api_key

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMClient | None":
        return cls(settings) if settings.llm_base_url else None

    def _chat(self, system: str, user: str, max_tokens: int = 1200) -> str:
        resp = httpx.post(
            f"{self.base}/chat/completions",
            headers={"Authorization": f"Bearer {self.key}"},
            json={"model": self.model, "temperature": 0.3, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    def rewrite(self, text: str, mode: str, language: str) -> str:
        system = (
            "You edit voiceover scripts. Rewrite the script for " + MODE_BRIEF.get(mode, mode) +
            ". Keep every fact, name, number and the speaker's intended message. Do not add new claims. "
            "Keep the same language(s) as the input. Fix grammar, shorten long sentences, spell out numbers "
            "and symbols. Return only the rewritten script, no notes.")
        return self._chat(system, f"Language: {language}\n\nScript:\n{text}")

    def notes(self, text: str) -> str:
        system = "You are a voice director. In at most 5 short bullet points, say how this script should be voiced."
        try:
            return self._chat(system, text, max_tokens=300)
        except Exception as exc:  # notes are advisory; never fail the analysis because of them
            return f"LLM unavailable: {type(exc).__name__}"
