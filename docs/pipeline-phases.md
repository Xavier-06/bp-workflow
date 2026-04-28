# BP 管线 Phase 详解

## Phase 0: Document Intake

**输入**：BP 文件（PDF/PPTX/DOCX/图片）
**输出**：`bp_ocr_text.txt` + `bp_step0_profile.json`

流程：
1. 根据文件类型选择解析策略：
   - PDF → VL 模型 OCR（优先） → pdfminer（回退） → PyPDF2（兜底）
   - PPTX → LibreOffice 渲染逐页 PNG → VL OCR → python-pptx（回退）
   - DOCX → python-docx 读文字 → 嵌入图片 VL OCR
   - 图片 → VL OCR 直接识别
2. VL 模型做结构化抽取（公司名/行业/融资阶段/团队/财务/竞品等）
3. 基于客观事实推断融资阶段（硬规则，不靠 VL 判断）

**融资阶段推断规则**：
- 搜不到公开工商/财报信息 → 绝不可能是 Pre-IPO/C轮+
- 零营收 → 不可能是 B轮+
- "量产样机/工程样机" → 判为"小批量"而非"量产"

## Phase 0.5: Company Verify + 护城河锚定

**输入**：`bp_step0_profile.json`
**输出**：`company_verify_report.json` + `company_verify_report.md` + `bp_moat_analysis.md`

### Part A: 公司核验

流程：
1. 读取 Step0 Profile 获取公司名、创始人、融资阶段
2. 根据融资阶段选择搜索策略：
   - 早期（种子/天使）：跳过工商搜索，聚焦创始人个人 + 技术验证
   - 成熟（A轮+）：搜工商注册、法定代表人等
3. 创始人履历验证（所有阶段）
4. 顾问验证（直接搜顾问本人）
5. 风险搜索（早期搜创始人个人风险，成熟搜公司风险）

### Part B: 护城河锚定

在核验完成后，根据 Step0 提取的商业模式，执行"发动机/油箱"分析：

| 商业模式 | 发动机（真壁垒） | 油箱（可替代部分） |
|----------|-----------------|-------------------|
| IDM | 工艺制程/良率/外延质量 | 封装测试/标准应用 |
| Fabless | 差异化IP/代工资源/架构设计 | 外延制造/标准工艺节点 |
| 系统集成 | 方案定义能力/核心模块自主性 | 标准零部件/成熟制造工艺 |
| 平台型 | 技术平台完整性/跨场景复用/生态协同 | 单点技术绝对性能 |
| ERP/MES/工业软件 | 核心算法/行业Know-how/客户黏性 | 标准SaaS功能/通用实施 |

搜索任务：
- `[赛道]` + 核心瓶颈/物理极限/工程难题
- `[赛道]` + 成本结构/规模化障碍
- `[赛道]` + 客户采购决策因子/替代方案
- `[赛道]` + 失败案例/被放弃的技术路线

叙事断裂检测：
- BP 声称的技术壁垒 vs 公开信息的落差
- 发动机是否足以驱动油箱
- 关键叙事是否存在逻辑断裂

**输出**：护城河分析结果写入 `company_verify_report.md` 的"护城河锚定"章节

## Phase 1: Presearch

**输入**：`bp_step0_profile.json`
**输出**：`bp_presearch_step_*.md`（4 个维度）+ `bp_presearch_results.json`

流程：
1. 读取 Profile 获取 entity、tech、industry、founder 等变量
2. 根据融资阶段选择查询模板（early_stage vs mature_stage）
3. 对 4 个维度（team/tech/industry/competition）分别搜索
4. 去重、截断，输出 Markdown 格式搜索结果

## Phase 2: 多维度分析

### Wave 1（Phase 2a-2b）

**子代理**：前 3 个维度并行

| 维度 | 角色 | 输出 |
|------|------|------|
| 团队与合规 | bp_团队与合规 | `bp_phase2_team.md` |
| 技术与产品 | bp_技术与产品 | `bp_phase2_tech.md` |
| 行业与供应链 | bp_行业与供应链 | `bp_phase2_industry.md` |

流程：
1. Phase 2a: `_run_bp_dispatch_prepare()` — 构建 brief + manifest → `needs_dispatch`
2. 主 AI 读取 manifest → 用 Task 工具派发 3 个子代理（team 异步模式）
3. Phase 2b: `_run_bp_dispatch_collect()` — 检查输出文件 + 质量评分

### Wave 2（Phase 2.5a-2.5b）

**子代理**：竞争与结论（依赖 Wave 1 输出）

| 维度 | 角色 | 输出 |
|------|------|------|
| 竞争与结论 | bp_竞争与结论 | `bp_phase2_competition.md` |

流程：
1. Phase 2.5a: 准备竞争与结论 manifest，注入前 3 维度输出作为上下文
2. 主 AI 派发竞争与结论子代理
3. Phase 2.5b: 检查输出

### 子代理自主闭环规则

子代理执行时必须自主闭环：
1. 发现数据缺口 → 自己补搜（最多 3 轮）
2. 来源不足 → 自己搜更多来源
3. 数据矛盾 → 自己判断，标注矛盾
4. 唯一完成条件 → 输出文件写完

## Phase 3: 统稿 + 交付

### 统稿（Phase 3a-3b）

| 子代理 | 输出 |
|--------|------|
| bp_统稿 | `bp_synthesis.md` |

统稿角色读取 4 个维度输出，按投研逻辑重组为完整研报：
执行摘要 → 技术原理 → 痛点解决 → 方案对比 → 厂商情况 → 市场规模 → 民用拓展 → BP验证 → 风险 → 结论建议

### 交付（Phase 3）

1. 优先使用统稿输出（投研逻辑结构），fallback 到 4 维度原文
2. 调用 `build_bp_dd_report_docx.py` 生成 DOCX 报告
3. 调用 `notify_plugin.notify_report()` 推送通知（可选）
4. 记录产物到 StateStore
5. 输出交付审计报告

## 质量门禁

| 门禁 | 标准 | 后果 |
|------|------|------|
| 子代理输出长度 | ≥6000 chars → score=5 | score<3 判为 fail |
| URL 数量 | <2 个 → 扣 1 分 | — |
| 章节数量 | <3 个 → 扣 1 分 | — |
| 统稿输出 | >2000 chars | 否则判缺失 |
