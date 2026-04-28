# 🐲 IR/BP Workflow

> AI 驱动的投研（IR）+ 商业计划书尽调（BP）双管线工作流，专为 WorkBuddy / OpenClaw 平台设计。
> 从数据采集到研报交付，全自动运行，零人工干预。

## 🏗️ 双管线架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    ir-coordinator（调度中心）                     │
│                    接收指令 → 识别管线 → 全自动执行               │
├──────────────────────────┬──────────────────────────────────────┤
│     IR 管线（8步研报）     │       BP 管线（尽调报告）            │
│                          │                                      │
│ Phase 0:  环境检测+注册    │ Phase 0:  VL OCR 文档识别            │
│ Phase 0.5: 公司验证+估值   │ Phase 0.5: 工商/风险验证             │
│ Phase 1:  8步预搜索       │ Phase 1:  4维度预搜索+URL提取         │
│ Phase 1.5: URL内容提取     │ Phase 2:  3维度并行分析(Wave1)       │
│ Phase 4:  4波子代理派发    │ Phase 2.5: 竞争与结论(Wave2)         │
│   Wave1: 数据收集         │ Phase 3:  统稿+验证+DOCX交付         │
│   Wave2: 行业/商业/财务/管理│                                      │
│   Wave3: 洞察/风险        │                                      │
│   Wave4: 统稿             │                                      │
│ Phase 5:  对抗验证+DOCX   │                                      │
│           +桌面+微信通知    │                                      │
└──────────────────────────┴──────────────────────────────────────┘
         ↓ 交付 ↓
   📊 券商级研报 / DD尽调报告 (DOCX) → 桌面 + 微信通知
```

## 📦 目录结构

```
ir-bp-workflow/
├── runtime/                     # 核心运行时（双管线共用）
│   ├── orchestrator/            # 编排引擎
│   │   ├── pipeline_orchestrator.py  # 主入口 submit/execute
│   │   ├── kernel.py            # Phase 内核
│   │   ├── state_store.py       # 统一状态协调
│   │   ├── workspace_layout.py  # Job workspace 布局
│   │   └── manifest.py          # 子代理派遣清单
│   ├── profiles/                # 管线 Profile
│   │   ├── base.py              # Profile 基类
│   │   ├── ir_profile.py        # IR 管线定义
│   │   └── bp_profile.py        # BP 管线定义
│   ├── entrypoints/             # 管线入口
│   ├── intake/                  # BP 文档入库 + VL OCR
│   ├── delivery/                # 交付子系统
│   └── verification/            # 验证子系统
├── scripts/                     # 功能脚本（40+）
│   ├── ir_subagent_launcher_wb.py   # IR 子代理发射器
│   ├── bp_subagent_launcher_wb.py   # BP 子代理发射器
│   ├── build_ir_broker_report_docx.py  # IR 研报 DOCX
│   ├── build_bp_dd_report_docx.py   # BP DD DOCX
│   ├── verification_agent.py    # 6层对抗验证
│   ├── verify_step1_completeness.py  # Step1 完整性门禁
│   ├── verify_cross_step_consistency.py  # 跨Step一致性
│   ├── search_gateway.py        # 搜索网关
│   ├── longshao_notify.py       # 微信通知
│   └── ...                      # 更多脚本见 docs/
├── instruction_store_ir/        # IR 角色指令库（8步）
│   ├── 投研_主笔_数据收集.md
│   ├── 投研_主笔_行业分析.md
│   ├── 投研_主笔_商业模式.md
│   ├── 投研_主笔_财务分析.md
│   ├── 投研_主笔_管理层.md
│   ├── 投研_主笔_差异化洞察.md
│   ├── 投研_主笔_风险催化.md
│   ├── 投研_主笔_文档汇总.md
│   └── 投研_主管.md
├── instruction_store_bp/        # BP 角色指令库（6维度）
│   ├── bp_团队与合规.md
│   ├── bp_技术与产品.md
│   ├── bp_行业与供应链.md
│   ├── bp_竞争与结论.md
│   ├── bp_统稿.md
│   └── bp_主管.md
├── skills/                      # AI Agent Skill 定义
│   ├── ir-coordinator/SKILL.md  # 🧠 调度中心（触发入口）
│   ├── ir-researcher/SKILL.md   # 🔍 数据采集 Agent
│   ├── ir-reporter/SKILL.md     # 📝 统稿 Agent
│   └── ir-verifier/SKILL.md     # 🛡️ 对抗验证 Agent
├── search/                      # 搜索子系统
│   ├── adapters/                # 搜索适配器（SearXNG/DDG/SEC/HKEX/...）
│   ├── models/                  # 搜索数据模型
│   ├── gateway.py               # 搜索网关统一入口
│   └── entity_resolver.py       # 实体解析
├── research/                    # 研究子系统
│   ├── planner.py               # 研究计划编排
│   ├── query_expander.py        # 查询扩展
│   └── memo_builder.py          # 研究备忘录
├── sources/                     # 来源子系统
├── routing/                     # 路由子系统
├── content/                     # 内容抓取（Scrapling 三层递进）
├── memory/                      # 分层记忆（hot/warm/topics）
├── memory_agent/                # 记忆管理 Agent
├── config/                      # 配置文件
├── tasks/                       # 估值增强器等工具
├── docs/                        # 文档
│   ├── pipeline-phases.md       # Phase 详解
│   ├── search-integration.md    # 搜索集成指南
│   ├── configuration.md         # 配置说明
│   ├── workbuddy-setup.md       # WorkBuddy 部署
│   └── openclaw-setup.md        # OpenClaw 部署
├── setup.sh                     # 🚀 一键安装脚本
├── .env.example                 # 环境变量模板
├── requirements.txt             # Python 依赖
└── README.md
```

## 🚀 一键安装

```bash
# 克隆并安装（WorkBuddy）
bash <(curl -fsSL https://raw.githubusercontent.com/Xavier-06/ir-bp-workflow/main/setup.sh)

# 或者手动安装
git clone https://github.com/Xavier-06/ir-bp-workflow.git ~/.workbuddy/ir_runtime
cd ~/.workbuddy/ir_runtime
bash setup.sh

# OpenClaw 用户
git clone https://github.com/Xavier-06/ir-bp-workflow.git ~/.openclaw/workspace/ir_runtime
cd ~/.openclaw/workspace/ir_runtime
bash setup.sh --openclaw
```

### 安装脚本做什么

1. 克隆/更新仓库到 `~/.workbuddy/ir_runtime/`
2. 安装 Python 依赖
3. 从 `.env.example` 创建 `.env`（需手动填写 API 密钥）
4. 安装 4 个 Skills 到 `~/.workbuddy/skills/`
5. 创建运行时目录（jobs/logs/data/sessions）
6. 验证管线编排器可用

### 前置条件

- Python 3.10+
- WorkBuddy 或 OpenClaw 平台
- 可选：兼容 OpenAI API 的视觉模型（BP OCR 用）
- 可选：SearXNG 实例（增强搜索，也可用平台自带插件）

## 📋 使用方式

### IR 管线：股票研报

```bash
# 命令行提交
cd ~/.workbuddy/ir_runtime
python3 -m runtime.orchestrator.pipeline_orchestrator submit \
  --entity "比亚迪" --market cn --query "新能源车竞争力"

python3 -m runtime.orchestrator.pipeline_orchestrator execute \
  --job-id TASK-XXXXXXXX-XXX
```

**对话触发**（推荐）：
- "分析比亚迪"
- "跑个研报看看腾讯"
- "对优必选做个尽调"

### BP 管线：商业计划书尽调

```bash
# 命令行提交
python3 -m runtime.orchestrator.pipeline_orchestrator submit \
  --entity "公司名称" --market cn --input-file /path/to/bp.pdf
```

**对话触发**（推荐）：
- "帮我看下这个 BP" + 上传文件
- "分析一下 XX 公司的商业计划书"
- "对这个项目做个尽调"

ir-coordinator 自动识别意图并启动对应管线。

## 🔍 搜索系统

管线搜索能力可插拔，推荐接入 WorkBuddy 金融搜索插件：

| 优先级 | 插件 | 覆盖范围 | 场景 |
|--------|------|---------|------|
| 1 | `neodata-financial-search` | 股票/基金/宏观/外汇/商品 | **默认首选**，自然语言即问即答 |
| 2 | `westock-data` | K线/财报/资金流/技术指标/筹码/股东 | neodata 不覆盖的结构化数据 |
| 3 | `web_search` | 通用搜索 | 两者都无法满足时的回退 |

离线/增强搜索：SearXNG 本地实例（`scripts/searxng_manager.py` 可一键启停）。

详见 [docs/search-integration.md](docs/search-intases.md)。

## 🧠 4 个 AI Agent

| Agent | 职责 | 触发方式 |
|-------|------|---------|
| **ir-coordinator** | 调度中心，编排 IR/BP 管线全自动执行 | 用户对话直接触发 |
| **ir-researcher** | 单维度数据采集，自主补搜闭环 | coordinator 内部调度 |
| **ir-reporter** | 统稿 + DOCX 生成 + 对抗验证 + 交付 | coordinator 内部调度 |
| **ir-verifier** | 6层对抗验证（L1-L5 脚本 + L6 人工论证） | coordinator 内部调度 |

## 🎯 核心设计理念

1. **Phase 驱动** — 管线由 Phase 序列组成，每个 Phase 可独立运行/暂停/恢复
2. **Profile 模式** — IR/BP 共享编排内核，通过 Profile 定义差异
3. **子代理自主闭环** — 发现数据缺口时自主补搜，不回主控等待
4. **搜索可插拔** — 搜索网关抽象层，支持 SearXNG / WorkBuddy 插件 / 自定义适配器
5. **断点续跑** — 管线中断后可从任意 Phase 恢复
6. **质量门禁** — Step 完整性 >70%、跨 Step 一致性、完成率 <50% 熔断
7. **交付清洗** — 报告绝不暴露内部路径/Task ID/子代理术语
8. **Zero Human Intervention** — 全自动推进，用户不需要发"继续"

## 🧩 扩展

### 添加新维度

1. 在 `instruction_store_ir/` 或 `instruction_store_bp/` 添加角色指令
2. 在对应 Profile 中注册新维度
3. 在 `ir_subagent_launcher_wb.py` 中添加系统提示

### 替换搜索后端

实现 `SearchAdapter` 接口并在 `search_gateway.py` 中注册，详见 [搜索集成指南](docs/search-integration.md)。

### 自定义通知

编辑 `scripts/longshao_notify.py` 或 `scripts/notify_plugin.py` 接入你的通知渠道。

## 📄 License

MIT License

---

*Built with 🐲 for the AI agent community*
