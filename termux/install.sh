#!/data/data/com.termux/files/usr/bin/bash
# Run the LSKhan Telegram bot (and OmniRoute) 24/7 on an Android phone with Termux:
# they run in the background, restart if they crash, and start again after the phone reboots.
#
#   bash termux/install.sh                   bot + OmniRoute
#   bash termux/install.sh --bot-only        bot only (you start OmniRoute yourself)
#   bash termux/install.sh status            are they running?
#   bash termux/install.sh logs              last lines of the bot's log
#   bash termux/install.sh uninstall         stop and remove the background services
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

status() {
    start_service_daemon >/dev/null 2>&1 || true
    local name
    for name in lskhan-omniroute lskhan-bot; do
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
    for name in lskhan-bot lskhan-omniroute; do
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
    *)           die "Use: bash termux/install.sh [--bot-only | status | logs | uninstall]" ;;
esac
