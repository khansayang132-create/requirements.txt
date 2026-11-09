---
name: youtube-metadata
description: Generate and validate YouTube titles, descriptions, tags, hashtags, keywords, calls to action and a category suggestion from a topic file, within YouTube's limits. Offline, no quota. Use for "generate SEO metadata", "write the title and description", or to check an existing metadata file.
---

# youtube-metadata

## 1. Skill name
`youtube-metadata`

## 2. Description
Template-based, deterministic metadata assembly with limit-aware validation. It never claims guaranteed SEO results.

## 3. Purpose
Turn creative inputs into upload-ready metadata that passes YouTube's rules. The inputs are a hook, summary, points, keywords and a CTA, written by you or drafted by Claude. The generator removes duplicate keywords, strips forbidden characters, fits tags to 500 API characters, and caps hashtags. It suggests a category with a stated reason.

## 4. When to use
- "Generate SEO metadata for this video" → write or ask Claude for a topic file, then run the generator.
- Validate a hand-written metadata file before uploading (`--validate-only`).
- The pipeline calls the same code when `metadata.topic_file` is set.

## 5. Required inputs
`--topic FILE` (YAML/JSON) containing at least `topic` or `hook`. Or `--validate-only FILE`.

## 6. Optional inputs
Topic fields: `title` (override), `summary`, `points[]`, `keywords[]`, `extra_tags[]`, `hashtags[]`, `cta`, `language` (`id`/`en` picks the default CTA), `category_id`, `chapters[{time,label}]`, `links[{label,url}]`, `disclosure`. CLI: `--out FILE.json|.yaml`, `--language`, `--json`.

## 7. Expected outputs
`title`, `description`, `tags`, `hashtags`, `keywords`, `cta`, `category_id`/`category_name`/`category_reason`, `category_suggestions`, `notes` (what was changed and why), `validation` (`ok`, `errors`, `warnings`, `tags_api_length`) and a `disclaimer`.

## 8. Dependencies
`PyYAML`. No network, no auth, no quota.

## 9. Exact execution commands
```bash
python skills/youtube-metadata/scripts/generate_metadata.py --topic data/topics/sample_topic.yaml
python skills/youtube-metadata/scripts/generate_metadata.py --topic data/topics/sample_topic.yaml --out data/topics/out/meta.json
python skills/youtube-metadata/scripts/generate_metadata.py --validate-only data/topics/out/meta.json
```

## 10. CLI arguments
`--topic FILE` | `--validate-only FILE` (one is required), `--out FILE`, `--language CODE`, `--json`. Exit 0 = valid, 5 = invalid.

## 11. Configuration
`config/settings.yaml` → `metadata`:
- `title_templates`: the first one that fits in 100 characters wins.
- `description_template`: placeholders `{hook}`, `{summary}`, `{points_block}`, `{chapters_block}`, `{cta}`, `{links_block}`, `{disclosure}`, `{hashtags_line}`, plus any topic key.
- `default_cta` per language, `max_tags`, `max_hashtags`, `category_rules` (category ID → keywords).

## 12. Error handling
| Rule | Limit |
|---|---|
| Title | required, ≤ 100 characters, no `<` `>` |
| Description | ≤ 5000 **bytes** UTF-8 (emoji count 4), no `<` `>` |
| Tags | ≤ 500 characters as the API counts them (comma between tags, quotes around tags containing spaces); no commas inside a tag; duplicates are an error |
| Hashtags | capped at `max_hashtags` (YouTube ignores all of them above 60) |
| Chapters | note if the first chapter is not 0:00 |

## 13. Failure recovery
Validation errors list every problem at once. Fix the topic file and re-run; generation is deterministic, so the same input gives the same output.

## 14. Security considerations
Purely local. Topic files are data: the template uses `str.format_map` with string values only, so no code runs. Keep descriptions truthful, with no invented events or statistics. The LSKhan content rules apply.

## 15. Integration with other skills
- `upload.py --metadata out.json`.
- `update_video.py --metadata out.json`.
- The pipeline's `metadata.topic_file`. Explicit `metadata.title` and friends in the pipeline config override generated values.

## 16. Working examples
```text
$ python skills/youtube-metadata/scripts/generate_metadata.py --topic data/topics/sample_topic.yaml
TITLE (52/100): Kalau kamu mau nikah beda negara… dengarkan ini dulu
CATEGORY: 22 People & Blogs — matched keywords: keluarga, pernikahan, nikah, marriage
TAGS (99/500): nikah beda negara, indonesia pakistan, mixed marriage, pernikahan internasional, tips menikah
HASHTAGS: #NikahBedaNegara #IndonesiaPakistan #MixedMarriage
...
note: removed duplicate keywords: Nikah Beda Negara
Generated from templates. Search/SEO performance is not guaranteed.
```
