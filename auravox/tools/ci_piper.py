"""CI check that Piper really speaks: download a small catalogued voice (MD5-verified), synthesise, measure.

Run where huggingface.co is reachable:  AVX_HOME=/tmp/avx python tools/ci_piper.py [en_US-lessac-low]
Exit 0 only when the model verified, the engine reports PASS and the speech passes the objective checks.
"""

import json
import sys
from pathlib import Path

from auravox import analysis
from auravox.studio import Studio

key = sys.argv[1] if len(sys.argv) > 1 else "en_US-lessac-low"
s = Studio(Path(__import__("os").environ.get("AVX_HOME", "/tmp/avx")))
m = s.store.install(key)
ver = s.store.verify(key)
s.refresh_engines()
health = s.engine_health("piper", max_age=0)
text = "The kite came home on a windy afternoon."
out = s.engines["piper"].generate(text, {"model": key}, {}, s.home / "piper_check.wav")
met = analysis.measure(Path(out["path"]), text)
rep = {"model": {k: m.get(k) for k in ("key", "bytes", "license", "sha256")}, "verify": ver, "health": health,
       "speech": {k: met[k] for k in ("duration_s", "rms_dbfs", "speech_ratio", "duration_ratio", "defects")},
       "alignment": bool(out["phonemes"])}
print(json.dumps(rep, indent=2, default=str))
ok = health[0] == "PASS" and not analysis.blocking(met) and met["duration_s"] > 1.0
sys.exit(0 if ok else 1)
