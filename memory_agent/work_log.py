"""
工作日志模块 - 按日期自动归档 Markdown 日志
记录：每日对话摘要、研究进度、待办事项
"""
import os
from datetime import datetime, date

import config


class WorkLog:
    """工作日志管理器"""

    def __init__(self):
        self.logs_dir = config.LOGS_DIR
        os.makedirs(self.logs_dir, exist_ok=True)

        # 活跃上下文文件
        self.active_context_path = os.path.join(self.logs_dir, "ACTIVE_CONTEXT.md")
        self.todo_path = os.path.join(self.logs_dir, "TODO.md")

    # ----------------------------------------------------------
    #  每日日志
    # ----------------------------------------------------------
    def _daily_log_path(self, dt: date = None) -> str:
        if dt is None:
            dt = date.today()
        return os.path.join(self.logs_dir, f"{dt.isoformat()}.md")

    def append_daily_log(self, content: str, section: str = "对话记录"):
        """追加一条记录到今日日志"""
        path = self._daily_log_path()
        now = datetime.now().strftime("%H:%M:%S")

        # 如果文件不存在，先写标题
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# 工作日志 - {date.today().isoformat()}\n\n")

        with open(path, "a", encoding="utf-8") as f:
            f.write(f"## [{now}] {section}\n\n{content}\n\n---\n\n")

    def get_daily_log(self, dt: date = None) -> str:
        """读取某日的日志"""
        path = self._daily_log_path(dt)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    # ----------------------------------------------------------
    #  活跃上下文 (ACTIVE_CONTEXT.md)
    # ----------------------------------------------------------
    def update_active_context(self, content: str):
        """更新当前研究上下文（覆盖写入）"""
        with open(self.active_context_path, "w", encoding="utf-8") as f:
            f.write(f"# 当前活跃上下文\n\n")
            f.write(f"*最后更新：{datetime.now().isoformat()}*\n\n")
            f.write(content)

    def get_active_context(self) -> str:
        """读取当前活跃上下文"""
        if os.path.exists(self.active_context_path):
            with open(self.active_context_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    # ----------------------------------------------------------
    #  待办事项 (TODO.md)
    # ----------------------------------------------------------
    def get_todos(self) -> str:
        if os.path.exists(self.todo_path):
            with open(self.todo_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def update_todos(self, content: str):
        with open(self.todo_path, "w", encoding="utf-8") as f:
            f.write(f"# 待办事项\n\n")
            f.write(f"*最后更新：{datetime.now().isoformat()}*\n\n")
            f.write(content)

    def add_todo(self, item: str, priority: str = "普通"):
        """追加一条待办"""
        with open(self.todo_path, "a", encoding="utf-8") as f:
            f.write(f"- [ ] **[{priority}]** {item}  *(添加于 {datetime.now().strftime('%m-%d %H:%M')})*\n")
