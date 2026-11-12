"""Remove secrets from anything that is logged or written to a report."""

import os
import re

from ..config import PROVIDER_ENV

_PATTERNS = [re.compile(r"(?i)(x-api-key|authorization|api[_-]?key|secret)(['\"]?\s*[:=]\s*['\"]?)([^\s'\",}]+)"),
             re.compile(r"\bsk_[A-Za-z0-9]{16,}\b"), re.compile(r"\bBasic [A-Za-z0-9+/=]{12,}")]


def redact(text: str) -> str:
    out = str(text)
    for env in PROVIDER_ENV.values():
        v = os.environ.get(env)
        if v and len(v) >= 6:
            out = out.replace(v, "***")
    out = _PATTERNS[0].sub(lambda m: m.group(1) + m.group(2) + "***", out)
    for p in _PATTERNS[1:]:
        out = p.sub("***", out)
    return out
