# IR 管线详细流程

## 管线阶段

```
phase0_preflight          — 环境检测 + 任务注册 + NeoData token 预检
phase05_company_verify    — 公司验证 + 估值数据 (NeoData优先 + yfinance交叉验证)
phase1_presearch          — 10 step 预搜索 (NeoData Layer 0 + SearchGateway/SearXNG)
phase15_extract           — URL 内容提取 (Scrapling 三层递进)
phase12_precompute        — 预计算引擎: financial_metrics + sector_benchmarks
│   └── 输出写入 data/tasks/{TASK_ID}_precompute_{engine}.json 供子代理使用
phase4_dispatch_prepare   — launch_next_wave() 发射第一个 wave，返回 needs_dispatch
│   └── kernel 暂停，coordinator 循环 launch_next_wave() 推进所有 wave
phase4_dispatch_collect   — 检查子代理输出 + 质量门禁
phase5_delivery           — 对抗验证 + DOCX + 交付（或由 finalize_pipeline() 代替）
```

## 核心 API

```python
from ir_subagent_launcher_wb import (
    launch_next_wave,      # 发射当前 wave，返回 team 派发指令
    get_pipeline_status,   # 管线状态快照
    get_current_wave_index,# 当前该发哪个 wave
    finalize_pipeline,     # Phase 5 全自动（质检→DOCX→桌面→微信）
    check_step_quality,    # 单 step 质检
)
```

## 提交任务

```bash
# ⚠️ 所有 python3 管线命令必须带 cd 前缀（Bash 每次调用是独立 shell）
cd ~/.workbuddy/ir_runtime && python3 -m runtime.orchestrator.pipeline_orchestrator submit \
  --entity "标的名称" --market cn --query "研究重点"

# 执行管线（同样必须带 cd）
cd ~/.workbuddy/ir_runtime && python3 -m runtime.orchestrator.pipeline_orchestrator execute --job-id TASK-XXXXX

# ⚠️ 如果返回 needs_poll: true + bg_pid，必须轮询到进程结束才能推进
# while kill -0 {bg_pid} 2>/dev/null; do sleep 30; done
```

返回 `job_id`（如 `TASK-XXXXXXXX-XXX`）。

## Wave 编排

> **架构对齐**：10-Agent 实战管线：step_macro（宏观面）+ step6b_valuation（估值面）等。

```
Wave 1: step1_data                                      (串行)
Wave 2: step2_industry, step3_biz, step4_finance, step5_mgmt, step_macro  (并行)
Wave 3: step6b_valuation                               (串行)
Wave 4: step6_insight, step7_risk                      (并行)
Wave 5: step8_master                                   (串行)
Phase 5: finalize_pipeline() → 质检 → DOCX → 桌面 → 微信通知
```

### IR Step 依赖和波次

| 波次 | Steps | 依赖 | 预估时间 |
|------|-------|------|---------|
| Wave 1 | step1_data | 无 | 10-25 分钟 |
| Wave 2 | step2_industry, step3_biz, step4_finance, step5_mgmt, step_macro | 无 (独立) | 每个 15-25 分钟 |
| Wave 3 | step6b_valuation | step1+4 | 15-25 分钟 |
| Wave 4 | step6_insight, step7_risk | step1+2+3 / step1+3+4 | 每个 15-25 分钟 |
| Wave 5 | step8_master | step1~step7_risk | 20-30 分钟 |

## 预计算数据（Phase 1.2 输出）

预计算引擎在 `phase15_extract` 之后自动运行，输出写入 `{IR_RUNTIME}/data/tasks/`：

| 引擎 | 输出文件 | 使用者 |
|------|---------|--------|
| financial_metrics | `{TASK_ID}_precompute_financial_metrics.json/.md` | step4_finance, step6b_valuation |
| sector_benchmarks | `{TASK_ID}_precompute_sector_benchmarks.json/.md` | step2_industry, step6_insight |

**子代理使用方式**：
```bash
# 读取预计算数据（JSON 格式）
cat {IR_RUNTIME}/data/tasks/{TASK_ID}_precompute_financial_metrics.json | python3 -m json.tool

# 或读取 markdown 格式（方便人类阅读）
cat {IR_RUNTIME}/data/tasks/{TASK_ID}_precompute_financial_metrics.md
```

子代理 step brief 中会包含预计算数据路径，子代理应优先读取预计算数据，再根据需要补充搜索。

## 执行伪代码（Coordinator 循环）

```python
# Phase 0-1.5: 管线自动跑 preflight → company_verify → presearch → extract
python3 -m runtime.orchestrator.pipeline_orchestrator execute --job-id TASK-XXXXX
# → 管线在 phase4_dispatch_prepare 暂停，返回 needs_dispatch=True + task_tool_instructions

# Phase 4: Coordinator 用 team 异步模式发射 wave
MAX_RETRIES = 2
TOOL_LIMITS = """⚠️ 工具限制：你没有 Glob/Grep 工具。搜索文件用 Bash（find/ls），读文件用 Read，搜索内容用 Bash（grep）。不要调用 Glob 或 Grep。
NeoData 金融数据查询（A/HK 股首选，token 已在 preflight 存好）：
  cd ~/.workbuddy/ir_runtime && python3 -c "from scripts.search_gateway import neodata_search; import json; print(json.dumps(neodata_search('查询语句'), ensure_ascii=False))"
"""

# 1. 创建 team
team_create(team_name=f"ir-{task_id}")

while True:
    result = launch_next_wave(task_id, entity, query, market)
    
    if result['all_done']:
        break
    
    # 为本 wave 每个 step 派发 team member（同一 wave 内并行）
    # ⚠️ 规则4：prompt 开头必须加 TOOL_LIMITS
    for instruction in result['task_tool_instructions']:
        step = instruction['step']
        output_path = instruction['output_path']
        
        Agent(
            name=f'{step}',
            team_name=f'ir-{task_id}',
            mode='bypassPermissions',
            description=step,
            prompt=TOOL_LIMITS + "\n" + instruction['prompt'],
            run_in_background=True
        )
    
    # 规则5：主动轮询输出文件，不等消息
    # 具体做法：派发完所有子代理后，用一个 Bash 命令循环检查
    # bash: while true; do all_ok=true; for f in path1 path2 ...; do test -s "$f" || all_ok=false; done; $all_ok && break; sleep 60; done
    # 超过 20 分钟未完成的 step → 重派（最多 2 次）
    
    # 规则6：shutdown 后从 config 移除成员
    # 收到 shutdown_response approve 后立即执行：
    # python3 -c "import json; p='/Users/xavier/.workbuddy/teams/{team}/config.json'; d=json.load(open(p)); d['members']=[m for m in d['members'] if m['name']!='{step}']; json.dump(d,open(p,'w'),ensure_ascii=False,indent=2)"
    # 如果仍无法派发 → TeamDelete → 新建 team
    # ⚠️ 2026-05-11 实测：TeamDelete 也可能无法清除 Agent 工具的内存注册表
    # 如果 TeamDelete 后仍报 "A teammate named X is already active"，说明框架级内存锁死
    # 此时唯一方案是重启 session，当前任务无法继续

# 清理 team
team_delete()

# Phase 5: 全自动交付
result = finalize_pipeline(task_id, entity, market)
```

## IR 子代理派发规则

- **必须用 team 异步模式**：`team_create()` → `Agent(name=..., team_name=..., run_in_background=True)` → 轮询输出文件
- **禁止用同步 `task()`**（无 name 参数）——会返回 code=10003 挂掉
- `subagent_name` 固定为 `code-explorer`
- `mode="bypassPermissions"` 确保子代理可写文件
- **⚠️ 子代理 prompt 必须加工具限制声明**（规则4）：Glob/Grep 不存在，用 Bash+Read 替代
- `launch_next_wave()` 返回的 `task_tool_instructions` 包含完整的 prompt（含 brief_path + output_path）
- **派发后主动轮询**（规则5）：每 60 秒用 Bash `test -s` 检查输出文件，不依赖子代理消息
- **shutdown 后清理 team config**（规则6）：从 config.json members 移除已退出成员
- 输出文件超时未出现 → 重派（最多重试 2 次）
- 重试仍然失败 → 记录失败原因，跳过该 step，继续下一 wave
- step8_master 失败 → 用已有 step 输出拼接兜底

## IR 交付规则

- `finalize_pipeline()` **必须执行**（全自动：质检 → DOCX → 桌面 → 微信通知）
- DOCX 失败 → 用 markdown 兜底
- **研报必须复制到桌面**
- **微信通知必须尝试发送**（通过 `longshao_notify.py` → wechat_bot SDK）
  - ⚠️ `longshao_notify.py` 已升级为三步发送（文本通知→文件→确认文本）
  - 如果 `--file` 调用返回 `ok: false`，必须重试一次
  - 即使返回 `ok: true`，也要提醒用户检查微信是否收到（SDK send_file 静默失败不抛异常）
- 交付完成后，在聊天窗口告知用户文件完整路径
- **禁止**使用 `deliver_attachments`（客户端不显示附件）

## Wave 5 step8_master 统稿硬约束

- 读取 step1~step7_risk 全部输出，汇总为券商风格完整研报（投资摘要→行业→商业模式→财务估值→管理层→宏观→差异化洞察→风险催化剂→来源附录）
- **脚注硬规则**：正文每个关键数据点都要有脚注标注，末尾"来源附录"展开完整引用
- **跨章节数据一致性**：同一指标在不同章节出现时数字必须一致，以有明确来源的为准
- **算术验算**：PE×EPS≈股价、市值=股价×总股本等关键算术必须自验
- **⚠️ 统稿保留硬约束**（解决统稿过度压缩问题）：
  - **核心对比表必须原文保留**：行业竞争格局对比表、产品参数对比表、估值对比表——不得删除或压缩为文字叙述
  - **市占率/份额/渗透率数据必须完整保留**：TAM/SAM/SOM分层推算及每层具体数字、各细分市场渗透率、竞品市占率（具体数字和百分比，不能只写"垄断竞争"等模糊表述）、标的公司渗透率——这些是判断市场空间的核心依据
  - **去重只做跨step，不做step内压缩**：跨step重复内容可合并，但单个step内部的表格、数据、分析段落不得删除或压缩
  - **来源合并不得丢来源**：所有step的来源索引表/脚注列表都必须合并到统稿末尾"来源附录"章节，不能因格式不同（[^N]脚注/编号表格/URL直接引用/评级格式）就丢弃；非[^N]格式的来源必须转换为[^N]脚注格式纳入统一编号；目标：统稿来源总数 ≥ 各step来源去重后总数
- 总字数不低于原始各 step 内容总量的 70%（禁止过度压缩）

## 子代理自主闭环规则

子代理在执行过程中必须自主闭环，不要回主控等待指示：
1. **检测到数据缺口** → 自己补搜（NeoData/yfinance/web_search/企查查MCP），继续推进
2. **来源不足** → 自己搜更多来源，补充到输出中
3. **数据矛盾** → 自己判断哪个更可靠，标注矛盾来源
4. **前序 step 输出有 gap** → 自己补充搜索填补
5. **唯一需要回主控的情况**：step 输出文件写完，表示完成

## 错误恢复（断点续跑）

如果管线中途因 context window 等原因断裂：
1. `get_pipeline_status(task_id)` 看哪些 step 已完成
2. `launch_next_wave()` 自动从断点继续（已完成的 step 自动跳过）
3. 不需要从头开始
