#!/usr/bin/env python3
"""Refresh the stored OAuth access token now (uses the saved refresh token; prints no secrets).

Example:
  python skills/youtube-auth/scripts/refresh_token.py
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
    cli.add_output_flags(p)
    args = p.parse_args()
    load_env()
    creds = oauth_manager.load_credentials(refresh=False)
    oauth_manager.refresh_credentials(creds)
    s = oauth_manager.status()
    cli.emit(s, args.json, lambda d: f"Refreshed. State: {d['state']}. New access-token expiry: {d['access_token_expiry']}")
    return 0


if __name__ == "__main__":
    cli.run(main)
