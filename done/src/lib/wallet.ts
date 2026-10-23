import { PublicKey } from "@solana/web3.js";

const B58 = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

/** A Solana wallet address (on the ed25519 curve, so not a PDA), or null. */
export function parseWallet(s: string): PublicKey | null {
  const t = s.trim();
  if (!B58.test(t)) return null;
  try {
    const k = new PublicKey(t);
    return PublicKey.isOnCurve(k.toBytes()) ? k : null;
  } catch {
    return null;
  }
}

export const short = (key: string) => (key.length > 10 ? `${key.slice(0, 4)}…${key.slice(-4)}` : key);
