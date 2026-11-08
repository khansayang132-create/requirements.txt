# Troubleshooting

Start with `:checkhealth` (or `scripts/verify.sh` from a shell). The raw output of every run is in `logs/`.

| Symptom | Cause | Fix |
|---|---|---|
| `Neovim Architect needs Neovim 0.12 or newer` | Old nvim earlier on PATH | `type -a nvim`. On Linux the installer puts 0.12.6 in `~/.local/bin`; make sure that comes first (`exec $SHELL` after install). Termux: `pkg upgrade neovim`. |
| Boxes or `?` instead of icons | Terminal font isn't a Nerd Font | Termux: install a Nerd Font as `~/.termux/font.ttf`, then `termux-reload-settings`. Or run `export NVIM_NERD_FONT=0` for plain text. |
| No syntax colours, `:TSUpdate` errors | No `tree-sitter` CLI or no C compiler | `tree-sitter --version` must be ≥ 0.26.1 and `cc --version` must work. Termux: `pkg install clang rust`, then re-run install.sh (it builds the CLI with cargo). |
| LSP doesn't start for a language | Server binary not installed | `:checkhealth vim.lsp`. The config only enables servers it can find on PATH; install one (docs/languages.md) and restart Neovim. |
| `npm EEXIST` during install | A command of the same name exists (e.g. pyright from pipx/uv) | Fixed: the installer now skips tools that already exist. Re-run it. |
| Yank doesn't reach the system clipboard | No clipboard provider | Linux X11: `xclip`. Wayland: `wl-clipboard`. Termux: `pkg install termux-api` plus the Termux:API app. Then `:checkhealth provider`. |
| Completion menu works but fuzzy matching is slow | blink.cmp's binary didn't load (common on Termux) | It falls back to Lua automatically. `:checkhealth blink.cmp` shows which one is in use. |
| Formatting does nothing | Formatter not installed | `:ConformInfo` lists what's available per filetype. |
| Plugin update broke something | Upstream change | `update.sh` already rolls back if verification fails. Manually: `scripts/rollback.sh --list`, then `scripts/rollback.sh <dir>`, or `:Lazy restore` to return to `lazy-lock.json`. |
| Slow startup | A plugin loading eagerly | `nvim --startuptime /tmp/st.log +qa`, then `:Lazy profile`. |

## Rollback procedure

1. `scripts/rollback.sh --list` shows backups (newest first), each marked `config` or `config + plugins`.
2. `scripts/rollback.sh` restores the newest config backup, or pass a directory.
3. The config you are replacing is backed up first, then moved to `~/.config/nvim.rolled-back-<time>`. Nothing is deleted.
4. To go back to your original pre-Architect config, pick the oldest backup. The installer also moved that config to `~/.config/nvim.pre-architect-<time>`.
