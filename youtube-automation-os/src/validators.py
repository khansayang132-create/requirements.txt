"""Validation for metadata, schedule times, video files and thumbnails.

Limits (YouTube Data API ``videos`` resource docs):
* title: required, max 100 characters, no ``<`` or ``>``;
* description: max 5000 bytes (UTF-8), no ``<`` or ``>``;
* tags: total max 500 characters, where the API counts a comma between tags and
  wraps a tag containing a space in quotes (``"two words"`` costs 2 extra);
* thumbnails (``thumbnails.set``): JPEG/PNG here, max 2 MB, 16:9 recommended,
  1280x720 recommended, minimum width 640.

Validators never modify input. Each returns a ``ValidationResult`` listing every
error and warning so the user can fix everything in one pass.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

TITLE_MAX_CHARS = 100
DESCRIPTION_MAX_BYTES = 5000
TAGS_MAX_CHARS = 500
TAG_MAX_CHARS = 100  # practical per-tag limit; YouTube Studio rejects longer tags
HASHTAGS_MAX = 15  # YouTube ignores *all* hashtags on a video that has more than 60; we stay far below
PRIVACY_VALUES = ("private", "unlisted", "public")
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".wmv", ".flv", ".webm", ".mpeg", ".mpg", ".m4v", ".3gp", ".3gpp", ".mts"}
VIDEO_MAX_BYTES = 256 * 1024**3  # 256 GB

THUMB_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
THUMB_TARGET = (1280, 720)
THUMB_MIN_WIDTH = 640
THUMB_ASPECT = 16 / 9
THUMB_ASPECT_TOLERANCE = 0.01
THUMB_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png"}

_ANGLE = re.compile(r"[<>]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def merge(self, other: ValidationResult, prefix: str = "") -> ValidationResult:
        self.errors += [prefix + e for e in other.errors]
        self.warnings += [prefix + w for w in other.warnings]
        self.info.update(other.info)
        return self

    def as_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings, "info": self.info}


# ---------------------------------------------------------------- metadata ------
def tags_api_length(tags: list[str]) -> int:
    """Length as the API counts it: commas between tags, quotes around tags containing spaces."""
    total = 0
    for i, tag in enumerate(tags):
        total += len(tag) + (2 if " " in tag else 0)
        if i:
            total += 1
    return total


def validate_title(title: str | None) -> ValidationResult:
    r = ValidationResult()
    if title is None or not str(title).strip():
        r.errors.append("title: empty (YouTube requires a title)")
        return r
    if len(title) > TITLE_MAX_CHARS:
        r.errors.append(f"title: {len(title)} characters, max {TITLE_MAX_CHARS}")
    if _ANGLE.search(title):
        r.errors.append("title: contains '<' or '>' (not allowed by YouTube)")
    if _CONTROL.search(title):
        r.errors.append("title: contains control characters")
    if title != title.strip():
        r.warnings.append("title: leading/trailing whitespace")
    return r


def validate_description(description: str | None) -> ValidationResult:
    r = ValidationResult()
    if description is None or not description.strip():
        r.warnings.append("description: empty (allowed, but a description helps viewers)")
        return r
    size = len(description.encode("utf-8"))
    if size > DESCRIPTION_MAX_BYTES:
        r.errors.append(f"description: {size} bytes, max {DESCRIPTION_MAX_BYTES}")
    if _ANGLE.search(description):
        r.errors.append("description: contains '<' or '>' (not allowed by YouTube)")
    if _CONTROL.search(description):
        r.errors.append("description: contains control characters")
    hashtags = re.findall(r"(?<!\w)#\w+", description)
    if len(hashtags) > HASHTAGS_MAX:
        r.warnings.append(f"description: {len(hashtags)} hashtags; keep to {HASHTAGS_MAX} or fewer (YouTube ignores all of them above 60)")
    return r


def validate_tags(tags: list[str] | None) -> ValidationResult:
    r = ValidationResult()
    tags = list(tags or [])
    if not tags:
        r.warnings.append("tags: none (allowed)")
        return r
    seen: dict[str, str] = {}
    for tag in tags:
        if not isinstance(tag, str) or not tag.strip():
            r.errors.append("tags: empty tag")
            continue
        if _ANGLE.search(tag):
            r.errors.append(f"tags: '{tag}' contains '<' or '>'")
        if "," in tag:
            r.errors.append(f"tags: '{tag}' contains a comma (commas separate tags)")
        if len(tag) > TAG_MAX_CHARS:
            r.errors.append(f"tags: '{tag[:30]}…' is {len(tag)} characters, max {TAG_MAX_CHARS}")
        key = tag.strip().lower()
        if key in seen:
            r.errors.append(f"tags: duplicate keyword '{tag}' (same as '{seen[key]}')")
        else:
            seen[key] = tag
    length = tags_api_length(tags)
    r.info["tags_api_length"] = length
    if length > TAGS_MAX_CHARS:
        r.errors.append(f"tags: {length} characters as counted by the API, max {TAGS_MAX_CHARS}")
    return r


def validate_category(category_id) -> ValidationResult:
    r = ValidationResult()
    if category_id is None or not str(category_id).isdigit():
        r.errors.append(f"categoryId: '{category_id}' is not a numeric YouTube category ID")
    return r


def validate_privacy(privacy: str | None) -> ValidationResult:
    r = ValidationResult()
    if privacy not in PRIVACY_VALUES:
        r.errors.append(f"privacyStatus: '{privacy}' must be one of {', '.join(PRIVACY_VALUES)}")
    return r


def parse_publish_at(value: str) -> datetime:
    """Parse an ISO-8601 timestamp that MUST include a timezone. Returns an aware datetime."""
    text = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("publishAt must include a timezone offset, e.g. 2026-11-10T09:00:00+07:00")
    return dt


def to_rfc3339_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_schedule(publish_at: str | None, privacy: str | None, now: datetime | None = None) -> ValidationResult:
    """YouTube only honours publishAt when privacyStatus is 'private' at upload/update time."""
    r = ValidationResult()
    if not publish_at:
        return r
    try:
        dt = parse_publish_at(publish_at)
    except ValueError as exc:
        r.errors.append(f"publishAt: {exc}")
        return r
    now = now or datetime.now(timezone.utc)
    if dt <= now + timedelta(minutes=1):
        r.errors.append(f"publishAt: {to_rfc3339_utc(dt)} is not in the future")
    if privacy != "private":
        r.errors.append(
            f"publishAt requires privacyStatus 'private' (got '{privacy}'); the video becomes public at the scheduled time"
        )
    r.info["publish_at_utc"] = to_rfc3339_utc(dt)
    return r


def validate_metadata(meta: dict, now: datetime | None = None) -> ValidationResult:
    r = ValidationResult()
    r.merge(validate_title(meta.get("title")))
    r.merge(validate_description(meta.get("description")))
    r.merge(validate_tags(meta.get("tags")))
    r.merge(validate_category(meta.get("category_id")))
    r.merge(validate_privacy(meta.get("privacy")))
    r.merge(validate_schedule(meta.get("publish_at"), meta.get("privacy"), now=now))
    if not isinstance(meta.get("made_for_kids"), bool):
        r.errors.append("made_for_kids: must be set explicitly to true or false (YouTube/COPPA requirement)")
    return r


# ------------------------------------------------------------------- video ------
def validate_video_file(path: str | Path | None) -> ValidationResult:
    r = ValidationResult()
    if not path:
        r.errors.append("video: no file given")
        return r
    p = Path(path)
    if not p.exists():
        r.errors.append(f"video: file not found: {p}")
        return r
    if not p.is_file():
        r.errors.append(f"video: not a regular file: {p}")
        return r
    size = p.stat().st_size
    r.info["video_bytes"] = size
    if size == 0:
        r.errors.append("video: file is empty")
    if size > VIDEO_MAX_BYTES:
        r.errors.append(f"video: {size} bytes exceeds YouTube's 256 GB limit")
    if p.suffix.lower() not in VIDEO_EXTENSIONS:
        r.errors.append(f"video: extension '{p.suffix}' is not a YouTube-supported video format")
    if not os.access(p, os.R_OK):
        r.errors.append("video: file is not readable")
    return r


# --------------------------------------------------------------- thumbnail ------
def validate_thumbnail(path: str | Path | None, strict: bool = False) -> ValidationResult:
    """Validate a thumbnail without modifying it.

    Errors: missing/unreadable/corrupt file, format other than JPEG/PNG (by content, not
    extension), > 2 MB, width < 640. Warnings (errors with ``strict``): not 16:9, not
    exactly 1280x720, extension that disagrees with the real format.
    """
    from PIL import Image, UnidentifiedImageError

    r = ValidationResult()
    if not path:
        r.errors.append("thumbnail: no file given")
        return r
    p = Path(path)
    if not p.is_file():
        r.errors.append(f"thumbnail: file not found: {p}")
        return r
    size = p.stat().st_size
    r.info.update({"path": str(p), "bytes": size})
    if size > THUMB_MAX_BYTES:
        r.errors.append(f"thumbnail: {size / 1024 / 1024:.2f} MB exceeds the 2 MB limit ({size} > {THUMB_MAX_BYTES} bytes)")
    try:
        with Image.open(p) as img:
            fmt = img.format
            width, height = img.size
            img.verify()  # detects truncation/corruption; does not alter the file
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        r.errors.append(f"thumbnail: not a readable image ({type(exc).__name__}: {exc})")
        return r
    r.info.update({"format": fmt, "width": width, "height": height})
    if fmt not in THUMB_FORMATS:
        r.errors.append(f"thumbnail: format {fmt} not supported here; use JPEG or PNG")
    else:
        r.info["mimetype"] = THUMB_FORMATS[fmt]
        ext = p.suffix.lower()
        expected = {"JPEG": {".jpg", ".jpeg"}, "PNG": {".png"}}[fmt]
        if ext not in expected:
            r.warnings.append(f"thumbnail: extension '{ext}' does not match real format {fmt}")
    soft: list[str] = []
    if width < THUMB_MIN_WIDTH:
        r.errors.append(f"thumbnail: width {width}px is below YouTube's minimum of {THUMB_MIN_WIDTH}px")
    ratio = width / height if height else 0
    r.info["aspect_ratio"] = round(ratio, 4)
    if abs(ratio - THUMB_ASPECT) / THUMB_ASPECT > THUMB_ASPECT_TOLERANCE:
        soft.append(f"thumbnail: aspect ratio {width}:{height} ({ratio:.3f}) is not 16:9 (1.778); YouTube will letterbox it")
    if (width, height) != THUMB_TARGET:
        soft.append(f"thumbnail: {width}x{height}; recommended size is {THUMB_TARGET[0]}x{THUMB_TARGET[1]}")
    (r.errors if strict else r.warnings).extend(soft)
    return r
