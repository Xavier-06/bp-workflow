#!/usr/bin/env python3
"""
Task Registry — 基于文件系统的任务生命周期管理

借鉴 Claude Code utils/tasks.ts 设计：
- 每个任务是磁盘上一个 JSON 文件
- 递增整数 ID（高水位线机制，永不重复）
- file lock 防并发冲突
- blocked_by 依赖关系
- 子代理关联

用法：
    from scripts.task_registry import TaskRegistry, TaskStatus, Task

    tasks = TaskRegistry()
    t = tasks.create("PDF 入库", phase="phase0", blocked_by=[])
    tasks.update(t.id, status=TaskStatus.IN_PROGRESS)
    tasks.update(t.id, status=TaskStatus.COMPLETED)
    ready = tasks.get_ready_tasks()  # 阻塞已解除的 task
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / "tasks" / "task_registry"

HIGH_WATER_MARK = ".highwatermark"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass
class Task:
    id: int
    subject: str
    description: str = ""
    active_form: str = ""
    status: TaskStatus = TaskStatus.PENDING
    pipeline: str = ""
    phase: str = ""
    parent_id: Optional[int] = None
    blocked_by: list[int] = field(default_factory=list)
    subagent_key: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = d["status"] if isinstance(d["status"], str) else d["status"].value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        field_names = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in field_names}
        s = filtered.pop("status", "pending")
        if isinstance(s, str):
            filtered["status"] = TaskStatus(s)
        return cls(**filtered)


def _lock(fd):
    fcntl.flock(fd, fcntl.LOCK_EX)

def _unlock(fd):
    fcntl.flock(fd, fcntl.LOCK_UN)


class TaskRegistry:
    """任务注册表。每个任务 = 一个 JSON 文件 + 高水位线文件。"""

    def __init__(self, task_dir: Optional[Path] = None):
        self._dir = task_dir or TASKS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._mark_path = self._dir / HIGH_WATER_MARK

    # ── 高水位线 ─────────────────────────────────────────
    def _read_hwm(self) -> int:
        try:
            return int(self._mark_path.read_text().strip())
        except (OSError, ValueError):
            return 0

    def _write_hwm(self, val: int):
        self._mark_path.write_text(str(val))

    def _next_id(self) -> int:
        """在持有文件锁时调用，返回并递增 ID。"""
        lock_path = self._dir / ".tasks.lock"
        lock_path.touch()
        with open(lock_path, "w") as f:
            _lock(f)
            try:
                hwm = self._read_hwm()
                new_id = hwm + 1
                self._write_hwm(new_id)
                return new_id
            finally:
                _unlock(f)

    def reset_hwm(self):
        """重置高水位线（清理管线时调用）。"""
        self._write_hwm(0)

    # ── 文件 I/O ──────────────────────────────────────────
    def _task_path(self, task_id: int) -> Path:
        safe = f"task_{task_id}"
        return self._dir / f"{safe}.json"

    def _read_task(self, task_id: int) -> Optional[Task]:
        p = self._task_path(task_id)
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text())
            return Task.from_dict(d)
        except Exception:
            return None

    def _write_task(self, task: Task):
        p = self._task_path(task.id)
        p.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2) + "\n")

    # ── CRUD ──────────────────────────────────────────────
    def create(self, subject: str, description: str = "",
               active_form: str = "", phase: str = "",
               pipeline: str = "", blocked_by: Optional[list[int]] = None,
               parent_id: Optional[int] = None,
               subagent_key: Optional[str] = None,
               metadata: Optional[dict] = None) -> Task:
        tid = self._next_id()
        task = Task(
            id=tid,
            subject=subject,
            description=description,
            active_form=active_form or subject,
            phase=phase,
            pipeline=pipeline,
            blocked_by=blocked_by or [],
            parent_id=parent_id,
            subagent_key=subagent_key,
            metadata=metadata or {},
        )
        self._write_task(task)
        return task

    def get(self, task_id: int) -> Optional[Task]:
        return self._read_task(task_id)

    def update(self, task_id: int, **kwargs) -> Optional[Task]:
        task = self._read_task(task_id)
        if task is None:
            return None
        for k, v in kwargs.items():
            if hasattr(task, k):
                if k == "status":
                    if isinstance(v, str):
                        v = TaskStatus(v)
                    now = time.time()
                    if v == TaskStatus.IN_PROGRESS and task.status != TaskStatus.IN_PROGRESS:
                        task.started_at = now
                    elif v in (TaskStatus.COMPLETED, TaskStatus.FAILED) and task.status != v:
                        task.completed_at = now
                setattr(task, k, v)
        if "error" in kwargs:
            task.status = TaskStatus.FAILED
            task.completed_at = task.completed_at or time.time()
        self._write_task(task)
        return task

    def list_all(self, pipeline: Optional[str] = None) -> list[Task]:
        tasks = []
        for p in self._dir.glob("task_*.json"):
            try:
                d = json.loads(p.read_text())
                t = Task.from_dict(d)
                if pipeline is None or t.pipeline == pipeline:
                    tasks.append(t)
            except Exception:
                continue
        return sorted(tasks, key=lambda t: t.id)

    def delete(self, task_id: int) -> bool:
        p = self._task_path(task_id)
        if p.exists():
            p.unlink()
            return True
        return False

    def clear_pipeline(self, pipeline: str):
        """删除某管线的所有任务并重置 HWM。"""
        for t in self.list_all(pipeline):
            self.delete(t.id)
        self._write_hwm(0)

    # ── 阻塞检查 ──────────────────────────────────────────
    def is_blocked(self, task: Task) -> bool:
        if not task.blocked_by:
            return False
        for bid in task.blocked_by:
            parent = self._read_task(bid)
            if parent is None or parent.status not in (TaskStatus.COMPLETED,):
                return True
        return False

    def get_ready_tasks(self, pipeline: Optional[str] = None) -> list[Task]:
        ready = []
        for t in self.list_all(pipeline):
            if t.status == TaskStatus.PENDING:
                if not self.is_blocked(t):
                    ready.append(t)
                else:
                    self.update(t.id, status=TaskStatus.BLOCKED)
            elif t.status == TaskStatus.BLOCKED:
                if not self.is_blocked(t):
                    self.update(t.id, status=TaskStatus.PENDING)
                    ready.append(t)
        return ready

    def pipeline_status(self, pipeline: str) -> dict:
        """管线整体状态摘要。"""
        tasks = self.list_all(pipeline)
        if not tasks:
            return {"pipeline": pipeline, "total": 0, "state": "empty"}

        counts = {}
        for t in tasks:
            s = t.status.value if isinstance(t.status, TaskStatus) else str(t.status)
            counts[s] = counts.get(s, 0) + 1

        done = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        total = len(tasks)

        if failed > 0:
            state = "failed"
        elif done == total:
            state = "completed"
        else:
            state = "in_progress"

        return {
            "pipeline": pipeline,
            "state": state,
            "total": total,
            "completed": done,
            "failed": failed,
            "in_progress": counts.get("in_progress", 0),
            "pending": counts.get("pending", 0),
            "blocked": counts.get("blocked", 0),
            "tasks": [
                {"id": t.id, "subject": t.subject, "phase": t.phase,
                 "status": t.status.value if isinstance(t.status, TaskStatus) else str(t.status)}
                for t in tasks
            ],
        }

    # ── 文本树（简洁：按 ID 顺序，显示依赖） ─────────
    def print_tree(self, pipeline: Optional[str] = None):
        tasks = self.list_all(pipeline)
        if not tasks:
            print("(no tasks)")
            return

        for t in tasks:
            marker = {
                TaskStatus.PENDING: "⏳",
                TaskStatus.IN_PROGRESS: "🔄",
                TaskStatus.COMPLETED: "✅",
                TaskStatus.BLOCKED: "🚫",
                TaskStatus.FAILED: "❌",
            }.get(t.status, "?")
            label = f"  {marker} Task {t.id}: {t.subject}"
            if t.subagent_key:
                label += f" [{t.subagent_key}]"
            if t.blocked_by:
                label += f"  ← 阻塞: {t.blocked_by}"
            print(label)


if __name__ == "__main__":
    import sys
    reg = TaskRegistry()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"

    if cmd == "list":
        tasks = reg.list_all()
        if not tasks:
            print("(no tasks)")
        else:
            reg.print_tree()
    elif cmd == "status" and len(sys.argv) > 2:
        tid = int(sys.argv[2])
        t = reg.get(tid)
        if t:
            print(json.dumps(t.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"Task {tid} not found")
    elif cmd == "pipeline" and len(sys.argv) > 2:
        p = sys.argv[2]
        info = reg.pipeline_status(p)
        print(json.dumps(info, ensure_ascii=False, indent=2))
    elif cmd == "tree":
        p = sys.argv[2] if len(sys.argv) > 2 else None
        reg.print_tree(p)
    else:
        print("Usage: python3 task_registry.py [list|status <id>|pipeline <name>|tree [name]]")
