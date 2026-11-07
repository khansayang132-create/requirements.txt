import numpy as np
import pandas as pd

from promovent.ta.structure import analyze


def frame(closes, highs=None, lows=None):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="1h", tz="UTC")
    c = np.array(closes, float)
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.array(highs, float) if highs is not None else np.maximum(o, c) + 0.1
    lo = np.array(lows, float) if lows is not None else np.minimum(o, c) - 0.1
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": 1.0}, index=idx)


# up to 10 (bar 4), pull back to 6 (bar 9), then rally through 10
PATH = [5, 6, 7, 8, 10, 9, 8, 7, 6.5, 6, 6.5, 7, 8, 9, 10.5, 11, 12]


def test_swing_confirmed_only_after_right_bars():
    st = analyze(frame(PATH), left=3, right=3)
    # swing high at bar 4 is stamped on bar 7, not bar 4
    assert np.isnan(st["swing_high"].iloc[4])
    assert st["swing_high"].iloc[7] == frame(PATH)["high"].iloc[4]


def test_bos_up_on_close_above_swing_high():
    st = analyze(frame(PATH), left=3, right=3)
    i = st.index.get_loc(st.index[st["break"] != ""][0])
    assert st["break"].iloc[i] == "BOS_UP"
    assert frame(PATH)["close"].iloc[i] > st["last_sh"].iloc[i]
    assert st["structure_trend"].iloc[-1] == 1


def test_choch_after_uptrend_breaks_down():
    down = PATH + [11, 10, 9.5, 9, 9.6, 10, 10.4, 9, 8, 7, 5]
    st = analyze(frame(down), left=3, right=3)
    breaks = [b for b in st["break"] if b]
    assert breaks[0] == "BOS_UP" and "CHOCH_DN" in breaks


def test_bullish_fvg():
    df = frame([10, 10, 12, 13], highs=[10.2, 10.5, 12.5, 13.2], lows=[9.8, 9.9, 10.8, 12.6])
    st = analyze(df)
    assert st["fvg_bull_lo"].iloc[3] == 10.5 and st["fvg_bull_hi"].iloc[3] == 12.6


def test_sweep_of_highs_closes_back_inside():
    p = PATH[:12]
    highs = list(np.maximum(np.concatenate([[p[0]], p[:-1]]), p) + 0.1)
    lows = list(np.minimum(np.concatenate([[p[0]], p[:-1]]), p) - 0.1)
    # bar 12 wicks above the bar-4 swing high (10.1) and closes back below it
    p2, h2, l2 = p + [9.5], highs + [10.6], lows + [6.9]
    st = analyze(frame(p2, h2, l2), left=3, right=3)
    assert st["sweep"].iloc[-1] == -1
    assert st["break"].iloc[-1] == ""
