# Installation Report

**Machine:** Claude Code cloud container: Ubuntu 24.04.5 LTS, kernel 6.18, x86_64, 4 cores, 15 GiB RAM, running as root. **This is not the owner's phone.** The owner works from Android/Termux, and that path is written but NOT TESTED (see Unresolved issues).

## State before (Phase Zero, 2026-11-08 19:4x UTC)

Neovim **not installed** (Vim 9.1 present). No `~/.config/nvim`, no `~/.local/share/nvim`, no `~/.vimrc`. Present: git 2.43, curl, wget, Python 3.13, Node 22.23, Go 1.24, Rust 1.97, gcc 13, clang 18, make, cmake, ripgrep 14.1, tmux, Java 21, gh. Missing: fd, tree-sitter CLI, xclip, luarocks. Post-install values: [system-audit.md](system-audit.md).

## What was installed

See [DEPENDENCIES.md](../DEPENDENCIES.md) for every version. In short: Neovim 0.12.6, tree-sitter 0.26.13, lua-language-server 3.19.2 and StyLua 2.6.0 as SHA256-pinned release binaries in `~/.local`; 371 apt packages (fd, clangd, clang-format, shfmt, shellcheck, xclip, python3-venv, and on the first run also Ubuntu's nodejs/npm, see note); 4 npm language-server packages into `~/.local`; gopls v0.24.0; the rust-analyzer component; 22 plugins at locked commits; 21 treesitter parsers; 6 learning repositories.

## Runs

| Run | Result | Notes |
|---|---|---|
| install #1 | stopped at npm (exit 1) | `npm EEXIST`: pyright already existed via uv. Fixed: skip existing commands. |
| install #2 | completed; verify found bugs | Tests exposed: function-valued `cmd` servers never enabled; rustup proxy; parser downloads 403 here; harness bugs. All fixed (CHANGELOG.md). |
| e2e #1, #2 (fresh HOME) | FAIL | Real bug found: lazy.nvim itself not pinned on fresh install. Fixed in `lsk/lazy.lua`. Remaining failures were test-script bugs, fixed. |
| install #3 (real HOME, repeat run) | exit 0 | Every existing tool detected and skipped: proves safe re-runs. |
| **e2e #3 (fresh HOME)** | **PASS** | 8/8 checks: fresh install, foreign config backed up and moved aside, all 22 plugins at lockfile commits, rollback restores the original byte-for-byte, re-install, then 11 PASS + LSP PARTIAL (rust-analyzer deliberately off PATH there). |
| **install #4 (real HOME)** | **exit 0, 13/13 PASS** | [verification-report.md](verification-report.md) |

## Performance

Measured in a real pseudo-terminal (`script`), median of 5, using the editor process's "NVIM STARTED" time from `--startuptime`:

| | Startup |
|---|---|
| Baseline `nvim --clean` | 117.2 ms |
| With this config | 131.7 ms |
| Config overhead | **≈ 15 ms** |

Startup is dominated by Neovim's own init in this container. Most plugins lazy-load on keys, events or filetypes. Only the theme and nvim-treesitter (which doesn't support lazy-loading) load at startup.

## Health check warnings (0 errors)

All are expected: no Python/Ruby/Perl/Node "remote plugin" hosts (legacy, not used); no clipboard because the container has no X display (xclip is installed and works under X); nvim-lspconfig lists filetypes like `yaml.docker-compose` that Neovim doesn't define; mini.icons not installed (optional for which-key).

## Backups

`/root/Developer/Neovim-Backups/<timestamp>/`, one per install run, each with `MANIFEST.txt`. The rollback round trip is proven in e2e #3.

## Unresolved issues

1. **Termux not tested.** The Android path (`pkg` packages, cargo-built tree-sitter CLI, Termux clipboard) was never executed: no Android device here. Run `bash neovim-architect/scripts/install.sh` on the phone; its verify step writes a real report.
2. **Arch / Fedora / macOS branches not tested** (package names only).
3. **SHA256 pins are trust-on-first-use.** The GitHub release-digest API was blocked here, so the hashes are from these downloads, not cross-checked with upstream's published digests.
4. **Parser tarball downloads are blocked in this sandbox** (HTTP 403); the git fallback was used. On a normal network the primary download path runs. It's the standard nvim-treesitter path, but it wasn't exercised here.
5. **Java (jdtls), Markdown (marksman) and DAP debugging are not configured** (see docs/languages.md and architecture-decision.md).
6. **Interactive UI is unverified by eye.** Tests run headless plus a real PTY for startup. Colours, icons and layout weren't looked at on a screen.
