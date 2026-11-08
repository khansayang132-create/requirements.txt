# shellcheck shell=bash
# shellcheck disable=SC2034  # variables below are used by the scripts that source this
# Shared helpers for Neovim Architect scripts. Source, don't execute.
set -euo pipefail

ARCH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_SRC="$ARCH_ROOT/config/nvim"
NVIM_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/nvim"
NVIM_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/nvim"
NVIM_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/nvim"
LOCAL_BIN="$HOME/.local/bin"
LOCAL_OPT="$HOME/.local/opt"
BACKUP_ROOT="$HOME/Developer/Neovim-Backups"
LEARN_ROOT="$HOME/Developer/Neovim-Learning"
MARKER=".neovim-architect"   # file that marks a config directory as ours
LOG_DIR="$ARCH_ROOT/logs"

# ---- Pinned upstream releases (official GitHub release assets) -------------
# SHA256 values were computed from the downloads on 2026-11-08 and are checked
# on every install. To upgrade: bump the version, download, sha256sum, update.
NVIM_MIN="0.12.0"
NVIM_VERSION="0.12.6"
NVIM_SHA256_x86_64="474430d53e6264f6d6dd18db42d6dc9df3a1b56ca9e88a325bbf860e1a811d87"
NVIM_SHA256_aarch64="8f1f64a0bdb97247034038c3823c6cbad5bdf9ecd5751b85494b71c3ee04c815"
TS_MIN="0.26.1"
TS_VERSION="0.26.13"
TS_SHA256_x86_64="c9c8bef027658d60249ca4fc0663578ceb2e2029346bb8702e091e20d7716475"
TS_SHA256_aarch64="088c5ebf4b4b558c8abfd167c9c4f9669c2f9070da3edd9c0157dc051d77ac5d"
LUALS_VERSION="3.19.2"
LUALS_SHA256_x86_64="93ad326b10f6c00911dd8c450fa098332dbd8f9f45d1052f5636a2d54479b947"
LUALS_SHA256_aarch64="17b8e401a874440adeb649e5024c364f2bb9d15156c74a40e56d1ae9a1b2e4f2"

STYLUA_VERSION="2.6.0"
STYLUA_SHA256_x86_64="a485f72bbfa22e4642e77a84b5edc2611a5cab7477b34e2e709dd8f78e919895"
STYLUA_SHA256_aarch64="8e67539e5fdf7a81cd03cf592b0df18d3bb96ee17a5ea5d9bf67b86387b903b0"
GOPLS_VERSION="v0.24.0"   # go install (Go module proxy verifies checksums via sum.golang.org)

# npm-installed language servers and formatter (pinned majors), as
# "package@major:command". Skipped when the command already exists
# (e.g. pyright installed via pipx/uv), so nothing is overwritten.
NPM_TOOLS=(
  "pyright@1:pyright-langserver"
  "typescript@5:tsc"
  "typescript-language-server@5:typescript-language-server"
  "vscode-langservers-extracted@4:vscode-json-language-server"
  "yaml-language-server@1:yaml-language-server"
  "bash-language-server@5:bash-language-server"
  "prettier@3:prettier"
)

# ---- Output ------------------------------------------------------------------
if [[ -t 1 ]]; then C_G=$'\e[32m'; C_Y=$'\e[33m'; C_R=$'\e[31m'; C_B=$'\e[1m'; C_0=$'\e[0m'
else C_G=""; C_Y=""; C_R=""; C_B=""; C_0=""; fi
info() { printf '%s==>%s %s\n' "$C_B" "$C_0" "$*"; }
ok()   { printf '%s ok%s  %s\n' "$C_G" "$C_0" "$*"; }
warn() { printf '%swarn%s %s\n' "$C_Y" "$C_0" "$*" >&2; }
die()  { printf '%sFAIL%s %s\n' "$C_R" "$C_0" "$*" >&2; exit "${2:-1}"; }
have() { command -v "$1" >/dev/null 2>&1; }
ts_now() { date +%Y%m%d-%H%M%S; }

# version_ge A B -> true if A >= B (dotted numeric)
version_ge() { [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" == "$2" ]]; }

# ---- Environment detection ----------------------------------------------------
detect_env() {
  OS_KIND="unknown"; PKG=""; ARCH="$(uname -m)"
  [[ "$ARCH" == "arm64" ]] && ARCH="aarch64"
  if [[ -n "${TERMUX_VERSION:-}" || "${PREFIX:-}" == *com.termux* ]]; then
    OS_KIND="termux"; PKG="pkg"
  elif [[ "$(uname -s)" == "Darwin" ]]; then
    OS_KIND="macos"; PKG="brew"
  elif [[ "$(uname -s)" == "Linux" ]]; then
    OS_KIND="linux"
    if have apt-get; then PKG="apt"
    elif have pacman; then PKG="pacman"
    elif have dnf; then PKG="dnf"
    fi
    grep -qi microsoft /proc/version 2>/dev/null && OS_KIND="wsl"
  fi
  SUDO=""
  if [[ "$OS_KIND" != "termux" && "$OS_KIND" != "macos" && "$(id -u)" != "0" ]]; then
    if have sudo; then SUDO="sudo"; else SUDO="__none__"; fi
  fi
  export OS_KIND PKG ARCH SUDO
}

nvim_version() { nvim --version 2>/dev/null | head -1 | sed -E 's/^NVIM v?([0-9.]+).*/\1/'; }

# ---- Downloads ----------------------------------------------------------------
# fetch_verified URL DEST SHA256
fetch_verified() {
  local url="$1" dest="$2" want="$3" got
  curl -fsSL --retry 3 -o "$dest" "$url" || die "download failed: $url"
  got="$(sha256sum "$dest" | cut -d' ' -f1)"
  [[ "$got" == "$want" ]] || { rm -f "$dest"; die "checksum mismatch for $url (got $got)"; }
  ok "verified sha256 $(basename "$dest")"
}

# ---- Backups ------------------------------------------------------------------
# backup_nvim [--with-plugins] -> prints backup dir
backup_nvim() {
  local with_plugins="${1:-}" dir; dir="$BACKUP_ROOT/$(ts_now)"
  mkdir -p "$dir"
  local saved=()
  for src in "$NVIM_CONFIG" "$HOME/.vimrc" "$HOME/.vim" "$NVIM_STATE"; do
    if [[ -e "$src" ]]; then
      local name; name="$(echo "${src#"$HOME"/}" | tr '/' '_')"
      cp -a "$src" "$dir/$name"; saved+=("$src -> $dir/$name")
    fi
  done
  if [[ "$with_plugins" == "--with-plugins" && -e "$NVIM_DATA" ]]; then
    tar -C "$(dirname "$NVIM_DATA")" -czf "$dir/nvim-data.tar.gz" "$(basename "$NVIM_DATA")"
    saved+=("$NVIM_DATA -> $dir/nvim-data.tar.gz")
  fi
  {
    echo "created: $(date -Iseconds)"
    echo "host: $(uname -a)"
    printf 'saved: %s\n' "${saved[@]:-nothing (no existing config)}"
  } > "$dir/MANIFEST.txt"
  echo "$dir"
}
