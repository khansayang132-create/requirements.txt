// App state + the mock chain adapter.
// There is no deployed DONE program yet, so mock mode is the only working mode. Chain mode exists
// to show that honestly: every action fails with ProgramNotConfigured instead of pretending.
import { Keypair } from "@solana/web3.js";
import { useSyncExternalStore } from "react";
import type { Agreement, Milestone, VerificationMode } from "./protocol";
import { agreementPayload, evidencePayload, hashOf, type Evidence } from "./hash";
import { parseUsdc } from "./usdc";

export const PROGRAM_ID: string | null = null; // set when a DONE program is deployed
export const USDC_MINT_DEVNET = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU";
export type Cluster = "devnet" | "mainnet-beta";

export class ProgramNotConfigured extends Error {
  constructor() { super("No DONE program configured. Turn on Mock mode in Settings."); }
}

// Deterministic demo wallets: real, valid ed25519 keys, so address checks behave like on chain.
const idKey = (n: number) => Keypair.fromSeed(new Uint8Array(32).fill(n)).publicKey.toBase58();
export const IDENTITIES = [
  { name: "Sponsor", key: idKey(1) },
  { name: "Worker", key: idKey(2) },
  { name: "Verifier", key: idKey(3) },
] as const;

export interface State {
  mock: boolean;
  cluster: Cluster;
  wallet: string | null;
  agreements: Agreement[];
  balances: Record<string, bigint>;
}

// ---------- tiny external store ----------
const KEY = "done.state";
let state: State = load();
const listeners = new Set<() => void>();

function set(next: State) {
  state = next;
  save(next);
  listeners.forEach((l) => l());
}
export const getState = () => state;
export function useStore<T>(pick: (s: State) => T): T {
  return useSyncExternalStore((l) => (listeners.add(l), () => listeners.delete(l)), () => pick(state));
}

// bigint-safe persistence. Storage can be missing (private mode, previews); the app still works.
function save(s: State) {
  try { localStorage.setItem(KEY, JSON.stringify(s, (_k, v) => (typeof v === "bigint" ? `${v}n` : v))); } catch { /* ignore */ }
}
function load(): State {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw, (_k, v) => (typeof v === "string" && /^-?\d+n$/.test(v) ? BigInt(v.slice(0, -1)) : v));
  } catch { /* fall through to seed */ }
  return seed();
}

export function resetState() {
  try { Object.keys(localStorage).filter((k) => k.startsWith("done.")).forEach((k) => localStorage.removeItem(k)); } catch { /* ignore */ }
  set(seed());
}
export const setMock = (mock: boolean) => set({ ...state, mock });
export const setCluster = (cluster: Cluster) => set({ ...state, cluster });
export const connect = (key: string | null) => set({ ...state, wallet: key });

// ---------- tx lifecycle ----------
export type TxState =
  | { s: "idle" }
  | { s: "signing" }
  | { s: "sending"; sig: string }
  | { s: "confirming"; sig: string }
  | { s: "finalized"; sig: string }
  | { s: "failed"; sig?: string; reason: string };

export const isMockSig = (sig: string) => sig.startsWith("MOCK-");
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const mockSig = () => {
  const b = crypto.getRandomValues(new Uint8Array(24));
  return "MOCK-" + [...b].map((x) => "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"[x % 58]).join("");
};

/** Runs one mock transaction through sign → send → confirm → finalize. `apply` mutates state at "confirmed". */
async function mockTx(onState: (t: TxState) => void, apply: (sig: string) => void, delays = [700, 450, 700, 900]): Promise<string> {
  if (!state.mock) throw new ProgramNotConfigured();
  onState({ s: "signing" });
  await wait(delays[0]);
  const sig = mockSig();
  onState({ s: "sending", sig });
  await wait(delays[1]);
  apply(sig);
  onState({ s: "confirming", sig });
  await wait(delays[2]);
  await wait(delays[3]);
  onState({ s: "finalized", sig });
  return sig;
}

/** Wraps an action so any error ends as a "failed" state with a short reason, never an exception in the UI. */
export async function runTx(onState: (t: TxState) => void, action: (on: (t: TxState) => void) => Promise<unknown>) {
  try {
    await action(onState);
  } catch (e) {
    onState({ s: "failed", reason: e instanceof Error ? e.message : "Transaction failed" });
  }
}

function updateAgreement(id: string, f: (a: Agreement) => Agreement) {
  set({ ...state, agreements: state.agreements.map((a) => (a.id === id ? f(a) : a)) });
}
function updateMilestone(id: string, i: number, f: (m: Milestone) => Milestone) {
  updateAgreement(id, (a) => ({ ...a, milestones: a.milestones.map((m, j) => (j === i ? f(m) : m)) }));
}
function requireWallet() {
  if (!state.mock) throw new ProgramNotConfigured();
  if (!state.wallet) throw new Error("Connect a wallet first.");
  return state.wallet;
}

/** The checks the on-chain program would make: right signer, right status, milestones in order. */
function requireStep(id: string, i: number, status: Milestone["status"], who: ("sponsor" | "worker" | "verifier")[]) {
  const wallet = requireWallet();
  const a = state.agreements.find((x) => x.id === id);
  if (!a) throw new Error("Agreement not found.");
  const m = a.milestones[i];
  if (!m || m.status !== status) throw new Error("Milestone is not in the right state.");
  if (a.milestones.slice(0, i).some((x) => x.status !== "RELEASED")) throw new Error("Earlier milestones come first.");
  if (!who.some((r) => a[r] === wallet)) throw new Error("This wallet can't sign this step.");
  return a;
}

// ---------- actions ----------
export interface NewAgreement {
  title: string; scope: string; worker: string; verifier?: string; budget: bigint;
  milestones: { title: string; amount: bigint; verificationMode: VerificationMode; dod: string[] }[];
}

export async function createAgreement(input: NewAgreement, onState: (t: TxState) => void): Promise<string> {
  const sponsor = requireWallet();
  const total = input.milestones.reduce((s, m) => s + m.amount, 0n);
  if (total !== input.budget) throw new Error("Milestones must add up to the budget.");
  if ((state.balances[sponsor] ?? 0n) < input.budget) throw new Error("Insufficient USDC balance.");
  const commitment = await hashOf(agreementPayload(input));
  const id = crypto.randomUUID().slice(0, 8);
  await mockTx(onState, (sig) => set({
    ...state,
    balances: { ...state.balances, [sponsor]: (state.balances[sponsor] ?? 0n) - input.budget },
    agreements: [{
      id, title: input.title.trim(), scope: input.scope.trim(), sponsor, worker: input.worker, verifier: input.verifier,
      budget: input.budget, funded: true, commitment, createdAt: Date.now(), initSig: sig,
      milestones: input.milestones.map((m) => ({ ...m, title: m.title.trim(), status: "PENDING" as const })),
    }, ...state.agreements],
  }));
  return id;
}

export async function submitEvidence(id: string, i: number, ev: Evidence, onState: (t: TxState) => void) {
  requireStep(id, i, "PENDING", ["worker"]);
  const hash = await hashOf(evidencePayload(ev));
  await mockTx(onState, (sig) => updateMilestone(id, i, (m) => ({ ...m, status: "EVIDENCE_SUBMITTED", evidence: { ...ev, hash, sig, at: Date.now() } })));
}

export async function verifyMilestone(id: string, i: number, onState: (t: TxState) => void) {
  requireStep(id, i, "EVIDENCE_SUBMITTED", ["sponsor", "verifier"]);
  await mockTx(onState, (sig) => updateMilestone(id, i, (m) => ({ ...m, status: "VERIFIED", verifySig: sig })));
}

export async function releaseMilestone(id: string, i: number, onState: (t: TxState) => void) {
  const a = requireStep(id, i, "VERIFIED", ["sponsor"]);
  const amount = a.milestones[i].amount;
  await mockTx(onState, (sig) => {
    set({ ...state, balances: { ...state.balances, [a.worker]: (state.balances[a.worker] ?? 0n) + amount } });
    updateMilestone(id, i, (m) => ({ ...m, status: "RELEASED", releaseSig: sig, releasedAt: Date.now() }));
  });
}

// ---------- seed ----------
function seed(): State {
  const [S, W, V] = IDENTITIES.map((x) => x.key);
  const u = parseUsdc;
  const now = Date.now();
  const sig = (n: number) => `MOCK-seed${n}`;
  const ms = (title: string, amount: string, mode: VerificationMode, dod: string[], status: Milestone["status"], n: number, extra: Partial<Milestone> = {}): Milestone => ({
    title, amount: u(amount), verificationMode: mode, dod, status,
    ...(status !== "PENDING" ? { evidence: { type: "Link", url: `https://github.com/example/pr/${n}`, notes: "Ready for review", hash: `MOCK-evidence-${n}`, sig: sig(n * 10), at: now - n * 3.6e6 } } : {}),
    ...(status === "VERIFIED" || status === "RELEASED" ? { verifySig: sig(n * 10 + 1) } : {}),
    ...(status === "RELEASED" ? { releaseSig: sig(n * 10 + 2), releasedAt: now - n * 3.6e6 } : {}),
    ...extra,
  });
  const agreements: Agreement[] = [
    {
      id: "a1f09c2e", title: "Landing page rebuild", scope: "Responsive marketing site, 4 pages.", sponsor: S, worker: W,
      budget: u("4000"), funded: true, commitment: "MOCK-commitment-a1f09c2e", createdAt: now - 864e6, initSig: sig(1),
      milestones: [
        ms("Wireframes", "800", "Sponsor review", ["3 page layouts", "Mobile + desktop"], "RELEASED", 1),
        ms("Design system", "1200", "Sponsor review", ["Tokens file", "8 components"], "RELEASED", 2),
        ms("Build pages", "1500", "Third-party verifier", ["Lighthouse ≥ 90", "Deployed preview"], "EVIDENCE_SUBMITTED", 3),
        ms("Launch", "500", "Sponsor review", ["DNS live", "Analytics on"], "PENDING", 4),
      ],
      verifier: V,
    },
    {
      id: "b7d3e410", title: "Indexer API", scope: "REST API over program accounts.", sponsor: S, worker: W,
      budget: u("2500"), funded: true, commitment: "MOCK-commitment-b7d3e410", createdAt: now - 432e6, initSig: sig(2),
      milestones: [
        ms("Schema + ingest", "1000", "Automated check", ["CI green", "Backfill script"], "VERIFIED", 5),
        ms("Query endpoints", "1500", "Sponsor review", ["OpenAPI spec", "p95 < 200 ms"], "PENDING", 6),
      ],
    },
    {
      id: "c2a8f5b1", title: "Audit fixes", scope: "Resolve findings H-1 to M-4.", sponsor: S, worker: W,
      budget: u("1200"), funded: true, commitment: "MOCK-commitment-c2a8f5b1", createdAt: now - 1728e6, initSig: sig(3),
      milestones: [ms("All findings fixed", "1200", "Third-party verifier", ["Auditor sign-off"], "RELEASED", 7)],
      verifier: V,
    },
  ];
  return { mock: true, cluster: "devnet", wallet: null, agreements, balances: { [S]: u("50000"), [W]: u("3200"), [V]: 0n } };
}
