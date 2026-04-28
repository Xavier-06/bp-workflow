"""
配置文件 - 在这里填入你的百炼 API Key 和模型偏好
"""
import os
import pathlib

# ============================================================
#  百炼 DashScope API 配置
# ============================================================
# Auto-load DashScope API key from workspace credentials
_workspace_root = pathlib.Path(__file__).resolve().parent.parent
_creds_file = _workspace_root / ".credentials" / "investment-research.env"
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
if not DASHSCOPE_API_KEY and _creds_file.exists():
    for _line in open(_creds_file, encoding="utf-8"):
        _line = _line.strip()
        if _line.startswith("DASHSCOPE_API_KEY=") and not _line.startswith("DASHSCOPE_API_KEY_PENDING"):
            DASHSCOPE_API_KEY = _line.split("=", 1)[1]
            break
    del _line, _creds_file, _workspace_root

# LLM 模型（对话用）
LLM_MODEL = "qwen-max"  # 可选：qwen-max, qwen-plus, qwen-turbo

# Embedding 模型（向量化用）
EMBEDDING_MODEL = "text-embedding-v2"

# ============================================================
#  记忆系统配置
# ============================================================

# 向量库路径（ChromaDB 本地持久化）
CHROMA_DB_PATH = os.path.join(os.path.dirname(__file__), "memory_db")

# 每次对话注入多少条相关记忆
MEMORY_TOP_K = 5

# 记忆相关性阈值（0~1，越高越严格，低于此分数的记忆不注入）
MEMORY_RELEVANCE_THRESHOLD = 0.3

# ============================================================
#  指令库配置
# ============================================================

# 指令文件路径
INSTRUCTIONS_PATH = os.path.join(os.path.dirname(__file__), "instructions", "instructions.json")

# ============================================================
#  工作日志配置
# ============================================================

# 日志存储目录
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")

# ============================================================
#  基础人设 Prompt（投研小组主管）
# ============================================================

BASE_SYSTEM_PROMPT = """你是一位资深投研小组主管，负责协调和管理多个行业研究智能体。

你的核心职责：
1. 根据用户需求，调度合适的行业研究智能体执行分析任务
2. 综合多个行业的研究结论，给出全局性投资建议
3. 管理研究进度，确保报告质量和时效性
4. 记住用户的研究偏好、历史决策和反馈，持续优化服务

你的工作风格：
- 专业严谨，数据驱动
- 善于发现行业间的关联和交叉机会
- 主动提醒风险，不盲目乐观
- 根据用户的投资风格调整建议的激进程度
"""
