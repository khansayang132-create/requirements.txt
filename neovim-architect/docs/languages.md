# Languages

Status comes from `scripts/verify.sh` on the build machine (Ubuntu 24.04, x86_64; see `reports/verification-report.md`). "Attached" means the server started on a real sample in `tests/samples/` and, where the sample has a deliberate error, reported a diagnostic.

| Language | Runtime on build machine | Language server (source) | Formatter | Treesitter | Verified |
|---|---|---|---|---|---|
| Lua | LuaJIT (in Neovim) | lua_ls 3.19.2 (release binary) | stylua 2.6.0 | ✓ | attached, diagnostics, completion, go-to-definition |
| Python | 3.13 | pyright (existing uv install reused; npm otherwise) | ruff, black fallback | ✓ | attached, type-error diagnostic |
| JavaScript / TypeScript | Node 22 | ts_ls via typescript-language-server 5 + TypeScript 5 (npm) | prettier 3 | ✓ (js, ts, tsx) | attached, type-error diagnostic |
| HTML / CSS / JSON | – | vscode-langservers-extracted 4 (npm) | prettier | ✓ | attached |
| YAML | – | yaml-language-server 1 (npm) | prettier | ✓ | attached |
| Bash | bash 5 | bash-language-server 5 (npm) | shfmt | ✓ | attached |
| C / C++ | gcc 13, clang 18 | clangd 18 (apt) | clang-format | ✓ | attached, type-error diagnostic |
| Rust | rustc 1.97 | rust-analyzer (rustup component) | rustfmt | ✓ | attached (needs rustup on PATH) |
| Go | go 1.24 | gopls v0.24.0 (`go install`) | gofmt | ✓ | attached |
| Markdown | – | none (marksman optional) | prettier | ✓ | highlighting + formatting only |
| Java | Java present | jdtls: **not installed** | – | ✓ | NOT TESTED |
| TOML | – | none | – | ✓ | highlighting only |

## Why Java isn't set up

A Java runtime is present, but jdtls is a separate ~50 MB Eclipse download that needs Java 21+. It has no apt or Termux package, and nothing in this repo is Java. The config already enables it automatically if a `jdtls` command appears on PATH. To add it:
- Arch: `pacman -S jdtls`
- macOS: `brew install jdtls`
- Elsewhere: unpack the jdtls snapshot from the Eclipse download site and link its `bin/jdtls` into `~/.local/bin`.

## Adding a language

1. Install its server so the command is on PATH.
2. Add `name = { bin = "<command>" }` to `config/nvim/lua/lsk/servers.lua` (the name must be one of nvim-lspconfig's `lsp/*.lua` configs).
3. Add the parser name to `lsk/ts_parsers.lua` and the formatter to `plugins/coding.lua`.
4. Optionally add a `tests/samples/sample.<ext>` plus a case in `tests/verify.lua`.
5. Run `scripts/update.sh --config-only`.

## Termux notes

On Android, `install.sh` uses `pkg` for lua-language-server, stylua, clang (clangd), shfmt and Node; npm for the web servers; and `pkg install rust` → rust-analyzer if you want Rust. Mason is deliberately not used: its glibc binaries don't run on Android.
