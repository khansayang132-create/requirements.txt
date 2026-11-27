"""Quality assurance. A production passes only when its files exist, decode, agree with each
other and with the manifest, meet loudness and peak targets, contain no long dead air, and its
subtitles fit the audio. Speech recognition is used when it is installed; otherwise that check
says it was skipped (it never counts as a pass)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from .. import audio as A
from ..mastering import integrated_loudness, true_peak_db


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def longest_silence(x: np.ndarray, sr: int, threshold_db: float = -45.0) -> float:
    hop = int(sr * 0.01)
    rms = np.sqrt(np.convolve(x ** 2, np.ones(hop) / hop, mode="same")[::hop] + 1e-12)
    quiet = 20 * np.log10(rms) < threshold_db
    best = cur = 0
    for q in quiet:
        cur = cur + 1 if q else 0
        best = max(best, cur)
    return round(best * 0.01, 2)


def check(files: dict[str, str], manifest_duration: float, target_lufs: float, cues: list[dict],
          sentences: int, script_text: str = "", asr=None, ceiling_db: float = -1.0) -> dict:
    checks: list[dict] = []

    def add(name, ok, detail, required=True):
        checks.append({"check": name, "ok": bool(ok), "detail": detail, "required": required})

    probes = {}
    for fmt, p in files.items():
        path = Path(p)
        if not path.is_file() or path.stat().st_size < 1000:
            add(f"{fmt} file exists", False, str(path))
            continue
        info = A.probe(path)
        probes[fmt] = info | {"bytes": path.stat().st_size, "sha256": sha256(path)}
        add(f"{fmt} decodes", info["duration"] > 0, f"{info['codec']} {info['sample_rate']} Hz {info['duration']:.3f}s")
        add(f"{fmt} duration matches render", abs(info["duration"] - manifest_duration) <= 0.15,
            f"{info['duration']:.3f}s vs {manifest_duration:.3f}s")
    if "wav" in probes:
        x, sr = A.load_audio(files["wav"])
        lufs, peak = integrated_loudness(x, sr), true_peak_db(x)
        add("loudness on target", abs(lufs - target_lufs) <= 1.0, f"{lufs:.2f} LUFS (target {target_lufs})")
        add("true peak under ceiling", peak <= ceiling_db + 0.15, f"{peak:.2f} dBTP (ceiling {ceiling_db})")
        sil = longest_silence(x, sr)
        add("no dead air over 2.5 s", sil <= 2.5, f"longest silence {sil}s")
        add("not clipped", float(np.mean(np.abs(x) > 0.999)) < 1e-4, "samples at full scale checked")
    if "wav" in probes and "mp3" in probes:
        add("wav and mp3 agree", abs(probes["wav"]["duration"] - probes["mp3"]["duration"]) <= 0.1,
            f"{probes['wav']['duration']:.3f}s / {probes['mp3']['duration']:.3f}s")
    add("subtitles cover every sentence", len({c["sentence"] for c in cues}) >= sentences,
        f"{len({c['sentence'] for c in cues})}/{sentences} sentences")
    add("subtitles inside the audio", all(c["end_s"] <= manifest_duration + 0.05 for c in cues),
        f"last cue ends {cues[-1]['end_s'] if cues else 0}s")
    if asr and script_text:
        try:
            heard = asr(files.get("wav") or files.get("mp3"))
            from ..enhance import _content
            want, got = _content(script_text, "id"), _content(heard, "id")
            cov = len(want & got) / max(1, len(want))
            add("speech recognition hears the script", cov >= 0.7, f"{cov:.0%} of content words heard",
                required=False)
        except Exception as exc:
            add("speech recognition hears the script", False, f"error: {exc}"[:200], required=False)
    else:
        checks.append({"check": "speech recognition", "ok": None, "detail": "skipped: no recogniser installed",
                       "required": False})
    passed = all(c["ok"] for c in checks if c["required"])
    return {"passed": passed, "checks": checks, "files": probes}
