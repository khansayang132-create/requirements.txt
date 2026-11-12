"""termux/router.py: /v1 only with the OmniRoute key, never OmniRoute's dashboard, everything else to the site."""
import http.client
import json
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROUTER = Path(__file__).resolve().parent.parent / "termux" / "router.py"
KEY = "sk-test-omniroute-key-123456"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _server(name, seen):
    class H(BaseHTTPRequestHandler):
        def _any(self):
            body = self.rfile.read(int(self.headers.get("content-length") or 0))
            seen.append((name, self.command, self.path, self.headers.get("authorization"), body))
            if self.path.endswith("/stream"):  # an SSE-like reply in several writes
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                for i in range(3):
                    self.wfile.write(f"data: {i}\n\n".encode())
                    self.wfile.flush()
                return
            out = json.dumps({"server": name, "path": self.path}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        do_GET = do_POST = _any

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def router(tmp_path):
    seen = []
    site, omni = _server("site", seen), _server("omni", seen)
    port = _free_port()
    env = tmp_path / ".env"
    env.write_text(f'OMNIROUTE_API_KEY="{KEY}"\nOMNIROUTE_BASE_URL=http://127.0.0.1:{omni.server_port}/v1\n'
                   f"SITE_PORT={site.server_port}\nSITE_ROUTER_PORT={port}\n")
    proc = subprocess.Popen([sys.executable, "-u", str(ROUTER), str(env)], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield port, seen
    proc.terminate()
    log = proc.communicate(timeout=5)[0]
    assert KEY not in log  # the request log never contains the key
    site.shutdown()
    omni.shutdown()


def _req(port, method, path, headers=None, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    return r.status, r.read()


AUTH = {"Authorization": f"Bearer {KEY}"}


def test_v1_with_key_reaches_omniroute(router):
    port, seen = router
    code, body = _req(port, "GET", "/v1/models?x=1", AUTH)
    assert code == 200 and json.loads(body) == {"server": "omni", "path": "/v1/models?x=1"}
    assert seen[-1][3] == f"Bearer {KEY}"  # OmniRoute still gets the key
    code, body = _req(port, "POST", "/v1/chat/completions", {**AUTH, "content-type": "application/json"},
                      b'{"model":"m"}')
    assert code == 200 and seen[-1][1:3] == ("POST", "/v1/chat/completions") and seen[-1][4] == b'{"model":"m"}'


def test_v1_without_or_with_wrong_key_is_refused(router):
    port, seen = router
    assert _req(port, "GET", "/v1/models")[0] == 401
    assert _req(port, "GET", "/v1/models", {"Authorization": "Bearer wrong"})[0] == 401
    assert _req(port, "GET", "/v1", {"Authorization": f"bearer {KEY}x"})[0] == 401
    assert not [s for s in seen if s[0] == "omni"]


def test_dot_segments_never_reach_omniroute(router):
    port, seen = router
    for path in ("/v1/../dashboard", "/v1/%2e%2e/dashboard", "/v1/%2E%2E/api/keys", "/v1/./models", "/v1\\..\\x"):
        assert _req(port, "GET", path, AUTH)[0] == 400, path
    assert not seen


def test_everything_else_goes_to_the_site(router):
    port, seen = router
    for path in ("/", "/about?q=1", "/v1foo", "/dashboard"):
        code, body = _req(port, "GET", path)
        assert code == 200 and json.loads(body) == {"server": "site", "path": path}
    assert {s[0] for s in seen} == {"site"}


def test_streams_replies(router):
    port, _ = router
    code, body = _req(port, "GET", "/v1/stream", AUTH)
    assert code == 200 and body == b"data: 0\n\ndata: 1\n\ndata: 2\n\n"


def test_upstream_down_is_502(tmp_path):
    port = _free_port()
    env = tmp_path / ".env"
    env.write_text(f"OMNIROUTE_API_KEY={KEY}\nOMNIROUTE_BASE_URL=http://127.0.0.1:1/v1\nSITE_PORT=1\n"
                   f"SITE_ROUTER_PORT={port}\n")
    proc = subprocess.Popen([sys.executable, str(ROUTER), str(env)], stdout=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        assert _req(port, "GET", "/v1/models", AUTH)[0] == 502
        assert _req(port, "GET", "/")[0] == 502
    finally:
        proc.terminate()
        proc.wait(timeout=5)
