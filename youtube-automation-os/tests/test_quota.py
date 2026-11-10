"""Quota estimation, persistence, exhaustion handling (no endless retries)."""

from __future__ import annotations

import json

import pytest
from conftest import err, make_client, ok

from src.exceptions import QuotaExceededError
from src.quota_manager import QuotaManager, pacific_today


def test_costs_match_verified_google_table(settings):
    """Pinned to https://developers.google.com/youtube/v3/determine_quota_cost (updated 2026-11-03)."""
    costs = settings["quota"]["costs"]
    assert costs["videos.insert"] == {"cost": 1, "bucket": "videos_insert"}
    assert settings["quota"]["buckets"]["videos_insert"]["daily_limit"] == 100
    assert settings["quota"]["buckets"]["data_api"]["daily_limit"] == 10000
    expected = {"videos.update": 50, "videos.delete": 50, "thumbnails.set": 50, "captions.insert": 400,
                "captions.update": 450, "captions.list": 50, "videos.list": 1}
    for op, cost in expected.items():
        assert costs[op]["cost"] == cost, op
    assert costs["captions.download"]["verified"] is False


def test_estimate_by_bucket(quota):
    est = quota.estimate(["videos.insert", "thumbnails.set", "videos.list", "captions.insert", "made.up"])
    assert est.by_bucket == {"videos_insert": 1, "data_api": 451}
    assert est.unknown_ops == ["made.up"]


def test_unverified_cost_warns(quota):
    warnings = quota.check(["captions.download"])
    assert any("unverified" in w for w in warnings)


def test_check_refuses_when_estimate_exceeds_remaining(quota):
    for _ in range(199):
        quota.record("thumbnails.set")  # 9950 units
    assert quota.remaining()["data_api"]["remaining_estimate"] == 50
    warnings = quota.check(["videos.list"])
    assert any("Quota warning" in w for w in warnings)
    with pytest.raises(QuotaExceededError, match="Estimated need 400"):
        quota.check(["captions.insert"])


def test_upload_bucket_is_separate(quota):
    for _ in range(100):
        quota.record("videos.insert")
    assert quota.remaining()["data_api"]["used_estimate"] == 0
    with pytest.raises(QuotaExceededError):
        quota.check(["videos.insert"])
    quota.check(["thumbnails.set"])  # other bucket unaffected


def test_ledger_persists_and_resets_on_new_pacific_day(settings, tmp_path):
    ledger = tmp_path / "state" / "quota_ledger.json"
    q1 = QuotaManager(settings["quota"], ledger)
    q1.record("videos.update", http_status=200)
    q2 = QuotaManager(settings["quota"], ledger)
    assert q2.remaining()["data_api"]["used_estimate"] == 50
    data = json.loads(ledger.read_text())
    assert data["date"] == pacific_today() and data["calls"][0]["op"] == "videos.update"
    data["date"] = "2000-01-01"
    data["exhausted"] = ["data_api"]
    ledger.write_text(json.dumps(data))
    q3 = QuotaManager(settings["quota"], ledger)
    assert q3.remaining()["data_api"] == {**q3.remaining()["data_api"], "used_estimate": 0, "exhausted": False}


def test_env_override_of_daily_limit(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_DAILY_QUOTA", "20000")
    q = QuotaManager(settings["quota"], tmp_path / "l.json")
    assert q.remaining()["data_api"]["daily_limit"] == 20000


def test_quota_exceeded_response_stops_immediately_and_marks_bucket(rt):
    client, http = make_client(rt, [err(403, "quotaExceeded", "The request cannot be completed because you have exceeded your quota.")])
    with pytest.raises(QuotaExceededError, match="resets at midnight Pacific"):
        client.update_video({"id": "V", "snippet": {"title": "t", "categoryId": "22"}}, "snippet")
    assert len(http.requests) == 1  # no retries
    assert rt.policy.sleep.calls == []
    report = rt.quota.report()["buckets"]["data_api"]
    assert report["exhausted"] is True and report["used_estimate"] == 50  # failed calls still cost quota
    # Every later call in that bucket is refused before any HTTP request is made.
    with pytest.raises(QuotaExceededError, match="exhausted"):
        client.get_video("V")
    assert len(http.requests) == 1


def test_upload_limit_exceeded_is_quota_not_retry(rt):
    from conftest import SAMPLE_VIDEO

    client, http = make_client(rt, [err(403, "uploadLimitExceeded", "The user has exceeded the number of videos they may upload.")])
    with pytest.raises(QuotaExceededError):
        client.upload_video(SAMPLE_VIDEO, {"snippet": {"title": "t", "categoryId": "22"}, "status": {"privacyStatus": "private"}})
    assert len(http.requests) == 1
    assert rt.quota.report()["buckets"]["videos_insert"]["exhausted"] is True


def test_successful_calls_are_recorded(rt):
    client, _ = make_client(rt, [ok({"items": [{"id": "V", "snippet": {"title": "t"}}]})])
    assert client.get_video("V")["id"] == "V"
    calls = json.loads((rt.state_dir / "quota_ledger.json").read_text())["calls"]
    assert calls[-1]["op"] == "videos.list" and calls[-1]["success"] is True and calls[-1]["request_id"]


def test_quota_cli_report(tmp_path):
    from conftest import run_script

    r = run_script("skills/youtube-pipeline/scripts/state_manager.py", "quota", "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert set(data["buckets"]) == {"data_api", "videos_insert", "search_list", "analytics"}
