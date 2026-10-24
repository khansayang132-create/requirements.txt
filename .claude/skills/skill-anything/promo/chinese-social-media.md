# 中文社交媒体推广文案

---

## 即刻/微信朋友圈 (短文案)

刚开源了一个项目：SkillAnything

一句话说明：给它任何软件/API/CLI工具，它自动生成可用于 Claude Code、OpenClaw、Codex 的 AI Agent Skill。

7 阶段全自动流水线：分析 -> 设计 -> 实现 -> 测试 -> 基准评测 -> 优化 -> 多平台打包。

如果说 CLI-Anything 是让软件有了 CLI，SkillAnything 就是让软件有了 Skill。

github.com/AgentSkillOS/SkillAnything

---

## 小红书风格 (种草文)

标题：用一行命令，把任何软件变成 AI Agent Skill

正文：

分享一个刚做的开源工具 SkillAnything

做 AI Agent 开发的同学应该都知道，手写 SKILL.md 有多痛苦：
- 写完发现触发不准，要反复调 description
- Claude Code 的格式和 OpenClaw 不一样，要写好几个版本
- 没有基准测试，不知道 Skill 到底有没有用

SkillAnything 就是为了解决这些问题。

它是一个「生成 Skill 的 Skill」，全自动 7 阶段流水线：

1/ 分析目标 -- 给它 jq、httpie、Stripe API 等任何目标
2/ 设计架构 -- 自动判断用什么 Skill 结构
3/ 生成代码 -- SKILL.md + 辅助脚本 + 参考文档
4/ 自动测试 -- 生成评测用例和触发查询
5/ 基准评测 -- 对比有/没有 Skill 的效果
6/ 描述优化 -- 用 train/test 拆分防止过拟合
7/ 多平台打包 -- 同时输出 Claude Code、OpenClaw、Codex 格式

安装只需一行：
git clone https://github.com/AgentSkillOS/SkillAnything ~/.claude/skills/skill-anything

然后在 Claude Code 里说「帮我给 jq 生成一个 skill」就行了。

MIT 开源，欢迎 Star

#ClaudeCode #AIAgent #开源项目 #AI编程

---

## 微信公众号/知乎风格 (长文)

标题：SkillAnything：一个让任何软件变成 AI Agent Skill 的自动化流水线

副标题：如果 CLI-Anything 让软件有了命令行，SkillAnything 让软件有了 Agent 能力

---

写在前面

AI Agent 生态正在快速成型。Claude Code 有 Skills，OpenClaw 有 Skills，Codex 也在跟进。但有一个问题：Skill 的创建过程太手工了。

你需要手写 SKILL.md，反复调试 description 看触发准不准，手动为不同平台适配格式，而且没有客观的评测手段来判断你的 Skill 到底有没有提升 Agent 的表现。

SkillAnything 要解决的就是这个问题。

---

它是什么

SkillAnything 是一个「元 Skill」-- 一个生成 Skill 的 Skill。

你给它一个目标（CLI 工具、REST API、Python 库、工作流、Web 服务），它跑一条 7 阶段的全自动流水线，最终输出可以直接安装使用的多平台 Skill 包。

---

7 阶段流水线

| 阶段 | 做什么 | 产出 |
|------|--------|------|
| 分析 | 自动检测目标类型，提取能力 | analysis.json |
| 设计 | 映射到最优 Skill 架构 | architecture.json |
| 实现 | 生成 SKILL.md + 脚本 + 参考文档 | 完整 Skill 目录 |
| 测试 | 自动生成评测用例 | evals.json |
| 评测 | 有/无 Skill 对照基准测试 | benchmark.json |
| 优化 | 训练集/测试集拆分优化描述 | 优化后 SKILL.md |
| 打包 | 输出多平台安装包 | dist/ |

---

技术特点

1. 目标自动检测：给它 `jq`，它自动运行 `jq --help` 提取子命令；给它一个 URL，它去抓 OpenAPI Spec。
2. 描述优化防过拟合：用 60/40 的 train/test 拆分，确保描述泛化能力。
3. 多平台一键打包：Claude Code、OpenClaw、Codex、通用 .skill 格式，各自的 frontmatter 和配置自动适配。
4. 代码保护：核心原创脚本支持 PyArmor 混淆，Apache 2.0 衍生代码保留源码。

---

站在巨人的肩膀上

- CLI-Anything (MIT) -- 7 阶段流水线方法论
- Dazhuang Skill Creator (Apache 2.0) -- 项目结构
- Anthropic Skill Creator (Apache 2.0) -- 评测/基准系统

所有归属信息写在 NOTICE 文件中，完全合规。

---

快速开始

git clone https://github.com/AgentSkillOS/SkillAnything ~/.claude/skills/skill-anything

然后在 Claude Code 中对话：
「帮我给 httpie 生成一个 skill」

---

GitHub: github.com/AgentSkillOS/SkillAnything
协议：MIT
欢迎 Star 和 PR

---

## 即刻/Twitter 短文案合集 (备选)

### 版本 A（技术向）
开源了 SkillAnything -- 7 阶段自动化流水线，把任何软件变成 AI Agent Skill。支持 Claude Code / OpenClaw / Codex 三平台。描述优化用 train/test 拆分防过拟合。MIT 协议。
github.com/AgentSkillOS/SkillAnything

### 版本 B（类比向）
CLI-Anything 让每个软件有了 CLI
SkillAnything 让每个软件有了 Agent Skill

给它任何工具，自动分析 -> 设计 -> 实现 -> 测试 -> 优化 -> 打包。
一个目标进去，四个平台的 Skill 出来。

github.com/AgentSkillOS/SkillAnything

### 版本 C（痛点向）
手写 SKILL.md 三大痛：
1. 描述写了改改了写，触发还是不准
2. Claude Code 和 OpenClaw 格式不一样，要维护两份
3. 没有基准测试，不知道有没有用

SkillAnything：全自动生成 + 评测 + 多平台打包，一条命令搞定。
github.com/AgentSkillOS/SkillAnything
