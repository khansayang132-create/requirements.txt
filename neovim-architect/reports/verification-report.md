# Verification Report

- Generated: 2026-11-08T20:24:10+00:00 by `scripts/verify.sh` (raw log: `logs/verify-20261108-202343.log`)
- Host: Linux 6.18.44-fc-v310 x86_64, os=linux, pkg=apt
- Neovim: NVIM v0.12.6

| # | Test | Status | Evidence |
|---|---|---|---|
| 1 | executable | **PASS** | /root/.local/bin/nvim: NVIM v0.12.6 |
| 2 | config | **PASS** | all Lua files parse; no startup errors |
| 3 | plugins | **PASS** | 22 plugins installed and loaded: nvim-lspconfig, telescope.nvim, plenary.nvim, telescope-fzf-native.nvim, todo-comments.nvim, lazy.nvim, persistence.nvim, tokyonight.nvim, toggleterm.nvim, blink.cmp, vim-fugitive, lualine.nvim, friendly-snippets, nvim-treesitter, bufferline.nvim, conform.nvim, nvim-tree.lua, which-key.nvim, nvim-web-devicons, orgmode, fidget.nvim, gitsigns.nvim |
| 4 | health | **PASS** | vim.lsp: 0 error, 6 warn; vim.treesitter: 0 error, 0 warn; vim.provider: 0 error, 7 warn; lazy: 0 error, 0 warn; nvim-treesitter: 0 error, 0 warn; telescope: 0 error, 0 warn; blink.cmp: 0 error, 1 warn; conform: 0 error, 0 warn; which-key: 0 error, 2 warn |
| 5 | lsp | **PASS** | ok: lua_ls attached, 1 diagnostics; pyright attached, 1 diagnostics; ts_ls attached, 1 diagnostics; bashls attached, 0 diagnostics; jsonls attached, 0 diagnostics; yamlls attached, 0 diagnostics; html attached, 0 diagnostics; cssls attached, 0 diagnostics; clangd attached, 1 diagnostics; rust_analyzer attached, 0 diagnostics; gopls attached, 0 diagnostics; lua_ls go-to-definition ok / failed:  / not installed:  |
| 6 | completion | **PASS** | lua_ls completion for 'gre': 1 items, includes greet(): true; snippet expand -> "local name = value"; friendly-snippets lua files: 2; blink.cmp loaded: true |
| 7 | search | **PASS** | find_files: 11/11 sample files; live_grep 'ARCHITECT_MARKER': 1 hit (expect 1); buffers picker: 1; fzf-native sorter: true |
| 8 | git | **PASS** | gitsigns hunks: 2; fugitive branch: "master" |
| 9 | terminal | **PASS** | opened: true, shell running: true, closed: true |
| 10 | treesitter | **PASS** | parsers 21/21 installed (missing: ); lua parse: chunk; highlighter active: true |
| 10b | format | **PASS** | lua format run: true -> "local x = { 1, 2 }\ if x then\ \9print(x)\ end"; available: c=clang-format, css=prettier, go=gofmt, html=prettier, json=prettier, lua=stylua, py=ruff_format+black, rs=rustfmt, sh=shfmt, ts=prettier, yaml=prettier |
| 11 | startup | **PASS** | median 131.7 ms with config vs 117.2 ms for nvim --clean (5 TTY runs each) |
| 12 | rollback | **PASS** | latest backup /root/Developer/Neovim-Backups/20261108-202342; rollback.sh --list ok |

Statuses come only from the run above. PARTIAL = works, but something optional is missing (see evidence).
