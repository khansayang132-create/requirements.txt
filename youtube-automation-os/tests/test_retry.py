"""Error classification, bounded backoff with jitter, auth refresh, logging + redaction."""

from __future__ import annotations

import json

import pytest
from conftest import NoSleep, err, make_client, ok, read_log
from googleapiclient.errors import HttpError

from src.exceptions import APIError, QuotaExceededError
from src.logger import REDACTED, StructuredLogger, redact
from src.retry import ErrorClass, RetryPolicy, classify, parse_http_error


@pytest.mark.parametrize(
    "status,reason,expected",
    [
        (401, None, ErrorClass.AUTH),
        (403, "quotaExceeded", ErrorClass.QUOTA),
        (403, "dailyLimitExceeded", ErrorClass.QUOTA),
        (403, "uploadLimitExceeded", ErrorClass.QUOTA),
        (403, "rateLimitExceeded", ErrorClass.RATE_LIMIT),
        (403, "insufficientPermissions", ErrorClass.PERMISSION),
        (403, "forbidden", ErrorClass.PERMISSION),
        (404, "videoNotFound", ErrorClass.NOT_FOUND),
        (429, None, ErrorClass.RATE_LIMIT),
        (500, None, ErrorClass.SERVER),
        (502, None, ErrorClass.SERVER),
        (503, "backendError", ErrorClass.SERVER),
        (504, None, ErrorClass.SERVER),
        (400, "invalidTitle", ErrorClass.CLIENT),
        (None, None, ErrorClass.NETWORK),
    ],
)
def test_classification(status, reason, expected):
    assert classify(status, reason) is expected


def _http_error(status, reason, headers=None):
    import httplib2

    resp = httplib2.Response({"status": str(status), **(headers or {})})
    body = json.dumps({"error": {"code": status, "message": "m", "errors": [{"reason": reason}]}}).encode()
    return HttpError(resp, body, uri="https://youtube.googleapis.com/youtube/v3/videos")


def test_parse_http_error_reads_reason():
    assert parse_http_error(_http_error(403, "quotaExceeded"))[:2] == (403, "quotaExceeded")


class Flaky:
    def __init__(self, failures):
        self.failures = list(failures)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "ok"


def test_server_errors_are_retried_with_bounded_jittered_backoff():
    sleep = NoSleep()
    policy = RetryPolicy(max_attempts=5, base_delay=1, max_delay=8, sleep=sleep, rand=lambda: 1.0)
    fn = Flaky([_http_error(500, "backendError"), _http_error(503, "backendError"), _http_error(502, None)])
    assert policy.run(fn, operation="t") == "ok"
    assert fn.calls == 4
    assert sleep.calls == [1, 2, 4]  # rand=1.0 → exactly the upper bounds


def test_backoff_never_exceeds_cap():
    policy = RetryPolicy(max_attempts=10, base_delay=1, max_delay=8)
    for attempt in range(10):
        for _ in range(50):
            assert 0 <= policy.backoff(attempt) <= min(8, 2**attempt)
    assert policy.schedule()[-1] == 8


def test_retries_are_bounded():
    sleep = NoSleep()
    policy = RetryPolicy(max_attempts=3, sleep=sleep)
    fn = Flaky([_http_error(503, "backendError")] * 10)
    with pytest.raises(APIError) as exc:
        policy.run(fn, operation="t")
    assert fn.calls == 3 and len(sleep.calls) == 2
    assert exc.value.classification == "server" and exc.value.retryable and exc.value.attempts == 3


@pytest.mark.parametrize("status,reason,cls", [(404, "videoNotFound", "not_found"), (400, "invalidTitle", "client"), (403, "forbidden", "permission")])
def test_permanent_errors_are_not_retried(status, reason, cls):
    policy = RetryPolicy(sleep=NoSleep())
    fn = Flaky([_http_error(status, reason)])
    with pytest.raises(APIError) as exc:
        policy.run(fn, operation="t")
    assert fn.calls == 1 and exc.value.classification == cls


def test_permission_error_message_explains_scopes():
    with pytest.raises(APIError, match="OAuth scope"):
        RetryPolicy(sleep=NoSleep()).run(Flaky([_http_error(403, "insufficientPermissions")]), operation="t")


def test_quota_error_never_retried():
    sleep = NoSleep()
    fn = Flaky([_http_error(403, "quotaExceeded")] * 5)
    marked = []
    with pytest.raises(QuotaExceededError):
        RetryPolicy(sleep=sleep).run(fn, operation="t", on_quota_error=lambda: marked.append(1))
    assert fn.calls == 1 and sleep.calls == [] and marked == [1]


def test_429_honours_retry_after():
    sleep = NoSleep()
    policy = RetryPolicy(max_attempts=3, base_delay=1, max_delay=30, sleep=sleep, rand=lambda: 0.0)
    fn = Flaky([_http_error(429, "rateLimitExceeded", {"retry-after": "7"})])
    assert policy.run(fn, operation="t") == "ok"
    assert sleep.calls == [7.0]


def test_network_errors_retried_only_for_idempotent_calls():
    policy = RetryPolicy(max_attempts=3, sleep=NoSleep())
    assert policy.run(Flaky([TimeoutError("timed out")]), operation="t") == "ok"
    fn = Flaky([TimeoutError("timed out")])
    with pytest.raises(APIError) as exc:
        policy.run(fn, operation="t", idempotent=False)
    assert fn.calls == 1 and exc.value.classification == "network"


def test_401_triggers_one_refresh_then_retry():
    refreshed = []
    fn = Flaky([_http_error(401, "authError")])
    assert RetryPolicy(sleep=NoSleep()).run(fn, operation="t", on_auth_error=lambda: refreshed.append(1) or True) == "ok"
    assert refreshed == [1] and fn.calls == 2
    fn2 = Flaky([_http_error(401, "authError")] * 3)
    with pytest.raises(APIError) as exc:
        RetryPolicy(sleep=NoSleep()).run(fn2, operation="t", on_auth_error=lambda: True)
    assert exc.value.classification == "auth" and fn2.calls == 2


def test_client_call_retries_then_succeeds_and_logs(rt, log_path):
    client, http = make_client(rt, [err(503, "backendError"), err(500, "backendError"), ok({"items": [{"id": "V"}]})])
    assert client.get_video("V")["id"] == "V"
    assert len(http.requests) == 3
    records = [r for r in read_log(log_path) if r["operation"] == "videos.list"]
    failures = [r for r in records if r.get("error_class")]
    assert [r["http_status"] for r in failures] == [503, 500]
    assert [r["retry_count"] for r in failures] == [0, 1]
    assert all(r["request_id"] == records[0]["request_id"] for r in records)
    assert any(r.get("result") == "success" for r in records)
    assert all({"timestamp", "request_id", "operation", "endpoint"} <= set(r) for r in failures)


def test_redaction_masks_tokens_everywhere(tmp_path):
    log = StructuredLogger(tmp_path / "l.jsonl", echo=False)
    access, refresh, secret_ = "ya29" + ".abcdefghijklmnop", "1/" + "/0abcdefghijklmnopqrst", "GOCSPX" + "-zzz"
    log.info("x", f"Authorization: Bearer {access}", creds={"refresh_token": refresh, "client_secret": secret_, "client_id": "public-id"})
    text = (tmp_path / "l.jsonl").read_text()
    for secret in (access, refresh, secret_):
        assert secret not in text
    rec = json.loads(text)
    assert rec["creds"]["client_id"] == "public-id" and rec["creds"]["refresh_token"] == REDACTED
    assert redact({"nested": [{"access_token": "abc"}]}) == {"nested": [{"access_token": REDACTED}]}


def test_retry_manager_cli_explains():
    from conftest import run_script

    r = run_script("skills/youtube-pipeline/scripts/retry_manager.py", "--status", "403", "--reason", "quotaExceeded", "--json")
    assert r.returncode == 0
    d = json.loads(r.stdout)
    assert d["classification"] == "quota" and d["retried"] is False
    r = run_script("skills/youtube-pipeline/scripts/retry_manager.py", "--status", "503", "--json")
    assert json.loads(r.stdout)["retried"] is True
