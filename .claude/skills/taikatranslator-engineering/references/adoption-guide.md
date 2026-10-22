# Adopting the starter kit into the real TaikaTranslator repo

The kit proves the patterns work. The real project decides names, packages and libraries. Port behaviour plus tests, not files wholesale.

## 0. Baseline first (no code changes)
```
git status && git log --oneline -5
mvn -v && java -version && python --version
mvn -B clean verify 2>&1 | tee baseline-verify.log       # record the real starting point, even if red
python -m compileall -q vision
```
Write down: Java release in the pom, JUnit version (4 or 5?), Surefire/Failsafe present?, the artifact name `mvn package` produces, which HTTP client the code uses (SDK, OkHttp, `java.net.http`), the logging stack, and where the extraction, translation, retry and DOCX code live. If the repo has a Graphify knowledge graph, `graphify query` callers/callees/tests for each of those before reading files.

## 1. Mapping table (fill it in, put it in the PR description)

| Kit class | Ticket | Real-project counterpart | Action |
|---|---|---|---|
| `retry.RetryExecutor`, `RetryPolicy`, `ErrorCategory`, `Sleeper` | 5.2.4 / 6.3 | existing `RetryExecutor`? | Keep the real class name/API; port the missing behaviour (categories, idempotency, Retry-After cap, injectable sleeper) + the tests |
| `geometry.*` | 5.2.2 | layout normalizer? | Adapter if the real system isn't normalized; port tests |
| `layout.TextFitter` + measurers | 5.2.3 | text-expansion code | Port; use the real DOCX font in `AwtTextMeasurer` |
| `validation.ArtifactValidator`, `AtomicPublisher` | 6.4 / 6.6 | none, probably | Add |
| `cli.CliOptions`, `ExitCode`, `Main` | 6.1 | `Main`/CLI parser (picocli?) | Port the checks and the check order into the existing entry point; keep its flag names; port `CliMainIT` (launches the real JAR) |
| `config.*` | 6.5 | config loading | Port precedence, secret typing, unknown-key rejection and startup provider checks |
| `core.*` | 6.6–6.8 | temp handling, resume | Add workspace, limits, checkpoints, translation cache |
| `vision.VisionRunner`, `vision/segmenter.py` | vision | existing `vision/segmenter.py`? | Keep the real segmenter; adopt the runner contract (paths only, timeout, exit codes, validated JSON + PNG outputs) and its tests |
| `reporting.*` | 6.2 / report | logging config | MDC + JSON encoder if SLF4J exists; report writer as is |
| `translation.*` | 5.2.5 / TranslationValidator | DeepL wrapper | Add protection + validation around the existing call |
| `provider.DeepLTranslator`, `AzureLayoutClient` | 6.3 | SDK clients? | If an SDK is used, keep it; apply the same retry/idempotency rules and port the stub tests |
| `pipeline.AzureLayoutMapper`, `CanonicalDocument` | architecture | existing model | Compare; port the table-dedupe and recovery recording |
| `docx.DocxInspector`, `StructureDiff` | 5.2.6 | none | Add as test utilities (main or test scope) |
| `scripts/visual_diff.py` | 5.2.7 | none | Add under `scripts/`, baselines under `src/test/resources/baselines/` |
| fixtures + `make_fixtures.py` | 5.2.5 | none | Copy, then add fixtures for the project's real document classes |
| `templates/ci.yml`, `verify.sh`, `verify.ps1` | 7.1 | existing CI? | Merge into existing workflows; don't run two CIs |

## 2. Order of PRs (small, each green)
1. Test harness only (TSK-5.2.1): JUnit 5, Surefire/Failsafe split, `live` tag exclusion, enforcer. No behaviour change. Evidence: before/after `mvn verify`.
2. Geometry + tests (5.2.2). 3. Text fitting + tests (5.2.3). 4. Retry + tests (5.2.4).
5. Fixture + E2E with mocks (5.2.5) and DOCX structure checks (5.2.6).
6. Visual job (5.2.7). 7. Phase 6 tickets one per PR. 8. CI (7.1) — or earlier, as soon as step 1 lands.

## 3. Rules while porting
- Keep public method names and field meanings that other code depends on; add, don't rename.
- Every ported behaviour arrives with its tests in the same PR.
- Run the real suite after each step; a red test you didn't cause gets reported, not "fixed" by deleting it.
- Copy the kit's tests and adapt them to the real classes. They encode the acceptance criteria.
- Update the ticket's verification record with the real commit, command and result.
