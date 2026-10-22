#!/data/data/com.termux/files/usr/bin/bash
# CI test for termux/install.sh, run inside the termux/termux-docker image (a real Termux userland).
set -euxo pipefail

pkg update -y >/dev/null 2>&1 || true
pkg install -y python termux-services >/dev/null

rm -rf "$HOME/bot"; cp -r /mnt/repo "$HOME/bot"; cd "$HOME/bot"
printf 'TELEGRAM_BOT_TOKEN=123456:fake\n' > .env

# Stand-ins: a bot that crashes after 3 seconds (to prove restarts) and an OmniRoute that just runs.
cat > bot.py <<'EOF'
import time
print("FAKE BOT STARTED", flush=True)
time.sleep(3)
raise SystemExit(1)
EOF
: > requirements.txt
printf '#!%s/bin/sh\nexec sleep 100000\n' "$PREFIX" > "$PREFIX/bin/omniroute"
chmod +x "$PREFIX/bin/omniroute"

bash termux/install.sh

export SVDIR=$PREFIX/var/service
sv status lskhan-omniroute | grep -q '^run:'
test -x "$HOME/.termux/boot/lskhan-start"

# The bot must be restarted by runit after each crash.
log=$PREFIX/var/log/sv/lskhan-bot/current
for _ in $(seq 1 30); do
    [[ -f $log && $(grep -c 'FAKE BOT STARTED' "$log") -ge 2 ]] && break
    sleep 1
done
[[ $(grep -c 'FAKE BOT STARTED' "$log") -ge 2 ]]

bash termux/install.sh status
bash termux/install.sh logs 5

# Re-running the installer must be safe.
bash termux/install.sh
sv status lskhan-bot

bash termux/install.sh uninstall
test ! -d "$PREFIX/var/service/lskhan-bot"
test ! -d "$PREFIX/var/service/lskhan-omniroute"
test ! -e "$HOME/.termux/boot/lskhan-start"

echo "ALL TERMUX TESTS PASSED"
