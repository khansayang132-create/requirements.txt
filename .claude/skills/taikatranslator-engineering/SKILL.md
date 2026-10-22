---
name: taikatranslator-engineering
description: Professional engineering playbook and verified starter kit for TaikaTranslator Enterprise (Java/Maven PDF → Azure Document Intelligence extraction → DeepL translation → DOCX reconstruction, with a Python vision helper). Use when asked to plan, implement, test, harden, review or report on TaikaTranslator work; write or update SpecKit tickets (TSK-x.y); decide whether a ticket can be marked PASS; set up its CI, fixtures or visual regression; or debug coordinates, text expansion, retries, DOCX output or provider (Azure/DeepL) behaviour.
---

# TaikaTranslator engineering

A method plus working code. TaikaTranslator's own source is **not in this repo**; it lives in the owner's project. This skill gives you the rules, the reference material and a **starter kit whose 134 Java tests and 19 Python tests have actually been run**, locally and in CI on JDK 17 (`starter/STATUS.md`). Port its patterns into the real code; never present kit evidence as evidence about TaikaTranslator. Nothing here touches `bot.py` or `apex/`.

## 0. First moves, every time

1. **Get the real code.** No source, no changes. Ask for `pom.xml`, `src/`, `vision/`, `walkthrough.md`, `GRAPH_REPORT.md`, existing tests, config templates. Tell the owner to leave out `.env`, keys, passwords and private documents.
2. **Inspect before moving anything** (`references/adoption-guide.md` §0). If the project has a Graphify knowledge graph, query it first (`graphify query` callers/callees/tests, `graphify path`, `graphify explain`) and fall back to Grep/Read. Record Java release, test framework, artifact name, HTTP client, logging stack, and where extraction/translation/retry/DOCX live.
3. **Run what exists** (`mvn -B clean verify`, `python -m compileall -q vision`) and keep the output. That's the baseline, red or green.
4. **Pick the next ticket** from the execution order in `backlog.md`. Foundation before features.

## 1. Where to look

`starter/.../` below is short for `starter/src/main/java/com/taikatranslator/`; each package has its tests under `starter/src/test/java/com/taikatranslator/`.

| You're asked to… | Open |
|---|---|
| Plan work, write or update a ticket, set a status | `backlog.md`, `templates/ticket-template.md`, §4 below |
| Add tests, make tests deterministic, build fixtures | `references/testing-playbook.md`, `starter/src/test/` |
| Coordinates, units, rotation, page sizes | `references/layout-and-geometry.md`, `starter/.../geometry/` |
| Font size / text expansion / overflow | `references/layout-and-geometry.md` § Text fitting, `starter/.../layout/` |
| Retries, timeouts, 429/456/5xx, polling | `references/providers.md`, `starter/.../retry/`, `starter/.../provider/` |
| Azure or DeepL request/response details | `references/providers.md` |
| CLI, logging, config, secrets, temp files, limits, checkpoints, audit | `references/production-hardening.md`, `starter/.../cli/Main`, `config/`, `core/` |
| Stamps, signatures, cleaning pages for OCR, calling Python from Java | `starter/vision/segmenter.py`, `starter/.../vision/VisionRunner` |
| Merged cells, headers/footers, page numbers, fonts in DOCX | `starter/.../docx/DocxAssembler`, `references/layout-and-geometry.md` |
| Output validation, safe publishing | `starter/.../validation/` |
| DOCX structure checks | `starter/.../docx/DocxInspector`, `StructureDiff` |
| Visual regression | `starter/scripts/visual_diff.py`, testing playbook § Visual |
| CI and local verify scripts | `templates/ci.yml`, `templates/verify.sh`, `templates/verify.ps1` |
| Processing report format | `templates/processing-report.schema.json`, `starter/.../reporting/ProcessingReport` |
| Review a change (yours or theirs) | `references/review-checklist.md` |
| Something behaves strangely | `references/traps.md` first |
| Port the kit into the real repo | `references/adoption-guide.md` |
| Report progress | `templates/status-report.md` |

## 2. The acceptance principle

A zero exit code proves only that the process ended. A translated document is accepted only when six gates are checked **separately**, each with its own recorded result:

| # | Gate | Evidence | Kit |
|---|---|---|---|
| 1 | Execution | every stage reported an outcome | report `stages[]` |
| 2 | Content | expected source text extracted; every block translated, placeholders intact | `content.extracted`, `content.translated` gates |
| 3 | Structure | paragraph order, styles, tables, sizes match expectation | `structure` gate, `StructureDiff` |
| 4 | Visual fidelity | rendered pages within thresholds of a baseline | `visual_diff.py` (separate job) |
| 5 | Artifact integrity | files have valid signatures; DOCX reopens in POI | `artifact.integrity` gate |
| 6 | Auditability | input hash, runId, versions, config (redacted) recorded | report `inputs`, `environment` |

A gate that didn't run is **SKIPPED**, never passed. Structure passing never implies visual passing; the kit's own render proved it (`references/traps.md` #5).

## 3. Engineering rules

1. **Interfaces at every external edge** (Azure, DeepL, vision subprocess, clock, sleeper, randomness). Unit tests use fakes: no network, no credentials, no real sleeping.
2. **Unit vs integration vs live.** `*Test` → Surefire; `*IT` → Failsafe against `127.0.0.1` stubs; `@Tag("live")` excluded by default, skipped (never passed) without keys.
3. **One canonical coordinate system** (normalized [0,1], top-left, rotation applied). Convert only at boundaries. Keep existing field meanings; add adapters. Compare with tolerances.
4. **Invalid geometry is loud:** a named error or a documented recovery that shows in the report.
5. **Text fitting uses real font metrics** of the DOCX font; character ratios only as fallback. Size always finite, positive, within [min, max]; text never truncated; overflow is a warning.
6. **Retries are a policy:** categories, not exceptions; bounded by attempts and time; full jitter; capped Retry-After; non-idempotent calls (Azure submit) not retried after timeout/5xx; 456 never retried; interrupts propagate.
7. **Artifacts:** stage next to the destination → validate (signature, structure, required content) → atomic no-clobber publish → keep diagnostics on failure. A filename existing is not success.
8. **CLI fails early,** before any paid call, with documented exit codes and no silent overwrite.
9. **Logs:** JSON lines, runId on every line, counts not content, never keys or document text.
10. **Fixtures** synthetic or licensed, generated by a script, expectations in files not code. Mocks marked synthetic until re-recorded live.
11. **Small, green steps.** Port behaviour plus its tests per PR. Don't move packages before the code is understood and covered. No abstraction without two implementations.
12. **Java version agrees** in `maven.compiler.release`, CI and production.

## 4. Definition of Done and status

PASS requires all of: implementation (or a written reason none is needed); relevant tests passing **on the current commit**; every acceptance box checked with what was observed; evidence (command, environment, result, report path); docs updated when behaviour/config changed; no secrets or document content anywhere.

`NOT_STARTED` · `IN_PROGRESS` · `BLOCKED` (name the dependency) · `PASS` · `FAIL` (verification ran, a criterion failed). Code written is not PASS. Old-commit evidence is not PASS. Kit evidence is not TaikaTranslator evidence.

## 5. Reporting

Use `templates/status-report.md`: Verified / Failed / Not verified (with why and how to verify) / Blocked / ticket transitions / next action. Report counts ("77 passed, 0 failed"), not adjectives. Don't promise 100% OCR accuracy or perfect layout: define supported document classes and show each meets its thresholds.

## 6. Verification commands

```
python --version && python -m pip --version
python -m compileall -q vision
mvn -B clean verify                       # unit + integration; reports in target/*-reports/
python scripts/visual_diff.py compare <out.docx> --baseline <dir> --out target/visual
```
Same commands on Linux and Windows PowerShell (`templates/verify.ps1` wraps them). `compileall` proves only that Python parses; model-backed vision needs its own integration test. Check the real JAR name in `pom.xml` before writing any `java -jar target/<name>.jar --input … --output-dir …` instruction.

## 7. The starter kit

```
cd .claude/skills/taikatranslator-engineering/starter
mvn -B clean verify && python -m pytest -q scripts/tests vision/tests
java -jar target/taikatranslator.jar --help
```
Map of packages to tickets: `starter/README.md`. What was really run, defects found, and what's still unverified: `starter/STATUS.md`. CI runs it on every push (`taika-starter` and the separate visual gate `taika-visual` in this repo's `.github/workflows/test.yml`). If you change the kit, rerun both commands and update `STATUS.md`.
