"""Minimal MCP client over stdio (JSON-RPC 2.0, newline-delimited), stdlib only.

Only servers allowlisted in agency/agency.json are started, as fixed argv lists in the repo root with a
secret-free environment. Each call starts the server, runs initialize -> request, and stops it, so no
connection outlives a tool call. Server output is untrusted data: it is returned as text, never executed.
"""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path

PROTOCOL = "2025-06-18"


class MCPError(RuntimeError):
    pass


class Session:
    def __init__(self, argv: list[str], cwd: Path, env: dict, timeout: float):
        self.deadline = time.monotonic() + timeout
        self.p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, start_new_session=True)
        self.next_id = 0
        # A reader thread owns stdout: select() on a buffered pipe misses lines that arrive together.
        self.lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.p.stdout is not None
        for line in self.p.stdout:
            self.lines.put(line)
        self.lines.put(None)  # EOF

    def _send(self, msg: dict) -> None:
        assert self.p.stdin is not None
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def request(self, method: str, params: dict) -> dict:
        self.next_id += 1
        rid = self.next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        while True:
            left = self.deadline - time.monotonic()
            if left <= 0:
                raise MCPError(f"timed out waiting for {method}")
            try:
                line = self.lines.get(timeout=min(left, 1.0))
            except queue.Empty:
                continue
            if line is None:
                raise MCPError(f"server exited during {method} (exit {self.p.poll()})")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # stray log output on stdout
            if msg.get("id") != rid:
                continue  # notifications or server-to-client requests are ignored
            if "error" in msg:
                raise MCPError(f"{method}: {msg['error'].get('message', msg['error'])}")
            return msg.get("result") or {}

    def __enter__(self):
        self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                    "clientInfo": {"name": "lskhan-agency", "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def __exit__(self, *exc):
        try:
            os.killpg(self.p.pid, signal.SIGTERM)
            self.p.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def list_tools(argv: list[str], cwd: Path, env: dict, timeout: float = 60) -> list[dict]:
    with Session(argv, cwd, env, timeout) as s:
        return s.request("tools/list", {}).get("tools", [])


def call_tool(argv: list[str], cwd: Path, env: dict, name: str, arguments: dict, timeout: float = 120) -> dict:
    with Session(argv, cwd, env, timeout) as s:
        return s.request("tools/call", {"name": name, "arguments": arguments})
