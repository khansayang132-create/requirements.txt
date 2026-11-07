"""Machine-learning engine.

What it does: estimates P(forward return over `horizon` bars > `threshold`) from causal
technical features. The output is an *input* shown next to the rule-based score; it is never
passed to RiskEngine.evaluate and cannot approve, size or block a trade (tests enforce this).

Leakage controls:
- features at bar i use only bars <= i (same indicators as the no-repaint test covers);
- the label at bar i uses bars i+1 .. i+horizon, so the last `horizon` rows have no label and are dropped;
- walk-forward splits are chronological with a purge gap of `horizon` bars between train and test,
  so no training label overlaps a test feature window;
- no shuffling anywhere.

Models: LightGBM (gradient boosting) and RandomForest, compared with a base-rate baseline.
An LSTM is NOT included: on OHLCV-only features with a few thousand samples per symbol it has
no evidence of beating trees here, and it would add a heavy dependency (torch) for marketing value.
"""
