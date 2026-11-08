# Dependencies

Versions actually installed and running on the build machine (Ubuntu 24.04.5, x86_64), read from each tool's `--version` on 2026-11-08. "Source" says where `install.sh` gets it. **Reused** means it was already on the machine and the installer deliberately left it alone.

## Pinned release binaries (SHA256-checked, installed to `~/.local`)

| Tool | Version | SHA256 pin location |
|---|---|---|
| Neovim | 0.12.6 | `scripts/lib.sh` (x86_64 + aarch64) |
| tree-sitter CLI | 0.26.13 | `scripts/lib.sh` |
| lua-language-server | 3.19.2 | `scripts/lib.sh` |
| StyLua | 2.6.0 | `scripts/lib.sh` |

## Language servers and formatters

| Tool | Version | Source |
|---|---|---|
| typescript-language-server | 5.3.0 | npm (`@5`) |
| vscode-langservers-extracted (html/css/json) | 4.10.0 | npm (`@4`) |
| yaml-language-server | 1.25.0 | npm (`@1`) |
| bash-language-server | 5.8.1 | npm (`@5`) |
| pyright | 1.1.414 | **reused** (uv tool); npm `@1` otherwise |
| TypeScript (`tsc`) | 6.0.2 | **reused** (`/opt/node22`); npm `@5` otherwise |
| prettier | 3.8.1 | **reused** (`/opt/node22`); npm `@3` otherwise |
| ruff | 0.16.9 | **reused** (uv tool); venv `ruff<1` otherwise |
| gopls | v0.24.0 | `go install` (checksum-verified by the Go module proxy) |
| rust-analyzer / rustfmt | 1.97.0 / 1.9.0 | `rustup component add` |
| clangd / clang-format | 18.1.3 | apt |
| shfmt | 3.8.0 | apt |

## System

| Tool | Version | Source |
|---|---|---|
| git | 2.43.0 | apt |
| ripgrep | 14.1.0 | apt |
| fd | 9.0.0 (`fdfind`, linked as `fd`) | apt |
| gcc / make | 13.3.0 / 4.3 | apt (`build-essential`) |
| Node.js | 22.23.4 | **reused** (`/opt/node22`) |
| Python | 3.13.18 | **reused** |
| shellcheck | 0.9.0 | apt |
| xclip | 0.13 | apt (clipboard provider) |

Note: on this build machine, the first installer run (before the "reuse existing runtimes" fix) also pulled Ubuntu's `nodejs`/`npm` packages into `/usr/bin`. `/opt/node22` stays first on PATH, so nothing was shadowed. The fixed installer no longer does this.

## Plugins

22 plugins, pinned to exact commits in [`config/nvim/lazy-lock.json`](config/nvim/lazy-lock.json); see [docs/plugins.md](docs/plugins.md).

## Termux equivalents

`pkg`: neovim, lua-language-server, stylua, clang (clangd + clang-format), shfmt, ripgrep, fd, nodejs-lts, python, termux-api, optionally tree-sitter-cli and ruff; `cargo install tree-sitter-cli@0.26.13` as the fallback. npm provides the web/YAML/Bash servers.
