# Changelog

## 1.0.0 — 2026-11-08

First release: Neovim 0.12.6, lazy.nvim, 23 plugin specs (22 installed; conjure is opt-in), 11 language servers, 21 treesitter parsers.

Bugs found by the test suite and fixed before release:
- **LSP servers silently never started** for ts_ls, html, cssls, jsonls and yamlls. nvim-lspconfig builds their `cmd` with a function, which an "is the binary on PATH" check can't read. Fix: each server names its executable explicitly (`lsk/servers.lua`).
- **rust-analyzer looked installed but wasn't.** rustup ships a proxy that exits with an error until the component is added. Fix: the server counts as present only if `--version` runs; the installer adds the component.
- **Installer stopped on `npm EEXIST`** when pyright already existed (installed via uv). Fix: npm tools whose command already exists are skipped, never overwritten.
- **Installer would duplicate Node/Python** from apt when a newer one was already on PATH. Fix: runtimes are only installed when missing.
- **Treesitter parsers failed behind a proxy that blocks GitHub tarballs** (HTTP 403). Fix: `lsk/ts_git_fallback.lua` git-fetches the same pinned revisions and compiles locally. nvim-treesitter reloads its parser table on install, so the override is applied in the `User TSUpdate` hook.
- **Headless installs raced** with interactive auto-install. Fix: the plugin only auto-installs parsers when a UI is attached.
- **Startup timing could hang** on a hit-enter prompt. Fix: hard 30 s timeout per run.
