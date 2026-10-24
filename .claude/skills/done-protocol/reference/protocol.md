# DONE protocol logic for the UI

**The on-chain program is the source of truth.** Everything here is the default for when the program/IDL doesn't say otherwise. If the IDL has a status enum, a commitment layout or an instruction order, use that and update this file; never make the UI "agree" with itself instead of the chain.

---

## 1. Milestone state machine

```
PENDING ──submit_evidence (worker)──▶ EVIDENCE_SUBMITTED ──verify (sponsor/verifier)──▶ VERIFIED ──release (sponsor)──▶ RELEASED
                                          │
                                          └──reject (sponsor/verifier, if the program has it)──▶ PENDING
```

```ts
export type MilestoneStatus = "PENDING" | "EVIDENCE_SUBMITTED" | "VERIFIED" | "RELEASED";
export type Role = "sponsor" | "worker" | "verifier" | "viewer";

export function roleOf(wallet: string | null, a: { sponsor: string; worker: string; verifier?: string }): Role {
  if (!wallet) return "viewer";
  if (wallet === a.sponsor) return "sponsor";
  if (wallet === a.worker) return "worker";
  if (a.verifier && wallet === a.verifier) return "verifier";
  return "viewer";
}

export type Action = "submitEvidence" | "verify" | "release";

/** Actions this wallet may take on milestone `index`. Empty array → show status only, no button. */
export function allowedActions(role: Role, status: MilestoneStatus, index: number, firstOpenIndex: number): Action[] {
  if (index !== firstOpenIndex) return [];            // sequential; drop this line if the program allows parallel
  switch (status) {
    case "PENDING": return role === "worker" ? ["submitEvidence"] : [];
    case "EVIDENCE_SUBMITTED": return role === "sponsor" || role === "verifier" ? ["verify"] : [];
    case "VERIFIED": return role === "sponsor" ? ["release"] : [];
    case "RELEASED": return [];
  }
}

export const firstOpenIndex = (ms: { status: MilestoneStatus }[]) => {
  const i = ms.findIndex((m) => m.status !== "RELEASED");
  return i === -1 ? ms.length : i;
};
```

A sponsor and worker that are the same wallet (testing) get the union of both roles' actions: compute `roleOf` for each role field, not with `else if`, in that case.

## 2. Agreement status

Read it from the account if it has a status field. Otherwise derive:

| Condition | Status |
|---|---|
| escrow balance 0 and no milestone moved | `DRAFT` |
| funded, every milestone `PENDING` | `FUNDED` |
| funded, some milestone beyond `PENDING`, not all `RELEASED` | `ACTIVE` |
| every milestone `RELEASED` | `COMPLETED` |

---

## 3. USDC amounts

USDC has **6 decimals** (check `mint.decimals`; don't hard-code if you can read it). Store and do math in `bigint` base units. No `Number`, `parseFloat`, `toFixed` on money.

```ts
export const USDC_DECIMALS = 6;
const SCALE = 10n ** BigInt(USDC_DECIMALS);

/** "1,250.5" → 1250500000n. Throws on anything that isn't a plain non-negative decimal with ≤ 6 places. */
export function parseUsdc(input: string): bigint {
  const s = input.trim().replace(/,/g, "");
  if (!/^\d+(\.\d{0,6})?$/.test(s)) throw new Error("Invalid USDC amount");
  const [whole, frac = ""] = s.split(".");
  return BigInt(whole) * SCALE + BigInt(frac.padEnd(USDC_DECIMALS, "0"));
}

/** 1250500000n → "1,250.50". Always at least 2 decimals, up to 6, no trailing zeros past 2. */
export function formatUsdc(base: bigint): string {
  const neg = base < 0n;
  const abs = neg ? -base : base;
  const whole = (abs / SCALE).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  let frac = (abs % SCALE).toString().padStart(USDC_DECIMALS, "0").replace(/0+$/, "");
  if (frac.length < 2) frac = frac.padEnd(2, "0");
  return `${neg ? "-" : ""}${whole}.${frac}`;
}

export const budgetRemaining = (total: bigint, milestones: bigint[]) =>
  milestones.reduce((r, m) => r - m, total);   // must be exactly 0n to submit
```

Tests to keep with it: `parseUsdc("0.000001") === 1n`, `parseUsdc("1.") === 1_000_000n`, `parseUsdc("1.0000001")` throws, `parseUsdc("-1")` throws, `formatUsdc(1n) === "0.000001"`, `formatUsdc(1_250_500_000n) === "1,250.50"`, round-trip for random values.

---

## 4. Addresses and hashes

**Base58 public key:**

```ts
import { PublicKey } from "@solana/web3.js";
const B58 = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
export function parseWallet(s: string): PublicKey | null {
  const t = s.trim();
  if (!B58.test(t)) return null;
  try {
    const k = new PublicKey(t);
    return PublicKey.isOnCurve(k.toBytes()) ? k : null;   // wallet, not a PDA; drop this check if workers may be multisig vaults
  } catch { return null; }
}
```

Inline field states: empty (neutral), invalid (`border-red-500/40` + "Not a Solana address"), valid (`border-emerald-500/40` + truncated key). Also reject the sponsor's own address as worker unless test mode is on.

**Canonical commitment (DoD) hash.** Deterministic JSON → UTF-8 → SHA-256 → lowercase hex. Same input on any machine = same hash.

```ts
type Json = string | number | boolean | null | Json[] | { [k: string]: Json };

/** Sorted keys, no whitespace, strings NFC-normalised, integers only (money goes in as base-unit strings). */
export function canonicalJson(v: Json): string {
  if (v === null || typeof v === "boolean") return JSON.stringify(v);
  if (typeof v === "number") {
    if (!Number.isSafeInteger(v)) throw new Error("Only safe integers in commitments; encode amounts as strings");
    return String(v);
  }
  if (typeof v === "string") return JSON.stringify(v.normalize("NFC"));
  if (Array.isArray(v)) return `[${v.map(canonicalJson).join(",")}]`;
  return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k.normalize("NFC"))}:${canonicalJson(v[k])}`).join(",")}}`;
}

export async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function commitmentPayload(m: {
  title: string; amount: bigint; verificationMode: string; dod: string[];
}): Json {
  return {
    v: 1,
    title: m.title.trim(),
    amount: m.amount.toString(),
    verification_mode: m.verificationMode,
    dod: m.dod.map((d) => d.trim()).filter(Boolean),   // order is meaningful; don't sort
  };
}
// preview and submit both call: sha256Hex(canonicalJson(commitmentPayload(m)))
```

If the program stores 32 raw bytes, convert the hex to `Uint8Array` at the instruction boundary only. Debounce the live preview (~150 ms); show `—` while a field is invalid instead of hashing junk.

**Evidence hash:** same encoder over `{ v: 1, type, url, notes }`. If the proof is a file, hash the file bytes (`crypto.subtle.digest` on the `ArrayBuffer`) and put that hex in the payload as `file_sha256`.

---

## 5. Transaction lifecycle

```ts
export type TxState =
  | { s: "idle" }
  | { s: "signing" }                                     // wallet popup is open (the wallet's UI, not ours)
  | { s: "sending"; sig: string }                        // signature exists, broadcast in flight
  | { s: "confirming"; sig: string; level: "processed" | "confirmed" }
  | { s: "finalized"; sig: string }
  | { s: "failed"; sig?: string; reason: string };       // reason: decoded program error or "Wallet rejected"

export async function runTx(
  conn: import("@solana/web3.js").Connection,
  send: () => Promise<string>,                          // wallet-adapter sendTransaction → signature
  set: (t: TxState) => void,
) {
  set({ s: "signing" });
  let sig: string;
  try { sig = await send(); } catch (e) { return set({ s: "failed", reason: walletError(e) }); }
  set({ s: "sending", sig });
  const { blockhash, lastValidBlockHeight } = await conn.getLatestBlockhash();
  try {
    const res = await conn.confirmTransaction({ signature: sig, blockhash, lastValidBlockHeight }, "confirmed");
    if (res.value.err) return set({ s: "failed", sig, reason: programError(res.value.err) });
    set({ s: "confirming", sig, level: "confirmed" });
    await conn.confirmTransaction({ signature: sig, blockhash, lastValidBlockHeight }, "finalized");
    set({ s: "finalized", sig });
  } catch {
    set({ s: "failed", sig, reason: "Not confirmed in time. Check explorer." });   // blockhash expired; may still land
  }
}
```

Use the same blockhash the transaction was built with when you have it; the `getLatestBlockhash` above is the fallback. `walletError` maps `WalletSignTransactionError`/user rejection → `"Wallet rejected"`; `programError` maps custom error codes to their IDL names.

Timeline UI (inside the inspector panel), one row per step with a dot: `Sign` → `Send` → `Confirmed` → `Finalized`. Signature shows from `sending` on, linked to `https://explorer.solana.com/tx/<sig>?cluster=devnet` (cluster from settings; omit the param on mainnet). Refetch the agreement account on `confirmed`; enable the next action only after the refetch shows the new status.

---

## 6. Mock mode

- Toggle in `/settings`, persisted in `localStorage` (`done.mock = "1"`), default **off**.
- A `MockAdapter` implements the same interface as the chain client: same functions, same return types, in-memory state seeded from a fixtures file.
- Mock signatures start with `MOCK-` and render as plain mono text, never as an explorer link.
- `MOCK` badge in the top bar on every page while it's on. Screenshots or demos from mock mode must not be presented as devnet results.
- "Reset local state" clears every `done.*` key and reloads.
