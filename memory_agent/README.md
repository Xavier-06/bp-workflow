# 🧠 投研主管 Agent - 记忆系统

一个带完整记忆能力的投研助手，越用越懂你。

## 系统架构

```
用户对话
  │
  ▼
┌─────────────────────────────────────────┐
│         System Prompt 动态拼装           │
│  ┌───────────┬───────────┬───────────┐  │
│  │ 基础人设   │ 相关记忆   │ 智能体指令 │  │
│  └───────────┴───────────┴───────────┘  │
│  + 活跃上下文 + 待办事项                  │
└─────────────────────────────────────────┘
  │
  ▼
百炼 API (Qwen-max) 流式对话
  │
  ▼
┌─────────────────────────────────────────┐
│         对话后自动记忆提取                 │
│  ┌──────────┐ ┌──────────┐ ┌─────────┐ │
│  │ 向量记忆库│ │ 工作日志  │ │ 待办更新 │ │
│  │ (ChromaDB)│ │ (Markdown)│ │         │ │
│  └──────────┘ └──────────┘ └─────────┘ │
└─────────────────────────────────────────┘
```

## 三层记忆

| 层级 | 存储方式 | 用途 | 检索方式 |
|------|---------|------|---------|
| **向量记忆** | ChromaDB + 百炼 Embedding | 偏好/错误/数据/摘要 | 语义相似度 |
| **指令库** | JSON 文件 | 15+ 行业智能体指令 | 关键词精确匹配 |
| **工作日志** | Markdown 文件 | 每日日志/上下文/待办 | 直接读取 |

## 快速开始

### 1. 安装依赖

```bash
cd memory_agent
pip install -r requirements.txt
```

### 2. 配置 API Key

编辑 `config.py`，填入你的百炼 API Key：

```python
DASHSCOPE_API_KEY = "sk-xxxxxxxxxxxxxxxx"
```

或者用环境变量：

```bash
# Mac/Linux
export DASHSCOPE_API_KEY="sk-xxxxxxxxxxxxxxxx"

# Windows PowerShell
$env:DASHSCOPE_API_KEY="sk-xxxxxxxxxxxxxxxx"
```

### 3. 导入智能体指令

**方式一：批量导入（推荐）**

创建一个文件夹，每个 `.txt` 文件就是一个智能体的完整指令：

```
my_instructions/
├── 医药_行业分析师.txt
├── 半导体_研究员.txt
├── 新能源_行业分析师.txt
├── 消费_行业分析师.txt
├── 金融_银行分析师.txt
└── ...
```

文件内容就是完整指令（几千字都没问题）。如果想加关键词，在第一行写：

```
#keywords: 医药，创新药，CXO，生物制药，临床试验
你是一位专业的医药行业分析师，负责...
（后面是完整指令正文）
```

然后运行导入：

```bash
python import_instructions.py
# 选 2，输入文件夹路径
```

**方式二：直接编辑 JSON**

编辑 `instructions/instructions.json`，格式见文件中的示例。

### 4. 启动

```bash
python main.py
```

## 使用命令

| 命令 | 说明 |
|------|------|
| `/quit` | 退出并自动保存本轮记忆 |
| `/save` | 手动触发记忆提取 |
| `/stats` | 查看记忆库统计 |
| `/agents` | 查看已配置的智能体 |
| `/context` | 查看当前研究上下文 |
| `/todo` | 查看待办事项 |
| `/clear` | 清除本轮对话（保留记忆） |
| `/reset` | 清空全部记忆（慎用） |

## 工作流程示例

```
你：帮我分析一下最近医药板块的投资机会

[系统自动执行]
  → 检索向量库：找到 3 条相关记忆
    - [偏好] 用户偏好创新药赛道，不看仿制药
    - [数据] 上次讨论过恒瑞医药的管线进展
    - [错误] 上次忽略了集采政策影响，被用户纠正
  → 匹配指令：命中"医药_行业分析师"指令
  → 注入活跃上下文 + 待办
  → 拼装完整 system prompt
  → 调用百炼 API

助手：基于你之前的偏好，我重点从创新药赛道分析...
     (结合了记忆中的偏好和历史教训)

你：/quit

[系统自动执行]
  → LLM 分析本轮对话
  → 提取关键信息写入向量库
  → 更新工作日志
  → 保存退出
```

## 文件结构

```
memory_agent/
├── main.py                 # 主入口（CLI 界面）
├── agent.py                # 核心 Agent（串联记忆 + 指令+LLM）
├── memory_store.py         # 向量记忆库（ChromaDB）
├── instruction_store.py    # 智能体指令库（JSON）
├── work_log.py             # 工作日志（Markdown）
├── config.py               # 配置文件
├── import_instructions.py  # 指令批量导入工具
├── requirements.txt        # Python 依赖
├── instructions/           # 指令存储目录
│   └── instructions.json
├── logs/                   # 日志目录
│   ├── ACTIVE_CONTEXT.md
│   ├── TODO.md
│   └── 2025-01-15.md
└── memory_db/              # ChromaDB 向量库（自动生成）
```

## 配置调优

在 `config.py` 中可调整：

- `LLM_MODEL`: 换模型（qwen-max 效果最好，qwen-turbo 最便宜）
- `MEMORY_TOP_K`: 每次注入多少条记忆（默认 5，指令多的话可以减到 3）
- `MEMORY_RELEVANCE_THRESHOLD`: 记忆相关性阈值（默认 0.3，调高则更严格）
- `BASE_SYSTEM_PROMPT`: 基础人设（按你的风格调整）

## 和之前 Mem0 / OpenVIKING 的区别

| 对比项 | Mem0 | 本方案 |
|--------|------|--------|
| 长指令支持 | ❌ 会被切片 | ✅ JSON 全文存储，不走向量 |
| 记忆精度 | 一般 | ✅ 分 4 类独立存储 + 语义检索 |
| 本地部署 | 复杂 | ✅ pip install 即可 |
| 自定义程度 | 低 | ✅ 完全可控 |

## 常见问题

**Q: 之前 Mem0 和 OpenVIKING 配的要删吗？**
A: 不用急着删。这套是独立的，两套并存不冲突。新方案跑通验证后再清理旧的。

**Q: 指令太长会不会超 token 限制？**
A: 百炼 Qwen-max 支持 32K 上下文。如果同时触发 3 个指令 + 5 条记忆 + 上下文，建议单个指令控制在 5000 字以内。超出的话可以在 config.py 把 MEMORY_TOP_K 降到 3。

**Q: 向量库会越来越大吗？**
A: 会，但 ChromaDB 本地存储很高效，几万条记忆也就几十 MB。如果想清理，用 `/reset` 或者直接删除 `memory_db/` 文件夹。
