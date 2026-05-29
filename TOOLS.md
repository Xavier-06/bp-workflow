## 搜索引擎（2026-04-04 统一网关）

**脚本导入：**
```python
from scripts.search_gateway import search, verify_engines
results = search("公司名 关键词", max_results=10)  # SearXNG 主力 → DDG 自动兜底
status = verify_engines()  # {"searxng": True/False, "ddg": True/False}
```

**CLI：**
```bash
python3 scripts/search_gateway.py '关键词' -n 10 --json
python3 scripts/search_gateway.py --verify           # 引擎状态检查
```

**统一搜索栈：**
- **SearXNG 本地（18080）**：26 引擎（Google/Brave/Bing/arXiv/Scholar/Reuters...），Clash 代理 127.0.0.1:7897
- **DDG（ddgs CLI）**：Rust HTTP 客户端，不走代理，SearXNG 不可用时全局自动兜底
- **Scrapling**：SearXNG 返回 URL → 抓正文 → LLM 提取（正文补抓）
- **Yahoo Finance**：估值补证（仅 IR 管线）
- **禁用**：Tavily（BP 管线零费用），Tavily（IR 管线已移除）

**回退链**：SearXNG 本地(18080) → SearXNG 公共实例 → DDG CLI → DDG Python 库

---

## 记忆去重

**脚本导入（函数，无类）：**
```python
from scripts.memory_dedup import add_content
add_content("内容", type="今日事项")
# decay/dedup 只能通过 CLI 调用
```

**CLI：**
```bash
python3 scripts/memory_dedup.py add "内容" --type 今日事项
python3 scripts/memory_dedup.py decay --days 30
python3 scripts/memory_dedup.py dedup --file memory/2026-04-07.md

---

## 预计算引擎（v5 新增）

### 财务指标预计算

```bash
# 完整预计算（ROE/ROA/毛利率/净利率/现金流/估值）
python3 scripts/financial_metrics_precompute.py AAPL
python3 scripts/financial_metrics_precompute.py 0700.HK

# API 导入
from scripts.financial_metrics_precompute import compute_all
result = compute_all("AAPL")  # dict: roe, roa, gross_margin, net_margin, fcf_yield, pe, pb, ps
```

**注意**：ROE/ROA 计算已修复 yfinance 季度数组长度不一致 Bug（income statement vs balance sheet 季度数可能不同）。

### 信息传导验证

```bash
# 7-Agent 信息传导验证
python3 scripts/info_propagation_check.py --task TASK-20260515-001
```

---

## CLI 任务管理

```bash
# 创建
python3 ir_runtime.py create "比亚迪" --type 专题研究类

# 重命名（修改标的/类型/标签）
python3 ir_runtime.py rename TASK-20260515-001 --target "优必选"
python3 ir_runtime.py rename TASK-20260515-001 --type 快报类
python3 ir_runtime.py rename TASK-20260515-001 --label "重点跟踪/周报素材"

# 查看
python3 ir_runtime.py status TASK-20260515-001
python3 ir_runtime.py list

# 执行
python3 ir_runtime.py run TASK-20260515-001 --phase 2

# 通知
python3 ir_runtime.py notify "研报已完成"
```

---

## 运维工具集

### 日常巡检
```bash
bash scripts/check-reminders.sh       # 提醒检查
bash scripts/check-skills.sh          # Skills 健康检查
bash scripts/watch-agent.sh           # Agent 运行监控
```

### 清理维护
```bash
bash scripts/cleanup_completed_tasks.sh   # 已完成任务清理
bash scripts/cleanup_memory.sh            # 记忆文件清理
bash scripts/cleanup_sessions.sh          # 会话文件清理
```

### 记忆管理
```bash
bash scripts/memory-cmd.sh [cmd]                    # 记忆命令入口
bash scripts/memory-decay.sh --days 30              # 记忆老化
python3 scripts/memory_dedup.py decay --days 30     # 去重衰退
```

### 环境与搜索
```bash
source scripts/load_workspace_env.sh       # 加载工作区环境变量
source scripts/python_ssl_env.sh           # Python SSL 证书配置
bash scripts/start_local_searxng.sh        # 启动本地 SearXNG
python3 scripts/searxng_manager.py         # SearXNG 管理器
```

### 路径修复
```bash
# 迁移后批量修复路径引用
python3 tools/patch_paths.py --root ~/.workbuddy/ir_runtime
```
