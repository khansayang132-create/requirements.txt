# Design log

One line per finished design, newest first, written by the `design-check` skill and the `design-director` agent. Read this before choosing a direction so different subjects don't get the same look.

| Date | Subject | Direction | Check caught |
|---|---|---|---|
| 2026-11-07 | Promovent v2.5 Next.js app (`promovent/web/`, 12 pages) | Same graphite ledger tokens as v2.0 (product continuity), sidebar ⇄ menu drawer, LIVE/SIMULATED/UNAVAILABLE badges on every data panel | 20 px alert checkboxes (now 24 px in a 44 px label; 12 warnings kept), header stretched on short pages (grid rows; found in screenshots), stale Next server serving old chunks (test setup). |
| 2026-11-07 | Promovent terminal (`promovent/promovent/static/index.html`) | Graphite trading ledger, dark only, teal/coral up-down + amber accent, system sans + mono figures, sticky status rail over a 12-col grid | TradingView in-chart logo link 35×19 px on phone (disabled; footer credits TradingView). Eyes caught: chart vs copilot on different synthetic series, duplicate alerts, marker clutter. All fixed. |
| 2026-10-29 | DONE Protocol app (`done/`) | Pitch black, violet accent, Inter + JetBrains Mono, sidebar ⇄ bottom drawer (from the `done-protocol` skill) | 22 px copy buttons, 20 px back link, 32/36 px pills on phone, h1 → h3 jumps. All fixed. |
