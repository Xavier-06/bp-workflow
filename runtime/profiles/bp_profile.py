from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from runtime.profiles.base import JobContext, PipelineProfile


def _task_dir(runtime_root: Path, job_ctx: JobContext) -> Path:
    workspace = getattr(job_ctx, "workspace", None)
    if workspace is not None:
        task_dir = workspace.root
    else:
        task_dir = runtime_root / "tasks" / job_ctx.job_id
        task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir


def _outputs_dir(runtime_root: Path, job_ctx: JobContext) -> Path:
    workspace = getattr(job_ctx, "workspace", None)
    if workspace is not None:
        return workspace.outputs_dir
    task_dir = _task_dir(runtime_root, job_ctx)
    task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir


def _run_python_script(runtime_root: Path, script_name: str, *args: str) -> subprocess.CompletedProcess[str]:
    script_path = runtime_root / "scripts" / script_name
    cmd = [sys.executable, str(script_path), *args]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(runtime_root), timeout=1800)


def _not_implemented_phase(phase: str, reason: str, *, result_key: str) -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "bp_placeholder",
        "phase": phase,
        "result": {
            result_key: "skipped",
            "reason": reason,
        },
    }


# ── Phase 0: 文档入库（OCR + 结构化抽取）──────────────

def _run_document_intake(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    from runtime.intake.bp_document_intake import run_document_intake

    metadata = job_ctx.metadata or {}
    input_file = metadata.get("input_file", "")
    if not input_file:
        return {
            "ok": False,
            "mode": "shared_kernel",
            "phase": "phase0_document_intake",
            "job_id": job_ctx.job_id,
            "error": "metadata.input_file 未提供",
        }
    return run_document_intake(job_ctx, input_file)


# ── Phase 0.5 / 1: 主体核验 + 预搜索 ────────────

def _run_company_verify(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    from scripts.bp_company_verify import run_company_verify

    return run_company_verify(job_ctx)


def _run_presearch(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    from scripts.bp_presearch import run_presearch

    return run_presearch(job_ctx)


# ── Phase 2: BP 子代理发射（4 维度）────────────────


def _dispatch_role_specs(task_dir: Path, profile: dict) -> list[dict[str, Any]]:
    presearch_files = sorted(str(p) for p in task_dir.glob("bp_presearch_step*.md"))
    return [
        {
            "role_name": "bp_团队与合规",
            "brief_key": "bp_团队与合规",
            "description": "维度1: 创始人履历验证 + 法律风险 + 行业口碑",
            "output_file": str(task_dir / "bp_phase2_team.md"),
            "key_inputs": {
                "company_name": profile.get("company_name", ""),
                "founders": profile.get("founders", []),
                "presearch_steps": presearch_files,
            },
        },
        {
            "role_name": "bp_技术与产品",
            "brief_key": "bp_技术与产品",
            "description": "维度2+3: 技术路线祛魅 + 产品买家秀",
            "output_file": str(task_dir / "bp_phase2_tech.md"),
            "key_inputs": {
                "company_name": profile.get("company_name", ""),
                "products": profile.get("products", []),
                "tech_keywords": profile.get("tech_keywords", []),
                "presearch_steps": [f for f in presearch_files if "tech" in Path(f).name],
            },
        },
        {
            "role_name": "bp_行业与供应链",
            "brief_key": "bp_行业与供应链",
            "description": "维度4+5: 产业趋势冷思考 + 产业链控制力",
            "output_file": str(task_dir / "bp_phase2_industry.md"),
            "key_inputs": {
                "company_name": profile.get("company_name", ""),
                "presearch_steps": [f for f in presearch_files if "industry" in Path(f).name],
            },
        },
        {
            "role_name": "bp_竞争与结论",
            "brief_key": "bp_竞争与结论",
            "description": "维度6 + Deal Breakers: 竞争格局 + 投资结论",
            "output_file": str(task_dir / "bp_phase2_competition.md"),
            "key_inputs": {
                "company_name": profile.get("company_name", ""),
                "competitors": profile.get("competitors", {}),
                "presearch_steps": [
                    f for f in presearch_files if any(k in Path(f).name for k in ("competition", "moat"))
                ],
            },
        },
    ]


def _quality_check(output_path: Path) -> dict[str, Any]:
    """对子代理输出做质量评分。"""
    text = output_path.read_text(encoding="utf-8")
    urls = text.count("http")
    sections = text.count("## ")
    content_len = len(text)
    score = 0
    if content_len >= 6000:
        score = 5
    elif content_len >= 3000:
        score = 3
    elif content_len >= 1000:
        score = 2
    elif content_len >= 500:
        score = 1
    if urls < 2:
        score = max(0, score - 1)
    if sections < 3:
        score = max(0, score - 1)
    return {
        "score": score,
        "content_length": content_len,
        "url_count": urls,
        "section_count": sections,
        "verdict": "pass" if score >= 3 else "fail",
    }


# 前 3 个维度（不含竞争与结论）
_CORE_ROLES = ["bp_团队与合规", "bp_技术与产品", "bp_行业与供应链"]


def _run_bp_dispatch_prepare(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """Phase 2a: 写 manifest + brief，返回 needs_dispatch 让主 AI 自动派发前 3 个维度子代理。"""
    from scripts.bp_subagent_launcher_wb import _spawn_one

    task_dir = _task_dir(runtime_root, job_ctx)
    outputs_dir = _outputs_dir(runtime_root, job_ctx)

    profile_path = task_dir / "bp_step0_profile.json"
    profile: dict[str, Any] = {}
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            profile = {}

    all_subs = _dispatch_role_specs(task_dir, profile)
    for sub in all_subs:
        sub["output_file"] = str(outputs_dir / Path(sub["output_file"]).name)

    # 只派发前 3 个维度
    core_subs = [s for s in all_subs if s["role_name"] in _CORE_ROLES]

    dispatch_data = {
        "task_id": job_ctx.job_id,
        "phase": "2a",
        "status": "pending",
        "total_subagents": len(all_subs),
        "subagents": all_subs,
        "core_subagents": [s["role_name"] for s in core_subs],
        "deferred_subagents": ["bp_竞争与结论"],
        "briefs_ready": True,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    dispatch_path = task_dir / "phase2_dispatch.json"
    dispatch_path.write_text(json.dumps(dispatch_data, ensure_ascii=False, indent=2), encoding="utf-8")

    results = []
    manifests = []
    for sub in core_subs:
        try:
            result = _spawn_one(job_ctx.job_id, sub, task_dir=task_dir)
            results.append(result)
            if result.get("manifest_path"):
                manifests.append(result["manifest_path"])
        except Exception as exc:
            results.append({"role": sub["role_name"], "status": "spawn_failed", "error": str(exc)})

    return {
        "ok": True,
        "needs_dispatch": True,
        "mode": "bp_dispatch_prepare",
        "phase": "phase2_dispatch_prepare",
        "job_id": job_ctx.job_id,
        "dispatch_info": {
            "manifests": manifests,
            "roles": [s["role_name"] for s in core_subs],
            "dispatch_path": str(dispatch_path),
            "task_dir": str(task_dir),
            "outputs_dir": str(outputs_dir),
        },
        "result": {
            "dispatched": len(manifests),
            "total_core": len(core_subs),
            "manifests": manifests,
        },
    }


def _run_bp_dispatch_collect(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """Phase 2b: 检查前 3 个维度子代理输出是否已完成。"""
    task_dir = _task_dir(runtime_root, job_ctx)
    outputs_dir = _outputs_dir(runtime_root, job_ctx)

    step_quality: dict[str, dict] = {}
    completed = []
    missing = []

    for role in _CORE_ROLES:
        slug = {"bp_团队与合规": "team", "bp_技术与产品": "tech", "bp_行业与供应链": "industry"}[role]
        output_path = outputs_dir / f"bp_phase2_{slug}.md"
        if output_path.exists() and output_path.stat().st_size > 100:
            completed.append(role)
            step_quality[role] = _quality_check(output_path)
            print(f"    ✅ {role}: {step_quality[role]['content_length']} chars, score={step_quality[role]['score']}", flush=True)
        else:
            missing.append(role)

    if outputs_dir != task_dir:
        for slug in ("team", "tech", "industry"):
            src = outputs_dir / f"bp_phase2_{slug}.md"
            dst = task_dir / f"bp_phase2_{slug}.md"
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)

    return {
        "ok": len(missing) == 0,
        "mode": "bp_dispatch_collect",
        "phase": "phase2_dispatch_collect",
        "job_id": job_ctx.job_id,
        "result": {
            "completed": len(completed),
            "total_core": len(_CORE_ROLES),
            "missing": missing,
            "step_quality": step_quality,
        },
    }


def _run_bp_competition_prepare(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """Phase 2.5a: 竞争与结论子代理 — 在前 3 维度完成后派发，返回 needs_dispatch。"""
    from scripts.bp_subagent_launcher_wb import _spawn_one

    task_dir = _task_dir(runtime_root, job_ctx)
    outputs_dir = _outputs_dir(runtime_root, job_ctx)

    profile_path = task_dir / "bp_step0_profile.json"
    profile: dict[str, Any] = {}
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            profile = {}

    all_subs = _dispatch_role_specs(task_dir, profile)
    comp_sub = next((s for s in all_subs if s["role_name"] == "bp_竞争与结论"), None)
    if comp_sub is None:
        return {"ok": False, "error": "bp_竞争与结论 role spec not found"}

    comp_sub["output_file"] = str(outputs_dir / Path(comp_sub["output_file"]).name)

    # 把前 3 维度输出加入 key_inputs，让竞争与结论能参考
    prior_outputs = {}
    for slug in ("team", "tech", "industry"):
        p = outputs_dir / f"bp_phase2_{slug}.md"
        if not p.exists():
            p = task_dir / f"bp_phase2_{slug}.md"
        if p.exists():
            prior_outputs[slug] = str(p)
    comp_sub["key_inputs"]["prior_dimension_outputs"] = prior_outputs

    try:
        result = _spawn_one(job_ctx.job_id, comp_sub, task_dir=task_dir)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "needs_dispatch": True,
        "mode": "bp_competition_prepare",
        "phase": "phase25_competition_prepare",
        "job_id": job_ctx.job_id,
        "dispatch_info": {
            "manifests": [result.get("manifest_path", "")] if result.get("manifest_path") else [],
            "roles": ["bp_竞争与结论"],
            "task_dir": str(task_dir),
            "outputs_dir": str(outputs_dir),
        },
        "result": result,
    }


def _run_bp_competition_collect(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """Phase 2.5b: 检查竞争与结论输出。"""
    task_dir = _task_dir(runtime_root, job_ctx)
    outputs_dir = _outputs_dir(runtime_root, job_ctx)

    output_path = outputs_dir / "bp_phase2_competition.md"
    if output_path.exists() and output_path.stat().st_size > 100:
        quality = _quality_check(output_path)
        print(f"    ✅ bp_竞争与结论: {quality['content_length']} chars, score={quality['score']}", flush=True)
        if outputs_dir != task_dir:
            dst = task_dir / "bp_phase2_competition.md"
            if not dst.exists():
                shutil.copy2(output_path, dst)
        return {
            "ok": True,
            "mode": "bp_competition_collect",
            "phase": "phase25_competition_collect",
            "job_id": job_ctx.job_id,
            "result": {"quality": quality},
        }

    return {
        "ok": False,
        "mode": "bp_competition_collect",
        "phase": "phase25_competition_collect",
        "job_id": job_ctx.job_id,
        "result": {"missing": "bp_phase2_competition.md"},
    }


# ── Phase 3a: BP 统稿（投研逻辑重组 + 执行摘要）──────────

def _run_bp_synthesis_prepare(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """Phase 3a: 准备统稿子代理 — 读四个维度输出，按投研逻辑重组。"""
    from scripts.bp_subagent_launcher_wb import _spawn_one

    task_dir = _task_dir(runtime_root, job_ctx)
    outputs_dir = _outputs_dir(runtime_root, job_ctx)

    # 检查四个维度输出是否齐全
    dim_files = {}
    for slug in ("team", "tech", "industry", "competition"):
        for d in (outputs_dir, task_dir):
            p = d / f"bp_phase2_{slug}.md"
            if p.exists() and p.stat().st_size > 100:
                dim_files[slug] = str(p)
                break

    if len(dim_files) < 4:
        missing = [s for s in ("team", "tech", "industry", "competition") if s not in dim_files]
        return {"ok": False, "error": f"统稿缺少维度输出: {missing}"}

    synthesis_output = outputs_dir / "bp_synthesis.md"
    # 也写一份到 task_dir
    synthesis_output_task = task_dir / "bp_synthesis.md"

    sub = {
        "role_name": "bp_统稿",
        "brief_key": "bp_统稿",
        "description": "将四个维度分析重组为投研逻辑结构的完整研究报告",
        "output_file": str(synthesis_output),
        "key_inputs": {
            "dimension_outputs": dim_files,
            "synthesis_output_copy": str(synthesis_output_task),
        },
    }

    # 写 manifest
    manifest_path = task_dir / "bp_phase3_manifest_synthesis.json"
    synthesis_system_prompt = (
        'You are the lead analyst at a top-tier VC firm. Your job is to synthesize four dimension '
        'reports into ONE coherent, professional investment research report — like what 悦享资本/红杉/高瓴 would produce. '
        'You have FULL read/write access to the workspace. '
        '\n\n'
        '## 你的任务\n'
        '读取四个维度分析报告（团队、技术、行业、竞争），重新组织为一份完整的投研报告。\n'
        '不是简单拼接——你要重新组织叙事逻辑，消除重复，补充交叉引用，写执行摘要。\n\n'
        '## ⚠️ 脚注规则（最高优先级！）\n'
        '这是用户最关心的问题之一，必须严格执行：\n'
        '- 子代理输出中的 [^N] 脚注标记**必须完整保留**，不得在统稿时丢弃\n'
        '- 统稿时如发现子代理输出缺少脚注，必须自行补上：正文中每个关键定量数据后加 [^N] 标记\n'
        '- 关键定量数据 = 市场规模、营收、增速、估值、PS/PE 倍数、专利数、员工数、市占率、毛利率等任何带数字的关键断言\n'
        '- 报告末尾必须放"来源与参考"章节，将 [^N] 展开为完整来源信息（来源名+URL+日期）\n'
        '- 脚注编号统一重新编排（从 [^1] 开始连续编号），保证不冲突\n'
        '- **绝对不能只在末尾堆来源表而不在正文引用**——正文中没有 [^N] 的数据等于没有来源\n\n'
        '## 技术原理深写规则\n'
        '- **技术原理必须给外行讲透**：不要假设读者懂行业术语。每个核心概念先用大白话解释"这东西到底在干什么"，再给技术细节\n'
        '- 例如：不要只写"采用 RHBD 设计加固"，要解释"RHBD 就是在标准芯片上通过电路设计（如三重冗余投票）来抵抗太空辐射干扰，不需要特殊工艺线，成本较低但抗辐照能力有上限"\n'
        '- 读者看完技术原理部分后，应该不需要再去搜索外部资料就能理解\n\n'
        '## 专利精简规则\n'
        '- 如果技术维度报告列了大量专利，只保留核心专利（≤5项），其余改为概括性描述\n'
        '- 例如："另有 18 项专利覆盖设计加固细节和测试方法，详见知识产权附录"\n'
        '- 不要全量堆砌专利列表\n\n'
        '## 技术壁垒量化评估（必须独立成节）\n'
        '- 读者看完报告后必须能明确回答三个问题：\n'
        '  ① 壁垒到底有多高？（专利数vs竞品、认证周期、客户转换成本、人才稀缺度，每个都要有数字）\n'
        '  ② 技术到底实不实用？（量产状态、真实客户是谁、收入贡献占比，不能只写"有应用前景"）\n'
        '  ③ 到底能赚多少钱？（市场规模×渗透率×毛利率估算，给出具体数字区间）\n'
        '- 每个判断都要有数据支撑和 [^N] 脚注\n\n'
        '## 输出结构（严格按此顺序）\n'
        '# 一、执行摘要\n'
        '一页纸讲清核心判断。分四段：技术层面、市场层面、竞争层面、拓展层面。\n'
        '每段 3-5 句话，必须有具体数据。这是整篇报告最重要的部分。\n\n'
        '# 二、技术原理深度分析\n'
        '从技术维度报告中提取，补充技术路线对比表、核心组件拆解表。\n'
        '技术原理必须给外行讲透，不能只有术语没有解释。专利只保留核心≤5项，不堆砌。\n\n'
        '# 二.5、技术壁垒量化评估\n'
        '独立成节。必须回答：①壁垒多高？②实用性多强？③能赚多少钱？\n'
        '每个判断配具体数字和[^N]脚注。\n\n'
        '# 三、技术在目标场景中的独特价值与痛点解决\n'
        '按场景拆分，每个场景列具体痛点+数据+方案如何解决。\n\n'
        '# 四、现有方案深度对比\n'
        '大对比表（横向对比 8-10 个维度），含价格。\n\n'
        '# 五、市场现有厂商情况\n'
        '全球+国内厂商对比表，竞争格局判断。\n\n'
        '# 六、市场规模独立推算\n'
        '必须有分场景推算表和汇总表。\n\n'
        '# 七、民用场景与产品拓展\n'
        '按时间线分梯队（1-3年/3-5年/5-10年+），每个场景评可行性星级。\n\n'
        '# 八、BP核心逻辑独立验证\n'
        '逐条验证 BP 声称，给评级（✓成立/⚠部分成立/✗不成立）。用表格呈现。\n\n'
        '# 九、风险因素\n'
        '按类别分：技术/市场/竞争/政策/经营。每条风险要具体。\n\n'
        '# 十、综合结论与建议\n'
        '核心判断（2-3段）+ 投资建议（是否进入尽调+尽调重点清单）+ 估值建议。\n\n'
        '# 来源与参考\n'
        '将正文中所有 [^N] 脚注展开为完整来源信息，格式：[^N] 来源名称 — URL (日期)\n\n'
        '## 写作规范\n'
        '- 用中文写作，语言专业但不晦涩\n'
        '- 表格是核心信息载体，至少 8 个表格\n'
        '- 来源只列外部 URL，不要列内部文件路径\n'
        '- 禁止内部术语：子代理、dispatch、Phase、handoff、Step、manifest、spawn\n'
        '- 不要写"根据团队维度报告"这种话，直接呈现分析结论\n'
        '- 输出写入指定的 output file，同时复制一份到 synthesis_output_copy 路径\n'
    )

    manifest_data = {
        "task_id": job_ctx.job_id,
        "role": "bp_统稿",
        "slug": "synthesis",
        "label": f"{job_ctx.job_id}-bp-phase3-synthesis",
        "system_prompt": synthesis_system_prompt,
        "brief_path": "",
        "output_path": str(synthesis_output),
        "output_copy_path": str(synthesis_output_task),
        "dimension_files": dim_files,
        "timeout": 1800,
        "thinking": "high",
        "dispatch_mode": "team_async",
        "mode": "bypassPermissions",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "pending",
    }
    manifest_path.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "needs_dispatch": True,
        "mode": "bp_synthesis_prepare",
        "phase": "phase3_synthesis_prepare",
        "job_id": job_ctx.job_id,
        "dispatch_info": {
            "manifests": [str(manifest_path)],
            "roles": ["bp_统稿"],
            "task_dir": str(task_dir),
            "outputs_dir": str(outputs_dir),
        },
        "result": {
            "manifest_path": str(manifest_path),
            "dimension_files": dim_files,
        },
    }


def _run_bp_synthesis_collect(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """Phase 3a collect: 检查统稿输出是否完成。"""
    task_dir = _task_dir(runtime_root, job_ctx)
    outputs_dir = _outputs_dir(runtime_root, job_ctx)

    # 检查两个可能的位置
    for d in (outputs_dir, task_dir):
        synthesis_path = d / "bp_synthesis.md"
        if synthesis_path.exists() and synthesis_path.stat().st_size > 2000:
            quality = _quality_check(synthesis_path)
            print(f"    ✅ bp_统稿: {quality['content_length']} chars, score={quality['score']}", flush=True)
            # 确保两个位置都有
            if outputs_dir != task_dir:
                for src_dir, dst_dir in [(outputs_dir, task_dir), (task_dir, outputs_dir)]:
                    src = src_dir / "bp_synthesis.md"
                    dst = dst_dir / "bp_synthesis.md"
                    if src.exists() and not dst.exists():
                        shutil.copy2(src, dst)
            return {
                "ok": True,
                "mode": "bp_synthesis_collect",
                "phase": "phase3_synthesis_collect",
                "job_id": job_ctx.job_id,
                "result": {"quality": quality},
            }

    return {
        "ok": False,
        "mode": "bp_synthesis_collect",
        "phase": "phase3_synthesis_collect",
        "job_id": job_ctx.job_id,
        "result": {"missing": "bp_synthesis.md"},
    }


# ── Phase 3b: BP 交付 ──────────────────────────────────


def _run_bp_delivery(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    task_dir = _task_dir(runtime_root, job_ctx)
    workspace = getattr(job_ctx, "workspace", None)
    delivery_dir = workspace.delivery_dir if workspace is not None else task_dir
    outputs_dir = _outputs_dir(runtime_root, job_ctx)

    # 优先使用统稿输出（投研逻辑结构），fallback 到四个维度原文
    synthesis_path = None
    for d in (outputs_dir, task_dir):
        p = d / "bp_synthesis.md"
        if p.exists() and p.stat().st_size > 2000:
            synthesis_path = p
            break

    use_synthesis = synthesis_path is not None

    dimension_outputs: dict[str, str] = {}
    if use_synthesis:
        # 统稿模式：整篇报告作为一个整体
        dimension_outputs["synthesis"] = synthesis_path.read_text(encoding="utf-8")
    else:
        # Fallback：四个维度原文
        file_map = {
            "team": task_dir / "bp_phase2_team.md",
            "tech": task_dir / "bp_phase2_tech.md",
            "industry": task_dir / "bp_phase2_industry.md",
            "competition": task_dir / "bp_phase2_competition.md",
        }
        for slug, output_path in file_map.items():
            if output_path.exists():
                dimension_outputs[slug] = output_path.read_text(encoding="utf-8")

    delivery_errors = []

    docx_path = ""
    if dimension_outputs:
        try:
            from scripts.build_bp_dd_report_docx import build_bp_dd_report

            output_path = delivery_dir / f"{job_ctx.job_id}_bp_dd_report.docx"
            result_path = build_bp_dd_report(
                task_id=job_ctx.job_id,
                entity=job_ctx.entity,
                dimension_outputs=dimension_outputs,
                output_path=str(output_path),
            )
            docx_path = str(result_path)
        except Exception as exc:
            delivery_errors.append(f"DOCX 生成失败: {exc}")
    else:
        delivery_errors.append("无可用的维度输出或统稿输出")

    audit_path = delivery_dir / "bp_delivery_audit.json"
    audit_data = {
        "job_id": job_ctx.job_id,
        "entity": job_ctx.entity,
        "mode": "synthesis" if use_synthesis else "dimension_fallback",
        "dimensions_completed": list(dimension_outputs.keys()),
        "gate_verdict": "PASS" if docx_path else "PARTIAL",
        "audit_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    audit_path.write_text(json.dumps(audit_data, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        from runtime.orchestrator.state_store import StateStore

        ss = StateStore(runtime_root)
        if docx_path:
            ss.record_artifact(job_ctx.job_id, "bp_dd_report", Path(docx_path))
        ss.record_artifact(job_ctx.job_id, "bp_delivery_audit", audit_path)
    except Exception:
        pass

    # 微信通知（三步发送：文本→文件→确认，失败自动重试1次）
    # ⚠️ iLink SDK context_token 过期时 ret=-2 但不抛异常，需检查 file_sent 字段
    wechat_result = None
    if docx_path:
        for attempt in range(2):
            try:
                sys.path.insert(0, str(runtime_root))
                from scripts.longshao_notify import notify_bp_report
                
                dimension_count = len(dimension_outputs)
                total_dimensions = len(file_map) if 'file_map' in dir() else dimension_count
                
                result = notify_bp_report(
                    task_id=job_ctx.job_id,
                    docx_path=docx_path,
                    dimension_count=dimension_count,
                    total=total_dimensions,
                )
                wechat_result = result
                # 检查文件是否真正发送成功（file_sent=False 说明 context_token 可能过期）
                if result.get('ok') and result.get('file_sent', True):
                    break
                if result.get('ok') and not result.get('file_sent', True):
                    print(f"  ⚠ 微信文本通知成功但文件发送可能失败（context_token 可能过期），请检查微信", flush=True)
                    break
                if attempt == 0:
                    print(f"  ⚠ 微信通知第{attempt+1}次失败: {result.get('msg', '未知错误')}，重试中...", flush=True)
            except Exception as e:
                if attempt == 0:
                    print(f"  ⚠ 微信通知第{attempt+1}次异常: {e}，重试中...", flush=True)

    dimensions_total = len(file_map) if 'file_map' in dir() else len(dimension_outputs)
    return {
        "ok": bool(docx_path),
        "mode": "bp_delivery_minimal",
        "phase": "phase3_delivery",
        "job_id": job_ctx.job_id,
        "deliver_to_user": True if docx_path else False,
        "result": {
            "dimensions_completed": len(dimension_outputs),
            "dimensions_total": dimensions_total,
            "docx_path": str(docx_path),
            "audit_path": str(audit_path),
            "delivery_errors": delivery_errors,
            "gate_verdict": "PASS" if docx_path else "PARTIAL",
        },
    }


class BPProfile(PipelineProfile):
    def __init__(self, runtime_root: Path):
        super().__init__(
            name="bp",
            job_type="business_plan_dd",
            phase_handlers={
                "phase0_document_intake": lambda job_ctx: _run_document_intake(runtime_root, job_ctx),
                "phase05_company_verify": lambda job_ctx: _run_company_verify(runtime_root, job_ctx),
                "phase1_presearch": lambda job_ctx: _run_presearch(runtime_root, job_ctx),
                "phase2_dispatch_prepare": lambda job_ctx: _run_bp_dispatch_prepare(runtime_root, job_ctx),
                "phase2_dispatch_collect": lambda job_ctx: _run_bp_dispatch_collect(runtime_root, job_ctx),
                "phase25_competition_prepare": lambda job_ctx: _run_bp_competition_prepare(runtime_root, job_ctx),
                "phase25_competition_collect": lambda job_ctx: _run_bp_competition_collect(runtime_root, job_ctx),
                "phase3_synthesis_prepare": lambda job_ctx: _run_bp_synthesis_prepare(runtime_root, job_ctx),
                "phase3_synthesis_collect": lambda job_ctx: _run_bp_synthesis_collect(runtime_root, job_ctx),
                "phase3_delivery": lambda job_ctx: _run_bp_delivery(runtime_root, job_ctx),
            },
        )
        self.runtime_root = runtime_root
