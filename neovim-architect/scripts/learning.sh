#!/usr/bin/env bash
# Builds ~/Developer/Neovim-Learning: shallow clones of the learning repos,
# kept in their original structure, plus an index. Re-running only updates.
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "$0")/lib.sh"

# dir|repo|what it teaches
REPOS=(
  "01-Learn-Vim|iggredible/Learn-Vim|Book-length Vim course: modes, motions, registers, macros, Vimscript."
  "02-Vim-Galore|mhinz/vim-galore|Deep reference on Vim concepts and tips (last updated 2021, still accurate for core Vim)."
  "03-Vim-Tips-Wiki|DanilaMihailov/vim-tips-wiki|1500+ Vim Tips Wiki pages as native help files: try :help vtw-<TAB>."
  "04-Vim-Exercises|steveshogren/10-minute-vim-exercises|Short daily drills for building muscle memory (2017, timeless)."
  "05-Vim-Basics|hakluke/how-to-exit-vim|The classic: every way to exit Vim. Start here, then run :Tutor."
  "06-Neovim-Lua|nanotee/nvim-lua-guide|Lua in Neovim: vim.api, vim.opt, keymaps, autocommands."
)

mkdir -p "$LEARN_ROOT"
for row in "${REPOS[@]}"; do
  IFS='|' read -r dir repo _ <<<"$row"
  dest="$LEARN_ROOT/$dir"
  if [[ -d "$dest/.git" ]]; then
    remote="$(git -C "$dest" remote get-url origin)"
    [[ "$remote" == "https://github.com/$repo.git" ]] || { warn "$dest is a clone of $remote, not $repo; skipping"; continue; }
    git -C "$dest" pull -q --ff-only && ok "updated $dir"
  elif [[ -e "$dest" ]]; then
    warn "$dest exists and is not a git clone; skipping"
  else
    git clone -q --depth 1 "https://github.com/$repo.git" "$dest" && ok "cloned $repo -> $dir" \
      || warn "could not clone $repo"
  fi
done

# Native help tags for the tips wiki (loaded by lazy.lua when present)
if [[ -d "$LEARN_ROOT/03-Vim-Tips-Wiki/doc" ]] && have nvim; then
  # silent!: upstream files contain ~40 duplicate tags (E154); tags are still written
  nvim --headless -c "silent! helptags $LEARN_ROOT/03-Vim-Tips-Wiki/doc" -c qa \
    && [[ -s "$LEARN_ROOT/03-Vim-Tips-Wiki/doc/tags" ]] && ok "helptags for vim-tips-wiki"
fi

mkdir -p "$LEARN_ROOT/07-Neovim-Plugins" "$LEARN_ROOT/08-Neovim-Configuration"
cat > "$LEARN_ROOT/07-Neovim-Plugins/README.md" <<EOF
# Neovim plugins in this setup

Every installed plugin ships its own manual. In Neovim run \`:help <name>\`
or \`<leader>fh\` and type the plugin name. Full list with reasons:
$ARCH_ROOT/docs/plugins.md
EOF
cat > "$LEARN_ROOT/08-Neovim-Configuration/README.md" <<EOF
# How this configuration is built

- Source (edit here, then re-run install.sh): $ARCH_ROOT/config/nvim
- Installed copy: $NVIM_CONFIG
- Architecture and reasons: $ARCH_ROOT/ARCHITECTURE.md
- Keybindings: $ARCH_ROOT/docs/keybindings.md
- Built-in docs: \`:help lua-guide\`, \`:help lsp\`, \`:help treesitter\`
EOF

{
  echo "# Neovim Learning Library"
  echo
  echo "Open from Neovim with \`<leader>hl\`. Suggested order: 05 → \`:Tutor\` → 01 → 04 → 06 → 02/03 as reference."
  echo
  echo "| Folder | Source | What it teaches |"
  echo "|---|---|---|"
  for row in "${REPOS[@]}"; do
    IFS='|' read -r dir repo what <<<"$row"
    status="missing"; [[ -d "$LEARN_ROOT/$dir/.git" ]] && status="$(git -C "$LEARN_ROOT/$dir" log -1 --format=%cs)"
    echo "| [$dir](./$dir) | [$repo](https://github.com/$repo) (upstream $status) | $what |"
  done
  echo "| [07-Neovim-Plugins](./07-Neovim-Plugins) | this setup | Where each plugin's manual lives. |"
  echo "| [08-Neovim-Configuration](./08-Neovim-Configuration) | this setup | How the config is organised. |"
} > "$LEARN_ROOT/README.md"
ok "index -> $LEARN_ROOT/README.md"
