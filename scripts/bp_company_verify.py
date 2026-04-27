#!/usr/bin/env python3
"""BP company verification.

Verifies company identity, founders, registration signals, litigation/compliance
signals, and writes a compact evidence report for downstream BP due diligence.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "tasks"


def _task_dir(job_ctx: Any) -> Path:
    workspace = getattr(job_ctx, "workspace", None)
    if workspace is not None:
        return workspace.root
    path = TASKS_DIR / job_ctx.job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_profile(task_dir: Path) -> dict[str, Any]:
    path = task_dir / "bp_step0_profile.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _entity_from_profile(profile: dict[str, Any], fallback: str = "") -> str:
    for key in ("company_name", "entity", "project_name"):
        value = str(profile.get(key) or "").strip()
        if value:
            return value
    return fallback.strip()


def _founder_names(profile: dict[str, Any]) -> list[str]:
    raw = profile.get("team_highlights") or profile.get("founders") or []
    if isinstance(raw, str):
        raw = [raw]
    names: list[str] = []
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        first = re.split(r"\s|[-—,，/／|｜]", text, maxsplit=1)[0].strip()
        if first and first not in names:
            names.append(first)
    return names[:8]


def _advisor_names(profile: dict[str, Any]) -> list[str]:
    raw = profile.get("advisors") or []
    if isinstance(raw, str):
        raw = [raw]
    names: list[str] = []
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        first = re.split(r"\s|[-—,，/／|｜]", text, maxsplit=1)[0].strip()
        if first and first not in names:
            names.append(first)
    return names[:8]


def _search(query: str, max_results: int = 6) -> list[dict[str, Any]]:
    try:
        from scripts.search_gateway import search
        rows = search(query, max_results=max_results)
        result = rows if isinstance(rows, list) else []
        if not result:
            print(f"    ⚠️ 搜索无结果: {query[:50]}", flush=True)
        return result
    except Exception as e:
        print(f"    ❌ 搜索异常: {e}", flush=True)
        return []


def _compact_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        out.append({
            "title": str(row.get("title") or "")[:180],
            "url": str(row.get("url") or ""),
            "content": str(row.get("content") or row.get("snippet") or "")[:500],
            "source": str(row.get("source") or row.get("engine") or ""),
        })
    return out


def _write_markdown(task_dir: Path, entity: str, report: dict[str, Any]) -> Path:
    path = task_dir / "company_verify_report.md"
    lines = [
        f"# BP 工商与主体核验：{entity or '未知主体'}",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 核验结论：{report['verdict']}",
        "",
        "## 主体线索",
    ]
    for item in report.get("identity_signals", []):
        lines += [f"- {item.get('title', '')}", f"  - {item.get('url', '')}"]
    if not report.get("identity_signals"):
        lines.append("- 未找到稳定的公开主体线索")

    lines += ["", "## 创始人与管理层线索"]
    if not report.get("founders"):
        lines.append("- ⚠️ BP 未披露实际创始人/CEO/管理层")
    for founder, rows in report.get("founder_signals", {}).items():
        lines.append(f"### {founder}")
        if rows:
            for item in rows:
                lines += [f"- {item.get('title', '')}", f"  - {item.get('url', '')}"]
        else:
            lines.append("- 未找到独立公开线索")

    lines += ["", "## 科学顾问/外部顾问线索"]
    if not report.get("advisors"):
        lines.append("- BP 未提及外部顾问")
    for advisor, rows in report.get("advisor_signals", {}).items():
        lines.append(f"### {advisor}")
        if rows:
            for item in rows:
                lines += [f"- {item.get('title', '')}", f"  - {item.get('url', '')}"]
        else:
            lines.append("- 未找到独立公开线索")

    lines += ["", "## 风险与合规线索"]
    for item in report.get("risk_signals", []):
        lines += [f"- {item.get('title', '')}", f"  - {item.get('url', '')}"]
    if not report.get("risk_signals"):
        lines.append("- 未发现明确公开风险线索；不代表不存在风险")

    lines += ["", "## 备注", "公开搜索只能作为线索发现，不能替代工商数据库、法院公告、征信或律师尽调。"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_company_verify(job_ctx: Any) -> dict[str, Any]:
    task_dir = _task_dir(job_ctx)
    profile = _read_profile(task_dir)
    entity = _entity_from_profile(profile, getattr(job_ctx, "entity", ""))
    founders = _founder_names(profile)
    advisors = _advisor_names(profile)
    stage = str(profile.get("financing_stage") or "").strip().lower()
    is_early = any(kw in stage for kw in ("种子", "天使", "seed", "angel", "pre-a", "pre_a"))

    print(f"  🔍 主体核验: entity={entity}, stage={stage}, early={is_early}", flush=True)
    print(f"     founders={founders}, advisors={advisors}", flush=True)
    if not founders and advisors:
        print(f"  ⚠️ BP 未披露实际创始人/CEO，仅有顾问: {advisors}", flush=True)

    # 根据融资阶段选择搜索策略
    identity_rows: list[dict[str, Any]] = []
    if is_early:
        # 种子/天使轮：公司大概率没注册，搜创始人个人 + 技术关键词
        print(f"  📋 早期项目策略：跳过工商搜索，聚焦创始人和技术验证", flush=True)
        tech_keywords = profile.get("sub_industry") or profile.get("industry") or ""
        products = profile.get("product_service") or []
        product_str = " ".join(str(p) for p in products[:3]) if products else ""

        early_queries = []
        tech_tag = " ".join(filter(None, [tech_keywords, product_str]))[:40] or entity
        for founder in founders[:3]:
            early_queries.append(f'"{founder}" {tech_tag} 研究')
            early_queries.append(f'"{founder}" 竞赛 获奖 论文')
        if tech_keywords:
            early_queries.append(f'{tech_keywords} 技术 研究 进展')
        if product_str:
            early_queries.append(f'{product_str} 市场 应用')

        for query in early_queries:
            rows = _search(query, max_results=4)
            identity_rows.extend(rows)
    else:
        # B轮及以后：正常搜工商
        if entity:
            for query in (
                f'"{entity}" 工商 注册 法定代表人',
                f'"{entity}" 统一社会信用代码',
                f'"{entity}" 官网 公司 简介',
            ):
                identity_rows.extend(_search(query, max_results=4))

    # 创始人个人履历（所有阶段都搜，但早期不绑公司名）
    founder_signals: dict[str, list[dict[str, str]]] = {}
    for founder in founders:
        if is_early:
            query = f'"{founder}" 履历 背景 研究'
        else:
            query = f'"{entity}" "{founder}" 创始人 CEO' if entity else f'"{founder}" 创始人 CEO'
        founder_signals[founder] = _compact_rows(_search(query, max_results=4))

    # 顾问验证（不绑公司名，直接搜顾问本人）
    advisor_signals: dict[str, list[dict[str, str]]] = {}
    for advisor in advisors:
        query = f'"{advisor}" 院士 教授 专家'
        advisor_signals[advisor] = _compact_rows(_search(query, max_results=3))

    # 风险搜索（早期项目搜创始人个人风险，不搜公司）
    risk_rows: list[dict[str, Any]] = []
    if is_early:
        for founder in founders[:3]:
            for query in (
                f'"{founder}" 诉讼 失信 处罚',
                f'"{founder}" 骗局 造假 争议',
            ):
                risk_rows.extend(_search(query, max_results=3))
    elif entity:
        for query in (
            f'"{entity}" 诉讼 行政处罚',
            f'"{entity}" 失信 被执行人',
            f'"{entity}" 经营异常 风险',
        ):
            risk_rows.extend(_search(query, max_results=4))

    compact_identity = _compact_rows(identity_rows)[:10]
    compact_risk = _compact_rows(risk_rows)[:10]
    verdict = "verified_with_public_signals" if compact_identity else "insufficient_public_signals"

    report = {
        "task_id": job_ctx.job_id,
        "entity": entity,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "verdict": verdict,
        "identity_signals": compact_identity,
        "founders": founders,
        "founder_signals": founder_signals,
        "advisors": advisors,
        "advisor_signals": advisor_signals,
        "risk_signals": compact_risk,
        "limitations": [
            "公开搜索结果只作线索，不等同于工商数据库核验结论。",
            "如进入投资流程，应继续使用工商数据库、法院公告和律师尽调做最终确认。",
        ],
    }

    json_path = task_dir / "company_verify_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = _write_markdown(task_dir, entity, report)

    return {
        "ok": True,
        "mode": "bp_company_verify",
        "phase": "phase05_company_verify",
        "job_id": job_ctx.job_id,
        "result": {
            "entity": entity,
            "verdict": verdict,
            "identity_signal_count": len(compact_identity),
            "risk_signal_count": len(compact_risk),
            "json_path": str(json_path),
            "markdown_path": str(md_path),
        },
    }


if __name__ == "__main__":
    import argparse
    from runtime.profiles.base import JobContext

    parser = argparse.ArgumentParser(description="Run BP company verification")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--entity", default="")
    args = parser.parse_args()
    result = run_company_verify(JobContext(job_id=args.task_id, entity=args.entity))
    print(json.dumps(result, ensure_ascii=False, indent=2))
