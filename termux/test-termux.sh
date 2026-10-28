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
# runsv outlives runsvdir and keeps writing supervise/; a real restart kills it too, and rm races it otherwise.
pkill -x runsv || true
for _ in $(seq 1 20); do pgrep -x runsv >/dev/null || break; sleep 0.5; done
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

# check: talks to OmniRoute with the key from .env. A stand-in OmniRoute that only accepts one key:
cat > "$HOME/fake_omni.py" <<'PYEOF'
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("authorization") != "Bearer good-key":
            self.send_response(401); self.end_headers(); return
        b = json.dumps({"data": [{"id": "cc/claude-opus-5-5"}]}).encode()
        self.send_response(200); self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
ThreadingHTTPServer(("127.0.0.1", 20199), H).serve_forever()
PYEOF
python "$HOME/fake_omni.py" &
fake_omni=$!
sleep 2
printf 'TELEGRAM_BOT_TOKEN=123456:fake\nOMNIROUTE_BASE_URL=http://127.0.0.1:20199/v1\nOMNIROUTE_API_KEY=good-key\nOMNIROUTE_MODEL=cc/claude-opus-5-5\n' > .env
bash termux/install.sh check | grep -q 'OmniRoute is up'
sed -i 's/^OMNIROUTE_API_KEY=.*/OMNIROUTE_API_KEY=bad-key/' .env
if bash termux/install.sh check; then echo "check must fail on a refused key"; exit 1; fi
sed -i 's/^OMNIROUTE_API_KEY=.*/OMNIROUTE_API_KEY=good-key/' .env

# update: updates OmniRoute through npm, restarts the services, and ends with a passing check.
printf '#!%s/bin/sh\necho "$*" >> "%s/npm-calls"\n' "$PREFIX" "$HOME" > "$PREFIX/bin/npm"
chmod +x "$PREFIX/bin/npm"
rm -rf .git   # the CI copy has no usable remote; update must still work and say so
bash termux/install.sh update | tee "$HOME/update.out"
grep -q 'install -g omniroute@latest' "$HOME/npm-calls"
grep -q 'not a git clone' "$HOME/update.out"
grep -q 'OmniRoute is up' "$HOME/update.out"
kill "$fake_omni"

# Website publishing: refuses to go public by accident, then runs ngrok as a service.
printf '#!%s/bin/sh\necho "FAKE NGROK $*"\nexec sleep 100000\n' "$PREFIX" > "$PREFIX/bin/ngrok"
chmod +x "$PREFIX/bin/ngrok"
printf 'TELEGRAM_BOT_TOKEN=123456:fake\nNGROK_AUTHTOKEN=tok123\nSITE_DOMAIN=https://demo.ngrok-free.app/\n' > .env
if bash termux/install.sh site; then echo "site without SITE_AUTH must be refused"; exit 1; fi
printf 'SITE_AUTH="owner:short"\n' >> .env
if bash termux/install.sh site; then echo "short password must be refused"; exit 1; fi
sed -i 's/^SITE_AUTH=.*/SITE_AUTH="owner:correct-horse-battery"/' .env
bash termux/install.sh site
conf=$HOME/.config/lskhan/ngrok.yml
[[ $(stat -c %a "$conf") == 600 ]]
grep -q 'url: https://demo.ngrok-free.app$' "$conf"
grep -q 'url: 8080' "$conf"
grep -q 'type: basic-auth' "$conf"
grep -q '"owner:correct-horse-battery"' "$conf"
grep -q 'dns_resolver_ips' "$conf"
sv status lskhan-site | grep -q '^run:'
for _ in $(seq 1 20); do grep -q 'FAKE NGROK start --config' "$PREFIX/var/log/sv/lskhan-site/current" 2>/dev/null && break; sleep 1; done
grep -q "FAKE NGROK start --config $conf --log stdout lskhan-site" "$PREFIX/var/log/sv/lskhan-site/current"
bash termux/install.sh status | grep -q lskhan-site

bash termux/install.sh uninstall
test ! -d "$PREFIX/var/service/lskhan-bot"
test ! -d "$PREFIX/var/service/lskhan-site"
test ! -d "$PREFIX/var/service/lskhan-omniroute"
! compgen -G "$PREFIX/var/service/.lskhan-*" >/dev/null   # no half-removed folders left
bash termux/install.sh uninstall   # idempotent: a second run is a no-op
test ! -e "$HOME/.termux/boot/lskhan-start"
test ! -e "$PREFIX/etc/profile.d/lskhan-wakelock.sh"

echo "ALL TERMUX TESTS PASSED"
