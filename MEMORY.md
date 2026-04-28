# MEMORY.md — 记忆索引

> 纯索引，≤200 行 / ≤25KB。每行 ≤150 字符，指向 memory/ 下具体文件。
> 内容下沉到 `memory/daily/` 和 `memory/topics/`，这里只做指针。

---

## User — 关于 Xavier
| 条目 | 指向 | 类型 |
|------|------|------|
| [用户信息](USER.md) | 投研/PEVC/二级市场 | user |
| [偏好/沟通](SOUL.md) | 风格/边界 | user |
| [团队关系](USER.md) | 5 人团队结构 | user |

## Feedback — 经验教训
| 条目 | 指向 | 类型 |
|------|------|------|
| [学习日志](.learnings/LEARNINGS.md) | 教训/prompt/最佳实践 | feedback |
| [压测教训](memory/2026-04-03.md § 压测流程) | 批量修复 > 单点修复 | feedback |
| [交付教训](memory/2026-04-04.md § 交付守卫) | 生成后必须主动发送 | feedback |

## Project — 管线 & 系统

| 条目 | 指向 | 类型 |
|------|------|------|
| [BP 管线](memory/topics/bp-pipeline.md) | Pipeline v4 | project |
| [IR 研报管线](memory/topics/ir-research.md) | Pipeline v6 | project |
| [搜索系统](memory/topics/search-system.md) | SearXNG+DDG | project |
| [记忆系统](memory/topics/memory-system.md) | ChromaDB+去重 | project |
| [Agent & Skills](memory/topics/agent-skills.md) | 任务/管线 | project |
| [飞书集成](memory/topics/feishu.md) | 通知/消息 | project |
| [安全与凭证](memory/topics/security.md) | .env/API key | project |
| [Task/Hook 系统](memory/topics/task-hook-registry.md) | TaskRegistry+HookDispatcher | project |
| [今日事项](memory/daily/) | 每日日志 YYYY-MM-DD.md | project |
| [验证系统](memory/topics/验证系统.md) | 验证/校验 | project |
| [Claude Code 升级](memory/topics/Claude-Code-升级.md) | ACP 升级 | project |

## Reference — 外部资源指针
| 条目 | 指向 | 类型 |
|------|------|------|
| [Yahoo Finance](memory/topics/ir-research.md § 数据源) | 行情/财务 | reference |
| [Alpha Vantage](memory/topics/ir-research.md § API) | 金融数据 API | reference |
| [ClawHub](memory/topics/agent-skills.md § 市场) | 技能市场 | reference |
| [GitHub free-code](https://github.com/paoloanzn/free-code) | Claude Code fork, 6K⚡ | reference |

---

## 什么 NOT 存（硬性排除）
- 代码模式/架构/文件路径 — grep 可查
- git 历史/谁改了 — `git log`/`git blame` 是权威源
- 调试方案 — 修复在代码里
- 已在 AGENTS.md / TOOLS.md 里的
- 进行中任务/临时状态

## 信任但验证（Trust but Verify）
提到具体函数/文件/标志 → **必须先 grep 验证**
"记忆说 X 存在" ≠ "X 现在存在"
记忆冲突时 → 信任当前状态，更新或删除旧记忆

---

*最后更新：2026-04-05 · 53 行（上限 200）· 索引文件，非内容*
