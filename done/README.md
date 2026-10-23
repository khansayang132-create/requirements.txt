# DONE Protocol app

Web app for DONE: USDC escrow for verifiable work (agreements → milestones → evidence → verification → release).
Built with the [`done-protocol` skill](../.claude/skills/done-protocol/SKILL.md). Vite + React 18 + TypeScript + Tailwind 4, hash routing, so `dist/` runs from any static host.

## Status

| Part | State |
|---|---|
| All 7 pages, inspector sidebar/drawer, tx timeline | IMPLEMENTED, VERIFIED in headless Chromium at 390 px and 1440 px |
| Mock chain adapter (`src/lib/store.ts`): roles, sequential milestones, budget sum, balances | IMPLEMENTED, VERIFIED (`test/logic.test.ts`) |
| USDC bigint math, canonical commitment + evidence hashes | IMPLEMENTED, VERIFIED |
| Real chain mode | BLOCKED: no DONE program deployed. With mock mode off, every action fails with `ProgramNotConfigured`. Set `PROGRAM_ID` and add an adapter with the same functions once the program and IDL exist. |
| Real wallets (Phantom etc.) | NOT IMPLEMENTED: the wallet panel offers three mock wallets (Sponsor, Worker, Verifier). |

## Commands

```
npm ci
npm run dev         # http://localhost:5173
npm test            # vitest: money, hashes, roles, full mock lifecycle
npm run typecheck
npm run lint:ui     # the skill's rule linter over src/
npm run build       # dist/
```
