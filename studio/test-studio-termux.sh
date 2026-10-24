#!/data/data/com.termux/files/usr/bin/bash
# CI test for studio/run.sh inside the termux/termux-docker image (a real Termux userland):
# jaclang and jac-client install without llvmlite, and the prebuilt page is served without bun.
set -euxo pipefail

echo "deb https://packages-cf.termux.dev/apt/termux-main stable main" > "$PREFIX/etc/apt/sources.list"
for attempt in 1 2 3; do
    apt-get update -q >/dev/null && apt-get install -y -q python >/dev/null && break
    [[ $attempt == 3 ]] && exit 1
    sleep 10
done

rm -rf "$HOME/bot"; cp -r /mnt/repo "$HOME/bot"; cd "$HOME/bot"
rm -rf studio/.jac .env

# Stand-in for bot.py: the bot's packages (python-telegram-bot, openai) are already on the owner's
# phone, and building their Rust parts here would take most of the job. tests/test_studio.py covers
# the real AI path.
cat > bot.py <<'EOF'
import os, pathlib
for line in (pathlib.Path(__file__).parent / ".env").read_text().splitlines():  # like load_dotenv()
    if "=" in line:
        os.environ.setdefault(*line.split("=", 1))
routes, MODEL, CINTA_PERSONA, DEFAULT_TOPIC = [], "", "persona", "topik"
def hook_task(topic): return topic
def script_task(topic): return topic
async def chat(**kwargs): raise RuntimeError("no AI in this test")
EOF
: > requirements.txt

bash studio/test-studio.sh
