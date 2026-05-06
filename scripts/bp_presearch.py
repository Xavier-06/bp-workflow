#!/usr/bin/env python3
"""BP presearch.

Builds a concise multi-step public-info pack from OCR + step0 profile so the four
BP dimension agents start with shared evidence instead of empty context.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "tasks"
CURRENT_YEAR = time.localtime().tm_year
PREV_YEAR = CURRENT_YEAR - 1

# 早期项目（种子/天使）：公司大概率没注册，搜技术关键词、行业、创始人个人
EARLY_STAGE_QUERIES = {
    "team": [
        '"{founder}" 履历 背景 研究 论文',
        '"{founder}" 竞赛 获奖 专利',
        '"{tech}" 领域 创业 团队',
        '"{founder}" LinkedIn 教育 工作经历',
    ],
    "tech": [
        '{tech} 技术 原理 研究进展 {year}',
        '{tech} 产品 应用 案例 落地',
        '{tech} 专利 论文 学术',
        '{tech} vs 传统方案 对比 优劣势',
        '{tech} 技术路线 分类 对比',
        '{tech} 产品 价格 成本 售价',
        '{tech} 行业标准 技术规范 国标 团标',
        # 技术验证搜索（v2新增）
        '{tech} 技术突破 实验验证 第三方测试',
        '{tech} 标准 规范 认证 检测',
    ],
    "industry": [
        '{industry} 市场规模 行业趋势 {year}',
        '{industry} market size TAM global {year}',
        '{industry} 政策 监管 准入 资质',
        '{tech} 上下游 供应链 产业链',
        '{industry} 厂商 企业 公司 玩家',
        '{tech} 民用 应用场景 拓展',
        '{industry} 研究报告 market research report {year}',
        # 行业报告搜索加强（v2新增，不用site:和OR操作符）
        '{industry} 行业报告 白皮书 深度报告 {year}',
        '{industry} industry report forecast {year}',
        '{tech} 市场分析 行业深度 券商研报 {year}',
    ],
    "competition": [
        '{tech} 竞品 替代方案 对比',
        '{industry} 竞争格局 龙头企业 市占率',
        '{tech} 融资 投资 创业公司 {year}',
        '{tech} company startup funding {year}',
        '{industry} 失败案例 风险 教训',
    ],
}

# 成熟项目（A轮及以后）：公司已注册，可以搜公司名
MATURE_STAGE_QUERIES = {
    "team": [
        '"{entity}" 创始人 履历 融资',
        '"{entity}" 管理层 股权结构 治理',
        '"{entity}" 诉讼 行政处罚 合规',
        '"{entity}" CEO CTO 背景 经历',
    ],
    "tech": [
        '"{entity}" 产品 技术 专利 客户',
        '"{entity}" 解决方案 落地 案例 订单',
        '"{entity}" 技术 路线 研发 {year}',
        '"{entity}" vs 竞品 产品对比 价格',
        '{tech} 技术路线 分类 对比 优劣',
        '{tech} 产品 价格 成本 单价',
        '{tech} 行业标准 技术规范 国标 团标',
        # 技术验证搜索（v2新增）
        '{tech} 技术验证 第三方测试 认证报告',
        '{tech} 标准 规范 认证 检测',
    ],
    "industry": [
        '"{entity}" 行业 市场规模 竞争格局 {year}',
        '{industry} market size TAM SAM global {year}',
        '"{entity}" 上下游 供应链 客户 供应商',
        '"{entity}" 行业 趋势 风险 政策 监管',
        '{industry} 厂商 企业 龙头 上市公司',
        '{tech} 民用 应用场景 拓展 新兴',
        '{industry} 研究报告 market research {year}',
        # 行业报告搜索加强（v2新增，不用site:和OR操作符）
        '{industry} 行业报告 白皮书 深度报告 {year}',
        '{industry} industry report forecast {year}',
        '{industry} 券商研报 深度报告 行业分析 {year}',
    ],
    "competition": [
        '"{entity}" 竞品 对标 融资 估值',
        '"{entity}" 竞争格局 市占率 替代方案',
        '"{entity}" 融资 估值 投资人 {year}',
        '{industry} 竞品 公司 startup funding {year}',
        '{industry} 失败案例 风险 倒闭 教训',
    ],
}


def _task_dir(job_ctx: Any) -> Path:
    workspace = getattr(job_ctx, "workspace", None)
    if workspace is not None:
        return workspace.root
    path = TASKS_DIR / job_ctx.job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _entity(task_dir: Path, fallback: str = "") -> str:
    profile = _read_json(task_dir / "bp_step0_profile.json")
    return str(profile.get("company_name") or profile.get("entity") or fallback or "").strip()


def _extract_tech_keywords(task_dir: Path) -> str:
    """从 profile 的 product_service + competitive_advantages 中提取技术关键词，
    用于替代过于宽泛的 industry/sub_industry 构造搜索词。
    
    优先级：product_service > competitive_advantages > sub_industry
    """
    profile = _read_json(task_dir / "bp_step0_profile.json")
    keywords: list[str] = []

    # 1. 从 product_service 提取高频技术词
    products = profile.get("product_service") or []
    if isinstance(products, list):
        for p in products:
            p = str(p).strip()
            # 提取核心技术词：去掉"芯片""产品""服务""装备"等通用后缀
            for term in p.split("、"):
                term = term.strip()
                if len(term) >= 4:
                    keywords.append(term)

    # 2. 从 competitive_advantages 提取
    advs = profile.get("competitive_advantages") or []
    if isinstance(advs, list):
        for a in advs[:3]:
            a = str(a).strip()
            if len(a) >= 4:
                keywords.append(a[:30])

    if keywords:
        # 去重并取前5个最相关的
        seen = set()
        unique = []
        for k in keywords:
            k_clean = k.replace("芯片", "").replace("产品", "").strip()
            if k_clean and k_clean not in seen and len(k_clean) >= 2:
                seen.add(k_clean)
                unique.append(k)
        if unique:
            return unique[0]  # 返回最核心的技术词

    # 3. fallback: 用 sub_industry
    return str(profile.get("sub_industry") or "").strip()


def _ocr_tech_hints(task_dir: Path) -> list[str]:
    """从 OCR 文本中提取技术关键词提示，用于补充 presearch 搜索词。
    
    扫描 OCR 文本中反复出现的技术术语（≥2次出现的≥3字中文词组）。
    """
    ocr_path = task_dir / "bp_ocr_text.txt"
    if not ocr_path.exists():
        return []
    try:
        import re
        text = ocr_path.read_text(encoding="utf-8")
        # 提取2-6字的中文技术词组（出现≥3次）
        candidates = re.findall(r'[\u4e00-\u9fff]{2,6}(?:芯片|技术|方案|平台|能力|装备|检测|验证)', text)
        from collections import Counter
        counts = Counter(candidates)
        # 过滤：出现≥3次且不是纯通用词
        generic = {"技术方案", "技术能力", "芯片技术", "检测技术", "验证技术", "解决方案"}
        hints = [w for w, c in counts.most_common(10) if c >= 3 and w not in generic]
        return hints[:5]
    except Exception:
        return []


def _infer_keywords_from_ocr(task_dir: Path) -> dict[str, str]:
    """当 profile 提取失败时，从 OCR 文本推断 tech 和 industry 关键词。
    
    策略：
    1. 寻找"行业"/"领域"/"赛道"等关键词后的上下文
    2. 寻找"专注于"/"致力于"/"主要从事"后的业务描述
    3. 统计高频专业术语
    """
    ocr_path = task_dir / "bp_ocr_text.txt"
    if not ocr_path.exists():
        return {}
    try:
        import re
        text = ocr_path.read_text(encoding="utf-8")
        result = {}
        
        # 策略1：匹配"专注于"/"致力于"/"主要从事"后的业务描述
        biz_match = re.search(
            r'(?:专注于|致力于|主要从事|聚焦)\s*([\u4e00-\u9fff、]+(?:芯片|技术|方案|装备|产品|服务|器件))',
            text
        )
        if biz_match:
            result["tech"] = biz_match.group(1).strip()[:30]
        
        # 策略2：匹配"行业"/"领域"/"赛道"前的关键词
        industry_match = re.search(
            r'([\u4e00-\u9fff]{2,8})(?:行业|领域|赛道|产业|市场)',
            text
        )
        if industry_match:
            result["industry"] = industry_match.group(1).strip()
        
        # 策略3：高频技术词（≥5次出现的4-8字中文词组）
        if not result.get("tech"):
            from collections import Counter
            tech_candidates = re.findall(r'[\u4e00-\u9fff]{2,6}(?:芯片|器件|模块|系统)', text)
            counts = Counter(tech_candidates)
            for word, count in counts.most_common(5):
                if count >= 5 and len(word) >= 4:
                    result["tech"] = word
                    break
        
        return result
    except Exception:
        return {}


def _search(query: str, max_results: int = 6) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if len(q) < 3:
        return []
    try:
        from scripts.search_gateway import search
        rows = search(q, max_results=max_results)
        result = rows if isinstance(rows, list) else []
        if not result:
            # 尝试简化查询重试（去掉年份、去掉过长的修饰词）
            simplified = _simplify_query(q)
            if simplified and simplified != q:
                rows2 = search(simplified, max_results=max_results)
                result = rows2 if isinstance(rows2, list) else []
                if result:
                    print(f"    🔄 简化查询后有结果: {simplified[:50]}", flush=True)
        return result
    except Exception as e:
        print(f"    ❌ 搜索异常: {e}", flush=True)
        return []


def _simplify_query(query: str) -> str:
    """简化查询：去掉年份、去掉过长修饰词，提高命中率。"""
    import re as _re
    # 去掉年份（2024/2025/2026）
    simplified = _re.sub(r'\s+20[2-3]\d\s*$', '', query).strip()
    # 如果查询超过6个关键词，只保留前4个
    parts = simplified.split()
    if len(parts) > 6:
        simplified = ' '.join(parts[:4])
    return simplified if simplified != query else ''


def _format_step(title: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"# {title}", ""]
    if not rows:
        lines += ["- 未找到稳定公开信息", ""]
        return "\n".join(lines)
    for idx, row in enumerate(rows, 1):
        lines += [
            f"## {idx}. {row.get('title', '')}",
            f"- URL: {row.get('url', '')}",
            f"- 摘要: {str(row.get('content') or row.get('snippet') or '').strip()[:500]}",
            "",
        ]
    return "\n".join(lines)


def _infer_entity_from_ocr(task_dir: Path) -> str:
    """从 OCR 文本中尝试提取公司名（第一行通常包含公司名）"""
    ocr_path = task_dir / "bp_ocr_text.txt"
    if ocr_path.exists():
        try:
            lines = ocr_path.read_text(encoding="utf-8").splitlines()
            for line in lines[:10]:
                line = line.strip()
                if len(line) >= 4 and any("\u4e00" <= c <= "\u9fff" for c in line):
                    # 取前 20 个字符作为候选公司名
                    candidate = line[:20]
                    if "公司" in candidate or "集团" in candidate or "有限" in candidate or "股份" in candidate:
                        # 提取公司名
                        for suffix in ["有限公司", "股份有限公司", "有限责任公司", "集团", "公司"]:
                            idx = candidate.find(suffix)
                            if idx >= 0:
                                return candidate[:idx + len(suffix)]
                        return candidate
        except Exception:
            pass
    return ""


def _infer_entity_from_filename(task_dir: Path, job_ctx: Any) -> str:
    """从 BP 文件名中尝试提取公司名"""
    metadata = getattr(job_ctx, "metadata", {}) or {}
    input_file = metadata.get("input_file", "")
    if input_file:
        from pathlib import Path as _Path
        fname = _Path(input_file).stem
        # 去掉常见后缀
        for suffix in ["-向省长汇报材料", "-汇报材料", "-BP", "-商业计划书", "_BP"]:
            fname = fname.replace(suffix, "")
        if len(fname) >= 2:
            return fname
    return ""


def run_presearch(job_ctx: Any) -> dict[str, Any]:
    task_dir = _task_dir(job_ctx)
    profile = _read_json(task_dir / "bp_step0_profile.json")
    entity = _entity(task_dir, getattr(job_ctx, "entity", ""))

    # 如果 entity 为空，尝试从 OCR 文本和文件名中推断
    if not entity:
        entity = _infer_entity_from_ocr(task_dir)
    if not entity:
        entity = _infer_entity_from_filename(task_dir, job_ctx)
    if not entity:
        print("  ⚠️ 无法推断 entity，跳过 presearch", flush=True)
        return {
            "ok": False,
            "mode": "bp_presearch",
            "phase": "phase1_presearch",
            "job_id": job_ctx.job_id,
            "error": "entity 为空，无法构造搜索关键词",
        }

    # 融资阶段判断
    stage = str(profile.get("financing_stage") or "").strip().lower()
    is_early = any(kw in stage for kw in ("种子", "天使", "seed", "angel", "pre-a", "pre_a"))

    # 提取搜索变量
    tech = str(profile.get("sub_industry") or profile.get("industry") or "").strip()
    industry = str(profile.get("industry") or "").strip()
    
    # 🔧 优化：用 product_service 中提取的核心技术词替代宽泛的 sub_industry
    tech_keyword = _extract_tech_keywords(task_dir)
    if tech_keyword and len(tech_keyword) > len(tech):
        tech = tech_keyword
        print(f"     ⚡ tech_keyword 替换: sub_industry → {tech}", flush=True)
    
    # 🔧 优化：从 OCR 文本补充技术关键词
    ocr_hints = _ocr_tech_hints(task_dir)
    if ocr_hints:
        print(f"     ⚡ OCR 技术关键词补充: {ocr_hints}", flush=True)
    
    # 🔧 修复：当 profile 提取失败（extraction_error）导致 tech/industry 全空时，
    # 用 OCR 技术关键词作为 fallback，避免搜索词只剩 entity 名称
    if not tech and ocr_hints:
        tech = ocr_hints[0]
        print(f"     ⚡ tech 从 OCR hints fallback: {tech}", flush=True)
    if not industry and ocr_hints:
        industry = ocr_hints[0]
        print(f"     ⚡ industry 从 OCR hints fallback: {industry}", flush=True)
    
    # 🔧 修复：如果 OCR hints 也没有，从 OCR 文本做最后一轮 keyword 提取
    if not tech or not industry:
        inferred = _infer_keywords_from_ocr(task_dir)
        if not tech and inferred.get("tech"):
            tech = inferred["tech"]
            print(f"     ⚡ tech 从 OCR 推断 fallback: {tech}", flush=True)
        if not industry and inferred.get("industry"):
            industry = inferred["industry"]
            print(f"     ⚡ industry 从 OCR 推断 fallback: {industry}", flush=True)
    
    founders = profile.get("team_highlights") or []
    first_founder = ""
    if founders:
        first_founder = str(founders[0]).split(" - ")[0].split("-")[0].strip()

    print(f"  📋 presearch: entity={entity}, stage={stage}, early={is_early}", flush=True)
    print(f"     tech={tech}, industry={industry}, founder={first_founder}", flush=True)

    if is_early:
        step_queries = EARLY_STAGE_QUERIES
    else:
        step_queries = MATURE_STAGE_QUERIES

    summary: dict[str, Any] = {
        "task_id": job_ctx.job_id,
        "entity": entity,
        "stage": stage,
        "strategy": "early_stage" if is_early else "mature_stage",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "steps": {},
    }

    for slug, templates in step_queries.items():
        print(f"  🔎 presearch [{slug}] ...", flush=True)
        rows: list[dict[str, Any]] = []
        used_queries: list[str] = []
        for template in templates:
            query = template.format(
                entity=entity,
                tech=tech or entity,
                industry=industry or tech or entity,
                founder=first_founder or entity,
                year=CURRENT_YEAR,
                prev_year=PREV_YEAR,
            )
            used_queries.append(query)
            rows.extend(_search(query, max_results=4))
        
        # 🔧 优化：用 OCR 提取的技术关键词补充搜索
        if ocr_hints and slug in ("tech", "industry", "competition"):
            for hint in ocr_hints[:2]:  # 每个维度最多补2个关键词查询
                if slug == "tech":
                    sup_query = f'{hint} 技术 产品 市场 {CURRENT_YEAR}'
                elif slug == "industry":
                    sup_query = f'{hint} 市场规模 行业趋势 {CURRENT_YEAR}'
                else:
                    sup_query = f'{hint} 竞品 竞争格局 替代'
                used_queries.append(f"[ocr补充] {sup_query}")
                rows.extend(_search(sup_query, max_results=3))
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            url = str(row.get("url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            deduped.append({
                "title": str(row.get("title") or "")[:180],
                "url": url,
                "content": str(row.get("content") or row.get("snippet") or "")[:600],
                "source": str(row.get("source") or row.get("engine") or ""),
            })
            if len(deduped) >= 8:
                break

        markdown = _format_step(f"BP Presearch - {slug}", deduped)
        md_path = task_dir / f"bp_presearch_step_{slug}.md"
        md_path.write_text(markdown + "\n", encoding="utf-8")
        summary["steps"][slug] = {
            "queries": used_queries,
            "count": len(deduped),
            "path": str(md_path),
        }

    summary_path = task_dir / "bp_presearch_results.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "mode": "bp_presearch",
        "phase": "phase1_presearch",
        "job_id": job_ctx.job_id,
        "result": {
            "entity": entity,
            "summary_path": str(summary_path),
            "step_count": len(summary["steps"]),
        },
    }


if __name__ == "__main__":
    import argparse
    from runtime.profiles.base import JobContext

    parser = argparse.ArgumentParser(description="Run BP presearch")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--entity", default="")
    args = parser.parse_args()
    result = run_presearch(JobContext(job_id=args.task_id, entity=args.entity))
    print(json.dumps(result, ensure_ascii=False, indent=2))
