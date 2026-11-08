# Plugins

Managed by lazy.nvim. Exact commits are pinned in [`config/nvim/lazy-lock.json`](../config/nvim/lazy-lock.json). `:Lazy` shows load state and timing.

| Plugin | Area | Loads on | Why this one |
|---|---|---|---|
| folke/lazy.nvim | manager | startup | Maintained successor to packer, with lockfile and lazy-loading |
| folke/tokyonight.nvim | theme | startup | Full treesitter/LSP highlight coverage |
| nvim-lualine/lualine.nvim | statusline | VeryLazy | Shows branch, diff, diagnostics, LSP |
| akinsho/bufferline.nvim | buffers | VeryLazy | Buffer tabs with diagnostics; hidden when only one buffer |
| nvim-tree/nvim-tree.lua | explorer | `<leader>e` | Git-aware tree, follows cwd |
| nvim-tree/nvim-web-devicons | icons | with UI | Disabled when `NVIM_NERD_FONT=0` |
| folke/which-key.nvim | discovery | VeryLazy | Pop-up of every mapping; also shows registers on `"` and `@` |
| j-hui/fidget.nvim | notifications | VeryLazy | LSP progress and `vim.notify` |
| nvim-telescope/telescope.nvim | search | `<leader>f…` | Files, grep, buffers, symbols, registers |
| nvim-telescope/telescope-fzf-native.nvim | search | with telescope | Native fuzzy sorter (built with `make`) |
| nvim-lua/plenary.nvim | library | dependency | Required by telescope and todo-comments |
| nvim-treesitter/nvim-treesitter (`main`) | syntax | startup | Parser manager plus queries for built-in treesitter |
| neovim/nvim-lspconfig | LSP | BufReadPre | Server definitions for `vim.lsp.enable` |
| saghen/blink.cmp | completion | InsertEnter | Fast completion, signature help, built-in snippet support |
| rafamadriz/friendly-snippets | snippets | with blink | Snippet library for many languages |
| stevearc/conform.nvim | formatting | BufWritePre | Per-language formatters, LSP fallback |
| lewis6991/gitsigns.nvim | git | BufReadPre | Signs, hunks, blame, staging |
| tpope/vim-fugitive | git | `:Git` | Status, commit, blame, 3-way merge |
| akinsho/toggleterm.nvim | terminal | `Ctrl-\` | Float/split terminals that follow cwd |
| folke/todo-comments.nvim | productivity | BufReadPost | Highlights and searches TODO/FIXME/NOTE |
| folke/persistence.nvim | sessions | BufReadPre | Per-directory session restore |
| nvim-orgmode/orgmode | notes | `.org` / `<leader>o…` | Agenda and capture, pure Lua |
| Olical/conjure | REPL | Lisp filetypes | **Off by default** (`NVIM_CONJURE=1`) |

## Considered and not used

packer.nvim (unmaintained), impatient.nvim (built in as `vim.loader`), neovim-remote (built in as `nvim --remote`), registers.nvim (unreachable, replaced by `<leader>fR`), Neorg (luarocks), Mason (its binaries don't run on Termux), nvim-dap (no debug adapters present; see architecture-decision.md).

## Adding a plugin

Create `config/nvim/lua/plugins/<name>.lua` returning a lazy.nvim spec, run `scripts/update.sh --config-only`, and commit the updated `lazy-lock.json`.
