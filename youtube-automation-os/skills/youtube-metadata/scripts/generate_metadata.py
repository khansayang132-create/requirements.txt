#!/usr/bin/env python3
"""Generate and validate YouTube metadata (title, description, tags, hashtags, CTA, category)
from a topic file, using the templates in config/settings.yaml → metadata.

Offline and deterministic: no API calls, no quota. SEO results are not guaranteed.

Topic file fields (YAML or JSON): topic, hook, summary, points[], keywords[], hashtags[],
cta, language, title (optional override), category_id (optional), chapters[{time,label}],
links[{label,url}], disclosure, extra_tags[].

Examples:
  python skills/youtube-metadata/scripts/generate_metadata.py --topic data/topics/sample_topic.yaml
  python skills/youtube-metadata/scripts/generate_metadata.py --topic t.yaml --out data/topics/out/meta.json
  python skills/youtube-metadata/scripts/generate_metadata.py --validate-only existing_meta.yaml
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli  # noqa: E402
from src.config import get, load_env, load_settings, load_yaml_file, upload_defaults  # noqa: E402
from src.metadata import generate  # noqa: E402
from src.validators import ValidationResult, validate_category, validate_description, validate_tags, validate_title  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--topic", help="Topic YAML/JSON file")
    src.add_argument("--validate-only", metavar="METADATA_FILE", help="Validate an existing metadata file instead of generating")
    p.add_argument("--out", help="Write the result to this .json or .yaml file")
    p.add_argument("--language", help="Override the topic's language (id/en) for the default CTA")
    cli.add_output_flags(p)
    args = p.parse_args()
    load_env()
    settings = load_settings()

    if args.validate_only:
        meta = load_yaml_file(args.validate_only)
        r = ValidationResult()
        r.merge(validate_title(meta.get("title")))
        r.merge(validate_description(meta.get("description")))
        r.merge(validate_tags(meta.get("tags")))
        r.merge(validate_category(meta.get("category_id", "22")))
        cli.emit(r.as_dict(), args.json, _human_validation)
        return 0 if r.ok else 5

    topic = load_yaml_file(args.topic)
    if args.language:
        topic["language"] = args.language
    defaults = upload_defaults(settings)
    meta = generate(topic, get(settings, "metadata", {}) or {}, default_category=defaults["category_id"])
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.suffix.lower() in (".yaml", ".yml"):
            import yaml

            out.write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")
        else:
            out.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {out}", file=sys.stderr)
    cli.emit(meta, args.json, _human)
    return 0 if meta["validation"]["ok"] else 5


def _human_validation(r: dict) -> str:
    lines = [f"Valid: {r['ok']}"] + [f"ERROR: {e}" for e in r["errors"]] + [f"warning: {w}" for w in r["warnings"]]
    return "\n".join(lines)


def _human(m: dict) -> str:
    lines = [
        f"TITLE ({len(m['title'])}/100): {m['title']}",
        f"CATEGORY: {m['category_id']} {m['category_name']} — {m['category_reason']}",
        f"TAGS ({m['validation']['info'].get('tags_api_length', 0)}/500): {', '.join(m['tags'])}",
        f"HASHTAGS: {' '.join(m['hashtags'])}",
        "DESCRIPTION:",
        m["description"],
        "",
    ]
    lines += [f"note: {n}" for n in m["notes"]]
    lines += [f"ERROR: {e}" for e in m["validation"]["errors"]] + [f"warning: {w}" for w in m["validation"]["warnings"]]
    lines.append(m["disclaimer"])
    return "\n".join(lines)


if __name__ == "__main__":
    cli.run(main)
