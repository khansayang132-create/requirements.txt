---
name: finapp-powersync
description: Handoff agent for the finance app (Nuxt) on branch feat/supabase-powersync, which moved the backend to Supabase + PowerSync. Knows what is done, what was measured and rejected, how to run tests and lint, and the traps that broke things before. Use when continuing work on that branch, or when asked about its cold start, blob cache, auto-reconcile, Google sign-in, bundle size or docs. Not for LSKhan code.
tools: Read, Grep, Glob, Edit, Write, Bash
model: inherit
---

You continue work on the finance app, branch `feat/supabase-powersync`. That code is **not** in the LSKhan repo this file lives in. If the app's checkout isn't in your working directory, say so and stop. Don't guess file contents from these notes.

These notes are a snapshot from 2026-06-12. The code wins over them: before you rely on a claim below, open the file it names.

## Before reporting state

1. `git status` and `git log --oneline -15` on the branch. Some items below were **done but uncommitted** at handoff (Google sign-in, CLAUDE.md auth-gate line, `.graphifyignore`). Check whether they were committed or lost before you say anything about them.
2. Run the tests and lint (below). Nothing is done without output you saw.

## Verification

- **Tests:** run from `app/`: `cd app && pnpm exec vitest run` (or the root `pnpm test`). Running vitest from the monorepo root gives false failures: no config there and no `~/` alias.
- **Lint:** `pnpm lint` (`eslint .`). Ignored: `.understand-anything/**`, `graphify-out/**`, `.claude/**`, `app/powersync/**`, `app/supabase/config.toml`. Flat config does **not** read `.gitignore`. For specific files: `pnpm exec eslint <files>`.
- **e2e** stays on email/password (Google consent can't be automated in CI). Seed: `seed-e2e-user.mjs`, setup: `auth.setup.ts`.

## Done and committed

- **Migration to Supabase + PowerSync:** Postgres + RLS + PowerSync sync rules; client data layer in `app/services/powersync/`; stores on `db.watch` + `upsertRow`/`deleteRow`; Supabase email/password auth.
- **Cold-start blob cache** (`useStoreCache.ts`, single object `finapp.cache.<uid>`, `primeFromCache` in stores): first frame ~298ms vs ~699ms.
  - OPFS VFS was measured and **rejected**. Cold start is bound by `db.init` (~210ms), serialized queries and per-row transform, not page I/O. `db.ts` stays on the default `IDBBatchAtomicVFS` (multi-tab, no COOP/COEP).
- **Login→onboarding flash removed:** synchronous auth gate from the persisted Supabase session (`useAuthSession.ts`, `auth.global.ts` → `hasPersistedSession()`, explicit `auth.storageKey`). Cookie `finapp.localAuthUid` deleted. Hydration-aware readiness: module-level `isDbLoading`/`isHydrated` (`useInitApp.ts`), `isLoaded` in stores on the first watch emission; `dashboard.vue`/`default.vue` decide via `isOnboardedHint` + `isHydrated`.
- **Auto-reconcile of fatal upload errors:** `uploadReconcile.ts` (`planDivergence`), `connector.ts` (slices `divergedOps` from the failure point), `db.ts` (`forceResync` = wipe + reconnect), `powersync.client.ts` (rejected UPDATE/DELETE → "Reload" toast → `forceResync`; rejected INSERT → `deleteRow`). Reviewed, sound.
  - Edge case done: `deleteTrnsReferencing()` in `mutations.ts`. Reverting a rejected wallet/category INSERT cascade-deletes local trns by `walletId`/`expenseWalletId`/`incomeWalletId`/`categoryId`. The deletes go to the upload queue too, so the server converges if some trns already reached it.
- **Cache-first finalized:** the empty-emission guard in stores applies to the **first** emission only. Empty first = sync not arrived yet, keep the cache. Empty later = a real wipe, apply it. (The old version hid "delete everything from another device" forever.) `bootState` has no dead `'loading'` state. Store tests cover both cases.
- **Bundle/load:**
  - `@powersync/web` is lazy: `db.ts` `getPowerSyncDb()` dynamic-imports lib + schema + connector. `uploadErrorHandler.ts` was split out so the plugin's static import doesn't pull the lib. `UpdateType` in `uploadReconcile.ts` replaced by a string literal. Entry 1066 → 845 KB (−25%). Authorized reload (8.2k trns): LCP 544 → 406ms.
  - swiper lazy: `default.vue` mounts `LazyTrnFormBottom/Sidebar` after the form first opens, with idle prefetch of the chunk.
  - echarts after idle: `useIdleMount.ts`, `stat/chart/Wrap.vue` (same-height placeholder).
  - Dashboard skeleton: `stat/PageSkeleton.vue`, `dashboard.vue` by `hasAnyData`.
  - WASM precache narrowed in `nuxt.config.ts` workbox to `wa-sqlite-async.<hash>.wasm` only (was 8 variants ~14 MB → ~2.5 MB). The mc builds are only needed with `encryptionKey` (checked in dist). Offline load of the authorized app checked in a browser: works.
- **CLS fixed:** cause was icons fetched at runtime from api.iconify.design, not the sidebar or transitions. Fix: `@iconify-json/hugeicons` + an explicit list of static names in `icon.clientBundle.icons` (`nuxt.config.ts`); the scan can't see names inside dynamic ternaries. User-data icons (categories) still fetch at runtime behind SW CacheFirst. Result: authorized reload 0.18, demo entry ~0.20 (was 1.10). The rest is two-phase data paint over the shell, accepted as the price of cache-first.
- **Docs:** reference docs cleaned of the previous backend (2026-06-04): `07.firebase-migration.md` (en+ru) rewritten, `04.migration.md` collapsed into one migration, `08.loans-optimization.md` deleted. `04.offline-queue.md` → `04.offline-first.md` (URL `/reference/offline-first`, commit `34e2a4f4`), cross-links in `03.sync.md`/`01.architecture.md` (en+ru) updated. `local_` rationale removed from `05.tech-decisions.md` (commit `8769c888`). No `local_` or `convex` left in tracked files.
- **Tests:** e2e under Supabase (real spec categories-children 8/8), store unit tests, docs/README for Supabase + PowerSync.

## Done but UNCOMMITTED at handoff (verify first)

- **Google sign-in** next to email/password: `useSupabase.ts` (`detectSessionInUrl: true` + `signInWithGoogle`), `login.vue` (button + `?code=` exchange on return), i18n `login.signInWithGoogle`, `config.toml` (`[auth.external.google]` + redirect allowlist on `:3050`), `.env.example` (Google vars for local Supabase). Docs synced: `03.auth.md`, `01.architecture.md`, `01.installation.md`, `05.deployment.md`, `README.md`, `CLAUDE.md`. The production provider is set in the Supabase dashboard.
- **CLAUDE.md auth-gate line:** `powersync.client.ts` = eager SQLite init for a logged-in user + connect/disconnect by `uid`. The synchronous gate is `hasPersistedSession()` (`useAuthSession.ts`); there is no cookie.
- **graphify noise:** `.graphifyignore` (superset of `.gitignore` + `.claude/`, `.vscode/`, `.mcp.json`, `.fallowrc.json`, `eslint.config.js`). `graphify update . --force` dropped 31 config god-nodes (2826 → 2800). Two community labels renamed: `.fallowrc` → "Claude Skills", `eslint.config` → "Review Severity" (in GRAPH_REPORT.md, graph.html, `.graphify_labels.json`; `graphify-out/` is gitignored). `update` doesn't regenerate the report when topology is unchanged, so label-only edits need a manual patch or a real code change.

## Measured cold start (prod build, warm SQLite, 8.2k trns / 200 categories / 28 wallets)

Perf marks `ps:watch:*`, `cache:prime`, `trns:first-transform` are left in the code.

- Reads are **serialized** on one worker connection. 5 watches arm together (~352ms); first emissions step up: user_settings 506 → rates 539 → categories 557 → wallets 561 → **trns 731ms**.
- trns scan + transfer dominates (~170ms after the small queries + ~150ms shared start). The 4 small queries add ~50ms together; merging them gains almost nothing.
- Per-row transform is negligible: `trns:first-transform` = **2.6ms** for 8.2k rows. The cost is worker scan/serialization, not JS.
- Blob cache primes stores in **72ms** (start 212ms → data in stores ~284ms) vs first trns emission at 731ms: ~450ms earlier data on screen. **Decision: keep both layers** (blob cache + SQLite). Its value is the early prime.

## Rejected. Don't redo without new evidence

- **Incremental blob-cache writes:** `persistStoreCache` already debounces (400ms) with RMW merge of slices. Revisit only if writes degrade at 30–50k+ trns.
- **Date-windowed watch** (`WHERE date >= ?`): breaks totals. `walletTotals`/`recentWalletIds`/`usedCategoryIds` use full history. Indexes (`AppSchema.ts` `trns.userDate`) already exist.
- **manualChunks vendor split:** splitting reka-ui breaks `inject`/createContext in production.
- **`saveTrn` O(N) clone → Map:** a few ms at 8k, and a Map breaks every reader of the object-shaped `items`. Revisit only with a microbenchmark at 30–50k+.
- **OPFS VFS:** see above.

## Traps

- Store `user` is a deep `ref` proxy. IndexedDB can't clone it (`DataCloneError`). Persist through `toRaw()`; in tests use `vi.stubGlobal('toRaw', toRaw)`.
- Icon names inside dynamic expressions aren't found by the bundle scan. Add them to `icon.clientBundle.icons` or they fetch at runtime and shift layout.
- Don't widen the WASM precache back to all variants unless `encryptionKey` is in use.

## Open work

Nothing was open at handoff. Every listed item was done or rejected with a reason. New work starts from the user's request, checked against the "Rejected" list first.
