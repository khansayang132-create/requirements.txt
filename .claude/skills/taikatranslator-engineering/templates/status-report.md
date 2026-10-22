# Status report — <ticket or work item>

<!-- Same shape every time. Verified and unverified never share a list. -->

**Commit:** `<sha>` on `<branch>` · **Date:** <YYYY-MM-DD> · **Environment:** <OS, JDK, Maven, Python, LibreOffice>

## Verified (ran it, saw it pass)
| Check | Command | Result | Evidence |
|---|---|---|---|
| Unit tests | `mvn -B clean test` | 77 passed, 0 failed | `target/surefire-reports/` |
| … | … | … | … |

## Failed
| Check | What failed | Cause | Next action |
|---|---|---|---|

## Not verified (and why)
| Claim | Why not verified | What would verify it |
|---|---|---|
| Live DeepL translation | No API key in this environment (correct: tests must not need one) | `mvn verify -Dgroups=live` with `DEEPL_AUTH_KEY` set |

## Blocked
| Item | Blocked on | Owner |
|---|---|---|

## Tickets
| Ticket | Before | After | Evidence |
|---|---|---|---|
| TSK-5.2.1 | IN_PROGRESS | PASS | Surefire XML at `<path>`, commit `<sha>` |

## Next
1. <single most important next action>
