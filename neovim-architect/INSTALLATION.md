# Installation

## Termux on Android (the owner's phone)

One paste. It updates Termux packages, so expect a few minutes:

```bash
pkg install -y git && cd ~ && { [ -d requirements.txt ] || git clone https://github.com/khansayang132-create/requirements.txt.git; } && cd requirements.txt && git pull --ff-only && bash neovim-architect/scripts/install.sh
```

Then:
1. **Icons:** download any Nerd Font `.ttf` (e.g. JetBrainsMono Nerd Font), copy it to `~/.termux/font.ttf`, and run `termux-reload-settings`. Or skip icons with `echo 'export NVIM_NERD_FONT=0' >> ~/.bashrc`.
2. **Clipboard:** install the *Termux:API* app (same store as Termux). The script already installs the `termux-api` package.
3. **Treesitter:** if `tree-sitter-cli` isn't in your Termux mirror, the script builds it with `cargo`. That needs `pkg install rust` and about 10 minutes the first time.

> Termux status: **NOT TESTED on a phone yet.** This setup was built and verified in an Ubuntu 24.04 x86_64 cloud container, because there is no Android device here. The Termux path uses `pkg` packages instead of downloads (Neovim, lua-language-server, stylua, clang, rust). After it runs, `scripts/verify.sh` writes a real report from your phone; please share it.

## Ubuntu / Debian / Mint / WSL

```bash
git clone https://github.com/khansayang132-create/requirements.txt.git && cd requirements.txt/neovim-architect
bash scripts/install.sh
exec $SHELL   # pick up ~/.local/bin on PATH
```

- System packages come from apt (uses `sudo` when not root). Neovim 0.12.6, tree-sitter 0.26.13, lua-language-server 3.19.2 and StyLua 2.6.0 are official release binaries, SHA256-checked, installed to `~/.local` with no system-wide changes.
- An existing Node or Python is reused, never duplicated. A command that already exists (e.g. pyright from uv) is skipped, not overwritten.

## Arch / Fedora / macOS

Same command. Packages come from pacman / dnf / brew. **NOT TESTED** here: these branches only differ in package names, listed in `install.sh`.

## Options

```
scripts/install.sh --no-packages   # config + plugins only (you manage tools)
scripts/install.sh --no-learning   # skip cloning the learning library
scripts/install.sh --no-verify     # skip the test run at the end
```

## What happens to my existing config?

If `~/.config/nvim` exists and isn't from this project, it is **copied** to `~/Developer/Neovim-Backups/<time>/` and then **moved** to `~/.config/nvim.pre-architect-<time>`. Nothing is deleted. `scripts/rollback.sh` brings it back; that round trip is tested by `tests/e2e-fresh-home.sh`.

## Exit codes

`0` ok · `1` failure (message says which step) · `2` bad arguments · `3` unsupported OS/CPU · `4` missing git/curl with `--no-packages` · `5` Neovim missing or older than 0.12.
