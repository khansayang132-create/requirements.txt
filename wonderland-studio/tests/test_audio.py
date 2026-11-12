"""Sound department tests: Foley timed from the animation, the mix, the ambience beds, mastering.

Fast (no video rendering) except the one test marked ``slow``, which muxes a short clip with ffmpeg.
Run:  python -m pytest wonderland-studio/tests/test_audio.py          (add -m "not slow" to skip the mux)
"""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wonderland.audio import foley, synth  # noqa: E402
from wonderland.audio.tts import write_wav  # noqa: E402
from wonderland.departments import audio as audio_dept  # noqa: E402
from wonderland.render.stage import Actor, Item, Overlay, Renderer, Shot  # noqa: E402

FPS = 24
SR = synth.SR
UNI = {"characters": []}          # Renderer.pose needs no character specs


def lift_track(actor: Actor, shot: Shot) -> list[float]:
    r = Renderer(UNI, 1080, 1920, FPS)
    return [r.pose(actor, shot, f / FPS, f / FPS, 0.0).lift for f in range(round(shot.duration * FPS))]


def events_for(shots, kind=None, actor=None):
    ev, _ = foley.spot(shots, UNI, FPS)
    return [e for e in ev if (kind is None or e["kind"] == kind) and (actor is None or actor in e["source"])]


# ----------------------------------------------------------------------------- Foley ----
def test_hop_in_landing_is_within_one_frame_of_lift_returning_to_zero():
    a = Actor(id="mimi", x=315, action="idle", enter="hop")
    shot = Shot(env="meadow", actors=[a], duration=2.0)
    lift = lift_track(a, shot)
    truth = next(f for f in range(1, len(lift)) if lift[f - 1] > 0 and lift[f] == 0)
    lands = events_for([shot], "landing", "mimi")
    assert lands, "no landing detected"
    assert abs(lands[0]["frame"] - truth) <= 1, (lands[0], truth)
    assert lands[0]["sound"] == "thump" and lands[0]["surface"] == "grass"
    assert lands[0]["timecode"] == foley.timecode(lands[0]["t"], FPS)


def test_hop_cycle_landings_match_lift_minima():
    a = Actor(id="bobo", x=540, action="hop")
    shot = Shot(env="playroom", actors=[a], duration=3.0)
    lift = lift_track(a, shot)
    minima = [f for f in range(1, len(lift) - 1) if lift[f] <= lift[f - 1] and lift[f] < lift[f + 1]]
    lands = [e for e in foley.Spotter([shot], UNI, FPS).spot()[0] if e["kind"] == "landing"]
    assert len(lands) >= 2
    for e in lands:
        assert min(abs(e["frame"] - m) for m in minima) <= 1, (e["frame"], minima)
        assert e["surface"] == "wood"


def test_walk_in_footsteps_follow_the_step_cycle():
    a = Actor(id="zuzu", x=865, action="idle", enter="walk")
    shot = Shot(env="bathroom", actors=[a], duration=2.0)
    steps = [e for e in events_for([shot], "footstep", "zuzu") if "walk-in" in e["source"]]
    assert len(steps) >= 3
    # the rig puts a foot down whenever sin(step) or sin(step + pi) falls to 0, step = 15 t
    period = math.pi / 15
    for e in steps:
        k = round(e["shot_t"] / period)
        assert abs(e["shot_t"] - k * period) <= 1 / FPS, e
        assert e["surface"] == "tile"
    gaps = np.diff([e["t"] for e in steps])
    assert np.all(gaps > period * 0.8)
    assert all(e["pan"] > 0 for e in steps), "walking in from the right is panned right"


def test_props_transfer_and_claps_are_spotted():
    x, y = Actor(id="mimi", x=315, action="give", facing=1), Actor(id="bobo", x=765, action="clap", facing=-1)
    items = [Item(name="ball", count=3, layout="show", cue=[0.4, 0.9, 1.4])]
    shot = Shot(env="garden", actors=[x, y], items=items, duration=3.0,
                transfer={"name": "ball", "from": "mimi", "to": "bobo", "start": 0.5, "end": 1.6})
    ev, _ = foley.spot([shot], UNI, FPS)
    pops = [e for e in ev if e["kind"] == "pop_in"]
    assert [round(e["shot_t"], 2) for e in pops] == [0.4, 0.9, 1.4]
    assert any(e["kind"] == "give" and e["pan"] < 0 for e in ev)
    assert any(e["kind"] == "catch" and e["pan"] > 0 for e in ev)
    assert any(e["kind"] == "clap" for e in ev)


def test_event_density_cap_holds_on_a_busy_shot():
    actors = [Actor(id=i, x=x, action=act) for i, x, act in (("a", 215, "clap"), ("b", 540, "hop"), ("c", 865, "dance"))]
    items = [Item(name="star", count=10, layout="show", cue=[0.1 * i for i in range(10)]),
             Item(name="leaf", count=12, layout="fall")]
    shot = Shot(env="rainy", actors=actors, items=items, duration=6.0, fx="sparkle",
                sfx=[{"name": "boing", "at": 0.1}, {"name": "chime", "at": 0.2}],
                transfer={"name": "ball", "from": "a", "to": "c", "start": 0.5, "end": 1.0})
    ev, stats = foley.spot([shot], UNI, FPS)
    assert stats["detected"] > foley.MAX_PER_SECOND * 6          # it really is busy
    assert sum(1 for e in ev if e["layer"] == "sfx") <= foley.MAX_SFX_PER_SHOT
    d = foley.density(ev, shot.duration)
    assert d["per_second_max"] <= foley.MAX_PER_SECOND, d
    assert stats["dropped_by_density_cap"] > 0


# ----------------------------------------------------------------------------- mixing ---
def speechlike(seconds: float, seed: int = 0, sr: int = 44100) -> np.ndarray:
    """A voice-shaped test signal: a buzzy 190 Hz source through three formants, in syllables, ~0.11 RMS."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr)) / sr
    f0 = 190 * (1 + 0.06 * np.sin(2 * math.pi * 0.7 * t))
    ph = 2 * math.pi * np.cumsum(f0) / sr
    x = sum(np.sin(k * ph) / k * (1.0 / (1 + ((k * 190 - 600) / 250) ** 2) + 0.6 / (1 + ((k * 190 - 1700) / 300) ** 2)
                                    + 0.3 / (1 + ((k * 190 - 2700) / 400) ** 2)) for k in range(1, 30))
    syl = np.clip(np.sin(2 * math.pi * 3.6 * t + rng.uniform(0, 6)), 0, 1) ** 0.7
    x = x * syl
    x[-int(0.05 * sr):] *= np.linspace(1, 0, int(0.05 * sr))
    return (x / np.sqrt(np.mean(x ** 2)) * 0.11).astype(np.float32)


@pytest.fixture(scope="module")
def episode(tmp_path_factory):
    """Three shots across two places: title + hop-in, a walk-in with props, the end card. Real voice-like lines."""
    d = tmp_path_factory.mktemp("ep")
    shots = [
        Shot(env="meadow", actors=[Actor(id="mimi", x=315, action="cheer", enter="hop"), Actor(id="bobo", x=765, action="clap", enter="walk")],
             overlay=Overlay("Hello Meadow", style="title"), duration=4.0, sfx=[{"name": "boing", "at": 0.05}]),
        Shot(env="pond", actors=[Actor(id="mimi", x=315, action="point"), Actor(id="zuzu", x=765, action="wave", enter="walk")],
             items=[Item(name="duck", count=3, layout="show")], duration=4.5, fx="sparkle", sfx=[{"name": "splash", "at": 2.4}]),
        Shot(env="pond", actors=[Actor(id="mimi", x=315, action="cheer"), Actor(id="zuzu", x=765, action="cheer")],
             overlay=Overlay("Bye!", style="end"), duration=3.5),
    ]
    voices, t = [], 0.0
    for i, s in enumerate(shots):
        p = d / f"line{i}.wav"
        write_wav(p, speechlike(min(2.2, s.duration - 1.2), seed=i))
        voices.append({"path": str(p), "start": 0.6, "shot_start": t, "provider": "test", "license": "test signal",
                       "cost_usd": 0.0, "chars": 10, "duration": 2.2})
        t += s.duration
    story = {"mood": "bright", "title": "Test", "beats": []}
    rep = audio_dept.build_soundtrack(shots, voices, story, 1234, d / "sound.wav", universe=UNI, fps=FPS, report_path=d / "foley.json")
    return {"dir": d, "shots": shots, "voices": voices, "story": story, "report": rep}


def read24(path: Path) -> tuple[np.ndarray, int, int, int]:
    with wave.open(str(path), "rb") as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = np.frombuffer(w.readframes(n), dtype=np.uint8).reshape(-1, 3)
    x = (raw[:, 0].astype(np.int32) | (raw[:, 1].astype(np.int32) << 8) | (raw[:, 2].astype(np.int32) << 16))
    x = np.where(x >= 1 << 23, x - (1 << 24), x).astype(np.float64) / 8388608.0
    return x.reshape(-1, ch).T, sr, ch, sw


def test_output_is_48k_stereo_and_report_is_complete(episode):
    x, sr, ch, sw = read24(episode["dir"] / "sound.wav")
    assert (sr, ch, sw) == (48000, 2, 3)
    assert abs(x.shape[1] / sr - sum(s.duration for s in episode["shots"])) < 2 / sr
    rep = episode["report"]
    for k in ("path", "seconds", "music", "sfx_events", "voice_providers", "voice_cost_usd", "voice_chars", "peak", "licences",
              "foley_events", "ambience", "buses"):
        assert k in rep, k
    kinds = {lic["kind"] for lic in rep["licences"]}
    assert {"music", "sfx", "foley", "ambience", "voice"} <= kinds
    assert all("no third-party material" in lic["license"] for lic in rep["licences"] if lic["kind"] != "voice")
    assert [a["env"] for a in rep["ambience"]] == ["meadow", "pond", "pond"]
    assert [s["kind"] for s in rep["stings"]] == ["title", "end"]
    import json
    full = json.loads((episode["dir"] / "foley.json").read_text())
    assert full["events"] and all({"t", "frame", "timecode", "source", "layer", "pan"} <= set(e) for e in full["events"])
    assert any(e["kind"] == "landing" for e in full["events"]) and any(e["kind"] == "footstep" for e in full["events"])


def test_deterministic(episode, tmp_path):
    rep2 = audio_dept.build_soundtrack(episode["shots"], episode["voices"], episode["story"], 1234, tmp_path / "again.wav", universe=UNI, fps=FPS)
    assert (tmp_path / "again.wav").read_bytes() == (episode["dir"] / "sound.wav").read_bytes()
    assert rep2["peak"] == episode["report"]["peak"]


def test_mix_never_clips(episode):
    x, *_ = read24(episode["dir"] / "sound.wav")
    peak = float(np.max(np.abs(x)))
    assert peak <= synth.MIX["ceiling"] + 1e-3 < 1.0
    assert episode["report"]["peak"] <= synth.MIX["ceiling"] + 1e-3


def test_voice_is_12db_above_the_bed_during_speech(episode):
    rep = episode["report"]
    assert rep["voice_to_bed_db"] >= 12.0, rep["voice_to_bed_db"]
    assert rep["voice_to_bed_db_p10_400ms"] >= 9.0, rep["voice_to_bed_db_p10_400ms"]


def test_music_dips_under_a_foley_peak():
    dur = 4.0
    t = np.arange(int(dur * SR)) / SR
    music = (0.3 * np.sin(2 * math.pi * 220 * t)).astype(np.float32)
    hit = 2.0
    res = synth.mix_layers(dur, [], music, foley=[{"t": hit, "sound": "thump", "surface": "grass", "gain": 0.17, "pan": 0.0}], master=False)
    m = res["stems"]["music"][0]

    def rms(a, b):
        return float(np.sqrt(np.mean(m[int(a * SR):int(b * SR)] ** 2)))
    before, during = rms(1.0, 1.5), rms(hit + 0.01, hit + 0.06)
    dip = 20 * math.log10(during / before)
    assert -8.0 <= dip <= -4.0, dip                         # about 6 dB
    assert rms(3.4, 3.9) / before > 0.95                    # and it comes back
    g = 20 * np.log10(res["gains"]["music"][int(1.5 * SR):int(3.5 * SR)])
    assert np.max(np.abs(np.diff(g))) < 0.05                # smooth: < 0.05 dB per sample, no pumping clicks


@pytest.mark.parametrize("env", sorted(synth.AMBIENCE))
def test_every_environment_has_a_seamless_ambience(env):
    loop = synth.ambience_loop(env, seed=7)
    assert loop.shape[0] == 2
    rms = float(np.sqrt(np.mean(loop.astype(np.float64) ** 2)))
    assert 20 * math.log10(rms) > -60, "not silent"
    assert 20 * math.log10(rms) < -40, "very low in level"
    for ch in loop:
        d = np.abs(np.diff(ch))
        seam = abs(float(ch[0]) - float(ch[-1]))
        assert seam <= float(np.percentile(d, 99.9)), (env, seam)
    corr = float(np.corrcoef(loop[0], loop[1])[0, 1])
    assert corr < 0.5, f"channels too similar ({corr:.2f}); should be decorrelated"
    assert np.array_equal(loop, synth.ambience_loop(env, seed=7))


def test_ambience_crossfades_between_places():
    trk = synth.ambience_track([(0, 2, "meadow"), (2, 4, "night")], 4.0, seed=1)
    assert trk.shape == (2, 4 * SR)
    jump = np.max(np.abs(np.diff(trk[:, int(1.9 * SR):int(2.1 * SR)], axis=1)))
    assert jump <= np.percentile(np.abs(np.diff(trk, axis=1)), 99.99)


def test_spectrum_is_gentle(episode):
    mix = episode["report"]["mix"]
    assert mix["above_8k_pct"] < 1.0 and mix["below_40_pct"] < 1.0


# ----------------------------------------------------------------------------- mastering --
@pytest.mark.slow
def test_mux_hits_minus_14_lufs_and_true_peak(episode, tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    from wonderland.departments import editing, qa
    dur = sum(s.duration for s in episode["shots"])
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=180x320:rate={FPS}:duration={dur}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    out = editing.mux(video, episode["dir"] / "sound.wav", tmp_path / "final.mp4")
    m = editing.measure_loudness(out)
    assert abs(m["lufs"] - (-14.0)) <= 1.0, m
    assert m["true_peak_dbtp"] <= -1.5, m
    a = next(s for s in qa.probe(out)["streams"] if s["codec_type"] == "audio")
    assert (a["codec_name"], a["sample_rate"], a["channels"]) == ("aac", "48000", 2)
