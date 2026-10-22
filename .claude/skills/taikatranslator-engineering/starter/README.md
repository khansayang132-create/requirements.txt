# TaikaTranslator starter kit

Verified reference implementations for the Phase 5 / Phase 6 tickets, with the tests that prove them. It is **not** TaikaTranslator: it's the pattern library to port into the real project (see `../references/adoption-guide.md`). What has really been run is recorded in [`STATUS.md`](./STATUS.md).

## Run it

```
mvn -B clean verify                                   # 106 unit (Surefire) + 29 integration (Failsafe), builds target/taikatranslator.jar
python -m pip install -r vision/requirements.txt pytest
python -m pytest -q scripts/tests vision/tests        # visual_diff.py + vision segmenter
VISUAL_DOCX=target/e2e-evidence/service-agreement.ES.docx python -m pytest -q scripts/tests   # adds a real LibreOffice render
java -jar target/taikatranslator.jar --help           # exit codes and flags
```
Needs JDK 17+ and Maven 3.8+. No network beyond Maven Central, no credentials. Evidence lands in `target/surefire-reports/`, `target/failsafe-reports/` and `target/e2e-evidence/` (DOCX, report.json, run.log.jsonl).

## What's in it

| Package / file | Ticket | What it shows |
|---|---|---|
| `retry` | 5.2.4, 6.3 | Error categories, bounded exponential backoff with full jitter, capped Retry-After, idempotency-aware retries, deadline, interrupt propagation, injectable sleeper |
| `geometry` | 5.2.2 | Canonical normalized coordinates, inch/pixel/point/normalized input, rotation, clamp-with-note recovery, explicit error reasons |
| `layout` | 5.2.3 | Text fitting with real font metrics (AWT) or deterministic fixed advance; no truncation; overflow warnings |
| `validation` | 6.4, 6.6 | Signature + structure validation for PDF/PNG/DOCX/JSON; stage → validate → atomic no-clobber publish |
| `cli` | 6.1 | `Main` (runnable JAR): argument, config, filesystem, limit and credential checks before any paid call; resume via checkpoints; exit-code contract tested by launching the JAR |
| `config` | 6.5 | Precedence CLI > env > file > defaults; secrets only from env; `Secret` never prints; unknown settings rejected; https enforced; config fingerprint |
| `core` | 6.6–6.8 | Private run workspace; size/page/block/character limits; checkpoints keyed by input + config + output hashes; translation cache so a resume doesn't pay twice |
| `vision` + `vision/segmenter.py` | vision stage | Python stamp/signature detection (mask, cleaned page, JSON) and a Java runner with timeout, exit-code mapping and output validation |
| `reporting` | 6.2 | JSON-lines run log with runId, credential redaction, processing report (schema in `../templates/`) |
| `translation` | 5.2.5 | Placeholder/URL/email protection for DeepL XML tag handling; block-level translation validation |
| `provider` | 6.3 | DeepL `/v2/translate` client (batching, 456, Retry-After) and Azure prebuilt-layout submit/poll client |
| `pipeline` | architecture | Azure → canonical model mapper (table dedupe, reading order) and a reference pipeline that records all gates |
| `docx` | 5.2.6 | DOCX assembly with fitted sizes, declared fonts, merged cells, header/footer parts and PAGE fields; structural inspector and human-readable diff |
| `scripts/visual_diff.py` | 5.2.7 | Render DOCX → PNG, baseline, compare with thresholds, blank-page and clipping checks, diff images |
| `src/test/resources/` | 5.2.5, 5.2.7 | Synthetic fixture (HTML source + PDF) with header, placeholders, merged row and expanding text; Azure/DeepL mocks; expected extraction and structure; reviewed visual baseline. Regenerate fixtures with `fixtures/make_fixtures.py` |

## Ground rules it follows
- Unit tests need no network, credentials or renderer. Stub servers bind `127.0.0.1:0`.
- No test sleeps; time and randomness are injected.
- Nothing is reported as passed that wasn't checked (the reference pipeline records the visual gate as SKIPPED).
- The Azure mock is synthetic, shaped after the documented response. Re-record from a live call before trusting provider details.
