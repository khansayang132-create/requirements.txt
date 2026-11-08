# Architecture Decision

**Decision: Option C. A custom, modular Lua configuration on Neovim 0.12, managed by lazy.nvim.**

## Constraints that decided it

1. **The real target is a phone.** The owner works from Android in Termux, with no Linux computer. Anything Mason downloads is a glibc binary and does not run on Android's bionic libc, and luarocks builds are fragile there. The setup must get its tools from `pkg`, npm or local compilation.
2. **The ecosystem moved.** nvim-treesitter's maintained branch (`main`) requires Neovim 0.12 and tree-sitter-cli 0.26.1+, and the old `master` branch is frozen. Configs and distributions written against `master` are on a dead end.
3. **Upgrades must not destroy the setup.** That needs a lockfile, backups and a config you can read.

## Options compared

| Criterion | A. NvChad v2.5 | B. LunarVim 1.4 | C. Custom + lazy.nvim | D. NixVim |
|---|---|---|---|---|
| Maintenance | Active (2026-10) | Stalled since 2025-06 | Every plugin active | Active |
| Reliability on Termux | Uses Mason by default (glibc binaries) | Same, plus stale | Tools from pkg/npm; Mason not used | No Nix on Android |
| Install complexity | Low on desktop | Low, but its own installer script | One script in this repo | Needs Nix |
| Performance | Good | OK | ~100 ms startup measured (see verification report) | Good |
| Plugin compatibility (Neovim 0.12, treesitter `main`) | Tracks upstream | Behind | Chosen to match | Tracks upstream |
| Customization | Via NvChad's override layer | Via `lvim` layer | Plain Lua, nothing to fight | Nix language |
| Upgrade safety | Starter repo plus NvChad core updates | Poor | `lazy-lock.json` pinned, auto-rollback in `update.sh` | Excellent (Nix generations) |
| Hardware needs | Low | Low | Low | High (Nix store) |
| Documentation | Good | Aging | This repo's docs plus each plugin's `:help` | Good |
| Long-term maintainability | Depends on NvChad | Poor | ~500 lines you own | Requires Nix skills |

## Why not packer?

packer.nvim's README declares it unmaintained since August 2023 and recommends lazy.nvim or pckr. lazy.nvim (v11.17.5, active) offers lazy-loading, a lockfile and headless `Lazy! restore/sync/update`, which `install.sh` and `update.sh` use. Neovim 0.12's built-in `vim.pack` was considered too, but it has no lazy-loading or lockfile-restore workflow yet, so lazy.nvim stays the safer choice.

## Shape of the system

```
init.lua  ->  lsk/options, keymaps, autocmds   (no plugins needed)
          ->  lsk/lazy  ->  plugins/*.lua      (one file per area)
                 ui · editor · treesitter · lsp · coding · git · notes
```

- LSP uses Neovim's own `vim.lsp.config` / `vim.lsp.enable`. Server definitions come from nvim-lspconfig, and a server is enabled only when its executable exists.
- Only one distribution lives in `~/.config/nvim`. Anything already there is backed up and moved aside, never merged.

## Debugging (DAP): deliberately not installed

No debug adapter (debugpy, codelldb, delve, js-debug) is present on this machine, and on Termux most adapters have no build. Following the brief ("configure debugging only where the necessary debug adapters and language runtimes exist"), nvim-dap is left out. To add it later, create `plugins/dap.lua` with `mfussenegger/nvim-dap` plus one adapter, for example `python3 -m pip install debugpy` and `nvim-dap-python`.
