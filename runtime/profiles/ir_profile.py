from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from runtime.profiles.base import JobContext, PipelineProfile


def _not_implemented_phase(name: str):
    def _runner(job_ctx: JobContext) -> dict[str, Any]:
        return {
            "ok": True,
            "mode": "skeleton",
            "phase": name,
            "job_id": job_ctx.job_id,
        }
    return _runner


def _workspace_for(job_ctx: JobContext):
    """Get JobWorkspace from context (injected by kernel)."""
    return job_ctx.workspace


def _sync_step_to_workspace(job_ctx: JobContext, step_name: str, output_path: Path):
    """Copy a completed step output file into the workspace outputs dir.

    Keeps the legacy path intact while also populating the workspace.
    """
    ws = _workspace_for(job_ctx)
    if ws is None or not output_path.exists():
        return
    dest = ws.outputs_dir / f"{step_name}.md"
    try:
        shutil.copy2(output_path, dest)
    except Exception:
        pass


def _sync_artifact_to_workspace(job_ctx: JobContext, artifact_type: str, src_path: Path):
    """Copy a delivery artifact into the workspace delivery dir and record it."""
    ws = _workspace_for(job_ctx)
    if ws is None or not src_path.exists():
        return
    dest = ws.delivery_dir / src_path.name
    try:
        shutil.copy2(src_path, dest)
        # Record artifact
        manifest_path = ws.state_dir / "artifacts.json"
        artifacts = {}
        if manifest_path.exists():
            try:
                artifacts = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        artifacts[artifact_type] = {
            "path": str(dest),
            "original_path": str(src_path),
            "recorded_at": time.time(),
        }
        manifest_path.write_text(
            json.dumps(artifacts, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# Phase 0-3: Research chain (unchanged, now with workspace sync)
# ═══════════════════════════════════════════════════════════

def _run_preflight(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    from scripts.ir_preflight_check import run_preflight

    metadata = job_ctx.metadata or {}
    result = run_preflight(
        job_ctx.job_id,
        entity=job_ctx.entity,
        query=job_ctx.query,
        market=job_ctx.market,
    )
    return {
        "ok": bool(result.get("passed", False)),
        "mode": "legacy_wrapped",
        "phase": "phase0_preflight",
        "job_id": job_ctx.job_id,
        "result": result,
        "metadata_used": {
            "entity": job_ctx.entity,
            "query": job_ctx.query,
            "market": job_ctx.market,
            "ticker": metadata.get("ticker", ""),
            "english_name": metadata.get("english_name", ""),
        },
    }


def _run_company_verify(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    if os.environ.get("IRBP_BG_CHILD") == "1":
        from scripts.ir_company_verify import run as run_company_verify
        result = run_company_verify(
            task_id=job_ctx.job_id,
            entity=job_ctx.entity,
            market=job_ctx.market,
        )
        return {
            "ok": "error" not in result,
            "mode": "legacy_wrapped",
            "phase": "phase05_company_verify",
            "job_id": job_ctx.job_id,
            "result": result,
        }
    from scripts.heavy_phase_bg import check_cached_result, launch_heavy_phase
    cached = check_cached_result(runtime_root, job_ctx.job_id, "phase05_company_verify")
    if cached is not None:
        print(f"  📦 [ir] 使用缓存的 company_verify 结果", flush=True)
        return cached
    return launch_heavy_phase(runtime_root, job_ctx, "phase05_company_verify", pipeline="ir")


def _run_presearch(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    if os.environ.get("IRBP_BG_CHILD") == "1":
        return _run_presearch_inner(runtime_root, job_ctx)
    from scripts.heavy_phase_bg import check_cached_result, launch_heavy_phase
    cached = check_cached_result(runtime_root, job_ctx.job_id, "phase1_presearch")
    if cached is not None:
        print(f"  📦 [ir] 使用缓存的 presearch 结果", flush=True)
        return cached
    return launch_heavy_phase(runtime_root, job_ctx, "phase1_presearch", pipeline="ir")


def _run_presearch_inner(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """presearch 实际执行逻辑（子进程内直接调用）"""
    from scripts.ir_presearch import run_presearch

    metadata = job_ctx.metadata or {}
    ticker = metadata.get("ticker", "")
    english_name = metadata.get("english_name", "")

    # 自动解析 ticker 和英文名（如果 submit 时没传）
    if not ticker:
        try:
            from tasks.valuation_enricher import _resolve_ticker, _CN_TO_EN_SEARCH
            resolved = _resolve_ticker(job_ctx.entity)
            if resolved:
                ticker = resolved
                print(f"  🔍 自动解析 ticker: {job_ctx.entity} → {ticker}", flush=True)
            if not english_name:
                english_name = _CN_TO_EN_SEARCH.get(job_ctx.entity, "")
                if english_name:
                    print(f"  🔍 自动解析英文名: {job_ctx.entity} → {english_name}", flush=True)
        except Exception:
            pass

    result = run_presearch(
        task_id=job_ctx.job_id,
        entity=job_ctx.entity,
        market=job_ctx.market,
        ticker=ticker,
        english_name=english_name,
    )
    return {
        "ok": True,
        "mode": "legacy_wrapped",
        "phase": "phase1_presearch",
        "job_id": job_ctx.job_id,
        "result": result,
        "query_context": {
            "ticker": ticker,
            "english_name": english_name,
        },
    }


def _run_extract(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    from scripts.ir_extract_content import extract_from_presearch

    metadata = job_ctx.metadata or {}
    max_pages = metadata.get("max_extract_pages", 15)
    result = extract_from_presearch(
        task_id=job_ctx.job_id,
        entity=job_ctx.entity,
        max_pages=max_pages,
    )
    ok_count = result.get("ok_count", 0)
    total = result.get("total_urls", 0)

    # Sync extraction results to workspace
    ws = _workspace_for(job_ctx)
    if ws is not None:
        try:
            extract_facts = runtime_root / "data" / "tasks" / f"{job_ctx.job_id}_body_content" / "ir_extracted_facts.json"
            if extract_facts.exists():
                shutil.copy2(extract_facts, ws.extraction_dir / "ir_extracted_facts.json")
        except Exception:
            pass

    return {
        "ok": ok_count > 0,
        "mode": "legacy_wrapped",
        "phase": "phase15_extract",
        "job_id": job_ctx.job_id,
        "result": {
            "total_urls": total,
            "ok_count": ok_count,
            "agg_entities": result.get("agg_entities", []),
            "agg_financials": result.get("agg_financials", []),
            "agg_events": result.get("agg_events", []),
            "agg_risks": result.get("agg_risks", []),
            "agg_valuation_views": result.get("agg_valuation_views", []),
        },
    }


# ═══════════════════════════════════════════════════════════
# Phase 1.2: Precompute — 三大预计算引擎（财务指标/技术指标/行业对标）
# ═══════════════════════════════════════════════════════════

def _run_precompute(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """Phase 1.2: 运行三大预计算引擎（财务指标 / 技术指标 / 行业对标）。

    输出写入 data/tasks/ 供子代理（step0_tech/step4_finance/step6b_valuation 等）使用。
    预计算引擎需要股票代码（ticker），如果 metadata 没有则尝试解析。
    """
    import subprocess

    metadata = job_ctx.metadata or {}
    ticker = metadata.get("ticker", "")
    market = metadata.get("market", job_ctx.market)

    # 如果没有 ticker，尝试解析
    if not ticker:
        try:
            from tasks.valuation_enricher import _resolve_ticker
            ticker = _resolve_ticker(job_ctx.entity)
            if ticker:
                print(f"  🔍 [precompute] 自动解析 ticker: {job_ctx.entity} → {ticker}", flush=True)
        except Exception:
            pass

    precompute_results: dict[str, Any] = {}
    all_ok = True
    errors: list[str] = []

    tasks_dir = runtime_root / "data" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    # 三个预计算引擎
    engines = {
        "financial_metrics": runtime_root / "scripts" / "financial_metrics_precompute.py",
        "technical_indicators": runtime_root / "scripts" / "technical_indicators.py",
        "sector_benchmarks": runtime_root / "scripts" / "sector_benchmarks.py",
    }

    for engine_name, script_path in engines.items():
        if not script_path.exists():
            errors.append(f"{engine_name}: script not found at {script_path}")
            all_ok = False
            continue

        try:
            # 没有 ticker 时跳过需要 ticker 的引擎
            if not ticker:
                precompute_results[engine_name] = {"status": "skipped", "reason": "no ticker available"}
                print(f"  ⚠️  [precompute] {engine_name}: 无 ticker，跳过", flush=True)
                continue

            print(f"  🔢 [precompute] 运行 {engine_name}...", flush=True)
            r = subprocess.run(
                ["python3", str(script_path), ticker, "--json"],
                capture_output=True, text=True, timeout=120,
            )

            if r.returncode != 0:
                error_msg = f"{engine_name}: exit {r.returncode}, stderr: {(r.stderr or '')[:200]}"
                errors.append(error_msg)
                print(f"  ⚠️  [precompute] {error_msg}", flush=True)
                precompute_results[engine_name] = {
                    "status": "error",
                    "error": error_msg,
                    "stdout": (r.stdout or "")[:500],
                }
                all_ok = False
                continue

            # 解析 JSON 输出
            try:
                output_data = json.loads(r.stdout.strip())
            except json.JSONDecodeError:
                output_data = {"raw": r.stdout.strip()}

            # 保存 JSON 输出到 data/tasks/
            output_file = tasks_dir / f"{job_ctx.job_id}_precompute_{engine_name}.json"
            output_file.write_text(
                json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # 同时保存 markdown 版本（可选，方便子代理阅读）
            try:
                r_md = subprocess.run(
                    ["python3", str(script_path), ticker, "--markdown"],
                    capture_output=True, text=True, timeout=60,
                )
                if r_md.returncode == 0:
                    md_file = tasks_dir / f"{job_ctx.job_id}_precompute_{engine_name}.md"
                    md_file.write_text(r_md.stdout, encoding="utf-8")
            except Exception:
                pass  # markdown 是可选的

            precompute_results[engine_name] = {
                "status": "ok",
                "output_file": str(output_file),
                "data": output_data,
            }
            print(f"  ✅ [precompute] {engine_name} 完成 → {output_file.name}", flush=True)

        except subprocess.TimeoutExpired:
            errors.append(f"{engine_name}: timeout (120s)")
            precompute_results[engine_name] = {"status": "timeout"}
            all_ok = False
        except Exception as e:
            errors.append(f"{engine_name}: {e}")
            precompute_results[engine_name] = {"status": "error", "error": str(e)}
            all_ok = False

    # 同步到 workspace outputs
    ws = _workspace_for(job_ctx)
    if ws is not None:
        try:
            for engine_name in engines:
                src = tasks_dir / f"{job_ctx.job_id}_precompute_{engine_name}.json"
                if src.exists():
                    shutil.copy2(src, ws.outputs_dir / f"precompute_{engine_name}.json")
                src_md = tasks_dir / f"{job_ctx.job_id}_precompute_{engine_name}.md"
                if src_md.exists():
                    shutil.copy2(src_md, ws.outputs_dir / f"precompute_{engine_name}.md")
        except Exception:
            pass

    return {
        "ok": all_ok,
        "mode": "precompute",
        "phase": "phase12_precompute",
        "job_id": job_ctx.job_id,
        "result": {
            "ticker": ticker,
            "market": market,
            "engines": precompute_results,
            "errors": errors,
            "output_dir": str(tasks_dir),
        },
    }


# ═══════════════════════════════════════════════════════════
# Phase 4: Dispatch — 拆成 prepare + collect，避免死锁
# ═══════════════════════════════════════════════════════════

def _run_dispatch_prepare(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """Phase 4a: 使用 launch_next_wave 发射第一个 wave，返回 needs_dispatch=True。

    Coordinator 读取返回的 task_tool_instructions 后用 team 异步模式派发子代理。
    后续 wave 由 Coordinator 循环调用 launch_next_wave() 推进。
    """
    from scripts.ir_subagent_launcher_wb import (
        launch_next_wave,
        get_pipeline_status,
        step_output_path,
        STEP_DEPS,
        LAUNCH_WAVES,
    )

    metadata = job_ctx.metadata or {}
    entity = job_ctx.entity
    market = metadata.get("market", job_ctx.market) if metadata else job_ctx.market

    # 发射当前 wave（自动检测已完成的 step，支持断点恢复）
    wave_result = launch_next_wave(
        task_id=job_ctx.job_id,
        entity=entity,
        query=job_ctx.query,
        market=market,
    )

    if wave_result.get('all_done'):
        # 所有 step 已完成（恢复场景），直接进 collect
        return {
            "ok": True,
            "needs_dispatch": False,
            "mode": "wave_orchestration",
            "phase": "phase4_dispatch_prepare",
            "job_id": job_ctx.job_id,
            "result": {
                "message": "All waves already completed, proceed to collect",
                "pipeline_status": get_pipeline_status(job_ctx.job_id),
            },
        }

    dispatched_count = wave_result.get('dispatched_count', 0)
    if dispatched_count == 0:
        return {
            "ok": False,
            "mode": "wave_orchestration",
            "phase": "phase4_dispatch_prepare",
            "job_id": job_ctx.job_id,
            "result": {"error": "No steps dispatched in wave", "wave_result": wave_result},
        }

    return {
        "ok": True,
        "needs_dispatch": True,
        "mode": "wave_orchestration",
        "phase": "phase4_dispatch_prepare",
        "job_id": job_ctx.job_id,
        "result": {
            "wave_index": wave_result.get('wave_index'),
            "wave_label": wave_result.get('wave_label'),
            "dispatched_count": dispatched_count,
            "task_tool_instructions": wave_result.get('task_tool_instructions', []),
            "after_all_tasks_complete": wave_result.get('after_all_tasks_complete'),
            "total_waves": len(LAUNCH_WAVES),
            "pipeline_status": get_pipeline_status(job_ctx.job_id),
        },
    }


def _run_dispatch_collect(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """Phase 4b: 检查子代理输出是否完成，做质量门禁。

    Coordinator 在所有 wave 的 task 子代理完成后调用此 phase。
    """
    from scripts.ir_subagent_launcher_wb import (
        check_step_quality,
        dispatch_rewrite,
        step_output_path,
        get_pipeline_status,
        STEP_DEPS,
    )

    metadata = job_ctx.metadata or {}
    entity = job_ctx.entity
    market = metadata.get("market", job_ctx.market) if metadata else job_ctx.market

    # 获取管线状态
    pipeline_status = get_pipeline_status(job_ctx.job_id)

    completed_steps: list[str] = []
    step_quality: dict[str, dict[str, Any]] = {}

    for step_name in STEP_DEPS:
        output_path = step_output_path(job_ctx.job_id, step_name)
        if output_path.exists() and output_path.stat().st_size > 100:
            completed_steps.append(step_name)
            _sync_step_to_workspace(job_ctx, step_name, output_path)
            quality = check_step_quality(job_ctx.job_id, step_name)
            step_quality[step_name] = quality

    total_expected = len(STEP_DEPS)
    completion_rate = len(completed_steps) / max(total_expected, 1)
    circuit_break = completion_rate < 0.5

    rewrite_dispatched: list[str] = []
    for step_name, quality in step_quality.items():
        if quality.get("verdict") == "fail" and quality.get("score", 0) > 0:
            try:
                rewrite_result = dispatch_rewrite(
                    job_ctx.job_id, step_name, entity, job_ctx.query, market
                )
                if rewrite_result.get("status") == "dispatched":
                    rewrite_dispatched.append(step_name)
            except Exception:
                pass

    return {
        "ok": not circuit_break,
        "mode": "wave_orchestration",
        "phase": "phase4_dispatch_collect",
        "job_id": job_ctx.job_id,
        "result": {
            "completed": len(completed_steps),
            "total_expected": total_expected,
            "completion_rate": round(completion_rate, 2),
            "circuit_break": circuit_break,
            "completed_steps": completed_steps,
            "step_quality": step_quality,
            "rewrite_dispatched": rewrite_dispatched,
            "pipeline_status": pipeline_status,
            "workspace_outputs_dir": str(_workspace_for(job_ctx).outputs_dir) if _workspace_for(job_ctx) else "",
        },
    }


# ═══════════════════════════════════════════════════════════
# Phase 5: Delivery — 对抗验证 + DOCX + 交付（workspace-aware）
# ═══════════════════════════════════════════════════════════

def _run_delivery(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    if os.environ.get("IRBP_BG_CHILD") == "1":
        return _run_delivery_inner(runtime_root, job_ctx)
    from scripts.heavy_phase_bg import check_cached_result, launch_heavy_phase
    cached = check_cached_result(runtime_root, job_ctx.job_id, "phase5_delivery")
    if cached is not None:
        print(f"  📦 [ir] 使用缓存的 delivery 结果", flush=True)
        return cached
    return launch_heavy_phase(runtime_root, job_ctx, "phase5_delivery", pipeline="ir")


def _run_delivery_inner(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """Phase 5: 对抗验证 + 审计 + DOCX + 交付（子进程内直接调用）。

    All artifacts are synced to workspace.delivery_dir.
    Legacy paths remain intact.
    """
    import subprocess
    from scripts.verification_agent import run_verification

    metadata = job_ctx.metadata or {}
    session_id = metadata.get("session_id", "")

    # 1. 对抗式验证
    verification = {}
    verification_path = ""
    try:
        verification = run_verification(task_id=job_ctx.job_id, pipeline="ir")
    except Exception as e:
        verification = {"verdict": "ERROR", "summary": str(e)}

    verification_verdict = verification.get("verdict", "UNKNOWN")

    # Sync verification to workspace
    ws = _workspace_for(job_ctx)
    if ws is not None:
        try:
            vdest = ws.verification_dir / "verification_result.json"
            vdest.write_text(
                json.dumps(verification, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            verification_path = str(vdest)
        except Exception:
            pass

    # 2. 来源审计 + 执行审计
    audits_ok = True
    audit_errors: list[str] = []
    audit_paths: dict[str, str] = {}
    for audit_script in ("build_ir_source_audit.py", "build_ir_execution_audit.py"):
        script_path = runtime_root / "scripts" / audit_script
        if script_path.exists():
            try:
                r = subprocess.run(
                    ["python3", str(script_path), job_ctx.job_id],
                    capture_output=True, text=True, timeout=120,
                )
                if r.returncode != 0:
                    audits_ok = False
                    audit_errors.append(f"{audit_script}: exit {r.returncode}")
                else:
                    # Try to parse output path from stdout
                    try:
                        payload = json.loads(r.stdout.strip())
                        audit_output = payload.get("output", "")
                        if audit_output and Path(audit_output).exists():
                            _sync_artifact_to_workspace(job_ctx, audit_script, Path(audit_output))
                            audit_paths[audit_script] = audit_output
                    except Exception:
                        pass
            except Exception as e:
                audits_ok = False
                audit_errors.append(f"{audit_script}: {e}")

    # 3. 生成券商风格 Word 报告
    docx_path = ""
    docx_error = ""
    build_docx_script = runtime_root / "scripts" / "build_ir_broker_report_docx.py"
    if build_docx_script.exists():
        try:
            r = subprocess.run(
                ["python3", str(build_docx_script), job_ctx.job_id],
                capture_output=True, text=True, timeout=180,
            )
            if r.returncode == 0:
                try:
                    payload = json.loads(r.stdout)
                    docx_path = payload.get("output", "")
                    if docx_path and Path(docx_path).exists():
                        _sync_artifact_to_workspace(job_ctx, "broker_report_docx", Path(docx_path))
                except Exception:
                    docx_path = ""
            else:
                docx_error = f"exit {r.returncode}: {r.stderr[:200]}"
        except Exception as e:
            docx_error = str(e)

    # 4. 交付通知 — 用 wechat-ilink-bot SDK 发送文件（三步发送：文本→文件→确认）
    # ⚠️ wechat_bot 装在 Python 3.14，系统 Python 3.9 找不到模块
    # 必须用 subprocess + Python 3.14 调用 longshao_notify.py CLI
    delivery_ok = False
    delivery_error = ""
    if docx_path:
        # 找 Python 3.14+（wechat_bot 所在环境）
        import shutil
        python314 = shutil.which("python3.14") or ""
        if not python314:
            import glob as _glob
            _candidates = sorted(_glob.glob("/opt/homebrew/Cellar/python@3.14/*/Frameworks/Python.framework/Versions/3.*/Resources/Python.app/Contents/MacOS/Python"), reverse=True)
            python314 = _candidates[0] if _candidates else ""
        notify_script = str(runtime_root / "scripts" / "longshao_notify.py")
        caption = f"🐲 龙少 — 研报交付通知\n📋 任务: {job_ctx.job_id}\n💬 研报已完成，请查收\n📄 文件: {Path(docx_path).name}"
        if python314:
            for attempt in range(2):
                try:
                    r = subprocess.run(
                        [python314, notify_script, "--file", str(docx_path), caption],
                        capture_output=True, text=True, cwd=str(runtime_root), timeout=120,
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        import json as _json
                        result = _json.loads(r.stdout.strip())
                        delivery_ok = result.get("ok", False)
                    else:
                        delivery_error = f"exit={r.returncode} stderr={r.stderr[:200]}"
                    if delivery_ok:
                        break
                    delivery_error = result.get("msg", "未知错误") if r.returncode == 0 else delivery_error
                    if attempt == 0:
                        print(f"  ⚠ 微信交付第{attempt+1}次失败: {delivery_error}，重试中...", flush=True)
                except Exception as e:
                    delivery_error = str(e)
                    if attempt == 0:
                        print(f"  ⚠ 微信交付第{attempt+1}次异常: {delivery_error}，重试中...", flush=True)
        else:
            delivery_error = "Python 3.14 not found, skipping WeChat delivery"
    else:
        delivery_error = "No docx_path, skipping delivery notification"

    # Collect workspace artifact summary
    workspace_artifacts = {}
    if ws is not None:
        artifacts_manifest = ws.state_dir / "artifacts.json"
        if artifacts_manifest.exists():
            try:
                workspace_artifacts = json.loads(artifacts_manifest.read_text(encoding="utf-8"))
            except Exception:
                pass

    return {
        "ok": True,
        "mode": "legacy_wrapped",
        "phase": "phase5_delivery",
        "job_id": job_ctx.job_id,
        "result": {
            "verification_verdict": verification_verdict,
            "verification_summary": verification.get("summary", ""),
            "verification_path": verification_path,
            "audits_ok": audits_ok,
            "audit_errors": audit_errors,
            "audit_paths": audit_paths,
            "docx_path": docx_path,
            "docx_error": docx_error,
            "delivery_ok": delivery_ok,
            "delivery_error": delivery_error,
            "delivery_quality": verification_verdict.lower() if verification_verdict != "ERROR" else "unknown",
            "workspace_artifacts": workspace_artifacts,
            "workspace_delivery_dir": str(ws.delivery_dir) if ws else "",
        },
    }


class IRProfile(PipelineProfile):
    def __init__(self, runtime_root: Path):
        super().__init__(
            name="ir",
            job_type="investment_research",
            phase_handlers={
                "phase0_preflight": lambda job_ctx: _run_preflight(runtime_root, job_ctx),
                "phase05_company_verify": lambda job_ctx: _run_company_verify(runtime_root, job_ctx),
                "phase1_presearch": lambda job_ctx: _run_presearch(runtime_root, job_ctx),
                "phase15_extract": lambda job_ctx: _run_extract(runtime_root, job_ctx),
                "phase12_precompute": lambda job_ctx: _run_precompute(runtime_root, job_ctx),
                "phase4_dispatch_prepare": lambda job_ctx: _run_dispatch_prepare(runtime_root, job_ctx),
                "phase4_dispatch_collect": lambda job_ctx: _run_dispatch_collect(runtime_root, job_ctx),
                "phase5_delivery": lambda job_ctx: _run_delivery(runtime_root, job_ctx),
            },
        )
        self.runtime_root = runtime_root
