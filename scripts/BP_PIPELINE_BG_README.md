# BP Pipeline 后台分步执行

## 为什么改？

原版 `run_bp.py` 一口气跑完所有 phase，其中 `company_verify`（2-5分钟）和 `presearch`（3-10分钟）
是同步函数调用，受 WorkBuddy Bash 工具的超时限制（默认 2 分钟，最大 10 分钟）。
超时后系统发 SIGTERM 杀掉 Python 进程，导致管线截断。

## 架构

```
bp_pipeline_bg.py（编排器）
  │
  ├─ start phase05_company_verify  →  fork 后台运行，写 PID 文件
  │                                    ↓ 子进程独立执行，不受 Bash 超时限制
  │                                    ↓ 完成后写 .result.json，清理 PID
  │
  ├─ poll phase05_company_verify   →  读 .result.json / .pid 文件
  │
  └─ status-all                    →  列出所有 phase 状态
```

## Heavy vs Light Phases

| Phase | 耗时 | 执行方式 |
|-------|------|---------|
| phase0_document_intake | 30s | 前台 |
| phase05_company_verify | 2-5min | **后台** |
| phase1_presearch | 3-10min | **后台** |
| phase2_dispatch_prepare | 秒级 | 前台 |
| phase2_dispatch_collect | 秒级 | 前台 |
| phase25_competition_prepare | 秒级 | 前台 |
| phase25_competition_collect | 秒级 | 前台 |
| phase3_synthesis_prepare | 秒级 | 前台 |
| phase3_synthesis_collect | 秒级 | 前台 |
| phase3_delivery | 2-5min | **后台** |

## WorkBuddy Agent 调用示例

```bash
# 1. 文档入库（前台，很快）
python3 scripts/bp_pipeline_bg.py --job-id $JOB start phase0_document_intake \
    --entity "阅文集团" --market hk --input-file /path/to/bp.pdf

# 2. 主体核验（后台）
python3 scripts/bp_pipeline_bg.py --job-id $JOB start phase05_company_verify \
    --entity "阅文集团" --market hk

# 3. 等待完成（轮询）
python3 scripts/bp_pipeline_bg.py --job-id $JOB poll phase05_company_verify --timeout 600

# 4. 预搜索（后台）
python3 scripts/bp_pipeline_bg.py --job-id $JOB start phase1_presearch \
    --entity "阅文集团" --market hk

# 5. 等待预搜索完成
python3 scripts/bp_pipeline_bg.py --job-id $JOB poll phase1_presearch --timeout 900

# 6. 后续 phase 以此类推...

# 查看所有 phase 状态
python3 scripts/bp_pipeline_bg.py --job-id $JOB status-all
```

## 状态文件

每个 phase 运行期间和完成后，状态文件位于 `jobs/{job_id}/state/`：

- `{phase}.pid` — 进程 PID（运行中，完成后自动删除）
- `{phase}.running` — 开始时间戳（运行中）
- `{phase}.result.json` — 执行结果（完成后）
- `{phase}.error` — 错误信息（失败时）

## 注意事项

1. **不要同时启动同一 phase 两次**：`start` 会检测 PID 文件，避免重复运行
2. **重跑**：如果需要重跑某个 phase，直接再次 `start`，会自动清理旧的结果文件
3. **超时**：后台进程本身的超时由 Python 代码控制（搜索的 timeout 参数），不受 Bash 超时限制
