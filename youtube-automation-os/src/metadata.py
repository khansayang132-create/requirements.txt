"""Template-based metadata generation: title, description, tags, hashtags, CTA, category.

Deterministic: the same topic file + templates always give the same output, so it is
testable and reviewable. Templates live in ``config/settings.yaml`` → ``metadata``.
Claude (or a person) writes the creative inputs — hook, summary, points, keywords —
in a topic file; this module assembles them within YouTube's limits.

No claim is made that this improves ranking: SEO results are not guaranteed.
"""

from __future__ import annotations

import re
from typing import Any

from .validators import (
    DESCRIPTION_MAX_BYTES,
    TAGS_MAX_CHARS,
    TITLE_MAX_CHARS,
    ValidationResult,
    tags_api_length,
    validate_category,
    validate_description,
    validate_tags,
    validate_title,
)

DISCLAIMER = "Generated from templates. Search/SEO performance is not guaranteed."

CATEGORY_NAMES = {
    "1": "Film & Animation", "2": "Autos & Vehicles", "10": "Music", "15": "Pets & Animals",
    "17": "Sports", "19": "Travel & Events", "20": "Gaming", "22": "People & Blogs",
    "23": "Comedy", "24": "Entertainment", "25": "News & Politics", "26": "Howto & Style",
    "27": "Education", "28": "Science & Technology", "29": "Nonprofits & Activism",
}


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def sanitize(text: str) -> str:
    """Remove characters YouTube rejects (< >) and control characters; collapse inner spaces."""
    text = re.sub(r"[<>]", "", text or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", sanitize(text)).strip()


def truncate_words(text: str, limit: int, ellipsis: str = "…") -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - len(ellipsis)]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:-–—") + ellipsis


def dedupe(items: list[str]) -> tuple[list[str], list[str]]:
    seen: set[str] = set()
    out, dropped = [], []
    for item in items:
        key = item.strip().lower()
        if not key:
            continue
        if key in seen:
            dropped.append(item)
            continue
        seen.add(key)
        out.append(item.strip())
    return out, dropped


def to_hashtag(text: str) -> str:
    words = re.findall(r"[\w]+", sanitize(text), flags=re.UNICODE)
    if not words:
        return ""
    if len(words) == 1:
        tag = words[0]
    else:
        tag = "".join(w[:1].upper() + w[1:] for w in words)
    return "#" + tag


def fit_tags(tags: list[str], max_count: int, max_chars: int = TAGS_MAX_CHARS) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    dropped: list[str] = []
    for tag in tags:
        tag = _one_line(tag).replace(",", " ").strip()
        if not tag:
            continue
        if len(kept) >= max_count or tags_api_length(kept + [tag]) > max_chars:
            dropped.append(tag)
            continue
        kept.append(tag)
    return kept, dropped


def suggest_category(topic: dict, rules: dict) -> list[dict]:
    """Score categories by keyword hits in topic text. Returns best-first suggestions with reasons."""
    haystack = " ".join(
        str(x) for x in [topic.get("topic", ""), topic.get("hook", ""), topic.get("summary", ""), " ".join(topic.get("keywords", []) or []), " ".join(topic.get("points", []) or [])]
    ).lower()
    scores = []
    for cat_id, words in (rules or {}).items():
        hits = [w for w in words if re.search(r"(?<!\w)" + re.escape(w.lower()) + r"(?!\w)", haystack)]
        if hits:
            scores.append({"category_id": str(cat_id), "name": CATEGORY_NAMES.get(str(cat_id), "?"), "score": len(hits), "matched": hits})
    scores.sort(key=lambda s: (-s["score"], s["category_id"]))
    return scores


def generate(topic: dict, templates: dict, *, default_category: str = "22") -> dict:
    """Build metadata from a topic dict. Returns the metadata plus a validation report and notes."""
    lang = topic.get("language") or templates.get("default_language") or "en"
    notes: list[str] = []
    values = _SafeDict({k: (_one_line(v) if isinstance(v, str) else v) for k, v in topic.items()})

    # ---- title
    title = _one_line(topic.get("title") or "")
    if not title:
        for tmpl in templates.get("title_templates", ["{topic}"]):
            candidate = _one_line(tmpl.format_map(values))
            if candidate and len(candidate) <= TITLE_MAX_CHARS:
                title = candidate
                break
        else:
            first = templates.get("title_templates", ["{topic}"])[0]
            title = truncate_words(_one_line(first.format_map(values)), TITLE_MAX_CHARS)
            if title:
                notes.append("title shortened to fit 100 characters")
    elif len(title) > TITLE_MAX_CHARS:
        title = truncate_words(title, TITLE_MAX_CHARS)
        notes.append("title shortened to fit 100 characters")

    # ---- tags / keywords
    raw_keywords = [str(k) for k in (topic.get("keywords") or [])]
    keywords, dup_kw = dedupe(raw_keywords)
    if dup_kw:
        notes.append(f"removed duplicate keywords: {', '.join(dup_kw)}")
    tag_candidates = keywords + [str(t) for t in (topic.get("extra_tags") or [])]
    tag_candidates, _ = dedupe(tag_candidates)
    tags, dropped_tags = fit_tags(tag_candidates, int(templates.get("max_tags", 15)))
    if dropped_tags:
        notes.append(f"dropped tags to stay within limits: {', '.join(dropped_tags)}")

    # ---- hashtags
    hashtag_src = [str(h) for h in (topic.get("hashtags") or [])] or keywords
    hashtags = []
    for h in hashtag_src:
        tag = to_hashtag(h.lstrip("#"))
        if tag:
            hashtags.append(tag)
    hashtags, _ = dedupe(hashtags)
    hashtags = hashtags[: int(templates.get("max_hashtags", 5))]

    # ---- CTA
    cta = _one_line(topic.get("cta") or "") or _one_line((templates.get("default_cta") or {}).get(lang, ""))

    # ---- description
    points = [_one_line(p) for p in (topic.get("points") or []) if _one_line(p)]
    chapters = topic.get("chapters") or []
    links = topic.get("links") or []
    blocks = _SafeDict(values)
    blocks.update(
        {
            "hook": _one_line(topic.get("hook") or ""),
            "summary": sanitize(topic.get("summary") or "").strip(),
            "points_block": "\n".join(f"• {p}" for p in points),
            "chapters_block": "\n".join(f"{_one_line(str(c.get('time', '')))} {_one_line(str(c.get('label', '')))}".strip() for c in chapters if isinstance(c, dict)),
            "links_block": "\n".join(f"{_one_line(str(link.get('label', '')))}: {str(link.get('url', '')).strip()}".strip(": ") for link in links if isinstance(link, dict)),
            "cta": cta,
            "hashtags_line": " ".join(hashtags),
            "disclosure": _one_line(topic.get("disclosure") or ""),
        }
    )
    description = templates.get("description_template", "{hook}\n\n{summary}\n\n{cta}\n\n{hashtags_line}").format_map(blocks)
    description = re.sub(r"\n{3,}", "\n\n", description).strip()
    if len(description.encode("utf-8")) > DESCRIPTION_MAX_BYTES:
        description = description.encode("utf-8")[: DESCRIPTION_MAX_BYTES - 3].decode("utf-8", "ignore").rstrip() + "…"
        notes.append("description truncated to 5000 bytes")
    if chapters:
        first = str(chapters[0].get("time", "")) if isinstance(chapters[0], dict) else ""
        if first not in ("0:00", "00:00"):
            notes.append("chapters: YouTube only shows chapters when the first timestamp is 0:00 and there are at least 3")

    # ---- category
    suggestions = suggest_category(topic, templates.get("category_rules", {}))
    explicit = topic.get("category_id")
    if explicit is not None:
        category_id, category_reason = str(explicit), "set explicitly in topic file"
    elif suggestions:
        category_id, category_reason = suggestions[0]["category_id"], f"matched keywords: {', '.join(suggestions[0]['matched'])}"
    else:
        category_id, category_reason = str(default_category), "default category (no keyword matched)"

    report = ValidationResult()
    report.merge(validate_title(title))
    report.merge(validate_description(description))
    report.merge(validate_tags(tags))
    report.merge(validate_category(category_id))

    return {
        "title": title,
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
        "keywords": keywords,
        "cta": cta,
        "category_id": category_id,
        "category_name": CATEGORY_NAMES.get(category_id, "unknown"),
        "category_reason": category_reason,
        "category_suggestions": suggestions[:3],
        "language": lang,
        "notes": notes,
        "validation": report.as_dict(),
        "disclaimer": DISCLAIMER,
    }


def to_upload_fields(meta: dict) -> dict[str, Any]:
    """The subset of generated metadata that maps onto an upload."""
    return {k: meta[k] for k in ("title", "description", "tags", "category_id") if k in meta}
