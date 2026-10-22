# Review checklist

Use it for your own change before pushing and for reviewing someone else's. Every "no" is a finding with a file and line.

## Correctness
- [ ] Does every new external call declare whether it's idempotent, and does the retry rule match?
- [ ] Are HTTP statuses mapped through `ErrorCategory` (429, 456, 5xx, 401/403, other 4xx)?
- [ ] Is `InterruptedException` rethrown with the interrupt flag restored, never swallowed or wrapped?
- [ ] Are coordinates converted only at boundaries, with units explicit in names (`widthPt`, `heightTwips`, `xNorm`)?
- [ ] Does any new geometry path reject NaN, zero-size and out-of-page input with a reason?
- [ ] Can any code path truncate translated text? (Search for `substring`, `limit`, `maxLength`.)
- [ ] Are block counts checked after translation (in == out, ids match)?
- [ ] Are placeholders restored from the original token list?

## Evidence and honesty
- [ ] Is every new acceptance criterion covered by a test whose name says what it checks?
- [ ] Is there a test for the failure path of every new guard?
- [ ] Do tests run without network and credentials (`mvn test`)?
- [ ] Is anything reported as passed/succeeded that wasn't actually checked?
- [ ] Do structure and visual results stay separate?
- [ ] Does the status report list what was not verified?

## Safety
- [ ] No key, token, auth header, SAS URL or document text in code, tests, logs, reports, fixtures or commit messages.
- [ ] Outputs staged and validated before publish; no silent overwrite.
- [ ] Temp files in a per-run directory, cleaned up, owner-only permissions.
- [ ] Limits enforced before upload (size, pages, characters).
- [ ] New dependencies pinned, needed, and from a known publisher.

## Maintainability
- [ ] Matches the surrounding code's style, naming and comment density.
- [ ] No abstraction added "for later". Each new interface has two implementations (real + test) or a stated reason.
- [ ] Config has a default, validation and a line in `docs/configuration.md`.
- [ ] Behaviour change reflected in docs (README, architecture, troubleshooting) and the CHANGELOG.

## Before merge
- [ ] `mvn -B clean verify` green on the branch head in CI, not just locally.
- [ ] Python checks green (`compileall`, `pytest`).
- [ ] Visual job green, or its NOT RUN reason stated.
- [ ] Ticket status and verification record updated with this commit's evidence.
