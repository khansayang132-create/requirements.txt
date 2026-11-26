"""Optional LLM over any OpenAI-compatible endpoint: llama.cpp `llama-server -m model.gguf`,
Ollama, LM Studio or OmniRoute. Off unless NOVA_LLM_BASE_URL is set. Its output is untrusted
text: callers validate it (see enhance.meaning_check) before using it."""
from __future__ import annotations

import re

import httpx

from .config import Settings

MODE_BRIEF = {
    "natural": "relaxed, human, conversational delivery",
    "professional": "polished studio narration and commercial delivery",
    "expressive": "emotionally engaging storytelling",
}


class LLMEmpty(RuntimeError):
    pass


def _base_url(url: str) -> str:
    """Accept the base address, .../v1 or the full .../v1/chat/completions URL."""
    url = url.rstrip("/")
    url = re.sub(r"/chat/completions$", "", url)
    return url if url.endswith("/v1") else url + "/v1"


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.base = _base_url(settings.llm_base_url)
        self.thinking = settings.llm_thinking
        self.model = settings.llm_model
        self.key = settings.llm_api_key

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMClient | None":
        return cls(settings) if settings.llm_base_url else None

    def _chat(self, system: str, user: str, max_tokens: int = 1200) -> str:
        body = {"model": self.model, "temperature": 0.3, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if not self.thinking:
            # Thinking models (Gemma 4, Qwen 3) otherwise spend the whole token budget on hidden
            # reasoning and return no answer. llama.cpp, vLLM and LM Studio read this field.
            body["chat_template_kwargs"] = {"enable_thinking": False}
        headers = {"Authorization": f"Bearer {self.key}"}
        resp = httpx.post(f"{self.base}/chat/completions", headers=headers, json=body, timeout=180)
        if resp.status_code == 400 and "chat_template_kwargs" in body:
            body.pop("chat_template_kwargs")  # servers that reject unknown fields (e.g. OpenAI)
            resp = httpx.post(f"{self.base}/chat/completions", headers=headers, json=body, timeout=180)
        resp.raise_for_status()
        content = (resp.json()["choices"][0]["message"].get("content") or "")
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        if not content:
            raise LLMEmpty("the model returned no answer (only hidden reasoning, or it ran out of tokens)")
        return content

    def rewrite(self, text: str, mode: str, language: str) -> str:
        system = (
            "You edit voiceover scripts. Rewrite the script for " + MODE_BRIEF.get(mode, mode) +
            ". Keep every fact, name, number and the speaker's intended message. Do not add new claims. "
            "Keep the same language(s) as the input. Fix grammar, shorten long sentences, spell out numbers "
            "and symbols. Return only the rewritten script, no notes.")
        return self._chat(system, f"Language: {language}\n\nScript:\n{text}")

    def notes(self, text: str, language: str = "") -> str:
        lang = {"id": "Bahasa Indonesia", "en": "English"}.get(language, "the same language as the script")
        system = ("You are a voice director. In at most 5 short bullet points, say how this script should be voiced. "
                  f"Write the notes in {lang}.")
        try:
            return self._chat(system, text, max_tokens=300)
        except Exception as exc:  # notes are advisory; never fail the analysis because of them
            return f"LLM unavailable: {type(exc).__name__}"
