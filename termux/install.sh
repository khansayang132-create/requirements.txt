#!/data/data/com.termux/files/usr/bin/bash
# Run the LSKhan Telegram bot (and OmniRoute) 24/7 on an Android phone with Termux:
# they run in the background, restart if they crash, and start again after the phone reboots.
#
#   bash termux/install.sh                   bot + OmniRoute
#   bash termux/install.sh --bot-only        bot only (you start OmniRoute yourself)
#   bash termux/install.sh status            are they running?
#   bash termux/install.sh logs              last lines of the bot's log
#   bash termux/install.sh uninstall         stop and remove the background services
#   bash termux/install.sh check             is OmniRoute answering with your key? are the services up?
#   bash termux/install.sh update            update the bot and OmniRoute, restart, then check
#   bash termux/install.sh site              publish the website on this phone (port 8080 by
#                                            default) at your fixed ngrok address, 24/7
#
# For start-after-reboot, also install the "Termux:Boot" app (same place you got Termux,
# e.g. F-Droid) and open it once.

set -euo pipefail

die() { echo "❌ $*" >&2; exit 1; }
ok()  { echo "✅ $*"; }

[[ -n ${PREFIX:-} && -d $PREFIX/bin && -n ${HOME:-} ]] || die "Run this inside the Termux app."
BOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
SV=$PREFIX/var/service
BOOT=$HOME/.termux/boot/lskhan-start
WAKELOCK=$PREFIX/etc/profile.d/lskhan-wakelock.sh

start_service_daemon() {
    # Same as termux-services does when a new Termux session opens.
    # shellcheck disable=SC1091
    . "$PREFIX/etc/profile.d/start-services.sh"
    for _ in $(seq 1 20); do [[ -f $PREFIX/var/run/service-daemon.pid ]] && break; sleep 0.5; done
    sleep 2   # give runsvdir a moment to pick up new service folders
}

# make_service NAME COMMAND...: a runit service with automatic restarts and a log.
make_service() {
    local name=$1; shift
    mkdir -p "$SV/$name/log"
    {
        echo "#!$PREFIX/bin/sh"
        echo "exec 2>&1"
        echo "cd \"$BOT_DIR\""
        echo "exec $*"
    } > "$SV/$name/run"
    chmod +x "$SV/$name/run"
    ln -sf "$PREFIX/share/termux-services/svlogger" "$SV/$name/log/run"
    rm -f "$SV/$name/down"
}

enable_service() {
    local name=$1
    for _ in $(seq 1 20); do sv up "$name" >/dev/null 2>&1 && return 0; sleep 1; done
    die "Could not start $name. Close Termux completely, open it again, and re-run this script."
}

install_all() {
    local with_omni=$1
    [[ -f $BOT_DIR/bot.py ]] || die "bot.py not found in $BOT_DIR. Run this from the bot folder."
    [[ -f $BOT_DIR/.env ]] || echo "⚠️  No .env yet: copy .env.example to .env and fill it in, then: bash termux/install.sh"

    echo "📦 Installing background services (termux-services)..."
    command -v sv-enable >/dev/null || pkg install -y termux-services >/dev/null
    command -v python >/dev/null || pkg install -y python >/dev/null

    if ! (cd "$BOT_DIR" && python -c 'import telegram, openai, dotenv') 2>/dev/null; then
        echo "📦 Installing the bot's Python packages..."
        pip install -q -r "$BOT_DIR/requirements.txt" \
            || die "Python packages failed to install. Try: pkg install rust && pip install -r requirements.txt"
    fi

    local omni=""
    if [[ $with_omni == 1 ]]; then
        omni=$(command -v omniroute || true)
        [[ -n $omni ]] || die "The 'omniroute' command was not found. Install OmniRoute first, or use --bot-only."
        # Stop a copy started by hand so the service can use port 20128.
        pkill -f "$omni" 2>/dev/null || true
    fi
    pkill -f "python.*bot.py" 2>/dev/null || true

    [[ -n $omni ]] && make_service lskhan-omniroute "\"$omni\""
    make_service lskhan-bot python -u bot.py

    start_service_daemon
    [[ -n $omni ]] && enable_service lskhan-omniroute
    enable_service lskhan-bot

    # Keep Android from pausing Termux while the phone sleeps.
    command -v termux-wake-lock >/dev/null && timeout 10 termux-wake-lock || true

    # Every time Termux opens: take the wake lock again. (The services themselves are started by
    # termux-services' own profile.d script.) So after a reboot, opening Termux once is enough.
    echo "(termux-wake-lock >/dev/null 2>&1 &)" > "$WAKELOCK"

    # Optional: start everything after a reboot without opening Termux (needs the Termux:Boot app).
    mkdir -p "$(dirname "$BOOT")"
    {
        echo "#!$PREFIX/bin/sh"
        echo "termux-wake-lock"
        echo ". \"$PREFIX/etc/profile.d/start-services.sh\""
    } > "$BOOT"
    chmod +x "$BOOT"

    ok "Running in the background now${omni:+ (bot + OmniRoute)}."
    echo "   It restarts automatically if it crashes."
    echo "   Check:  bash termux/install.sh status"
    echo "   Logs:   bash termux/install.sh logs"
    echo
    echo "For it to keep running 24/7 on your phone:"
    echo "  1. Android Settings → Apps → Termux → Battery → Unrestricted (no battery optimization)."
    echo "  2. Leave the Termux notification there (don't swipe it away or press Exit)."
    echo "  3. After the phone restarts, open Termux once: the bot starts again by itself."
    echo "     (Optional: the Termux:Boot app does this step for you, if your phone can install it.)"
}

# Read KEY=value from .env without running it as shell code.
env_get() {
    local line
    line=$(grep -E "^$1=" "$BOT_DIR/.env" 2>/dev/null | tail -n 1) || true
    line=${line#*=}; line=${line%$'\r'}; line=${line#\"}; line=${line%\"}
    printf '%s' "$line"
}

install_ngrok() {
    command -v ngrok >/dev/null && return 0
    local arch
    case $(uname -m) in
        aarch64|arm64) arch=arm64 ;;
        armv7l|armv8l|arm) arch=arm ;;
        x86_64) arch=amd64 ;;
        i686|i386) arch=386 ;;
        *) die "No ngrok build for this phone's CPU ($(uname -m))." ;;
    esac
    echo "📦 Installing ngrok..."
    command -v curl >/dev/null || pkg install -y curl >/dev/null
    local tmp; tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/ngrok.tgz" "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-$arch.tgz" \
        || die "Could not download ngrok. Check the phone's internet connection."
    tar -xzf "$tmp/ngrok.tgz" -C "$PREFIX/bin" ngrok
    chmod +x "$PREFIX/bin/ngrok"
    rm -rf "$tmp"
}

# Publish the phone's local website at the owner's fixed ngrok address, as a runit service.
site() {
    [[ -f $BOT_DIR/.env ]] || die "No .env yet: copy .env.example to .env first."
    local token domain port auth public
    token=$(env_get NGROK_AUTHTOKEN); domain=$(env_get SITE_DOMAIN)
    port=$(env_get SITE_PORT); port=${port:-8080}
    auth=$(env_get SITE_AUTH); public=$(env_get SITE_PUBLIC)
    domain=${domain#https://}; domain=${domain#http://}; domain=${domain%%/*}

    [[ -n $token ]] || die "Set NGROK_AUTHTOKEN in .env (ngrok dashboard → Your Authtoken)."
    [[ -n $domain ]] || die "Set SITE_DOMAIN in .env to your free ngrok domain (ngrok dashboard → Domains), e.g. name.ngrok-free.app"
    [[ $port =~ ^[0-9]+$ ]] || die "SITE_PORT must be a number (got: $port)."
    if [[ -z $auth && $public != yes ]]; then
        die "Set SITE_AUTH=username:password in .env, so only you (and Claude) can open the site. To publish it to everyone instead, set SITE_PUBLIC=yes."
    fi
    if [[ -n $auth ]]; then
        [[ $auth =~ ^[^:]+:.{8,}$ ]] || die "SITE_AUTH must look like username:password, with a password of 8+ characters."
        [[ $auth != *\"* && $auth != *\\* ]] || die "SITE_AUTH must not contain quotes or backslashes."
    fi

    install_ngrok
    local conf=$HOME/.config/lskhan/ngrok.yml
    mkdir -p "$(dirname "$conf")"
    ( umask 077
      {
          echo "version: 3"
          echo "agent:"
          echo "  authtoken: \"$token\""
          echo "  console_ui: false"
          # Android has no /etc/resolv.conf, so Go programs can't find a DNS server by themselves.
          echo "  dns_resolver_ips: [\"1.1.1.1\", \"8.8.8.8\"]"
          echo "endpoints:"
          echo "  - name: lskhan-site"
          echo "    url: https://$domain"
          echo "    upstream:"
          echo "      url: $port"
          if [[ -n $auth ]]; then
              echo "    traffic_policy:"
              echo "      on_http_request:"
              echo "        - actions:"
              echo "            - type: basic-auth"
              echo "              config:"
              echo "                credentials:"
              echo "                  - \"$auth\""
          fi
      } > "$conf" )

    command -v sv-enable >/dev/null || pkg install -y termux-services >/dev/null
    pkill -f "ngrok start" 2>/dev/null || true
    make_service lskhan-site ngrok start --config "\"$conf\"" --log stdout lskhan-site
    start_service_daemon
    enable_service lskhan-site
    command -v termux-wake-lock >/dev/null && timeout 10 termux-wake-lock || true

    if command -v curl >/dev/null && ! curl -s -m 5 -o /dev/null "http://127.0.0.1:$port/"; then
        echo "⚠️  Nothing answers on http://127.0.0.1:$port yet. Start your website, and the address will work."
    fi
    ok "Website published at https://$domain${auth:+ (password protected)}."
    echo "   It restarts automatically and comes back after a reboot like the bot."
    echo "   Check:  bash termux/install.sh status"
    echo "   Log:    tail $PREFIX/var/log/sv/lskhan-site/current"
}

# Is OmniRoute up, does it accept the key in .env, and does it offer OMNIROUTE_MODEL?
check() {
    local base key model tmp code ids rc=0
    base=$(env_get OMNIROUTE_BASE_URL); base=${base:-http://127.0.0.1:20128/v1}; base=${base%/}
    key=$(env_get OMNIROUTE_API_KEY); model=$(env_get OMNIROUTE_MODEL)
    command -v curl >/dev/null || pkg install -y curl >/dev/null
    tmp=$(mktemp)
    # The key goes to curl on stdin, so it never shows in a process list.
    code=$( { [[ -n $key ]] && printf 'header = "Authorization: Bearer %s"\n' "$key"; true; } \
            | curl -s -m 10 -K - -o "$tmp" -w '%{http_code}' "$base/models" ) || code=000
    case $code in
        200)
            ids=$(python -c 'import json,sys; print("\n".join(m.get("id","") for m in json.load(open(sys.argv[1])).get("data",[])))' "$tmp" 2>/dev/null || true)
            ok "OmniRoute is up at $base ($(printf '%s\n' "$ids" | grep -c . ) models)."
            if [[ -n $model && $model != auto ]] && ! printf '%s\n' "$ids" | grep -qxF "$model"; then
                echo "⚠️  OMNIROUTE_MODEL=$model is not in OmniRoute's model list. Check the name in the dashboard."; rc=1
            fi ;;
        401|403)
            echo "❌ OmniRoute refused the key (HTTP $code). Copy a key from the dashboard into OMNIROUTE_API_KEY in .env."; rc=1 ;;
        000)
            echo "❌ Nothing answers at $base. Start it: bash termux/install.sh (or run omniroute)."; rc=1 ;;
        *)
            echo "❌ OmniRoute answered HTTP $code at $base/models."; rc=1 ;;
    esac
    rm -f "$tmp"
    status
    return $rc
}

# Pull the latest bot code, update its packages and OmniRoute, restart the services, then check.
update() {
    if git -C "$BOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        echo "⬇️  Updating the bot code..."
        git -C "$BOT_DIR" pull --ff-only || die "git pull failed (local changes?). Run: git -C \"$BOT_DIR\" status"
    else
        echo "⚠️  $BOT_DIR is not a git clone, so the bot code was not updated."
    fi
    echo "📦 Updating the bot's Python packages..."
    pip install -q -U -r "$BOT_DIR/requirements.txt" || die "Python packages failed to update."
    if command -v omniroute >/dev/null; then
        command -v npm >/dev/null || pkg install -y nodejs >/dev/null
        echo "📦 Updating OmniRoute..."
        npm install -g omniroute@latest >/dev/null || die "OmniRoute update failed. Try: pkg upgrade nodejs, then run this again."
    fi
    start_service_daemon >/dev/null 2>&1 || true
    local name
    for name in lskhan-omniroute lskhan-bot lskhan-site; do
        [[ -d $SV/$name ]] && sv restart "$name" >/dev/null 2>&1 || true
    done
    # OmniRoute needs a few seconds to start listening after a restart.
    local _
    for _ in $(seq 1 15); do check >/dev/null 2>&1 && break; sleep 2; done
    check
}

status() {
    start_service_daemon >/dev/null 2>&1 || true
    local name
    for name in lskhan-omniroute lskhan-bot lskhan-site; do
        [[ -d $SV/$name ]] || continue
        sv status "$name" || true
    done
}

logs() {
    local log=$PREFIX/var/log/sv/lskhan-bot/current
    [[ -f $log ]] || die "No bot log yet."
    tail -n "${1:-40}" "$log"
}

uninstall() {
    start_service_daemon >/dev/null 2>&1 || true
    local name gone
    for name in lskhan-bot lskhan-omniroute lskhan-site; do
        gone="${SV:?}/.$name.removing"
        rm -rf "$gone" 2>/dev/null || true   # left over from an interrupted uninstall
        [[ -d $SV/$name ]] || continue
        sv down "$name" 2>/dev/null || true
        # After "sv down" its runsv keeps writing supervise/, so a plain rm races it ("Directory not
        # empty"). Hide the folder from runsvdir (it skips dot-folders and stops runsv for vanished
        # ones), tell runsv to exit, then delete, retrying until runsv has let go.
        mv "$SV/$name" "$gone"
        sv exit "$gone/log" "$gone" 2>/dev/null || true
        for _ in $(seq 1 20); do rm -rf "$gone" 2>/dev/null && break; sleep 0.5; done
        [[ ! -e $gone ]] || die "Could not remove $gone; run this again in a few seconds."
    done
    rm -f "$BOOT" "$WAKELOCK"
    ok "Background services removed. (The bot's files and .env are untouched.)"
}

case ${1:-} in
    "")          install_all 1 ;;
    --bot-only)  install_all 0 ;;
    status)      status ;;
    logs)        logs "${2:-40}" ;;
    uninstall)   uninstall ;;
    site)        site ;;
    check)       check ;;
    update)      update ;;
    *)           die "Use: bash termux/install.sh [--bot-only | status | check | update | logs | site | uninstall]" ;;
esac
