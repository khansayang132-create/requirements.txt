"""The control centre reports real DB state and its buttons change real queue state."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from auravox import server
from auravox.queue import Queue


def _up(studio):
    server.Handler.studio = studio
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _get(url, method="GET"):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method=method)) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_state_and_controls(studio):
    q = Queue(studio)
    jid = q.enqueue("noop", {}, "a job")
    httpd, base = _up(studio)
    try:
        code, body = _get(base + "/api/state")
        st = json.loads(body)
        assert code == 200 and st["queue"] == {"queued": 1} and st["jobs"][0]["id"] == jid
        assert _get(f"{base}/api/jobs/{jid}/pause", "POST")[0] == 200 and q.get(jid)["status"] == "paused"
        assert _get(f"{base}/api/jobs/{jid}/resume", "POST")[0] == 200 and q.get(jid)["status"] == "queued"
        assert _get(f"{base}/api/jobs/{jid}/cancel", "POST")[0] == 200 and q.get(jid)["status"] == "cancelled"
        assert _get(f"{base}/api/jobs/{jid}/retry", "POST")[0] == 200 and q.get(jid)["status"] == "queued"
        assert _get(base + "/api/jobs/AVX-JOB-999999/retry", "POST")[0] == 404
        (studio.home / "secret.txt").write_text("x")
        assert _get(base + "/files/secret.txt")[0] == 200
        assert _get(base + "/files/%2e%2e/%2e%2e/etc/passwd")[0] == 404
        assert b"AURAVOX Control Centre" in _get(base + "/")[1]
    finally:
        httpd.shutdown()
