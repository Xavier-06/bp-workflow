---
name: IR 研报研究
type: project
last_updated: 2026-04-03
---

# IR 研报研究 — 主题记忆

## 核心进展

*暂无简报级条目*

## 详细记录

### 研报管线 IR 升级（v3 → v4）新增
*2026-04-03*

### 差距分析（对标 BP DD v4 架构）
| # | 能力 | IR 现状 | BP v4 做法 | IR 升级方案 |
|---|------|---------|-----------|-----------|
| 1 | Gap Detection + 迭代深钻 | runner.py 内部简单 gap 分析，无独立脚本 | gap_detector + gap_driven_search 最多3轮 | ir_gap_detector.py（新） |
| 2 | LLM 信息抽取 | 完全没有 | extract_content.py qwen-plus 提取结构化事实 | ir_extract_content.py（新） |
| 3 | 查询改写 | query_expander.py 基础展开，无LLM改写 | LLM 逆向验证/类比/供应链策略 | ir_query_rewriter.py（新） |
| 4 | 官方验证层 | 没有 | Phase 0.5 天眼查/企查查 | ir_company_verify.py（待写） |
| 5 | Preflight LLM 提取 | 基础校验，无LLM | 正则+LLM双提取+哈希保护 | 复用或适配 BP 模式 |
| 6 | 全自动 auto 模式 | 手动一步步跑 | Phase 0→5 一键到头 | run_ir_pipeline.py（待写） |

### IR 新增文件
- `scripts/ir_gap_detector.py` — 9 维度覆盖检测 + A-E 评级 + 缺口搜索词
  - 维度：行情/行业/商业模式/财务/管理层/洞察/风险/统稿/验证
  - 评分：🅰官方=3 / 🅱权威=1.5 / 🅲普通=0.5
- `scripts/ir_extract_content.py` — LLM 正文信息抽取
  - qwen-plus 提取：实体/财务/业务/治理/事件/风险/估值观点
  - 输出：聚合实体/财务/事件/风险/估值汇总
- `scripts/ir_query_rewriter.py` — LLM 查询改写
  - 逆向验证/同业类比/供应链/官方渠道/情绪面
  - 无 API key 时 fallback 规则模板生成

### 重要文件变更 (2026-04-03)
*2026-04-03*

- `scripts/extract_content.py` — v2 (11.3KB, LLM 信息抽取)
- `scripts/query_expander.py` — v2 (9.0KB, LLM 改写实现 + fallback)
- `scripts/gap_driven_search.py` — 更新 (9.6KB, 证据摘要传入)
- `scripts/run_bp_pipeline.py` — v3 (13.0KB, Phase 0.5 + Phase 4→5 自动衔接)
- `scripts/bp_preflight_check.py` — v4 (25.4KB, LLM 提取 + 哈希保护)
- `scripts/company_verify.py` — 新增 (14.4KB, 工商信息验证层)
- `rules/bp-pipeline.md` — 架构更新至 2026-04-03 v4
- `scripts/ir_gap_detector.py` — 新增 (17.2KB, 9 维度缺口检测)
- `scripts/ir_extract_content.py` — 新增 (10.5KB, LLM 正文抽取)
- `scripts/ir_query_rewriter.py` — 新增 (11.7KB, LLM 查询改写)

### BP 尽调管线 v1 首战失败复盘（利玛软件 / 2026-04-01）
*2026-04-01*

### 问题定性
**Critical 级别系统性失败**：不是小瑕疵，是 PDF 提取→交付清洗→报告结构→数据校验全链条一起炸了。

### 九大类问题（Xavier 精准诊断）

| # | 问题类别 | 具体表现 |
|---|----------|----------|
| 1 | PDF 提取失败 | 团队履历（BP 第 17-18 页白纸黑字）→"未识别"；产品描述→痛点碎片；客户 LOGO 20 家→仅 2 家 |
| 2 | 内部流程泄漏 | 任务 ID、时间戳、内部路径、子代理分工、搜索调试信息、信条口号全部进入 Word |
| 3 | 引用格式不专业 | 正文裸 URL 而非脚注编号 |
| 4 | 编码乱码 | 字符、emoji 转码失败 |
| 5 | 结构错位 | 按"Step 0→5"agent 工作流而非专业 DD 结构 |
| 6 | 数据矛盾/捏造 | 估值假设 2025 年收入 3 亿 vs BP 原文 2026 年 1000 万（差 30 倍）；前文"不建议投资"后文"推荐投资" |
| 7 | 搜索不足 | 团队搜索返回 Pinterest 登录页；客户验证未做；专利只搜 Google Patents |
| 8 | 缺失关键内容 | 融资金额、股权结构、历史财务、融资用途分析、执行摘要 |
| 9 | 语言排版 | Markdown 痕迹、表格崩坏、口号不专业、重复冗长 |

### 根因分析
1. `pdf_extractor.py` 对结构化信息（履历表、LOGO 墙、图表）提取能力不足
2. `build_bp_dd_report_docx.py` 没有"交付清洗层"，直接把子代理中间稿拼接外发
3. 没有"BP 原文数据校验"环节，估值假设与 BP 脱节 30 倍未被拦截
4. 子代理 brief 没有禁止"内部术语/信条/调试信息"进入最终输出

### 修复规则（已写入 AGENTS.md）
1. **交付清洗层**：过滤任务 ID、路径、子代理术语、信条、调试信息、Markdown 痕迹
2. **结构模板**：改为专业 DD 结构（执行摘要→公司→行业→商业模式→竞争→团队→财务→风险→建议）
3. **数据校验门禁**：估值假设必须引用 BP 原文数字，偏差>20% 需标注并告警
4. **引用格式**：正文仅脚注编号 [1][2][3]，来源统一收文末附录
5. **PDF 提取增强**：团队履历/客户 LOGO 墙提取失败→必须用搜索补证
6. **搜索增强**：团队搜索词优化（公司名 + 人名 + 前东家）；客户验证走招投标/政府采购网；专利搜中国国家知识产权局

### 状态
- [x] 错误记入 `.learnings/ERRORS.md`（ERR-20260401-001）
- [x] 规则写入 `AGENTS.md`（交付清洗层硬规则）
- [ ] 脚本修复待执行：`build_bp_dd_report_docx.py`、`bp_preflight_check.py`、`pdf_extractor.py`

### Xavier 偏好确认
- BP 尽调：搜索不用 Tavily，只用 SearXNG + Scrapling + DDG 等免费工具
- BP 管线与研报管线必须物理隔离（指令库分开、脚本分开、任务类型分开）
- 交付报告必须是专业 DD 结构，不能暴露内部工作流
# 2026-04-01 日志

### 学到的教训
*2026-03-30*

- `dispatch_ir_subagent_via_agent.py` 不能依赖 `openclaw agent`（Gateway 模型路由不稳定），改成直接 API 调用
- `.credentials/investment-research.env` 里的值有单引号包裹，Python `split('=',1)` 后必须 strip 引号
- execution-loop 的所有 subprocess 调用必须用 venv python，不能用系统 python3

- **价格数据源**：CoinGecko/Binance 在国内被墙，搜索 snippet 不是实时数据
- **Session 子代理清理**：需要清理 sessions.json 里的孤儿条目
- **投研管线根因**：优必选研报 16 类问题的根因是"门禁不够细"——数据包字段太少、没有算术验算、没有估值假设一致性检查、没有路径清洗、没有去重检测。门禁必须是代码级的，不能靠"应该检查"

### 重要决定
*2026-03-29*

- 研报质量基线：≥ 40KB / 600 行，必须含 DCF、可比估值、护城河评分、治理评分、风险分级
- Pre-search 成为标准流程（发射 subagent 前必须跑）
- Task package 由 preflight 自动创建，两条路径不再冲突

- 晨报架构改用 5 层流水线，不再用旧的 RSS 聚合逻辑
- 清理脚本按任务完成状态清理，不是按时间
- 投研管线从 v2 升级到 v3，全面修复优必选研报暴露的系统性缺陷

### 今日事项
*2026-03-28*

### 搜索系统 runner v3 修复和优化
- **垃圾页面过滤**：加了 GARBAGE_TITLES 检查（Access Denied / 403 / Captcha 等），evidence 创建前过滤
- **搜索并发化**：ThreadPoolExecutor(max_workers=4) 并发搜索，Round 搜索时间从 100s+ 降到 3-10s/轮
- **SearXNG 做主力 DDG 做补位**：SearXNG 通过代理 1-4s/query，DDG 的 primp 10-18s/query 太慢
- **查询去重**：ResearchState 加 used_queries 追踪，_generate_gap_queries 排除已搜过的查询
- **snippet 模式 acceptance**：snippet_only=True 时 snippet>=80 字自动 accept

### 腾讯端到端测试结果
- 3 轮迭代搜索，66 秒完成
- 10 条 accepted evidence，0 垃圾
- Gap 检测正确识别并补搜 business_model + financials
- Citation 输出完整（10 条带编号来源）

### Citation 模板 + 研究计划飞书推送（Subagent 任务）
- **Part 1**：修改 `research/memo_builder.py`
  - `MemoBuilder.build()` 获取 `state.citation_map` 并传给各方法
  - `_extract_finding_from_evidence()` 新增 `citation_map` 和 `id_to_url` 参数，自动附加 `[N]` 引用
  - `_extract_news_finding()` 同上
  - `ResearchMemo.to_markdown()` 方法：输出带 `[N]` 引用和完整来源列表
- **Part 2**：修改 `research/runner.py`
  - `_print_research_plan()` 末尾追加飞书推送（fire-and-forget）
  - 推送内容：entity、task_type、market、max_rounds、subquestions、展开查询数
- 验证：`to_markdown` 方法存在检查通过 ✅

### 双路径 subagent 强制校验修复
- **问题诊断**：存在两条执行路径（自动化管线 vs 对话触发），对话路径完全绕过 subagent 编组和 thinking=high
- **修复内容**：
  1. `ir_preflight_check.py` — 研报启动前强制校验 + 自动创建 task package
  2. `ir_subagent_launcher.py` — 统一 subagent 发射器（含工具绝对路径 + pre-search 引用 + 降级指引）
  3. `ir_presearch.py` — 发射前用 research_api 跑 7 轮搜索，~70 条 evidence 兜底
  4. `run_ir_execution_loop.py` 补丁 — 支持双任务执行（primary 等待时推进 support_task）
  5. `instruction_store/` 11 个角色指令文件全部创建
  6. AGENTS.md 更新 — 双路径强制校验 + 质量基线

### 压测 1：NVDA（修复验证）
- 8/8 subagent 发射，5/8 成功写文件，3/8 空返回（搜索工具路径问题）
- 主控接管 3 个 step，最终完成
- 发现根因：subagent brief 缺少工具绝对路径和降级指引

### 压测 2：TSLA（对标 Perplexity Deep Research）
- 8/8 subagent 全部成功写文件（0% 空返回）
- Pre-search 7 轮共 70+ 条 evidence
- 最终报告 660 行 / 44KB / 12 个表格
- 评级：谨慎，概率加权目标价 $235（当前 $361.83）
- Word 已发送飞书

### 执行循环阻塞修复
- TSLA 任务通过对话路径完成但 ledger 标"进行中"，管线找不到 task package → 循环 50 次
- 修复：preflight 自动创建 task package，避免管线/对话路径冲突

### 晨报链去 Tavily 换 search_news（SearXNG/DDG）
- **修复**：`gold_brief_gj.sh` 和 `crypto_news.sh` 中的 Tavily 调用全部替换为 `search_news.py`
- **新流程**：SearXNG 优先 → DDG 降级，不再依赖 Tavily API key
- **验证**：bash -n 语法检查通过，grep 确认无 Tavily 残留

### 研报管线阻塞问题修复
- **问题 1**：NVDA 任务报"task package not found" → 手动创建 package，更新 preflight 自动创建逻辑
- **问题 2**：PopMart 报"query 缺少明确行业/标的" → 修复 `generate_ir_search_plan.py`
- **问题 3**：review gate dispatch 反复失败 → 根因是 `openclaw agent` 走 Gateway 切模型到 `codex/gpt-5.4` 失败
  - 修复：`dispatch_ir_subagent_via_agent.py` v2 改成直接调 DashScope qwen-plus API 做 review，彻底绕过 Gateway
  - search-plan-review 改成 soft gate：记录建议但不阻塞管线
- **问题 4**：fill_packet 用系统 Python 3.9 不支持 `dataclass(slots=True)`
  - 修复：execution-loop 里所有 cmd 调用改用 `.venv/bin/python3`（3.14）

### 研报进度路由修复
- **问题**：所有研报进度和结果都发给 Xavier，不管是谁让做的
- **修复**：
  - `config/recipients.json` v2：新增 `sender_map`（飞书 sender_id → recipient key）
  - `scripts/resolve_sender.py`：新增工具脚本，按 sender_id 或姓名解析 recipient
  - TASK-20260330-003（优必选研报）recipient 已从 xavier 改为 zhouzong
- **规则**：以后任务创建时必须按消息来源设 recipient

### OpenClaw doctor 修复
- 移除 stale plugin `qwen-portal-auth`
- 归档 26 个 orphan transcript files（.deleted 备份）
- 系统状态：Feishu ✅, Gateway ✅, Skills 41 eligible

### 团队信息确认
- 周总 = 周欣，飞书 ID `user:2f5ff2cf`
- USER.md 已更新

### 子代理清理 + 会话标签管理
- 清理了 83 个已完成任务的子代理会话（泡泡玛特/优必选/英伟达/TSLA 等）
- tasks.md 补齐了所有已完成任务的 ✅ 标记
- 写了清理脚本 `scripts/cleanup_completed_tasks.py`，定时每天凌晨 1 点跑
- 飞书会话标签改好了：Xavier=ou_fc4728374aeed4fb302026963720c08c，周总=2f5ff2cf/ou_67210f80aae94b073c8f90f184b510d5，吉总=44e18a48
- 脚本：`scripts/set_session_labels.py`

### 加密晨报 v2.0 架构设计 + Step 1-2 实现
- Xavier 给晨报打了 18 条问题诊断，核心问题：无数据/重复/无分析/无结论
- 5 层架构设计：数据层→新闻层→解读层→机会层→结论层
- **Step 1 数据层**：`scripts/crypto_fetch_data.py` - 从搜索获取价格/宏观数据，输出 `crypto_data_layer1.json`
- **Step 2 去重**：`scripts/crypto_dedup.py` - 全局去重 + 黑名单过滤，输出 `crypto_news_deduped.json`
- 修改了 `scripts/crypto_news.sh`，集成数据层+去重+质量检查+飞书发送
- 晨报成功生成并飞书发送

### 价格数据限制（重要）
- CoinGecko API 和网站在国内被墙（SSL 连接失败）
- Binance API 也被墙
- search_news 的 snippet 不含实时价格，解析出的价格可能过时
- **结论**：搜索无法获取实时价格，需要找其他方案

### 投研管线 v3 全面升级（优必选研报 16 类问题修复）
Xavier 对优必选研报做了 16 条问题诊断，涵盖数据错误/内部矛盾/分析深度/方法论/格式。根据诊断逐一修复：

**脚本升级（4 个）：**
1. `verify_step1_completeness.py` → v2：新增算术交叉验算（市值=股价×股本、PE×EPS≈股价、分析师评级加总、收入占比加总100%）、估值方法适用性预警（亏损公司DCF警告）、扩充字段（总股本/现金/分部收入/政府补贴/审计意见/配售历史/员工数等）
2. `verify_cross_step_consistency.py` → v2：新增DCF假设vs情景分析中性情景一致性检查、可比估值营收假设偷换检测、重复内容检测（n-gram频率）、系统路径/命令泄露扫描、可比公司适当性检查（亏损公司不应用已盈利公司做PE可比）
3. `build_ir_broker_report_docx.py` → v2：新增 `sanitize_text()` 清洗所有内部路径/task ID/脚本命令/子代理术语；Markdown 表格→Word 原生表格；标题页不再暴露 task ID；新增免责声明页
4. `ir_presearch.py` → v2：每 step 搜索词从 3-7 条扩到 5-22 条，新增资产负债表/现金流/分部收入/政府补贴/配售历史/审计意见/员工数/竞争对手出货量等搜索词
5. `ir_evidence_blacklist.py` → v2：新增来源可靠性 4 级分级（TIER_1权威一手/TIER_2权威二手/TIER_3低可靠/BLACKLIST），新增 `get_source_tier()` 和 `audit_sources()` 函数

**指令库升级（6 个角色）：**
1. `投研_主笔_预测与估值.md`：**新增估值方法选择矩阵**（深度亏损→PS为主/DCF仅参考）、**情景锚点一致性硬规则**（DCF基准=中性情景）、**可比公司选择规则**（同阶段公司）、**与分析师共识对比硬规则**（差距>20%必须解释）、**护城河评分规范**（"未知"=2分）、**市值验算硬规则**
2. `投研_主笔_数据收集.md`：输出格式从 6 部分扩到 8 部分（新增资产负债表、收入质量/特殊项），**新增必填字段**：总股本、现金及等价物、分部收入、政府补贴、关联交易、审计意见、配售历史、员工数、研发占比。**市值必须自己算并验算**
3. `投研_主笔_文档汇总.md`：**新增去重硬规则**（同一数据点全文最多出现2次）、**新增估值一致性专项检查**（DCF/可比法的输入假设必须=中性情景）、**来源标注精度要求**（必须含报告名称+日期）、禁止最终产出包含内部术语
4. `投研_主笔_风险催化.md`：**新增情景锚点硬规则**（基准情景是估值锚点）、**新增管理层目标可行性论证**（6项最低拆解要求）、**新增必须包含的特定风险**（股权稀释/补贴依赖/大股东减持/持续经营）
5. `投研_主笔_行业分析.md`：**新增竞争对手数据精度要求**（区分年度vs累计、内部vs商业、标注来源可靠性和时效、区分产品形态）
6. `投研_主笔_商业模式.md`：**新增护城河评分规范**（1-5分定义、"未知"=2分、每个维度需事实论据、竞争对手打分也需事实）、**数据一致性约束**（与Step1一致）

**instruction_store/index.json** 升级到 v3

- BP DD 管线 Perplexity 差距分析（约 60-70%）
- 三项升级 + 三个待修复问题拆解并部署完成
- Phase 0.5 工商信息验证层（天眼查/企查查创始人履历）补齐
- IR 研报管线 v4 升级启动 — 对标 BP DD → Perplexity Deep Research
  - 差距分析完成，拆 6 个任务逐个交付
  - ✅ 任务 1: ir_gap_detector.py — 研报维度缺口检测器（9 维度覆盖 + 据评分 + A-E 评级）
  - ✅ 任务 2: ir_extract_content.py — LLM 正文信息抽取层（qwen-plus 提取财务/事件/风险）
  - ✅ 任务 3: ir_query_rewriter.py — LLM 查询改写器（逆向验证/同业类比/供应链策略）

Phase 1: 记忆类型分类 + frontmatter 支持改造完成

### 待办
*2026-03-28*

- [x] full_text 模式测试 ✅
- [x] gap 维度检测调优 ✅
- [x] runner v3 接入投研主链 ✅
- [x] memo citation [N] 模板 ✅
- [x] 晨报链去 Tavily ✅
- [x] Yahoo Finance 估值接入 ✅
- [x] PDF 提取接入 ✅
- [x] fill_ir_data_packet v2 研报主链接入 ✅
- [ ] 记忆系统 tiering 自动化（漏洞待修）
- [ ] sub-question 中英文匹配改进

### 泡泡玛特研报质量事故修复（完成 ✅）
- **问题**：Xavier 发现泡泡玛特研报 18 个事实性错误（海外收入占比差4倍、回购金额差10倍、门店数差一个量级、算术错误、人物国籍编造等）
- **根因**：Step 1 数据包几乎空白但管线没阻塞，下游全靠模型幻觉填充；泡泡玛特走了对话路径，绕过了所有质量门

#### 第一层：门禁脚本（已完成）
  1. ✅ 新建 `scripts/verify_step1_completeness.py` — Step 1 完整性门禁
  2. ✅ 新建 `scripts/verify_cross_step_consistency.py` — 跨 Step 数据一致性检查
  3. ✅ 升级 `scripts/filter_ir_evidence.py` — 域名黑名单 + 过时证据过滤
  4. ✅ 升级 `scripts/ir_presearch.py` — 搜索词扩展到 5-10 条/step

#### 第二层：管线集成 + 指令库升级（已完成）
  5. ✅ `run_ir_execution_loop.py` — 自动化管线集成 verify_step1（fill_packet 后）+ verify_consistency（bundle 前）
  6. ✅ `fill_ir_data_packet.py` — 搜索完成后自动调用域名黑名单过滤
  7. ✅ 新建 `scripts/ir_evidence_blacklist.py` — 共享黑名单模块（filter_ir_evidence + fill_packet 共用）
  8. ✅ 指令库全角色升级（v2）— 11 个角色全部加"数据纪律"硬规则：
     - `投研_主管` — 加 Step 1 完整性门禁 + 一致性门禁的代码级调用要求
     - `投研_主笔_行业分析` — 禁止编造市场规模、全球≠中国
     - `投研_主笔_商业模式` — 收入拆分/门店数/海外占比必须有来源
     - `投研_主笔_财务分析` — 禁止推算替代引用、同一指标不能有多个值
     - `投研_主笔_预测与估值` — 预测假设可追溯、估值输入有来源、算术验算
     - `投研_主笔_差异化洞察` — 洞察必须引用 Step 1-5 证据、跨 step 数据必须一致
     - `投研_主笔_风险催化` — 情景分析数字有来源、风险量化有依据
     - `投研_主笔_移交说明` — 必须引用代码级门禁结果、缺失项量化、质量等级 A/B/C
     - `instruction_store/index.json` 升级到 v2

- [ ] 晨报 Step 3-5：去重+过滤无用内容 → 加山寨币/板块 → 加交易结论
- [ ] 找到可用的实时价格 API（替代 CoinGecko）
- [ ] 把去重模块集成到 crypto_news.sh 的 Python 脚本里

### BP 尽调管线 v1 建设
- Xavier 要把 BP 简报工作交给 Agent，发来完整的 8 维度证伪性尽调指令
- 决策：与投研管线**完全物理隔离**（指令库、脚本、任务类型全部独立）
- 共用的只有底层无状态工具（SearXNG、pdf_extractor、task_ledger）

**建成清单：**
- `instruction_store_bp/` — 6 个角色指令（主管 + 护城河锚定 + 团队与合规 + 技术与产品 + 行业与供应链 + 竞争与结论）
- `scripts/bp_preflight_check.py` — Step 0 前置判断（从 PDF 提取融资阶段/制造模式/商业模式/核心竞争力/对标对象）
- `scripts/bp_presearch.py` — 全网搜索（SearXNG + DDG，零 API 费用）
- `scripts/bp_verify_consistency.py` — 跨维度一致性验证
- `scripts/build_bp_dd_report_docx.py` — DOCX 尽调报告生成
- `AGENTS.md` 新增 BP 管线硬规则（路由判定 + 执行流程 + 质量门禁）

**搜索栈：** SearXNG（主） + DDG（备） + Scrapling（正文抓取） + Yahoo Finance（对标估值），全免费
**子代理编组：** 5 个（比投研管线的 6-9 个精简，因为 BP 本身就是信息源）
**执行流程：** PDF → preflight → presearch → Step 1 → Step 2-4 并行 → Step 5 → DOCX → 飞书发送

### runner v3 full_text + gap 调优 + 主链接口 (2026-03-28 10:05)
*2026-03-28*

### Part 1: full_text 端到端测试 ✅
- 测试命令：ResearchRunner(max_fetch_per_round=5, snippet_only=False, max_rounds=2)
- 结果：accepted=1, with_full_text=1, rounds=2
- 结论：full_text 模式已生效

### Part 2: gap 维度检测调优 ✅
修改 `research/runner.py`:
- **risks** 增加关键词：'机遇', '挑战', '政策', '合规', '竞争对手', '市场份额', 'competition', 'macro'
- **management** 增加关键词：'创始人', '董事会', '治理', '股权', '激励', 'founder', 'board', 'governance'
- **COVERAGE_THRESHOLD**: 从 2 降到 1，减少 false negative
- 验证：gap 检测覆盖了全部 5 个维度 (business_model, financials, recent_events, risks, management)

### Part 3: 主链接口 research_api.py ✅
新建 `research/research_api.py`:
- 一键调用：`run_research(query, entity, market, max_rounds, snippet_only)`
- 返回 dict: memo_markdown, accepted_count, rounds_used, stop_reason, citation_map, valuation_data
- 验证通过：python3 research/research_api.py 腾讯 hk

### Bug 修复
- 修复 `memo_builder.py`: 添加 self.citation_map 初始化，解决内部方法访问属性报错

### 晨报链去 Tavily 换 SearXNG/DDG (2026-03-28 10:10)
*2026-03-28*

### 完成事项
1. **新建 `scripts/search_news.py`**：通用新闻搜索脚本，SearXNG 优先，DDG 降级
2. **修改 `scripts/send_iran_brief_gj.sh`**：
   - 移除 TAVILY_API_KEY 相关代码
   - 用 subprocess 调用 search_news.py 替代 Tavily API
   - 保留 DASHSCOPE_API_KEY 用于翻译

### 验证结果
- `bash -n scripts/send_iran_brief_gj.sh` 语法检查通过 ✅
- `python3 scripts/search_news.py 'US Iran conflict latest 2026' 3` 输出正常 JSON ✅

### 记忆系统升级 (2026-03-28 11:50)
*2026-03-28*

### 漏洞修复
1. **HOT tiering 刷新频率**：原来只在 00:12 跑 → 加 08:30/12:00/18:00/23:00 四个点
2. **ChromaDB 向量记忆孤立**：主 venv 装 chromadb+dashscope，新建 memory/memory_bridge.py 统一接口
3. **research_api 接向量记忆**：搜索前自动检索历史，搜索后自动存估值+摘要到向量库

### 新增文件
- `memory/memory_bridge.py` - 向量记忆统一 API
- `scripts/fill_ir_data_packet.py` - 研报主链搜索入口（v2）
- `content/pdf_extractor.py` - PDF 提取模块
- `tasks/valuation_enricher.py` - Yahoo Finance 估值接入

### 待优化（非紧急）
- proactive-reminders.json 清理 null 条目
- sub-question 中英文匹配改进

### 泡泡玛特深度研报（2026-03-28 下午）
*2026-03-28*

### 完整多智能体工作流（8个子代理串行）
- Step 1 数据收集：市场数据、2024/2025年报、估值快照
- Step 2 行业分析：潮玩市场550-600亿，CAGR 25-30%
- Step 3 商业模式：护城河4.3/5，出海毛利率70%+
- Step 4 财务分析：毛利率66.8%，FCF 44亿，PE vs 可比
- Step 5 管理层：治理7.4/10，王宁持股约20-25%
- Step 6 差异化洞察：逆向买入，PE 13.78x vs 净利+293%背离
- Step 7 风险催化剂：风险收益比3:1
- Step 8 统稿：5500字卖方风格研报

### 研报结论
- 评级：买入（Buy）
- 目标价：HK$163（基准）/ HK$217（乐观）
- 当前价：HK$149.6

### 2025全年关键数据（CNBC 2026-03-25）
- 营收：RMB 371亿（YoY +185%）
- The Monsters（Labubu）：~RMB 103亿
- Q4明显放缓，触发股价-22%
- PE 13.78x处于历史低位

### 产出文件
- reports/popmart_deep_research_v2.md（最终版）
- data/tasks/popmart_step1-7_*.md（各章节素材）
