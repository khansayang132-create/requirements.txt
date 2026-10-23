// USDC money helpers. Amounts are bigint base units (6 decimals); never floats.
export const USDC_DECIMALS = 6;
const SCALE = 10n ** BigInt(USDC_DECIMALS);

/** "1,250.5" → 1250500000n. Throws on anything that isn't a plain non-negative decimal with ≤ 6 places. */
export function parseUsdc(input: string): bigint {
  const s = input.trim().replace(/,/g, "");
  if (!/^\d+(\.\d{0,6})?$/.test(s)) throw new Error("Invalid USDC amount");
  const [whole, frac = ""] = s.split(".");
  return BigInt(whole) * SCALE + BigInt(frac.padEnd(USDC_DECIMALS, "0"));
}

/** Like parseUsdc but returns null instead of throwing (for live form fields). */
export function tryParseUsdc(input: string): bigint | null {
  try { return parseUsdc(input); } catch { return null; }
}

/** 1250500000n → "1,250.50". At least 2 decimals, up to 6. */
export function formatUsdc(base: bigint): string {
  const neg = base < 0n;
  const abs = neg ? -base : base;
  const whole = (abs / SCALE).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  let frac = (abs % SCALE).toString().padStart(USDC_DECIMALS, "0").replace(/0+$/, "");
  if (frac.length < 2) frac = frac.padEnd(2, "0");
  return `${neg ? "-" : ""}${whole}.${frac}`;
}

/** Plain form for putting back into an input: no thousands separators. */
export const toInput = (base: bigint) => formatUsdc(base).replace(/,/g, "");

export const budgetRemaining = (total: bigint, milestones: bigint[]) => milestones.reduce((r, m) => r - m, total);
