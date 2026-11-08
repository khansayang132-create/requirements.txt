#!/usr/bin/env bash
# Update plugins and parsers safely: backup (with plugin data) -> Lazy update ->
# TSUpdate -> verify. If verification fails, roll back automatically.
# The new lazy-lock.json is copied into the repo so the update is tracked in git.
# Usage: scripts/update.sh [--config-only]   (just re-sync config from this repo)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "$0")/lib.sh"
case ":$PATH:" in *":$LOCAL_BIN:"*) ;; *) export PATH="$LOCAL_BIN:$PATH" ;; esac
have nvim || die "nvim not installed; run scripts/install.sh" 5

if [[ "${1:-}" == "--config-only" ]]; then
  exec bash "$ARCH_ROOT/scripts/install.sh" --no-packages --no-learning
fi

backup="$(backup_nvim --with-plugins)"; ok "backup -> $backup"
info "updating plugins"
nvim --headless "+Lazy! update" +qa
info "updating treesitter parsers"
nvim --headless -c 'lua require("nvim-treesitter").update():wait(900000)' -c qa

if bash "$ARCH_ROOT/scripts/verify.sh"; then
  cp "$NVIM_CONFIG/lazy-lock.json" "$CONFIG_SRC/lazy-lock.json"
  ok "updated; lazy-lock.json copied to repo (commit it)"
else
  warn "verification failed after update; rolling back to $backup"
  bash "$ARCH_ROOT/scripts/rollback.sh" "$backup"
  exit 1
fi
