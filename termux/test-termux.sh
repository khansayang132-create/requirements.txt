#!/data/data/com.termux/files/usr/bin/bash
# CI test for termux/install.sh, run inside the termux/termux-docker image (a real Termux userland).
set -euxo pipefail

# Use Termux's main package server directly: pkg picks a random mirror, which may be mid-sync.
echo "deb https://packages-cf.termux.dev/apt/termux-main stable main" > "$PREFIX/etc/apt/sources.list"
for attempt in 1 2 3; do
    apt-get update -q >/dev/null && apt-get install -y -q python termux-services >/dev/null && break
    [[ $attempt == 3 ]] && exit 1
    sleep 10
done

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
test -f "$PREFIX/etc/profile.d/lskhan-wakelock.sh"

# The bot must be restarted by runit after each crash.
log=$PREFIX/var/log/sv/lskhan-bot/current
for _ in $(seq 1 30); do
    [[ -f $log && $(grep -c 'FAKE BOT STARTED' "$log") -ge 2 ]] && break
    sleep 1
done
[[ $(grep -c 'FAKE BOT STARTED' "$log") -ge 2 ]]

bash termux/install.sh status
bash termux/install.sh logs 5

# Simulate a phone restart without Termux:Boot: kill everything, then "open Termux" (a login shell).
sv down lskhan-bot lskhan-omniroute || true
pkill -f runsvdir || true
rm -f "$PREFIX/var/run/service-daemon.pid"
for f in "$PREFIX"/var/service/*/supervise "$PREFIX"/var/service/*/log/supervise; do rm -rf "$f"; done
sleep 2
if pgrep -f 'sleep 100000' >/dev/null; then pkill -f 'sleep 100000'; fi
bash -lc 'true'
back=0
for _ in $(seq 1 20); do
    if sv status lskhan-bot 2>/dev/null | grep -q '^run:' && sv status lskhan-omniroute 2>/dev/null | grep -q '^run:'; then back=1; break; fi
    sleep 1
done
[[ $back == 1 ]]

# Re-running the installer must be safe.
bash termux/install.sh
sv status lskhan-bot

bash termux/install.sh uninstall
test ! -d "$PREFIX/var/service/lskhan-bot"
test ! -d "$PREFIX/var/service/lskhan-omniroute"
test ! -e "$HOME/.termux/boot/lskhan-start"
test ! -e "$PREFIX/etc/profile.d/lskhan-wakelock.sh"

# --- Headroom (experimental) ---
# A failed build must not stop the bot. A stand-in pkg refuses Headroom's build tools.
mkdir -p "$HOME/fakebin"
printf '#!%s/bin/sh\necho "fake pkg refuses: $*" >&2\nexit 1\n' "$PREFIX" > "$HOME/fakebin/pkg"
chmod +x "$HOME/fakebin/pkg"
out=$(PATH=$HOME/fakebin:$PATH bash termux/install.sh --with-headroom 2>&1)
echo "$out"
grep -q 'Continuing without Headroom' <<<"$out"
sv status lskhan-bot | grep -q '^run:'
test ! -d "$PREFIX/var/service/lskhan-headroom"
test -z "$(grep '^HEADROOM_BASE_URL=.' .env || true)"

# A finished build (a stand-in that answers /health) becomes a service and the bot is pointed at it.
hr=$HOME/.lskhan-headroom
mkdir -p "$hr/bin"
cat > "$hr/bin/headroom" <<EOF
#!$PREFIX/bin/python
import sys, http.server
print("FAKE HEADROOM", sys.argv[1:], flush=True)
port = int(sys.argv[sys.argv.index("--port") + 1])
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
EOF
chmod +x "$hr/bin/headroom"
printf '#!%s/bin/sh\nexit 0\n' "$PREFIX" > "$hr/bin/python"   # passes the "core loads" check
chmod +x "$hr/bin/python"
touch "$hr/.installed"
printf 'OMNIROUTE_API_KEY=fake\nHEADROOM_BASE_URL=\n' >> .env
bash termux/install.sh --with-headroom
sv status lskhan-headroom | grep -q '^run:'
[[ $(curl -s -m 5 http://127.0.0.1:8765/health) == ok ]]
grep -qx 'HEADROOM_BASE_URL=http://127.0.0.1:8765/v1' .env
run=$PREFIX/var/service/lskhan-headroom/run
grep -q 'HEADROOM_BEACON=off' "$run"
grep -q -- '--host 127.0.0.1 --port 8765 --openai-api-url http://127.0.0.1:20128/v1' "$run"

# Re-running without the flag keeps Headroom and doesn't touch .env again.
bash termux/install.sh
sv status lskhan-headroom | grep -q '^run:'
[[ $(grep -c '^HEADROOM_BASE_URL=' .env) == 1 ]]
out=$(bash termux/install.sh status); grep -q 'Headroom answers' <<<"$out"
out=$(bash termux/install.sh logs headroom 5); grep -q 'FAKE HEADROOM' <<<"$out"

# If the build disappears, a re-run drops the service instead of leaving it crash-looping.
rm "$hr/.installed"
PATH=$HOME/fakebin:$PATH bash termux/install.sh
test ! -d "$PREFIX/var/service/lskhan-headroom"
sv status lskhan-bot | grep -q '^run:'

touch "$hr/.installed"
bash termux/install.sh --with-headroom
bash termux/install.sh uninstall
test ! -d "$PREFIX/var/service/lskhan-headroom"
test -d "$hr"   # the hours-long build is kept

echo "ALL TERMUX TESTS PASSED"
