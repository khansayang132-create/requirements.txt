---
name: done-protocol
description: Build, extend or review the DONE Protocol web app (Solana USDC escrow for verifiable work: agreements, milestones, evidence, verification, settlement). Pitch-black + violet design system, no modals (right sidebar on desktop, bottom drawer on mobile), button-first UI. Use for any DONE page, component, wallet/tx flow, DoD commitment hash, USDC amount handling, or a UI review of DONE code.
---

# DONE Protocol UI

Production rules for the DONE web app. **This file is the source of truth**; the original `UI.md` brief is folded in here with its contradictions resolved (§9). Two reference files carry the copy-paste code:

- [`reference/components.md`](./reference/components.md): tokens, `Button`, `Card`, `StatusBadge`, `InspectorPanel` (sidebar ⇄ drawer), `TopDrawer`, shells, nav.
- [`reference/protocol.md`](./reference/protocol.md): state machines, role → action matrix, USDC math, Base58, DoD commitment hash, transaction lifecycle, mock mode.

And one tool: [`scripts/ui_lint.py`](./scripts/ui_lint.py) mechanically enforces the hard rules. Run it before you call any DONE UI work finished.

---

## 0. Workflow (follow in order)

1. **Read the target project first.** Find the framework (default: Next.js App Router + Tailwind + `@solana/wallet-adapter-react` + `@solana/web3.js`), the Tailwind version (v4 `@theme` vs v3 `tailwind.config`), and the **on-chain program's IDL / account layouts**. The program wins over this file on anything about data: status names, commitment format, decimals, instruction order.
2. **Install tokens once** (`reference/components.md` §1). Never hand-type a hex color in a component.
3. **Build from the primitives** in `reference/components.md`. Don't create a second button, badge, or panel style.
4. **Wire data through `reference/protocol.md`.** Amounts are `bigint` base units; hashes come from the canonical function; tx state comes from the lifecycle reducer.
5. **Verify** (§8): `python3 <skill>/scripts/ui_lint.py <src-dir>` passes with zero errors, typecheck and build pass, and you looked at every changed screen at 390 px and 1440 px wide.
6. **Report like a status file:** what you ran, what passed, what is NOT VERIFIED (e.g. "devnet tx not sent: no funded wallet in sandbox").

---

## 1. Hard rules (a violation is a bug)

| # | Rule | Enforced by |
|---|---|---|
| H1 | **Dark only.** Base `#000000`, surfaces `#0d0d0f` / `#141416`, nested border `#202024`, divider `#26262a`. No `dark:` variants, no light surfaces (`bg-white`, `bg-neutral-50…200`). | lint `LIGHT`, `HEX` |
| H2 | **Violet is the only accent.** Primary actions, brand mark, active nav, toggles, focus rings: `violet-400/500/600/700`. No `purple-*` / `fuchsia-*`. | lint `ACCENT` |
| H3 | **No sharp corners.** Cards/panels `rounded-2xl`, buttons/inputs `rounded-xl`, badges `rounded-lg`, drawers `rounded-3xl` (`rounded-t-3xl` bottom). `rounded-full` only for dots, avatars, progress tracks. Never `rounded-none/sm/md` or bare `rounded`. | lint `RADIUS` |
| H4 | **No modals, popups, toasts or browser dialogs.** Inspection = `InspectorPanel` (right sidebar `w-[440px]` ≥ md, bottom drawer `max-h-[85vh]` < md). Global/tx alerts = `TopDrawer`. Destructive confirms = inline two-step button, not `confirm()`. | lint `MODAL`, `TOAST` |
| H5 | **Money is never a float.** USDC = 6 decimals, stored and computed as `bigint` base units, parsed with `parseUsdc`, shown with `formatUsdc`. Milestone amounts must sum exactly to the budget. | lint `FLOAT` (warn) + review |
| H6 | **Nothing fake looks real.** A tx hash appears only after the wallet returns a signature; "Confirmed" only after the RPC says so. Mock mode shows a `MOCK` badge in the top bar and never links mock IDs to an explorer. No placeholder metrics: unknown → `—`. | review |
| H7 | **Hashes are reproducible.** The DoD commitment and evidence hash use the canonical encoder in `reference/protocol.md` (or the program's own format). The preview and the submitted value come from the same function call. | review |
| H8 | **Accessible.** Body text ≥ `neutral-400` on black (`neutral-500` fails AA at 4.4:1; use it only for ≥ 18 px or disabled). Every control has a visible `focus-visible` violet ring, touch targets ≥ 44 px, drawers trap focus, close on `Esc`, and return focus. `motion-reduce:` disables slides. | review |

Suppress a lint hit only with a reason on the same line: `{/* ui-lint-ignore: avatar image needs rounded-md */}`.

---

## 2. Design tokens (summary; full code in components.md §1)

| Token | Value | Tailwind |
|---|---|---|
| `bg` | `#000000` | `bg-black` |
| `surface` | `#0d0d0f` | `bg-[#0d0d0f]` → `bg-surface` |
| `surface-2` | `#141416` | `bg-surface-2` |
| `line-soft` | `#202024` | `border-line-soft` |
| `line` | `#26262a` | `border-line` |
| text | primary `neutral-100`, secondary `neutral-400`, muted `neutral-500` (≥ 18 px only) | |
| accent | `violet-600` fill, `violet-700` hover, `violet-400` text/icon, `violet-500/30` border | |
| type | Inter / system sans; numbers, keys, hashes: `font-mono tabular-nums` | |
| spacing | page `p-4` mobile, `p-8` desktop, `max-w-6xl` content; card `p-5`, nested `p-4`; grid gaps `gap-4`/`gap-6` | |
| motion | 200 ms `ease-out` transform only, `motion-reduce:transition-none` | |

Primary button text is white on `violet-600` (5.7:1). Hover goes **darker** (`violet-700`), never lighter: white on `violet-500` is 4.2:1 and fails AA.

---

## 3. Shell

**Desktop (≥ md):** fixed left nav `w-64` (`bg-surface border-r border-line`; logo, 5 nav items `rounded-xl`, active = `bg-violet-600/10 text-violet-300`, cluster pill at the bottom) · top bar `h-14` (protocol status dot, cluster, RPC ping ms, USDC balance, wallet pill, `MOCK` badge when on) · main `md:pl-64`, `max-w-6xl p-8` · `InspectorPanel` slides from the right, `w-[440px]`, and main content gets `lg:pr-[440px]` while it is open so nothing hides under it.

**Mobile (< md):** sticky top header (logo + wallet button) · content `p-4 pb-24` · fixed bottom nav `h-16 rounded-t-2xl bg-surface border-t border-line pb-[env(safe-area-inset-bottom)]`, 5 icon tabs with labels (`Overview`, `Agreements`, `Sponsor`, `Worker`, `Settings`), active tab violet · `InspectorPanel` becomes a bottom drawer with a drag handle (swipe down > 80 px closes).

**Inspector state lives in the URL** (`?inspect=milestone:2&panel=evidence`) so back closes it, refresh restores it, and links can be shared.

---

## 4. Pages

| Route | Must contain | Primary action |
|---|---|---|
| `/` | Hero: *"Programmable settlement for verifiable work."* + one subline. 3 metric cards: Total Escrowed, Total Settled, Active Milestones (real chain data or `—`). Recent settlements list: agreement, milestone, worker key (truncated mono), amount, `VERIFIED`/`RELEASED` badge, tx hash → explorer. | `Create Agreement` · secondary `Explore Protocol State` |
| `/agreements` | Segmented filter `All · Sponsoring · Assigned · Completed` (in URL `?f=`). Cards: title, worker key, status badge, step track `2 / 4 settled`, escrowed vs released. Whole card is a link. Empty state: one line + one button. | `New Agreement` |
| `/agreements/new` | Sponsor card (worker address with live Base58 check, total budget, scope ≤ 280 chars). Milestone builder (title, amount, DoD checklist items, verification mode pills). **Live remaining-budget counter** (must hit exactly 0.00). Live commitment hash preview (mono, copy button). Sticky action bar. | `Initialize & Fund Escrow` (disabled until valid; label says why) |
| `/agreements/[id]` | Summary header: locked USDC, sponsor + worker keys (copy), status. Vertical milestone pipeline; each card shows status, title, amount, verification mode, and **only the actions §5 allows for the connected wallet**. Clicking a card opens the inspector. | per role (§5) |
| `/sponsor` | Escrow health (locked, released, pending review) + Review queue (`EVIDENCE_SUBMITTED`, oldest first). | `Review` → inspector panel B |
| `/worker` | Earnings (released, verified-unreleased, pending) + actionable list (`PENDING` assigned to me). | `Submit Evidence` → panel A |
| `/settings` | Cluster pills (Devnet default; Mainnet requires a typed confirm inline), Program ID + USDC mint (mono, copy, explorer), Mock mode toggle, Reset local state (destructive two-step). | — |

Inspector panels: **A Evidence** (proof type pills, URL, notes, live evidence hash, `Submit Proof`), **B Verification** (each DoD item as a checkbox; button enabled only when all are checked; `Confirm & Verify`), **C Settlement** (payout amount, recipient, `Release USDC`, then the tx timeline + explorer link). Each panel shows the tx lifecycle (protocol.md §5) inline; it does not close until the tx is final or the user dismisses a failure.

---

## 5. Status colors and who can act

| Status | Badge | Actor → action |
|---|---|---|
| `DRAFT` | neutral | sponsor → `Fund Escrow` |
| `FUNDED`, `ACTIVE` | amber | — |
| `COMPLETED` | violet | — |
| `PENDING` | neutral | worker → `Submit Evidence` |
| `EVIDENCE_SUBMITTED` | yellow | sponsor/verifier → `Run Verification` |
| `VERIFIED` | emerald | sponsor → `Release USDC` |
| `RELEASED` | indigo | anyone → view tx |

Exact classes are in `StatusBadge` (components.md §4). A wallet that isn't the right role sees the status, not a disabled button. Milestones are sequential: only the earliest non-`RELEASED` milestone is actionable unless the program allows parallel milestones. Details and the derivation of agreement status: protocol.md §1–2.

---

## 6. Copy rules (aggressive text reduction)

- Buttons: verb first, ≤ 3 words (`Submit Proof`, `Release USDC`). Disabled buttons say why in ≤ 4 words (`Budget off by 12.50`).
- No paragraph longer than one sentence anywhere in the app. Help text lives in a `title`/`aria-describedby` hint, not a block.
- Numbers over words: show `2 / 4 settled`, not "Two of four milestones have been settled".
- Errors: what failed + the one next step (`Wallet rejected. Try again.`). Decode program errors to their IDL name; never dump a raw log.
- Keys and hashes: `AbC1…xYz9` (4 + 4) in mono with a copy button; full value in `title`.

---

## 7. Interaction rules

- Every action button has four visual states: idle, pending (spinner + "Confirm in wallet…"), success, error. No double submit: disabled while pending.
- Optimistic UI is **not** allowed for chain state. Refetch the account after `confirmed`.
- Quick-increment buttons for amounts (`+10`, `+100`, `Max remaining`) next to every USDC input.
- Segmented pills, not `<select>`, for anything with ≤ 5 options.
- Keyboard: `Esc` closes the inspector, `[`/`]` move to the previous/next milestone while it is open.
- Loading: skeletons shaped like the final card (`animate-pulse bg-surface-2 rounded-2xl`), never a full-page spinner.

---

## 8. Definition of done for any DONE UI change

- [ ] `python3 .claude/skills/done-protocol/scripts/ui_lint.py <src>` exits 0 (errors fixed, warnings each justified).
- [ ] `tsc --noEmit` and the production build pass.
- [ ] Checked at 390 px and 1440 px: no horizontal scroll, nothing under the bottom nav or the open sidebar.
- [ ] Keyboard-only pass: tab order sane, focus visible, `Esc` closes the inspector and focus returns to the card.
- [ ] Every amount path uses `parseUsdc`/`formatUsdc`; budget sum check present on `/agreements/new`.
- [ ] Commitment hash preview equals the submitted hash (same function call, asserted in a test).
- [ ] Mock mode visibly labelled; no mock ID links to an explorer.
- [ ] Status report lists anything NOT VERIFIED (devnet send, wallet signing in CI, etc.).

---

## 9. Conflicts in the original brief, and how they were resolved

| Brief said | Also said | Resolved to | Why |
|---|---|---|---|
| Primary button `bg-white text-black` | "All primary actions … use violet" | `bg-violet-600 text-white hover:bg-violet-700` | Accent rule is the design principle; white also clashes with pitch-black. |
| Desktop sidebar `w-96` (diagram) | `w-[440px]` (spec text, component) | `w-[440px]` | Component spec is the more specific one. |
| Badges `rounded-xl` (principles) | Badges `rounded-lg` (components) | `rounded-lg` | Component spec is the more specific one; xl looks like a button at badge size. |
| "State badges use violet" | Badge palette amber/emerald/indigo | Status colors as §5; violet only for `COMPLETED` | Status must be distinguishable at a glance. |
| `COMPLETED` status | No color given | violet | Terminal success, on brand. |
| "Zero floating popups" | Top drawer for alerts | Top drawer allowed; toasts and modals are not | Drawers are anchored to an edge, not floating. |

If the owner overrules a row, change it here and in the matching component; nowhere else.
