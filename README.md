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
│   Wave3: 洞察/风险/估值    │                                      │
│   Wave4: 统稿             │                                      │
│ Phase 5:  对抗验证+DOCX   │                                      │
│           +桌面+微信通知    │                                      │
└──────────────────────────┴──────────────────────────────────────┘
         ↓ 交付 ↓
   📊 券商级研报 / DD尽调报告 (DOCX) → 桌面 + 微信通知
```

## ❓ 解决什么问题

### 痛点一：AI 投研"浅尝辄止"
市面 AI 研报工具只能生成"资料汇编"——堆砌公开信息，缺乏投研逻辑深度。真正的券商研报需要 8 个维度的系统性分析（数据/行业/商业/财务/管理层/洞察/风险/估值/统稿），单轮对话无法完成。

### 痛点二：多 Agent 协作"各自为政"
现有 Agent 框架（AutoGPT、CrewAI）的痛点：子 Agent 挂掉（code=10003）、上下文断裂、数据口径不一致、最终需要人工拼接。我们构建了**有状态编排器**——统一状态协调、manifest 派发、自动重试、断点续跑。

### 痛点三：BP 尽调"信息黑洞"
早期项目的 BP 尽调面临两难：创始人自说自话（信息偏差）vs 昂贵的人工尽调（成本高、周期长）。本管线自动化完成 **VL OCR → 结构化抽取 → 4 维度并行分析 → 竞争格局 → 统稿 → DOCX 交付**，30 分钟内完成全链路。

### 痛点四：交付链路断裂
研报写完了，但复制到桌面、转 DOCX、发微信通知——这些"最后一公里"经常被模型遗忘。管线有**强制 finalize 步骤**：对抗验证 → DOCX 生成 → 桌面复制 → 微信推送（三步协议），报告不会丢。

### 痛点五：数据时效性和真实性
AI 生成研报最大的隐患：**编造不存在的人名、使用过时的融资状态、引用已撤销的政策**。v5 引入 **ANTI-DEFECT RULES**——每个 step/维度 都有专属验证规则（人员存在性验证、融资状态搜索验证、数据时效性检查等），从根源上防止幻觉。

## 📦 目录结构

```
ir-bp-workflow/
├── runtime/                     # 核心运行时（双管线共用）
│   ├── profiles/                # 管线 Profile
│   │   ├── bp_profile.py        # BP 管线定义（含竞争与结论强制派发+附件收集）
│   │   └── ...
│   ├── entrypoints/             # 入口点
│   ├── intake/                  # 输入处理
│   └── orchestrator/            # 管线编排器
├── scripts/                     # 功能脚本（160+）
│   ├── ir_subagent_launcher_wb.py   # IR 子代理发射器（含 ANTI-DEFECT RULES）
│   ├── bp_subagent_launcher_wb.py   # BP 子代理发射器（含 ANTI-DEFECT RULES）
│   ├── search_gateway.py            # 搜索网关 v5（含 NeoData Layer 0）
│   ├── build_ir_broker_report_docx.py  # IR 研报 DOCX
│   ├── build_bp_dd_report_docx.py   # BP DD DOCX
│   ├── build_valuation_excel.py     # 估值 Excel 生成
│   ├── verification_agent.py        # 6层对抗验证
│   ├── ir_auto_orchestrator.py      # IR 全自动编排器
│   ├── longshao_notify.py           # 微信通知
│   └── ...
├── instruction_store_ir/        # IR 角色指令库 v4（11 个角色）
├── instruction_store_bp/        # BP 角色指令库 v4（7 个维度）
├── skills/                      # AI Agent Skill 定义
│   ├── ir-coordinator/SKILL.md  # 🧠 调度中心
│   ├── ir-researcher/SKILL.md   # 🔍 数据采集 Agent
│   ├── ir-reporter/SKILL.md     # 📝 统稿 Agent
│   └── ir-verifier/SKILL.md     # 🛡️ 对抗验证 Agent
├── search/                      # 搜索子系统
│   ├── adapters/                # 7 个搜索引擎适配器
│   │   ├── ddg.py               # DuckDuckGo
│   │   ├── hkex.py              # 港交所
│   │   ├── rss.py               # RSS/Atom
│   │   ├── searxng.py           # SearXNG
│   │   ├── sec.py               # SEC EDGAR
│   │   ├── tavily.py            # Tavily
│   │   └── yahoo.py             # Yahoo Finance
│   └── models/                  # 搜索数据模型
│       ├── evidence.py          # 证据评级
│       ├── provider_result.py   # 搜索结果
│       ├── query_plan.py        # 查询计划
│       └── search_hit.py        # 搜索命中
├── memory/                      # 分层记忆系统
│   ├── memoryAge.py             # 记忆老化策略
│   ├── memory_bridge.py         # 记忆桥接
│   ├── hot/                     # 热记忆（当前任务）
│   ├── warm/                    # 温记忆（用户偏好）
│   └── topics/                  # 主题记忆（知识库）
├── rules/                       # 执行协议
│   └── ir-pipeline.md           # IR 管线 Zero Human Intervention 协议
├── research/                    # 研究子系统
├── content/                     # 内容抓取（Scrapling 三层递进）
├── config/                      # 配置文件
├── docs/                        # 文档
├── setup.sh                     # 🚀 一键安装脚本
├── .env.example                 # 环境变量模板
├── requirements.txt             # Python 依赖
└── README.md
```

## 🚀 一键安装

```bash
# 一行命令安装
curl -fsSL https://raw.githubusercontent.com/Xavier-06/ir-bp-workflow/main/setup.sh | bash

# 或手动安装
git clone https://github.com/Xavier-06/ir-bp-workflow.git ~/.workbuddy/ir_runtime
cd ~/.workbuddy/ir_runtime && bash setup.sh
```

安装脚本自动完成：克隆仓库 → 安装 Python 依赖 → 创建 .env → 安装 4 个 Skills → 创建运行时目录 → 验证管线编排器

### 前置条件

| 依赖 | 版本 | 用途 | 必需？ |
|------|------|------|--------|
| Python | 3.10+ | 管线运行 | ✅ 必需 |
| WorkBuddy / OpenClaw | 最新版 | AI Agent 平台 | ✅ 必需 |
| DuckDuckGo Search | `pip install duckduckgo-search` | 搜索引擎 | ✅ 必需 |
| yfinance | `pip install yfinance` | 金融数据 | ✅ 必需 |
| SearXNG | Docker 镜像 | 本地搜索引擎 | ⚡ 推荐 |
| HTTP 代理 | Clash/V2Ray 等 | Google/Scrapling 翻墙 | ⚡ 按需 |
| NeoData | WorkBuddy 内置 | A/HK 股金融数据 | ⚡ 推荐 |
| VL 视觉模型 | qwen3-vl 等 | BP OCR | ⚡ BP 管线需 |
| 企查查 MCP | WorkBuddy 内置 | BP 工商验证/竞争分析/知识产权 | ⚡ BP 管线需 |

### MCP 工具依赖

BP 管线的 Phase 0.5 工商验证和维度分析大量依赖企查查 MCP（WorkBuddy 内置），需要在 WorkBuddy 设置中连接 `qcc-company` 服务：

| MCP 工具 | 能力 | 管线用途 |
|---------|------|---------|
| `mcp__qcc-company` | 工商信息（股东、注册资本、法人、变更记录、分支机构、对外投资） | Phase 0.5 验证、竞争分析、产业链分析 |
| `mcp__qcc-risk` | 风险信息（诉讼、失信被执行人、行政处罚、经营异常） | 团队合规维度 |
| `mcp__qcc-ipr` | 知识产权（专利、商标、著作权） | 团队合规维度 |
| `mcp__qcc-operation` | 经营信息（招投标、资质许可、年报） | 竞争分析、行业供应链、估值 |

> **注意**：企查查 MCP 仅用于 BP 管线。IR 管线通过搜索网关获取工商数据，不依赖 MCP。

### 网络配置说明

**搜索网关采用 6 层降级链**，即使没有代理也能用，但部分层需要特定网络条件：

| 层 | 搜索引擎 | 需要代理？ | 说明 |
|----|---------|-----------|------|
| Layer 0 | NeoData | ❌ | 腾讯内网，WorkBuddy 自动鉴权 |
| Layer 1 | DuckDuckGo | ❌ | 直接搜索，无需翻墙 |
| Layer 2 | SearXNG | ❌ | 本地 Docker 实例 |
| Layer 3 | Google | ✅ | 需要代理 (`PROXY_URL`) |
| Layer 4 | Scrapling | ✅ | StealthyFetcher 走代理 |
| Layer 5 | yfinance | ❌ | Yahoo Finance API |

**配置代理**（仅 Google/Scrapling 层需要）：
```bash
# 在 .env 中设置
PROXY_URL=你的代理端口
```

**配置 SearXNG**（推荐，提升搜索质量）：
```bash
docker run -d -p 你的端口 --name searxng searxng/searxng:latest
```

**配置 NeoData**（推荐，A/HK 股首选数据源）：
- 通过 WorkBuddy 的 `neodata-financial-search` skill 自动获取 token
- 搜索网关会自动将金融类查询路由到 NeoData Layer 0

## 📋 使用方式

### IR 管线：股票研报

对话触发（推荐）：
- "分析比亚迪"
- "跑个研报看看腾讯"
- "对优必选做个尽调"

ir-coordinator 自动识别意图并启动 IR 管线。

### BP 管线：商业计划书尽调

对话触发（推荐）：
- "帮我看下这个 BP" + 上传文件
- "分析一下 XX 公司的商业计划书"

## 🧠 核心设计

### 长链推理：8 步 IR 研报

4 个 wave、8 个 step 的渐进式推理链，每个 step 依赖前序输出：

| Wave | Steps | 推理深度 |
|------|-------|---------|
| Wave 1 | step1_data | 基础数据（估值/财务/市场）+ **融资状态验证** |
| Wave 2 | step2+3+4+5 | 并行深度分析（行业/商业/财务/管理层）+ **人员/竞品真实性验证** |
| Wave 3 | step6+6b+7 | 高阶推理（差异化洞察/**预测与估值**/风险催化）+ **可比公司状态验证** |
| Wave 4 | step8_master | 综合统稿（基于前 7 步完整输出）+ **跨 step 一致性检查** |

### ANTI-DEFECT RULES：反幻觉验证体系

每个 step/维度内置专属验证规则，从根源防止 AI 幻觉：

| 规则 | 适用步骤 | 防御目标 |
|------|---------|---------|
| 融资状态验证 | step1, BP 竞争 | 防止引用已 IPO 公司的过时融资数据 |
| 人员存在性验证 | step5, BP 团队 | 防止编造不存在的高管/董事姓名 |
| 数据时效性检查 | step4, step6b | 确保财务/估值数据在 6 个月内 |
| 可比公司状态验证 | step6b, BP 估值 | 确认 comps 表中公司仍在经营/已上市 |
| 政策时效性验证 | step7, BP 行业 | 确认引用的政策仍然有效 |
| 竞品运营状态 | step3, BP 技术 | 确认竞品未被收购/重组/转型 |
| 审计意见检查 | step4 | 关注审计意见变更（无保留→保留 = 红旗） |
| 跨 step 一致性 | step8 | 同一实体在不同 step 中的状态描述一致 |

### 搜索系统：6 层降级链 + NeoData

```
Layer 0: NeoData 金融数据（A/HK股行情、财报、板块、研报）
Layer 1: DuckDuckGo（通用搜索）
Layer 2: SearXNG 本地实例（Baidu + Bing 补充）
Layer 3: Google 直接抓取（走代理，自己解析）
Layer 4: Scrapling StealthyFetcher（深度正文提取）
Layer 5: yfinance 估值数据（IR 管线专用）
```

- **金融查询自动路由**：搜索网关自动检测金融类查询（股价/财报/估值/PE 等），优先走 NeoData
- **数据源优先级**：A/HK 股 → NeoData → yfinance(交叉验证) → web_search；美股 → yfinance → web_search
- 7 个适配器（NeoData/DDG/SearXNG/SEC/HKEX/Yahoo/RSS），支持实体解析、查询计划、证据评级

### 多 Agent 协作：4 角色分工

| Agent | 职责 | 触发方式 |
|-------|------|---------|
| **ir-coordinator** | 调度中心，编排全自动执行 | 用户对话直接触发 |
| **ir-researcher** | 单维度数据采集，自主补搜闭环 | coordinator 内部调度 |
| **ir-reporter** | 统稿 + DOCX + 对抗验证 + 交付 | coordinator 内部调度 |
| **ir-verifier** | 6 层对抗验证（L1-L5 脚本 + L6 人工论证） | coordinator 内部调度 |

### 质量门禁

- Step1 完整性 <50% → 熔断
- 跨 Step 一致性 FAIL → 必须修正
- **ANTI-DEFECT RULES** → 每个 step 输出前必须完成验证
- 完成率 <50% → 阻断交付
- 对抗验证 L6 → 主动找证据推翻结论

### 全自动交付

```
finalize_pipeline() → 对抗验证 → DOCX 生成 → 桌面复制 → 微信通知
```

## 🎯 设计理念

1. **Phase 驱动** — 管线由 Phase 序列组成，可独立运行/暂停/恢复
2. **Profile 模式** — IR/BP 共享编排内核，Profile 定义差异
3. **子代理自主闭环** — 数据缺口时自主补搜，不回主控等待
4. **搜索可插拔** — 网关抽象层 + NeoData Layer 0，支持多种搜索引擎/插件
5. **断点续跑** — 中断后从任意 Phase 恢复
6. **交付清洗** — 报告绝不暴露内部路径/Task ID
7. **Zero Human Intervention** — 全自动推进，无需发"继续"
8. **ANTI-DEFECT** — 每个 step 都有反幻觉规则，搜索验证而非信任模型记忆

## 📊 项目数据

- **160+ 个 Python 脚本**，**~28,000 行代码**
- **已分析标的**：AVGO、泡泡玛特、优必选、东江环保、佰维存储、阅文集团、中芯国际、及部分融资项目等
- **交付物**：券商级 DOCX 研报（执行摘要 + 估值分析 + 风险矩阵 + 免责声明）+ 估值 Excel
- **自动化率**：Phase 0-5 全自动，Zero Human Intervention

## 📄 License

MIT License

---

*Built with 🐲 for the AI agent community*
