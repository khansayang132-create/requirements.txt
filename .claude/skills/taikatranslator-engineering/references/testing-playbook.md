# Testing playbook

## The layers

| Layer | Runs in | Naming | Needs | Proves |
|---|---|---|---|---|
| Unit | `mvn test` (Surefire) | `*Test` | nothing: no network, keys, renderer | Logic: geometry, fitting, retry policy, validators, CLI parsing |
| Stub integration | `mvn verify` (Failsafe) | `*IT` | a local `127.0.0.1` HTTP stub | Real HTTP behaviour: status codes, headers, Retry-After, batching, polling |
| End-to-end fixture | `mvn verify` (Failsafe) | `*IT` | fixture files + stubs | Every stage and every gate on a known document |
| Process level | `mvn verify` (Failsafe, after `package`) | `*IT` | the built JAR + stubs | Exit codes, stdout/stderr contract, resume, nothing leaks, as a user runs it (`CliMainIT`) |
| Cross-language | `mvn verify` | `*IT` | python3 + deps | Java/Python contract: timeout, exit codes, output validation (`VisionRunnerIT`); `VISION_REQUIRED=1` makes a missing runtime fail instead of skip in CI |
| Visual | separate job/script | `visual_diff.py` | LibreOffice, poppler, fonts | Rendered pages match a baseline |
| Live | opt-in, `-Dgroups=live` | `@Tag("live")` | real keys | The provider still behaves as the mocks say (on that date) |

A higher layer never replaces a lower one, and their results are reported separately.

## Making tests deterministic

| Source of flakiness | Fix (in the kit) |
|---|---|
| Real sleeping in backoff | Inject `Sleeper`; tests record waits (`RetryExecutorTest`) |
| Wall-clock deadlines | Inject `Clock`; `FakeTime` advances when it "sleeps" (`ProviderClientsIT`) |
| Random jitter | Inject a `DoubleSupplier`; tests pass a constant |
| Installed fonts | `FixedAdvanceMeasurer` in tests; AWT only in a test that checks proportionality, not exact numbers |
| Shared output folders | `@TempDir` per test; evidence copied to `target/` only on purpose |
| Port collisions | Stub servers bind port 0 and report the real port |
| Floating point | Compare geometry with a tolerance; exact `equals` on doubles failed in the kit's first run |
| ZIP/XML ordering in DOCX | Compare structure (`DocxInspector` + `StructureDiff`), never bytes |
| Interrupt flag leaking between tests | `@AfterEach` clears it (`Thread.interrupted()`) |

A skipped test is not a passed test. Wherever a test skips for a missing tool (Python, LibreOffice, keys), CI sets a flag that turns the skip into a failure, so a broken CI image can't go green silently.

Run the suite twice in a row before calling it reproducible: `mvn -q verify && mvn -q verify`.

## Writing good assertions

- **Assert behaviour named in the acceptance criteria**, one criterion per test where practical, and name the test after it (`permanentErrorsAreNotRetried`, `neverOverwritesSilently`).
- **Failure messages explain themselves.** `StructureDiff` prints "element 4: cell [1,0] "Traduccion", expected "Traducción"". A bare `expected true` costs an engineer ten minutes.
- **Test the negative path for every guard.** Each validator has a test that feeds it bad input and checks the specific reason.
- **Check counts as well as content:** number of HTTP requests (retries really happened, or really didn't), number of batches, number of blocks.
- **Check what must NOT happen:** key not in the log, document text not in the log, no file published after a failure, original result untouched without `--overwrite`.

## Fixtures

- Synthetic or licensed only. No customer documents, ever; not even "just for a local test".
- One generator script owns the fixture (`make_fixtures.py`): the input document, the mocked provider responses and the expected results all come from the same table, so they can't drift apart.
- Expected results live in `src/test/resources/expected/` and are readable JSON a reviewer can check by eye.
- Each fixture exercises named cases on purpose: the kit's service agreement has a title, a heading, placeholders, an email, a URL at the end of a sentence, a table whose cells Azure also lists as paragraphs, a box slightly outside the page, and a phrase that grows 2.5× in Spanish.
- Mark synthetic provider mocks as synthetic. Re-record from a live call before trusting provider-specific details.

Recommended next fixtures for the real project: a rotated page (`/Rotate 90`), an image-only scanned page (pixel units), a landscape page, a two-page document with a table split across pages, merged table cells, a page with a stamp/signature figure, right-to-left text if supported.

## Stub servers

`StubServer` (JDK `com.sun.net.httpserver`, no extra dependency) takes a handler `(request, callNumber) → reply`. Script sequences by call number: `n == 1 → 429 with Retry-After: 2`, then success. Assert on `stub.requests` (method, path, headers, body). Use WireMock instead if the project already has it; the principle is the same.

## Structure versus visual

| Question | Structure test | Visual test |
|---|---|---|
| Are all paragraphs there, in order? | ✔ | — |
| Is the table 3 × 2 with the right cell text? | ✔ | — |
| Is the font size what the fitter chose? | ✔ | — |
| Does the text overflow its box when rendered? | ✘ | ✔ |
| Is anything clipped at the page edge? | ✘ | ✔ |
| Is there an unexpected blank page? | ✘ | ✔ |
| Is it readable? | ✘ | partly (and a human look) |

Both pass, or the document isn't accepted.

## Visual regression workflow

```
python scripts/visual_diff.py baseline out/doc.docx --baseline src/test/resources/baselines/doc   # once, reviewed by a human
python scripts/visual_diff.py compare  out/doc.docx --baseline src/test/resources/baselines/doc --out target/visual
```
- Baseline PNGs and `manifest.json` (tool versions, DPI) are committed. Changing a baseline is a reviewed change with a reason.
- Create and compare baselines on the **same CI image**. Different LibreOffice or font versions shift glyphs; the script warns when versions differ.
- Thresholds: `--threshold` (fraction of changed pixels per page, default 0.2%), `--pixel-tolerance` (grey-level noise ignored, default 32), `--edge-margin` (clipping band, default 4 px).
- Exit 3 = renderer missing, reported as NOT RUN. It is never a pass.
- Look at `diff-<n>.png` yourself. Red marks changed pixels over a faded copy of the new page.
