---
name: taikatranslator-engineering
description: Professional engineering playbook for TaikaTranslator Enterprise (Java/Maven PDF → OCR/extraction → DeepL translation → DOCX reconstruction, with a Python vision helper). Use when asked to plan, write, test, harden, review or report on TaikaTranslator work, write or update SpecKit tickets (TSK-x.y), set up its CI, or decide whether a ticket can be marked PASS.
---

# TaikaTranslator engineering

A working method, not a code dump. TaikaTranslator's source is **not in this repo**; it lives in the owner's own project. Everything here applies to that codebase once it is available (uploaded ZIP, attached repo or local folder). This skill does not touch `bot.py` or `apex/`.

Files next to this one:
- [`ticket-template.md`](./ticket-template.md): the SpecKit format every ticket uses.
- [`backlog.md`](./backlog.md): Phases 5–7, the acceptance principle, the quality metrics and the execution order.

## 0. First move, every time

1. **Get the real code.** No source, no changes. Ask for `pom.xml`, `src/`, `vision/`, `walkthrough.md`, `GRAPH_REPORT.md` (if any), existing tests and config templates. Tell the owner to leave out `.env`, keys, passwords and private documents.
2. **Inspect before moving anything.** If the project has a knowledge graph (Graphify: `graphify query` / `path` / `explain`), use it first for callers, dependents and test coverage; fall back to Grep/Read. Record the baseline: Java version in `maven-compiler-plugin`, the JAR name `mvn package` really produces, test framework, current packages, which interfaces already exist (extraction, translation, vision, retry).
3. **Run what already exists** (`mvn -q clean test`, `python -m compileall -q vision`) and write down the real result before changing anything. That is the baseline evidence.
4. Pick the next ticket from the execution order in `backlog.md`. Foundation before features: a reliable, verifiable pipeline beats a bigger one nobody can check.

## 1. The acceptance principle

A zero exit code from `java -jar` proves only that the process ended. A translated document is accepted only when these six are checked **separately**, each with its own observable result:

| # | Gate | Evidence |
|---|---|---|
| 1 | Execution | Pipeline finished; every stage reported an outcome |
| 2 | Content | Expected source text extracted; required blocks translated |
| 3 | Structure | Paragraph order, table rows/columns, element counts preserved |
| 4 | Visual fidelity | Rendered pages compared to baseline within thresholds |
| 5 | Artifact integrity | DOCX reopens in Apache POI; files have valid signatures |
| 6 | Auditability | Inputs, config (no secrets), versions and commit recorded so the run can be reproduced |

Never merge gates. Passing an XML/structure test does not prove visual alignment; a structure pass does not prove the translation is complete.

## 2. Engineering rules

- **Interfaces at every external edge.** Azure Document Intelligence, DeepL and the vision process are injected through interfaces so unit tests run with fakes and no credentials or network.
- **Unit vs integration.** Surefire runs `*Test` (no network, no keys). Failsafe runs `*IT` (real or stub services). Live cloud tests are tagged and opt-in; provider behaviour, availability and price vary.
- **Deterministic tests.** Inject the clock and the sleep/delay strategy; never `Thread.sleep` real backoff in a test. Use `@TempDir`; tests clean up after themselves. Same input → same output on every run.
- **Canonical coordinates.** Internally use normalized page coordinates in `[0,1]` with a documented origin and rotation rule; convert to pixels/points/EMU only at named boundaries. If an existing interface uses another system, keep it and add a tested adapter. Never silently change what a field means.
- **Invalid geometry is loud.** Zero-size, negative, out-of-page or missing bounds produce a validation error or a documented recovery action, never a quiet made-up position.
- **Text fitting.** Measure with font metrics, available width, line spacing and paragraph constraints; a character-count ratio is only a fallback estimate. Font size is never zero, negative, NaN or infinite; it respects configured min/max; text is never silently truncated; a block that cannot fit records a layout warning. Spanish and other expanding languages are the normal case, not the edge case.
- **Retries are a policy, not a loop.** Bounded attempts; retry transport errors, 429 (honour `Retry-After`) and 5xx; fail fast on other 4xx; exponential backoff with jitter and a max interval; propagate `InterruptedException` (restore the interrupt flag). Only retry non-idempotent calls when the provider's API makes it safe. For Azure's async analysis, submission, polling and result retrieval each get their own policy.
- **Artifacts are validated, then moved.** Write to a temp location, check existence, non-zero size, file signature (`%PDF`, PNG header, ZIP/DOCX), JSON structure, DOCX reopen and required content, then atomic-move into the final directory where the filesystem allows. On failure keep the diagnostics. A filename existing is not success.
- **CLI fails early.** Validate arguments, input file type, output-dir permissions and config before any expensive call. Handle paths with spaces. Meaningful exit codes, usage text on bad input, and never overwrite an existing result silently.
- **Structured logs with a `runId`.** Log stage, event, duration, retry count, error category, pages, extracted and translated block counts and validation results. Never log API keys, auth headers or document content by default.
- **Fixtures are synthetic or licensed.** Mock Azure/DeepL responses are stored as files under `src/test/resources/mocks/`; expected extraction and expected translation live in `expected/`, separate from the code.
- **Small steps.** Introduce the proposed components (`DocumentClassifier`, `DocumentValidator`, `TranslationValidator`, `ArtifactValidator`, `ProcessingReportWriter`, `ProcessingCheckpointStore`) one at a time when a ticket needs them, not as empty abstractions up front. The target layout in `backlog.md` is a direction, not a move order.
- **Java version agrees everywhere.** Compiler release, CI JDK and production runtime must match; pin it.

## 3. Definition of Done

A ticket is PASS only when it has all of:

- An implementation, or a written reason no code change is needed.
- The relevant tests passing on the **current** commit.
- Every acceptance-criteria box checked with what was observed.
- Evidence: command, environment, result, report location (Surefire/Failsafe XML, logs, the generated artifact).
- Updated docs when behaviour or config changed.
- No credentials or sensitive document content anywhere in the change, logs or report.

Status values: `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED` (name the dependency), `PASS`, `FAIL` (verification ran and a criterion failed). Code written is not PASS. Evidence from an older commit is not PASS.

## 4. Reporting

Report like `apex/STATUS.md`: what you ran, what passed (with counts), what failed, what is blocked and why, and the next action. Keep verified results and untested claims in separate lists. Don't promise 100% OCR accuracy or perfect layout; define supported document classes and show each meets its documented thresholds.

## 5. Verification commands

Linux CI and Windows PowerShell use the same commands:

```
python --version
python -m pip --version
python -m compileall -q vision
mvn clean verify
```

`compileall` proves only that the Python parses; model-backed vision needs its own integration test. Check the real JAR name in `pom.xml` before writing any `java -jar target/<name>.jar --input ... --output-dir ...` instruction.
