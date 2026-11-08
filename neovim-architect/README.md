# Neovim Architect

A reproducible, tested Neovim 0.12 IDE: LSP for 11 languages, treesitter, completion and snippets, formatting, git, fuzzy search, terminal, org notes, sessions, and a local learning library. One script installs it on **Termux (Android)**, Ubuntu/Debian/WSL, Arch, Fedora or macOS. Another proves it works.

```bash
cd neovim-architect
bash scripts/install.sh      # backup -> install -> plugins -> learning library -> verify
nvim                         # press Space and wait to see every shortcut
```

| Want to… | Run |
|---|---|
| Install or repair | `scripts/install.sh` (safe to re-run) |
| Check it works | `scripts/verify.sh` → `reports/verification-report.md` |
| Update plugins | `scripts/update.sh` (backs up, updates, verifies, auto-rolls back on failure) |
| Apply config edits from this repo | `scripts/update.sh --config-only` |
| Back up now | `scripts/backup.sh [--with-plugins]` |
| Undo | `scripts/rollback.sh --list`, then `scripts/rollback.sh [dir]` |
| Audit a machine | `scripts/audit.sh` → `reports/system-audit.md` |

## Layout

```
config/nvim/        the Neovim config (copied to ~/.config/nvim), lazy-lock.json pins every plugin
scripts/            install · verify · update · backup · rollback · audit · learning
reports/            system / repository audits, architecture decision, install + verification reports
docs/               keybindings · plugins · languages · troubleshooting
tests/              verify.lua (in-editor checks), e2e-fresh-home.sh, language samples
logs/               install/verify logs (git-ignored)
```

Also created in your home folder: `~/Developer/Neovim-Architect` (a link here), `~/Developer/Neovim-Learning`, `~/Developer/Neovim-Backups` and `~/Developer/Notes`.

Read next: [INSTALLATION.md](INSTALLATION.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [docs/keybindings.md](docs/keybindings.md) · [reports/verification-report.md](reports/verification-report.md)
