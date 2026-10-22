# TaikaTranslator Enterprise — backlog

Mission: high-fidelity document extraction, translation and reconstruction. Scanned and digital PDFs in; editable DOCX out with layout preserved, text expansion handled, failures recovered from, and a measurable processing report.

Every status below is `NOT_STARTED` until verified against the real codebase. Write each ticket out in full with [`ticket-template.md`](./ticket-template.md) when work starts.

## Execution order

| Order | Work | Why first |
|---|---|---|
| 1 | Inspect the repo and Maven config | Real baseline |
| 2 | TSK-5.2.1 | Reproducible tests |
| 3 | TSK-5.2.2 – 5.2.4 | Geometry, text scaling, retry |
| 4 | TSK-5.2.5 – 5.2.6 | Whole pipeline verified |
| 5 | TSK-5.2.7 | Visual regression |
| 6 | TSK-6.1 – 6.6 | Runtime and artifact hardening |
| 7 | TSK-7.1 | CI |
| 8 | TSK-7.2 | Baselines, then targets |
| 9 | Docs | Document verified behaviour only |

## Phase 5 — Automated testing and quality gates

### TSK-5.2.1 — Deterministic test environment (P0)
- JUnit 5 + Surefire for unit tests; Failsafe for `*IT` integration tests.
- Unit tests need no Azure/DeepL credentials and no network; clients injected through interfaces.
- `@TempDir` for artifacts; tests clean up.
- **Accept:** `mvn clean test` passes; Surefire XML produced; failures give a nonzero exit; repeated runs agree.
- **Evidence:** Maven summary, `target/surefire-reports/*.xml`, test sources.

### TSK-5.2.2 — Layout normalization (P0)
- Cases: zero width/height, negative or out-of-page, missing coords, normalized vs pixel input, portrait/landscape, mixed page sizes, rotated pages, missing or inconsistent page metadata.
- Document the canonical coordinate system (normalized `[0,1]`, origin, rotation). Adapter for any existing interface that uses another system.
- **Accept:** every valid element is consistent with the documented system; invalid geometry → explicit error or documented recovery, never a silent position.

### TSK-5.2.3 — Text-expansion calculations (P0)
- Cases: shorter, longer, empty, very long, Unicode/accents, mixed script, line breaks, narrow table cells, minimum readable size.
- Font metrics first; character ratio as fallback.
- **Accept:** size never 0/negative/NaN/∞; min/max respected; no silent truncation; layout warning when a block can't fit; deterministic.

### TSK-5.2.4 — RetryExecutor resilience (P0)
- Cases: first-try success, recoverable HTTP, 429, 5xx, connection failure, timeout, exhaustion, interruption, `Retry-After`, backoff + jitter.
- **Accept:** bounded; non-retryable fails at once; interruption propagates; backoff tested via injectable clock/delay; no real sleeping. Non-idempotent calls retried only when safe.

### TSK-5.2.5 — End-to-end fixture (P0)
- Synthetic document: heading, several paragraphs, simple table, scanned page or image, signature/stamp where relevant, text that expands.
- Mocked Azure and DeepL responses for CI; real-cloud tests kept separate.
- **Accept:** documented expected extraction; expected translation stored apart from code; output DOCX reopened and checked for paragraph/table counts, required text and translations, artifact presence and page bounds; readable failure report.

### TSK-5.2.6 — DOCX structural regression (P0)
- Check paragraph order, table rows/columns, cell text, font sizes and basic styling, alignment, image relationships, image size/placement, page/section properties.
- **Accept:** DOCX opens in Apache POI with all required elements. Compare structure, not bytes (ZIP metadata and XML order vary).

### TSK-5.2.7 — Visual regression (P1)
- Render DOCX → PDF/images; compare text position, table geometry, image placement, page count, overflow, blank pages, clipping.
- **Accept:** renderer and version documented; baselines versioned; thresholds configurable; inspectable diff report; missing renderer reported explicitly. Stays separate from 5.2.6.

## Phase 6 — Production reliability and security

| Ticket | Objective | Priority |
|---|---|---|
| TSK-6.1 | Validate CLI arguments and input files | P0 |
| TSK-6.2 | Structured, correlation-aware logging (`runId`) | P0 |
| TSK-6.3 | External API timeouts and retries | P0 |
| TSK-6.4 | Validate intermediate and final artifacts | P0 |
| TSK-6.5 | Configuration and secret validation | P0 |
| TSK-6.6 | Safe temporary-file handling | P0 |
| TSK-6.7 | Resource and document-size limits | P1 |
| TSK-6.8 | Resumable processing checkpoints | P1 |
| TSK-6.9 | Processing metrics and benchmarks | P1 |
| TSK-6.10 | Security and dependency audit | P1 |

- **6.1:** reject missing/unsupported input, check output-dir permissions, handle spaces in paths, reject bad config, meaningful exit codes, usage text, never overwrite silently.
- **6.2:** log stage, duration, retries, error category, pages, extracted/translated block counts, validation results. Illustrative event: `{"timestamp","level","runId","stage","event","durationMs","status"}`. No keys, auth headers or document content.
- **6.3:** configurable connect timeout, request timeout, max retries, max backoff, provider concurrency, overall deadline. Separate transport, rate-limit, server and permanent client errors. Azure submit / poll / fetch each get their own policy.
- **6.4:** existence, non-zero size, signature, JSON validity, PNG validity, DOCX reopen, required content, final location. Temp → validate → atomic move. Keep diagnostics on failure.

## Phase 7 — CI and quality

### TSK-7.1 — Build and test automation (P0)
On pull requests and pushes to the main branch: pinned JDK, Python 3.12 (or the declared version), install Python deps, `python -m compileall -q vision`, Python unit tests, `mvn clean verify`, archive test reports, publish the build artifact only when required checks pass.

### TSK-7.2 — Quality gates
Collect baselines first, then set targets.

| Metric | Measures | Verified by |
|---|---|---|
| Extraction completeness | Required source text recovered | Expected-text comparison |
| Translation completeness | Required blocks translated | Block-level validation |
| Structural preservation | Paragraph and table integrity | DOCX structure checks |
| Layout fidelity | Position and formatting | Rendered-page comparison |
| Artifact validity | Outputs readable | Format validation |
| Retry reliability | Recovery from transient failures | Fault-injection tests |
| Performance | Time per page | Benchmark suite |
| Memory | Peak usage | Instrumented benchmark |
| Reproducibility | Consistent output | Repeated fixture runs |

## Target architecture

```
CLI → Input Validation → Document Classification → PDF/Image Preflight
    → Vision (optional: artifact masks, cleaned images)
    → Extraction (Azure / other) → Canonical Document Model → Structural Validation
    → Translation Planning → DeepL → Translation Validation
    → Layout Reconstruction → DOCX Generation → Artifact Validation → Processing Report
```

Target layout (adapt; don't move working files blindly): `src/main/java/com/taikatranslator/{cli,config,core,extraction,translation,vision,assembly,validation,reporting,model}`, `src/test/resources/{fixtures,expected,mocks}`, `vision/{segmenter.py,requirements.txt,tests/}`, `scripts/verify.{sh,ps1}`, `.github/workflows/ci.yml`, `docs/{architecture,configuration,testing,troubleshooting,performance}.md`, plus `README`, `CHANGELOG`, `CONTRIBUTING`, `SECURITY`.
