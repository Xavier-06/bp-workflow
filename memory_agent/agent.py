"""
核心 Agent 模块 - 串联记忆系统、指令库和 LLM 对话
"""
import json
from typing import Optional, Generator

import dashscope
from dashscope import Generation

import config
from memory_store import MemoryStore
from instruction_store import InstructionStore
from work_log import WorkLog


class Agent:
    """投研主管 Agent - 带记忆系统的对话核心"""

    def __init__(self):
        dashscope.api_key = config.DASHSCOPE_API_KEY

        # 初始化各模块
        self.memory = MemoryStore()
        self.instructions = InstructionStore()
        self.work_log = WorkLog()

        # 当前对话历史
        self.conversation_history = []

    # ----------------------------------------------------------
    #  System Prompt 动态拼装
    # ----------------------------------------------------------
    def _build_system_prompt(self, user_input: str) -> str:
        """根据当前话题，动态拼装 system prompt"""

        # 1. 基础人设
        parts = [config.BASE_SYSTEM_PROMPT]

        # 2. 检索相关记忆
        memories = self.memory.search(user_input, top_k=config.MEMORY_TOP_K)
        if memories:
            parts.append("\n## 相关记忆\n")
            for mem in memories:
                parts.append(f"- [{mem['category']}] {mem['content']} (相关度：{mem['score']})\n")

        # 3. 匹配智能体指令
        matched_agents = self.instructions.match_by_keywords(user_input)
        if matched_agents:
            parts.append("\n## 可用智能体指令\n")
            for agent in matched_agents[:3]:  # 最多注入 3 个
                parts.append(f"\n=== {agent['name']} ===\n{agent['instruction']}\n")

        # 4. 活跃上下文
        context = self.work_log.get_active_context()
        if context:
            parts.append(f"\n## 当前研究上下文\n{context}\n")

        # 5. 待办事项
        todos = self.work_log.get_todos()
        if todos:
            parts.append(f"\n## 待办事项\n{todos}\n")

        return "\n".join(parts)

    # ----------------------------------------------------------
    #  对话核心
    # ----------------------------------------------------------
    def chat(self, user_input: str, stream: bool = True) -> Generator[str, None, None]:
        """
        与用户对话，流式返回
        """
        # 添加到对话历史
        self.conversation_history.append({"role": "user", "content": user_input})

        # 构建 system prompt
        system_prompt = self._build_system_prompt(user_input)

        # 调用百炼 API
        messages = [
            {"role": "system", "content": system_prompt},
            *self.conversation_history,
        ]

        if stream:
            response = Generation.call(
                model=config.LLM_MODEL,
                messages=messages,
                stream=True,
                incremental_output=True,
            )
            full_response = ""
            for chunk in response:
                if chunk.status_code == 200:
                    content = chunk.output.choices[0].message.content
                    yield content
                    full_response += content
                else:
                    yield f"\n[API 错误：{chunk.code} - {chunk.message}]"
                    break

            # 保存助手回复到历史
            self.conversation_history.append({"role": "assistant", "content": full_response})

            # 记录到工作日志
            self.work_log.append_daily_log(
                f"用户：{user_input}\n\n助手：{full_response[:500]}...",
                section="对话记录",
            )
        else:
            response = Generation.call(
                model=config.LLM_MODEL,
                messages=messages,
            )
            if response.status_code == 200:
                content = response.output.choices[0].message.content
                self.conversation_history.append({"role": "assistant", "content": content})
                yield content
            else:
                yield f"[API 错误：{response.code} - {response.message}]"

    # ----------------------------------------------------------
    #  记忆提取
    # ----------------------------------------------------------
    def extract_and_save_memories(self) -> dict:
        """
        分析本轮对话，提取关键信息存入记忆库
        返回：{"status": "success/skipped/error", "memories_saved": int, ...}
        """
        if len(self.conversation_history) < 2:
            return {"status": "skipped", "reason": "对话历史太短，无需提取记忆"}

        # 拼接本轮对话
        conversation_text = "\n".join(
            [f"{msg['role']}: {msg['content']}" for msg in self.conversation_history]
        )

        # 调用 LLM 分析需要记忆的内容
        analysis_prompt = f"""
请分析以下对话，提取需要长期记忆的关键信息。

对话内容：
{conversation_text}

请按以下 JSON 格式输出（如果没有某类记忆，该字段为空数组）：
{{
    "preferences": ["用户偏好 1", "用户偏好 2"],
    "errors": ["需要注意的教训 1"],
    "data_points": ["关键数据/事实 1"],
    "summary": "本轮对话的简短摘要（100 字以内）",
    "todos": ["新增待办 1", "新增待办 2"]
}}

只输出 JSON，不要其他内容。
"""

        try:
            response = Generation.call(
                model=config.LLM_MODEL,
                messages=[{"role": "user", "content": analysis_prompt}],
            )

            if response.status_code != 200:
                return {"status": "error", "reason": f"LLM 调用失败：{response.code}"}

            result = json.loads(response.output.choices[0].message.content)

            # 保存记忆
            memories_saved = 0

            for pref in result.get("preferences", []):
                self.memory.add_memory(pref, category="user_preferences")
                memories_saved += 1

            for err in result.get("errors", []):
                self.memory.add_memory(err, category="past_errors")
                memories_saved += 1

            for data in result.get("data_points", []):
                self.memory.add_memory(data, category="key_data")
                memories_saved += 1

            summary = result.get("summary", "")
            if summary:
                self.memory.add_memory(summary, category="conversations")
                memories_saved += 1

            # 更新待办
            todos_added = 0
            for todo in result.get("todos", []):
                self.work_log.add_todo(todo)
                todos_added += 1

            # 更新活跃上下文
            if summary:
                self.work_log.update_active_context(
                    f"最近讨论：{summary}\n时间：{len(self.conversation_history)} 轮对话"
                )

            return {
                "status": "success",
                "memories_saved": memories_saved,
                "context_updated": bool(summary),
                "todos_added": todos_added,
            }

        except json.JSONDecodeError as e:
            return {"status": "error", "reason": f"JSON 解析失败：{e}"}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    # ----------------------------------------------------------
    #  管理功能
    # ----------------------------------------------------------
    def get_memory_stats(self) -> dict:
        """返回记忆库统计"""
        return self.memory.get_stats()

    def reset_conversation(self):
        """清除当前对话历史（不清记忆库）"""
        self.conversation_history = []
