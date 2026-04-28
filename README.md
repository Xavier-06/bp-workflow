# 🐲 BP Due Diligence Workflow

> AI 驱动的商业计划书（BP）尽调工作流，专为 WorkBuddy / OpenClaw 平台设计。

一套完整的 BP 尽调管线，从文档 OCR 到多维度研报生成，全自动运行。

## 🏗️ 架构概览

```
BP 文件 (PDF/PPTX/DOCX/图片)
  │
  ▼
┌─────────────────────────────────────────────┐
│ Phase 0: Document Intake                     │
│   VL OCR → 结构化抽取 (bp_step0_profile.json)│
├─────────────────────────────────────────────┤
│ Phase 0.5: Company Verify + 护城河锚定       │
│   工商/风险/创始人验证 + 发动机/油箱分析       │
├─────────────────────────────────────────────┤
│ Phase 1: Presearch                           │
│   4 维度预搜索（团队/技术/行业/竞争）           │
├─────────────────────────────────────────────┤
│ Phase 2: 4 维度分析（并行子代理）              │
│   Wave 1: 团队与合规 + 技术与产品 + 行业与供应链│
│   Wave 2: 竞争与结论（依赖 Wave 1）           │
├─────────────────────────────────────────────┤
│ Phase 3: 统稿 + 交付                         │
│   投研逻辑重组 → DOCX 生成 → 通知推送         │
└─────────────────────────────────────────────┘
```

## 📦 目录结构

```
bp-workflow/
├── runtime/                     # 核心运行时
│   ├── orchestrator/            # 编排引擎
│   │   ├── kernel.py            # 管线内核（phase 驱动）
│   │   ├── state_store.py       # 统一状态协调
│   │   ├── workspace_layout.py  # Job workspace 布局
│   │   └── manifest.py          # 子代理派遣清单
│   ├── profiles/                # 管线 Profile
│   │   ├── base.py              # Profile 基类 + JobContext
│   │   └── bp_profile.py        # BP 管线定义
│   ├── entrypoints/             # 管线入口
│   │   └── run_bp_pipeline_entry.py
│   └── intake/                  # 文档入库
│       └── bp_document_intake.py  # OCR + 结构化抽取
├── scripts/                     # 功能脚本
│   ├── bp_subagent_launcher_wb.py  # 子代理发射器
│   ├── bp_company_verify.py     # 工商/主体核验
│   ├── bp_presearch.py          # 多维度预搜索
│   ├── bp_delivery_gate.py      # 交付门禁
│   ├── bp_pipeline_healthcheck.py # 管线健康检查
│   ├── bp_preflight_check.py    # 管线起飞检查
│   ├── bp_report_format_rebuild.py # 报告格式重建
│   ├── bp_search_smoke.py       # 搜索冒烟测试
│   ├── bp_verify_consistency.py # 一致性验证
│   ├── build_bp_dd_report_docx.py  # DOCX 报告生成
│   ├── search_gateway.py        # 搜索网关（可替换）
│   └── notify_plugin.py         # 通知插件模板
├── instruction_store_bp/        # BP 角色指令库
│   ├── bp_主管.md                # 主控编排
│   ├── bp_团队与合规.md           # 维度 1
│   ├── bp_技术与产品.md           # 维度 2+3
│   ├── bp_行业与供应链.md         # 维度 4+5
│   ├── bp_竞争与结论.md           # 维度 6 + Deal Breakers
│   └── bp_统稿.md                # 统稿重组
├── skills/                      # AI 平台 Skill 定义
│   ├── ir-coordinator/SKILL.md  # 调度中心
│   ├── ir-researcher/SKILL.md   # 数据采集 Agent
│   ├── ir-reporter/SKILL.md     # 统稿 Agent
│   └── ir-verifier/SKILL.md     # 对抗验证 Agent
├── docs/                        # 文档
│   ├── pipeline-phases.md       # Phase 详解
│   ├── search-integration.md    # 🔍 搜索系统集成指南
│   ├── configuration.md         # 配置说明
│   ├── openclaw-setup.md        # OpenClaw 部署
│   └── workbuddy-setup.md       # WorkBuddy 部署
├── .env.example                 # 环境变量模板
├── requirements.txt             # Python 依赖
└── README.md
```

## 🚀 安装

### 前置条件

- Python 3.10+
- WorkBuddy 或 OpenClaw 平台
- 一个兼容 OpenAI API 的视觉模型（用于 BP OCR）
- 搜索系统（见 [搜索集成指南](docs/search-integration.md)）

### WorkBuddy 安装

```bash
# 1. 克隆到 WorkBuddy 工作目录
cd ~/.workbuddy/
git clone https://github.com/Xavier-06/bp-workflow.git ir_runtime

# 2. 安装 Python 依赖
cd ir_runtime
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填写你的 VL API 配置

# 4. 安装 Skill（4 个）
cp -r skills/ir-coordinator ~/.workbuddy/skills/
cp -r skills/ir-researcher ~/.workbuddy/skills/
cp -r skills/ir-reporter ~/.workbuddy/skills/
cp -r skills/ir-verifier ~/.workbuddy/skills/

# 5. 配置搜索系统
#    详见 docs/search-integration.md
#    推荐使用 WorkBuddy 自带的 neodata-financial-search + westock-data 插件

# 6. （可选）配置通知插件
#    编辑 scripts/notify_plugin.py 实现你的推送逻辑

# 7. 验证
python3 -m runtime.orchestrator.pipeline_orchestrator --help
```

### OpenClaw 安装

```bash
# 1. 克隆到 OpenClaw 工作目录
cd ~/.openclaw/workspace/
git clone https://github.com/Xavier-06/bp-workflow.git ir_runtime

# 2-5 同上

# 6. 在 OpenClaw 的 AGENTS.md 中添加触发规则
#    参见 docs/openclaw-setup.md
```

## 🔍 搜索系统集成

BP 管线的搜索能力可插拔替换，默认使用 SearXNG，推荐接入 WorkBuddy 金融搜索插件。

### 推荐方案：WorkBuddy 插件

| 插件 | 覆盖范围 | 使用场景 |
|------|---------|---------|
| `neodata-financial-search` | 股票/基金/宏观/外汇/商品 | **默认首选**，自然语言即问即答 |
| `westock-data` | K线/财报/资金流/技术指标/筹码/股东 | neodata 不覆盖的结构化数据 |
| `web_search` | 通用搜索 | 两者都无法满足时的回退 |

详见 [docs/search-integration.md](docs/search-integration.md)。

## 📋 使用方式

### 命令行提交 BP 任务

```bash
cd ~/.workbuddy/ir_runtime

# 提交 BP 尽调任务
python3 -m runtime.orchestrator.pipeline_orchestrator submit \
  --entity "公司名称" --market cn --input-file /path/to/bp.pdf

# 执行任务
python3 -m runtime.orchestrator.pipeline_orchestrator execute \
  --job-id TASK-XXXXXXXX-XXX

# 查看状态
python3 -m runtime.orchestrator.pipeline_orchestrator status \
  --job-id TASK-XXXXXXXX-XXX
```

### AI 对话触发

在 WorkBuddy/OpenClaw 对话中直接说：

- "帮我看下这个 BP" + 上传文件
- "分析一下 XX 公司的商业计划书"
- "对这个项目做个尽调"

ir-coordinator Skill 会自动识别并启动 BP 管线。

## 🔌 通知插件

管线交付时支持通过通知插件推送报告。内置模板支持以下扩展：

| 平台 | 实现方式 |
|------|---------|
| 微信 iLink Bot | `wechat-ilink-bot` SDK |
| Slack | Webhook |
| 飞书 | Bot API |
| Telegram | Bot API |
| 邮件 | SMTP |

编辑 `scripts/notify_plugin.py` 即可接入你的通知渠道。

## 🧩 扩展

### 添加新维度

1. 在 `instruction_store_bp/` 添加角色指令 `.md` 文件
2. 在 `bp_profile.py` 的 `_dispatch_role_specs()` 中注册新维度
3. 在 `bp_subagent_launcher_wb.py` 的 `ROLE_SYSTEM_PROMPTS` 中添加系统提示

### 自定义报告模板

编辑 `scripts/build_bp_dd_report_docx.py` 修改 DOCX 报告的布局、样式和内容结构。

### 替换搜索后端

实现 `SearchAdapter` 接口并在 `search_gateway.py` 中注册，详见 [搜索集成指南](docs/search-integration.md)。

## 🎯 核心设计理念

1. **Phase 驱动**：管线由 Phase 序列组成，每个 Phase 可独立运行、暂停、恢复
2. **Profile 模式**：BP/IR 管线共享编排内核，通过 Profile 定义差异
3. **Phase 0.5 护城河锚定**：在核验阶段同步完成商业模式分析（发动机/油箱），不必等后续维度
4. **子代理自主闭环**：子代理发现数据缺口时自主补搜，不回主控等待
5. **搜索可插拔**：搜索网关抽象层，支持 SearXNG / WorkBuddy 插件 / 自定义适配器
6. **断点续跑**：管线中断后可从任意 Phase 恢复，无需从头开始
7. **交付清洗**：报告中绝不暴露内部路径、Task ID、子代理术语

## 📄 License

MIT License

---

*Built with 🐲 for the AI agent community*
