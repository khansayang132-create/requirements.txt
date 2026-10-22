# TaikaTranslator Enterprise — backlog

**Mission:** high-fidelity document extraction, translation and reconstruction. Scanned and digital PDFs in; an editable DOCX out with layout preserved, text expansion handled, failures recovered from, and a measurable processing report.

**Status of every ticket below: `NOT_STARTED` in the real project.** The "Kit" line says where a verified reference implementation and its tests live in `starter/`. That evidence belongs to the kit, not to TaikaTranslator; a ticket becomes PASS only with evidence from the real repo's current commit.

## Execution order

| # | Work | Why first |
|---|---|---|
| 1 | Inspect the repo and Maven config (`references/adoption-guide.md` §0) | Real baseline |
| 2 | TSK-5.2.1 | Reproducible tests |
| 3 | TSK-5.2.2 – 5.2.4 | Geometry, text scaling, retry |
| 4 | TSK-5.2.5 – 5.2.6 | Whole pipeline verified |
| 5 | TSK-5.2.7 | Visual regression |
| 6 | TSK-6.1 – 6.6 | Runtime and artifact hardening |
| 7 | TSK-7.1 (can land right after 5.2.1) | CI |
| 8 | TSK-7.2 | Baselines, then targets |
| 9 | Docs | Document verified behaviour only |

---

## Phase 5 — Automated testing and quality gates

### TSK-5.2.1 — Deterministic test environment
- **Priority:** P0 · **Depends on:** repo inspection · **Kit:** `starter/pom.xml`
- **Scope:** JUnit 5; Surefire for `*Test`; Failsafe for `*IT`; `live` tag excluded from both; enforcer for Java/Maven versions; external clients behind interfaces; `@TempDir` everywhere.
- **Out of scope:** new features; moving packages.
- **Acceptance:**
  - [ ] `mvn clean test` passes with network disabled and no `AZURE_*`/`DEEPL_*` variables set.
  - [ ] `target/surefire-reports/*.xml` produced; `mvn verify` also produces `target/failsafe-reports/*.xml`.
  - [ ] A deliberately failing test makes `mvn test` exit nonzero (try once, revert).
  - [ ] Two consecutive runs give the same counts and results.
  - [ ] No test writes outside its temp dir or `target/`.
- **Verify:** `env -u DEEPL_AUTH_KEY -u AZURE_DI_KEY mvn -B clean verify && mvn -B verify; echo $?`
- **Evidence:** Maven summary lines, report XML paths, the test sources touched.

### TSK-5.2.2 — Layout normalization
- **Priority:** P0 · **Depends on:** 5.2.1 · **Kit:** `geometry/*`, `CoordinateNormalizerTest` (15 tests), `references/layout-and-geometry.md`
- **Scope:** provider coordinates → documented canonical system; adapter if the existing interface differs.
- **Acceptance:**
  - [ ] Canonical system documented in `docs/architecture.md` (range, origin, rotation, conversion points).
  - [ ] Tests for: zero width, zero height, negative, out-of-page, missing, malformed, NaN/∞, normalized vs pixel vs inch input, portrait, landscape, two page sizes in one document, rotation 90/180/270, missing/inconsistent page metadata, mislabelled units.
  - [ ] Every valid element lands inside [0,1] consistently with the documentation.
  - [ ] Every invalid case yields a named error or a documented recovery that appears in the report.
  - [ ] Geometry comparisons use a tolerance.
- **Verify:** `mvn -B test -Dtest='*Normaliz*,*Geometry*'`

### TSK-5.2.3 — Text-expansion calculations
- **Priority:** P0 · **Depends on:** 5.2.1 · **Kit:** `layout/*`, `TextFitterTest` (12 tests)
- **Scope:** font-size fitting from font metrics; character ratio only as fallback.
- **Acceptance:**
  - [ ] Tests for shorter, longer, empty, blank, very long, accented, mixed script (incl. CJK, Arabic, emoji), explicit line breaks, narrow table cell, min-size enforcement, degenerate box.
  - [ ] Size is never 0, negative, NaN or ∞, and always within configured [min, max].
  - [ ] No character is dropped (assert the joined lines equal the input minus wrap spaces).
  - [ ] A block that can't fit at min size produces a layout warning in the report.
  - [ ] Identical input → identical output.
  - [ ] Production measurer uses the DOCX's font; the resolved font family is recorded.
- **Verify:** `mvn -B test -Dtest='*Fit*'`

### TSK-5.2.4 — RetryExecutor resilience
- **Priority:** P0 · **Depends on:** 5.2.1 · **Kit:** `retry/*`, `RetryExecutorTest` (17 tests)
- **Acceptance:**
  - [ ] Cases: first-try success, recoverable error then success, 429 with Retry-After, Retry-After above the cap, 5xx, connection failure, timeout, exhaustion, interruption in the call, interruption during backoff, already-interrupted thread, non-retryable 400/401/403/404/456.
  - [ ] Attempts bounded by `maxAttempts` and by a time budget.
  - [ ] Non-idempotent calls are not retried after timeout or 5xx.
  - [ ] Backoff (exponential, capped, full jitter) asserted through an injected sleeper and random source; no real sleeping (suite stays fast).
  - [ ] Interrupt flag restored and exception propagated.
- **Verify:** `mvn -B test -Dtest='*Retry*'`

### TSK-5.2.5 — End-to-end document fixture
- **Priority:** P0 · **Depends on:** 5.2.2–5.2.4 · **Kit:** `src/test/resources/{fixtures,mocks,expected}`, `make_fixtures.py`, `EndToEndFixtureIT` (5 tests)
- **Scope:** synthetic document with heading, paragraphs, table, image/scanned page, stamp/signature where relevant, text that expands; mocked Azure and DeepL.
- **Acceptance:**
  - [ ] Fixture is synthetic or licensed, and regenerable by a script.
  - [ ] Expected extraction and expected translation stored as files, separate from code.
  - [ ] Output DOCX reopened and checked: paragraph and table counts, required source-derived text, translated text, artifact presence, page size.
  - [ ] Failure output names the element and the difference (no bare "expected true").
  - [ ] Failure paths: missing translation → no file published, report FAILED; existing output → untouched.
  - [ ] Repeated runs produce the same structure.
- **Verify:** `mvn -B verify -Dit.test='EndToEnd*'`
- **Evidence:** `target/e2e-evidence/{report.json,run.log.jsonl,*.docx}`

### TSK-5.2.6 — DOCX structural regression
- **Priority:** P0 · **Depends on:** 5.2.5 · **Kit:** `docx/DocxInspector`, `docx/StructureDiff`, `DocxAssemblerTest` (6 tests: merges, headers/footers, PAGE field, fonts, row heights)
- **Acceptance:**
  - [ ] Checks paragraph order, styles, alignment, font sizes, table shape, merged cells and cell text, image count/relationship/extent (EMU), header/footer text, page-number fields, section page size/orientation (twips).
  - [ ] Compares structure, never bytes.
  - [ ] DOCX opens in Apache POI; a truncated or non-DOCX ZIP is rejected (`ArtifactValidatorTest`).
- **Verify:** `mvn -B verify`

### TSK-5.2.7 — Visual regression
- **Priority:** P1 · **Depends on:** 5.2.5 · **Kit:** `scripts/visual_diff.py`, `scripts/tests/` (9 tests), baseline in `src/test/resources/baselines/`, CI job `taika-visual`
- **Acceptance:**
  - [ ] Renderer, versions and DPI recorded in the baseline manifest; baselines committed.
  - [ ] Compares page count, per-page pixel change (configurable threshold and tolerance), blank pages, content at page edges.
  - [ ] Writes `report.json` and a diff image per differing page.
  - [ ] Missing renderer → explicit NOT RUN (exit 3), never pass.
  - [ ] Runs as its own CI job, separate from structure tests.
- **Verify:** `python scripts/visual_diff.py compare <docx> --baseline <dir> --out target/visual; echo $?`

---

## Phase 6 — Production reliability and security

Details and defaults: `references/production-hardening.md`.

| Ticket | Objective | P | Kit |
|---|---|---|---|
| TSK-6.1 | Validate CLI arguments and input files | P0 | `cli/CliOptions`, `cli/Main`, runnable JAR (10 unit + 5 process-level tests) |
| TSK-6.2 | Structured, correlation-aware logging | P0 | `reporting/RunLog`, `Redactor` (4 tests + log checks in E2E and CLI tests) |
| TSK-6.3 | External API timeouts and retries | P0 | `retry/*`, `provider/*` (17 + 12 stub tests) |
| TSK-6.4 | Validate intermediate and final artifacts | P0 | `validation/*` (10 tests), vision output validation |
| TSK-6.5 | Configuration and secret validation | P0 | `config/*` (12 tests) |
| TSK-6.6 | Safe temporary-file handling | P0 | `core/RunWorkspace`, `AtomicPublisher.stage` |
| TSK-6.7 | Resource and document-size limits | P1 | `core/InputLimits` (file before upload; pages/blocks/characters before translation) |
| TSK-6.8 | Resumable processing checkpoints | P1 | `core/CheckpointStore`, `core/TranslationCache` (resume proven to make zero provider calls) |
| TSK-6.9 | Processing metrics and benchmarks | P1 | report counts/durations; benchmark harness not built |
| TSK-6.10 | Security and dependency audit | P1 | guidance only (`references/production-hardening.md`) |

### Vision stage (supports the mission's "detect document artifacts")
- **Kit:** `vision/segmenter.py` (10 pytest tests), `vision/VisionRunner` + `VisionRunnerIT` (6 tests).
- **Acceptance (real project):** measured precision/recall on 20–50 labelled real pages per document class; black-ink signatures handled or explicitly out of scope; runner timeout, exit-code mapping and output validation in place; CI fails rather than skips when the vision runtime is missing.

## Phase 7 — CI and quality

### TSK-7.1 — Build and test automation (P0)
Template: `templates/ci.yml`, `templates/verify.sh`, `templates/verify.ps1`. On PRs and pushes to main: pinned JDK, Python 3.12, deps, `compileall`, Python tests, `mvn clean verify`, upload reports, publish the JAR only when checks pass, visual job separate.

### TSK-7.2 — Quality gates
Collect baselines first, then set targets.

| Metric | Measures | Verified by |
|---|---|---|
| Extraction completeness | Required source text recovered | Expected-text comparison |
| Translation completeness | Required blocks translated | `TranslationValidator` |
| Structural preservation | Paragraph and table integrity | `StructureDiff` |
| Layout fidelity | Position and formatting | `visual_diff.py` |
| Artifact validity | Outputs readable | `ArtifactValidator` |
| Retry reliability | Recovery from transient failures | Stub fault injection |
| Performance | Time per page | Benchmark over repeated fixture runs (median, p95) |
| Memory | Peak usage | Instrumented benchmark |
| Reproducibility | Consistent output | Repeated fixture runs |

Don't promise 100% OCR accuracy or perfect layout. Define supported document classes and show each meets its documented thresholds.

## Target architecture

```
CLI → Input Validation → Document Classification → PDF/Image Preflight
    → Vision (optional: artifact masks, cleaned images)
    → Extraction (Azure / other) → Canonical Document Model → Structural Validation
    → Translation Planning → DeepL → Translation Validation
    → Layout Reconstruction → DOCX Generation → Artifact Validation → Processing Report
```

Target layout (adapt; don't move working files blindly): `src/main/java/com/taikatranslator/{cli,config,core,extraction,translation,vision,assembly,validation,reporting,model}`, `src/test/resources/{fixtures,expected,mocks,baselines}`, `vision/{segmenter.py,requirements.txt,tests/}`, `scripts/verify.{sh,ps1}`, `scripts/visual_diff.py`, `.github/workflows/ci.yml`, `docs/{architecture,configuration,testing,troubleshooting,performance}.md`, plus `README`, `CHANGELOG`, `CONTRIBUTING`, `SECURITY`.
