#!/usr/bin/env python3
"""
TaskRegistry — Claude Code 风格的任务系统
=========================================
设计灵感来源：Claude Code 的 tasks.ts / Task.ts
from __future__ import annotations

核心特性：
1. 文件持久化 — JSON 文件存在磁盘，进程重启不丢
2. 高水位线 — ID 永不重复（即使任务被删）
3. fcntl 文件锁 — 防子代理并发冲突
4. blocked_by 依赖树 — 自动计算阻塞状态
5. activeForm — 给人看的进度文本

CLI 用法：
    python3 scripts/task.py list                          # 列出所有任务
    python3 scripts/task.py status <task_id>              # 查看任务详情
    python3 scripts/task.py tree                          # 打印依赖树
    python3 scripts/task.py create <subject> [--desc TEXT] [--phase P] [--pipeline PL] [--blocked ID,...]
    python3 scripts/task.py update <task_id> [--status S]
    python3 scripts/task.py complete <task_id>
    python3 scripts/task.py fail <task_id> [--error TEXT]
"""

import sys
import os
import json
import fcntl
import time
import argparse
import math
from pathlib import Path
from enum import Enum
from typing import Optional, List, Dict
from datetime import datetime

# ═══════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════
WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / "tasks" / "task_registry"
HIGH_WATERMARK_FILE = TASKS_DIR / ".high_watermark"
LOCK_FILE = TASKS_DIR / ".lock"

TASKS_DIR.mkdir(parents=True, exist_ok=True)


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"

    @property
    def is_terminal(self):
        return self in (TaskStatus.COMPLETED, TaskStatus.FAILED)

    @property
    def is_active(self):
        return self in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)


# ═══════════════════════════════════════════════
# Task 数据模型
# ═══════════════════════════════════════════════
class Task:
    """单个任务（内存表示）"""

    def __init__(self, data: dict):
        self._d = data

    @property
    def id(self) -> int: return self._d.get("id", 0)
    @property
    def subject(self) -> str: return self._d.get("subject", "")
    @property
    def description(self) -> str: return self._d.get("description", "")
    @property
    def active_form(self) -> str: return self._d.get("active_form", self._d.get("subject", ""))
    @property
    def status(self) -> TaskStatus: return TaskStatus(self._d.get("status", "pending"))
    @property
    def pipeline(self) -> str: return self._d.get("pipeline", "")
    @property
    def phase(self) -> str: return self._d.get("phase", "")
    @property
    def parent_id(self) -> Optional[int]: return self._d.get("parent_id")
    @property
    def blocked_by(self) -> List[int]: return list(self._d.get("blocked_by", []))
    @property
    def subagent_id(self) -> Optional[str]: return self._d.get("subagent_id")
    @property
    def created_at(self) -> float: return self._d.get("created_at", 0)
    @property
    def started_at(self) -> Optional[float]: return self._d.get("started_at")
    @property
    def completed_at(self) -> Optional[float]: return self._d.get("completed_at")
    @property
    def error(self) -> Optional[str]: return self._d.get("error")

    def to_dict(self) -> dict:
        return dict(self._d)

    def _status_emoji(self) -> str:
        s = self.status
        if s == TaskStatus.COMPLETED: return "✅"
        if s == TaskStatus.IN_PROGRESS: return "🔄"
        if s == TaskStatus.BLOCKED: return "🔒"
        if s == TaskStatus.FAILED: return "❌"
        return "⏳"

    def __repr__(self):
        return f"Task({self.id}: {self._status_emoji()} {self.subject})"


# ═══════════════════════════════════════════════
# TaskRegistry — 核心
# ═══════════════════════════════════════════════
class TaskRegistry:
    """
    类似 Claude Code 的 TaskRegistry。

    - 每个任务是 tasks/task_registry/<id>.json
    - 高水位线文件保证 ID 永不重复
    - fcntl 锁防并发
    """

    def __init__(self):
        self._ensure_dirs()

    def _ensure_dirs(self):
        TASKS_DIR.mkdir(parents=True, exist_ok=True)

    def _lock(self):
        """获取排他锁，返回锁文件句柄"""
        LOCK_FILE.touch()
        fd = open(LOCK_FILE, 'w')
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _unlock(self, fd):
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()

    def _next_id(self) -> int:
        """从高位水线文件读取下一个可用 ID"""
        if HIGH_WATERMARK_FILE.exists():
            hw = int(HIGH_WATERMARK_FILE.read_text().strip() or "0")
        else:
            hw = 0
        next_id = hw + 1
        HIGH_WATERMARK_FILE.write_text(str(next_id))
        return next_id

    def _task_path(self, task_id: int) -> Path:
        return TASKS_DIR / f"{task_id}.json"

    def _read_task_file(self, path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def _write_task_file(self, task_id: int, data: dict):
        path = self._task_path(task_id)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _compute_blocked_status(self) -> None:
        """遍历所有任务，根据 blocked_by 计算 BLOCKED 状态"""
        completed_ids = set()
        for f in TASKS_DIR.glob("*.json"):
            try:
                d = json.loads(f.read_text())
                if d.get("status") == TaskStatus.COMPLETED:
                    completed_ids.add(d["id"])
            except:
                pass

        for f in TASKS_DIR.glob("*.json"):
            try:
                d = json.loads(f.read_text())
                if d.get("status") in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    continue
                blocked_by = d.get("blocked_by", [])
                if blocked_by and not all(bid in completed_ids for bid in blocked_by):
                    if d["status"] != TaskStatus.BLOCKED:
                        d["status"] = TaskStatus.BLOCKED.value
                        self._write_task_file(d["id"], d)
            except:
                pass

    # ─── CRUD ───

    def create(self, subject: str, description: str = "",
               active_form: str = "",
               pipeline: str = "", phase: str = "",
               parent_id: Optional[int] = None,
               blocked_by: Optional[list[int]] = None,
               subagent_id: Optional[str] = None,
               metadata: Optional[dict] = None) -> Task:
        """
        创建新任务。自动分配高水位线 ID。
        返回创建的 Task。
        """
        lock = self._lock()
        try:
            task_id = self._next_id()
            data = {
                "id": task_id,
                "subject": subject,
                "description": description,
                "active_form": active_form or subject,
                "status": TaskStatus.PENDING.value,
                "pipeline": pipeline,
                "phase": phase,
                "parent_id": parent_id,
                "blocked_by": blocked_by or [],
                "subagent_id": subagent_id,
                "created_at": time.time(),
                "started_at": None,
                "completed_at": None,
                "error": None,
                "metadata": metadata or {},
            }
            self._write_task_file(task_id, data)
            self._compute_blocked_status()
            return Task(data)
        finally:
            self._unlock(lock)

    def get(self, task_id: int) -> Optional[Task]:
        path = self._task_path(task_id)
        if path.exists():
            return Task(json.loads(path.read_text()))
        return None

    def query(self, pipeline: str = "", phase: str = "",
             status: Optional[TaskStatus] = None) -> List[Task]:
        """列出任务，支持按 pipeline / phase / status 筛选"""
        self._compute_blocked_status()
        tasks = []
        for f in sorted(TASKS_DIR.glob("*.json")):
            try:
                d = json.loads(f.read_text())
                task = Task(d)
                if pipeline and task.pipeline != pipeline:
                    continue
                if phase and task.phase != phase:
                    continue
                if status and task.status != status:
                    continue
                tasks.append(task)
            except:
                continue
        return tasks

    def list_all(self) -> List[Task]:
        return self.query()

    def update(self, task_id: int, **kwargs) -> Optional[Task]:
        """
        更新任务字段。自动处理状态变更的副作用。

        特殊处理：
        - status -> in_progress: 设置 started_at
        - status -> completed: 设置 completed_at
        - status -> failed: 记录 error
        """
        lock = self._lock()
        try:
            data = self._read_task_file(self._task_path(task_id))
            if not data:
                return None

            status = kwargs.get("status")
            if status is not None:
                now = time.time()
                if status == TaskStatus.IN_PROGRESS.value:
                    if data["status"] != TaskStatus.IN_PROGRESS.value:
                        data["started_at"] = now
                elif status == TaskStatus.COMPLETED.value:
                    data["completed_at"] = now
                elif status == TaskStatus.FAILED.value:
                    data["completed_at"] = now

            for k, v in kwargs.items():
                data[k] = v

            self._write_task_file(task_id, data)
            self._compute_blocked_status()
            return Task(data)
        finally:
            self._unlock(lock)

    def complete(self, task_id: int) -> Optional[Task]:
        return self.update(task_id, status=TaskStatus.COMPLETED.value)

    def fail(self, task_id: int, error: str = "") -> Optional[Task]:
        return self.update(task_id, status=TaskStatus.FAILED.value, error=error)

    def in_progress(self, task_id: int) -> Optional[Task]:
        return self.update(task_id, status=TaskStatus.IN_PROGRESS.value)

    def can_run(self, task_id: int) -> bool:
        """检查任务是否可以开始运行（依赖项全部完成）"""
        task = self.get(task_id)
        if task is None: return False
        if task.status.is_terminal: return False

        for dep_id in task.blocked_by:
            dep = self.get(dep_id)
            if dep is None or dep.status != TaskStatus.COMPLETED:
                return False
        return True

    def dependency_tree(self) -> dict:
        """返回依赖树（邻接表 + 根节点列表）"""
        tasks = self.list_all()
        tree = {}
        roots = []
        for t in tasks:
            tree[t.id] = {
                "subject": t.subject,
                "phase": t.phase,
                "status": t.status.value,
                "blocked_by": t.blocked_by,
                "children": [],
            }
            if not t.blocked_by:
                roots.append(t.id)
        # 计算 children
        for t in tasks:
            for dep_id in t.blocked_by:
                if dep_id in tree:
                    tree[dep_id]["children"].append(t.id)
        return {"nodes": tree, "roots": roots}

    def delete(self, task_id: int) -> bool:
        path = self._task_path(task_id)
        if path.exists():
            path.unlink()
            return True
        return False


# ═══════════════════════════════════════════════
# 格式化输出
# ═══════════════════════════════════════════════
def _status_emoji(s: str) -> str:
    m = {
        "pending": "⏳", "in_progress": "🔄", "completed": "✅",
        "blocked": "🔒", "failed": "❌",
    }
    return m.get(s, "?")

def _duration(start: Optional[float], end: Optional[float]) -> str:
    if start is None: return ""
    if end is None:
        end = time.time()
    delta = end - start
    if delta < 60: return f"{delta:.0f}s"
    if delta < 3600: return f"{delta/60:.1f}m"
    return f"{delta/3600:.1f}h"

def _ts(t: float) -> str:
    return datetime.fromtimestamp(t).strftime("%m-%d %H:%M")


def _print_tasks(tasks: list[Task]):
    if not tasks:
        print("  (无任务)")
        return

    # 表头
    print(f"  {'ID':>4}  {'状态':^2}  {'管线/阶段':^16}  {'任务':^40}  {'耗时':^8}")
    print(f"  {'─' * 4}  {'─' * 2}  {'─' * 16}  {'─' * 40}  {'─' * 8}")

    for t in tasks:
        pipe_phase = f"{t.pipeline}/{t.phase}" if t.phase else (t.pipeline or "-")
        dur = _duration(t.started_at or t.created_at, t.completed_at)
        print(f"  {t.id:>4}  {_status_emoji(t.status.value)}  {pipe_phase:^16}  {t.subject:<40}  {dur:^8}")

    print(f"\n  共 {len(tasks)} 个任务")


def _print_tree(registry: TaskRegistry):
    tree = registry.dependency_tree()
    nodes = tree["nodes"]

    def _render(tid: int, indent: int = 0):
        n = nodes[tid]
        em = _status_emoji(n["status"])
        prefix = "  " * indent + ("├─ " if indent else "")
        label = f"[{em}] {tid}: {n['subject']} ({n['phase']})"
        print(f"{prefix}{label}")
        for cid in n.get("children", []):
            _render(cid, indent + 1)

    print("\n  任务依赖树：")
    for root in tree["roots"]:
        _render(root)
    # 打印孤立节点
    visited = set()
    for root in tree["roots"]:
        _collect_children(root, nodes, visited)
    for tid in nodes:
        if tid not in visited:
            _render(int(tid), 0)

def _collect_children(tid, nodes, visited):
    visited.add(str(tid))
    for cid in nodes.get(str(tid), {}).get("children", []):
        _collect_children(cid, nodes, visited)


def _print_status(task: Task):
    status = task.status
    print(f"\n  Task #{task.id}: {task.subject}")
    print(f"  {'─' * 50}")
    print(f"  状态: {_status_emoji(status.value)} {status.value}")
    if task.pipeline: print(f"  管线: {task.pipeline}")
    if task.phase:  print(f"  阶段: {task.phase}")
    if task.active_form != task.subject: print(f"  进度: {task.active_form}")
    if task.description: print(f"  详情: {task.description}")
    if task.subagent_id: print(f"  子代理: {task.subagent_id}")
    if task.blocked_by: print(f"  依赖: {', '.join(str(x) for x in task.blocked_by)}")
    if task.error: print(f"  错误: {task.error}")
    print(f"  创建: {_ts(task.created_at)}")
    if task.started_at: print(f"  开始: {_ts(task.started_at)}")
    if task.completed_at: print(f"  完成: {_ts(task.completed_at)}")
    dur = _duration(task.started_at or task.created_at, task.completed_at or None)
    if dur: print(f"  耗时: {dur}")


# ═══════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="TaskRegistry CLI")
    sub = parser.add_subparsers(dest="command")

    # list
    p_list = sub.add_parser("list", help="列出所有任务")
    p_list.add_argument("--pipeline", default="", help="按管线筛选")

    # status
    p_status = sub.add_parser("status", help="查看任务详情")
    p_status.add_argument("task_id", type=int)

    # tree
    sub.add_parser("tree", help="打印依赖树")

    # create
    p_create = sub.add_parser("create", help="创建任务")
    p_create.add_argument("subject", help="任务标题")
    p_create.add_argument("--desc", default="", help="详情")
    p_create.add_argument("--active-form", default="", help="进度显示文本")
    p_create.add_argument("--pipeline", default="", help="管线名")
    p_create.add_argument("--phase", default="", help="阶段")
    p_create.add_argument("--parent", type=int, default=None, help="父任务ID")
    p_create.add_argument("--blocked", default="", help="阻塞依赖（逗号分隔ID）")
    p_create.add_argument("--subagent", default="", help="子代理ID")

    # update
    p_update = sub.add_parser("update", help="更新任务")
    p_update.add_argument("task_id", type=int)
    p_update.add_argument("--status", choices=["pending", "in_progress", "completed", "blocked", "failed"])
    p_update.add_argument("--error", default=None, help="错误信息")
    p_update.add_argument("--active-form", default=None)

    # complete / fail
    p_complete = sub.add_parser("complete", help="完成任务")
    p_complete.add_argument("task_id", type=int)

    p_fail = sub.add_parser("fail", help="标记失败")
    p_fail.add_argument("task_id", type=int)
    p_fail.add_argument("--error", default="", help="错误信息")

    # can-run
    p_cr = sub.add_parser("can_run", help="检查任务是否可以运行")
    p_cr.add_argument("task_id", type=int)

    # delete
    p_del = sub.add_parser("delete", help="删除任务")
    p_del.add_argument("task_id", type=int)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    reg = TaskRegistry()

    if args.command == "list":
        tasks = reg.query(pipeline=args.pipeline)
        _print_tasks(tasks)

    elif args.command == "status":
        t = reg.get(args.task_id)
        if t: _print_status(t)
        else: print(f"  任务 #{args.task_id} 不存在")

    elif args.command == "tree":
        _print_tree(reg)

    elif args.command == "create":
        blocked = [int(x) for x in args.blocked.split(",") if x.strip()] if args.blocked else []
        t = reg.create(
            subject=args.subject,
            description=args.desc,
            active_form=args.active_form or args.subject,
            pipeline=args.pipeline,
            phase=args.phase,
            parent_id=args.parent,
            blocked_by=blocked,
            subagent_id=args.subagent or None,
        )
        print(f"  ✅ 创建 Task #{t.id}: {t.subject}")

    elif args.command == "update":
        kwargs = {}
        if args.status: kwargs["status"] = args.status
        if args.error is not None: kwargs["error"] = args.error
        if args.active_form is not None: kwargs["active_form"] = args.active_form
        t = reg.update(args.task_id, **kwargs)
        if t:
            print(f"  ✅ 更新 Task #{t.id}")
            _print_status(t)
        else:
            print(f"  ❌ 任务 #{args.task_id} 不存在")

    elif args.command == "complete":
        t = reg.complete(args.task_id)
        if t:
            print(f"  ✅ 完成 Task #{t.id}")
        else:
            print(f"  ❌ 任务 #{args.task_id} 不存在")

    elif args.command == "fail":
        t = reg.fail(args.task_id, error=args.error)
        if t:
            print(f"  ❌ 标记失败 Task #{t.id}")
        else:
            print(f"  ❌ 任务 #{args.task_id} 不存在")

    elif args.command == "can_run":
        can = reg.can_run(args.task_id)
        print(f"  {'✅ 可以运行' if can else '🔒 依赖未完成'}")

    elif args.command == "delete":
        ok = reg.delete(args.task_id)
        print(f"  {'✅ 已删除' if ok else '❌ 不存在'} Task #{args.task_id}")


if __name__ == "__main__":
    main()
