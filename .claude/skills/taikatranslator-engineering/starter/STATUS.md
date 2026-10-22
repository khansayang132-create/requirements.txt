# Starter kit — verification status

This records what was actually run on the kit. It says nothing about the real TaikaTranslator codebase, which has not been seen yet; every ticket there is still `NOT_STARTED`.

**Environment:** Ubuntu 24.04.5 container · OpenJDK 21.0.12.1 (compiling with `--release 17`) · Maven 3.9.11 · Python 3.13.16 · Pillow 12.3.0 · pytest 8.3.4 · LibreOffice 24.2.7.2 · pdftoppm 24.02.0 · Date 2026-10-22

## VERIFIED

| Check | Command | Result |
|---|---|---|
| Unit tests | `mvn -B clean verify` (Surefire) | 77 run, 0 failures: Retry 17, Geometry 15, TextFitter 12, ArtifactValidator 10, CLI 10, Translation 9, Reporting 4 |
| Integration tests | same (Failsafe) | 17 run, 0 failures: ProviderClientsIT 12 (DeepL + Azure against local stubs), EndToEndFixtureIT 5 |
| End-to-end gates | `EndToEndFixtureIT` → `target/e2e-evidence/report.json` | content.extracted, content.translated, artifact.integrity, structure, execution all passed; visual SKIPPED (by design); status SUCCESS_WITH_WARNINGS from the deliberate 0.6% overflow on p4 |
| DOCX structure vs expected file | `StructureDiff` against `expected/service-agreement.ES.structure.json` | no differences, including hand-derived font sizes (20 / 14 / 11 / 11 / 7.5) |
| Log hygiene | E2E test | key and document sentence absent from the log; runId on every line |
| Report schema | `jsonschema` 4.23.0 validation of the E2E report against `templates/processing-report.schema.json` | valid; an invalid status is rejected |
| Visual diff logic | `pytest scripts/tests` | 9 passed (8 synthetic-image tests + 1 real LibreOffice render of the E2E DOCX) |
| Visual diff round trip | `visual_diff.py baseline` then `compare` on the same DOCX; then on a copy with one sentence lengthened | identical: PASS exit 0; modified: FAIL exit 1, 1.1962% pixels changed (> 0.2%), `diff-1.png` written and inspected |
| `verify.sh` | `shellcheck -S warning` 0.10.0 | clean |

## Defects found and fixed while verifying
1. Exact double equality in a geometry test (pixel vs inch path differs in the last bit) → `NormalizedBox.approxEquals`.
2. URL token regex captured trailing sentence punctuation → pattern excludes `.,;:!?)]}'"` at the end; test added.
3. No-overwrite publish could race (atomic rename replaces on POSIX) → hard-link publish.
4. Reference pipeline first recorded the visual gate as passed while not running it → SKIPPED stage.
5. One test expectation was wrong (two 60,000-char texts fit a 120 KiB batch) → test corrected, code unchanged.

## Observed, not fixed (by design, documented)
- The E2E DOCX renders the expanded line at 7.5 pt. Correct for the fixed-advance measurer the test uses, but small on the page: real fitting must use the DOCX font's metrics (`AwtTextMeasurer`). Recorded in `references/traps.md` #5.

## NOT VERIFIED
| Item | Why | How to verify |
|---|---|---|
| Build and tests on JDK 17 | Only JDK 21 is installed here; `--release 17` guarantees the API level, not runtime behaviour | `taika-starter` CI job runs on Temurin 17 |
| Live Azure / DeepL calls | No keys here, and tests must not need them | `@Tag("live")` tests in the real project with keys from env |
| Azure mock fidelity | Mock is hand-authored from the documented shape | Re-record from one live `prebuilt-layout` call |
| Windows `verify.ps1` | No Windows here | Run on a Windows dev machine |
| `templates/ci.yml` in the real repo | Template only | First CI run in the TaikaTranslator repo |
