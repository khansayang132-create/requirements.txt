#!/usr/bin/env bash
# Restore a Neovim config from ~/Developer/Neovim-Backups. Nothing is deleted:
# the current config is backed up first and moved to nvim.rolled-back-<ts>.
# Usage: scripts/rollback.sh --list
#        scripts/rollback.sh [BACKUP_DIR]     (default: newest backup with a config)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "$0")/lib.sh"

cfg_name="$(echo "${NVIM_CONFIG#"$HOME"/}" | tr '/' '_')"   # e.g. .config_nvim

list() {
  local found=0
  for d in $(ls -1d "$BACKUP_ROOT"/*/ 2>/dev/null | sort -r); do
    d="${d%/}"; [[ -f "$d/MANIFEST.txt" ]] || continue
    local has="no config"; [[ -d "$d/$cfg_name" ]] && has="config"
    [[ -f "$d/nvim-data.tar.gz" ]] && has="$has + plugins"
    echo "$d  ($has)"; found=1
  done
  (( found )) || { echo "no backups in $BACKUP_ROOT"; return 1; }
}

if [[ "${1:-}" == "--list" ]]; then list; exit $?; fi

src="${1:-}"
if [[ -z "$src" ]]; then
  for d in $(ls -1d "$BACKUP_ROOT"/*/ 2>/dev/null | sort -r); do
    [[ -d "${d%/}/$cfg_name" ]] && { src="${d%/}"; break; }
  done
fi
[[ -n "$src" && -d "$src/$cfg_name" ]] || die "no backup containing $cfg_name found (try --list)" 2

info "restoring $src/$cfg_name -> $NVIM_CONFIG"
safety="$(backup_nvim)"; ok "current state saved to $safety"
[[ -e "$NVIM_CONFIG" ]] && mv "$NVIM_CONFIG" "$NVIM_CONFIG.rolled-back-$(ts_now)"
cp -a "$src/$cfg_name" "$NVIM_CONFIG"
if [[ -f "$src/nvim-data.tar.gz" ]]; then
  [[ -e "$NVIM_DATA" ]] && mv "$NVIM_DATA" "$NVIM_DATA.rolled-back-$(ts_now)"
  tar -C "$(dirname "$NVIM_DATA")" -xzf "$src/nvim-data.tar.gz"
  ok "plugin data restored"
fi
ok "rolled back. Previous config kept at $NVIM_CONFIG.rolled-back-*"
