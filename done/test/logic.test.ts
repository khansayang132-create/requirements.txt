import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { agreementPayload, canonicalJson, evidencePayload, hashOf } from "../src/lib/hash";
import { agreementStatus, allowedActions, rolesOf } from "../src/lib/protocol";
import * as store from "../src/lib/store";
import { budgetRemaining, formatUsdc, parseUsdc } from "../src/lib/usdc";
import { parseWallet } from "../src/lib/wallet";

const [S, W, V] = store.IDENTITIES.map((i) => i.key);

describe("usdc", () => {
  it("parses and formats exactly", () => {
    expect(parseUsdc("0.000001")).toBe(1n);
    expect(parseUsdc("1.")).toBe(1_000_000n);
    expect(parseUsdc("1,250.5")).toBe(1_250_500_000n);
    for (const bad of ["1.0000001", "-1", "", "abc", "1e3"]) expect(() => parseUsdc(bad)).toThrow();
    expect(formatUsdc(1n)).toBe("0.000001");
    expect(formatUsdc(1_250_500_000n)).toBe("1,250.50");
    expect(formatUsdc(0n)).toBe("0.00");
    expect(budgetRemaining(parseUsdc("100"), [parseUsdc("60"), parseUsdc("40")])).toBe(0n);
  });
  it("round-trips", () => {
    for (let i = 0; i < 2000; i++) {
      const v = BigInt(Math.floor(Math.random() * 1e15));
      expect(parseUsdc(formatUsdc(v))).toBe(v);
    }
  });
});

describe("hash", () => {
  it("is independent of key order and unicode form", () => {
    expect(canonicalJson({ b: 1, a: ["é".normalize("NFD")] })).toBe(canonicalJson({ a: ["é"], b: 1 }));
    expect(() => canonicalJson({ x: 1.5 })).toThrow();
  });
  it("milestone order changes the commitment", async () => {
    const m = (t: string) => ({ title: t, amount: 1n, verificationMode: "Sponsor review", dod: ["x"] });
    const base = { worker: W, budget: 2n, scope: "" };
    expect(await hashOf(agreementPayload({ ...base, milestones: [m("a"), m("b")] })))
      .not.toBe(await hashOf(agreementPayload({ ...base, milestones: [m("b"), m("a")] })));
  });
});

describe("wallet", () => {
  it("accepts wallets, rejects junk", () => {
    expect(parseWallet(S)?.toBase58()).toBe(S);
    expect(parseWallet("not-a-key")).toBeNull();
    expect(parseWallet("0OIl" + S.slice(4))).toBeNull();
  });
});

describe("store lifecycle (mock adapter)", () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] }); store.resetState(); });
  afterEach(() => vi.useRealTimers());
  // Hashing (crypto.subtle) resolves off the fake clock, so keep yielding and advancing until the tx is done.
  const settle = async <T>(p: Promise<T>) => {
    let done = false;
    p.then(() => (done = true), () => (done = true));
    while (!done) { await new Promise((r) => setImmediate(r)); await vi.advanceTimersByTimeAsync(250); }
    return p;
  };
  const states: string[] = [];
  const on = (t: store.TxState) => states.push(t.s);

  it("creates, then walks one milestone through every step with the right signers", async () => {
    store.connect(S);
    const input = {
      title: "Test", scope: "s", worker: W, verifier: V, budget: parseUsdc("100"),
      milestones: [{ title: "M1", amount: parseUsdc("100"), verificationMode: "Sponsor review" as const, dod: ["a", "b"] }],
    };
    const before = store.getState().balances[S];
    const id = await settle(store.createAgreement(input, on));
    expect(states.slice(-4)).toEqual(["signing", "sending", "confirming", "finalized"]);
    let a = store.getState().agreements.find((x) => x.id === id)!;
    // The commitment shown in the form preview is the one stored.
    expect(a.commitment).toBe(await hashOf(agreementPayload(input)));
    expect(store.getState().balances[S]).toBe(before - parseUsdc("100"));
    expect(agreementStatus(a)).toBe("FUNDED");

    // Sponsor can't submit evidence; worker can.
    await expect(store.submitEvidence(id, 0, { type: "Link", url: "https://x.dev", notes: "" }, on)).rejects.toThrow(/can't sign/);
    store.connect(W);
    expect(allowedActions(rolesOf(W, a), a, 0)).toEqual(["submitEvidence"]);
    const ev = { type: "Link", url: "https://x.dev", notes: "n" };
    await settle(store.submitEvidence(id, 0, ev, on));
    a = store.getState().agreements.find((x) => x.id === id)!;
    expect(a.milestones[0].evidence?.hash).toBe(await hashOf(evidencePayload(ev)));

    // Worker can't verify; verifier can; only sponsor releases.
    await expect(store.verifyMilestone(id, 0, on)).rejects.toThrow(/can't sign/);
    store.connect(V);
    await settle(store.verifyMilestone(id, 0, on));
    await expect(store.releaseMilestone(id, 0, on)).rejects.toThrow(/can't sign/);
    store.connect(S);
    const wBefore = store.getState().balances[W];
    await settle(store.releaseMilestone(id, 0, on));
    a = store.getState().agreements.find((x) => x.id === id)!;
    expect(a.milestones[0].status).toBe("RELEASED");
    expect(agreementStatus(a)).toBe("COMPLETED");
    expect(store.getState().balances[W]).toBe(wBefore + parseUsdc("100"));
    expect(a.milestones[0].releaseSig).toMatch(/^MOCK-/);
  });

  it("rejects a budget that milestones don't add up to, and out-of-order steps", async () => {
    store.connect(S);
    await expect(store.createAgreement({
      title: "x", scope: "", worker: W, budget: parseUsdc("10"),
      milestones: [{ title: "m", amount: parseUsdc("9"), verificationMode: "Sponsor review", dod: ["a"] }],
    }, on)).rejects.toThrow(/add up/);
    store.connect(W);
    // Seed agreement b7d3e410: milestone 0 VERIFIED, so milestone 1 can't take evidence yet.
    await expect(store.submitEvidence("b7d3e410", 1, { type: "Link", url: "https://x.dev", notes: "" }, on)).rejects.toThrow(/Earlier milestones/);
  });

  it("fails honestly with no program when mock mode is off", async () => {
    store.connect(W);
    store.setMock(false);
    await expect(store.submitEvidence("b7d3e410", 1, { type: "Link", url: "https://x.dev", notes: "" }, on)).rejects.toThrow(store.ProgramNotConfigured);
  });
});
