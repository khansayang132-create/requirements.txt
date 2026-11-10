#!/usr/bin/env python3
"""Check authentication status. Offline by default; --live makes one channels.list call (1 quota unit).

Exit codes: 0 authenticated (and required profiles satisfied), 4 not authenticated / missing scopes.

Examples:
  python skills/youtube-auth/scripts/validate_auth.py
  python skills/youtube-auth/scripts/validate_auth.py --require upload,manage
  python skills/youtube-auth/scripts/validate_auth.py --live --json
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli, oauth_manager  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--require", default="", help="Comma-separated scope profiles that must be granted")
    p.add_argument("--live", action="store_true", help="Refresh if needed and call channels.list(mine=true) to confirm the token works")
    cli.add_output_flags(p)
    args = p.parse_args()
    rt = cli.runtime()

    s = oauth_manager.status()
    problems: list[str] = []
    if not s["client_config_present"]:
        problems.append("OAuth client config missing (GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET or GOOGLE_CLIENT_SECRETS_FILE)")
    if s["state"] in ("NOT_AUTHENTICATED", "INVALID_NO_REFRESH_TOKEN"):
        problems.append(f"Auth state {s['state']}: run skills/youtube-auth/scripts/authenticate.py")
    if s.get("token_file_exists") and not s.get("token_file_private"):
        problems.append(f"Token file permissions are {s.get('token_file_mode')}; run: chmod 600 {s['token_path']}")
    if args.require:
        needed = oauth_manager.resolve_scopes(args.require)
        missing = sorted(set(needed) - set(s.get("granted_scopes", [])))
        s["missing_scopes"] = missing
        if missing:
            problems.append("Missing scopes: " + ", ".join(missing))

    if args.live and not any(pr.startswith(("OAuth client", "Auth state", "Missing scopes")) for pr in problems):
        client = cli.make_client(rt, ["channels.list"])
        channel = client.my_channel()
        s["live_check"] = (
            {"ok": True, "channel_id": channel["id"], "channel_title": channel.get("snippet", {}).get("title")}
            if channel
            else {"ok": False, "detail": "Token works but this Google account has no YouTube channel"}
        )
        if not channel:
            problems.append("No YouTube channel on this account")
        s = {**oauth_manager.status(), **{k: v for k, v in s.items() if k in ("live_check", "missing_scopes")}}

    s["problems"] = problems
    s["ok"] = not problems
    cli.emit(s, args.json, _human)
    return 0 if not problems else 4


def _human(s: dict) -> str:
    lines = [f"OK: {s['ok']}  state: {s['state']}", f"token: {s['token_path']} exists={s['token_file_exists']}"]
    if s.get("granted_scopes"):
        lines.append("scopes: " + ", ".join(x.rsplit("/", 1)[-1] for x in s["granted_scopes"]))
    if s.get("live_check"):
        lines.append(f"live check: {s['live_check']}")
    for pr in s["problems"]:
        lines.append(f"PROBLEM: {pr}")
    return "\n".join(lines)


if __name__ == "__main__":
    cli.run(main)
