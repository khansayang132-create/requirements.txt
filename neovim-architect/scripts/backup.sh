#!/usr/bin/env bash
# Timestamped backup of Neovim/Vim config and state to ~/Developer/Neovim-Backups.
# Usage: scripts/backup.sh [--with-plugins]   (also archives ~/.local/share/nvim)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "$0")/lib.sh"
[[ "${1:-}" == "" || "${1:-}" == "--with-plugins" ]] || die "usage: backup.sh [--with-plugins]" 2
dir="$(backup_nvim "${1:-}")"
ok "backup -> $dir"
cat "$dir/MANIFEST.txt"
