# Product Hunt / Hacker News Pitch

---

## Tagline (60 chars)

Making ANY Software Skill-Native for AI Agents

## One-liner (140 chars)

Auto-generate production-ready AI Agent Skills for Claude Code, OpenClaw, and Codex from any CLI tool, API, library, or workflow.

## Description

### The Problem

AI Agent Skills (like Claude Code Skills) are powerful but painful to create:
- Writing SKILL.md is manual and error-prone
- Testing trigger accuracy is trial-and-error
- Each platform (Claude Code, OpenClaw, Codex) has different formats
- No objective benchmarking to know if your Skill actually helps

### The Solution

SkillAnything is a meta-skill: a Skill that generates Skills. Give it any target -- a CLI tool (jq, httpie), a REST API (Stripe, GitHub), a Python library (pandas), or a workflow -- and it runs a fully automated 7-phase pipeline:

1. **Analyze** -- Auto-detect target type, extract capabilities
2. **Design** -- Choose optimal skill architecture
3. **Implement** -- Generate SKILL.md + scripts + references
4. **Test** -- Auto-generate evaluation cases
5. **Benchmark** -- Compare with/without skill performance
6. **Optimize** -- Improve description with train/test split
7. **Package** -- Output for Claude Code, OpenClaw, Codex, and generic

### Key Features

- **Zero manual prompt engineering** -- Just name your target
- **Multi-platform output** -- One pipeline, four platform formats
- **Benchmark-driven** -- Objectively measure skill quality
- **Anti-overfitting** -- Train/test split for description optimization
- **Code protection** -- PyArmor obfuscation for commercial distribution

### Built on

- CLI-Anything (MIT) -- 7-phase pipeline concept
- Anthropic Skill Creator (Apache 2.0) -- Evaluation system
- Dazhuang Skill Creator (Apache 2.0) -- Project structure

### Getting Started

```
git clone https://github.com/AgentSkillOS/SkillAnything ~/.claude/skills/skill-anything
```

Then in Claude Code: "Create a skill for the jq CLI tool"

MIT Licensed. Open source. PRs welcome.

---

## HN Title Options

- Show HN: SkillAnything -- Auto-generate AI Agent Skills for any software
- Show HN: A 7-phase pipeline that turns any CLI/API into an AI Agent Skill
- Show HN: SkillAnything -- the meta-skill that generates Skills for Claude Code, OpenClaw, and Codex
