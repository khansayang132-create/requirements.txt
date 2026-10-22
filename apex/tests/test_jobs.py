"""Job queue: idempotency, state machine, retries/backoff, dead letters, crash recovery, shutdown."""
import pytest

from apex.jobs import InvalidTransition, JobQueue
from apex.models import JobState


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def q(tmp_path):
    clock = Clock()
    queue = JobQueue(tmp_path / "jobs.db", clock=clock, base_backoff=10, max_backoff=100)
    queue.clock_obj = clock
    return queue


def test_enqueue_is_idempotent(q):
    a = q.enqueue("k1", "produce_video", {"x": 1})
    b = q.enqueue("k1", "produce_video", {"x": 2})
    assert a.id == b.id and b.payload == {"x": 1}
    assert q.counts() == {"QUEUED": 1}


def test_happy_path_and_audit_log(q):
    j = q.enqueue("k", "produce_video", {})
    c = q.claim("w1")
    assert c.id == j.id and c.state == JobState.RUNNING and c.attempts == 1
    q.complete(j.id, {"final": "x.mp4"})
    done = q.get(j.id)
    assert done.state == JobState.COMPLETED and done.result == {"final": "x.mp4"}
    assert [e["to_state"] for e in q.events(j.id)] == ["CREATED", "QUEUED", "RUNNING", "QUALITY_REVIEW", "COMPLETED"]


def test_invalid_transition_rejected(q):
    j = q.enqueue("k", "produce_video", {})
    with pytest.raises(InvalidTransition):
        q.complete(j.id, {})  # QUEUED -> COMPLETED is not allowed


def test_retry_with_exponential_backoff_then_dead_letter(q):
    j = q.enqueue("k", "produce_video", {}, max_attempts=3)
    q.claim("w")
    j1 = q.fail(j.id, "provider timeout", retryable=True)
    assert j1.state == JobState.QUEUED
    assert q.claim("w") is None  # backoff not elapsed
    q.clock_obj.t += 10
    assert q.claim("w").attempts == 2
    q.fail(j.id, "provider timeout", retryable=True)
    q.clock_obj.t += 19
    assert q.claim("w") is None  # second backoff is 20s
    q.clock_obj.t += 1
    assert q.claim("w").attempts == 3
    dead = q.fail(j.id, "provider timeout", retryable=True)
    assert dead.state == JobState.FAILED and "provider timeout" in dead.last_error
    assert q.claim("w") is None


def test_non_retryable_fails_immediately(q):
    j = q.enqueue("k", "produce_video", {}, max_attempts=5)
    q.claim("w")
    assert q.fail(j.id, "no API key", retryable=False).state == JobState.FAILED


def test_crashed_worker_job_is_recovered(q):
    j = q.enqueue("k", "produce_video", {})
    q.claim("dead-worker", lease_seconds=60)
    q.clock_obj.t += 30
    assert q.claim("w2") is None  # lease still valid: no duplicate execution
    assert q.heartbeat(j.id, "dead-worker", 60)
    q.clock_obj.t += 61  # no heartbeat since: worker presumed dead
    rec = q.claim("w2")
    assert rec.id == j.id and rec.attempts == 2
    assert not q.heartbeat(j.id, "dead-worker", 60)  # old owner lost the lease
    assert any("lease expired" in (e["detail"] or "") for e in q.events(j.id))


def test_graceful_release_does_not_count_attempt(q):
    j = q.enqueue("k", "produce_video", {})
    q.claim("w1")
    q.release(j.id, "w1")
    again = q.claim("w2")
    assert again.id == j.id and again.attempts == 1


def test_cancel(q):
    j = q.enqueue("k", "produce_video", {})
    q.cancel(j.id)
    assert q.get(j.id).state == JobState.CANCELLED
    assert q.claim("w") is None


def test_queue_survives_restart(tmp_path):
    db = tmp_path / "jobs.db"
    j = JobQueue(db).enqueue("k", "produce_video", {"a": 1})
    reopened = JobQueue(db)
    assert reopened.get(j.id).state == JobState.QUEUED
    assert reopened.claim("w").id == j.id
