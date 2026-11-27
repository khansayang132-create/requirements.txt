"""Scheduled-run command: segments file -> one mastered voiceover; placeholders refused."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from nova.audio import probe
from nova.daily import load_segments
from nova.pipeline import VOICES_DIR

NOVA = Path(__file__).resolve().parent.parent


def test_packaged_reference_present():
    ref = VOICES_DIR / "soft-young-indonesian-woman.reference.wav"
    assert ref.is_file() and 5 < probe(ref)["duration"] < 25


def test_placeholders_refused(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps([{"text": "Halo semua."}, {"text": "Ini [jawaban asli suami]."}]))
    with pytest.raises(ValueError, match="placeholder"):
        load_segments(f)


def test_daily_cli_renders_mp3(tmp_path):
    f = tmp_path / "today.json"
    f.write_text(json.dumps([
        {"label": "0-2s", "text": "Kebaya Indonesia vs shalwar kameez Pakistan… aku coba dua-duanya!", "emotion": "excitement"},
        {"label": "2-5s", "text": "Aku nilai tiga hal: nyaman, ribet nggak, dan kata suami."},
    ]))
    out = tmp_path / "voiceover.mp3"
    r = subprocess.run([sys.executable, "-m", "nova.daily", "--segments", str(f), "--out", str(out),
                        "--engine", "espeak-ng"], cwd=NOVA, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    summary = json.loads(r.stdout.strip().splitlines()[-1])
    assert summary["scenes"] == 2 and abs(summary["lufs"] + 14) < 1.0
    info = probe(out)
    assert info["codec"] == "mp3" and info["duration"] > 3
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"text": "Suamiku bilang [jawaban]."}]))
    r = subprocess.run([sys.executable, "-m", "nova.daily", "--segments", str(bad), "--out", str(out)],
                       cwd=NOVA, capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and "placeholder" in r.stderr


def test_daily_cli_clones_a_reference_with_consent(tmp_path, speaker_wav):
    f = tmp_path / "today.json"
    f.write_text(json.dumps([{"text": "Halo semua, ini suara aku sendiri."}]))
    out = tmp_path / "me.mp3"
    base = [sys.executable, "-m", "nova.daily", "--segments", str(f), "--out", str(out), "--engine", "espeak-ng",
            "--reference", str(speaker_wav), "--speaker", "Test Speaker"]
    refused = subprocess.run(base + ["--consent", "yes"], cwd=NOVA, capture_output=True, text=True, timeout=300)
    assert refused.returncode == 2 and "consent" in refused.stderr.lower()  # statement must name the speaker
    r = subprocess.run(base + ["--consent", "I, Test Speaker, consent to cloning my own voice.", "--pitch", "1",
                               "--soften", "0.5"], cwd=NOVA, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    summary = json.loads(r.stdout.strip().splitlines()[-1])
    assert summary["voice"] == "Test Speaker" and probe(out)["duration"] > 1
