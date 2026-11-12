import subprocess

from conftest import needs_ffmpeg

from dhfactory.agents.quality_control import check_video


@needs_ffmpeg
def test_qc_catches_missing_audio_and_wrong_size(tmp_path):
    v = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=2", "-pix_fmt", "yuv420p", str(v)], check=True)
    rep = check_video(v, width=1080, height=1920, duration_target=10)
    assert rep["overall"] == "FAIL"
    assert rep["checks"]["audio_stream"]["status"] == "FAIL" and rep["checks"]["resolution"]["status"] == "FAIL"
    assert rep["checks"]["duration"]["status"] == "FAIL"


def test_qc_missing_file(tmp_path):
    rep = check_video(tmp_path / "nope.mp4", width=1, height=1, duration_target=None)
    assert rep["overall"] == "FAIL"


def test_cli_doctor_and_help(settings, capsys):
    from dhfactory.cli import main

    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert '"heygen"' in out and "BLOCKED" in out and "production-manager" in out
