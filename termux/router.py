"""Front door for the phone's published address (bash termux/install.sh site, with OMNIROUTE_PUBLIC=yes).

    python termux/router.py /path/to/.env

ngrok forwards the public domain here. Requests under /v1/ go to OmniRoute's API, but only with
`Authorization: Bearer <OMNIROUTE_API_KEY>` from .env (checked here, so it holds even if OmniRoute's
own key setting is off). Everything else goes to the website on SITE_PORT. OmniRoute's dashboard
and its other routes are never reachable through this. Standard library only.
"""
from __future__ import annotations

import hmac
import http.client
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
              "transfer-encoding", "upgrade", "host", "content-length"}


def read_env(path: str) -> dict[str, str]:
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"')
    return env


def make_handler(site: tuple[str, int], omni: tuple[str, int], omni_prefix: str, key: str):
    expected = f"Bearer {key}".encode()

    class Router(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _reply(self, code: int, text: str) -> None:
            body = text.encode()
            self.send_response(code)
            self.send_header("content-type", "text/plain; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _relay(self, target: tuple[str, int], path: str) -> None:
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
            conn = http.client.HTTPConnection(*target, timeout=300)
            try:
                conn.request(self.command, path, body=body, headers=headers)
                resp = conn.getresponse()
            except OSError:
                conn.close()
                return self._reply(502, "upstream not answering\n")
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in HOP_BY_HOP:
                    self.send_header(k, v)
            self.send_header("transfer-encoding", "chunked")  # streams replies (SSE) as they arrive
            self.end_headers()
            try:
                while chunk := resp.read1(65536):
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            except OSError:
                self.close_connection = True
            finally:
                conn.close()

        def _route(self) -> None:
            path = urllib.parse.urlsplit(self.path).path
            # No dot segments, raw or encoded: /v1/../dashboard must never reach OmniRoute's dashboard.
            if any(seg in (".", "..") for seg in urllib.parse.unquote(path).split("/")) or "\\" in path:
                return self._reply(400, "bad path\n")
            if path == "/v1" or path.startswith("/v1/"):
                if not key:
                    return self._reply(503, "OmniRoute is not published (no OMNIROUTE_API_KEY on the phone)\n")
                given = (self.headers.get("authorization") or "").encode()
                if not hmac.compare_digest(given, expected):
                    return self._reply(401, "missing or wrong OmniRoute key\n")
                query = self.path[len(urllib.parse.urlsplit(self.path).path):]
                return self._relay(omni, omni_prefix + path[len("/v1"):] + query)
            return self._relay(site, self.path)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _route

        def log_message(self, fmt, *args):  # one line per request, without headers or keys
            sys.stdout.write("%s %s\n" % (self.command, urllib.parse.urlsplit(self.path).path))
            sys.stdout.flush()

    return Router


def main() -> None:
    env = read_env(sys.argv[1])
    base = urllib.parse.urlsplit(env.get("OMNIROUTE_BASE_URL") or "http://127.0.0.1:20128/v1")
    omni = (base.hostname or "127.0.0.1", base.port or 80)
    omni_prefix = base.path.rstrip("/") or ""  # OmniRoute's own API prefix, normally /v1
    site = ("127.0.0.1", int(env.get("SITE_PORT") or 8080))
    port = int(env.get("SITE_ROUTER_PORT") or 8099)
    handler = make_handler(site, omni, omni_prefix, env.get("OMNIROUTE_API_KEY", ""))
    print(f"router on 127.0.0.1:{port}: /v1/ -> {omni[0]}:{omni[1]}{omni_prefix}, rest -> site :{site[1]}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


if __name__ == "__main__":
    main()
