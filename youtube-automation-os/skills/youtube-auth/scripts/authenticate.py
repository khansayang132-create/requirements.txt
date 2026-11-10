#!/usr/bin/env python3
"""Authorize this toolkit for a YouTube channel (Google OAuth 2.0, installed-app loopback flow).

Examples:
  python skills/youtube-auth/scripts/authenticate.py --scopes upload,manage
  python skills/youtube-auth/scripts/authenticate.py --scopes upload,manage,captions,analytics --no-browser
  python skills/youtube-auth/scripts/authenticate.py --list-profiles
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli, oauth_manager  # noqa: E402
from src.config import load_env  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scopes", default="upload,manage", help="Comma-separated profiles from config/scopes.yaml or full scope URLs (default: upload,manage)")
    p.add_argument("--no-browser", action="store_true", help="Print the consent URL instead of opening a browser (open it on the same device)")
    p.add_argument("--force", action="store_true", help="Re-authorize even if a valid token exists")
    p.add_argument("--list-profiles", action="store_true", help="Show scope profiles and exit")
    cli.add_output_flags(p)
    args = p.parse_args()
    load_env()

    if args.list_profiles:
        cli.emit(oauth_manager.scope_profiles(), True)
        return 0

    scopes = oauth_manager.resolve_scopes(args.scopes)
    current = oauth_manager.status()
    if current.get("has_refresh_token") and set(scopes) <= set(current.get("granted_scopes", [])) and not args.force:
        print("Already authorized with the requested scopes. Use --force to re-authorize.", file=sys.stderr)
        cli.emit(current, args.json, _human)
        return 0

    oauth_manager.client_config()  # fail fast with a clear message if client config is missing
    result = oauth_manager.authenticate(scopes, open_browser=not args.no_browser)
    cli.emit(result, args.json, _human)
    return 0


def _human(s: dict) -> str:
    lines = [f"Auth state: {s.get('state')}", f"Token file: {s.get('token_path')} (mode {s.get('token_file_mode', '-')})"]
    lines.append(f"Refresh token present: {s.get('has_refresh_token')}")
    lines.append(f"Access token expiry: {s.get('access_token_expiry')}")
    lines.append("Granted scopes:\n  " + "\n  ".join(s.get("granted_scopes", []) or ["(none)"]))
    lines.append("Profiles satisfied: " + (", ".join(s.get("profiles_satisfied", [])) or "(none)"))
    return "\n".join(lines)


if __name__ == "__main__":
    cli.run(main)
