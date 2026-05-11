#!/usr/bin/env python3
"""
BP Pipeline — 后台分步执行版

替代 run_bp.py 的一口气执行模式，每个 heavy phase 在后台独立运行，
通过 PID 文件 + 轮询实现异步等待。

用法（WorkBuddy Agent 调用）：
    # 1. 启动 phase0（前台，很快）
    python3 scripts/bp_pipeline_bg.py --job-id TASK-XXX start phase0_document_intake ...
    
    # 2. 启动 phase05（后台）
    python3 scripts/bp_pipeline_bg.py --job-id TASK-XXX start phase05_company_verify ...
    
    # 3. 轮询 phase05 是否完成
    python3 scripts/bp_pipeline_bg.py --job-id TASK-XXX poll phase05_company_verify
    
    # 4. 启动 phase1（后台）
    python3 scripts/bp_pipeline_bg.py --job-id TASK-XXX start phase1_presearch ...
    
    # 5. 轮询 + 收集
    python3 scripts/bp_pipeline_bg.py --job-id TASK-XXX poll phase1_presearch
    
    # 6. 后续 phase（dispatch/synthesis/delivery）同理

Heavy phases（后台运行）：
    phase05_company_verify   — 主体核验（大量搜索，2-5 分钟）
    phase1_presearch         — 预搜索（30-42 次搜索，3-10 分钟）
    phase3_delivery          — 交付（含对抗验证 + DOCX 生成，2-5 分钟）

Light phases（前台运行）：
    phase0_document_intake   — OCR（30 秒内）
    phase2_dispatch_prepare  — 准备 manifest（秒级）
    phase2_dispatch_collect  — 检查输出（秒级）
    phase25_competition_prepare/collect — 同上
    phase3_synthesis_prepare/collect    — 同上
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
PHASE_RUNNER = SCRIPTS_DIR / "phase_runner.py"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

# Heavy phases — 会后台运行
HEAVY_PHASES = {"phase05_company_verify", "phase1_presearch", "phase3_delivery"}

# 超时设置（秒）
PHASE_TIMEOUTS = {
    "phase0_document_intake": 300,
    "phase05_company_verify": 600,    # 10 分钟
    "phase1_presearch": 900,           # 15 分钟
    "phase2_dispatch_prepare": 120,
    "phase2_dispatch_collect": 120,
    "phase25_competition_prepare": 120,
    "phase25_competition_collect": 120,
    "phase3_synthesis_prepare": 120,
    "phase3_synthesis_collect": 120,
    "phase3_delivery": 600,            # 10 分钟
}


def _python() -> str:
    return sys.executable


def start_phase(job_id: str, phase: str, entity: str = "", market: str = "cn",
                input_file: str = "", query: str = "", session_id: str = "") -> dict:
    """启动一个 phase。Heavy phases 后台运行，light phases 前台运行。"""
    common_args = [
        "--job-id", job_id,
        "--phase", phase,
        "--entity", entity,
        "--market", market,
        "--input-file", input_file,
        "--query", query,
        "--session-id", session_id,
    ]

    if phase in HEAVY_PHASES:
        # 后台运行
        cmd = [_python(), str(PHASE_RUNNER), "--background"] + common_args
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
        return {"ok": False, "error": f"Failed to start background: {result.stderr[:500]}"}
    else:
        # 前台运行
        cmd = [_python(), str(PHASE_RUNNER), "--run"] + common_args
        timeout = PHASE_TIMEOUTS.get(phase, 300)
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=timeout)
        if result.stdout.strip():
            try:
                return json.loads(result.stdout.strip())
            except json.JSONDecodeError:
                return {"ok": result.returncode == 0, "stdout": result.stdout[-2000:]}
        return {"ok": result.returncode == 0, "stderr": result.stderr[:500]}


def poll_phase(job_id: str, phase: str, timeout: int = 0) -> dict:
    """轮询 phase 状态。timeout=0 表示只查一次，>0 表示阻塞等待。"""
    if timeout > 0:
        cmd = [_python(), str(PHASE_RUNNER), "--wait", "--job-id", job_id, "--phase", phase,
               "--timeout", str(timeout)]
    else:
        cmd = [_python(), str(PHASE_RUNNER), "--status", "--job-id", job_id, "--phase", phase]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=timeout + 30)
    if result.stdout.strip():
        try:
            return json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            return {"status": "parse_error", "stdout": result.stdout[:500]}
    return {"status": "error", "stderr": result.stderr[:500]}


def read_result(job_id: str, phase: str) -> dict:
    """读取已完成 phase 的结果"""
    result_file = ROOT / "jobs" / job_id / "state" / f"{phase}.result.json"
    if not result_file.exists():
        return {"ok": False, "error": f"Result not found: {result_file}"}
    return json.loads(result_file.read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(description="BP Pipeline 后台分步执行版")
    ap.add_argument("--job-id", required=True)

    sub = ap.add_subparsers(dest="action")

    # start
    p_start = sub.add_parser("start", help="启动一个 phase")
    p_start.add_argument("phase", help="阶段名称")
    p_start.add_argument("--entity", default="")
    p_start.add_argument("--market", default="cn")
    p_start.add_argument("--input-file", default="")
    p_start.add_argument("--query", default="")
    p_start.add_argument("--session-id", default="")

    # poll
    p_poll = sub.add_parser("poll", help="轮询 phase 状态")
    p_poll.add_argument("phase", help="阶段名称")
    p_poll.add_argument("--timeout", type=int, default=0, help="阻塞等待秒数（0=只查一次）")

    # result
    p_result = sub.add_parser("result", help="读取 phase 结果")
    p_result.add_argument("phase", help="阶段名称")

    # status-all
    sub.add_parser("status-all", help="查看所有 phase 状态")

    args = ap.parse_args()

    if args.action == "start":
        result = start_phase(args.job_id, args.phase, args.entity, args.market,
                             args.input_file, args.query, args.session_id)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    elif args.action == "poll":
        result = poll_phase(args.job_id, args.phase, timeout=args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    elif args.action == "result":
        result = read_result(args.job_id, args.phase)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    elif args.action == "status-all":
        from runtime.profiles.bp_profile import BPProfile
        profile = BPProfile(runtime_root=ROOT)
        all_status = {}
        for phase in profile.phases():
            status = poll_phase(args.job_id, phase)
            all_status[phase] = status
            icon = {"completed": "✅", "running": "🔄", "failed": "❌", "not_started": "⏳"}.get(status["status"], "❓")
            print(f"  {icon} {phase}: {status['status']}", flush=True)
        print(json.dumps(all_status, ensure_ascii=False, indent=2, default=str))

    else:
        ap.print_help()


if __name__ == "__main__":
    main()
