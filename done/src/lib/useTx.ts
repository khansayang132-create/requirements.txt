import { useCallback, useState } from "react";
import { runTx, type TxState } from "./store";

export const isPending = (t: TxState) => t.s === "signing" || t.s === "sending" || t.s === "confirming";

/** Local tx state for one action button/panel. `run` never throws; failures land in tx.s === "failed". */
export function useTx() {
  const [tx, setTx] = useState<TxState>({ s: "idle" });
  const run = useCallback((action: (on: (t: TxState) => void) => Promise<unknown>) => runTx(setTx, action), []);
  const reset = useCallback(() => setTx({ s: "idle" }), []);
  return { tx, pending: isPending(tx), run, reset };
}
