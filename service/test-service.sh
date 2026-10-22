#!/usr/bin/env bash
# CI test for service/install.sh on a real Ubuntu machine with systemd (run as a normal sudo user).
set -euxo pipefail
cd "$(dirname "$0")/.."

# A fake token: the bot really starts, Telegram rejects it, the bot exits, systemd restarts it.
printf 'TELEGRAM_BOT_TOKEN=123456:fake\nOMNIROUTE_API_KEY=test\n' > .env

# Stand-in for OmniRoute (the real one isn't needed to test the service wiring).
printf '#!/bin/sh\nexec sleep infinity\n' | sudo tee /usr/local/bin/omniroute >/dev/null
sudo chmod +x /usr/local/bin/omniroute

sudo bash service/install.sh --with-omniroute

systemctl is-active lskhan-omniroute
systemctl is-enabled lskhan-bot
systemctl is-enabled lskhan-omniroute
grep -q 'After=network-online.target lskhan-omniroute.service' /etc/systemd/system/lskhan-bot.service
grep -q "^User=$USER$" /etc/systemd/system/lskhan-bot.service
systemd-analyze verify /etc/systemd/system/lskhan-bot.service /etc/systemd/system/lskhan-omniroute.service
.venv/bin/python -c 'import telegram, openai, dotenv'

# The bot must actually run from the venv and reach Telegram (which rejects the fake token)...
for _ in $(seq 1 30); do
    journalctl -u lskhan-bot --no-pager | grep -qiE 'InvalidToken|Unauthorized|rejected' && break
    sleep 2
done
journalctl -u lskhan-bot --no-pager | tail -20
journalctl -u lskhan-bot --no-pager | grep -qiE 'InvalidToken|Unauthorized|rejected'
# ...and systemd must bring it back after it exits.
for _ in $(seq 1 30); do
    [[ $(systemctl show -p NRestarts --value lskhan-bot) -ge 1 ]] && break
    sleep 2
done
[[ $(systemctl show -p NRestarts --value lskhan-bot) -ge 1 ]]

sudo bash service/install.sh uninstall
test ! -e /etc/systemd/system/lskhan-bot.service
test ! -e /etc/systemd/system/lskhan-omniroute.service
if systemctl is-active lskhan-bot; then echo "bot still running"; exit 1; fi

echo "ALL SERVICE TESTS PASSED"
