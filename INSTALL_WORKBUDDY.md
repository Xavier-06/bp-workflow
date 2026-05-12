# IR/BP Workflow — WorkBuddy 安装指南

## 一键安装（推荐）

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Xavier-06/ir-bp-workflow/main/setup.sh)
```

安装脚本自动完成：克隆仓库 → 安装 Python 依赖 → 创建 .env → 安装 Skills → 验证安装。

## 手动安装

### 1. 克隆仓库

```bash
git clone https://github.com/Xavier-06/ir-bp-workflow.git ~/.workbuddy/ir_runtime
```

### 2. 安装 Python 依赖

```bash
cd ~/.workbuddy/ir_runtime
pip3 install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填写你的 API 密钥和搜索配置
```

必填项见 `.env` 内注释，核心配置：
- `VL_API_BASE` / `VL_API_KEY` — VL OCR API（BP 文档识别）
- `PROXY_URL` — HTTP 代理（Google/Scrapling 层需要，留空则自动降级）
- `SEARXNG_URL` — SearXNG 本地实例（推荐 Docker 部署，留空则跳过）

### 4. 安装 Skills

```bash
for skill in ir-coordinator ir-researcher ir-reporter ir-verifier; do
  mkdir -p ~/.workbuddy/skills/$skill
  cp ~/.workbuddy/ir_runtime/skills/$skill/SKILL.md ~/.workbuddy/skills/$skill/
  cp -r ~/.workbuddy/ir_runtime/skills/$skill/references ~/.workbuddy/skills/$skill/ 2>/dev/null || true
done
```

### 5. 重启 WorkBuddy

Skills 安装后需重启 WorkBuddy 才能加载。

## 仓库目录结构

```
ir_runtime/
├── ir_runtime.py          # 主入口（健康检查、SSL 证书探测、环境初始化）
├── run_bp.py              # BP 尽调入口
├── runtime/               # 管线编排器
│   └── orchestrator/      # pipeline_orchestrator.py
├── scripts/               # 搜索网关、SearXNG、记忆去重、预检等
│   ├── search_gateway.py  # 6 层搜索降级链
│   ├── searxng_search.py  # SearXNG 客户端
│   └── ...
├── search/                # 搜索适配器 + 模型
├── research/              # 研究模块
├── content/               # 内容抓取模块
├── routing/               # 路由模块
├── sources/               # 数据源模块
├── instruction_store_ir/  # IR 研报角色指令库（11 个角色）
├── instruction_store_bp/  # BP 尽调角色指令库（7 个角色）
├── memory/                # 记忆桥接层 + 主题记忆
├── memory_agent/          # 向量记忆系统
├── rules/                 # ANTI-DEFECT 规则 + 管线规则
├── skills/                # 4 个 WorkBuddy Skills
│   ├── ir-coordinator/    #   调度中心
│   ├── ir-researcher/     #   数据采集
│   ├── ir-reporter/       #   统稿交付
│   └── ir-verifier/       #   对抗验证
├── config/                # 配置文件
├── tasks/                 # 任务模板
├── docs/                  # 文档
├── requirements.txt       # Python 依赖
├── setup.sh               # 一键安装脚本
└── .env.example           # 环境变量模板
```

## 验证安装

```bash
cd ~/.workbuddy/ir_runtime
python3 runtime/orchestrator/pipeline_orchestrator.py --help
python3 scripts/ir_preflight_check.py --help
```

## 搜索引擎配置

搜索网关采用 6 层降级链，按需配置（不配置的层自动跳过）：

| 层级 | 引擎 | 需要配置 | 说明 |
|------|------|----------|------|
| L0 | NeoData | neodata-financial-search skill | A/HK 金融数据，WorkBuddy 自动鉴权 |
| L1 | DuckDuckGo | `pip install duckduckgo-search` | 免翻墙，开箱即用 |
| L2 | SearXNG | `SEARXNG_URL` + Docker | 本地聚合搜索 |
| L3 | Google | `PROXY_URL` | 需代理 |
| L4 | Scrapling | `PROXY_URL` | 高级抓取，需代理 |
| L5 | yfinance | 无 | 上市股票行情兜底 |

## 注意

- 仓库**不含**密钥、venv、logs、历史运行数据
- 所有端口和路径均通过环境变量配置，无硬编码
- 支持 WorkBuddy 和 OpenClaw 两种平台（`setup.sh --openclaw`）

## MCP 工具依赖（BP 管线）

BP 管线的工商验证和维度分析依赖企查查 MCP，需在 WorkBuddy 设置中连接 `qcc-company` 服务：

| MCP 工具 | 能力 | BP 管线用途 |
|---------|------|------------|
| `mcp__qcc-company` | 工商信息（股东、注册资本、法人、变更、分支机构、对外投资） | Phase 0.5 验证、竞争分析、产业链 |
| `mcp__qcc-risk` | 风险信息（诉讼、失信被执行人、行政处罚、经营异常） | 团队合规维度 |
| `mcp__qcc-ipr` | 知识产权（专利、商标、著作权） | 团队合规维度 |
| `mcp__qcc-operation` | 经营信息（招投标、资质许可、年报） | 竞争分析、行业供应链、估值 |

> 未连接企查查 MCP 时，BP 管线仍可运行，但工商验证和结构化竞品数据将缺失。IR 管线不依赖企查查 MCP。
