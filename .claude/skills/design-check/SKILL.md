---
name: design-check
description: Make anything Claude builds look finished and work for real people, then prove it. Pairs a design pass (direction from frontend-design or the project's own system) with a rendered check (scripts/check.mjs) for contrast, overflow, tap targets, fonts, focus, headings and JS errors at phone and desktop widths in light and dark. Use before calling any page, app, artifact, dashboard, email, slide or UI change done, when asked to make something beautiful, polished or professional, or to review a design.
---

# Design check

Beautiful means two things here, and both are required:

1. **Chosen.** Every colour, typeface, size and gap is a decision made for this subject. Taste and direction come from the project's own design system if it has one, otherwise from the [`frontend-design`](../frontend-design/SKILL.md) skill. This skill doesn't repeat that guidance.
2. **Measured.** It renders correctly for real people: readable contrast, no sideways scroll on a phone, targets a thumb can hit, fonts that actually load, focus you can see, no errors. `scripts/check.mjs` measures these; eyes and screenshots miss them.

The rule: **nothing is "done" until the check has run on the rendered result and you have looked at the screenshots.** "Looks good" without a check is a guess.

---

## 1. The loop

```
direction → build → check → look → fix → check again → log
```

1. **Direction.** In order of precedence:
   - the user's own words;
   - the project's system (a `CLAUDE.md` rule, a design skill like `done-protocol`, or a tokens/theme file);
   - `frontend-design`.

   Write the direction as tokens at the top of the CSS: 4–6 colours, 2 type roles, a spacing step, and one line naming the layout idea. Read [`../../design-log.md`](../../design-log.md) first, and don't reuse a direction listed there for a different subject.
2. **Build** from those tokens only. No stray hex values or one-off sizes.
3. **Check.** Run it on the real thing: the built file, the dev server, or the deployed URL.
   ```
   node .claude/skills/design-check/scripts/check.mjs <file.html | url> --out <dir>
   ```
   - Pick widths and schemes to match the work: `--schemes dark` for a dark-only app, `--widths 390,768,1440` for layouts with a tablet breakpoint.
   - For hash-routed apps, check every route: `http://127.0.0.1:4173/#/route`.
4. **Look.** Open the screenshots in `<dir>` (`390-light.png`, `1440-dark.png`, …) with the Read tool. The check can't judge hierarchy, balance or whether it feels right. You can, so use §3.
5. **Fix** every ERROR. Fix a WARN or write one line on why it stays (e.g. "30 px copy icon is secondary; 24 px minimum met").
6. **Check again** until there are 0 errors. Stop at three rounds; if errors remain, report them and say why they can't be fixed.
7. **Log** one line in `design-log.md`: date, subject, direction, and what the check caught.

## 2. What the check measures

| Check | Level | Rule |
|---|---|---|
| `overflow` | error | Page wider than the viewport (names the element that sticks out). |
| `contrast` | error | Text below WCAG AA: 4.5:1, or 3:1 for text ≥ 24 px or bold ≥ 18.66 px. Translucent layers are composited; text on an image or gradient is skipped. |
| `tap-target` | error < 24 px, warn < 44 px | Phone widths only; inline links inside paragraphs are exempt. |
| `alt` | error | `<img>` without `alt` (`alt=""` for decorative). |
| `js-error`, `console`, `load-failed`, `load` | error | Anything the page throws, logs as an error, or fails to fetch. |
| `font` | warn | A named family that never renders (not loaded, not installed), so the page silently shows a fallback. |
| `clipped` | warn | Text cut off by `overflow: hidden` with no ellipsis. |
| `headings` | warn | No `h1`, or a skipped level. |
| `focus` | warn | Keyboard focus changes nothing visible. |
| `line-length` | warn | Paragraphs over ~95 characters per line. |
| `title` | warn | No `<title>`. |
| `theme` | info | Identical in light and dark. Fine only when one look is deliberate. |

Exit code 1 means there are errors. `--json` prints the findings for scripts and agents.

**Setup:** you need Node 18+ and Playwright. Cloud sessions here already have both. Elsewhere, run `npm i -g playwright && npx playwright install chromium`. The script finds Playwright in the project or the global npm root. If it can't run (no Node, or a claude.ai chat), say **NOT CHECKED** in the report; never write "verified".

## 3. The look: a 60-second critique

Answer each one from the screenshots, not from the code:

- **One focal point** per screen? Squint at the screenshot: the first thing you see should be the most important thing.
- **Hierarchy in three steps or fewer.** Primary, secondary and muted text are clearly different; nothing else competes.
- **Alignment.** Do left edges line up down the page? Does repeated content (cards, rows) share the same padding and baselines?
- **Rhythm.** Do gaps come from one scale (4/8/12/16/24/32/48…)? Related items should sit closer together than unrelated ones.
- **Density fits the job.** Tools are compact and scannable; reading pages are airy with ~65-character lines.
- **Phone first.** At 390 px: no cramped rows, is the main action within thumb reach, does nothing hide under a fixed bar?
- **Both themes** (unless deliberately single): dark mode should be its own palette, not inverted colours, and the accent has to work on both backgrounds.
- **Real content.** No lorem ipsum and no fake metrics presented as real; empty states say what goes there.
- **Remove one thing.** Pick the weakest decoration and delete it.

## 4. Other kinds of output

- **Chat answers and Markdown:** lead with the answer, use headings only past ~3 sections, use a table when comparing ≥ 3 things on ≥ 2 attributes, put code in fenced blocks with the language, and keep paragraphs to 1–3 sentences.
- **Slides:** one idea per slide; the title is the takeaway, not the topic; at most 6 lines; numbers get their own slide. Render to HTML and run the check at the deck's size (`--widths 1280 --schemes light`).
- **Email (HTML):** single column ≤ 600 px, inline styles, system fonts, real `alt` text. Check at `--widths 390,600`.
- **Terminal output:** align columns, put one status word first (PASS/FAIL/WARN), end with a summary line, and use no colour codes unless the tool already does.
- **claude.ai artifacts:** the platform's artifact contract wins (themes, CDN allowlist, skeleton). Check the local HTML before publishing.

## 5. Report format

```
Design check: <what>, <widths> × <schemes>
Errors fixed: <n> (<list>)   Warnings left: <n> (<why each stays>)
Screenshots: <dir>
Direction: <one line>   Logged: yes
```
