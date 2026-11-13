"""media_audit catches what it claims (frozen video, missing audio, clipping) and does not cry wolf on calm shots."""
import shutil
import subprocess

import pytest

from agency import media_audit as M

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def _ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)


def test_still_picture_is_frozen(tmp_path):
    p = tmp_path / "still.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=s=320x568:r=24:d=1", "-frames:v", "1", str(tmp_path / "f.png"))
    _ff("-loop", "1", "-i", str(tmp_path / "f.png"), "-f", "lavfi", "-i", "sine=f=440:d=6", "-t", "6",
        "-r", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", str(p))
    rep = M.audit(p, do_playback=False)
    assert rep["video"]["frozen_runs_over_3s"] and rep["status"] == "FAIL"


def test_small_motion_in_a_wide_shot_is_not_frozen(tmp_path):
    """A 60x60 box moving across a big flat frame: the ep005 case (one arm moving in a wide shot)."""
    p = tmp_path / "calm.mp4"
    _ff("-f", "lavfi", "-i", "color=c=0xF0E0C0:s=1080x1920:r=24:d=6", "-f", "lavfi", "-i", "color=c=0x3060A0:s=60x60:r=24:d=6",
        "-f", "lavfi", "-i", "sine=f=440:d=6", "-filter_complex", "[0][1]overlay=x='200+40*t':y=900[v]", "-map", "[v]",
        "-map", "2", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p))
    rep = M.audit(p, do_playback=False)
    assert rep["video"]["frozen_runs_over_3s"] == [], rep["video"]


def test_missing_audio_and_per_channel_clipping(tmp_path):
    p = tmp_path / "silent.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=s=320x568:r=24:d=3", "-pix_fmt", "yuv420p", str(p))
    assert "no audio stream" in M.audit(p, do_playback=False)["problems"]
    q = tmp_path / "loud.mp4"                       # a square wave at full scale on both channels clips
    _ff("-f", "lavfi", "-i", "testsrc2=s=320x568:r=24:d=3", "-f", "lavfi", "-i",
        "aevalsrc='if(lt(mod(t*200,1),0.5),1,-1)|if(lt(mod(t*200,1),0.5),1,-1)':d=3", "-c:a", "pcm_s16le",
        "-pix_fmt", "yuv420p", str(tmp_path / "loud.mkv"))
    shutil.move(tmp_path / "loud.mkv", q.with_suffix(".mkv"))
    rep = M.audit(q.with_suffix(".mkv"), do_playback=False)
    assert rep["audio"]["clipped_samples"] > 0


def test_declared_still_is_reported_as_expected_not_hidden(tmp_path):
    p = tmp_path / "card.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=s=320x568:r=24:d=1", "-frames:v", "1", str(tmp_path / "f.png"))
    _ff("-loop", "1", "-i", str(tmp_path / "f.png"), "-f", "lavfi", "-i", "sine=f=440:d=5", "-t", "5",
        "-r", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", str(p))
    rep = M.audit(p, do_playback=False, expected=M.expected_from_edit({"segments": [["credits", 5.0]]}))
    assert rep["status"] == "PASS" and rep["expected"][0]["reason"] == "credits card"


def test_short_clip_playback_rewinds_before_measuring(tmp_path):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    p = tmp_path / "short.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=s=320x568:r=24:d=4", "-f", "lavfi", "-i", "sine=f=440:d=4", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(p))
    r = M.playback(p)
    if r["status"] == "BLOCKED":
        pytest.skip(r["detail"])
    assert r["status"] == "PASS" and r["advanced"] >= 1.0, r


def test_cli_audit_media_exit_code(tmp_path):
    from agency.cli import main
    p = tmp_path / "silent.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=s=320x568:r=24:d=3", "-pix_fmt", "yuv420p", str(p))
    assert main(["audit-media", str(p), "--no-playback", "--out", str(tmp_path / "r.json")]) == 1   # no audio -> FAIL
    assert "no audio stream" in (tmp_path / "r.json").read_text()
