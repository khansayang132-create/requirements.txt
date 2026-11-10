"""Caption parsing/conversion, Whisper being optional, caption API calls, analytics honesty."""

from __future__ import annotations

import json

import pytest
from conftest import SAMPLE_SRT, err, load_script, make_client, ok, run_script

from src.captions import format_srt, format_vtt, load_cues, parse_srt, parse_vtt, transcribe_with_whisper, validate_caption_file, validate_cues
from src.exceptions import APIError, DependencyMissing, ValidationError

analytics = load_script("youtube-analytics", "analytics")
reports = load_script("youtube-analytics", "reports")


# ---------------------------------------------------------------- captions -------
def test_srt_roundtrip_and_vtt_conversion():
    fmt, cues = load_cues(SAMPLE_SRT)
    assert fmt == "srt" and len(cues) == 2 and cues[1].start == 1.5
    vtt = format_vtt(cues)
    assert vtt.startswith("WEBVTT") and "00:00:01.500 --> 00:00:03.000" in vtt
    back = parse_vtt(vtt)
    assert [(c.start, c.end, c.text) for c in back] == [(c.start, c.end, c.text) for c in cues]
    assert parse_srt(format_srt(cues))[0].text == cues[0].text


def test_vtt_with_header_notes_and_short_timestamps():
    cues = parse_vtt("WEBVTT\n\nNOTE generated\n\n00:01.000 --> 00:02.500 align:start\nHalo\n\nid-2\n00:00:03.000 --> 00:00:04.000\nApa kabar\n")
    assert [(c.start, c.end, c.text) for c in cues] == [(1.0, 2.5, "Halo"), (3.0, 4.0, "Apa kabar")]


def test_invalid_captions_are_reported(tmp_path):
    bad = tmp_path / "bad.srt"
    bad.write_text("1\n00:00:05,000 --> 00:00:02,000\nmundur\n")
    r = validate_caption_file(bad)
    assert not r.ok and "not after start" in r.errors[0]
    broken = tmp_path / "broken.srt"
    broken.write_text("1\nno timing here\n")
    assert not validate_caption_file(broken).ok
    with pytest.raises(ValidationError):
        parse_vtt("not a vtt")
    assert not validate_cues([]).ok


def test_whisper_is_optional():
    try:
        import whisper  # noqa: F401
    except ImportError:
        with pytest.raises(DependencyMissing, match="requirements-whisper.txt"):
            transcribe_with_whisper(SAMPLE_SRT)
        r = run_script("skills/youtube-transcript/scripts/whisper_fallback.py", "--check", "--json")
        assert r.returncode == 9 and json.loads(r.stdout)["available"] is False
    else:  # pragma: no cover - only where whisper is installed
        pytest.skip("whisper installed; optional-dependency path not exercised")


def test_caption_cli_validate_convert_and_confirm(tmp_path):
    r = run_script("skills/youtube-transcript/scripts/upload_captions.py", "--file", str(SAMPLE_SRT), "--validate-only", "--json")
    assert r.returncode == 0 and json.loads(r.stdout)["info"]["cues"] == 2
    out = tmp_path / "x.vtt"
    r = run_script("skills/youtube-transcript/scripts/upload_captions.py", "--file", str(SAMPLE_SRT), "--convert", "vtt", "--out", str(out))
    assert r.returncode == 0 and out.read_text().startswith("WEBVTT")
    r = run_script("skills/youtube-transcript/scripts/upload_captions.py", "--file", str(SAMPLE_SRT), "--video-id", "V")
    assert r.returncode == 2
    r = run_script("skills/youtube-transcript/scripts/upload_captions.py", "--file", str(SAMPLE_SRT), "--video-id", "V", "--dry-run")
    assert r.returncode == 0 and json.loads(r.stdout)["quota_estimate"] == {"data_api": 400}


def test_caption_api_calls(rt):
    client, http = make_client(rt, [
        ok({"items": [{"id": "CAP1", "snippet": {"language": "id", "trackKind": "standard", "name": ""}}]}),
        ({"status": "200", "content-type": "text/plain"}, "1\n00:00:00,000 --> 00:00:01,000\nHalo\n"),
        ok({"id": "CAP2"}),
    ])
    assert client.list_captions("V")[0]["id"] == "CAP1"
    data = client.download_caption("CAP1", fmt="srt")
    assert b"Halo" in data
    assert "/captions/CAP1" in http.requests[1]["uri"] and "tfmt=srt" in http.requests[1]["uri"] and "alt=media" in http.requests[1]["uri"]
    assert client.insert_caption("V", "id", "Bahasa Indonesia", SAMPLE_SRT)["id"] == "CAP2"
    meta = http.requests[2]["body"]
    meta = meta.decode() if isinstance(meta, bytes) else meta
    assert '"videoId": "V"' in meta and '"language": "id"' in meta
    used = rt.quota.report()["buckets"]["data_api"]["used_estimate"]
    assert used == 50 + 200 + 400


def test_caption_download_forbidden_is_not_retried(rt):
    client, http = make_client(rt, [err(403, "forbidden", "The permissions associated with the request are not sufficient to download the caption track.")])
    with pytest.raises(APIError) as exc:
        client.download_caption("CAP1", fmt="srt")
    assert exc.value.classification == "permission" and len(http.requests) == 1


# --------------------------------------------------------------- analytics -------
def test_overview_query_and_unavailable_metrics(rt):
    response = {
        "columnHeaders": [{"name": m} for m in analytics.OVERVIEW],
        "rows": [[120, 300, 45, 61.5, 4, 1, 10, 2, 3]],
    }
    client, http = make_client(rt, [], analytics_script=[ok(response)])
    res = analytics.run_report(client, "overview", "2026-10-01", "2026-10-28", video_id=None, metrics=None, dimensions=None, sort=None, max_results=None)
    assert res["status"] == "ok"
    assert res["metrics"]["views"] == {"value": 120, "status": "ok"}
    assert res["metrics"]["subscribersLost"]["value"] == 1
    assert res["metrics"]["impressions"]["status"] == "unavailable" and res["metrics"]["impressions"]["value"] is None
    assert res["metrics"]["impressionsClickThroughRate"]["status"] == "unavailable"
    assert rt.quota.report()["buckets"]["analytics"]["used_estimate"] == 1


def test_zero_is_not_unavailable_and_missing_is_not_zero():
    params, unavailable = analytics.build_query("overview", start="2026-10-01", end="2026-10-02", video_id="V1", metrics=None, dimensions=None, sort=None, max_results=None)
    assert params["filters"] == "video==V1" and params["ids"] == "channel==MINE"
    response = {"columnHeaders": [{"name": "views"}, {"name": "likes"}], "rows": [[0, 0]]}
    res = analytics.normalize(response, params, unavailable)
    assert res["metrics"]["views"] == {"value": 0, "status": "ok"}
    assert res["metrics"]["subscribersGained"]["status"] == "unavailable"  # requested, not returned → not 0
    empty = analytics.normalize({"columnHeaders": [{"name": "views"}], "rows": []}, params, unavailable)
    assert empty["status"] == "no_data" and "1-3 days" in empty["note"]


def test_retention_needs_a_video():
    with pytest.raises(ValidationError, match="single video"):
        analytics.build_query("retention", start="2026-10-01", end="2026-10-02", video_id=None, metrics=None, dimensions=None, sort=None, max_results=None)
    params, _ = analytics.build_query("retention", start="2026-10-01", end="2026-10-02", video_id="V", metrics=None, dimensions=None, sort=None, max_results=None)
    assert params["dimensions"] == "elapsedVideoTimeRatio" and "audienceWatchRatio" in params["metrics"]


def test_traffic_report_and_markdown():
    params, unavailable = analytics.build_query("traffic", start="2026-10-01", end="2026-10-28", video_id=None, metrics=None, dimensions=None, sort=None, max_results=None)
    res = analytics.normalize({"columnHeaders": [{"name": "insightTrafficSourceType"}, {"name": "views"}, {"name": "estimatedMinutesWatched"}],
                               "rows": [["SHORTS", 900, 120], ["YT_SEARCH", 50, 30]]}, params, unavailable)
    md = reports.render_markdown({**res, "report": "traffic"})
    assert "| SHORTS | 900 | 120 |" in md


def test_comparison_report_shows_change_and_keeps_unavailable():
    cur = {"report": "overview", "query": {"startDate": "b", "endDate": "c"}, "metrics": {"views": {"value": 150, "status": "ok"}, "impressions": {"value": None, "status": "unavailable", "reason": "not in API"}}}
    prev = {"query": {"startDate": "a", "endDate": "b"}, "metrics": {"views": {"value": 100, "status": "ok"}, "impressions": {"value": None, "status": "unavailable"}}}
    md = reports.render_markdown(cur, prev)
    assert "| Views | 150 | 100 | +50 (+50.0%) |" in md
    assert "| Impressions | unavailable | unavailable | n/a |" in md
    assert "not zero" in md


def test_custom_report_rejects_api_missing_metrics_only():
    with pytest.raises(ValidationError):
        analytics.build_query("custom", start="2026-10-01", end="2026-10-02", video_id=None, metrics=["impressions"], dimensions=None, sort=None, max_results=None)


def test_analytics_api_error_is_classified(rt):
    client, _ = make_client(rt, [], analytics_script=[err(403, "insufficientPermissions", "Insufficient permission")])
    with pytest.raises(APIError, match="OAuth scope"):
        analytics.run_report(client, "overview", "2026-10-01", "2026-10-02", video_id=None, metrics=None, dimensions=None, sort=None, max_results=None)
