# IR 管线执行协议 (WorkBuddy Team 异步模式)

> **铁律：全自动推进，Zero Human Intervention。用户不需要发"继续"。**

## 触发条件

用户提供 **公司名/股票代码 + "研究/研报/IR"** → 读取本协议并执行。

## 总览

IR 管线 = 4 Wave × 8 Step + Phase 5 交付。主 AI 作为编排者（orchestrator），循环推进。

```
Wave 1: step1_data
Wave 2: step2_industry, step3_biz, step4_finance, step5_mgmt  (并行)
Wave 3: step6_insight, step7_risk  (并行)
Wave 4: step8_master
Phase 5: 质量门禁 → DOCX → 桌面 → 通知
```

## 执行流程（伪代码）

```python
# 1. 初始化任务
task_id = create_task_id()
write_task_package(task_id, entity, market, query)

# 2. 创建 team
team_create(team_name=f"ir-{task_id}")

# 3. 循环发射 wave
while True:
    result = launch_next_wave(task_id, entity, query, market)
    
    if result['all_done']:
        break
    
    # 为本 wave 的每个 step 派发 team member（并行）
    for instruction in result['task_tool_instructions']:
        task(
            subagent_name='code-explorer',
            name=instruction['step'],              # team member 名称
            team_name=f'ir-{task_id}',             # 加入 team
            mode='bypassPermissions',              # 写文件权限
            description=instruction['step'],
            prompt=instruction['prompt'],          # 含 brief_path + output_path
        )
    
    # 轮询等待本 wave 所有输出文件
    # execute_command: sleep 30 && test -s {output_path}
    # 最多等 15 分钟，超时则重派
    # → 不需要用户介入，直接进入下一轮循环

# 4. 清理 team
team_delete()

# 5. 全部 wave 完成 → finalize
result = finalize_pipeline(task_id, entity, market)
# → DOCX 生成 + 桌面投放 + 微信通知（含文件）
```

## 关键 API（ir_subagent_launcher_wb.py）

| 函数 | 用途 |
|------|------|
| `launch_next_wave(task_id, entity, query, market)` | 发射当前 wave，返回 team 派发指令 |
| `get_pipeline_status(task_id)` | 查看管线状态快照 |
| `get_current_wave_index(task_id)` | 当前该发射哪个 wave |
| `finalize_pipeline(task_id, entity, market)` | Phase 5 统稿交付 |
| `check_step_quality(task_id, step)` | 单 step 质检 |

## 铁律

### 1. 子代理派发方式
- **必须用 team 异步模式**：`team_create()` → `task(name=..., team_name=..., mode='bypassPermissions')` → 轮询输出文件
- **禁止用同步 `task()`**（无 name 参数）——会返回 code=10003 挂掉
- `subagent_name` 固定为 `code-explorer`
- 派发后通过 `execute_command` 轮询输出文件是否存在且 >100 字节

### 2. Wave 间不停
- 一个 wave 的所有子代理完成后，**立即**调用 `launch_next_wave()`
- **禁止**等待用户确认、禁止输出"请告诉我是否继续"

### 3. 子代理失败处理
- 输出文件超时未出现 → **重派一次**（重新 task with name）
- 重试仍然失败 → 记录失败原因，跳过该 step，继续下一 wave
- step8_master 失败 → 用已有 step 输出人工拼接兜底

### 4. 交付必须完成
- Phase 5 `finalize_pipeline()` 必须执行
- DOCX 失败 → 用 markdown 兜底
- **研报必须复制到桌面**
- **微信通知必须尝试发送**（含 `--file` 参数发送报告文件）

### 5. 输出格式
- 最终交付物优先 DOCX，DOCX 生成失败才用 markdown
- 中间 step 输出始终为 markdown

## 错误恢复

如果管线中途因 context window 等原因断裂：
1. 调用 `get_pipeline_status(task_id)` 看哪些 step 已完成
2. 调用 `launch_next_wave()` 自动从断点继续
3. 不需要从头开始

## 示例：完整一次执行

```
team_create("ir-TASK-XXX")
🌊 Wave 1/4 → step1_data → task(name=step1_data) → ✅
🌊 Wave 2/4 → step2-5 → 4× task(name=stepX) → ✅✅✅✅
🌊 Wave 3/4 → step6-7 → 2× task(name=stepX) → ✅✅
🌊 Wave 4/4 → step8_master → task(name=step8) → ✅
team_delete()
📊 finalize → 质量门禁 → DOCX → 桌面 → 微信(含文件) → ✅ Done
```

---
*最后更新: 2026-04-24 — IR 管线 Team 异步模式执行协议 v2*
