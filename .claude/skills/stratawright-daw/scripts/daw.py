#!/usr/bin/env python3
"""Safe agent wrapper for the Stratawright DAW IPC socket.

Talks to the socket directly instead of shelling out to daw-cli, because the
stock client (src/Agentic layer/client/main_client.cpp @ 35008ae) has two traps:
  * it exits 0 even when the server answers "ERROR 72 ...", so exit codes lie;
  * it reads the reply once into a 4096-byte buffer, so long lists are cut off.

This wrapper sends the same wire format (one line, args with spaces quoted),
reads until the server closes the connection, and returns one JSON object:
  {"ok", "code", "symbol", "message", "fields" | "rows", "raw"}
Its exit code is the protocol code (0, 70..76), so a failed step stops a script.

Usage:
  daw.py run track list                 # one command; JSON output is requested for you
  daw.py --dry-run run track delete --track 4
  daw.py batch plan.txt                 # one command per line, stops at the first error
  daw.py snapshot                       # status + tracks + routing in one object
  daw.py gain-stage --track 1..8        # measure, plan; add --apply to change gain

Python 3.9+, standard library only. Socket: $DAW_SOCKET or /tmp/daw_session.sock.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shlex
import socket
import sys
from pathlib import Path

DEFAULT_SOCKET = "/tmp/daw_session.sock"
SYMBOLS = {0: "OK", 70: "INVALID_ARGS", 71: "DAW_NOT_RUNNING", 72: "ENTITY_NOT_FOUND",
           73: "ENGINE_PLAYING_LOCKED", 74: "RESOURCE_BUSY", 75: "PLUGIN_FAULT", 76: "ASSET_I_O_ERROR"}
# Commands that only read state. Everything else is a mutation: journaled, and skipped by --dry-run.
READ_ONLY = {("status", ""), ("track", "list"), ("track", "inspect"), ("plugin", "list"),
             ("clip", "list"), ("route", "list"), ("job", "list"), ("job", "status")}
READ_ONLY_VERBS = {"analyze"}
# In `export`, --format is the audio codec, so JSON output cannot be requested there.
CODEC_FORMAT_VERBS = {"export"}
ERROR_RE = re.compile(r'^ERROR (\d+) (\S+) "(.*)"\s*$', re.S)
OK_RE = re.compile(r"^OK (\S+)\s*$")


class DawError(Exception):
    def __init__(self, result: dict):
        super().__init__(result.get("message", ""))
        self.result = result


def encode(args: list[str]) -> str:
    """Same encoding as main_client.cpp: quote args containing spaces, newline-terminated."""
    for a in args:
        if '"' in a or "\n" in a or "\r" in a:
            raise ValueError(f"argument {a!r} contains a quote or newline; the server's tokenizer cannot carry it")
    line = " ".join(f'"{a}"' if " " in a else a for a in args) + "\n"
    if len(line.encode()) > 4095:
        raise ValueError("command longer than 4095 bytes; the server reads one 4096-byte buffer")
    return line


def verb_sub(args: list[str]) -> tuple[str, str]:
    verb = args[0] if args else ""
    sub = args[1] if len(args) > 1 and not args[1].startswith("-") else ""
    return verb, sub


def is_mutation(args: list[str]) -> bool:
    verb, sub = verb_sub(args)
    return not (verb in READ_ONLY_VERBS or (verb, sub) in READ_ONLY)


def coerce(v):
    if not isinstance(v, str):
        return v
    if v in ("true", "TRUE"):
        return True
    if v in ("false", "FALSE"):
        return False
    try:
        return int(v) if re.fullmatch(r"-?\d+", v) else float(v) if re.fullmatch(r"-?\d+\.\d*(e-?\d+)?", v) else v
    except ValueError:
        return v


def parse_reply(raw: str) -> dict:
    text = raw.strip()
    m = ERROR_RE.match(text)
    if m:
        code = int(m.group(1))
        return {"ok": False, "code": code, "symbol": m.group(2), "message": m.group(3), "raw": raw}
    m = OK_RE.match(text)
    if m:  # success with no fields, or an empty list (the server prints this even for --format json)
        return {"ok": True, "code": 0, "symbol": m.group(1), "rows": [], "fields": {}, "raw": raw}
    out = {"ok": True, "code": 0, "symbol": "OK", "raw": raw}
    if text.startswith("[") or text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:  # a name containing a quote or backslash breaks the server's JSON
            out["parse_error"] = str(e)
            return out
        if isinstance(data, list):
            out["rows"] = [{k: coerce(v) for k, v in r.items()} for r in data]
        else:
            out["fields"] = {k: coerce(v) for k, v in data.items()}
        return out
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines and "\t" in lines[0]:  # TSV: header + one or more value lines
        header = lines[0].split("\t")
        rows = [dict(zip(header, (coerce(c) for c in ln.split("\t")))) for ln in lines[1:]]  # noqa: B905 (3.9)
        if len(rows) == 1:
            out["fields"] = rows[0]
        else:
            out["rows"] = rows
        return out
    if lines and all(": " in ln for ln in lines):  # KV
        out["fields"] = {k: coerce(v) for k, v in (ln.split(": ", 1) for ln in lines)}
    return out


class Daw:
    def __init__(self, sock_path: str | None = None, dry_run: bool = False,
                 journal: str | None = None, timeout: float = 30.0):
        self.sock_path = sock_path or os.environ.get("DAW_SOCKET", DEFAULT_SOCKET)
        self.dry_run = dry_run
        self.journal = journal
        self.timeout = timeout

    def call(self, args: list[str], want_json: bool = True) -> dict:
        args = list(args)
        verb, _ = verb_sub(args)
        if want_json and "--format" not in args and verb not in CODEC_FORMAT_VERBS:
            args += ["--format", "json"]
        line = encode(args)
        mutation = is_mutation(args)
        if self.dry_run and mutation:
            return {"ok": True, "code": 0, "symbol": "DRY_RUN", "would_send": line.strip()}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout)
                s.connect(self.sock_path)
                s.sendall(line.encode())
                chunks = []
                while True:
                    b = s.recv(65536)
                    if not b:
                        break
                    chunks.append(b)
        except (FileNotFoundError, ConnectionRefusedError) as e:
            return {"ok": False, "code": 71, "symbol": "DAW_NOT_RUNNING",
                    "message": f"No DAW listening on {self.sock_path} ({e.__class__.__name__}). Start Stratawright first."}
        except socket.timeout:  # noqa: UP041 (not TimeoutError on 3.9)
            return {"ok": False, "code": 1, "symbol": "TIMEOUT",
                    "message": f"No reply within {self.timeout}s. The command may or may not have run: "
                               "check state before retrying."}
        result = parse_reply(b"".join(chunks).decode("utf-8", "replace"))
        result["command"] = line.strip()
        if mutation:
            self._log(result)
        return result

    def must(self, args: list[str]) -> dict:
        r = self.call(args)
        if not r["ok"]:
            raise DawError(r)
        return r

    def _log(self, result: dict):
        if not self.journal:
            return
        p = Path(self.journal).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        entry = {"at": datetime.datetime.now().isoformat(timespec="seconds"), "command": result["command"],
                 "ok": result["ok"], "code": result["code"], "symbol": result.get("symbol")}
        with p.open("a") as f:
            f.write(json.dumps(entry) + "\n")


def expand_range(spec: str) -> list[int]:
    """Same grammar as ParsedArgs::parseIntegerRange: '1', '1..4', '1..4,7,9..10'."""
    out: list[int] = []
    for seg in spec.split(","):
        seg = seg.strip()
        if ".." in seg:
            a, b = seg.split("..", 1)
            lo, hi = int(a), int(b)
            out.extend(range(min(lo, hi), max(lo, hi) + 1))
        elif seg:
            out.append(int(seg))
    return out


def plan_gain(peak_dbfs: float, crest_db: float, target_rms: float, ceiling: float, max_move: float) -> dict:
    """Offset that moves estimated RMS (peak - crest factor) to target, never pushing peak above ceiling."""
    if peak_dbfs <= -90.0:
        return {"action": "skip", "reason": "silent or no audio"}
    rms = peak_dbfs - crest_db
    want = target_rms - rms
    offset = min(want, ceiling - peak_dbfs)
    limited_by = "peak_ceiling" if offset < want else None
    if abs(offset) > max_move:
        return {"action": "skip", "reason": f"needs {offset:+.1f} dB, beyond the ±{max_move} dB safety limit",
                "est_rms_dbfs": round(rms, 1)}
    return {"action": "apply" if abs(offset) >= 0.1 else "none", "est_rms_dbfs": round(rms, 1),
            "offset_db": round(offset, 1), "limited_by": limited_by}


def gain_stage(daw: Daw, tracks: str, target_rms: float, ceiling: float, via: str,
               apply: bool, max_move: float) -> dict:
    report = []
    for tid in expand_range(tracks):
        f = daw.must(["analyze", "loudness", "--track", str(tid)]).get("fields", {})
        p = plan_gain(float(f.get("SAMPLE_PEAK_DBFS", -120)), float(f.get("CREST_FACTOR_DB", 0)),
                      target_rms, ceiling, max_move)
        p.update(track=tid, peak_dbfs=f.get("SAMPLE_PEAK_DBFS"), lufs=f.get("INTEGRATED_LUFS"))
        if apply and p["action"] == "apply":
            if via == "clip":
                clips = [c for c in daw.must(["clip", "list", "--track", str(tid)]).get("rows", [])
                         if c.get("TYPE") == "AUDIO" and c.get("TRACK_ID") == tid]
                if not clips:
                    p.update(action="skip", reason="no audio clips on track (use --via fader)")
                for c in clips:
                    db = round(float(c["GAIN_DB"]) + p["offset_db"], 1)
                    daw.must(["clip", "set-gain", "--track", str(tid), "--clip", str(c["CLIP_ID"]), "--db", str(db)])
            else:
                cur = float(daw.must(["track", "inspect", "--track", str(tid)])["fields"].get("GAIN_DB", 0.0))
                daw.must(["track", "set-gain", "--track", str(tid), "--db", str(round(cur + p["offset_db"], 1))])
            if p["action"] == "apply" and daw.dry_run:
                p.update(applied="dry_run")
            elif p["action"] == "apply":
                after = daw.must(["analyze", "loudness", "--track", str(tid)]).get("fields", {})
                est = float(after.get("SAMPLE_PEAK_DBFS", -120)) - float(after.get("CREST_FACTOR_DB", 0))
                p.update(applied=True, after_est_rms_dbfs=round(est, 1),
                         after_peak_dbfs=after.get("SAMPLE_PEAK_DBFS"),
                         verified=abs(est - p["est_rms_dbfs"] - p["offset_db"]) <= 0.5)
        report.append(p)
    unverified = [p["track"] for p in report if p.get("applied") is True and not p["verified"]]
    return {"ok": not unverified, "unverified_tracks": unverified, "applied": apply, "via": via,
            "target_rms_dbfs": target_rms,
            "peak_ceiling_dbfs": ceiling, "tracks": report}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--socket", help="socket path (default $DAW_SOCKET or /tmp/daw_session.sock)")
    ap.add_argument("--dry-run", action="store_true", help="print mutations instead of sending them")
    ap.add_argument("--journal", default=os.environ.get("DAW_JOURNAL", "~/.cache/stratawright/journal.jsonl"),
                    help="append every mutation here (set to '' to disable)")
    ap.add_argument("--timeout", type=float, default=30.0)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="send one daw-cli command")
    r.add_argument("args", nargs=argparse.REMAINDER)
    b = sub.add_parser("batch", help="run commands from a file, one per line; '#' comments")
    b.add_argument("file")
    b.add_argument("--keep-going", action="store_true")
    sub.add_parser("snapshot", help="status, tracks and routing in one JSON object")
    g = sub.add_parser("gain-stage", help="measurement-based gain staging (dry plan unless --apply)")
    g.add_argument("--track", required=True)
    g.add_argument("--target-rms", type=float, default=-18.0)
    g.add_argument("--peak-ceiling", type=float, default=-6.0)
    g.add_argument("--via", choices=["clip", "fader"], default="clip")
    g.add_argument("--max-move", type=float, default=24.0)
    g.add_argument("--apply", action="store_true")
    ns = ap.parse_args(argv)
    daw = Daw(ns.socket, ns.dry_run, ns.journal or None, ns.timeout)

    def emit(obj) -> None:
        print(json.dumps(obj, indent=2, ensure_ascii=False))

    try:
        if ns.cmd == "run":
            args = ns.args[1:] if ns.args[:1] == ["--"] else ns.args
            if not args:
                ap.error("run needs a command, e.g. run track list")
            res = daw.call(args)
            emit(res)
            return res["code"]
        if ns.cmd == "batch":
            results, worst = [], 0
            for n, raw in enumerate(Path(ns.file).read_text().splitlines(), 1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = shlex.split(line)
                if parts and parts[0] == "daw-cli":
                    parts = parts[1:]
                res = daw.call(parts)
                res["line"] = n
                results.append(res)
                if not res["ok"]:
                    worst = worst or res["code"]
                    if not ns.keep_going:
                        break
            emit({"ok": worst == 0, "steps": results})
            return worst
        if ns.cmd == "snapshot":
            snap = {k: daw.call(a) for k, a in
                    {"status": ["status"], "tracks": ["track", "list"], "routing": ["route", "list"]}.items()}
            bad = next((v for v in snap.values() if not v["ok"]), None)
            emit({"ok": bad is None, **snap})
            return bad["code"] if bad else 0
        if ns.cmd == "gain-stage":
            rep = gain_stage(daw, ns.track, ns.target_rms, ns.peak_ceiling, ns.via, ns.apply, ns.max_move)
            emit(rep)
            return 0 if rep["ok"] else 1
    except DawError as e:
        emit(e.result)
        return e.result["code"]
    except ValueError as e:
        emit({"ok": False, "code": 70, "symbol": "INVALID_ARGS", "message": str(e)})
        return 70
    return 0


if __name__ == "__main__":
    sys.exit(main())
