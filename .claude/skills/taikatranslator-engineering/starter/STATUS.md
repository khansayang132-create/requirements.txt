# Starter kit — verification status

This records what was actually run on the kit. It says nothing about the real TaikaTranslator codebase, which has not been seen yet; every ticket there is still `NOT_STARTED`.

**Environment:** Ubuntu 24.04.5 container · OpenJDK 21.0.12.1 (compiling with `--release 17`) · Maven 3.9.11 · Python 3.13.16 · Pillow 12.3.0 · numpy 2.5.3 · pytest 8.3.4 · LibreOffice 24.2.7.2 · pdftoppm 24.02.0 · Carlito font · Date 2026-10-22. CI: GitHub Actions ubuntu-24.04, Temurin 17, Python 3.12, Pillow 13.0.0, numpy 2.2.6.

## VERIFIED

| Check | Command | Result |
|---|---|---|
| Unit tests | `mvn -B clean verify` (Surefire) | 106 run, 0 failures: Retry 17, Geometry 15, ConfigLoader 12, TextFitter 12, Core 11 (workspace, limits, checkpoints, translation cache), ArtifactValidator 10, CLI options 10, Translation 9, DocxAssembler 6, Reporting 4 |
| Integration tests | same (Failsafe), `VISION_REQUIRED=1` | 28 run, 0 failures, 0 skipped: ProviderClientsIT 12, VisionRunnerIT 6, CliMainIT 5, EndToEndFixtureIT 5 |
| Python | `pytest scripts/tests vision/tests` | 19 passed, 1 skipped (the optional real-render test needs `VISUAL_DOCX`; it passes when set) |
| Runnable JAR | `CliMainIT` launches `target/taikatranslator.jar` as a separate process with a clean environment | exit codes 0/2/3/4/5/8/9 as documented; zero provider calls before cheap checks pass; full run; overwrite refused with the original byte-identical; `--overwrite` resume made **no** new Azure or DeepL calls (14 cache hits); character limit stops before translation; DeepL 456 → exit 5, called once, diagnostics kept |
| Secrets and content | CliMainIT, EndToEndFixtureIT, ConfigLoaderTest | both keys absent from stdout, stderr, report and exception messages; document sentence absent from logs; secret in a config file rejected by name, value never printed |
| End-to-end gates | `EndToEndFixtureIT` → `target/e2e-evidence/report.json` | content.extracted, content.translated, artifact.integrity, structure, execution passed; visual SKIPPED (separate job); SUCCESS_WITH_WARNINGS from the deliberate 0.6% overflow |
| DOCX structure | `StructureDiff` vs `expected/service-agreement.ES.structure.json` | no differences: text, styles, font sizes (20/14/11/11/7.5), merged "Fees" row, header part, page-number field, Letter page size |
| Merged cells | `DocxAssemblerTest` + LibreOffice render inspected | 1x3, 2x1 and 2x2 spans round-trip; render shows all four rows after the row-height fix |
| Vision | `vision/tests` + `VisionRunnerIT` | red stamp and blue signature found at the right place; black text never reported; cleaned page has 0 coloured pixels left; timeout kills a hanging script in < 15 s; exit codes mapped; bad output rejected |
| Report schema | `jsonschema` 4.23.0 against `templates/processing-report.schema.json` | valid; invalid status rejected |
| Visual round trip | `visual_diff.py baseline` / `compare` | identical: PASS; modified sentence: FAIL 1.1962% (> 0.2%) with diff image |
| Visual baseline | `src/test/resources/baselines/service-agreement.ES/` | rendered here and inspected by eye before commit |
| JDK 17 | CI `taika-starter` on Temurin 17 | green (run 68, commit `8d3b4bf`); later commits re-verified by CI on push |
| `verify.sh` | `shellcheck -S warning` 0.10.0 | clean |

## Defects found and fixed while verifying
1. Exact double equality in a geometry test → `NormalizedBox.approxEquals`.
2. URL token regex captured trailing sentence punctuation → fixed, test added.
3. No-overwrite publish could race (atomic rename replaces on POSIX) → hard-link publish.
4. Reference pipeline first recorded the visual gate as passed while not running it → SKIPPED stage.
5. Wrong test expectation (two 60,000-char texts fit one 120 KiB batch) → test corrected.
6. Merge-only table rows collapsed to zero height in LibreOffice (structure tests green) → minimum row heights; test added.
7. Test data contradicted itself (text under a merge; 8.27 in ≠ A4; 13 vs 14 blocks) → expectations derived and commented.
8. Page numbers were copied as literal text → PAGE field.
9. Blank cells were sent to the translator → skipped; E2E proves it (no dictionary entry for "").
10. Nested stamp rings detected as separate artifacts → overlapping boxes merged.
11. Anti-aliased stamp text left 20 coloured pixels on the cleaned page → looser threshold inside detected boxes; 0 left; test added.
12. DOCX declared no fonts, so renderers chose their own → Calibri declared on every run, measured with metric-compatible Carlito.

## Observed, not fixed (by design, documented)
- The E2E DOCX renders the expanded line at 7.5 pt because the test uses the fixed-advance measurer on purpose (determinism). The CLI uses real Carlito metrics. `references/traps.md` #5.
- The vision segmenter is a colour-ink heuristic: black-ink signatures are not detected; thresholds are untuned for real scans. It says so in its own output (`limitations`).

## NOT VERIFIED
| Item | Why | How to verify |
|---|---|---|
| `taika-visual` CI job on a clean runner | Added in commit `701f51d`; first result pending at time of writing | Check the job; if fonts differ, regenerate the baseline on the CI image and review it |
| Live Azure / DeepL calls | No keys here, and tests must not need them | `@Tag("live")` tests in the real project with keys from env |
| Azure mock fidelity | Hand-authored from the documented shape | Re-record from one live `prebuilt-layout` call |
| Vision accuracy on real scans | Only synthetic pages exist here | Label 20–50 real pages per document class; measure precision/recall |
| Windows `verify.ps1` | No Windows here | Run on a Windows dev machine |
| `templates/ci.yml` in the real repo | Template only | First CI run in the TaikaTranslator repo |
