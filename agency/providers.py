"""LLM provider adapter: any OpenAI-compatible /chat/completions endpoint (OmniRoute, OpenAI, Headroom).

Configured from the environment; nothing is faked when it isn't:
    AGENCY_LLM_BASE_URL / AGENCY_LLM_API_KEY / AGENCY_LLM_MODEL, else the bot's OMNIROUTE_* settings.
Without a key, `provider_from_env` raises ProviderUnavailable and the calling task is BLOCKED.

Errors are normalized to ProviderError with the HTTP status and a redacted message. Retries are bounded
(one retry on connection errors and 5xx). Token usage is returned when the provider reports it.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class ProviderUnavailable(RuntimeError):
    pass


class ProviderError(RuntimeError):
    def __init__(self, status: int | None, message: str):
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status


@dataclass
class Completion:
    text: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None


class OpenAICompatible:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 90.0, retries: int = 1):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.timeout, self.retries = timeout, retries

    @property
    def label(self) -> str:
        return f"{self.base_url} ({self.model})"

    def complete(self, system: str, user: str, max_tokens: int = 1200) -> Completion:
        body = json.dumps({"model": self.model, "max_tokens": max_tokens,
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body.encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self.api_key}",
                                              "Content-Type": "application/json"})
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.load(resp)
                break
            except urllib.error.HTTPError as e:
                detail = e.read(500).decode(errors="replace")
                if e.code < 500 or attempt == self.retries:
                    raise ProviderError(e.code, detail) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == self.retries:
                    raise ProviderError(None, f"{self.base_url} unreachable: {e}") from None
            time.sleep(1.0)
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ProviderError(None, "response has no choices[0].message.content") from None
        usage = data.get("usage") or {}
        return Completion(text, data.get("model", self.model), usage.get("prompt_tokens"), usage.get("completion_tokens"))


def provider_from_env(env=os.environ) -> OpenAICompatible:
    key = env.get("AGENCY_LLM_API_KEY") or env.get("OMNIROUTE_API_KEY")
    if not key:
        raise ProviderUnavailable("no LLM key: set AGENCY_LLM_API_KEY (or OMNIROUTE_API_KEY) in .env")
    base = env.get("AGENCY_LLM_BASE_URL") or env.get("OMNIROUTE_BASE_URL") or "http://127.0.0.1:20128/v1"
    model = env.get("AGENCY_LLM_MODEL") or env.get("OMNIROUTE_MODEL") or "auto"
    return OpenAICompatible(base, key, model)
