# The Kite That Came Home — final review

**Status: waiting for your approval.** The pipeline is at `QUALITY_CONTROL` with every automatic check PASS. Nothing has
been approved or delivered on your behalf.

## Watch

| What | File |
|---|---|
| The film (57.1 s, 1920×1080, 24 fps, H.264 + AAC stereo, embedded subtitles) | `../movie/the-kite-that-came-home.mp4` |
| A frame every 2 s, with timestamps | `sheet_01.jpg`, `sheet_02.jpg` |
| Subtitles | `../movie/subtitles.srt` |
| Screenplay | `../story/screenplay.md` |
| Cast | `../reports/cast_lineup.png` |

Cast (all original): Amara Vale (9, lead), Teo Vale (15, her brother), Rosa Vale (38, mother), Idris Vale (72,
grandfather), Noor Haddad (45, neighbour). Three scenes: Fernmoor Park, the lost kite, Maple Street at sunset.

## What was measured (all PASS)

| Check | Result |
|---|---|
| Pipeline QA (`../reports/qa-report.md`) | 142 / 142 PASS: rigs, deformation, foot slide < 2 cm, lip-sync timing, every frame CRC-checked, A/V sync, loudness, subtitles |
| Every frame decoded (`../movie/media_audit_pilot.json`) | 1371 frames; no black, blank, frozen or flash frames except the declared ones: 0.4 s dips to black between scenes and the 5 s credits card |
| Audio | −16.2 LUFS integrated, true peak −1.5 dBFS, 0 clipped samples, no dropouts, audio and video both 57.125 s |
| Real playback | Played in Chromium: ready state 4, time advancing, 1920×1080 |
| Delivery readiness | No registered asset changed since registration, so `hv deliver` can write its manifest |

## What changed in this review

- **S02_SH01 (18–22 s, "No… the string broke. It's gone!")**: the camera aimed above a 1.25 m child, so Amara sat
  at the bottom edge, cut at the chest. Four camera options were test-rendered. The chosen one frames her waist-up
  with the kite still escaping over the trees, and only the camera target changed. The 122 frames were
  re-rendered in Cycles, then the film was re-cut and re-checked. The previous version, its frames and the old
  settings are in `../revisions/r1-S02_SH01/`. The frames and the .blend are local only, not in git.
- **The kite in S03 (33–51 s)** was keyed to fixed points, so in Noor's close-up it hung in front of her rather
  than in her hand. Props can now be held: they're baked to the hand on every frame. Noor holds the kite, hands
  it to Amara, and Amara holds it beside her until it rises over the group in the final cheer. S03 was
  re-rendered (463 frames) and the film re-cut and re-checked; previous files are in `../revisions/r2-S03-kite/`.

## Please judge (no machine measures these)

1. **Appeal and acting.** Faces are simple and stylised. Expressions read, but this is not feature-film animation.
2. **Lip sync.** Mouth timing follows the dialogue. Mouth *shapes* were not checked against a phoneme recogniser.
3. **The kite** is a simple flat diamond, which is large in Noor's close-up.
4. **Voices** are local text-to-speech, not actors.

## Approve and deliver (your decision)

```bash
cd humanverse
.venv/bin/python .claude/skills/humanverse-studio/scripts/hv.py approve --as "<your name>" --notes "<optional>"
.venv/bin/python .claude/skills/humanverse-studio/scripts/hv.py deliver
```

`approve` records your name and the QA result in `../reports/approval.json`. `deliver` writes `../delivery.json`,
listing every delivered file with its size and sha256, and refuses if any asset changed after registration. Nothing is
published or uploaded by either command.

To ask for changes instead, say which shot and what's wrong. Each shot can be re-rendered on its own, as S02_SH01 was.
