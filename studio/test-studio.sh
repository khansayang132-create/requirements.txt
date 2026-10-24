#!/usr/bin/env bash
# CI test for studio/run.sh (and studio/build.sh with --build).
#   bash studio/test-studio.sh --build   Ubuntu: prebuilt is current, it builds, it serves
#   bash studio/test-studio.sh           Termux (termux-docker): setup installs, it serves
# Run from a writable copy of the repo: run.sh writes STUDIO_ACCESS_CODE into .env.
set -euxo pipefail
cd "$(dirname "$0")/.."
PORT=8123
LOG="${TMPDIR:-/tmp}/studio-test.log"

[[ "$(bash studio/run.sh hash)" == "$(cat studio/prebuilt/SOURCE_HASH)" ]] \
    || { echo "studio/prebuilt is stale: run bash studio/build.sh and commit"; exit 1; }
bash studio/run.sh setup
bash studio/run.sh setup  # idempotent
if [[ ${1:-} == --build ]]; then
    bash studio/build.sh
fi
rm -f .env
STUDIO_PORT=$PORT bash studio/run.sh > "$LOG" 2>&1 &
trap 'kill %1 2>/dev/null || true; cat "$LOG"' EXIT
for _ in $(seq 1 120); do
    curl -sf "http://127.0.0.1:$PORT/" >/dev/null && break
    kill -0 %1 2>/dev/null || { echo "Studio exited"; exit 1; }
    sleep 1
done
grep -q '^STUDIO_ACCESS_CODE=.' .env
grep -q 'Client bundle already built' "$LOG"  # served the prebuilt bundle, built nothing

python3 - "$PORT" "$(grep '^STUDIO_ACCESS_CODE=' .env | cut -d= -f2-)" <<'EOF'
import json, re, sys, urllib.request
port, code = sys.argv[1], sys.argv[2]
base = f"http://127.0.0.1:{port}"
html = urllib.request.urlopen(base + "/").read().decode()
assert "<title>LSKhan Studio</title>" in html, html[:300]
script = re.search(r'src="(/static/client\.js[^"]*)"', html).group(1)
assert urllib.request.urlopen(base + script).status == 200

def walker(name, **args):
    req = urllib.request.Request(f"{base}/walker/{name}", json.dumps(args).encode(),
                                 {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))["data"]["reports"][0]

status = walker("AiStatus", code="")
assert status["locked"] is False and status["access"] is False, status
assert walker("Generate", kind="hook", code="wrong")["ok"] is False
assert walker("AiStatus", code=code)["access"] is True
print("studio OK")
EOF
# Served the prebuilt files as they are: a rebuild would have fetched bun and written source maps.
diff <(cd studio/prebuilt && printf '%s\n' * | grep -vx SOURCE_HASH) <(cd studio/.jac/client/dist && printf '%s\n' *)
[[ ! -e studio/.jac/bin/bun || ${1:-} == --build ]]
