#!/data/data/com.termux/files/usr/bin/bash
# Run the LSKhan Telegram bot (and OmniRoute) 24/7 on an Android phone with Termux:
# they run in the background, restart if they crash, and start again after the phone reboots.
#
#   bash termux/install.sh                   bot + OmniRoute
#   bash termux/install.sh --bot-only        bot only (you start OmniRoute yourself)
#   bash termux/install.sh --with-headroom   also build and run Headroom (EXPERIMENTAL, see below)
#   bash termux/install.sh status            are they running?
#   bash termux/install.sh logs              last lines of the bot's log
#   bash termux/install.sh logs headroom     last lines of Headroom's log
#   bash termux/install.sh uninstall         stop and remove the background services
#
# For start-after-reboot, also install the "Termux:Boot" app (same place you got Termux,
# e.g. F-Droid) and open it once.
#
# Headroom (--with-headroom) is experimental. It has no Android builds, so pip compiles about ten
# Rust/C packages on the phone: 1-3 hours, ~4 GB free space while building. If anything fails, the
# bot is still installed without it, and the bot skips Headroom whenever it isn't running.

set -euo pipefail

die()  { echo "❌ $*" >&2; exit 1; }
ok()   { echo "✅ $*"; }
warn() { echo "⚠️  $*" >&2; }

[[ -n ${PREFIX:-} && -d $PREFIX/bin && -n ${HOME:-} ]] || die "Run this inside the Termux app."
BOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
SV=$PREFIX/var/service
BOOT=$HOME/.termux/boot/lskhan-start
WAKELOCK=$PREFIX/etc/profile.d/lskhan-wakelock.sh
HR_VENV=$HOME/.lskhan-headroom
HR_VERSION=0.41.0
HR_PORT=8765

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

# env_value KEY: KEY's value from .env, without quotes (empty if unset).
env_value() {
    [[ -f $BOT_DIR/.env ]] || return 0
    sed -n "s/^$1=//p" "$BOT_DIR/.env" | tail -n 1 | tr -d "\"'"
}

# Build Headroom into its own venv. Returns non-zero (never exits) so a failed build can't stop
# the bot from being installed. A finished build leaves $HR_VENV/.installed; anything less is redone.
install_headroom() {
    [[ -f $HR_VENV/.installed && -x $HR_VENV/bin/headroom ]] && return 0

    local free_kb
    free_kb=$(df -Pk "$HOME" | awk 'NR==2 {print $4}')
    if (( free_kb < 4 * 1024 * 1024 )); then
        warn "Headroom needs about 4 GB free to build; only $(( free_kb / 1024 )) MB free."
        return 1
    fi

    echo "🧪 Building Headroom $HR_VERSION (experimental). This takes 1-3 hours."
    echo "   Keep Termux open and the phone charging. If it stops, re-run the same command: it continues."
    command -v termux-wake-lock >/dev/null && timeout 10 termux-wake-lock || true

    # Termux ships onnxruntime, numpy and cryptography prebuilt; the venv sees them through
    # --system-site-packages. Everything else is compiled by pip with Rust and clang.
    pkg install -y rust clang make cmake binutils onnxruntime python-numpy python-cryptography >/dev/null \
        || { warn "Could not install Headroom's build tools (pkg install failed)."; return 1; }
    [[ -x $HR_VENV/bin/pip ]] || python -m venv --system-site-packages "$HR_VENV" \
        || { warn "Could not create $HR_VENV."; return 1; }

    local log=$HR_VENV/build.log start=$SECONDS pid rc
    # maturin (used by most of the Rust packages) can't detect the Android API level by itself.
    ANDROID_API_LEVEL=$(getprop ro.build.version.sdk 2>/dev/null || echo 24) \
        "$HR_VENV/bin/pip" install --disable-pip-version-check "headroom-ai[proxy]==$HR_VERSION" >"$log" 2>&1 &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        sleep 60
        kill -0 "$pid" 2>/dev/null && echo "   ...still building ($(( (SECONDS - start) / 60 )) min): $(tail -n 1 "$log" | cut -c1-70)"
    done
    wait "$pid" && rc=0 || rc=$?
    if (( rc != 0 )) || [[ ! -x $HR_VENV/bin/headroom ]]; then
        warn "Headroom failed to build. Last lines of $log:"
        tail -n 15 "$log" >&2
        return 1
    fi
    touch "$HR_VENV/.installed"
    ok "Headroom built in $(( (SECONDS - start) / 60 )) min."
}

# Point the bot at Headroom unless .env already sets HEADROOM_BASE_URL to something.
use_headroom_in_env() {
    local env=$BOT_DIR/.env url=http://127.0.0.1:$HR_PORT/v1
    [[ -f $env ]] || return 0
    [[ -n $(env_value HEADROOM_BASE_URL) ]] && return 0
    if grep -q '^HEADROOM_BASE_URL=' "$env"; then
        sed -i "s|^HEADROOM_BASE_URL=.*|HEADROOM_BASE_URL=$url|" "$env"
    else
        echo "HEADROOM_BASE_URL=$url" >> "$env"
    fi
    echo "   Set HEADROOM_BASE_URL=$url in .env"
}

wait_headroom_healthy() {
    for _ in $(seq 1 90); do
        curl -s -m 2 "http://127.0.0.1:$HR_PORT/health" >/dev/null 2>&1 && return 0
        sleep 1
    done
    return 1
}

install_all() {
    local with_omni=$1 with_hr=$2
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

    # Once installed, Headroom stays on when the script is re-run without the flag.
    [[ -d $SV/lskhan-headroom ]] && with_hr=1
    local hr=0
    if [[ $with_hr == 1 ]]; then
        if install_headroom; then
            hr=1
        else
            warn "Continuing without Headroom. The bot works the same, just without compression."
        fi
    fi
    if [[ $hr == 0 && -d $SV/lskhan-headroom ]]; then
        # e.g. its build was deleted: don't leave a service that can only crash-loop.
        sv down lskhan-headroom 2>/dev/null || true
        rm -rf "${SV:?}/lskhan-headroom"
    fi

    pkill -f "python.*bot.py" 2>/dev/null || true

    [[ -n $omni ]] && make_service lskhan-omniroute "\"$omni\""
    if [[ $hr == 1 ]]; then
        # Same gateway the bot uses: OmniRoute when it has a key, otherwise OpenAI (Headroom's default).
        local upstream="" base
        if [[ -n $(env_value OMNIROUTE_API_KEY) ]]; then
            base=$(env_value OMNIROUTE_BASE_URL)
            upstream="--openai-api-url ${base:-http://127.0.0.1:20128/v1}"
        fi
        make_service lskhan-headroom env HEADROOM_BEACON=off DO_NOT_TRACK=1 \
            "\"$HR_VENV/bin/headroom\"" proxy --host 127.0.0.1 --port "$HR_PORT" "$upstream"
        use_headroom_in_env
    fi
    make_service lskhan-bot python -u bot.py

    start_service_daemon
    [[ -n $omni ]] && enable_service lskhan-omniroute
    if [[ $hr == 1 ]]; then
        enable_service lskhan-headroom
        if wait_headroom_healthy; then
            ok "Headroom running on 127.0.0.1:$HR_PORT."
        else
            warn "Headroom started but isn't answering yet. Check: bash termux/install.sh logs headroom"
        fi
    fi
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

    local what=bot
    [[ -n $omni ]] && what+=" + OmniRoute"
    [[ $hr == 1 ]] && what+=" + Headroom"
    ok "Running in the background now ($what)."
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
    for name in lskhan-omniroute lskhan-headroom lskhan-bot; do
        [[ -d $SV/$name ]] || continue
        sv status "$name" || true
    done
    if [[ -d $SV/lskhan-headroom ]]; then
        curl -s -m 2 "http://127.0.0.1:$HR_PORT/health" >/dev/null 2>&1 \
            && echo "Headroom answers on 127.0.0.1:$HR_PORT" || echo "Headroom is not answering on 127.0.0.1:$HR_PORT"
    fi
}

# logs [headroom] [LINES]
logs() {
    local name=bot
    [[ ${1:-} == headroom ]] && { name=headroom; shift; }
    local log=$PREFIX/var/log/sv/lskhan-$name/current
    [[ -f $log ]] || die "No $name log yet."
    tail -n "${1:-40}" "$log"
}

uninstall() {
    start_service_daemon >/dev/null 2>&1 || true
    local name
    for name in lskhan-bot lskhan-headroom lskhan-omniroute; do
        [[ -d $SV/$name ]] || continue
        sv down "$name" 2>/dev/null || true
        rm -rf "${SV:?}/$name"
    done
    rm -f "$BOOT" "$WAKELOCK"
    ok "Background services removed. (The bot's files and .env are untouched.)"
    # The build took hours, so keep it; the bot skips Headroom when it isn't running.
    [[ -d $HR_VENV ]] && echo "   Headroom's build is kept in $HR_VENV. To free the space: rm -rf $HR_VENV"
}

usage="Use: bash termux/install.sh [--bot-only] [--with-headroom] | status | logs [headroom] [LINES] | uninstall"
case ${1:-} in
    status)      status ;;
    logs)        shift; logs "$@" ;;
    uninstall)   uninstall ;;
    *)
        with_omni=1 with_hr=0
        for arg in "$@"; do
            case $arg in
                --bot-only)      with_omni=0 ;;
                --with-headroom) with_hr=1 ;;
                *)               die "$usage" ;;
            esac
        done
        install_all "$with_omni" "$with_hr" ;;
esac
