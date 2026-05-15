from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.orchestrator.workspace_layout import JobWorkspace, build_job_workspace
from runtime.profiles.base import JobContext


@dataclass
class OrchestratorKernel:
    runtime_root: Path

    def prepare_job(self, job_ctx: JobContext) -> JobWorkspace:
        """Build (or reuse) a JobWorkspace and inject it into the JobContext."""
        workspace = build_job_workspace(self.runtime_root, job_ctx.job_id)
        job_ctx.workspace = workspace
        return workspace

    def run(self, profile, job_ctx: JobContext,
            start_phase: str | None = None) -> dict[str, Any]:
        workspace = self.prepare_job(job_ctx)

        phases = profile.phases()
        if start_phase:
            try:
                idx = phases.index(start_phase)
                phases = phases[idx:]
            except ValueError:
                return {"ok": False, "error": f"Unknown start_phase: {start_phase}"}

        results: dict[str, Any] = {
            "job_id": job_ctx.job_id,
            "profile": profile.name,
            "workspace": str(workspace.root),
            "phases": [],
        }
        for i, phase_name in enumerate(phases):
            print(f"\n{'='*50}", flush=True)
            print(f"▶ 开始阶段: {phase_name}", flush=True)
            print(f"{'='*50}", flush=True)
            phase_result = profile.run_phase(phase_name, job_ctx)
            phase_ok = phase_result.get("ok", True)
            print(f"{'✅' if phase_ok else '❌'} 阶段完成: {phase_name} → {'成功' if phase_ok else '失败'}", flush=True)
            results["phases"].append({
                "phase": phase_name,
                "result": phase_result,
            })

            self._write_phase_state(workspace, phase_name, phase_result)

            if phase_result.get("needs_dispatch"):
                results["dispatch_info"] = phase_result.get("result", {})
                results["status"] = "needs_dispatch"
                results["paused_after"] = phase_name
                results["next_phase"] = phases[i + 1] if i + 1 < len(phases) else None
                results["ok"] = True  # 不是失败，是暂停
                print(f"  ⏸ needs_dispatch — 暂停于 {phase_name}，等待子代理完成后用 start_phase='{phases[i + 1] if i + 1 < len(phases) else 'done'}' 恢复", flush=True)
                return results

            if phase_result.get("needs_poll"):
                results["poll_info"] = phase_result
                results["status"] = "needs_poll"
                results["paused_after"] = phase_name
                results["next_phase"] = phases[i + 1] if i + 1 < len(phases) else None
                results["ok"] = True  # 不是失败，是暂停
                bg_pid = phase_result.get("bg_pid", "?")
                timeout = phase_result.get("timeout", 900)
                print(f"  ⏸ needs_poll — 后台子进程 PID={bg_pid} 执行中 ({phase_name})", flush=True)
                print(f"    用 scripts/heavy_phase_bg.py poll_heavy_phase() 或 start_phase='{phases[i + 1] if i + 1 < len(phases) else 'done'}' 恢复", flush=True)
                return results

            if phase_result.get("ok") is False:
                results["ok"] = False
                results["failed_phase"] = phase_name
                return results
        results["ok"] = True
        return results

    def _write_phase_state(self, workspace: JobWorkspace, phase_name: str,
                           phase_result: dict[str, Any]):
        """Append a phase result summary to the workspace state dir."""
        state_file = workspace.state_dir / f"{phase_name}.json"
        import json
        state_file.write_text(
            json.dumps(phase_result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
