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

Models: LightGBM, XGBoost, RandomForest and a statistical baseline (regularised logistic regression),
each compared with the base rate. An LSTM is NOT included: on live OKX data (2026-11-07) the tree models
reached AUC 0.55-0.58 with worse-than-base-rate calibration on ~8,400 samples. A sequence model needs far
more data to be justified, and adding torch for it would be marketing, not evidence.
learner.py logs live predictions, resolves them against actual prices, detects deterioration and only
promotes a model that beats the base rate out of sample.
"""
