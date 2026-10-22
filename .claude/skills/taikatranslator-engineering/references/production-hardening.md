# Production hardening (Phase 6)

What "done" looks like for each Phase 6 ticket, with the kit's reference implementation where one exists.

## TSK-6.1 CLI validation (kit: `cli/CliOptions`, `cli/ExitCode`)
Order matters: parse → validate config → validate filesystem → **then** spend money.
- Required flags, known flags only, every flag's value present; `--help` prints usage with exit 2.
- Input exists, is a regular readable file, has a supported extension **and** matching magic bytes (`%PDF-`, PNG, JPEG `FF D8 FF`, TIFF `II*\0`/`MM\0*`).
- Output directory created if missing, must be a writable directory.
- Output name derived deterministically (`<input>.<LANG>.docx`); an existing result is refused unless `--overwrite` (exit 8).
- Language codes validated before any API call; ambiguous targets (`EN`, `PT`) rejected with the fix in the message.
- Paths with spaces: never split or concatenate path strings; use `Path`.
- Exit codes are a contract. Document them in the README and test that they're distinct.

## TSK-6.2 Structured logging (kit: `reporting/RunLog`, `reporting/Redactor`)
- One JSON object per line; fields: `timestamp` (UTC ISO-8601), `level`, `runId`, `stage`, `event`, plus numbers (`durationMs`, `retries`, `pages`, `blocks`, `translatedBlocks`, `warnings`).
- `runId` on every line. With SLF4J: `MDC.put("runId", id)` at start, `MDC.clear()` in `finally`, JSON encoder (e.g. logstash-logback-encoder).
- Allowed: counts, ids, durations, categories, file names, hashes. Not allowed by default: document text, translations, keys, auth headers, SAS URLs, full request bodies.
- `Redactor` is a safety net for strings you didn't write (exception messages, URLs). It is not permission to log secrets "because they'll be redacted".
- Test that a known key and a known document sentence never appear in the captured log (the end-to-end test does both).

## TSK-6.3 API reliability (kit: `retry/*`, `provider/*`)
Configuration, all with defaults and validated at startup:

| Setting | Suggested default |
|---|---|
| connect timeout | 10 s |
| request timeout (translate) | 30 s |
| request timeout (Azure submit, large file) | 120 s |
| max attempts | 4 |
| base / max backoff | 500 ms / 20 s |
| per-operation retry budget | 2 min |
| Azure poll interval (when no Retry-After) | 1–2 s |
| overall analysis deadline | 10 min |
| provider concurrency | 2–4 parallel requests, behind a semaphore |
| whole-job deadline | pages × per-page budget, capped |

Categories, not exceptions, drive decisions (`ErrorCategory`). Idempotency is declared per call site (`execute(op, idempotent, call)`): Azure submit `false`, Azure poll `true`, DeepL translate `true` (accepting possible double billing).

## TSK-6.4 Artifact validation (kit: `validation/ArtifactValidator`, `validation/AtomicPublisher`)
Stage → write → validate → publish:
1. `stage(target)` creates `.<name>.<random>.part` **in the target's directory**, so the publish is a same-filesystem rename.
2. Write the DOCX/JSON/PNG there.
3. `validate`: exists, non-empty, signature, then type-specific (DOCX reopens in POI with body content; PNG has an IHDR with non-zero size; JSON parses and has required fields).
4. `publish(staged, target, overwrite)`: without overwrite it hard-links (atomic create-if-absent; a rename would silently replace a file created in the meantime), with overwrite it does an atomic rename. Reports `NON_ATOMIC_FALLBACK` when the filesystem can't do better.
5. On failure: `discard(staged, keepForDiagnostics=true)` renames to `.failed` and the report says where.

## TSK-6.5 Configuration and secrets
- Sources in order: CLI flags > environment variables > config file > defaults. Print the effective config (redacted) at debug level.
- Secrets only from environment or a secret store; refuse a config file that contains a key field (fail with the field name, not the value).
- Validate at startup: endpoint is `https://` (allow `http://127.0.0.1` only in test profile), key non-blank, numbers in range, durations positive, language codes valid.
- A missing key for a stage that will run is a startup failure (exit 4), not a crash on page 37.
- `.env` gitignored; `.env.example` lists names with empty values.

## TSK-6.6 Temporary files
- One run directory: `Files.createTempDirectory("taika-" + runId)`, owner-only permissions on POSIX (`PosixFilePermissions.fromString("rwx------")`).
- Delete in `finally` unless `--keep-temp` or the run failed and diagnostics are kept; the report records which.
- Never `new File("/tmp/out.docx")`: predictable names are a race and a leak.
- Staged outputs go next to the destination (above), not in the temp dir.
- Test: after a successful run, the temp dir is gone; after a failed run with diagnostics, it is listed in the report.

## TSK-6.7 Limits
Enforce before upload: file size, page count, image pixel dimensions, total characters to translate (compare with DeepL `/v2/usage`), number of blocks, per-document deadline. Each limit is configurable, defaulted, and produces a specific error message and exit code. Decompression bombs: cap rendered image size before rasterising PDFs.

## TSK-6.8 Checkpoints
Persist after each stage: `{runId, inputSha256, configHash, stage, outputPath, outputSha256}`. On resume, a checkpoint is valid only if the input hash **and** config hash match and the stage output still exists with the same hash. Translation checkpoints at block granularity save the most money. Never resume across a changed target language or glossary.

## TSK-6.9 Metrics and benchmarks
Per run: duration per stage, pages/min, blocks, characters translated, retries, peak heap (`MemoryMXBean`), overflow count. Benchmark with JMH or a repeated fixture run; establish a baseline first (TSK-7.2), then set thresholds. Report medians and p95, not one run.

## TSK-6.10 Security and dependency audit
- `mvn org.owasp:dependency-check-maven:check` (needs NVD access; an NVD API key speeds it up) or GitHub Dependabot; triage every HIGH/CRITICAL.
- `pip-audit -r vision/requirements.txt` for the Python side.
- Pin versions (Maven properties, `requirements.txt` with `==`).
- Secret scan the history (`gitleaks detect` or GitHub secret scanning). A key that was ever committed is rotated, not just deleted.
- XML: POI parses DOCX with XXE protections; don't feed untrusted XML to a default `DocumentBuilderFactory`.
- Untrusted PDFs: run PDF parsing with limits (time, memory); keep the vision subprocess sandboxed with a timeout.
- `SECURITY.md` with a contact and supported versions.
