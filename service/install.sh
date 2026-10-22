#!/usr/bin/env bash
# Run the LSKhan Telegram bot 24/7 on Linux with systemd: starts at boot, restarts if it crashes,
# keeps running after you log out.
#
#   sudo bash service/install.sh                   bot only (OmniRoute already runs on its own)
#   sudo bash service/install.sh --with-omniroute  bot + OmniRoute as services
#   sudo bash service/install.sh uninstall         remove the services
#
# Logs:    journalctl -u lskhan-bot -f
# Restart: sudo systemctl restart lskhan-bot   (do this after editing .env)

set -euo pipefail

BOT_UNIT=/etc/systemd/system/lskhan-bot.service
OMNI_UNIT=/etc/systemd/system/lskhan-omniroute.service

die() { echo "❌ $*" >&2; exit 1; }
ok()  { echo "✅ $*"; }

[[ $EUID -eq 0 ]] || die "Run with sudo: sudo bash $0 $*"
command -v systemctl >/dev/null || die "systemd is required."

# The services run as you (the user who ran sudo), not as root.
RUN_USER=${SUDO_USER:-${RUN_USER:-}}
[[ -n $RUN_USER && $RUN_USER != root ]] || die "Run this with sudo from your normal user account (not as root directly)."
RUN_HOME=$(getent passwd "$RUN_USER" | cut -d: -f6)
BOT_DIR=$(cd "$(dirname "$0")/.." && pwd)

uninstall() {
    systemctl disable --now lskhan-bot lskhan-omniroute >/dev/null 2>&1 || true
    rm -f "$BOT_UNIT" "$OMNI_UNIT"
    systemctl daemon-reload
    ok "Services removed. (The bot's files and .env are untouched.)"
}

install_omniroute() {
    # Find omniroute the way your own shell would (it is often installed via npm/nvm in your home).
    local omni
    omni=$(sudo -u "$RUN_USER" -i bash -lc 'command -v omniroute' 2>/dev/null || true)
    # nvm is usually loaded only by interactive shells (~/.bashrc).
    [[ -n $omni ]] || omni=$(sudo -u "$RUN_USER" -i bash -ic 'command -v omniroute' 2>/dev/null | tail -1 || true)
    [[ -n $omni ]] || die "Could not find the 'omniroute' command for $RUN_USER. Install OmniRoute first, or run without --with-omniroute."
    cat > "$OMNI_UNIT" <<EOF
[Unit]
Description=OmniRoute AI gateway (for LSKhan bot)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
User=$RUN_USER
WorkingDirectory=$RUN_HOME
Environment=HOME=$RUN_HOME
Environment=PATH=$(dirname "$omni"):/usr/local/bin:/usr/bin:/bin
ExecStart=$omni
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now lskhan-omniroute >/dev/null 2>&1
    ok "OmniRoute service installed ($omni)."
}

install_bot() {
    [[ -f $BOT_DIR/bot.py && -f $BOT_DIR/requirements.txt ]] || die "Run this from the bot folder (bot.py not found in $BOT_DIR)."
    [[ -f $BOT_DIR/.env ]] || echo "⚠️  No .env yet: copy .env.example to .env and fill it in, then: sudo systemctl restart lskhan-bot"

    command -v python3 >/dev/null || die "python3 is required."
    if ! python3 -c 'import venv, ensurepip' 2>/dev/null; then
        command -v apt-get >/dev/null || die "Python venv support is missing. Install python3-venv."
        echo "📦 Installing python3-venv..."
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv >/dev/null
    fi

    # A private virtualenv, so system Python packages (and Ubuntu's pip restrictions) don't matter.
    echo "📦 Installing the bot's Python packages..."
    sudo -u "$RUN_USER" python3 -m venv "$BOT_DIR/.venv"
    sudo -u "$RUN_USER" "$BOT_DIR/.venv/bin/pip" install -q --upgrade pip
    sudo -u "$RUN_USER" "$BOT_DIR/.venv/bin/pip" install -q -r "$BOT_DIR/requirements.txt"

    local after="network-online.target"
    [[ -f $OMNI_UNIT ]] && after="$after lskhan-omniroute.service"
    cat > "$BOT_UNIT" <<EOF
[Unit]
Description=LSKhan Telegram AI bot
After=$after
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
User=$RUN_USER
WorkingDirectory=$BOT_DIR
ExecStart=$BOT_DIR/.venv/bin/python -u $BOT_DIR/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable lskhan-bot >/dev/null 2>&1
    systemctl restart lskhan-bot
    ok "Bot service installed and started. It now runs 24/7 and starts automatically at boot."
    echo "   Logs:    journalctl -u lskhan-bot -f"
    echo "   Restart: sudo systemctl restart lskhan-bot   (after editing .env)"
}

case ${1:-} in
    uninstall)         uninstall ;;
    --with-omniroute)  install_omniroute; install_bot ;;
    "")                install_bot ;;
    *)                 die "Use: sudo bash $0 [--with-omniroute | uninstall]" ;;
esac
