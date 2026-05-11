"""
Heavy Phase Background Runner — 用于 profile handler 内部

将耗时 > 2 分钟的 phase（company_verify, presearch, delivery）放到
独立子进程中执行，避免受 Bash 工具超时限制。

工作原理：
    1. Handler 调用 launch_heavy_phase() → fork 子进程，写 PID 文件，立即返回 needs_poll
    2. Kernel 看到 needs_poll → 返回早期结果，Agent 知道该 phase 正在后台运行
    3. Agent 通过 poll_heavy_phase() 轮询直到完成
    4. Agent 调用 pipeline 恢复（start_phase=next_phase）
    5. 下次 handler 被调用时，检查 result 文件是否存在 → 直接返回缓存结果

子进程使用 start_new_session=True，不受父进程 SIGTERM 影响。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PHASE_RUNNER = Path(__file__).resolve().parent / "phase_runner.py"

PHASE_TIMEOUTS = {
    "phase05_company_verify": 600,
    "phase1_presearch": 900,
    "phase3_delivery": 600,
    "phase5_delivery": 600,
    "phase15_extract": 900,
}


def _state_dir(runtime_root: Path, job_id: str) -> Path:
    d = runtime_root / "jobs" / job_id / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _result_path(runtime_root: Path, job_id: str, phase: str) -> Path:
    return _state_dir(runtime_root, job_id) / f"{phase}.result.json"


def _pid_path(runtime_root: Path, job_id: str, phase: str) -> Path:
    return _state_dir(runtime_root, job_id) / f"{phase}.pid"


def _error_path(runtime_root: Path, job_id: str, phase: str) -> Path:
    return _state_dir(runtime_root, job_id) / f"{phase}.error"


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def check_cached_result(runtime_root: Path, job_id: str, phase: str) -> dict | None:
    """检查是否有缓存的结果文件（来自之前的后台运行）。
    如果有，返回解析后的 dict；否则返回 None。
    同时清理 PID 文件。"""
    result_file = _result_path(runtime_root, job_id, phase)
    pid_file = _pid_path(runtime_root, job_id, phase)

    if result_file.exists():
        try:
            data = json.loads(result_file.read_text(encoding="utf-8"))
            # 清理：删除结果文件避免下次误读（结果已被消费）
            result_file.unlink(missing_ok=True)
            _error_path(runtime_root, job_id, phase).unlink(missing_ok=True)
            pid_file.unlink(missing_ok=True)
            return data
        except Exception:
            pass

    # 检查是否有错误文件
    error_file = _error_path(runtime_root, job_id, phase)
    if error_file.exists():
        error_text = error_file.read_text(encoding="utf-8")
        # 也清理错误文件
        error_file.unlink(missing_ok=True)
        pid_file.unlink(missing_ok=True)
        return {"ok": False, "error": error_text}

    return None


def launch_heavy_phase(
    runtime_root: Path,
    job_ctx: Any,
    phase: str,
    pipeline: str = "bp",
) -> dict[str, Any]:
    """启动一个 heavy phase 的后台子进程，立即返回 needs_poll 结果。

    子进程通过 Popen(start_new_session=True) 启动，脱离父进程组。
    结果写入 state/{phase}.result.json。
    """
    metadata = job_ctx.metadata or {}

    # 清理旧的 PID/result/error 文件
    for p in (_result_path(runtime_root, job_ctx.job_id, phase),
              _error_path(runtime_root, job_ctx.job_id, phase)):
        p.unlink(missing_ok=True)

    cmd = [
        sys.executable,
        str(PHASE_RUNNER),
        "--job-id", job_ctx.job_id,
        "--phase", phase,
        "--entity", job_ctx.entity or "",
        "--market", getattr(job_ctx, "market", "cn") or "cn",
        "--input-file", metadata.get("input_file", ""),
        "--query", job_ctx.query or "",
        "--session-id", metadata.get("session_id", ""),
        "--pipeline", pipeline,
        "--run",
    ]

    print(f"  🔄 [heavy_phase_bg] 启动后台子进程: {phase}", flush=True)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,  # 子进程的 stdout 写到 result 文件
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(runtime_root),
            start_new_session=True,  # 关键：脱离父进程组
        )

        # 写 PID 文件供轮询
        pid_file = _pid_path(runtime_root, job_ctx.job_id, phase)
        pid_file.write_text(str(proc.pid), encoding="utf-8")

        print(f"  📌 [heavy_phase_bg] 子进程 PID={proc.pid}", flush=True)

        return {
            "ok": True,
            "needs_poll": True,
            "mode": "bg_launched",
            "phase": phase,
            "job_id": job_ctx.job_id,
            "bg_pid": proc.pid,
            "timeout": PHASE_TIMEOUTS.get(phase, 900),
        }
    except Exception as exc:
        return {
            "ok": False,
            "phase": phase,
            "error": f"Failed to launch subprocess: {exc}",
        }


def poll_heavy_phase(
    runtime_root: Path,
    job_id: str,
    phase: str,
    timeout: int = 0,
) -> dict[str, Any]:
    """轮询 heavy phase 的后台执行状态。

    timeout=0: 只查一次，立即返回
    timeout>0: 阻塞等待直到完成或超时
    """
    pid_file = _pid_path(runtime_root, job_id, phase)

    # 检查是否已有结果
    cached = check_cached_result(runtime_root, job_id, phase)
    if cached is not None:
        return {"status": "completed", "ok": cached.get("ok", False), "result": cached}

    # 检查进程是否在运行
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            if _is_process_alive(pid):
                if timeout <= 0:
                    elapsed = time.time() - pid_file.stat().st_mtime
                    return {"status": "running", "ok": None, "pid": pid, "elapsed_seconds": int(elapsed)}
                # 阻塞等待模式
                start = time.time()
                while time.time() - start < timeout:
                    cached = check_cached_result(runtime_root, job_id, phase)
                    if cached is not None:
                        return {"status": "completed", "ok": cached.get("ok", False), "result": cached}
                    if not _is_process_alive(pid):
                        break
                    time.sleep(3)
                # 超时或进程已死
                cached = check_cached_result(runtime_root, job_id, phase)
                if cached is not None:
                    return {"status": "completed", "ok": cached.get("ok", False), "result": cached}
                return {"status": "timeout" if timeout > 0 else "failed", "ok": False,
                        "error": f"Process {pid} dead without result"}
            else:
                # 进程已死但没结果 → 检查 error
                pid_file.unlink(missing_ok=True)
                cached = check_cached_result(runtime_root, job_id, phase)
                if cached is not None:
                    return {"status": "completed", "ok": cached.get("ok", False), "result": cached}
                return {"status": "failed", "ok": False, "error": f"Process {pid} died without writing result"}
        except ValueError:
            pid_file.unlink(missing_ok=True)

    return {"status": "not_started", "ok": None}
