#!/usr/bin/env python3
"""
Cleanup Registry — Claude Code cleanupRegistry.ts 的 Python 移植
=================================================================

管线生命周期管理：进程退出时自动清理临时文件、锁、未完成的子代理会话。
防止子代理 crash 后残留 dispatch.json 半成品、DOCX 半成品、临时文件。

核心思想：每个操作注册 cleanup callback → 退出时统一执行（只执行一次）。

用法：
    from cleanup_registry import registry, register_file, register_dir

    # 注册要清理的文件/目录
    tmp_path = register_file("/tmp/pipeline_xyz.pdf")
    tmp_dir = register_dir("/tmp/pipeline_xyz_output/")

    # 注册自定义清理函数
    registry.register(lambda: os.unlink("/tmp/custom_thing"))

    # 手动触发清理（通常在 atexit 中自动调用）
    registry.cleanup()

    # 取消注册（文件已被正式交付，不再清理）
    registry.unregister(tmp_path)
"""
from __future__ import annotations
import atexit
import json
import os
import signal
import shutil
import threading
import time
import weakref
from pathlib import Path
from typing import Callable, Optional

# ═══════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════
_registry_instance = None
_lock = threading.Lock()


def get_registry() -> "CleanupRegistry":
    """获取全局单例。"""
    global _registry_instance
    if _registry_instance is None:
        with _lock:
            if _registry_instance is None:
                _registry_instance = CleanupRegistry()
    return _registry_instance


# ============================================================
# CleanupRegistry — 核心
# ============================================================
class CleanupRegistry:
    """
    统一管理清理回调。

    - 每个回调只注册一次
    - 进程退出时自动执行（atexit + SIGTERM/SIGINT）
    - 幂等性：cleanup() 可安全调用多次，只执行一次
    """

    def __init__(self):
        self._callbacks: list[dict] = []  # [{fn, label, args}, ...]
        self._executed = False
        self._lock = threading.Lock()
        self._stats = {"registered": 0, "cleaned": 0, "errors": 0}
        self._register_handlers()

    def _register_handlers(self):
        """注册 atexit + 信号处理器。"""
        atexit.register(self.cleanup)

        # 处理 SIGTERM 和 SIGINT
        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sigint = signal.getsignal(signal.SIGINT)

        def _handle_sig(sig, frame):
            self.cleanup()
            # 恢复原始信号并重新发送，让进程正常终止
            try:
                if sig == signal.SIGTERM and callable(original_sigterm):
                    original_sigterm(sig, frame)
                elif sig == signal.SIGINT and callable(original_sigint):
                    original_sigint(sig, frame)
                else:
                    os._exit(128 + sig)
            except (TypeError, ValueError):
                os._exit(128 + sig)

        signal.signal(signal.SIGTERM, _handle_sig)
        signal.signal(signal.SIGINT, _handle_sig)

    def register(self, fn: Callable, *, label: str = "", **kwargs) -> str:
        """
        注册清理回调。

        Args:
            fn: 清理函数
            label: 描述标签（用于日志）
            **kwargs: 传给 fn 的关键字参数

        Returns:
            callback_id: 可用于 unregister
        """
        cb_id = f"{label}_{len(self._callbacks)}_{int(time.time()*1000)}"

        with self._lock:
            if kwargs:
                def wrapped():
                    fn(**kwargs)
            else:
                wrapped = fn

            self._callbacks.append({"id": cb_id, "fn": wrapped, "label": label})
            self._stats["registered"] += 1

        return cb_id

    def unregister(self, cb_id: str) -> bool:
        """取消注册（例如文件已被正式交付，不再需要清理）。"""
        with self._lock:
            for i, cb in enumerate(self._callbacks):
                if cb["id"] == cb_id:
                    self._callbacks.pop(i)
                    return True
        return False

    def cleanup(self, verbose: bool = False):
        """执行所有清理回调。幂等——只执行一次。"""
        with self._lock:
            if self._executed:
                return
            self._executed = True
            callbacks = list(self._callbacks)
            self._callbacks.clear()

        if verbose and callbacks:
            print(f"\n  🧹 Cleanup Registry: {len(callbacks)} 个清理任务")

        for i, cb in enumerate(callbacks):
            try:
                cb["fn"]()
                self._stats["cleaned"] += 1
                if verbose:
                    print(f"    ✅ [{i+1}] {cb['label']}")
            except Exception as e:
                self._stats["errors"] += 1
                if verbose:
                    print(f"    ❌ [{i+1}] {cb['label']}: {e}")

    def get_stats(self) -> dict:
        with self._lock:
            return dict(self._stats)

    def has_pending(self) -> bool:
        with self._lock:
            return len(self._callbacks) > 0


# ============================================================
# 便捷函数
# ============================================================
def register_file(path: str | Path, label: str = "") -> str:
    """注册清理临时文件。返回 cb_id。"""
    path = str(path)
    cb_id = registry.register(_remove_file, path=path, label=label or f"file:{path}")
    return cb_id

def register_dir(path: str | Path, label: str = "") -> str:
    """注册清理临时目录。返回 cb_id。"""
    path = str(path)
    cb_id = registry.register(_remove_dir, path=path, label=label or f"dir:{path}")
    return cb_id

def register_files(paths: list[str | Path], label: str = "") -> list[str]:
    """批量注册清理文件。返回 cb_ids。"""
    return [register_file(p, label or f"files:{len(paths)}") for p in paths]

def unregister(cb_id: str):
    """取消注册（文件已正式使用，不再清理）。"""
    registry.unregister(cb_id)

def cleanup(verbose: bool = False):
    """手动触发清理。"""
    registry.cleanup(verbose=verbose)


def _remove_file(path: str):
    p = Path(path)
    if p.exists():
        p.unlink()

def _remove_dir(path: str):
    p = Path(path)
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)


# 全局单例（模块级）
registry = CleanupRegistry()


# ============================================================
# 管线集成 helper
# ============================================================
class PipelineCleanup:
    """
    管线级清理封装。

    用法（在管线开头）：
        pc = PipelineCleanup(task_id)
        pc.register_temp_file("partial_output.md")
        pc.register_temp_file("dispatch.json")
        pc.register_temp_dir("temp_docs/")

        # 管线正常完成后
        pc.release_all()  # 不再清理（文件已交付）
    """

    def __init__(self, task_id: str, tasks_dir: Path):
        self.task_id = task_id
        self.tasks_dir = tasks_dir
        self._cb_ids: list[str] = []
        self._released = False

    def register_temp_file(self, filename: str) -> str:
        path = self.tasks_dir / filename
        if path.exists():
            cb_id = register_file(path, label=f"pipeline:{self.task_id}:{filename}")
            self._cb_ids.append(cb_id)
            return cb_id
        return ""

    def register_temp_dir(self, dirname: str) -> str:
        path = self.tasks_dir / dirname
        if path.exists():
            cb_id = register_dir(path, label=f"pipeline-{self.task_id}-{dirname}")
            self._cb_ids.append(cb_id)
            return cb_id
        return ""

    def release_all(self):
        """管线正常完成，释放所有清理任务（文件已交付，不再清理）。"""
        for cb_id in self._cb_ids:
            registry.unregister(cb_id)
        self._released = True
        self._cb_ids.clear()

    def cleanup(self):
        """管线异常终止，触发清理。"""
        if not self._released:
            for cb_id in self._cb_ids:
                registry.unregister(cb_id)
            self._cb_ids.clear()
