#!/usr/bin/env python3
"""
HookDispatcher — Claude Code 风格的事件 Hook 系统
===================================================
设计灵感来源：Claude Code 的 hooks.ts / AsyncHookRegistry / hookEvents.ts

管线事件驱动：
- 在管线关键节点 emit 事件
- 自动执行对应的 Hook 脚本（shell/python）
- 支持异步执行 & 飞书通知

事件列表：
    PipelineStarted       管线开始
    PhaseCompleted        Phase 完成
    PhaseFailed           Phase 失败
    PipelineCompleted     管线全部完成
    SubagentSpawned       子代理被 spawn
    SubagentCompleted     子代理成功完成
    SubagentFailed        子代理失败
    TaskCreated           新任务创建
    TaskCompleted         任务完成
    TaskFailed            任务失败
    BPReceived            新 BP 到达
    Error                 管线错误

Hook 配置格式（.pipeline/hooks/<event>.json）：
{
    "event": "PhaseCompleted",
    "command": "python3 scripts/notify_xavier.py",
    "args": {"phase": "$PHASE"},
    "async": true,
    "description": "Phase 完成后通知 Xavier"
}

$ 占位符会在 emit 时替换为上下文变量。
"""

import subprocess
import asyncio
import json
import os
import sys
import re
import time
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, Future

WORKSPACE = Path(__file__).resolve().parent.parent
HOOKS_DIR = WORKSPACE / ".pipeline" / "hooks"

class HookConfig:
    """单个 Hook 配置"""

    def __init__(self, source_file: Path, event: str, command: str,
                 args: Optional[dict] = None, async_: bool = True,
                 description: str = ""):
        self.source_file = source_file
        self.event = event
        self.command = command
        self.args = args or {}
        self.async_ = async_
        self.description = description

    def resolve_command(self, ctx: dict) -> str:
        """
        替换命令和参数中的占位符。
        
        支持 $VAR / ${VAR} 语法。
        ctx 中的变量会替换 $VAR / ${VAR}。
        """
        def _resolve(s: str) -> str:
            def replacer(m):
                var_name = m.group(1) or m.group(2) or m.group(3)
                return ctx.get(var_name, m.group(0))
            return re.sub(r'\$\{(\w+)\}|\$(\w+)', replacer, s)
        return _resolve(self.command)

    def to_dict(self) -> dict:
        return {
            "event": self.event,
            "command": self.command,
            "args": self.args,
            "async": self.async_,
            "description": self.description,
            "source": str(self.source_file),
        }


class HookResult:
    """Hook 执行结果"""

    def __init__(self, config: HookConfig, exit_code: int, stdout: str,
                 stderr: str, duration_ms: float):
        self.config = config
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.duration_ms = duration_ms

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    def summary(self) -> str:
        em = "✅" if self.success else "❌"
        return f"{em} [{self.config.command}] {self.config.description or self.config.event} ({self.duration_ms:.0f}ms)"


class HookDispatcher:
    """
    Hook 事件分发器。

    - 自动加载 .pipeline/hooks/ 下所有钩子配置（.json + .py）
    - 支持 .exec 格式的 Hook（Claude Code 脚本模式）
    """

    def __init__(self):
        self._hooks: list[HookConfig] = []
        HOOKS_DIR.mkdir(parents=True, exist_ok=True)
        self._load_hooks()
        if not self._hooks:
            self._generate_sample_hooks()
            self._load_hooks()

    def _load_hooks(self):
        """加载所有钩子"""
        self._hooks = []
        if not HOOKS_DIR.exists():
            return
        for f in sorted(HOOKS_DIR.glob("*.json")):
            try:
                d = json.loads(f.read_text())
                hook = HookConfig(
                    source_file=f,
                    event=d.get("event", ""),
                    command=d.get("command", ""),
                    args=d.get("args", {}),
                    async_=d.get("async", True),
                    description=d.get("description", ""),
                )
                self._hooks.append(hook)
            except Exception as e:
                print(f"  ⚠️ 加载 Hook 失败: {f.name} — {e}")

    def _generate_sample_hooks(self):
        """如果没有Hook，生成示例（不覆盖已有的）"""
        samples = {
            "pipeline_completed.json": {
                "event": "PipelineCompleted",
                "command": "echo 'Pipeline completed: $PIPELINE (Phase: $PHASE)'",
                "args": {},
                "async": True,
                "description": "管线完成后打印日志"
            },
            "subagent_failed.json": {
                "event": "SubagentFailed",
                "command": "python3 scripts/task.py update $TASK_ID --status failed --error '$ERROR_MSG'" if not (WORKSPACE / "scripts" / "task.py").exists() else "echo '[ALERT]' Subagent failed: $SUBAGENT_ID (Pipeline: $PIPELINE)'",
                "args": {},
                "async": True,
                "description": "子代理失败记录到 TaskRegistry"
            },
            "error.json": {
                "event": "Error",
                "command": "echo '[ERROR] Pipeline $PIPELINE failed: $ERROR_MSG'",
                "args": {},
                "async": True,
                "description": "管线错误日志"
            },
        }
        for name, data in samples.items():
            path = HOOKS_DIR / name
            if not path.exists():
                path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def get_hooks_for_event(self, event: str) -> list[HookConfig]:
        """获取匹配某个事件的所有 Hook"""
        return [h for h in self._hooks if h.event == event]

    def emit(self, event: str, **kwargs) -> list[HookResult]:
        """
        发射事件。

        kwargs 作为上下文变量传入 Hook（自动转大写：
            "phase": "phase4" → $PHASE = "phase4"
        """
        hooks = self.get_hooks_for_event(event)
        if not hooks:
            return []

        ctx = {k.upper(): str(v) for k, v in kwargs.items()}
        ctx["EVENT"] = event
        ctx["TIMESTAMP"] = time.strftime("%Y-%m-%d %H:%M:%S")

        results = []
        for hook in hooks:
            if hook.async_:
                # 异步执行
                executor = ThreadPoolExecutor(max_workers=1)
                future = executor.submit(self._run_hook, hook, ctx)
                future.add_done_callback(
                    lambda f: self._on_async_done(hook, f)
                )
                results.append(HookResult(
                    hook, -1, "(async)", "(async)", 0
                ))
                executor.shutdown(wait=False)
            else:
                # 同步执行
                r = self._run_hook(hook, ctx)
                results.append(r)

        return results

    def _run_hook(self, hook: HookConfig, ctx: dict) -> HookResult:
        """执行单个 Hook"""
        cmd = hook.resolve_command(ctx)
        start = time.time()
        try:
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=30, cwd=str(WORKSPACE),
            )
            duration = (time.time() - start) * 1000
            return HookResult(
                hook, proc.returncode,
                proc.stdout.strip(), proc.stderr.strip(),
                duration,
            )
        except subprocess.TimeoutExpired:
            duration = (time.time() - start) * 1000
            return HookResult(hook, -1, "", "Timeout (30s)", duration)
        except Exception as e:
            duration = (time.time() - start) * 1000
            return HookResult(hook, -1, "", str(e), duration)

    def _on_async_done(self, hook: HookConfig, future: Future):
        """异步 Hook 完成回调"""
        try:
            result = future.result()
            if not result.success:
                # 失败日志
                err_msg = f"Hook '{hook.description or hook.event}' failed"
                print(f"  ⚠️ {err_msg}: exit {result.exit_code}")
                if result.stderr:
                    print(f"    stderr: {result.stderr}")
        except Exception as e:
            print(f"  ⚠️ Hook '{hook.description or hook.event}' exception: {e}")

    def list_hooks(self) -> list[dict]:
        """列出所有 Hook"""
        return [h.to_dict() for h in self._hooks]


# ═══════════════════════════════════════════════
# 管线级便利 API：
# run_bp_pipeline.py / run_ir_pipeline.py 直接调用。
# ═══════════════════════════════════════════════
def emit_pipeline_event(pipeline: str, phase: str, event: str,
                        task_id: int = 0, error_msg: str = "",
                        subagent_id: str = ""):
    """
    管线事件便捷封装。

    用法（在管线 script 中）：
        from scripts.hook_dispatcher import emit_pipeline_event

        emit_pipeline_event("bp_dd", "phase0", "PhaseCompleted", task_id=3)
        emit_pipeline_event("bp_dd", "phase4", "SubagentFailed",
                           subagent_id="BP_DD_团队与合规", error_msg="OCR 失败")
    """
    dispatcher = HookDispatcher()
    ctx = {
        "pipeline": pipeline,
        "phase": phase,
        "event": event,
    }
    if task_id: ctx["task_id"] = str(task_id)
    if error_msg: ctx["error_msg"] = error_msg
    if subagent_id: ctx["subagent_id"] = subagent_id
    return dispatcher.emit(event, **ctx)


# ═══════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HookDispatcher")
    sub = parser.add_subparsers(dest="command")

    # list
    sub.add_parser("list", help="列出所有 Hook")

    # emit
    p_emit = sub.add_parser("emit", help="触发事件")
    p_emit.add_argument("event", help="事件名")
    p_emit.add_argument("--kv", nargs="*", default=[],
                        help="键值对（key=value）")

    args = parser.parse_args()

    if args.command == "list":
        dp = HookDispatcher()
        hooks = dp.list_hooks()
        if not hooks:
            print("  (无 Hook)")
        else:
            print(f"  {'事件':<20}  {'命令':<40}  {'异步':^4}  {'说明'}")
            print(f"  {'─' * 20}  {'─' * 40}  {'─' * 4}  {'─' * 20}")
            for h in hooks:
                print(f"  {h['event']:<20}  {h['command']:<40}  {'是' if h['async'] else '否':^4}  {h['description']}")
            print(f"\n  共 {len(hooks)} 个 Hook")

    elif args.command == "emit":
        dp = HookDispatcher()
        kv = {}
        for item in args.kv or []:
            if "=" in item:
                k, v = item.split("=", 1)
                kv[k] = v
        results = dp.emit(args.event, **kv)
        if not results:
            print(f"  (没有 Hook 匹配事件: {args.event})")
        for r in results:
            if r.exit_code == -1:
                print(f"  🔄 {r.config.description or r.config.event} (异步执行中)")
            else:
                print(f"  {'✅' if r.success else '❌'} {r.config.description or r.config.event} ({r.duration_ms:.0f}ms)")
                if r.stdout: print(f"    {r.stdout}")
                if r.stderr: print(f"    stderr: {r.stderr}")
    else:
        parser.print_help()
