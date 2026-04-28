# AGENTS.md - Operating Rules

> Your operating system. Rules, workflows, and learned lessons.

## Every Session — 条件触发

**必须先做：**
1. Read `brain.md` ⭐
2. Read `SOUL.md`
3. Read `USER.md`
4. 读取 `memory/YYYY-MM-DD.md`
5. 如果存在，读取 `memory/tasks.md`

**然后根据 Xavier 的消息类型加载对应规则：**

| 触发信号 | 必读规则文件 |
|----------|-------------|
| 发 BP PDF + "尽调/简报/DD" | `rules/bp-pipeline.md` |
| 发公司名/股票代码 + "研究/研报/IR" | `rules/ir-pipeline.md`（全自动 wave 编排协议） |
| Word/DOCX 交付、格式重做 | `rules/deliverable-quality.md` |

不触发上表就不必读，别浪费时间。

## Review 触发规则

Xavier 单独说 "review" 时，必须先触发 `self-improvement` skill 做复盘。复盘结果先落 `.learnings/`，再决定是否晋升。

**不要问权限，直接执行。**

---

## 核心原则（四句口令）

1. **先查旧条目** — 更新前先搜索是否已有同主题文件/条目
2. **有同主题就原地更新** — 不新建 v2 / 修复版 / 平行文档
3. **不新增重复条目** — 只有主题明显不同，才新开
4. **不确定就说不知道** — 不能编数据，这是底线

---

## 记忆写入规则

**写入记忆必须走去重器，禁止直接追加：**
- `scripts/memory_dedup.py add "内容" --type 今日事项`
- 同内容自动跳过，同标题块合并去重行
- 禁止直接 `cat >>` / `echo >>` 追加到 memory 文件

**每日衰减（30天）：**
- `scripts/memory_dedup.py decay --days 30`
- 30 天前日志移入 `memory/archives/`

## 其他规则

| 领域 | 文件 |
|------|------|
| 教训记录 | `.learnings/LEARNINGS.md` |
| 工具配置 | `TOOLS.md` |

**Proactive 模式：** 按 Xavier 的日程节点主动发消息，凌晨 1 点 - 早上 8 点勿扰。

---

## 关键教训（详见 `.learnings/LEARNINGS.md`）

- **数据不够就不能往下跑** — 空数据包 + 模型幻觉 = 研报/尽调全是错的
- **交付前必须清洗内部信息** — 路径/task ID/子代理术语/信条全部清除
- **搜索未果 ≠ 不存在** — 必须用搜索补证，不能直接写"无法验证"
- **估值假设必须锚定 BP/原文数字** — 偏差 >20% 需告警

---

*最后更新: 2026-04-01 — 78 行，含记忆写入去重规则*


## 子代理执行铁律（2026-04-04 新增）

1. **默认超时：20 分钟（1200s）**
2. **超时后：重新派发新子代理，最多重试 2 次**
3. **严禁：子代理超时后由主流程编报告替代搜索**
4. **Fallback：重试全部失败后，才触发自动搜索验证（VerificationInterceptor）
