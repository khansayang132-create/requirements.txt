// Statuses, roles and who may act. Defaults from the done-protocol skill; a real program's IDL overrides them.
export type MilestoneStatus = "PENDING" | "EVIDENCE_SUBMITTED" | "VERIFIED" | "RELEASED";
export type AgreementStatus = "DRAFT" | "FUNDED" | "ACTIVE" | "COMPLETED";
export type Role = "sponsor" | "worker" | "verifier";
export type Action = "submitEvidence" | "verify" | "release";
export const VERIFICATION_MODES = ["Sponsor review", "Third-party verifier", "Automated check"] as const;
export type VerificationMode = (typeof VERIFICATION_MODES)[number];

export interface Milestone {
  title: string;
  amount: bigint;
  verificationMode: VerificationMode;
  dod: string[];
  status: MilestoneStatus;
  evidence?: { type: string; url: string; notes: string; hash: string; sig: string; at: number };
  verifySig?: string;
  releaseSig?: string;
  releasedAt?: number;
}

export interface Agreement {
  id: string;
  title: string;
  scope: string;
  sponsor: string;
  worker: string;
  verifier?: string;
  budget: bigint;
  funded: boolean;
  commitment: string;
  createdAt: number;
  initSig?: string;
  milestones: Milestone[];
}

/** Every role this wallet holds on the agreement (one wallet can be sponsor and verifier). */
export function rolesOf(wallet: string | null, a: Pick<Agreement, "sponsor" | "worker" | "verifier">): Role[] {
  if (!wallet) return [];
  const r: Role[] = [];
  if (wallet === a.sponsor) r.push("sponsor");
  if (wallet === a.worker) r.push("worker");
  if (a.verifier && wallet === a.verifier) r.push("verifier");
  return r;
}

export const firstOpenIndex = (ms: Pick<Milestone, "status">[]) => {
  const i = ms.findIndex((m) => m.status !== "RELEASED");
  return i === -1 ? ms.length : i;
};

/** Actions this wallet may take on milestone `index`. Empty → show status only, no button. */
export function allowedActions(roles: Role[], a: Agreement, index: number): Action[] {
  if (!a.funded || index !== firstOpenIndex(a.milestones)) return [];
  const has = (r: Role) => roles.includes(r);
  switch (a.milestones[index].status) {
    case "PENDING": return has("worker") ? ["submitEvidence"] : [];
    case "EVIDENCE_SUBMITTED": return has("sponsor") || has("verifier") ? ["verify"] : [];
    case "VERIFIED": return has("sponsor") ? ["release"] : [];
    case "RELEASED": return [];
  }
}

export function agreementStatus(a: Pick<Agreement, "funded" | "milestones">): AgreementStatus {
  if (!a.funded) return "DRAFT";
  if (a.milestones.length > 0 && a.milestones.every((m) => m.status === "RELEASED")) return "COMPLETED";
  if (a.milestones.every((m) => m.status === "PENDING")) return "FUNDED";
  return "ACTIVE";
}

export const released = (a: Agreement) => a.milestones.filter((m) => m.status === "RELEASED").reduce((s, m) => s + m.amount, 0n);
export const locked = (a: Agreement) => (a.funded ? a.budget - released(a) : 0n);
