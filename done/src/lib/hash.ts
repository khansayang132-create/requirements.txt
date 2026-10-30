// Canonical JSON + SHA-256: the same input gives the same hash on any machine.
export type Json = string | number | boolean | null | Json[] | { [k: string]: Json };

/** Sorted keys, no whitespace, strings NFC-normalised, safe integers only (money goes in as strings). */
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

export interface MilestoneTerms { title: string; amount: bigint; verificationMode: string; dod: string[] }

export function commitmentPayload(m: MilestoneTerms): Json {
  return {
    v: 1,
    title: m.title.trim(),
    amount: m.amount.toString(),
    verification_mode: m.verificationMode,
    dod: m.dod.map((d) => d.trim()).filter(Boolean), // order is meaningful; don't sort
  };
}

/** One hash over the whole agreement: worker, budget, scope and every milestone's terms, in order. */
export function agreementPayload(a: { worker: string; budget: bigint; scope: string; milestones: MilestoneTerms[] }): Json {
  return { v: 1, worker: a.worker, budget: a.budget.toString(), scope: a.scope.trim(), milestones: a.milestones.map(commitmentPayload) };
}

export interface Evidence { type: string; url: string; notes: string }
export const evidencePayload = (e: Evidence): Json => ({ v: 1, type: e.type, url: e.url.trim(), notes: e.notes.trim() });

export const hashOf = (payload: Json) => sha256Hex(canonicalJson(payload));
