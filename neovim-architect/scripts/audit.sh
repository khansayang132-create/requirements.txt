#!/usr/bin/env bash
# Phase Zero: writes reports/system-audit.md from values detected on THIS machine.
# Read-only: changes nothing outside reports/.
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "$0")/lib.sh"
case ":$PATH:" in *":$LOCAL_BIN:"*) ;; *) export PATH="$LOCAL_BIN:$PATH" ;; esac
detect_env
OUT="${1:-$ARCH_ROOT/reports/system-audit.md}"

ver() { # first line of a tool's version output, or MISSING
  local t="$1"; shift
  if have "$t"; then ( "$t" "${@:---version}" 2>&1 | grep -v '^Picked up' | head -1 ) || echo "present"
  else echo "MISSING"; fi
}
os_name() {
  if [[ "$OS_KIND" == termux ]]; then echo "Termux ${TERMUX_VERSION:-} on Android $(getprop ro.build.version.release 2>/dev/null)"
  elif [[ -f /etc/os-release ]]; then . /etc/os-release; echo "$PRETTY_NAME"
  else sw_vers -productVersion 2>/dev/null || uname -s; fi
}
mem() { free -h 2>/dev/null | awk '/Mem:/ {print $2" total, "$7" available"}' || echo unknown; }
cpu() { (lscpu 2>/dev/null | awk -F: '/Model name/ {gsub(/^ +/,"",$2); print $2; exit}') || sysctl -n machdep.cpu.brand_string 2>/dev/null || echo unknown; }

{
  echo "# System Audit"
  echo
  echo "Generated $(date -Iseconds) by \`scripts/audit.sh\`. All values detected, none assumed."
  echo
  echo "## Operating system and device"
  echo "| Item | Value |"; echo "|---|---|"
  echo "| Environment | $OS_KIND |"
  echo "| OS | $(os_name) |"
  echo "| Kernel | $(uname -sr) |"
  echo "| Architecture | $(uname -m) |"
  echo "| Package manager | ${PKG:-none detected} (privilege: ${SUDO:-root/user-owned prefix}) |"
  echo "| Shell | ${SHELL:-unknown} |"
  echo "| Terminal (TERM / COLORTERM) | ${TERM:-unset} / ${COLORTERM:-unset} |"
  echo "| CPU | $(cpu) ($(nproc 2>/dev/null || echo ?) cores) |"
  echo "| RAM | $(mem) |"
  echo "| Disk (home) | $(df -h "$HOME" | awk 'NR==2 {print $4" free of "$2}') |"
  echo
  echo "## Development tools"
  echo "| Tool | Detected |"; echo "|---|---|"
  for t in nvim vim git gh curl wget python3 node npm go rustc cargo gcc clang make cmake rg fd tree-sitter tmux; do
    case "$t" in go) v="$(ver go version)" ;; tmux) v="$(ver tmux -V)" ;; java) v="$(ver java -version)" ;; *) v="$(ver "$t")" ;; esac
    echo "| $t | ${v//|//} |"
  done
  echo "| java | $(ver java -version) |"
  echo "| clipboard | $(for c in xclip xsel wl-copy pbcopy termux-clipboard-set; do have $c && printf '%s ' $c; done; echo) |"
  echo
  echo "## Existing Neovim / Vim setup"
  echo "| Item | Value |"; echo "|---|---|"
  echo "| Config dir | $( [[ -e "$NVIM_CONFIG" ]] && echo "$NVIM_CONFIG ($( [[ -e "$NVIM_CONFIG/$MARKER" ]] && echo 'Neovim Architect' || echo 'foreign, backed up before install'))" || echo "none" ) |"
  echo "| init file | $(ls "$NVIM_CONFIG"/init.{lua,vim} 2>/dev/null | tr '\n' ' ' || true) |"
  echo "| Plugin manager | $( [[ -d "$NVIM_DATA/lazy/lazy.nvim" ]] && echo lazy.nvim || ([[ -d "$NVIM_DATA/site/pack/packer" ]] && echo packer) || echo none) |"
  echo "| Installed plugins | $(ls "$NVIM_DATA/lazy" 2>/dev/null | wc -l) |"
  echo "| ~/.vimrc / ~/.vim | $( [[ -e ~/.vimrc ]] && echo yes || echo no ) / $( [[ -e ~/.vim ]] && echo yes || echo no ) |"
  echo "| Language servers on PATH | $(for s in lua-language-server pyright-langserver typescript-language-server vscode-html-language-server vscode-css-language-server vscode-json-language-server yaml-language-server bash-language-server clangd gopls rust-analyzer jdtls marksman; do have $s && printf '%s ' $s; done; echo) |"
} > "$OUT"
ok "audit -> $OUT"
