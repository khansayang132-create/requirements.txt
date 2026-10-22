# Human-Facing Output — ADHD-Friendly Shape for the Final Chat Message

Canonical rule for the **[chat summary]** — the one message a human reads when a workflow ends.
Every workflow's last step points here; the workflow files deliberately do not restate it.

**Source.** Adapted from the community skill **`i-have-adhd`**
(`ayghri/i-have-adhd:skills/i-have-adhd/SKILL.md` · MIT · 42,350★, verified via the GitHub API on
2026-09-12). Upstream is a session-wide output style toggled by `/i-have-adhd`; HarnessFlow applies
its rules to one place only — the final human-facing message — and keeps the harness's own
constraints where the two conflict (upstream's own "when a rule fights the harness" clause).

## Scope

- **Governs:** the [chat summary] of every workflow in every mode — the bullet-point summary of
  changes (code / debug / refactor / exec / pr), the printed final answers (query), the printed
  final correctness report, the loop outcome, the initialize completion summary — and, in
  Plan-Only mode (`_lib/approval_gate.md` Mode 1), the printed plan, since that is the run's final
  message.
- **Does not govern:** anything a machine or a later run reads — `repo_info/` log entries
  (`update_logs.md`, `past_Q&A.md`, `past_Correctness_Check.md`, `known_issues.md`), the
  [run record], overview files, subagent prompts and returned results, and every intermediate
  artifact. Those keep their own formats. Shape is presentation only: it never limits analysis,
  verification, or what the run records.

## Shape (in this order)

1. **Outcome first.** Line 1 states what now works, or the answer, or the yes/no result the
   workflow asks for — concrete, verifiable ("Login now works with magic links. Try: `npm run dev`,
   open `/login`."). No preamble ("I'll…", "Looking at…", "Great question"), no restated plan.
2. **What changed / the answer body.** Numbered when the reader must act in order, bulleted
   otherwise. One bounded item per line; the first sentence of each item carries the fact.
   Keep the visible set to **≤ 5 items per group** — rank by relevance, group the rest under one
   heading, and fold detail into the log entry the run already wrote (name that file once).
   Never drop a relevant item to fit; move it, and say where it went.
3. **Gaps, in matter-of-fact tone.** If anything failed or was skipped: cause → effect → fix, in
   one line each ("Test fails at `auth.spec.ts:42`: expected 200, got 401. Cause: … Fix: …").
   Never "uh oh" / "there seems to be a problem".
4. **Tangents last and separate.** Unrelated findings (stale dependency, adjacent bug) go under
   one line — `Separately:` — after the main result, never woven into it. At most two; the rest
   are already in `known_issues.md` if they mattered.
5. **`Next:` — exactly one action** the reader can do in under two minutes: a command to run, a
   file to open, a decision to make. If the run is fully done with nothing pending, `Next:` names
   the verification the reader would run to see the win. When the action takes longer, say how
   long in concrete units ("about 15 minutes; an afternoon if the fixture is missing"), never
   "some work".
6. **Wiki status line closes the message** (the harness-mandated one line from
   `_lib/harness_wiki.md`); `Next:` sits immediately before it.

## Rules the harness keeps over the upstream skill

- **No "want me to?"** — the run is autonomous (`_lib/approval_gate.md` Mode 2). A tangent is
  named, not offered; the reader asks for it in a new request if they want it.
- **Time estimates point at whoever executes** — a `Next:` estimate is the reader's time, not the
  agent's.
- **Destructive or outward-facing actions** never become the `Next:` line by default; they are
  stated as the decision the reader has to make (`_lib/safety_rules.md`).
- **Explain-mode override:** when the request itself asked to "explain" / "walk me through", the
  body runs as long as the topic needs, with headers to skim back; the outcome line, the ≤ 5
  working set per group, and the `Next:` line still apply.

## Pre-send check

Delete: any opening sentence that announces what you are about to do; any closing pleasantry
("hope this helps", "let me know"); any "by the way" woven into the result; any hedging adverb
that carries no real uncertainty; any idiom in place of the literal action. Then confirm: a reader
who sees only the first line and the `Next:` line knows **(a)** what just happened and **(b)**
what to do now. If yes, send.
