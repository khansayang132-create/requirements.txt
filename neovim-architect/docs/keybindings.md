# Keybindings

Leader is **Space**. Press Space and wait: which-key shows every group. `<leader>fk` searches all mappings live.
Open this sheet inside Neovim with `<leader>hc`.

## Files, search, projects
| Keys | Action |
|---|---|
| `<leader><space>` / `<leader>ff` | Find files (project root) |
| `<leader>fg` | Live grep (project root, ripgrep) |
| `<leader>fw` | Grep word under cursor |
| `<leader>fb` | Buffers |
| `<leader>fr` | Recent files |
| `<leader>f/` | Fuzzy search in current buffer |
| `<leader>fs` / `<leader>fS` | Document / workspace symbols (LSP) |
| `<leader>fd` | Diagnostics list |
| `<leader>fh` | Help pages |
| `<leader>fk` | Search keymaps |
| `<leader>fR` | Registers (replaces registers.nvim) |
| `<leader>e` / `<leader>E` | File explorer / reveal current file |
| `<leader>po` | Open project (git repos under ~/Developer, ~/projects, ~/src, ~) |
| `<leader>pr` | cd to project root (`:ProjectRoot`) |

## Buffers and windows
| Keys | Action |
|---|---|
| `Shift-l` / `Shift-h` | Next / previous buffer |
| `<leader>bd` | Delete buffer |
| `<leader>bp` | Pick buffer |
| `<leader>bo` | Close other buffers |
| `Ctrl-h/j/k/l` | Move between windows |
| `<leader>w` / `<leader>q` | Save / quit window |

## Code (LSP, completion, formatting)
| Keys | Action |
|---|---|
| `gd` / `gD` | Go to definition / declaration |
| `grr` / `<leader>cR` | References (built-in / Telescope) |
| `gri` | Go to implementation |
| `K` | Hover documentation |
| `Ctrl-s` (insert) | Signature help |
| `grn` / `<leader>cr` | Rename symbol |
| `gra` / `<leader>ca` | Code action |
| `gO` | Document symbols (built-in) |
| `]d` / `[d` | Next / previous diagnostic |
| `<leader>cd` | Line diagnostics float |
| `<leader>xq` | Diagnostics to quickfix |
| `<leader>cf` | Format buffer / selection |
| `<leader>uf` | Toggle format on save (default on) |
| `<leader>uh` | Toggle inlay hints |
| `<leader>ci` | LSP health/info |
| `Ctrl-space` | Open completion menu |
| `Ctrl-n` / `Ctrl-p` | Next / previous completion item |
| `Ctrl-y` | Accept completion |
| `Ctrl-e` | Close completion menu |
| `Tab` / `Shift-Tab` | Jump between snippet placeholders |

## Git
| Keys | Action |
|---|---|
| `]h` / `[h` | Next / previous hunk |
| `<leader>gs` / `<leader>gr` | Stage / reset hunk |
| `<leader>gp` | Preview hunk |
| `<leader>gb` | Blame line (full) |
| `<leader>ub` | Toggle inline blame |
| `<leader>gd` | Diff against index |
| `<leader>gg` | Git status (fugitive; `s` stage, `cc` commit) |
| `<leader>gB` | Blame whole file |
| `<leader>gD` | 3-way merge diff (conflicts) |
| `]x` / `[x` | Next / previous conflict marker |
| `<leader>gl` | Git log graph |
| `<leader>gc` | Browse commits |

## Terminal
| Keys | Action |
|---|---|
| `Ctrl-\` | Toggle terminal (follows Neovim's cwd) |
| `<leader>tf` / `<leader>th` / `<leader>tv` | Floating / horizontal / vertical terminal |
| `Esc Esc` | Leave terminal mode |

## TODOs, notes, sessions, docs
| Keys | Action |
|---|---|
| `]t` / `[t` | Next / previous TODO/FIXME comment |
| `<leader>tt` | Search TODO comments |
| `<leader>on` | Open notes inbox (`~/Developer/Notes/inbox.org`) |
| `<leader>oc` / `<leader>oa` | Org capture / agenda |
| `<leader>of` | Find a note |
| `<leader>qs` / `<leader>ql` | Restore session for this dir / last session |
| `<leader>qd` | Don't save this session |
| `<leader>hc` | This cheat sheet |
| `<leader>hl` | Learning library index |
| `<leader>?` | Buffer-local keymaps (which-key) |

Conflict check: no custom mapping overrides a Neovim default except `Ctrl-h/j/k/l` (window moves),
`Shift-h/l` (screen top/bottom → buffer switch) and `Esc` (also clears search highlight).
