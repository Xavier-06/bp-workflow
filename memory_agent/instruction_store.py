"""
指令库模块 - 管理 15+ 行业智能体的完整指令
采用 JSON 文件存储，按 行业：角色 做 key，全文调取（不走向量检索）
"""
import json
import os
from typing import Optional

import config


# 默认指令模板（首次运行时自动生成示例）
DEFAULT_INSTRUCTIONS = {
    "医药_行业分析师": {
        "name": "医药行业分析师",
        "industry": "医药",
        "role": "行业分析师",
        "description": "负责医药行业深度研究",
        "instruction": "你是一位专业的医药行业分析师...(在此粘贴完整指令，支持几千字)",
        "keywords": ["医药", "创新药", "仿制药", "CXO", "医疗器械", "生物制药", "临床试验"],
    },
    "半导体_行业分析师": {
        "name": "半导体行业分析师",
        "industry": "半导体",
        "role": "行业分析师",
        "description": "负责半导体产业链研究",
        "instruction": "你是一位专业的半导体行业分析师...(在此粘贴完整指令)",
        "keywords": ["半导体", "芯片", "晶圆", "封测", "EDA", "光刻", "AI 芯片"],
    },
    "新能源_行业分析师": {
        "name": "新能源行业分析师",
        "industry": "新能源",
        "role": "行业分析师",
        "description": "负责新能源产业链研究",
        "instruction": "你是一位专业的新能源行业分析师...(在此粘贴完整指令)",
        "keywords": ["新能源", "光伏", "锂电", "储能", "风电", "氢能", "电动车"],
    },
    "宏观_策略分析师": {
        "name": "宏观策略分析师",
        "industry": "宏观",
        "role": "策略分析师",
        "description": "负责宏观经济与市场策略",
        "instruction": "你是一位专业的宏观策略分析师...(在此粘贴完整指令)",
        "keywords": ["宏观", "GDP", "货币政策", "利率", "通胀", "PMI", "美联储"],
    },
}


class InstructionStore:
    """智能体指令库：按行业/角色管理完整指令"""

    def __init__(self):
        self.filepath = config.INSTRUCTIONS_PATH
        self._instructions: dict = {}
        self._load()

    # ----------------------------------------------------------
    #  加载 / 保存
    # ----------------------------------------------------------
    def _load(self):
        """从 JSON 文件加载指令库"""
        if os.path.exists(self.filepath):
            with open(self.filepath, "r", encoding="utf-8") as f:
                self._instructions = json.load(f)
        else:
            # 首次运行，生成示例指令
            self._instructions = DEFAULT_INSTRUCTIONS
            self._save()
            print(f"[指令库] 已生成示例指令文件：{self.filepath}")
            print(f"[指令库] 请编辑该文件，填入你的完整智能体指令")

    def _save(self):
        """保存到 JSON 文件"""
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._instructions, f, ensure_ascii=False, indent=2)

    # ----------------------------------------------------------
    #  查询指令
    # ----------------------------------------------------------
    def get_instruction(self, key: str) -> Optional[dict]:
        """
        按 key 精确获取指令（如 '医药_行业分析师'）
        返回完整指令字典，包含 instruction 全文
        """
        return self._instructions.get(key)

    def get_instruction_text(self, key: str) -> str:
        """只返回指令正文"""
        inst = self._instructions.get(key)
        if inst:
            return inst.get("instruction", "")
        return ""

    def match_by_keywords(self, query: str) -> list[dict]:
        """
        根据用户输入的关键词，模糊匹配相关的智能体指令
        返回匹配到的指令列表（按匹配度排序）
        """
        matches = []
        query_lower = query.lower()

        for key, inst in self._instructions.items():
            score = 0
            # 检查 keywords 匹配
            for kw in inst.get("keywords", []):
                if kw.lower() in query_lower:
                    score += 2
            # 检查行业名匹配
            if inst.get("industry", "").lower() in query_lower:
                score += 3
            # 检查角色名匹配
            if inst.get("role", "").lower() in query_lower:
                score += 1

            if score > 0:
                matches.append({
                    "key": key,
                    "score": score,
                    **inst,
                })

        matches.sort(key=lambda x: x["score"], reverse=True)
        return matches

    # ----------------------------------------------------------
    #  管理功能
    # ----------------------------------------------------------
    def add_instruction(
        self,
        key: str,
        name: str,
        industry: str,
        role: str,
        instruction: str,
        description: str = "",
        keywords: list[str] = None,
    ):
        """添加或更新一条智能体指令"""
        self._instructions[key] = {
            "name": name,
            "industry": industry,
            "role": role,
            "description": description,
            "instruction": instruction,
            "keywords": keywords or [],
        }
        self._save()

    def remove_instruction(self, key: str) -> bool:
        """删除一条指令"""
        if key in self._instructions:
            del self._instructions[key]
            self._save()
            return True
        return False

    def list_all(self) -> list[dict]:
        """列出所有指令摘要（不含 instruction 全文，避免刷屏）"""
        result = []
        for key, inst in self._instructions.items():
            result.append({
                "key": key,
                "name": inst.get("name", key),
                "industry": inst.get("industry", ""),
                "role": inst.get("role", ""),
                "description": inst.get("description", ""),
                "keywords": inst.get("keywords", []),
                "instruction_length": len(inst.get("instruction", "")),
            })
        return result

    def export_for_prompt(self, keys: list[str]) -> str:
        """
        将多个指令拼接为可注入 prompt 的格式
        用于同时调度多个智能体
        """
        parts = []
        for key in keys:
            inst = self._instructions.get(key)
            if inst:
                parts.append(
                    f"=== 智能体：{inst['name']} ({inst['industry']}) ===\n"
                    f"{inst['instruction']}\n"
                )
        return "\n".join(parts)
