"use client";

export const SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT", "LINK/USDT", "AVAX/USDT", "DOT/USDT"];
export const TFS = ["5m", "15m", "1h", "4h", "1d"];

export function Pickers({ sym, setSym, tf, setTf }: { sym: string; setSym: (s: string) => void; tf: string; setTf: (s: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      <select className="input !w-auto" aria-label="Symbol" value={sym} onChange={(e) => setSym(e.target.value)}>{SYMBOLS.map((s) => <option key={s}>{s}</option>)}</select>
      <select className="input !w-auto" aria-label="Timeframe" value={tf} onChange={(e) => setTf(e.target.value)}>{TFS.map((s) => <option key={s}>{s}</option>)}</select>
    </div>
  );
}

