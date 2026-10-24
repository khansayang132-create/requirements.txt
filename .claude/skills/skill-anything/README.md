<p align="center">
  <img src="https://img.shields.io/badge/SkillAnything-v1.0.0-00d4aa?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Ik0xMiAyTDIgN2wxMCA1IDEwLTV6Ii8+PHBhdGggZD0iTTIgMTdsMTAgNSAxMC01Ii8+PHBhdGggZD0iTTIgMTJsMTAgNSAxMC01Ii8+PC9zdmc+" alt="SkillAnything"/>
  <br/>
  <img src="https://img.shields.io/badge/Python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License"/>
  <img src="https://img.shields.io/badge/Claude_Code-Compatible-7C3AED?style=flat-square" alt="Claude Code"/>
  <img src="https://img.shields.io/badge/OpenClaw-Compatible-FF6B35?style=flat-square" alt="OpenClaw"/>
  <img src="https://img.shields.io/badge/Codex-Compatible-10A37F?style=flat-square" alt="Codex"/>
</p>

<h1 align="center">SkillAnything</h1>

<p align="center">
  <strong>Making ANY Software Skill-Native</strong>
  <br/>
  <em>The meta-skill that generates production-ready Skills for AI agent platforms.</em>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#the-7-phase-pipeline">Pipeline</a> &bull;
  <a href="#supported-platforms">Platforms</a> &bull;
  <a href="#architecture">Architecture</a> &bull;
  <a href="#examples">Examples</a> &bull;
  <a href="#attribution">Attribution</a>
</p>

---

## What is SkillAnything?

> **One target in, production-ready Skills out.**

SkillAnything is a **Skill that generates Skills**. Give it any target -- a CLI tool, REST API, Python library, workflow, or web service -- and it runs a fully automated 7-phase pipeline:

```
Target: "jq"
  |
  v
[Analyze] -> [Design] -> [Implement] -> [Test] -> [Benchmark] -> [Optimize] -> [Package]
  |                                                                                  |
  v                                                                                  v
analysis.json                                                          dist/
                                                                        ├── claude-code/
                                                                        ├── openclaw/
                                                                        ├── codex/
                                                                        └── generic/
```

No manual prompt engineering. No copy-paste between platforms. Just tell it what you want a skill for.

## Quick Start

### Install

```bash
# Claude Code
git clone https://github.com/AgentSkillOS/SkillAnything.git ~/.claude/skills/skill-anything

# OpenClaw
git clone https://github.com/AgentSkillOS/SkillAnything.git ~/.openclaw/skills/skill-anything

# Codex
git clone https://github.com/AgentSkillOS/SkillAnything.git ~/.codex/skills/skill-anything
```

### Use

In Claude Code, just say:

```
> Create a skill for the httpie CLI tool
> Generate a multi-platform skill for the Stripe API
> Turn this data pipeline workflow into a skill
```

SkillAnything handles the rest.

### Run Individual Phases

```bash
# Phase 1: Analyze a target
python -m scripts.analyze_target --target "jq" --output analysis.json

# Phase 2: Design architecture
python -m scripts.design_skill --analysis analysis.json --output architecture.json

# Phase 3: Scaffold skill
python -m scripts.init_skill my-skill --template cli --output ./out

# Phase 4: Generate test cases
python -m scripts.generate_tests --analysis analysis.json --skill-path ./out/my-skill

# Phase 5: Run evaluation
python -m scripts.run_eval --eval-set evals.json --skill-path ./out/my-skill

# Phase 6: Optimize description
python -m scripts.run_loop --eval-set trigger-evals.json --skill-path ./out/my-skill --model claude-sonnet-4-20250514

# Phase 7: Package for all platforms
python -m scripts.package_multiplatform ./out/my-skill --platforms claude-code,openclaw,codex
```

## The 7-Phase Pipeline

Inspired by [CLI-Anything](https://github.com/HKUDS/CLI-Anything)'s methodology, adapted for Skill generation:

| Phase | Name | What It Does | Output |
|:-----:|------|-------------|--------|
| 1 | **Analyze** | Auto-detect target type, extract capabilities | `analysis.json` |
| 2 | **Design** | Map capabilities to skill architecture | `architecture.json` |
| 3 | **Implement** | Generate SKILL.md + scripts + references | Complete skill directory |
| 4 | **Test Plan** | Auto-generate eval cases + trigger queries | `evals.json` |
| 5 | **Evaluate** | Benchmark with/without skill, grade results | `benchmark.json` |
| 6 | **Optimize** | Improve description via train/test loop | Optimized SKILL.md |
| 7 | **Package** | Multi-platform distribution packages | `dist/` |

### Target Auto-Detection

| Target Type | Detection Method | Example |
|-------------|-----------------|---------|
| CLI Tool | `which <name>` + `--help` parsing | `jq`, `httpie`, `ffmpeg` |
| REST API | URL with OpenAPI/Swagger spec | Stripe API, GitHub API |
| Library | Package name via pip/npm | `pandas`, `lodash` |
| Workflow | Step-by-step description | ETL pipeline, CI/CD flow |
| Service | URL with web docs | Slack, Notion |

## Supported Platforms

<table>
<tr>
<td align="center"><strong>Claude Code</strong><br/><code>~/.claude/skills/</code></td>
<td align="center"><strong>OpenClaw</strong><br/><code>~/.openclaw/skills/</code></td>
<td align="center"><strong>OpenAI Codex</strong><br/><code>~/.codex/skills/</code></td>
<td align="center"><strong>Generic</strong><br/><code>.skill</code> zip</td>
</tr>
<tr>
<td align="center">Full support<br/>Hooks in frontmatter</td>
<td align="center">Full support<br/>External settings.json</td>
<td align="center">Full support<br/>openai.yaml companion</td>
<td align="center">Full support<br/>Platform-agnostic</td>
</tr>
</table>

## Architecture

```
SkillAnything/
├── SKILL.md                    # Main entry point (< 500 lines)
├── METHODOLOGY.md              # Full 7-phase pipeline spec
├── config.yaml                 # Pipeline configuration
│
├── agents/                     # Subagent instructions
│   ├── analyzer.md             # Phase 1: Target analysis
│   ├── designer.md             # Phase 2: Skill design
│   ├── implementer.md          # Phase 3: Content writing
│   ├── grader.md               # Phase 5: Eval grading
│   ├── comparator.md           # Blind A/B comparison
│   ├── optimizer.md            # Phase 6: Description optimization
│   └── packager.md             # Phase 7: Multi-platform packaging
│
├── scripts/                    # Python automation core
│   ├── analyze_target.py       # [NEW] Target auto-detection
│   ├── design_skill.py         # [NEW] Architecture generation
│   ├── init_skill.py           # [NEW] Skill scaffolding
│   ├── generate_tests.py       # [NEW] Auto test generation
│   ├── package_multiplatform.py # [NEW] Multi-platform packaging
│   ├── obfuscate.py            # [NEW] PyArmor wrapper
│   ├── run_eval.py             # Trigger evaluation
│   ├── improve_description.py  # AI-powered optimization
│   ├── run_loop.py             # Eval + improve loop
│   ├── aggregate_benchmark.py  # Benchmark statistics
│   └── ...                     # + validators, reporters
│
├── references/                 # Documentation
│   ├── platform-formats.md     # Platform-specific specs
│   ├── schemas.md              # JSON schemas
│   └── pipeline-phases.md      # Phase details
│
├── templates/                  # Generation templates
│   ├── skill-scaffold/         # Skill directory template
│   └── platform-adapters/      # Platform-specific adapters
│
└── eval-viewer/                # Interactive eval review UI
    └── generate_review.py
```

## Examples

### Example 1: CLI Tool Skill

```
> Create a skill for the jq CLI tool

Phase 1: Analyzing jq... detected as CLI tool (confidence: 0.95)
Phase 2: Designing skill architecture... tool-augmentation pattern
Phase 3: Generating SKILL.md + 2 scripts + 1 reference
Phase 4: Created 5 test cases + 20 trigger queries
Phase 5: Benchmark: 87% pass rate (vs 42% baseline)
Phase 6: Description optimized: 18/20 trigger accuracy
Phase 7: Packaged for claude-code, openclaw, codex, generic

Done! Skill at: sa-workspace/dist/
```

### Example 2: API Skill

```
> Generate a skill for the Stripe API, focus on payments

Phase 1: Fetching Stripe OpenAPI spec... 247 endpoints found
Phase 2: Focusing on payment_intents, customers, charges
Phase 3: Generated SKILL.md with auth setup + endpoint references
...
```

### Example 3: Workflow Skill

```
> Turn this into a skill: fetch from Postgres, clean with pandas, upload to S3

Phase 1: Detected workflow with 3 steps
Phase 2: workflow-orchestrator pattern, 3 dependencies
Phase 3: Step-by-step SKILL.md with error handling guidance
...
```

## Configuration

Edit `config.yaml`:

```yaml
pipeline:
  auto_mode: true              # Full automation or interactive
  skip_eval: false             # Skip phases 5-6 for rapid prototyping

platforms:
  enabled: [claude-code, openclaw, codex, generic]
  primary: claude-code

eval:
  max_optimization_iterations: 5
  runs_per_query: 3

obfuscation:
  enabled: false               # PyArmor protection for core scripts
```

## Code Protection

SkillAnything supports code obfuscation for commercial distribution:

```bash
# Obfuscate original scripts (Apache 2.0 derived files are excluded)
python -m scripts.obfuscate --config config.yaml

# Output: dist-protected/ with PyArmor-protected core + readable adapted scripts
```

| Category | Files | Protection |
|----------|-------|-----------|
| SkillAnything Original | 6 scripts | PyArmor obfuscated |
| Anthropic Adapted | 9 scripts | Source (Apache 2.0 requires it) |
| Agent Instructions | 7 .md files | Readable (required by agents) |

## Attribution

Built on the shoulders of giants:

| Project | License | What We Used |
|---------|---------|-------------|
| [CLI-Anything](https://github.com/HKUDS/CLI-Anything) | MIT | 7-phase pipeline methodology |
| [Dazhuang Skill Creator](https://github.com/DazhuangJammy/DazhuangSkill-Creator) | Apache 2.0 | Project structure pattern |
| [Anthropic Skill Creator](https://github.com/anthropics) | Apache 2.0 | Eval/benchmark system, agent instructions |

See [`NOTICE`](./NOTICE) for complete attribution details.

## Contributing

We welcome contributions! Areas where help is needed:

- New target type analyzers (e.g., GraphQL, gRPC)
- Platform adapters for additional agent frameworks
- Evaluation improvements and test case quality
- Documentation and examples

## License

MIT License -- see [`LICENSE`](./LICENSE) for details.

---

<p align="center">
  <strong>SkillAnything</strong> -- Making ANY Software Skill-Native
  <br/>
  <sub>If CLI-Anything makes CLIs for software, SkillAnything makes Skills for everything.</sub>
</p>
