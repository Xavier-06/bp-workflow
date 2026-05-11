#!/usr/bin/env python3
"""
BP 尽调管线主控

Phase 0: OCR 提取
Phase 1: Step 0 + 全网搜索 + 正文提取
Phase 2: Gap Detection
Phase 3: Gap-Driven 深搜
Phase 4: 子代理
Phase 5: DOCX 一致性校验

用法:
  python3 run_pipeline.py --task-id TASK-XXX [--pdf /path/to/file.pdf]
"""
import sys
import os
import json
import time
import traceback
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / "tasks"
SCRIPTS_DIR = WORKSPACE / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))


def run_phase0(task_id: str, pdf_path: str = None) -> str:
    """Phase 0: OCR 提取"""
    import ocr_pdf
    task_dir = TASKS_DIR / task_id
    ocr_path = task_dir / "bp_ocr_text.txt"
    
    if ocr_path.exists():
        return ocr_path.read_text(encoding="utf-8")
    
    # Try to find PDF in task dir
    if not pdf_path:
        pdfs = list(task_dir.glob("*.pdf"))
        if pdfs:
            pdf_path = str(pdfs[0])
    
    if pdf_path:
        text = ocr_pdf.main(pdf_path)
        ocr_path.write_text(text, encoding="utf-8")
        return text
    return ""


def run_phase1(task_id: str, pdf_text: str) -> dict:
    """Phase 1: Step 0 + presearch"""
    from bp_preflight_check import run as preflight_run
    from bp_presearch import run as presearch_run
    
    step0_profile = preflight_run(task_id, pdf_text)
    presearch_summary = presearch_run(task_id)
    
    return {
        "phase": 1,
        "step0_profile": step0_profile,
        "presearch_summary": presearch_summary,
    }


def run_phase1b2(task_id: str) -> dict:
    """Phase 1b-2: 正文提取 (requests + Playwright fallback)"""
    from extract_content import run as extract_run
    
    result = extract_run(task_id, max_pages=15, try_js=True)
    
    return {
        "phase": "1b-2",
        "summary": result,
    }


def run_phase2(task_id: str) -> dict:
    """Phase 2: Gap Detection"""
    from gap_detector import detect as gap_detect
    
    gap_report = gap_detect(task_id)
    
    return {
        "phase": 2,
        "gap_report": gap_report,
    }


def run_phase3(task_id: str, gap_report: dict, pdf_text: str, max_rounds: int = 3) -> dict:
    """Phase 3: Gap-Driven 深搜 + LLM 查询改写"""
    from gap_driven_search import deep_drill
    from query_expander import llm_rewrite_queries
    
    task_dir = TASKS_DIR / task_id
    profile = {}
    profile_path = task_dir / "bp_step0_profile.json"
    if profile_path.exists():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    
    final_gap = gap_report
    
    for round_num in range(1, max_rounds + 1):
        # 读现有 gap queries
        gap_queries_path = task_dir / "bp_gap_queries.md"
        if not gap_queries_path.exists():
            break
        
        gap_text = gap_queries_path.read_text(encoding="utf-8")
        import re
        queries = re.findall(r"^\d+\.\s*(.+)", gap_text, re.MULTILINE)
        
        if not queries:
            break
        
        # 先跑 Gap-Driven 深搜
        final_gap = deep_drill(task_id, queries, round_num)
        
        score = final_gap.get("score", "")
        remaining_gaps = final_gap.get("gap_count", 0)
        
        # 数据充足 → 提前退出
        if score.startswith(("A", "B")) or remaining_gaps < 3:
            break
        
        # LLM 查询改写：找盲区
        evidence_urls = []
        gap_results_path = task_dir / "bp_gap_driven_results.json"
        if gap_results_path.exists():
            results = json.loads(gap_results_path.read_text(encoding="utf-8"))
            for r in results:
                if r.get("url"):
                    evidence_urls.append(r["url"])
        
        base_queries = [q["text"] for q in final_gap.get("unverified", [])]
        llm_extra = llm_rewrite_queries(
            base_queries, 
            evidence_urls, 
            entity=profile.get("company_name", ""), 
            max_n=8
        )
        
        if llm_extra:
            print(f"  LLM 补查 ({len(llm_extra)} 个): {llm_extra[:5]}")
            # 追加到 gap_queries.md 下一轮用
            gap_queries_path.write_text(
                gap_text + "\n\n# LLM 补充查询\n" + 
                "\n".join(f"{i+1}. {q}" for i, q in enumerate(llm_extra)),
                encoding="utf-8",
            )
    
    return {
        "phase": 3,
        "final_gap_report": final_gap,
    }


def run_phase4(task_id: str) -> dict:
    """Phase 4: 子代理分析 (由主控 sessions_spawn 派发)"""
    return {
        "phase": 4,
        "status": "ready_for_spawn",
    }


def run_phase5(task_id: str) -> dict:
    """Phase 5: DOCX + 一致性校验"""
    from build_bp_dd_report_docx import build_docx
    
    docx_path = build_docx(task_id)
    
    return {
        "phase": 5,
        "docx_path": str(docx_path),
    }


def run_pipeline(task_id: str, pdf_path: str = None):
    """完整管线"""
    print(f"BP DD 管线: {task_id}")
    print(f"{'='*50}")
    
    # Phase 0: OCR
    pdf_text = run_phase0(task_id, pdf_path)
    if not pdf_text:
        print("❌ OCR 失败，跳过管线")
        return
    
    # Phase 1: Step 0 + presearch
    result = run_phase1(task_id, pdf_text)
    
    # Phase 1b-2: 正文提取
    if result.get("presearch_summary", {}).get("total_results", 0) > 0:
        run_phase1b2(task_id)
    
    # Phase 2: Gap Detection
    result = run_phase2(task_id)
    
    # Phase 3: Gap-Driven 深搜
    result = run_phase3(task_id, result["gap_report"], pdf_text)
    
    # Phase 4: 子代理 (需主控 sessions_spawn)
    # run_phase4(task_id)
    
    # Phase 5: DOCX + 校验
    # run_phase5(task_id)
    
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--pdf", default=None)
    args = parser.parse_args()
    
    run_pipeline(args["task_id"], args["pdf"])