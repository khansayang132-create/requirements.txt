#!/usr/bin/env bash
# LSKhan Studio on the phone (Termux) or any Linux box.
#
#   bash studio/run.sh setup   install jaclang + jac-client and the bot's Python packages
#   bash studio/run.sh         start Studio; open http://127.0.0.1:8000 in the phone's browser
#   bash studio/run.sh hash    print the source hash that build.sh records in prebuilt/SOURCE_HASH
#
# The phone never builds the web page: jac builds with bun, which doesn't run in Termux. It
# serves the bundle that build.sh made on a computer (studio/prebuilt/, committed). jaclang's
# only dependency, llvmlite, is for native compilation and has no Android wheel, so it is
# skipped with --no-deps.
set -euo pipefail

STUDIO_DIR=$(cd "$(dirname "$0")" && pwd)
BOT_DIR=$(dirname "$STUDIO_DIR")
PORT="${STUDIO_PORT:-8000}"
PY=$(command -v python || command -v python3)
JAC_PKGS=("jaclang==0.16.7" "jac-client==0.3.25")

die() { echo "❌ $*" >&2; exit 1; }

source_hash() {
    (cd "$STUDIO_DIR" && find main.jac jac.toml global.css studio_ai.py components lib -type f | LC_ALL=C sort \
        | xargs sha256sum | sha256sum | cut -d' ' -f1)
}

setup() {
    if ! "$PY" -c 'import jaclang, jac_client' 2>/dev/null; then
        echo "Installing jaclang + jac-client..."
        "$PY" -m pip install -q --disable-pip-version-check --no-deps "${JAC_PKGS[@]}"
    fi
    if ! (cd "$BOT_DIR" && "$PY" -c 'import telegram, openai, dotenv') 2>/dev/null; then
        echo "Installing the bot's Python packages..."
        "$PY" -m pip install -q --disable-pip-version-check -r "$BOT_DIR/requirements.txt"
    fi
    echo "✅ Studio is installed. Start it with: bash studio/run.sh"
}

start() {
    command -v jac >/dev/null || die "jac not found. Run: bash studio/run.sh setup"
    [[ -f $STUDIO_DIR/prebuilt/SOURCE_HASH ]] || die "studio/prebuilt/ is missing. Build it on a computer: bash studio/build.sh"
    [[ $(cat "$STUDIO_DIR/prebuilt/SOURCE_HASH") == "$(source_hash)" ]] \
        || echo "⚠️  The page was built from older code. Rebuild on a computer (bash studio/build.sh) and commit." >&2

    # Fail closed: without an access code Studio refuses every AI call. Make one on first start.
    touch "$BOT_DIR/.env"
    if ! grep -qE '^STUDIO_ACCESS_CODE=.+' "$BOT_DIR/.env"; then
        sed -i '/^STUDIO_ACCESS_CODE=/d' "$BOT_DIR/.env"
        echo "STUDIO_ACCESS_CODE=$("$PY" -c 'import secrets; print(secrets.token_urlsafe(9))')" >> "$BOT_DIR/.env"
        echo "🔑 Made a Studio access code in .env. See it with: grep STUDIO_ACCESS_CODE $BOT_DIR/.env"
    fi

    # jac serves .jac/client/dist and never rebuilds while a client.*.js is there.
    rm -rf "$STUDIO_DIR/.jac/client/dist"
    mkdir -p "$STUDIO_DIR/.jac/client/dist"
    cp "$STUDIO_DIR"/prebuilt/* "$STUDIO_DIR/.jac/client/dist/"
    rm -f "$STUDIO_DIR/.jac/client/dist/SOURCE_HASH"

    echo "🌏💞 LSKhan Studio: open http://127.0.0.1:$PORT in your browser (Ctrl+C to stop)"
    cd "$STUDIO_DIR"
    exec jac start main.jac --port "$PORT"
}

case "${1:-start}" in
    setup) setup ;;
    start) start ;;
    hash) source_hash ;;
    *) die "usage: bash studio/run.sh [setup|start|hash]" ;;
esac
