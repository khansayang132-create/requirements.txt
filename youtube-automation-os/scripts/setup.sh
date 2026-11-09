#!/usr/bin/env bash
# Install YouTube Automation OS on this device. Safe to re-run (idempotent).
# Works on Android/Termux (the owner's phone) and on Linux/macOS.
#
#   bash youtube-automation-os/scripts/setup.sh          install or update dependencies, create .env, self-test
#   bash youtube-automation-os/scripts/setup.sh check    what is ready and what is still missing (offline)
#
# Nothing here talks to YouTube. Real uploads still need: Google OAuth client in .env,
# authenticate.py once, YOUTUBE_DRY_RUN=false, and --confirm on each write.

set -euo pipefail

die() { echo "❌ $*" >&2; exit 1; }
ok()  { echo "✅ $*"; }
todo() { echo "➡️  $*"; }

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VENV=$ROOT/.venv
PY=$VENV/bin/python
STAMP=$VENV/.requirements.sha256

is_termux() { [[ ${PREFIX:-} == *com.termux* ]]; }

base_python() {
    for p in python3 python; do
        if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
            command -v "$p"; return 0
        fi
    done
    return 1
}

req_hash() { cat "$ROOT/requirements.txt" "$0" | sha256sum | cut -d' ' -f1; }

install_deps() {
    if is_termux; then
        # No prebuilt wheels on Android: take Pillow (needs libjpeg/zlib) from Termux's own package,
        # and a compiler for the few pip packages that build C code.
        local pkgs=(python python-pip python-pillow clang) missing=() p
        for p in "${pkgs[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
        if (( ${#missing[@]} )); then
            ok "Termux: installing ${missing[*]}…"
            pkg install -y "${missing[@]}"
        fi
    fi
    local py
    py=$(base_python) || die "Python 3.11+ is required. Termux: pkg install python   Debian/Ubuntu: apt install python3 python3-venv"
    if [[ ! -x $PY ]]; then
        if is_termux; then
            "$py" -m venv --system-site-packages "$VENV"   # sees Termux's python-pillow
        else
            "$py" -m venv "$VENV"
        fi
        ok "Created $VENV"
    fi
    if [[ -f $STAMP && $(cat "$STAMP") == "$(req_hash)" ]] && "$PY" -c 'import googleapiclient, google_auth_oauthlib, PIL, yaml, dotenv' 2>/dev/null; then
        ok "Dependencies already installed (requirements unchanged)"
        return 0
    fi
    "$PY" -m pip install -q --upgrade pip
    if is_termux; then
        # Pillow comes from pkg (version pinned by Termux); everything else from the pinned file.
        grep -viE '^pillow' "$ROOT/requirements.txt" > "$VENV/requirements-termux.txt"
        "$PY" -m pip install -q -r "$VENV/requirements-termux.txt"
    else
        "$PY" -m pip install -q -r "$ROOT/requirements.txt"
    fi
    "$PY" -c 'import googleapiclient, google_auth_oauthlib, PIL, yaml, dotenv' || die "Dependencies did not import after install"
    req_hash > "$STAMP"
    ok "Dependencies installed"
}

make_env() {
    if [[ ! -f $ROOT/.env ]]; then
        cp "$ROOT/.env.example" "$ROOT/.env"
        ok "Created .env from .env.example (safety lock YOUTUBE_DRY_RUN=true is ON)"
    fi
    chmod 600 "$ROOT/.env"
    [[ -f $ROOT/token.json ]] && chmod 600 "$ROOT/token.json"
    return 0
}

self_test() {
    # Full pipeline dry run on the bundled sample: validates config, video, metadata, thumbnail,
    # captions and quota with no network. State goes to a temporary folder, not your real state.
    local tmp
    tmp=$(mktemp -d)
    if (cd "$ROOT" && YTAOS_STATE_DIR=$tmp/state YTAOS_LOG_PATH=$tmp/log.jsonl \
            "$PY" skills/youtube-pipeline/scripts/pipeline.py --config examples/sample_pipeline.yaml --dry-run --json > "$tmp/report.json"); then
        "$PY" -c "import json,sys; r=json.load(open(sys.argv[1])); assert r['mode']=='dry_run' and len(r['steps'])==14" "$tmp/report.json" \
            || die "Self-test report was incomplete: $tmp/report.json"
        ok "Self-test passed: pipeline dry run on the sample video (no API calls)"
        rm -rf "$tmp"
    else
        die "Self-test failed; output kept in $tmp"
    fi
}

env_value() { grep -E "^$1=" "$ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'" ; }

check() {
    local ready=1
    if [[ -x $PY ]] && "$PY" -c 'import googleapiclient, google_auth_oauthlib, PIL, yaml, dotenv' 2>/dev/null; then
        ok "Dependencies installed ($("$PY" --version))"
    else
        todo "Dependencies missing: bash youtube-automation-os/scripts/setup.sh"; ready=0
    fi
    if [[ ! -f $ROOT/.env ]]; then
        todo "No .env yet: bash youtube-automation-os/scripts/setup.sh"; ready=0
    elif [[ -n $(env_value GOOGLE_CLIENT_ID) && -n $(env_value GOOGLE_CLIENT_SECRET) ]] || [[ -n $(env_value GOOGLE_CLIENT_SECRETS_FILE) ]]; then
        ok "Google OAuth client configured in .env"
    else
        todo "Put your Desktop-app OAuth client into $ROOT/.env: GOOGLE_CLIENT_ID=… and GOOGLE_CLIENT_SECRET=… (README → Google Cloud configuration)"; ready=0
    fi
    if [[ -x $PY ]] && (cd "$ROOT" && "$PY" skills/youtube-auth/scripts/validate_auth.py --require upload,manage >/dev/null 2>&1); then
        ok "YouTube account authorized (upload + manage)"
    else
        todo "Authorize once: cd $ROOT && .venv/bin/python skills/youtube-auth/scripts/authenticate.py --scopes upload,manage,captions,analytics"; ready=0
    fi
    if [[ $(env_value YOUTUBE_DRY_RUN) == "false" ]]; then
        ok "Safety lock off: real writes allowed with --confirm"
    else
        todo "Safety lock ON (YOUTUBE_DRY_RUN=true): dry runs only. Set YOUTUBE_DRY_RUN=false in .env when you are ready to publish."
        ready=0
    fi
    if (( ready )); then
        ok "LIVE: ready to publish. Next: .venv/bin/python skills/youtube-pipeline/scripts/pipeline.py --config <your.yaml> --dry-run, then --confirm"
    fi
    return 0
}

case "${1:-install}" in
    install)
        install_deps
        make_env
        self_test
        echo
        check
        ;;
    check) check ;;
    *) die "Unknown command '$1'. Use: setup.sh [install|check]" ;;
esac
