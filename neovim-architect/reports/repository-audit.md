# Repository Audit

Checked 2026-11-08 with real `git` fetches (last commit date of the default branch, newest tag via `git ls-remote`, README scanned for deprecation notices). The GitHub web UI and API were blocked by the session's network policy, so stars/issues/releases pages were **not** inspected; license and Neovim-version notes come from each README where noted.

Classes: **A** core IDE · **B** plugin · **C** learning resource · **D** optional frontend · **E** experimental · **F** unrelated application · **G** legacy / abandoned.

| # | Repository (as given) | Last commit | Newest tag | Class | Decision |
|---|---|---|---|---|---|
| 1 | ChristianChiarulli/LunarVim (→ LunarVim/LunarVim) | 2025-06-05 | 1.4.0 | A, G | **Not used.** No commits for ~17 months; built on the older nvim-treesitter `master` API that is frozen for Neovim 0.11. |
| 2 | NvChad/NvChad | 2026-10-25 | v2.5 | A | Viable, actively maintained. Not chosen (see architecture-decision.md): its base46 theme cache and starter-repo layout add a layer between you and plain Lua config. |
| 3 | pta2002/nixvim (→ nix-community/nixvim) | 2026-10-17 | – | A | Not applicable: Nix is not installed here and does not run on Termux. |
| 4 | Sly-Harvey/nixvim | 2026-10-01 | – | A, E | Not applicable (personal Nix config, same reason). |
| 5 | nanotee/nvim-lua-guide | 2025-09-03 | – | C | **Cloned** to Neovim-Learning/06. Upstream notes it is now largely superseded by `:help lua-guide`, which is linked too. |
| 6 | wbthomason/packer.nvim | 2023-08-24 | – | B, G | **Not used.** README: "This repository is currently unmaintained … recommended to use one of the following plugin managers instead". Replaced by lazy.nvim. |
| 7 | lewis6991/impatient.nvim | 2023-05-05 | v0.2 | B, G | **Not used.** Its job is built into Neovim since 0.9 as `vim.loader.enable()`, which `init.lua` calls. |
| 8 | mhinz/neovim-remote | 2022-05-19 | v2.5.1 | B, G | **Not used.** Neovim has had `nvim --server ... --remote` built in since 0.7. |
| 9 | vhyrro/neorg (→ nvim-neorg/neorg) | 2026-08-14 | v9.6.4 | B | Maintained, but needs luarocks / rocks.nvim, which is fragile on Termux. **Orgmode chosen instead.** |
| 10 | nvim-orgmode/orgmode | 2026-10-31 | 0.7.5 | B | **Installed** (lazy-loaded on `.org`). Pure Lua. |
| 11 | tversteeg/registers.nvim | – | – | B | **Unreachable**: `git clone` and the web URL both return HTTP 403 from this environment (repo removed, renamed or private). Replaced by Telescope's registers picker (`<leader>fR`) plus which-key's built-in `"` / `@` register popup. |
| 12 | folke/todo-comments.nvim | 2025-11-10 | v1.5.0 | B | **Installed.** |
| 13 | Olical/conjure | 2026-11-08 | v4.60.0 | B | **Installed, off by default** (`NVIM_CONJURE=1`). Only useful for Lisps; no Lisp runtimes are on this machine. |
| 14 | rohit-px2/nvui | 2022-02-13 | v0.3.1 | D, G | **Not installed.** Abandoned Qt GUI; Windows/X11 only, no Android. Terminal Neovim is the target. |
| 15 | iggredible/Learn-Vim | 2026-09-07 | – | C | **Cloned** to 01. |
| 16 | mhinz/vim-galore | 2021-04-16 | v1.3 | C | **Cloned** to 02. Not updated since 2021, but its subject (core Vim) is stable. |
| 17 | DanilaMihailov/vim-tips-wiki | 2020-07-02 | v1.1.0 | C | **Cloned** to 03 and registered as `:help vtw-*` pages. |
| 18 | steveshogren/10-minute-vim-exercises | 2017-08-11 | – | C | **Cloned** to 04. |
| 19 | hakluke/how-to-exit-vim | 2026-08-05 | – | C | **Cloned** to 05. |
| 20 | oakes/vim_cubed | 2020-10-22 | – | E | **Not installed.** Novelty (Vim rendered on a 3D cube), needs a desktop GL stack. |
| 21 | programmerhat/vim-online-editor | 2024-03-20 | – | F | **Not installed.** A browser page, not a Neovim component. |
| 22 | a327ex/SNKRX | 2022-06-11 | – | F | **Not installed.** A LÖVE2D game; unrelated to Neovim. |

## Plugins added that were not in the list (all maintained, verified installable)

lazy.nvim (v11, the replacement for packer), nvim-treesitter `main`, nvim-lspconfig, blink.cmp, friendly-snippets, conform.nvim, telescope.nvim + telescope-fzf-native, gitsigns.nvim, vim-fugitive, toggleterm.nvim, which-key.nvim, lualine.nvim, bufferline.nvim, nvim-tree.lua, nvim-web-devicons, tokyonight.nvim, fidget.nvim, persistence.nvim, plenary.nvim. Exact commits are pinned in `config/nvim/lazy-lock.json`; reasons are in `docs/plugins.md`.

## Security notes

- No repository's install script was executed. Plugins are Lua sources loaded by Neovim; the only plugin build steps are `make` for telescope-fzf-native (a small C file) and `:TSUpdate` (compiles grammar C sources with the local compiler).
- blink.cmp downloads a prebuilt fuzzy-matcher binary for its release tag; if that fails it uses its pure-Lua matcher.
- Neovim, tree-sitter CLI and lua-language-server binaries are SHA256-pinned in `scripts/lib.sh`. The hashes were computed from the downloads here, because the release-digest API was blocked. Treat them as trust-on-first-use, and compare once against the digests on the GitHub release page if you want an independent check.
