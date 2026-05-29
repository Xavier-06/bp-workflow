#!/usr/bin/env python3
"""
信息传导验证引擎 — IR 管线 Phase 4

功能：
  使用 doubao-embedding-vision（火山引擎 ARK）计算前序 step 输出与 step8 统稿
  之间的余弦相似度，验证关键分析结论是否被有效采纳。

门禁规则：
  - 任一前序 step → step8 相似度 < 0.30 → WARN（人工复核标记）
  - 核心 step（行业/业务/财务）→ step8 < 0.25 → FAIL（阻断交付）

依赖：
  - Volces ARK API (doubao-embedding-vision)
  - 环境变量: VOLCES_ARK_API_KEY, VOLCES_ARK_BASE_URL（可选，有默认值）

用法：
  python info_propagation_check.py <TASK_DIR> [--threshold 0.30]

TASK_DIR 结构：
  {task_id}-step1_data.md
  {task_id}-step2_industry.md
  ... (所有 step 输出)
  {task_id}-step8_master.md (统稿)
"""

import sys
import os
import json
import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime

import numpy as np


# ============================================================
# 配置
# ============================================================

EMBEDDING_MODEL = "doubao-embedding-vision"
DEFAULT_WARN_THRESHOLD = 0.30
DEFAULT_FAIL_THRESHOLD = 0.25

# Volces ARK 配置
DEFAULT_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
DEFAULT_ARK_API_KEY = ""  # 请使用 --api-key CLI 参数或 VOLCES_ARK_API_KEY 环境变量

# 核心 step（信息传导失败会导致阻断交付）
# 对标论文 Table 3: 行业/财务/宏观→统稿是最关键的信号传导链路
CORE_STEPS = {"step2_industry", "step3_biz", "step4_finance", "step_macro"}

# 所有前序 step → step8 映射
# 对齐实际 IR 管线 STEP_DEPS (ir_subagent_launcher_wb.py)
STEP_TO_NAME = {
    "step1_data": "行情与基础数据 (step1_data)",
    "step2_industry": "行业与市场格局 (step2_industry)",
    "step3_biz": "业务模式 (step3_biz)",
    "step4_finance": "财务分析 (step4_finance)",
    "step5_mgmt": "管理与治理 (step5_mgmt)",
    "step_macro": "宏观环境分析 (step_macro)",
    "step6_insight": "投资洞察 (step6_insight)",
    "step6b_valuation": "预测与估值 (step6b_valuation)",
    "step7_risk": "风险提示 (step7_risk)",
}

# 火山引擎 doubao-embedding-vision 模型上下文限制 128K tokens
# ≈ ~250K 中文字符（远大于实际 step 输出长度，基本不需要截断）
# 设置保守上限防止极端情况
MAX_CHARS_DOUBAO = 200000


# ============================================================
# 嵌入 & 相似度
# ============================================================


def get_embedding(
    text: str,
    api_key: str,
    base_url: str = DEFAULT_ARK_BASE_URL,
) -> Optional[List[float]]:
    """
    调用火山引擎 ARK doubao-embedding-vision API 获取文本向量。
    使用 OpenAI 兼容接口，参数与 OpenAI embeddings API 一致。

    若文本为空或 API 不可用，返回 None。
    """
    if not text or not text.strip():
        return None

    # 火山引擎 doubao-embedding 有 token 限制，截断过长文本
    if len(text) > MAX_CHARS_DOUBAO:
        # 保留首尾各 60%（核心信息通常在首尾）
        head_len = int(MAX_CHARS_DOUBAO * 0.6)
        tail_len = MAX_CHARS_DOUBAO - head_len
        text = text[:head_len] + text[-tail_len:]

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding

    except ImportError:
        print("⚠ openai 包未安装。请执行: pip install openai", file=sys.stderr)
        return None
    except Exception as e:
        print(f"⚠ 嵌入请求失败 (model={EMBEDDING_MODEL}): {e}", file=sys.stderr)
        return None


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算两个向量的余弦相似度，返回 0-1 区间值"""
    if not a or not b:
        return 0.0
    a_arr = np.array(a)
    b_arr = np.array(b)
    dot = np.dot(a_arr, b_arr)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


# ============================================================
# 主检查函数
# ============================================================


def check_propagation(
    task_dir: Path,
    api_key: str,
    base_url: str = DEFAULT_ARK_BASE_URL,
    warn_threshold: float = DEFAULT_WARN_THRESHOLD,
    fail_threshold: float = DEFAULT_FAIL_THRESHOLD,
) -> Dict[str, Any]:
    """
    遍历 task_dir 中的所有 step 输出文件，计算与 step8 的传导相似度。

    返回:
    {
        "task_dir": str,
        "date": str,
        "embedding_model": str,
        "overall": "PASS" | "FAIL" | "PARTIAL",
        "warnings": [...],
        "fails": [...],
        "results": {
            "step_name": {"similarity": float, "status": "PASS"|"WARN"|"FAIL", "file": str}
        }
    }
    """
    step8_file = list(task_dir.glob("*step8_master*.md"))
    if not step8_file:
        return {
            "task_dir": str(task_dir),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "embedding_model": EMBEDDING_MODEL,
            "overall": "FAIL",
            "error": "step8 统稿文件未找到",
            "warnings": [],
            "fails": ["step8 统稿文件缺失"],
            "results": {},
        }

    step8_path = step8_file[0]
    step8_text = step8_path.read_text(encoding="utf-8")

    # 获取 step8 嵌入
    step8_embedding = get_embedding(step8_text, api_key, base_url)
    if step8_embedding is None:
        return {
            "task_dir": str(task_dir),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "embedding_model": EMBEDDING_MODEL,
            "overall": "FAIL",
            "error": f"无法获取 step8 嵌入向量（检查 {EMBEDDING_MODEL} API key 和网络）",
            "warnings": [],
            "fails": ["嵌入 API 不可用"],
            "results": {},
        }

    results: Dict[str, Dict] = {}
    warnings: List[str] = []
    fails: List[str] = []
    overall = "PASS"

    # 查找所有 step 输出文件
    step_files = {}
    for pattern in STEP_TO_NAME:
        matches = list(task_dir.glob(f"*{pattern}*.md"))
        if matches:
            step_files[pattern] = matches[0]

    for step_key, step_name in STEP_TO_NAME.items():
        if step_key not in step_files:
            continue

        step_path = step_files[step_key]
        step_text = step_path.read_text(encoding="utf-8")

        # 获取 step 嵌入
        step_embedding = get_embedding(step_text, api_key, base_url)
        if step_embedding is None:
            results[step_name] = {
                "similarity": None,
                "status": "SKIP",
                "reason": f"{EMBEDDING_MODEL} API 失败",
                "file": str(step_path),
            }
            continue

        similarity = cosine_similarity(step_embedding, step8_embedding)

        is_core = step_key in CORE_STEPS
        status = "PASS"

        if similarity < fail_threshold:
            status = "FAIL"
            msg = f"{step_name} → step8 相似度 {similarity:.3f} < 阻断线 {fail_threshold}"
            fails.append(msg)
            overall = "FAIL" if is_core else overall
        elif similarity < warn_threshold:
            status = "WARN"
            msg = f"{step_name} → step8 相似度 {similarity:.3f} < 预警线 {warn_threshold}"
            warnings.append(msg)
            if overall == "PASS":
                overall = "PARTIAL"

        results[step_name] = {
            "similarity": round(similarity, 4),
            "status": status,
            "is_core": is_core,
            "file": str(step_path),
        }

    return {
        "task_dir": str(task_dir),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "embedding_model": EMBEDDING_MODEL,
        "overall": overall,
        "warnings": warnings,
        "fails": fails,
        "results": results,
    }


# ============================================================
# 输出格式化
# ============================================================


def format_report(check_result: Dict[str, Any]) -> str:
    """生成 Markdown 信息传导验证报告"""

    lines = [
        "# 信息传导验证报告",
        "",
        f"**任务目录**: `{check_result['task_dir']}`",
        f"**检查日期**: {check_result['date']}",
        f"**嵌入模型**: {check_result.get('embedding_model', EMBEDDING_MODEL)}",
        f"**综合结论**: **{check_result['overall']}**",
        "",
    ]

    if "error" in check_result:
        lines.append(f"### ⚠ 错误: {check_result['error']}")
        return "\n".join(lines)

    # 门禁规则说明
    lines.extend([
        "## 门禁规则",
        "",
        f"- 嵌入模型: {EMBEDDING_MODEL}（火山引擎 ARK）",
        f"- 预警线: 相似度 < {DEFAULT_WARN_THRESHOLD} → WARN（人工复核）",
        f"- 阻断线: 相似度 < {DEFAULT_FAIL_THRESHOLD} → FAIL（阻断交付）",
        f"- 核心 step（阻断影响）: {', '.join(CORE_STEPS)}",
        f"- 论文基线: Technical→Sector 最低 0.397，合格线 0.35",
        "",
    ])

    # 详细结果表
    lines.extend([
        "## 传导相似度明细",
        "",
        "| Step | 相似度 | 状态 | 核心 |",
        "|------|--------|------|------|",
    ])

    for step_name, res in sorted(check_result["results"].items()):
        sim = f"{res['similarity']:.4f}" if res["similarity"] is not None else "N/A"
        status_icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "SKIP": "⏭️"}.get(res["status"], "❓")
        core_mark = "🔴 是" if res.get("is_core") else "否"
        lines.append(f"| {step_name} | {sim} | {status_icon} {res['status']} | {core_mark} |")

    lines.append("")

    # 预警和阻断详情
    if check_result["warnings"]:
        lines.append("## ⚠️ 预警项（需人工复核）")
        for w in check_result["warnings"]:
            lines.append(f"- {w}")
        lines.append("")

    if check_result["fails"]:
        lines.append("## ❌ 阻断项（必须修复后才能交付）")
        for f in check_result["fails"]:
            lines.append(f"- {f}")
        lines.append("")

    # 论文对标
    lines.extend([
        "## 论文对标",
        "",
        "| 论文关系 | 论文数值 | 对应 IR 管线 |",
        "|---------|---------|-------------|",
        "| Quantitative → Sector | 0.397 (fine) | step4_finance → step8 |",
        "| Qualitative → Sector | 0.244 (fine) | step3_biz/step5_mgmt → step8 |",
        "| Macro → PM | 0.203 (fine) | step_macro → step8 |",
        "| News → PM | 0.182 (fine) | step7_risk → step8 |",
        "| Sector → PM | 0.425 (fine) | step2_industry → step8 |",
        "",
        "_注: 以上为论文基线值，仅作参考。_",
    ])

    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================


def main():
    parser = argparse.ArgumentParser(
        description=f"信息传导验证引擎 — IR 管线 Phase 4（{EMBEDDING_MODEL}）"
    )
    parser.add_argument(
        "task_dir",
        nargs="?",
        default=None,
        help="任务目录路径（包含所有 step 输出 .md 文件）",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_WARN_THRESHOLD,
        help=f"预警阈值（默认 {DEFAULT_WARN_THRESHOLD}）",
    )
    parser.add_argument(
        "--fail-threshold",
        type=float,
        default=DEFAULT_FAIL_THRESHOLD,
        help=f"阻断阈值（默认 {DEFAULT_FAIL_THRESHOLD}）",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default="",
        help=f"火山引擎 ARK API Key（也可用环境变量 VOLCES_ARK_API_KEY）",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="",
        help=f"火山引擎 ARK Base URL（默认 {DEFAULT_ARK_BASE_URL}）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON 格式输出",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Markdown 报告格式输出",
    )

    args = parser.parse_args()

    if args.task_dir is None:
        print(f"用法: python info_propagation_check.py <TASK_DIR> [--threshold 0.30] [--json|--markdown]")
        print(f"模型: {EMBEDDING_MODEL}（火山引擎 ARK）")
        print("API Key 优先级: --api-key > VOLCES_ARK_API_KEY")
        print("Base URL 优先级: --base-url > VOLCES_ARK_BASE_URL > 内置默认值")
        sys.exit(0)

    # 获取 API key（优先级: CLI --api-key > VOLCES_ARK_API_KEY > DEFAULT_ARK_API_KEY）
    api_key = args.api_key or os.environ.get("VOLCES_ARK_API_KEY", "") or DEFAULT_ARK_API_KEY
    if not api_key:
        print("❌ 未找到 API Key。请设置方式之一:", file=sys.stderr)
        print("   1. --api-key ark-...", file=sys.stderr)
        print("   2. export VOLCES_ARK_API_KEY=ark-...", file=sys.stderr)
        sys.exit(1)

    base_url = args.base_url or os.environ.get("VOLCES_ARK_BASE_URL", "") or DEFAULT_ARK_BASE_URL

    task_path = Path(args.task_dir)
    if not task_path.exists():
        print(f"❌ 任务目录不存在: {args.task_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        result = check_propagation(
            task_path,
            api_key=api_key,
            base_url=base_url,
            warn_threshold=args.threshold,
            fail_threshold=args.fail_threshold,
        )

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        elif args.markdown:
            print(format_report(result))
        else:
            print(format_report(result))
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
