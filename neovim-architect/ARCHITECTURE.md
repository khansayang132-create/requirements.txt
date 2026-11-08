# Architecture

The full decision, with alternatives compared, is in [reports/architecture-decision.md](reports/architecture-decision.md). In short:

- **Neovim 0.12+**, a custom modular Lua config, and **lazy.nvim** with a committed `lazy-lock.json`.
- **No Mason.** Language servers come from pkg/apt/npm/go/rustup, because Mason's binaries don't run on Termux. A server is enabled only when its executable runs (`lua/lsk/servers.lua`).
- **nvim-treesitter `main`.** Parsers are compiled locally. If GitHub tarball downloads are blocked, `lua/lsk/ts_git_fallback.lua` git-fetches the same pinned revisions.

```
init.lua
├── lsk/options.lua     editor settings, diagnostics, clipboard detection
├── lsk/keymaps.lua     plugin-independent mappings (all with desc)
├── lsk/autocmds.lua    yank highlight, last position, per-language indent
├── lsk/project.lua     project root detection + project picker
├── lsk/servers.lua     language server table (shared with tests)
├── lsk/ts_parsers.lua  parser list (shared with install + tests)
├── lsk/lazy.lua        bootstrap lazy.nvim
└── plugins/
    ├── ui.lua          tokyonight, lualine, bufferline, nvim-tree, which-key, fidget
    ├── editor.lua      telescope (+fzf), todo-comments, persistence, toggleterm
    ├── treesitter.lua  highlight, indent, folds
    ├── lsp.lua         vim.lsp.enable + LspAttach mappings
    ├── coding.lua      blink.cmp + friendly-snippets, conform.nvim
    ├── git.lua         gitsigns, fugitive
    └── notes.lua       orgmode, conjure (opt-in)
```

## Rules for changing it

1. Edit `config/nvim` in this repo, not `~/.config/nvim` (the installer overwrites that copy).
2. `scripts/update.sh --config-only` applies the edit and runs the tests.
3. Commit the config change together with `lazy-lock.json`.
