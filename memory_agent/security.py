
"""Validation and safety checks applied to every record before it reaches the store.

Secrets are rejected, not redacted: a memory that needed a key to be useful should say where the key lives
(".env: OMNIROUTE_API_KEY"), never hold it. Errors name the kind of secret found, never its value.
"""
import re

KINDS = ("preference", "project", "architecture", "task", "bug", "decision", "session", "status")
SCOPES = ("global", "project")
CONFIDENCE = ("confirmed", "assumption")
TASK_STATES = ("pending", "in_progress", "blocked", "done")

MAX_TITLE = 200
MAX_CONTENT = 8000
MAX_TAGS = 20

PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,99}$")
BACKUP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")

SECRET_PATTERNS = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Anthropic/OpenAI key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Telegram bot token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("bearer token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}")),
    ("credential assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*['\"]?(?![$<{])[^\s'\"]{8,}")),
]

INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore (?:all |any )?(?:previous|prior|above) (?:instructions|rules)"),
    re.compile(r"(?i)disregard (?:the |your )?(?:system|previous) (?:prompt|instructions)"),
    re.compile(r"(?i)\byou are now\b"),
    re.compile(r"(?i)\b(?:run|execute) (?:this|the following) (?:command|script)"),
    re.compile(r"(?i)curl [^|]*\|\s*(?:ba)?sh"),
]

PRIVATE_TAG = re.compile(r"<private>.*?</private>", re.DOTALL | re.IGNORECASE)


class ValidationError(ValueError):
    """Bad input. The message is safe to show: it never echoes a secret."""


def find_secret(text: str) -> str | None:
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text or ""):
            return name
    return None


def reject_secrets(*texts: str) -> None:
    for text in texts:
        found = find_secret(text)
        if found:
            raise ValidationError(
                f"refused: the text looks like it contains a secret ({found}). Store where the secret lives "
                "(for example '.env: OMNIROUTE_API_KEY'), never the value.")


def redact(text: str) -> str:
    """For logs and error output only."""
    for _, pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def strip_private(text: str) -> str:
    return PRIVATE_TAG.sub("[private content removed]", text or "")


def looks_like_injection(text: str) -> bool:
    return any(p.search(text or "") for p in INJECTION_PATTERNS)


def check_choice(name: str, value, choices) -> str:
    if value not in choices:
        raise ValidationError(f"{name} must be one of {', '.join(choices)}; got {value!r}")
    return value


def check_text(name: str, value, limit: int, required: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a string")
    value = value.strip()
    if required and not value:
        raise ValidationError(f"{name} is required")
    if len(value) > limit:
        raise ValidationError(f"{name} is {len(value)} characters; the limit is {limit}")
    if "\x00" in value:
        raise ValidationError(f"{name} contains a NUL byte")
    return value


def check_project(value) -> str:
    if not isinstance(value, str) or not PROJECT_RE.match(value) or ".." in value:
        raise ValidationError("project must be 1-100 characters of letters, digits, '.', '_', '-', '/' (no '..')")
    return value


def check_tags(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [t for t in value.split(",")]
    if not isinstance(value, list):
        raise ValidationError("tags must be a list of strings")
    tags = sorted({t.strip().lower() for t in value if isinstance(t, str) and t.strip()})
    if len(tags) > MAX_TAGS:
        raise ValidationError(f"at most {MAX_TAGS} tags")
    for t in tags:
        if not TAG_RE.match(t):
            raise ValidationError(f"tag {t!r} must be lowercase letters, digits, '-' or '_' (max 40)")
    return tags


def check_key(value) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not KEY_RE.match(value):
        raise ValidationError("key must be lowercase letters, digits and . _ : - (max 100), e.g. 'bot.ai-route'")
    return value


def check_int(name: str, value, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValidationError(f"{name} must be an integer from {lo} to {hi}")
    return value


def check_backup_name(value: str) -> str:
    if not isinstance(value, str) or not BACKUP_NAME_RE.match(value):
        raise ValidationError("backup name must be letters, digits, '.', '_', '-' (no paths)")
    return value
