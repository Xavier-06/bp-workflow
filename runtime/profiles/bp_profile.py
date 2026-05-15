from __future__ import annotations

import json
import os
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
    if os.environ.get("IRBP_BG_CHILD") == "1":
        # 当前是后台子进程，直接执行
        from scripts.bp_company_verify import run_company_verify
        return run_company_verify(job_ctx)
    from scripts.heavy_phase_bg import check_cached_result, launch_heavy_phase
    cached = check_cached_result(runtime_root, job_ctx.job_id, "phase05_company_verify")
    if cached is not None:
        print(f"  📦 [bp] 使用缓存的 company_verify 结果", flush=True)
        return cached
    return launch_heavy_phase(runtime_root, job_ctx, "phase05_company_verify", pipeline="bp")


def _run_presearch(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    if os.environ.get("IRBP_BG_CHILD") == "1":
        from scripts.bp_presearch import run_presearch
        return run_presearch(job_ctx)
    from scripts.heavy_phase_bg import check_cached_result, launch_heavy_phase
    cached = check_cached_result(runtime_root, job_ctx.job_id, "phase1_presearch")
    if cached is not None:
        print(f"  📦 [bp] 使用缓存的 presearch 结果", flush=True)
        return cached
    return launch_heavy_phase(runtime_root, job_ctx, "phase1_presearch", pipeline="bp")


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
            "role_name": "bp_估值",
            "brief_key": "bp_估值",
            "description": "维度6: 融资轮估值 + 可比公司估值 + 投资回报模型(MOIC/IRR) + 退出路径 + Excel估值模型",
            "output_file": str(task_dir / "bp_phase2_valuation.md"),
            "key_inputs": {
                "company_name": profile.get("company_name", ""),
                "financing_rounds": profile.get("financing_rounds", []),
                "competitors": profile.get("competitors", {}),
                "presearch_steps": [
                    f for f in presearch_files if any(k in Path(f).name for k in ("valuation", "finance", "competition"))
                ],
            },
        },
        {
            "role_name": "bp_竞争与结论",
            "brief_key": "bp_竞争与结论",
            "description": "维度7 + Deal Breakers: 竞争格局 + 投资结论",
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
    """对子代理输出做质量评分。v2: 增加来源充分性检查。"""
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

    # v2: 来源充分性检查
    # 统计不同域名的外部URL数量（去重）
    import re as _re
    unique_domains = set()
    for m in _re.finditer(r'https?://([a-zA-Z0-9.-]+)', text):
        unique_domains.add(m.group(1))
    domain_count = len(unique_domains)

    # 检查是否有"未经搜索验证"标注（说明搜索不足）
    unverified_count = text.count("未经搜索验证") + text.count("⚠ 未经搜索验证")

    # 来源充分性扣分
    if domain_count < 3:
        score = max(0, score - 1)  # 至少3个不同来源域名
    if unverified_count > 2:
        score = max(0, score - 1)  # 超过2处未经搜索验证的推断

    return {
        "score": score,
        "content_length": content_len,
        "url_count": urls,
        "unique_domain_count": domain_count,
        "unverified_count": unverified_count,
        "section_count": sections,
        "verdict": "pass" if score >= 3 else "fail",
    }


# 前 4 个维度（不含竞争与结论，竞争在 Wave 2 派发）
_CORE_ROLES = ["bp_团队与合规", "bp_技术与产品", "bp_行业与供应链", "bp_估值"]


def _run_bp_dispatch_prepare(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """Phase 2a: 写 manifest + brief，返回 needs_dispatch 让主 AI 自动派发前 4 个维度子代理。"""
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

    # 只派发前 4 个维度（竞争在 Wave 2）
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
        # ⚠️ 强制指令：主 AI 必须用 Agent 工具派发子代理，不能跳过直接轮询
        "instruction": "MANDATORY: Read manifests, then use Agent tool to spawn sub-agents for each dimension. Do NOT skip to polling output files.",
    }


def _run_bp_dispatch_collect(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """Phase 2b: 检查前 4 个维度子代理输出是否已完成。"""
    task_dir = _task_dir(runtime_root, job_ctx)
    outputs_dir = _outputs_dir(runtime_root, job_ctx)

    _ROLE_SLUGS = {
        "bp_团队与合规": "team",
        "bp_技术与产品": "tech",
        "bp_行业与供应链": "industry",
        "bp_估值": "valuation",
    }

    step_quality: dict[str, dict] = {}
    completed = []
    missing = []

    for role in _CORE_ROLES:
        slug = _ROLE_SLUGS[role]
        output_path = outputs_dir / f"bp_phase2_{slug}.md"
        if output_path.exists() and output_path.stat().st_size > 100:
            completed.append(role)
            step_quality[role] = _quality_check(output_path)
            print(f"    ✅ {role}: {step_quality[role]['content_length']} chars, score={step_quality[role]['score']}", flush=True)
        else:
            missing.append(role)

    if outputs_dir != task_dir:
        for slug in _ROLE_SLUGS.values():
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
    """Phase 2.5a: 竞争与结论子代理 — 在前 4 维度完成后派发，返回 needs_dispatch。"""
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

    # 把前 4 维度输出加入 key_inputs，让竞争与结论能参考
    prior_outputs = {}
    for slug in ("team", "tech", "industry", "valuation"):
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
        # ⚠️ 强制指令：主 AI 必须用 Agent 工具派发子代理，不能跳过直接轮询
        "instruction": "MANDATORY: Read the manifest, then use Agent tool to spawn sub-agent for bp_竞争与结论. Do NOT skip to polling output file.",
    }


def _run_bp_competition_collect(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """Phase 2.5b: 检查竞争与结论输出。

    防御逻辑：如果输出文件不存在，检查 spawn receipt 是否已生成。
    若 receipt 存在但子代理输出缺失，返回 needs_dispatch=True 强制主 AI 重新派发，
    而非默默返回 missing（防止主 AI 跳过派发直接轮询的 bug）。
    """
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

    # 输出缺失 — 检查 spawn receipt 判断是否需要重新派发
    spawn_receipt_path = task_dir / "bp_phase2_spawn_competition.json"
    spawn_dispatched = False
    if spawn_receipt_path.exists():
        try:
            receipt = json.loads(spawn_receipt_path.read_text(encoding="utf-8"))
            spawn_dispatched = receipt.get("status") == "dispatched"
        except Exception:
            pass

    if spawn_dispatched:
        # receipt 存在但输出缺失 = 子代理可能没被真正 spawn（主 AI 跳过了 Agent 调用）
        # 强制返回 needs_dispatch 让主 AI 重新派发
        print("    ⚠️ bp_竞争与结论: spawn receipt 存在但输出缺失，强制重新派发", flush=True)
        return {
            "ok": True,
            "needs_dispatch": True,
            "mode": "bp_competition_collect_redispatch",
            "phase": "phase25_competition_collect",
            "job_id": job_ctx.job_id,
            "dispatch_info": {
                "manifests": [str(task_dir / "bp_phase2_manifest_competition.json")]
                if (task_dir / "bp_phase2_manifest_competition.json").exists() else [],
                "roles": ["bp_竞争与结论"],
                "task_dir": str(task_dir),
                "outputs_dir": str(outputs_dir),
                "reason": "spawn receipt exists but output missing — sub-agent likely not actually dispatched",
            },
            "result": {"missing": "bp_phase2_competition.md", "redispatch": True},
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
    """Phase 3a: 准备统稿子代理 — 读五个维度输出，按投研逻辑重组。"""
    from scripts.bp_subagent_launcher_wb import _spawn_one

    task_dir = _task_dir(runtime_root, job_ctx)
    outputs_dir = _outputs_dir(runtime_root, job_ctx)

    # 检查五个维度输出是否齐全
    dim_files = {}
    for slug in ("team", "tech", "industry", "valuation", "competition"):
        for d in (outputs_dir, task_dir):
            p = d / f"bp_phase2_{slug}.md"
            if p.exists() and p.stat().st_size > 100:
                dim_files[slug] = str(p)
                break

    if len(dim_files) < 5:
        missing = [s for s in ("team", "tech", "industry", "valuation", "competition") if s not in dim_files]
        return {"ok": False, "error": f"统稿缺少维度输出: {missing}"}

    synthesis_output = outputs_dir / "bp_synthesis.md"
    # 也写一份到 task_dir
    synthesis_output_task = task_dir / "bp_synthesis.md"

    sub = {
        "role_name": "bp_统稿",
        "brief_key": "bp_统稿",
        "description": "将五个维度分析重组为投研逻辑结构的完整研究报告",
        "output_file": str(synthesis_output),
        "key_inputs": {
            "dimension_outputs": dim_files,
            "synthesis_output_copy": str(synthesis_output_task),
        },
    }

    # 写 manifest
    manifest_path = task_dir / "bp_phase3_manifest_synthesis.json"
    synthesis_system_prompt = (
        'You are the lead analyst at a top-tier VC firm. Your job is to synthesize five dimension '
        'reports into ONE coherent, professional investment research report — like what 悦享资本/红杉/高瓴 would produce. '
        'You have FULL read/write access to the workspace. '
        '\n\n'
        '## 你的任务\n'
        '读取五个维度分析报告（团队、技术、行业、估值、竞争），重新组织为一份完整的投研报告。\n'
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
        '# 一.五、公司主体与治理结构\n'
        '**从团队维度报告中提取，必须包含以下内容：**\n'
        '1. 公司基本信息（工商注册、法人、注册资本、成立时间）\n'
        '2. **完整股权架构图**（所有股东、持股比例、实际控制人穿透、员工持股平台）\n'
        '3. 核心团队深度分析（创始人/高管履历验证、对比表格）\n'
        '4. 顾问/外部资源网络\n'
        '5. 合规与风险信号（诉讼、处罚、资质缺失）\n'
        '6. 团队匹配度判断\n\n'
        '⚠️ **股权架构必须完整呈现**：不能只提两个大股东，所有股东（包括持股平台、产业基金、自然人）都要列出，持股比例和穿透关系要写清。\n'
        '⚠️ **子公司/分支机构必须列出**：全集团员工汇总，不能只看总公司。\n'
        '⚠️ **团队维度内容必须完整保留（铁律）**：团队维度子代理的全部输出必须完整纳入统稿，不得压缩为几句话概括。具体要求：\n'
        '  - **核心团队逐人履历验证**：每人一行（姓名/职务/BP声称/验证结果/验证等级），必须保留完整对比表格\n'
        '  - **核心人物深度画像**：每位核心成员的详细分析（优势/疑点/评估）必须保留，不得压缩\n'
        '  - **顾问/外部资源网络**：产学研合作、客户合作网络的完整分析必须保留\n'
        '  - **合规与风险信号**：诉讼排查、失信排查、行业资质、财务合规的完整分析必须保留\n'
        '  - **团队匹配度判断**：技术匹配/商业化能力/行业资源的多维评级必须保留\n'
        '  - **关键待验证事项清单**：10项待验证事项及建议验证方式必须完整保留\n'
        '  原因：团队是天使轮投资的核心判断维度，压缩后投资人无法评估团队可信度。\n\n'
        '# 二、产品矩阵深度拆解（必须独立成章，不是技术分析的子节）\n'
        '**这是整份报告的基础——读者必须先知道公司卖什么，再听技术逻辑。**\n\n'
        '1. **产品线总览表**：每条产品线一行（产品线名称/核心品类/技术平台/量产状态/目标市场/营收占比估算）\n'
        '2. **每条产品线逐一深度拆解**：\n'
        '   - 具体型号与核心参数表（型号/关键参数/封装形式/认证状态）\n'
        '   - 量产状态（已量产/投片验证/研发中）与产能情况\n'
        '   - 目标应用场景与典型客户（✓已量产/🔄导入中/❓未验证）\n'
        '   - 该产品线营收占比估算\n'
        '   - 与同类竞品的核心参数对比\n'
        '3. **产品线间协同关系**\n\n'
        '# 三、技术原理深度分析\n'
        '从技术维度报告中提取，补充技术路线对比表、核心组件拆解表。\n'
        '技术原理必须给外行讲透，不能只有术语没有解释。专利只保留核心≤5项，不堆砌。\n\n'
        '# 三.5、技术壁垒量化评估\n'
        '独立成节。必须回答：①壁垒多高？②实用性多强？③能赚多少钱？\n'
        '每个判断配具体数字和[^N]脚注。\n\n'
        '# 四、技术在目标场景中的独特价值与痛点解决\n'
        '按场景拆分，每个场景列具体痛点+数据+方案如何解决。\n\n'
        '# 五、现有方案深度对比\n'
        '大对比表（横向对比 8-10 个维度），含价格。\n\n'
        '# 六、市场现有厂商情况\n'
        '全球+国内厂商对比表，竞争格局判断。\n\n'
        '# 七、市场规模独立推算\n'
        '必须有分场景推算表和汇总表。\n\n'
        '# 八、民用场景与产品拓展\n'
        '按时间线分梯队（1-3年/3-5年/5-10年+），每个场景评可行性星级。\n\n'
        '# 九、BP核心逻辑独立验证\n'
        '逐条验证 BP 声称，给评级（✓成立/⚠部分成立/✗不成立）。用表格呈现。\n\n'
        '# 十、估值分析\n'
        '**从估值维度报告中提取，必须包含以下内容：**\n'
        '1. 融资轮估值分析（各轮次金额/投后估值/隐含乘数/趋势）\n'
        '2. 可比公司估值对标（上市公司PE/PS + 一级市场对标）\n'
        '3. 投资回报模型（MOIC/IRR矩阵 + 退出路径分析）\n'
        '4. 估值风险与敏感性分析\n'
        '5. 合理估值区间与BP预期对比\n\n'
        '# 十一、风险因素\n'
        '按类别分：技术/市场/竞争/政策/经营。每条风险要具体。\n\n'
        '# 十二、综合结论与建议\n'
        '核心判断（2-3段）+ 投资建议（是否进入尽调+尽调重点清单）+ 估值建议。\n\n'
        '# 来源与参考\n'
        '将正文中所有 [^N] 脚注展开为完整来源信息，格式：[^N] 来源名称 — URL (日期)\n\n'
        '## ⚠️ 统稿保留硬约束（最高优先级 — 解决统稿过度压缩问题）\n'
        '统稿的职责是"跨维度去重+逻辑重组"，不是"压缩篇幅"。以下内容必须原文保留，不得删除或压缩为文字叙述：\n'
        '\n'
        '### 规则1：核心对比表必须原文保留\n'
        '子代理输出中的以下类型表格，**必须完整保留到统稿中**，不得删除、不得压缩为文字概述：\n'
        '- **行业技术路线全景对比表**（不同技术路线的原理/性能/成本/成熟度/代表企业横向对比）\n'
        '- **产品级竞品参数对比表**（每条产品线 vs 具体竞品型号，含性能参数/价格/认证/量产状态）\n'
        '- **现有方案深度对比大表**（横向8-10维度对比，含价格）\n'
        '- **核心组件拆解表**（组件/功能/技术难点/自研vs外采）\n'
        '如果子代理输出中已有这类表格，统稿时直接搬入对应章节，重新编排格式即可。如果子代理未产出但该品类报告理应有，统稿必须自行补充。\n'
        '投资人看报告最核心的判断依据就是"我的技术/产品在行业里排什么位置、替代方案有哪些"——丢失这些表 = 报告不合格。\n'
        '\n'
        '### 规则2：市占率/份额/渗透率数据必须完整保留\n'
        '以下数据不得省略或模糊化：\n'
        '- **TAM/SAM/SOM分层推算**及每层的具体数字和推算依据\n'
        '- **各细分市场的当前渗透率和长期渗透率预期**，以及驱动力/对标/必要条件\n'
        '- **竞品市占率**（具体数字和百分比必须保留，不能只写"垄断竞争"或"占据大部分份额"等模糊表述）\n'
        '- **标的公司在各细分市场的市占率/渗透率**（具体数字必须出现，不能省略）\n'
        '- **市场规模推算的关键参数**（目标单位数量/配备比例/单价/年更新量）\n'
        '这些数据是投资人判断"市场有多大、我能吃多少"的核心依据，省略 = 报告不合格。\n'
        '\n'
        '### 规则3：去重只做跨维度，不做维度内压缩\n'
        '- **跨维度去重**✓：如果团队维度和竞争维度都列了同一竞品列表，统稿时只保留一处（选信息更完整的那个），另一处改为引用\n'
        '- **维度内压缩**✗：单个维度内部的表格、数据、分析段落不得删除或压缩。如果技术维度有5张竞品对比表，统稿必须保留全部5张（可以分散到不同章节），不能合并成1张高层级表格\n'
        '- **判断标准**：如果删除某段内容后，读者对"标的公司的技术/产品在行业中处于什么位置"的理解变模糊了，那段内容就不该删\n'
        '\n'
        '### 规则4：来源合并不得丢来源\n'
        '子代理的来源引用格式可能不统一（有的用[^N]脚注，有的用编号表格，有的用🅰-N评级格式），统稿时必须全部归集：\n'
        '- **所有子代理的来源索引表都必须合并到统稿末尾的"来源与参考"章节**，不能因为格式不同就丢弃\n'
        '- **跨维度去重内容，来源也要去重保留**：如果4个维度都引用了同一来源（如企查查工商信息），统稿正文中只引用1次，但末尾来源表保留1条即可\n'
        '- **目标：统稿来源总数 ≥ 各维度来源去重后的总数**，不得少于子代理来源的总量。如果统稿25条来源但4个维度合计79条，说明大量来源在统稿过程中丢失了\n'
        '- 对于非[^N]格式的来源（如🅰-N评级格式、编号表格格式），统稿时必须将其转换为[^N]脚注格式并纳入统一编号\n'
        '\n'
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
    if os.environ.get("IRBP_BG_CHILD") == "1":
        return _run_bp_delivery_inner(runtime_root, job_ctx)
    from scripts.heavy_phase_bg import check_cached_result, launch_heavy_phase
    cached = check_cached_result(runtime_root, job_ctx.job_id, "phase3_delivery")
    if cached is not None:
        print(f"  📦 [bp] 使用缓存的 delivery 结果", flush=True)
        return cached
    return launch_heavy_phase(runtime_root, job_ctx, "phase3_delivery", pipeline="bp")


def _run_bp_delivery_inner(runtime_root: Path, job_ctx: JobContext) -> dict[str, Any]:
    """delivery 实际执行逻辑（由 phase_runner.py 子进程调用时通过 bp_profile 路由）"""
    task_dir = _task_dir(runtime_root, job_ctx)
    workspace = getattr(job_ctx, "workspace", None)
    delivery_dir = workspace.delivery_dir if workspace is not None else task_dir
    outputs_dir = _outputs_dir(runtime_root, job_ctx)

    # 优先使用统稿输出（投研逻辑结构），fallback 到五个维度原文
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
        # Fallback：五个维度原文
        file_map = {
            "team": task_dir / "bp_phase2_team.md",
            "tech": task_dir / "bp_phase2_tech.md",
            "industry": task_dir / "bp_phase2_industry.md",
            "valuation": task_dir / "bp_phase2_valuation.md",
            "competition": task_dir / "bp_phase2_competition.md",
        }
        for slug, output_path in file_map.items():
            if output_path.exists():
                dimension_outputs[slug] = output_path.read_text(encoding="utf-8")

    delivery_errors = []

    # v2: 在交付前对统稿输出跑 verification_agent.py（BP 管线之前没有验证环节）
    verification_result = None
    synthesis_text = dimension_outputs.get("synthesis", "") if dimension_outputs else ""
    if synthesis_text and len(synthesis_text) > 500:
        try:
            from scripts.verification_agent import AdversarialVerifier
            verifier = AdversarialVerifier(pipeline="bp")
            verification_result = verifier.run(synthesis_text)
            verdict = verification_result.get("verdict", "UNKNOWN")
            fail_count = verification_result.get("fail", 0)
            print(f"  🔍 BP 对抗验证: verdict={verdict}, fails={fail_count}", flush=True)

            # 保存验证结果
            ver_dir = delivery_dir.parent / "verification"
            ver_dir.mkdir(parents=True, exist_ok=True)
            ver_path = ver_dir / f"{job_ctx.job_id}_bp_verification.json"
            ver_path.write_text(
                json.dumps(verification_result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            # FAIL 但不阻断交付——只是记录和警告
            if verdict == "FAIL":
                delivery_errors.append(f"对抗验证 FAIL: {fail_count} 项检查失败（详见 verification/）")
        except Exception as exc:
            print(f"  ⚠️ BP 对抗验证跳过: {exc}", flush=True)

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

    # 收集附件文件（xlsx 等）到 delivery 目录
    attachment_paths: list[str] = []
    for xlsx_name in outputs_dir.glob(f"{job_ctx.job_id}_*.xlsx"):
        dst = delivery_dir / xlsx_name.name
        if not dst.exists():
            shutil.copy2(xlsx_name, dst)
        attachment_paths.append(str(dst))
    # 也检查 task_dir
    for xlsx_name in task_dir.glob(f"{job_ctx.job_id}_*.xlsx"):
        dst = delivery_dir / xlsx_name.name
        if not dst.exists():
            shutil.copy2(xlsx_name, dst)
        if str(dst) not in attachment_paths:
            attachment_paths.append(str(dst))

    try:
        from runtime.orchestrator.state_store import StateStore

        ss = StateStore(runtime_root)
        if docx_path:
            ss.record_artifact(job_ctx.job_id, "bp_dd_report", Path(docx_path))
        ss.record_artifact(job_ctx.job_id, "bp_delivery_audit", audit_path)
        # 注册 xlsx 附件
        for i, att_path in enumerate(attachment_paths):
            ss.record_artifact(job_ctx.job_id, f"bp_attachment_{i}", Path(att_path))
    except Exception:
        pass

    # 微信通知（三步发送：文本→文件→确认，失败自动重试1次）
    # ⚠️ wechat_bot 装在 Python 3.14，系统 Python 3.9 找不到模块
    # 必须用 subprocess + Python 3.14 调用 longshao_notify.py CLI
    wechat_result = None
    if docx_path:
        # 找 Python 3.14+（wechat_bot 所在环境）
        import shutil
        python314 = shutil.which("python3.14") or ""
        if not python314:
            # 回退到 homebrew 路径
            import glob as _glob
            _candidates = sorted(_glob.glob("/opt/homebrew/Cellar/python@3.14/*/Frameworks/Python.framework/Versions/3.*/Resources/Python.app/Contents/MacOS/Python"), reverse=True)
            python314 = _candidates[0] if _candidates else ""
        if not python314:
            print("  ⚠ 找不到 Python 3.14，跳过微信通知", flush=True)
            python314 = None
        notify_script = str(runtime_root / "scripts" / "longshao_notify.py")
        caption = f"📋 BP尽调报告完成\n标的: {job_ctx.job_id}\n报告: {Path(docx_path).name}"
        if python314:
            for attempt in range(2):
                try:
                    r = subprocess.run(
                        [python314, notify_script, "--file", str(docx_path), caption],
                        capture_output=True, text=True, cwd=str(runtime_root), timeout=120,
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        import json as _json
                        wechat_result = _json.loads(r.stdout.strip())
                    else:
                        wechat_result = {"ok": False, "msg": f"exit={r.returncode} stderr={r.stderr[:200]}"}
                    # 检查结果
                    if wechat_result.get('ok'):
                        break
                    if attempt == 0:
                        print(f"  ⚠ 微信通知第{attempt+1}次失败: {wechat_result.get('msg', '未知错误')}，重试中...", flush=True)
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
            "attachment_paths": attachment_paths,
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
