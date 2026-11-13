"""Phonemes -> visemes -> per-frame mouth curves, and an objective lip-sync validation report.

Validation per line: viseme count, phoneme coverage of the voiced audio, edge offsets between first/last phoneme and
the audio's voiced region, and the correlation between the mouth-open curve and the audio's loudness envelope.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from . import analysis

BILABIAL = ("m", "b", "p")
LABIODENT = ("f", "v")
ROUND = ("o", "O", "u", "U", "w")
OPEN = ("a", "A", "0", "V", "&", "aI", "aU")


def viseme(sym: str) -> dict:
    p = (sym or "").strip("'\",%=_:;")
    if not p:
        return {"open": 0.0, "wide": 0.0, "round": 0.0, "closed": 0.0, "class": "rest"}
    if p in BILABIAL:
        return {"open": 0.0, "wide": 0.0, "round": 0.0, "closed": 1.0, "class": "MBP"}
    if p in LABIODENT:
        return {"open": 0.12, "wide": 0.35, "round": 0.0, "closed": 0.3, "class": "FV"}
    if p.startswith(ROUND):
        return {"open": 0.45, "wide": 0.0, "round": 0.85, "closed": 0.0, "class": "O"}
    if p.startswith(OPEN):
        return {"open": 0.9, "wide": 0.35, "round": 0.0, "closed": 0.0, "class": "AA"}
    if p[0] in "eEIi@3":
        return {"open": 0.5, "wide": 0.45, "round": 0.0, "closed": 0.0, "class": "E"}
    return {"open": 0.25, "wide": 0.25, "round": 0.0, "closed": 0.0, "class": "CONS"}


def curves(phonemes: list, seconds: float, fps: int = 24) -> dict:
    n = int(np.ceil(seconds * fps)) + 1
    out = {k: np.zeros(n) for k in ("open", "wide", "round", "closed")}
    for a, b, s in phonemes or []:
        v = viseme(s)
        fa, fb = int(a * fps), max(int(a * fps) + 1, int(np.ceil(b * fps)))
        for k in out:
            out[k][fa:min(fb, n)] = np.maximum(out[k][fa:min(fb, n)], v[k])
    return {k: v.tolist() for k, v in out.items()}


def validate(meta: dict, fps: int = 24) -> dict:
    rows = []
    for r in meta["lines"]:
        x, sr, _ = analysis.read_wav(Path(r["wav"]))
        hop = sr // fps
        env = np.sqrt((x[: len(x) // hop * hop].reshape(-1, hop) ** 2).mean(axis=1))
        ph = r.get("phonemes") or []
        c = curves(ph, len(x) / sr, fps)
        mouth = np.array(c["open"])[: len(env)]
        corr = float(np.corrcoef(mouth, env[: len(mouth)])[0, 1]) if len(mouth) > 3 and mouth.std() > 0 and env.std() > 0 else 0.0
        voiced = np.nonzero(env > max(np.percentile(env, 10) * 4, 10 ** (-42 / 20)))[0]
        v0, v1 = (voiced[0] / fps, (voiced[-1] + 1) / fps) if len(voiced) else (0, 0)
        spoken = [(a, b) for a, b, s in ph if viseme(s)["class"] != "rest"]       # pause markers are not speech
        p0, p1 = (spoken[0][0], spoken[-1][1]) if spoken else (0, 0)
        covered = sum(b - a for a, b, s in ph if viseme(s)["class"] != "rest")
        cov = covered / max(1e-6, v1 - v0)
        st = "PASS" if (len(ph) >= 3 and corr >= 0.3 and abs(p0 - v0) <= 0.15 and abs(p1 - v1) <= 0.25 and 0.5 <= cov <= 1.6) else "FAIL"
        if not ph:
            st = "BLOCKED"
        rows.append({"line_id": r["line_id"], "status": st, "alignment": r.get("alignment"), "phonemes": len(ph),
                     "visemes": sorted({viseme(s)["class"] for _a, _b, s in ph}), "mouth_audio_correlation": round(corr, 3),
                     "start_offset_s": round(p0 - v0, 3), "end_offset_s": round(p1 - v1, 3), "voiced_coverage": round(cov, 3)})
    status = "PASS" if rows and all(r["status"] == "PASS" for r in rows) else ("BLOCKED" if any(r["status"] == "BLOCKED" for r in rows) else "FAIL")
    return {"status": status, "fps": fps, "lines": rows,
            "method": "mouth-open curve from engine phoneme timing vs. RMS envelope; offsets vs. voiced region",
            "not_tested": "perceptual lip-sync quality (human review of the rendered animation)"}
