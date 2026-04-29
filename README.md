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

## ❓ 解决什么问题

### 痛点一：AI 投研"浅尝辄止"
市面 AI 研报工具只能生成"资料汇编"——堆砌公开信息，缺乏投研逻辑深度。真正的券商研报需要 8 个维度的系统性分析（数据/行业/商业/财务/管理层/洞察/风险/统稿），单轮对话无法完成。

### 痛点二：多 Agent 协作"各自为政"
现有 Agent 框架（AutoGPT、CrewAI）的痛点：子 Agent 挂掉（code=10003）、上下文断裂、数据口径不一致、最终需要人工拼接。我们构建了**有状态编排器**——统一状态协调、manifest 派发、自动重试、断点续跑。

### 痛点三：BP 尽调"信息黑洞"
早期项目的 BP 尽调面临两难：创始人自说自话（信息偏差）vs 昂贵的人工尽调（成本高、周期长）。本管线自动化完成 **VL OCR → 结构化抽取 → 4 维度并行分析 → 竞争格局 → 统稿 → DOCX 交付**，30 分钟内完成全链路。

### 痛点四：交付链路断裂
研报写完了，但复制到桌面、转 DOCX、发微信通知——这些"最后一公里"经常被模型遗忘。管线有**强制 finalize 步骤**：对抗验证 → DOCX 生成 → 桌面复制 → 微信推送（三步协议），报告不会丢。

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
│   ├── search_gateway.py        # 搜索网关
│   ├── longshao_notify.py       # 微信通知
│   └── ...
├── instruction_store_ir/        # IR 角色指令库（8步）
├── instruction_store_bp/        # BP 角色指令库（6维度）
├── skills/                      # AI Agent Skill 定义
│   ├── ir-coordinator/SKILL.md  # 🧠 调度中心
│   ├── ir-researcher/SKILL.md   # 🔍 数据采集 Agent
│   ├── ir-reporter/SKILL.md     # 📝 统稿 Agent
│   └── ir-verifier/SKILL.md     # 🛡️ 对抗验证 Agent
├── search/                      # 搜索子系统（7个适配器）
├── research/                    # 研究子系统
├── content/                     # 内容抓取（Scrapling 三层递进）
├── memory/                      # 分层记忆（hot/warm/topics）
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

- Python 3.10+
- WorkBuddy 或 OpenClaw 平台
- 可选：兼容 OpenAI API 的视觉模型（BP OCR 用）

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
| Wave 1 | step1_data | 基础数据（估值/财务/市场） |
| Wave 2 | step2+3+4+5 | 并行深度分析（行业/商业/财务/管理层） |
| Wave 3 | step6+7 | 高阶推理（差异化洞察/风险催化） |
| Wave 4 | step8_master | 综合统稿（基于前 7 步完整输出） |

### 多 Agent 协作：4 角色分工

| Agent | 职责 | 触发方式 |
|-------|------|---------|
| **ir-coordinator** | 调度中心，编排全自动执行 | 用户对话直接触发 |
| **ir-researcher** | 单维度数据采集，自主补搜闭环 | coordinator 内部调度 |
| **ir-reporter** | 统稿 + DOCX + 对抗验证 + 交付 | coordinator 内部调度 |
| **ir-verifier** | 6 层对抗验证（L1-L5 脚本 + L6 人工论证） | coordinator 内部调度 |

### 搜索系统：三层降级链

```
SearXNG (8888) → DuckDuckGo → Scrapling StealthyFetcher → requests + BeautifulSoup
```

7 个适配器（SearXNG/DDG/SEC/HKEX/Yahoo/Tavily/RSS），支持实体解析、查询计划、证据评级。

### 质量门禁

- Step1 完整性 <50% → 熔断
- 跨 Step 一致性 FAIL → 必须修正
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
4. **搜索可插拔** — 网关抽象层，支持多种搜索引擎/插件
5. **断点续跑** — 中断后从任意 Phase 恢复
6. **交付清洗** — 报告绝不暴露内部路径/Task ID
7. **Zero Human Intervention** — 全自动推进，无需发"继续"

## 📊 项目数据

- **~200 个 Python 文件**，**~25,000 行代码**
- **已分析标的**：AVGO、泡泡玛特、优必选、东江环保、合肥艾创微等
- **交付物**：券商级 DOCX 研报（执行摘要 + 估值分析 + 风险矩阵 + 免责声明）
- **自动化率**：Phase 0-5 全自动

## 📄 License

MIT License

---

*Built with 🐲 for the AI agent community*
