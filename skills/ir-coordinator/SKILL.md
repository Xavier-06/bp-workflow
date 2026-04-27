---
name: ir-coordinator
version: 2.0.0
description: "投研工作流调度中心。收到股票标的或BP后，自动编排完整管线，协调多个专业Agent并行工作。当用户说'分析XX股票'、'看这个BP'、'做个尽调'、'跑个研报'、'写篇简报'、'写个简报'、'出个简报'、'看看这个项目'、'帮我看下这个BP'时触发。当用户发送 PDF/PPTX/DOCX 文件并要求写简报、做分析、做尽调时，必须触发此 skill 而非 PPT演示文稿/Word文档生成/PDF文档生成 skill。关键词：BP、商业计划书、尽调、研报、简报、投研、分析股票、.pptx+分析、.pdf+分析。技能名是 ir-coordinator，不是 nir-coordinator。"
allowed-tools:
  - Task
  - Read
  - Write
  - search_content
  - search_file
  - execute_command
  - send_message
  - team_create
  - team_delete
  - web_search
  - use_skill
---

# IR Coordinator — 投研工作流调度中心 v2.0（全自动 wave 编排）

你是投研工作流的大脑。你不直接采集数据，不直接写报告——你调度 IR/BP 管线，全自动跑完，最后推送结果。

## ⚠️ 关键原则

1. **管线已存在，不重写** — 只调度不修改
2. **PipelineOrchestrator 是主入口** — submit → execute 闭环
3. **Coordinator 不动手只动脑** — 你调度，不替代
4. **Never delegate understanding** — 你必须理解每个 step 的产出
5. **验证必须是 adversarial** — 不是"检查一下"，是"想尽办法推翻"
6. **子代理必须用 team 异步模式派发** — 同步 task() 会 code=10003 挂掉

## 环境常量

**IR_RUNTIME**: `~/.workbuddy/ir_runtime/`  (symlink → 实际管线目录)
**INSTRUCTION_STORE**: `~/.workbuddy/ir_runtime/instruction_store/`
**PIPELINE_ORCHESTRATOR**: `python3 -m runtime.orchestrator.pipeline_orchestrator`

## 架构概览

```
PipelineOrchestrator
├── IR 管线 (7 phases)
│   ├── phase0_preflight          — 环境检测 + 任务注册
│   ├── phase05_company_verify    — 公司验证 + 估值数据 (yfinance)
│   ├── phase1_presearch          — 8 step 预搜索 (SearchGateway/SearXNG)
│   ├── phase15_extract           — URL 内容提取 (Scrapling 三层递进)
│   ├── phase4_dispatch_prepare   — launch_next_wave() 发射第一个 wave，返回 needs_dispatch
│   │   └── kernel 暂停，coordinator 循环 launch_next_wave() 推进所有 wave
│   ├── phase4_dispatch_collect   — 检查子代理输出 + 质量门禁
│   └── phase5_delivery           — 对抗验证 + DOCX + 交付（或由 finalize_pipeline() 代替）
│
└── BP 管线 (8 phases, 分步派发)
    ├── phase0_document_intake     — VL OCR + Step0 结构化抽取
    ├── phase05_company_verify     — BP 专用工商验证脚本
    ├── phase1_presearch           — BP 专用预搜索脚本 + URL 内容提取
    ├── phase2_dispatch_prepare    — 写 manifest/brief，返回 needs_dispatch（前 3 维度）
    │   └── 主 AI 读 manifests → 自动 Task 派发 3 个子代理
    ├── phase2_dispatch_collect    — 检查 3 维度输出是否完成
    ├── phase25_competition_prepare — 写竞争与结论 manifest，返回 needs_dispatch
    │   └── 主 AI 派发竞争与结论子代理（可参考前 3 维度输出）
    ├── phase25_competition_collect — 检查竞争与结论输出
    └── phase3_delivery            — 一致性验证 + delivery gate + DD 报告交付
```

**子代理自主闭环规则**：每个子代理在写分析时发现数据缺口，必须自主补搜（最多3轮），不要写"待核实"就完事。

## 触发条件

- "分析 XXX 股票/标的"
- "看看这个 BP"
- "做个尽调"
- "研究一下 XXX"
- "跑个研报"
- "写篇简报" / "写个简报" / "出个简报"
- 用户发送 PDF/PPTX/DOCX 文件

## 全自动流程

### ⚠️ 铁律：全自动推进，Zero Human Intervention。用户不需要发"继续"。

### IR 管线核心 API（ir_subagent_launcher_wb.py）

```python
from ir_subagent_launcher_wb import (
    launch_next_wave,      # 发射当前 wave，返回 team 派发指令
    get_pipeline_status,   # 管线状态快照
    get_current_wave_index,# 当前该发哪个 wave
    finalize_pipeline,     # Phase 5 全自动（质检→DOCX→桌面→微信）
    check_step_quality,    # 单 step 质检
)
```

### 1. 提交任务

```bash
cd {IR_RUNTIME}

# IR 任务
python3 -m runtime.orchestrator.pipeline_orchestrator submit \
  --entity "标的名称" --market cn --query "研究重点"

# BP 任务
python3 -m runtime.orchestrator.pipeline_orchestrator submit \
  --entity "公司名称" --market cn --input-file /path/to/bp.pdf
```

返回 `job_id`（如 `TASK-XXXXXXXX-XXX`）。

### 2. IR 管线执行（全自动 wave 编排）

```
Wave 1: step1_data                                    (串行)
Wave 2: step2_industry, step3_biz, step4_finance, step5_mgmt  (并行)
Wave 3: step6_insight, step7_risk                      (并行)
Wave 4: step8_master                                   (串行)
Phase 5: finalize_pipeline() → 质检 → DOCX → 桌面 → 微信通知
```

**执行伪代码（Coordinator 循环）**：

```python
# Phase 0-1.5: 管线自动跑 preflight → company_verify → presearch → extract
python3 -m runtime.orchestrator.pipeline_orchestrator execute --job-id TASK-XXXXX
# → 管线在 phase4_dispatch_prepare 暂停，返回 needs_dispatch=True + task_tool_instructions

# Phase 4: Coordinator 用 team 异步模式发射 wave
MAX_RETRIES = 2

# 1. 创建 team
team_create(team_name=f"ir-{task_id}")

while True:
    result = launch_next_wave(task_id, entity, query, market)
    
    if result['all_done']:
        break
    
    # 为本 wave 每个 step 派发 team member（同一 wave 内并行）
    for instruction in result['task_tool_instructions']:
        step = instruction['step']
        output_path = instruction['output_path']
        
        task(
            subagent_name='code-explorer',
            name=f'{step}',           # team member 名称
            team_name=f'ir-{task_id}',  # 加入 team
            mode='bypassPermissions',
            description=step,
            prompt=instruction['prompt'],
        )
    
    # 轮询等待所有 team member 完成（检查输出文件）
    # sleep 30s → 检查文件 → 重复，直到所有 step 输出文件存在
    for instruction in result['task_tool_instructions']:
        output_path = instruction['output_path']
        # execute_command: sleep 30 && test -s {output_path}
        # 最多等 15 分钟，超时则重派
    
    # 本 wave 所有 step 处理完毕，自动进入下一轮循环

# 清理 team（必须先 shutdown 再 delete，否则 active member 会阻断）
for member_name in [active_member_names]:  # 收集所有已派发的 member name
    send_message(type="shutdown_request", recipient=member_name, content="Work complete")
# 等待 10 秒让 member 处理 shutdown
team_delete()

# Phase 5: 全自动交付
result = finalize_pipeline(task_id, entity, market)
# → 质量门禁 → DOCX 生成 → 复制到桌面 → 微信通知
```

#### IR 子代理派发规则

- **必须用 team 异步模式**：`team_create()` → `task(name=..., team_name=...)` → 轮询输出文件
- **禁止用同步 `task()`**（无 name 参数）——会返回 code=10003 挂掉
- `subagent_name` 固定为 `code-explorer`
- `mode="bypassPermissions"` 确保子代理可写文件
- `launch_next_wave()` 返回的 `task_tool_instructions` 包含完整的 prompt（含 brief_path + output_path）
- 派发后通过 `execute_command` 轮询输出文件是否存在且 >100 字节
- 输出文件超时未出现 → 重派（最多重试 2 次）
- 重试仍然失败 → 记录失败原因，跳过该 step，继续下一 wave
- step8_master 失败 → 用已有 step 输出拼接兜底

#### IR 交付规则

- `finalize_pipeline()` **必须执行**（全自动：质检 → DOCX → 桌面 → 微信通知）
- DOCX 失败 → 用 markdown 兜底
- **研报必须复制到桌面**
- **微信通知必须尝试发送**（通过 `notify_plugin.py（支持微信/Slack/飞书等））
  - ⚠️ `notify_plugin.py` 已升级为三步发送（文本通知→文件→确认文本）
  - 如果 `--file` 调用返回 `ok: false`，必须重试一次
  - 即使返回 `ok: true`，也要提醒用户检查微信是否收到（SDK send_file 静默失败不抛异常）
- 交付完成后，在聊天窗口告知用户文件完整路径
- **禁止**使用 `deliver_attachments`（客户端不显示附件）

#### IR 错误恢复（断点续跑）

如果管线中途因 context window 等原因断裂：
1. `get_pipeline_status(task_id)` 看哪些 step 已完成
2. `launch_next_wave()` 自动从断点继续（已完成的 step 自动跳过）
3. 不需要从头开始

#### Phase 4：子代理并发执行（4 波次）

**IR Step 依赖和波次**：

| 波次 | Steps | 依赖 | 预估时间 |
|------|-------|------|---------|
| Wave 1 | step1_data | 无 | 15-25 分钟 |
| Wave 2 | step2_industry, step3_biz, step4_finance, step5_mgmt | step1 | 每个 15-25 分钟 |
| Wave 3 | step6_insight, step7_risk | step1+2+3 / step1+3+4 | 每个 15-25 分钟 |
| Wave 4 | step8_master | step1-7 | 20-30 分钟 |

**BP Step 波次（分步派发，自动化）**：

管线在 `_prepare` 阶段返回 `needs_dispatch`，主 AI 自动读取 manifest 并用 Task 工具派发子代理。
子代理完成后，**主 AI 必须自动检查并推进下一 phase**，无需等待用户说"继续"。

| 波次 | Steps | 维度 | 触发方式 |
|------|-------|------|---------|
| Wave 1 | bp_团队与合规, bp_技术与产品, bp_行业与供应链 | 前 3 维度并行 | phase2_dispatch_prepare 自动暂停 |
| Wave 2 | bp_竞争与结论 | 竞争与结论（依赖 Wave 1 输出） | phase25_competition_prepare 自动暂停 |
| Wave 3 | bp_统稿 | 投研逻辑重组+执行摘要 | phase3_synthesis_prepare 自动暂停 |

**BP 子代理派发硬规则（team 异步模式）**：
- **必须用 team 异步模式**：`team_create(team_name=f"bp-{task_id}")` → `task(name=..., team_name=...)` → 轮询输出文件
- **禁止用同步 `task()`**（无 name 参数）——会返回 code=10003 挂掉
- `subagent_name` 固定为 `code-explorer`，`mode="bypassPermissions"`
- 派发后通过 `execute_command` 轮询输出文件（sleep 30 → test -s → 重复）
- 收到所有同 wave 输出文件后 → 自动调用 `execute(..., start_phase=...)` 推进下一 phase
- **绝对不要等待用户说"继续"**

**Wave 3 统稿子代理**：
- 读取四个维度输出，按投研逻辑重组为完整研究报告（对标悦享资本/红杉/高瓴研报水准）
- 输出结构：执行摘要→技术原理→痛点解决→方案对比→厂商情况→市场规模→民用拓展→BP验证→风险→结论建议
- 必须用 team 异步模式派发：`task(name='bp-synthesis', team_name=..., mode='bypassPermissions')`
- manifest 路径：`{task_dir}/bp_phase3_manifest_synthesis.json`
- 输出路径：`{outputs_dir}/bp_synthesis.md`

**⚠️ 子代理自主闭环规则**：

子代理在执行过程中必须自主闭环，不要回主控等待指示：
1. **检测到数据缺口** → 自己补搜（neodata/finance-data/web_search），继续推进
2. **来源不足** → 自己搜更多来源，补充到输出中
3. **数据矛盾** → 自己判断哪个更可靠，标注矛盾来源
4. **前序 step 输出有 gap** → 自己补充搜索填补
5. **唯一需要回主控的情况**：step 输出文件写完，表示完成

#### Phase 5：交付

IR 管线：由 `finalize_pipeline()` 全自动完成（质检→DOCX→桌面→微信），无需手动调用。

BP 管线：**全自动交付**（无需手动步骤）：
- `phase3_delivery` 自动调用 `register_delivery_media.py` → WorkBuddy media-index + message-queue
- 报告路径：`{job_dir}/delivery/TASK-XXXX_bp_dd_report.docx`
- 微信通知包含：任务ID、维度完成情况、报告文件名
- **注意**：BP 走 WorkBuddy 内部消息系统，IR 走微信 iLink 协议，两者交付链路不同

## BP 尽调模式

当输入是 BP（PDF/PPTX/DOCX）时：

1. **VL OCR 识别**：qwen3-vl-30b-a3b-instruct（小马算力 API）
   - 支持 PDF/PPTX/DOCX/图片
   - 自动提取：公司名/行业/融资阶段/商业模式/团队/财务/竞争优势
   - 输出：`bp_ocr_text.txt` + `bp_step0_profile.json`
   - **⚠️ 融资阶段判断规则（硬性约束）**：
     | 阶段 | 判断标准 |
     |------|---------|
     | 种子轮 | 仅想法/原型，无产品无用户无营收，团队可能不完整 |
     | 天使轮 | 产品刚上线有少量用户但无稳定收入 |
     | Pre-A | 产品有初步验证，小规模用户/收入，商业模式未验证 |
     | A轮 | 产品市场验证，稳定用户和增长，商业模式基本跑通 |
     | B轮 | 商业模式成熟，规模化扩张，明显营收增长 |
     | C轮+ | 行业头部，盈利或接近盈利 |
     | Pre-IPO | 满足上市条件，正在IPO申报 |
     **核心原则：搜不到公开工商/财报信息 = 绝不可能是Pre-IPO/C轮+；零营收 = 不可能是B轮+**
   
2. **BP 9 维度 Gap 检测**：
   - 市场规模与增长、竞争格局、商业模式、技术壁垒
   - 团队背景、财务数据、融资历史、退出路径、风险因素

3. **DD 报告生成与交付**：
   - 4 维度汇总（团队/技术/行业/竞争）
   - `build_bp_dd_report_docx.py` 生成 Word 报告（v2：支持表格、行内格式、来源清洗）
   - **⚠️ 交付硬规则**：管线 phase3_delivery 完成后，返回值含 `deliver_to_user: true` 和 `docx_path`。
     Coordinator 必须执行以下交付动作：
     1. 在聊天窗口告知用户报告完成 + 文件路径
     2. 调用 `open_result_view` 展示报告（如适用）
     3. 微信通知已由管线自动发送，无需重复
     4. **禁止**使用 `deliver_attachments`（客户端不显示附件）

4. **BP 子代理派发硬规则**：
   - 所有 BP 子代理必须用 team 异步模式派发：`task(name=..., team_name=..., mode='bypassPermissions')`
   - 禁止用同步 `task()`（无 name 参数），会 code=10003 挂掉
   - manifest 中已包含 `mode: bypassPermissions` 字段，coordinator 读取后直接使用
   - 子代理 system_prompt 已声明 FULL read/write access，权限必须匹配

5. **Team 清理硬规则**：
   - 交付完成后**必须清理 team**，否则 workspace 会一直挂着
   - 清理顺序：先 `send_message(type="shutdown_request", recipient=每个member)` → 等 10 秒 → `team_delete()`
   - 如果 `team_delete()` 因 active member 失败，再次发送 shutdown_request 并等待后重试
   - 绝对不能跳过 team 清理就结束对话

5. **VL OCR API 配置**（代码 default 已内置，无需手动设环境变量）：
   - `VL_API_BASE`: `https://YOUR_VL_API_BASE`
   - `VL_API_KEY`: 需通过环境变量 `VL_API_KEY` 配置
   - `VL_MODEL`: `qwen3-vl-30b-a3b-instruct`

## Workspace 产物结构

每个 job 的产物在 `{IR_RUNTIME}/jobs/{JOB_ID}/` 下：

```
jobs/{JOB_ID}/
├── state/           # phase 状态 JSON + artifacts.json
├── briefs/          # step brief 文件
├── search/          # 搜索结果
├── extraction/      # URL 提取结果
├── artifacts/       # 中间产物
├── outputs/         # step 输出 (.md)
├── verification/    # 对抗验证结果
└── delivery/        # DOCX + 审计报告
```

## 关键子系统

### StateStore（统一状态协调）

- 协调 task_ledger（人读）+ task_registry（机读）+ JobWorkspace（产物容器）
- `create_job()` → 初始化 workspace + 注册
- `update_phase_status()` → phase 完成后同步
- `record_artifact()` → 产物记录
- `snapshot()` → 完整状态快照

### Scrapling（内容抓取）

ir_extract_content 的 `_fetch_text` 三层递进：
1. **Scrapling Fetcher** — TLS 指纹模拟，快速（覆盖 90%）
2. **Scrapling StealthyFetcher** — 自动绕 Cloudflare/WAF
3. **requests + BS4** — 兜底

### valuation_enricher（估值数据）

- 基于 yfinance 获取 PE/PB/PS/市值/52W 高低/EPS/beta 等
- A 股代码自动映射（6位→SZ/SS/BJ）
- 中文名映射（东江环保→002672.SZ）

## 质量门禁（硬规则）

1. **Step 完整性门禁** — `verify_step1_completeness.py`
   - BLOCK（<50%）→ 禁止进入后续 step
   - WARN（50-70%）→ 降级标记后可继续
   - PASS（>70%）→ 正常推进
2. **跨 Step 一致性门禁** — `verify_cross_step_consistency.py`
   - FAIL → 必须修正后再统稿
3. **子代理产出最低标准** — Step1 ≥100字含市场数据，Step2-7 ≥150行含来源
4. **完成率 <50% 熔断** — dispatch 阶段完成率不足时阻断 delivery

## 错误处理

- 环境检测失败：报告缺失项，不继续
- 任一 Step 空返回：5 分钟内重派
- 子代理超时（25 分钟）：重新派发，最多 2 次
- 验证 FAIL：修复后重验 1 次
- 全链路超时（120 分钟）：标注超时，交付已完成部分
- 数据不够不能往下跑；估值偏差 >20% 需告警

## 微信推送格式

```
📊 研报完成：{标的名称}

✅ 8 步分析已完成
📄 报告路径：{workspace}/delivery/{TASK_ID}.docx
🔍 对抗验证：PASS/PARTIAL

关键发现：
- {3 条核心结论，每条 ≤30 字}
```

## 向量记忆

- ChromaDB + qwen3-embedding-8b（小马算力）
- 配置路径：`~/.workbuddy/vector-memory/`
- 查询：`python3 ~/.workbuddy/vector-memory/query.py "查询文本"`
- 入库：`python3 ~/.workbuddy/vector-memory/ingest.py`
