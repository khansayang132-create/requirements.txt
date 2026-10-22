#!/data/data/com.termux/files/usr/bin/bash
# CI test for `termux/install.sh --with-headroom` with a REAL Headroom build (no stand-in), run inside
# the termux/termux-docker image. Slow (it compiles the Rust packages), so it has its own workflow.
# Proves: the build finishes in Termux, the service answers, and a chat request from the bot's side
# goes through Headroom to an OpenAI-style gateway (a stand-in for OmniRoute) and back.
set -euxo pipefail

echo "deb https://packages-cf.termux.dev/apt/termux-main stable main" > "$PREFIX/etc/apt/sources.list"
for attempt in 1 2 3; do
    apt-get update -q >/dev/null && apt-get install -y -q python termux-services curl >/dev/null && break
    [[ $attempt == 3 ]] && exit 1
    sleep 10
done

rm -rf "$HOME/bot"; cp -r /mnt/repo "$HOME/bot"; cd "$HOME/bot"

# Stand-in OmniRoute on 20128: answers chat completions and logs the key it was given.
cat > "$HOME/fake-omniroute.py" <<'EOF'
import json, http.server
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        print("GATEWAY GOT", self.path, self.headers.get("authorization"), flush=True)
        out = json.dumps({"id": "x", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "halo dari omniroute"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()
        self.send_response(200); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out))); self.end_headers(); self.wfile.write(out)
http.server.HTTPServer(("127.0.0.1", 20128), H).serve_forever()
EOF
printf '#!%s/bin/sh\nexec python -u %s\n' "$PREFIX" "$HOME/fake-omniroute.py" > "$PREFIX/bin/omniroute"
chmod +x "$PREFIX/bin/omniroute"

# A bot that just stays up; the real bot needs a Telegram token.
printf 'import time\nprint("FAKE BOT STARTED", flush=True)\ntime.sleep(100000)\n' > bot.py
: > requirements.txt
printf 'TELEGRAM_BOT_TOKEN=123456:fake\nOMNIROUTE_API_KEY=test-key\nOMNIROUTE_BASE_URL=http://127.0.0.1:20128/v1\nHEADROOM_BASE_URL=\n' > .env

# A finished build cached by the workflow (in /mnt/cache) skips the ~50 min compile. The installer
# skips pkg once a build exists, so install Termux's prebuilt parts here.
hr=$HOME/.lskhan-headroom
if [[ -f /mnt/cache/headroom.tar ]]; then
    pkg install -y python-onnxruntime python-numpy python-cryptography >/dev/null
    tar -xf /mnt/cache/headroom.tar -C "$HOME"
    echo "RESTORED CACHED HEADROOM BUILD"
fi

start=$SECONDS
bash termux/install.sh --with-headroom
echo "INSTALL TOOK $(( (SECONDS - start) / 60 )) min"

if [[ ! -f $HOME/.lskhan-headroom/.installed ]]; then
    set +e
    echo "=== DIAGNOSTICS ==="
    python --version
    dpkg -s python-onnxruntime | grep -E '^(Status|Version)'
    dpkg -L python-onnxruntime | grep -iE 'site-packages/[^/]+$|dist-info' | head
    python -c 'import onnxruntime, sys; print("system import ok", onnxruntime.__version__, onnxruntime.__file__)'
    "$HOME/.lskhan-headroom/bin/python" -c 'import onnxruntime; print("venv import ok", onnxruntime.__version__)'
    "$HOME/.lskhan-headroom/bin/python" -c 'import sys; print(sys.path)'
    "$HOME/.lskhan-headroom/bin/pip" list 2>/dev/null | grep -iE 'onnx|numpy|crypto'
    cat "$HOME/.lskhan-headroom/pyvenv.cfg"
    exit 1
fi

# Save the build for the next run, before anything below can fail.
if [[ -d /mnt/cache && ! -f /mnt/cache/headroom.tar ]]; then
    tar -cf /mnt/cache/headroom.tar -C "$HOME" .lskhan-headroom
fi

export SVDIR=$PREFIX/var/service
sv status lskhan-headroom | grep -q '^run:'
grep -qx 'HEADROOM_BASE_URL=http://127.0.0.1:8765/v1' .env
health=""
for _ in $(seq 1 300); do
    health=$(curl -s -m 5 http://127.0.0.1:8765/health || true)
    [[ -n $health ]] && break
    sleep 1
done
if [[ -z $health ]]; then
    set +e
    echo "=== HEADROOM NOT ANSWERING ==="
    sv status lskhan-headroom
    cat "$PREFIX/var/service/lskhan-headroom/run"
    tail -n 150 "$PREFIX/var/log/sv/lskhan-headroom/current"
    echo "=== FOREGROUND RUN ==="
    HEADROOM_BEACON=off timeout 120 "$hr/bin/headroom" proxy --host 127.0.0.1 --port 8766 2>&1 | tail -n 80
    exit 1
fi
echo "HEADROOM ANSWERED AFTER $(( SECONDS - start ))s TOTAL"
[[ $(python -c 'import json,sys; print(json.loads(sys.argv[1])["status"])' "$health") == healthy ]]

# The bot's request path: POST /v1/chat/completions to Headroom, forwarded to "OmniRoute".
reply=$(curl -s -m 60 http://127.0.0.1:8765/v1/chat/completions \
    -H 'authorization: Bearer test-key' -H 'content-type: application/json' \
    -d '{"model":"cc/claude-opus-5-5","messages":[{"role":"user","content":"halo"}]}')
echo "$reply"
[[ $(python -c 'import json,sys; print(json.loads(sys.argv[1])["choices"][0]["message"]["content"])' "$reply") == "halo dari omniroute" ]]
out=$(tail -n 50 "$PREFIX/var/log/sv/lskhan-omniroute/current")
grep -q 'GATEWAY GOT /v1/chat/completions Bearer test-key' <<<"$out"

# Same request with the real openai client the bot uses, if it's installed in Headroom's venv.
"$HOME/.lskhan-headroom/bin/python" - <<'EOF'
from openai import OpenAI
c = OpenAI(api_key="test-key", base_url="http://127.0.0.1:8765/v1", max_retries=0)
r = c.chat.completions.create(model="cc/claude-opus-5-5", messages=[{"role": "user", "content": "halo"}])
assert r.choices[0].message.content == "halo dari omniroute", r
print("OPENAI CLIENT THROUGH HEADROOM OK")
EOF

bash termux/install.sh status
echo "REAL HEADROOM BUILD TEST PASSED"
