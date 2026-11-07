#!/bin/bash
# Install the done/ app's npm packages in Claude Code cloud sessions, so its typecheck,
# vitest and build work. Python deps are handled by scripts/agency-setup.sh (.venv).
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Run in the background so the session starts without waiting for npm.
echo '{"async": true, "asyncTimeout": 300000}'

cd "${CLAUDE_PROJECT_DIR:-.}/done"

# Run the install only if a listed file has changed since the install last succeeded.
# The hash file lives in node_modules (gitignored), so it goes away with the packages.
hashes=node_modules/.session-start.sha256
if ! sha256sum --check --status "$hashes" 2>/dev/null; then
  rm -f "$hashes"
  npm install --no-audit --no-fund --loglevel=error
  sha256sum ../.claude/hooks/session-start.sh package.json package-lock.json > "$hashes" || rm -f "$hashes"
  echo "done/: npm packages installed"
else
  echo "done/: npm packages up to date"
fi
