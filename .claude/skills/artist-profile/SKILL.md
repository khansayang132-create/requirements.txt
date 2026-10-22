---
name: artist-profile
description: Create a Spotify artist profile Markdown file from the owner's standard template (basic info, profile status, security assessment, technical notes, biography, discography, tracks, related artists). Use when asked to create, start or fill an artist profile.
---

# Artist profile

Builds one Markdown profile per artist from [`template.md`](./template.md). This is separate from the LSKhan TikTok tools; it does not touch `bot.py` or `apex/`.

## Steps

1. Copy `template.md` to `profiles/<artist-slug>.md` (create `profiles/` if it doesn't exist). One file per artist; don't overwrite an existing profile, update it.
2. Replace the placeholders:
   - `{{ARTIST_NAME}}`: the artist's display name.
   - `{{SPOTIFY_ID}}`: the 22-character Spotify artist ID (the part after `/artist/` in the link). Unknown → `TBD`.
   - `{{TIMESTAMP}}`: ISO 8601 time of collection, e.g. `python3 -c "import datetime; print(datetime.datetime.now().isoformat())"`.
   - `{{SOURCE_USER_ID}}`: the Spotify user whose following list the artist came from.
3. Fill a `TBD` field only with a value you actually retrieved (Spotify API or the artist's public page). Leave anything you couldn't retrieve as `TBD`; never estimate listeners, followers, popularity, genres or a risk level.
4. When a field is filled, update **Data Completeness** and **Validation** to match what was really done.

## Rules

- Public data only. No private account data, no credentials in the file.
- Same honesty rule as the rest of this repo: no invented numbers, sources or classifications.
