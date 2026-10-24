# Community Announcement (Discord / Slack / Forum)

---

## Short Version (for Discord/Slack channels)

Hey everyone! Just open-sourced **SkillAnything** -- a tool that auto-generates AI Agent Skills from any software target.

**What it does:** Give it a CLI tool, API, library, or workflow -> it runs a 7-phase pipeline -> outputs production-ready Skills for Claude Code, OpenClaw, Codex.

**Why it matters:** No more hand-writing SKILL.md files. No more trial-and-error with trigger descriptions. No more maintaining separate formats for each platform.

**Quick start:**
```
git clone https://github.com/AgentSkillOS/SkillAnything ~/.claude/skills/skill-anything
```
Then: "Create a skill for [any tool]"

MIT licensed. Feedback and PRs welcome!

https://github.com/AgentSkillOS/SkillAnything

---

## Long Version (for forums / detailed posts)

### Introducing SkillAnything: Auto-Generate AI Agent Skills for Any Software

I've been building Skills for Claude Code and other agent platforms for a while, and kept running into the same friction:

1. **Writing SKILL.md is tedious.** You write a description, test it, realize it doesn't trigger properly, rewrite, test again...
2. **Each platform wants different formats.** Claude Code uses hooks in frontmatter, OpenClaw uses external settings.json, Codex needs an openai.yaml companion file.
3. **No way to objectively measure quality.** Is your Skill actually helping? Without benchmarks, you're guessing.

So I built SkillAnything -- a "meta-skill" that generates Skills automatically.

### How it works

You give it a target (CLI tool name, API URL, package name, or workflow description), and it runs a 7-phase pipeline:

| Phase | What happens |
|-------|-------------|
| Analyze | Auto-detects target type, extracts capabilities |
| Design | Maps to optimal skill architecture |
| Implement | Generates SKILL.md + helper scripts |
| Test | Creates eval cases and trigger queries |
| Benchmark | Compares with-skill vs without-skill |
| Optimize | Improves description with train/test split |
| Package | Outputs for Claude Code, OpenClaw, Codex |

### What makes it different from skill-creator

Anthropic's built-in skill-creator is human-in-the-loop: you decide what the skill does, write drafts, review outputs. SkillAnything automates the entire pipeline. You just name a target.

That said, SkillAnything builds on skill-creator's excellent eval/benchmark system (properly attributed, Apache 2.0).

### Try it

```bash
git clone https://github.com/AgentSkillOS/SkillAnything ~/.claude/skills/skill-anything
```

In Claude Code:
```
> Create a skill for httpie
> Generate a multi-platform skill for the Stripe API
> Turn this ETL workflow into a skill
```

### Technical details

- 16 Python scripts (6 original + 10 adapted from Anthropic)
- 7 specialized subagent instruction files
- 4 platform adapter templates
- PyArmor support for commercial code protection
- MIT licensed, proper attribution in NOTICE file

### Attribution

Built on CLI-Anything (MIT), Dazhuang Skill Creator (Apache 2.0), and Anthropic Skill Creator (Apache 2.0).

### Links

- GitHub: https://github.com/AgentSkillOS/SkillAnything
- Release: https://github.com/AgentSkillOS/SkillAnything/releases/tag/v1.0.0

Would love feedback on the pipeline design, target analysis approach, or platform adapter templates. PRs welcome!

---

## WaytoAGI 社区版本 (中文)

### SkillAnything：让任何软件秒变 AI Agent Skill

大家好！分享一个刚开源的项目。

**背景：** 在 Claude Code / OpenClaw / Codex 生态里，Skill 越来越重要。但手写 SKILL.md 的体验不好——描述要反复调、不同平台格式不一样、没有客观评测手段。

**SkillAnything 做的事：** 给它任何目标（CLI 工具、API、Python 库、工作流），它跑一条 7 阶段全自动流水线，直接输出多平台可用的 Skill 包。

**7 阶段：** 分析 -> 设计 -> 实现 -> 测试 -> 基准评测 -> 描述优化 -> 多平台打包

**参考了这些项目：**
- CLI-Anything (MIT) 的流水线方法论
- Dazhuang Skill Creator (Apache 2.0) 的项目结构
- Anthropic Skill Creator (Apache 2.0) 的评测系统

所有归属写在 NOTICE 里，完全合规。

**安装：**
```
git clone https://github.com/AgentSkillOS/SkillAnything ~/.claude/skills/skill-anything
```

欢迎试用和反馈！GitHub: https://github.com/AgentSkillOS/SkillAnything
