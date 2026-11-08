#!/usr/bin/env bash
# Neovim Architect installer. Safe to re-run: every step checks before acting,
# existing configs are backed up (never deleted), downloads are SHA256-checked.
#
# Usage: scripts/install.sh [--no-packages] [--no-learning] [--no-verify]
#   --no-packages  skip OS/npm/tooling installs (config + plugins only)
#   --no-learning  skip cloning the learning library
#   --no-verify    skip scripts/verify.sh at the end
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "$0")/lib.sh"

DO_PACKAGES=1; DO_LEARNING=1; DO_VERIFY=1
for a in "$@"; do
  case "$a" in
    --no-packages) DO_PACKAGES=0 ;;
    --no-learning) DO_LEARNING=0 ;;
    --no-verify) DO_VERIFY=0 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) die "unknown option: $a" 2 ;;
  esac
done

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/install-$(ts_now).log"
exec > >(tee -a "$LOG") 2>&1
info "log: $LOG"

detect_env
info "environment: os=$OS_KIND pkg=${PKG:-none} arch=$ARCH"
case "$OS_KIND" in
  termux|linux|wsl|macos) ;;
  *) die "unsupported environment ($(uname -s)). Supported: Termux, Linux (apt/pacman/dnf), WSL, macOS." 3 ;;
esac
[[ "$ARCH" == "x86_64" || "$ARCH" == "aarch64" ]] || die "unsupported CPU architecture: $ARCH" 3
for t in git curl; do have "$t" || [[ $DO_PACKAGES == 1 ]] || die "$t is required" 4; done

mkdir -p "$LOCAL_BIN" "$LOCAL_OPT"
case ":$PATH:" in *":$LOCAL_BIN:"*) ;; *) export PATH="$LOCAL_BIN:$PATH" ;; esac

# ---- 1. System packages --------------------------------------------------------
pkg_install() {
  case "$PKG" in
    pkg)    pkg install -y "$@" ;;
    apt)    $SUDO apt-get install -y --no-install-recommends "$@" ;;
    pacman) $SUDO pacman -S --needed --noconfirm "$@" ;;
    dnf)    $SUDO dnf install -y "$@" ;;
    brew)   brew install "$@" ;;
  esac
}

# Runtimes are only added when their command is missing, so an existing
# Node/Python (nvm, /opt, pyenv...) is never duplicated or shadowed.
runtime_pkgs() { # args: node-pkg... -- python-pkg...
  local out=() part=node
  for p in "$@"; do
    if [[ "$p" == "--" ]]; then part=py; continue; fi
    if [[ $part == node ]]; then have node && have npm || out+=("$p")
    else have python3 || out+=("$p"); fi
  done
  echo "${out[@]}"
}

# Package lists are intentionally word-split ($rt, $(runtime_pkgs ...)).
# shellcheck disable=SC2046,SC2086
install_system_packages() {
  if [[ "$SUDO" == "__none__" ]]; then
    warn "not root and no sudo: skipping system packages (install them yourself, see DEPENDENCIES.md)"
    return
  fi
  info "installing system packages via $PKG"
  local rt
  case "$PKG" in
    pkg)
      pkg update -y
      rt="$(runtime_pkgs nodejs-lts -- python)"
      pkg install -y git curl wget unzip tar ripgrep fd clang make cmake $rt \
        neovim lua-language-server stylua shfmt termux-api
      # Optional, may not exist in every Termux mirror:
      pkg install -y tree-sitter-cli 2>/dev/null || warn "pkg tree-sitter-cli unavailable; will try cargo"
      pkg install -y ruff 2>/dev/null || warn "pkg ruff unavailable; Python formatting via black/LSP only"
      ;;
    apt)
      $SUDO apt-get update -qq
      rt="$(runtime_pkgs nodejs npm -- python3)"
      pkg_install git curl wget unzip tar ca-certificates ripgrep fd-find build-essential make cmake \
        python3-venv clangd clang-format shellcheck shfmt xclip $rt
      # Debian names the binary fdfind
      if have fdfind && ! have fd; then ln -sf "$(command -v fdfind)" "$LOCAL_BIN/fd"; fi
      ;;
    pacman) pkg_install git curl wget unzip tar ripgrep fd base-devel cmake clang shfmt xclip neovim tree-sitter-cli lua-language-server stylua $(runtime_pkgs nodejs npm -- python) ;;
    dnf)    pkg_install git curl wget unzip tar ripgrep fd-find gcc make cmake clang-tools-extra shfmt xclip $(runtime_pkgs nodejs npm -- python3) ;;
    brew)   pkg_install git ripgrep fd cmake neovim tree-sitter-cli lua-language-server stylua shfmt $(runtime_pkgs node -- python) ;;
  esac
}

# ---- 2. Neovim -----------------------------------------------------------------
install_neovim() {
  local cur; cur="$(nvim_version || true)"
  if [[ -n "$cur" ]] && version_ge "$cur" "$NVIM_MIN"; then ok "neovim $cur already installed ($(command -v nvim))"; return; fi
  [[ -n "$cur" ]] && warn "neovim $cur is older than $NVIM_MIN"
  if [[ "$OS_KIND" == "termux" || "$OS_KIND" == "macos" ]]; then
    die "package-manager neovim is ${cur:-missing}; need >= $NVIM_MIN. Run: $PKG upgrade neovim" 5
  fi
  local asset="nvim-linux-x86_64" sha="$NVIM_SHA256_x86_64"
  [[ "$ARCH" == "aarch64" ]] && asset="nvim-linux-arm64" && sha="$NVIM_SHA256_aarch64"
  local tmp; tmp="$(mktemp -d)"
  fetch_verified "https://github.com/neovim/neovim/releases/download/v$NVIM_VERSION/$asset.tar.gz" "$tmp/nvim.tgz" "$sha"
  rm -rf "$LOCAL_OPT/nvim-$NVIM_VERSION"; mkdir -p "$LOCAL_OPT/nvim-$NVIM_VERSION"
  tar -xzf "$tmp/nvim.tgz" -C "$LOCAL_OPT/nvim-$NVIM_VERSION" --strip-components=1
  ln -sfn "$LOCAL_OPT/nvim-$NVIM_VERSION/bin/nvim" "$LOCAL_BIN/nvim"
  rm -rf "$tmp"; hash -r
  ok "neovim $(nvim_version) -> $LOCAL_BIN/nvim"
}

# ---- 3. tree-sitter CLI (needed to compile parsers) ----------------------------
install_tree_sitter() {
  local cur; cur="$(tree-sitter --version 2>/dev/null | awk '{print $2}' || true)"
  if [[ -n "$cur" ]] && version_ge "$cur" "$TS_MIN"; then ok "tree-sitter $cur already installed"; return; fi
  if [[ "$OS_KIND" == "termux" || "$OS_KIND" == "macos" ]]; then
    if have cargo; then
      info "building tree-sitter-cli $TS_VERSION with cargo (several minutes)"
      cargo install --locked "tree-sitter-cli@$TS_VERSION" && ok "tree-sitter via cargo" && return
    fi
    warn "no tree-sitter CLI: parsers won't compile. Termux: pkg install rust && re-run."
    return
  fi
  local asset="tree-sitter-linux-x64" sha="$TS_SHA256_x86_64"
  [[ "$ARCH" == "aarch64" ]] && asset="tree-sitter-linux-arm64" && sha="$TS_SHA256_aarch64"
  local tmp; tmp="$(mktemp -d)"
  fetch_verified "https://github.com/tree-sitter/tree-sitter/releases/download/v$TS_VERSION/$asset.gz" "$tmp/ts.gz" "$sha"
  gzip -dc "$tmp/ts.gz" > "$LOCAL_BIN/tree-sitter"; chmod +x "$LOCAL_BIN/tree-sitter"; rm -rf "$tmp"
  ok "tree-sitter $(tree-sitter --version | awk '{print $2}')"
}

# ---- 4. Language servers & formatters -------------------------------------------
install_lua_ls() {
  if have lua-language-server; then ok "lua-language-server already installed"; return; fi
  [[ "$OS_KIND" == "termux" || "$OS_KIND" == "macos" ]] && { warn "lua-language-server missing (install via $PKG)"; return; }
  local a="x64" sha="$LUALS_SHA256_x86_64"; [[ "$ARCH" == "aarch64" ]] && a="arm64" && sha="$LUALS_SHA256_aarch64"
  local tmp dest="$LOCAL_OPT/lua-language-server-$LUALS_VERSION"; tmp="$(mktemp -d)"
  fetch_verified "https://github.com/LuaLS/lua-language-server/releases/download/$LUALS_VERSION/lua-language-server-$LUALS_VERSION-linux-$a.tar.gz" "$tmp/l.tgz" "$sha"
  rm -rf "$dest"; mkdir -p "$dest"; tar -xzf "$tmp/l.tgz" -C "$dest"; rm -rf "$tmp"
  ln -sfn "$dest/bin/lua-language-server" "$LOCAL_BIN/lua-language-server"
  ok "lua-language-server $LUALS_VERSION"
}

install_stylua() {
  have stylua && { ok "stylua already installed"; return; }
  [[ "$OS_KIND" == "termux" || "$OS_KIND" == "macos" ]] && { warn "stylua missing (install via $PKG)"; return; }
  have unzip || { warn "unzip missing: no stylua"; return; }
  local sha="$STYLUA_SHA256_x86_64"; [[ "$ARCH" == "aarch64" ]] && sha="$STYLUA_SHA256_aarch64"
  local tmp; tmp="$(mktemp -d)"
  fetch_verified "https://github.com/JohnnyMorganz/StyLua/releases/download/v$STYLUA_VERSION/stylua-linux-$ARCH.zip" "$tmp/s.zip" "$sha"
  unzip -o -q "$tmp/s.zip" -d "$tmp" && install -m 755 "$tmp/stylua" "$LOCAL_BIN/stylua"; rm -rf "$tmp"
  ok "stylua $STYLUA_VERSION"
}

install_npm_tools() {
  have npm || { warn "npm missing: skipping JS/TS/HTML/CSS/JSON/YAML/Bash/Python servers"; return; }
  local prefix=() todo=() entry
  [[ "$OS_KIND" != "termux" ]] && prefix=(--prefix "$HOME/.local")
  for entry in "${NPM_TOOLS[@]}"; do
    if have "${entry#*:}"; then ok "${entry#*:} already installed ($(command -v "${entry#*:}"))"
    else todo+=("${entry%%:*}"); fi
  done
  (( ${#todo[@]} )) || return 0
  info "npm install: ${todo[*]}"
  npm install -g "${prefix[@]}" --no-fund --no-audit "${todo[@]}" >/dev/null && ok "npm tools installed"
}

install_python_tools() {
  have ruff && { ok "ruff already installed"; return; }
  [[ "$OS_KIND" == "termux" ]] && return
  have python3 || return
  local venv="$HOME/.local/share/neovim-architect/venv"
  python3 -m venv "$venv" 2>/dev/null || { warn "python3-venv missing: no ruff"; return; }
  "$venv/bin/pip" install -q "ruff>=0.6,<1" && ln -sf "$venv/bin/ruff" "$LOCAL_BIN/ruff" && ok "ruff (venv)"
}

install_rust_tools() {
  # rustup ships a rust-analyzer proxy that fails until the component exists
  if have rustup && ! rust-analyzer --version >/dev/null 2>&1; then
    rustup component add rust-analyzer rustfmt >/dev/null 2>&1 && ok "rust-analyzer via rustup" \
      || warn "rustup component add rust-analyzer failed"
  fi
}

install_go_tools() {
  have go || return 0
  have gopls && { ok "gopls already installed"; return; }
  GOBIN="$LOCAL_BIN" go install "golang.org/x/tools/gopls@$GOPLS_VERSION" && ok "gopls $GOPLS_VERSION" \
    || warn "go install gopls failed"
}

ensure_path_in_shell() {
  [[ "$OS_KIND" == "termux" ]] && return
  local rc="$HOME/.bashrc"; [[ "${SHELL:-}" == */zsh ]] && rc="$HOME/.zshrc"
  grep -q 'neovim-architect: PATH' "$rc" 2>/dev/null && return
  printf '\n# neovim-architect: PATH\ncase ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac\n' >> "$rc"
  ok "added ~/.local/bin to PATH in $rc"
}

# ---- 5. Config ------------------------------------------------------------------
install_config() {
  if [[ -e "$NVIM_CONFIG" && ! -e "$NVIM_CONFIG/$MARKER" ]]; then
    local b; b="$(backup_nvim)"
    ok "backed up existing config to $b"
    mv "$NVIM_CONFIG" "$NVIM_CONFIG.pre-architect-$(ts_now)"
  elif [[ -e "$NVIM_CONFIG/$MARKER" ]]; then
    local b; b="$(backup_nvim)"; ok "backed up current Architect config to $b"
  fi
  mkdir -p "$NVIM_CONFIG"
  cp -a "$CONFIG_SRC/." "$NVIM_CONFIG/"
  cp "$ARCH_ROOT/docs/keybindings.md" "$NVIM_CONFIG/KEYBINDINGS.md"
  echo "installed $(date -Iseconds) from $ARCH_ROOT" > "$NVIM_CONFIG/$MARKER"
  ok "config -> $NVIM_CONFIG"
}

install_plugins() {
  if [[ -f "$CONFIG_SRC/lazy-lock.json" ]]; then
    info "installing plugins at the commits pinned in lazy-lock.json"
    nvim --headless "+Lazy! restore" +qa
  else
    info "no lazy-lock.json yet: installing latest and pinning"
    nvim --headless "+Lazy! sync" +qa
    cp "$NVIM_CONFIG/lazy-lock.json" "$CONFIG_SRC/lazy-lock.json"
  fi
  info "compiling treesitter parsers"
  nvim --headless -c 'lua local ok,ts=pcall(require,"nvim-treesitter"); if ok and vim.fn.executable("tree-sitter")==1 then ts.install(require("lsk.ts_parsers")):wait(900000) end' -c qa
  local missing
  missing="$(nvim --headless -c 'lua local i=require("nvim-treesitter").get_installed(); local n=0; for _,p in ipairs(require("lsk.ts_parsers")) do if not vim.list_contains(i,p) then n=n+1 end end; io.stdout:write(n)' -c qa 2>/dev/null)"
  if [[ "$missing" != "0" ]] && have tree-sitter; then
    warn "$missing parsers failed to download; retrying via git fetch (same pinned revisions)"
    nvim --headless -c 'lua require("lsk.ts_git_fallback").run()' -c qa
  fi
  ok "plugins + parsers"
}

# ---- 6. Learning library ----------------------------------------------------------
install_learning() { bash "$ARCH_ROOT/scripts/learning.sh"; }

link_project() {
  mkdir -p "$HOME/Developer"
  local link="$HOME/Developer/Neovim-Architect"
  if [[ "$ARCH_ROOT" == "$link" ]]; then return; fi
  if [[ -L "$link" || ! -e "$link" ]]; then ln -sfn "$ARCH_ROOT" "$link"; ok "$link -> $ARCH_ROOT"
  else warn "$link exists and is not a symlink; leaving it alone"; fi
}

# ---- Run ---------------------------------------------------------------------------
if [[ $DO_PACKAGES == 1 ]]; then
  install_system_packages
  install_neovim
  install_tree_sitter
  install_lua_ls
  install_stylua
  install_npm_tools
  install_python_tools
  install_rust_tools
  install_go_tools
  ensure_path_in_shell
else
  have nvim || die "nvim not found and --no-packages given" 5
fi
version_ge "$(nvim_version)" "$NVIM_MIN" || die "nvim $(nvim_version) < $NVIM_MIN" 5
install_config
install_plugins
link_project
[[ $DO_LEARNING == 1 ]] && install_learning
info "done. Launch with: nvim"
[[ $DO_VERIFY == 1 ]] && exec bash "$ARCH_ROOT/scripts/verify.sh"
exit 0
