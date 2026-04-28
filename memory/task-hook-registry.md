# TaskRegistry + Hook 系统集成

> Claude Code 任务系统 + Hook 事件系统的 Python 移植 & 管线集成。
> 灵感来源：`/Users/xavier/Downloads/claude/restored-cli-src/src/` 下的 `Task.ts`、`tasks.ts`、`hooks.ts`、`AsyncHookRegistry.ts`、`hookEvents.ts`

---

## 核心模块

| 模块 | 路径 | 状态 |
|------|------|------|
| TaskRegistry | `scripts/task_registry.py` | ✅ 完整 |
| BP DD 任务预设 | `scripts/task_preset_bp_dd.py` | ✅ 完整 |
| IR 任务预设 | `create_ir_tasks()` (在 `run_ir_pipeline.py`) | ✅ 完整 |
| HookDispatcher | `scripts/hook_dispatcher.py` | ✅ 完整 |
| BP 管线集成 | `scripts/run_bp_pipeline.py` | ✅ 集成完成 |
| IR 管线集成 | `scripts/run_ir_pipeline.py` | ✅ 集成完成 (v5) |
| CLI（task） | `scripts/task.py` | ⏳ 独立 CLI（与 pipeline 无关） |

---

## 管线集成清单

### run_bp_pipeline.py 修复（2026-04-04 上午）

| Bug | 修复 |
|-----|------|
| `timeout_sec` 未定义 → NameError | 定义 `PIPELINE_TIMEOUT = 1800` |
| `_try_phase5` 中 `hooks` 未定义 → NameError | 改为 `_get_hooks(task_id)` |
| Phase 跳过 `in_progress` 状态 | 新增 `_phase_in_progress()` |
| Phase 1+/2 异常没有 `_phase_failed` | try/except 包裹+调用 `_phase_failed` |
| Phase 0 失败没发 Hook | 补 `_phase_failed(task_id, "phase0", 1, error)` |
| `phase4_poll` 不更新 TaskRegistry | 轮询完成时调 `get_ready_tasks()` |
| Phase 4 子代理匹配逻辑不精确 | 改用 `t.parent_id == 5`（phase4 子任务） |
| 搜索引擎不可用没标记失败 | 补 `_phase_failed` 调用 |

### run_ir_pipeline.py 升级（2026-04-04 下午）

| 新增 | 说明 |
|------|------|
| `create_ir_tasks()` | 10 个任务 + 8 个子代理的依赖树 |
| `_ir_cache` | IR 管线专用缓存（不与 BP 碰撞） |
| Phase 状态流转 | pending → in_progress → completed/failed |
| `_phase_failed` | 每个 Phase 异常都触发 Hook 通知 |
| `_quality_gate_results()` | Perplexity 级质量评分（8 维度 × 3 分） |
| `_self_review_loop()` | 不达标自动补搜，最多 2 轮 |
| Phase 5 质量门禁 | DOCX 生成前自动评估 + 自审查 |
| PipelineStarted/Completed Hook | 管线首尾事件通知 |

### 状态流转（通用）

```
PipelineStarted (Hook)
  ↓
_phase_in_progress
  ↓ 执行 Phase 逻辑
_phase_done / _phase_failed (Hook: PhaseCompleted / PhaseFailed)
  ↓ 循环至最后 Phase
PipelineCompleted (Hook)
```

---

## 质量门禁（Perplexity Deep Research 标准）

| 评估项 | 规则 |
|--------|------|
| 来源可信度 | 官方 (SEC/HKEX/巨潮) → 3 分，权威媒体 → 2 分，单一来源 → 1 分，无来源 → 0 分 |
| 最低总分 | IR 管线 ≥16/24（8 维度×3），BP 管线类似 |
| 红旗标记 | 3+ 个 `待补/TODO/无法验证` → 强制降分 |
| 自审查 | 不达标 → 针对薄弱环节补搜 → 重评 → 最多 2 轮 |

---

## Hook 配置

位置：`.pipeline/hooks/*.json`

当前 Hook：
```json
// pipeline_completed.json
{ "event": "PipelineCompleted", "command": "echo 'Pipeline completed: $PIPELINE (Phase: $PHASE)'", "async": true, "description": "管线完成后打印日志" }

// subagent_failed.json
{ "event": "SubagentFailed", "command": "echo '[ALERT] Subagent failed: $SUBAGENT_ID (Pipeline: $PIPELINE)'", "async": true, "description": "子代理失败告警" }

// error.json
{ "event": "Error", "command": "echo '[ERROR] Pipeline $PIPELINE failed: $ERROR_MSG'", "async": true, "description": "管线错误日志" }
```

---

## 后续 TODO

- [ ] 飞书通知 Hook（`notify_xavier.py` 脚本 → 调飞书 API 发消息）
- [ ] 持久化恢复（`/resume`：进程重启后从 last checkpoint 恢复）

---

*2026-04-04 — 移植 & 双管线集成完成*