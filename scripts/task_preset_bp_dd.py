#!/usr/bin/env python3
"""
BP DD 管线任务树预设

为完整 BP 尽调链路创建任务树：
phase0_document_intake -> phase05_company_verify -> phase1_presearch -> phase2_dispatch -> phase3_delivery
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import sys

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

from scripts.task_registry import TaskRegistry


def create_bp_dd_tasks(task_id: str, reg: Optional["TaskRegistry"] = None) -> "TaskRegistry":
    """为 BP DD 管线创建当前完整任务树。"""
    if reg is None:
        reg = TaskRegistry()

    pipeline = f"bp_dd_{task_id}"

    existing = [t for t in reg.list_all() if t.pipeline == pipeline]
    for task in existing:
        reg.delete(task.id)

    intake = reg.create(
        subject="文档入库与 OCR",
        description="解析 BP 文件并抽取 step0 结构化画像",
        active_form="正在解析 BP 文档",
        phase="phase0_document_intake",
        pipeline=pipeline,
        blocked_by=[],
        metadata={"step": "phase0_document_intake"},
    )

    company_verify = reg.create(
        subject="主体核验",
        description="基于公开信息核验公司主体、创始人和风险线索",
        active_form="正在核验公司主体",
        phase="phase05_company_verify",
        pipeline=pipeline,
        blocked_by=[intake.id],
        metadata={"step": "phase05_company_verify"},
    )

    presearch = reg.create(
        subject="预搜索",
        description="按团队、技术、行业、竞争四个维度生成共享搜索底稿",
        active_form="正在做预搜索",
        phase="phase1_presearch",
        pipeline=pipeline,
        blocked_by=[intake.id, company_verify.id],
        metadata={"step": "phase1_presearch"},
    )

    dispatch = reg.create(
        subject="五维度并行尽调",
        description="派发团队、技术、行业、估值五个维度子任务",
        active_form="正在派发五维度分析",
        phase="phase2_dispatch",
        pipeline=pipeline,
        blocked_by=[presearch.id],
        metadata={"step": "phase2_dispatch"},
    )

    reg.create(
        subject="交付报告",
        description="汇总五维度结果并生成尽调报告 DOCX",
        active_form="正在生成尽调报告",
        phase="phase3_delivery",
        pipeline=pipeline,
        blocked_by=[dispatch.id],
        metadata={"step": "phase3_delivery"},
    )

    return reg


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", default="demo", help="Task ID prefix")
    ap.add_argument("--action", default="create", choices=["create", "list", "status"])
    args = ap.parse_args()

    reg = TaskRegistry()

    if args.action == "create":
        reg = create_bp_dd_tasks(args.task_id, reg)
        print(f"✅ 创建了 BP DD 任务树 (pipeline: bp_dd_{args.task_id})")
        print()
        reg.print_tree()
        print()
        ready = reg.get_ready_tasks(f"bp_dd_{args.task_id}")
        print(f"Ready to execute: {[f'Task {t.id}: {t.subject}' for t in ready]}")
    elif args.action == "list":
        status = reg.pipeline_status(f"bp_dd_{args.task_id}")
        print(json.dumps(status, ensure_ascii=False, indent=2))
    elif args.action == "status":
        reg.print_tree(f"bp_dd_{args.task_id}")
