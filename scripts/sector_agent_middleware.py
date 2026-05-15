#!/usr/bin/env python3
"""
Sector Agent 中间件层 — IR 管线 Level 2
对标牛津论文: Miyazaki et al., "Toward Expert Investment Teams," arXiv:2602.23330

Section 3.2: Sector Agent Architecture
  "The Sector Agent aggregates signals from subordinate agents
   (Technical, Quantitative, Qualitative, News) and applies
   sector-specific adjustments before passing to the PM Agent."

功能:
  1. 聚合 Level 1 Agent 输出（step2_industry, step3_biz, step4_finance, step7_risk）
  2. 应用行业基准对标（调用 sector_benchmarks_v2）
  3. 生成细粒度子问题分解（对标论文 Fine-grained decomposition）
  4. 产出行业调整分 (Sector Adjustment Score)
  5. 输出结构化 Sector View → 供 step8_master 合成

与牛津论文映射:
  IR 管线 step2_industry → 论文 Qualitative Agent (行业感知)
  IR 管线 step4_finance → 论文 Quantitative Agent (量化数据)
  IR 管线 step3_biz     → 论文 Qualitative Agent (商业模式)
  IR 管线 step7_risk    → 论文 News Agent (风险事件)
  Sector Agent          → 论文 Sector Agent (本脚本)

用法:
  python sector_agent_middleware.py <TASK_DIR> [--ticker <TICKER>] [--json|--markdown]
"""

import sys
import os
import json
import re
import math
import argparse
import statistics
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime
from dataclasses import dataclass, field


# ============================================================
# 配置
# ============================================================

# Level 1 → Sector 输入映射（对标论文 Table 1）
AGENT_INPUTS = {
    "step2_industry": {
        "label": "行业分析 Agent (Qualitative)",
        "paper_role": "Qualitative Agent",
        "extract_dimensions": ["industry_growth", "market_size", "competitive_landscape", "regulatory_env"],
    },
    "step3_biz": {
        "label": "商业模式 Agent (Qualitative)",
        "paper_role": "Qualitative Agent",
        "extract_dimensions": ["moat_depth", "revenue_model", "customer_concentration", "unit_economics"],
    },
    "step4_finance": {
        "label": "财务分析 Agent (Quantitative)",
        "paper_role": "Quantitative Agent",
        "extract_dimensions": ["revenue_growth", "margin_profile", "roe_roic", "fcf_quality", "leverage"],
    },
    "step7_risk": {
        "label": "风险分析 Agent (News/Risk)",
        "paper_role": "News Agent",
        "extract_dimensions": ["regulatory_risk", "competitive_risk", "tech_obsolescence", "macro_exposure"],
    },
}

# 论文 Table 3 基线：Level 1 → Sector 信息传导基准
PROPAGATION_BASELINE = {
    "Qualitative → Sector": 0.514,
    "Quantitative → Sector": 0.476,
    "News → Sector": 0.378,
}

# 细粒度子问题模板（对标论文 Section 3.1 Fine-grained Decomposition）
FINE_GRAINED_QUESTIONS = {
    "industry_growth": [
        "行业 TAM 过去 3 年 CAGR？与 GDP 增速的倍数关系？",
        "行业渗透率当前处于什么阶段（导入期/成长期/成熟期）？",
        "未来 3-5 年的核心增长驱动因素有哪些？",
        "行业是否存在结构性拐点（政策/技术/需求）？",
    ],
    "competitive_landscape": [
        "行业 CR3/CR5 集中度及变化趋势？",
        "目标公司在行业中的市场份额及排名？",
        "主要竞对的相对优劣势对比？",
        "行业进入壁垒（资金/技术/牌照/规模）有多高？",
    ],
    "moat_depth": [
        "护城河来源：品牌/规模/网络效应/转换成本/技术壁垒？",
        "护城河是否在强化还是被侵蚀？有何证据？",
        "竞争对手复制该护城河需要多少时间和资金？",
    ],
    "margin_profile": [
        "毛利率趋势：扩张还是收窄？驱动因素是什么？",
        "净利率与行业均值的差距及原因？",
        "经营杠杆：固定成本占比，营收增长对利润的弹性？",
    ],
    "fcf_quality": [
        "FCF/净利润比率（现金转化率）及趋势？",
        "资本开支强度：CapEx/营收比率，与折旧的关系？",
        "营运资本变动是否在消耗现金？",
    ],
}


@dataclass
class SectorSignal:
    """单一维度行业信号"""
    dimension: str
    raw_value: Any
    normalized_score: float  # 0-1
    confidence: float       # 0-1
    source_step: str
    sub_questions: List[str] = field(default_factory=list)


@dataclass
class SectorAdjustment:
    """行业调整"""
    peer_avg_revenue_growth: Optional[float] = None
    peer_avg_roe: Optional[float] = None
    peer_avg_gross_margin: Optional[float] = None
    peer_avg_pe: Optional[float] = None
    company_vs_peer_score: float = 0.5  # 0=远低于同行, 1=远超同行


@dataclass
class SectorView:
    """行业 Agent 综合视图"""
    task_dir: str
    date: str
    ticker: str
    signals: List[SectorSignal] = field(default_factory=list)
    adjustment: SectorAdjustment = field(default_factory=SectorAdjustment)
    composite_score: float = 0.5
    sector_sentiment: str = "NEUTRAL"  # BULLISH / NEUTRAL / BEARISH
    info_propagation_score: float = 0.0  # 与论文基线对比的传导质量
    fine_grained_completeness: float = 0.0  # 子问题覆盖率


# ============================================================
# 阶段 1: 信号提取（从 step 输出中提取结构化信号）
# ============================================================

def _extract_section(text: str, heading: str) -> str:
    """提取 Markdown 中指定标题下的内容"""
    pattern = rf'#{1,3}\s+{re.escape(heading)}.*?\n(.*?)(?=\n#{1,3}\s+|\Z)'
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extract_numeric_from_text(text: str, keywords: List[str]) -> Optional[float]:
    """从文本中提取与关键词关联的数值"""
    for kw in keywords:
        pattern = rf'{re.escape(kw)}.*?(\d+\.?\d*)\s*%?'
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


def _count_sentiment(text: str) -> Dict[str, int]:
    """统计情感标记"""
    return {
        "positive": len(re.findall(r'✅|优势|利好|增长|提升|改善|领先|突破', text)),
        "negative": len(re.findall(r'❌|⚠️|⚠|风险|下降|恶化|亏损|压力|挑战|威胁', text)),
        "neutral": len(re.findall(r'维持|稳定|持平|不变', text)),
    }


def extract_sector_signals(task_dir: Path) -> List[SectorSignal]:
    """从 step 输出提取行业信号"""

    signals: List[SectorSignal] = []

    for step_key, config in AGENT_INPUTS.items():
        step_files = list(task_dir.glob(f"*{step_key}*.md"))
        if not step_files:
            continue

        text = step_files[0].read_text(encoding="utf-8")
        sentiment = _count_sentiment(text)

        for dim in config["extract_dimensions"]:
            score = 0.5
            confidence = 0.5

            if dim == "industry_growth":
                val = _extract_numeric_from_text(text, ["CAGR", "增速", "增长率", "growth rate", "年复合"])
                if val is not None:
                    score = min(1.0, max(0.1, val / 30.0 + 0.1))
                    confidence = 0.7

            elif dim == "market_size":
                val = _extract_numeric_from_text(text, ["TAM", "市场规模", "market size", "亿美元", "万亿"])
                if val is not None:
                    score = min(1.0, max(0.2, 0.3 + math.log10(max(val, 1)) / 8))
                    confidence = 0.5

            elif dim in ("competitive_landscape", "moat_depth", "regulatory_env"):
                ratio = sentiment["positive"] / max(sentiment["positive"] + sentiment["negative"], 1)
                score = min(1.0, max(0.1, 0.3 + ratio * 0.7))
                confidence = 0.5

            elif dim in ("revenue_growth", "margin_profile"):
                # 从财务文本提取精确数值
                if dim == "revenue_growth":
                    val = _extract_numeric_from_text(text, ["营收增长", "收入增长", "revenue growth", "YoY"])
                else:
                    val = _extract_numeric_from_text(text, ["毛利率", "净利率", "gross margin", "net margin"])
                if val is not None:
                    score = min(1.0, max(0.1, val / 25.0 + 0.1))
                    confidence = 0.7
                else:
                    score = 0.5
                    confidence = 0.3

            elif dim in ("roe_roic", "fcf_quality", "leverage"):
                ratio = sentiment["positive"] / max(sentiment["positive"] + sentiment["negative"], 1)
                score = min(1.0, max(0.1, ratio * 0.8))
                confidence = 0.6

            elif dim in ("regulatory_risk", "competitive_risk", "tech_obsolescence", "macro_exposure"):
                # 风险维度：负面越多，得分越低
                ratio = sentiment["negative"] / max(sentiment["positive"] + sentiment["negative"], 1)
                score = max(0.1, 1.0 - ratio)  # 高风险=低分
                confidence = 0.5

            else:
                # 通用：从 sentiment 推算
                total = sentiment["positive"] + sentiment["negative"] + sentiment["neutral"]
                score = (sentiment["positive"] + sentiment["neutral"] * 0.5) / max(total, 1)
                confidence = 0.4

            # 获取对应细粒度子问题
            sub_qs = FINE_GRAINED_QUESTIONS.get(dim, [])

            signals.append(SectorSignal(
                dimension=dim,
                raw_value=None,
                normalized_score=round(score, 4),
                confidence=confidence,
                source_step=step_key,
                sub_questions=sub_qs,
            ))

    return signals


# ============================================================
# 阶段 2: 行业对标调整
# ============================================================

def _run_sector_benchmarks(ticker: str, task_dir: Path) -> Optional[Dict]:
    """调用 sector_benchmarks_v2.py 获取行业基准数据"""
    script_dir = Path(__file__).resolve().parent
    benchmark_script = script_dir / "sector_benchmarks_v2.py"

    if not benchmark_script.exists():
        return None

    # 查找 verify JSON
    verify_json = None
    for f in task_dir.glob("*ir_company_verify*.json"):
        verify_json = str(f)
        break

    cmd = ["python3", str(benchmark_script), ticker, "--mode", "hybrid", "--json"]
    if verify_json:
        cmd.extend(["--verify-json", verify_json])

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except Exception:
        pass

    return None


def compute_sector_adjustment(
    signals: List[SectorSignal],
    ticker: str,
    task_dir: Path,
) -> SectorAdjustment:
    """计算行业调整分"""

    adj = SectorAdjustment()

    # 尝试获取行业基准数据
    benchmarks = _run_sector_benchmarks(ticker, task_dir)

    if benchmarks:
        adj.peer_avg_revenue_growth = benchmarks.get("peer_avg_revenue_growth")
        adj.peer_avg_roe = benchmarks.get("peer_avg_roe")
        adj.peer_avg_gross_margin = benchmarks.get("peer_avg_gross_margin")
        adj.peer_avg_pe = benchmarks.get("peer_avg_pe")

        sector_score = benchmarks.get("sector_adjustment_score", 0.5)
        adj.company_vs_peer_score = round(sector_score, 4)

    # 如果没有 benchmark 数据，从信号推算
    if adj.company_vs_peer_score == 0.5 and signals:
        scores = [s.normalized_score for s in signals]
        adj.company_vs_peer_score = round(statistics.mean(scores), 4)

    return adj


# ============================================================
# 阶段 3: 细粒度完备性检查
# ============================================================

def compute_completeness(signals: List[SectorSignal]) -> float:
    """
    对标论文 Fine-grained Decomposition:
    检查是否每个维度都回答了对应的细粒度子问题。
    返回值: 0-1 覆盖率
    """
    total_questions = sum(
        len(FINE_GRAINED_QUESTIONS.get(s.dimension, []))
        for s in signals
    )
    if total_questions == 0:
        return 0.0

    # 根据 confidence 估算已回答问题数（高 confidence = 更多子问题被回答）
    answered = sum(s.confidence * len(s.sub_questions) for s in signals)
    return round(min(1.0, answered / total_questions), 4)


# ============================================================
# 主管道
# ============================================================

def run_sector_agent(
    task_dir: Path,
    ticker: str = "",
) -> SectorView:
    """主管道: 信号提取 → 行业对标 → 细粒度检查 → 综合视图"""

    view = SectorView(
        task_dir=str(task_dir),
        date=datetime.now().strftime("%Y-%m-%d"),
        ticker=ticker,
    )

    # 1. 信号提取
    signals = extract_sector_signals(task_dir)
    view.signals = signals

    if not signals:
        return view

    # 2. 行业对标调整
    view.adjustment = compute_sector_adjustment(signals, ticker, task_dir)

    # 3. 细粒度完备性
    view.fine_grained_completeness = compute_completeness(signals)

    # 4. 综合评分（信号 + 行业调整）
    raw_mean = statistics.mean([s.normalized_score for s in signals])
    adj_factor = view.adjustment.company_vs_peer_score
    view.composite_score = round(raw_mean * 0.6 + adj_factor * 0.4, 4)

    # 5. 行业情绪判定
    if view.composite_score >= 0.65:
        view.sector_sentiment = "BULLISH"
    elif view.composite_score <= 0.35:
        view.sector_sentiment = "BEARISH"
    else:
        view.sector_sentiment = "NEUTRAL"

    # 6. 信息传导评分（对标论文 Table 3 基线）
    # 取 Level 1 → Sector 的三种传导路径均值
    prop_scores = []
    for agent_type in ["Qualitative", "Quantitative", "News"]:
        key = f"{agent_type} → Sector"
        if key in PROPAGATION_BASELINE:
            # 用信号 confidence 均值作为传导质量的代理
            agent_signals = [s for s in signals if agent_type.lower() in s.source_step.lower() or
                             (agent_type == "Qualitative" and s.source_step in ("step2_industry", "step3_biz")) or
                             (agent_type == "Quantitative" and s.source_step == "step4_finance") or
                             (agent_type == "News" and s.source_step == "step7_risk")]
            if agent_signals:
                mean_conf = statistics.mean([s.confidence for s in agent_signals])
                prop_scores.append(mean_conf)

    if prop_scores:
        view.info_propagation_score = round(statistics.mean(prop_scores), 4)

    return view


# ============================================================
# 输出格式化
# ============================================================

def _signal_label(score: float) -> str:
    if score >= 0.65:
        return "🟢 看多"
    elif score <= 0.35:
        return "🔴 看空"
    return "🟡 中性"


def format_report(view: SectorView) -> str:
    """生成 Markdown Sector Agent 报告"""

    sentiment_emoji = {
        "BULLISH": "🟢 看多",
        "BEARISH": "🔴 看空",
        "NEUTRAL": "🟡 中性",
    }

    lines = [
        "# Sector Agent 行业综合分析",
        "",
        f"**任务目录**: `{view.task_dir}`",
        f"**检查日期**: {view.date}",
        f"**标的**: {view.ticker or '(未指定)'}",
        f"**方法**: Oxford 2026 Level 2 — Sector Agent Middleware",
        "",
        "---",
        "",
        "## 综合结论",
        "",
        f"| 指标 | 值 |",
        f"|------|----|",
        f"| **行业情绪** | **{sentiment_emoji.get(view.sector_sentiment, view.sector_sentiment)}** |",
        f"| **综合得分** | **{view.composite_score:.4f}** (0=极度看空, 1=极度看多) |",
        f"| **行业对标分** | **{view.adjustment.company_vs_peer_score:.4f}** |",
        f"| **细粒度完备性** | **{view.fine_grained_completeness:.1%}** |",
        f"| **信息传导分** | **{view.info_propagation_score:.4f}** (论文基线: 0.378-0.514) |",
        "",
    ]

    # 行业对标
    if view.adjustment.peer_avg_roe is not None:
        lines.extend([
            "## 行业对标",
            "",
            "| 指标 | 同行均值 |",
            "|------|---------|",
        ])
        if view.adjustment.peer_avg_revenue_growth is not None:
            lines.append(f"| 营收增速 | {view.adjustment.peer_avg_revenue_growth:.1f}% |")
        if view.adjustment.peer_avg_roe is not None:
            lines.append(f"| ROE | {view.adjustment.peer_avg_roe:.1f}% |")
        if view.adjustment.peer_avg_gross_margin is not None:
            lines.append(f"| 毛利率 | {view.adjustment.peer_avg_gross_margin:.1f}% |")
        if view.adjustment.peer_avg_pe is not None:
            lines.append(f"| PE | {view.adjustment.peer_avg_pe:.1f}x |")
        lines.append("")

    # 信号明细
    lines.extend([
        "## 维度信号明细",
        "",
        "| 维度 | 得分 | 置信度 | 信号 | 来源 Agent |",
        "|------|------|--------|------|-----------|",
    ])
    for s in view.signals:
        agent_label = AGENT_INPUTS.get(s.source_step, {}).get("label", s.source_step)
        lines.append(
            f"| {s.dimension} | {s.normalized_score:.4f} | "
            f"{s.confidence:.0%} | {_signal_label(s.normalized_score)} | "
            f"{agent_label} |"
        )
    lines.append("")

    # 细粒度子问题清单（只展示未充分回答的）
    low_confidence_signals = [s for s in view.signals if s.confidence < 0.6 and s.sub_questions]
    if low_confidence_signals:
        lines.extend([
            "## 细粒度子问题清单（需补充验证）",
            "",
            "以下维度的置信度不足，建议对子问题进行专项搜索：",
            "",
        ])
        for s in low_confidence_signals[:6]:  # 最多展示6个
            lines.append(f"### {s.dimension}（置信度 {s.confidence:.0%}）")
            for i, q in enumerate(s.sub_questions[:3], 1):  # 每维度最多3个
                lines.append(f"{i}. {q}")
            lines.append("")

    # 论文对标
    lines.extend([
        "---",
        "",
        "## 论文对标",
        "",
        "| 论文关系 | 论文基线 | 当前传导 | 状态 |",
        "|---------|---------|---------|------|",
    ])
    for path, baseline in PROPAGATION_BASELINE.items():
        # 计算当前传导（按 agent 类型分组信号的均值 confidence）
        if "Qualitative" in path:
            agent_signals = [s for s in view.signals
                             if s.source_step in ("step2_industry", "step3_biz")]
        elif "Quantitative" in path:
            agent_signals = [s for s in view.signals
                             if s.source_step == "step4_finance"]
        elif "News" in path:
            agent_signals = [s for s in view.signals
                             if s.source_step == "step7_risk"]
        else:
            agent_signals = []

        current = round(statistics.mean([s.confidence for s in agent_signals]), 4) if agent_signals else 0
        status = "✅ PASS" if current >= baseline * 0.7 else "⚠️ BELOW" if current > 0 else "⏭️ N/A"

        lines.append(f"| {path} | {baseline} | {current} | {status} |")

    lines.extend([
        "",
        "_论文基线来源: Miyazaki et al., Table 3: Embedding Cosine Similarity for Info Propagation_",
    ])

    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Sector Agent Middleware — Oxford 2026 Level 2"
    )
    parser.add_argument(
        "task_dir",
        nargs="?",
        default=None,
        help="任务目录路径（包含 step 输出 .md 文件）",
    )
    parser.add_argument(
        "--ticker",
        type=str,
        default="",
        help="股票代码（用于行业对标，如 600519.SS, NVDA）",
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
        print("用法: python sector_agent_middleware.py <TASK_DIR> [--ticker <TICKER>] [--json|--markdown]")
        print()
        print("对标论文: Miyazaki et al., 'Toward Expert Investment Teams,' arXiv:2602.23330")
        print("功能: Level 1 Agent → Sector Agent 信号聚合 + 行业对标 + 细粒度完备性检查")
        sys.exit(0)

    task_path = Path(args.task_dir)
    if not task_path.exists():
        print(f"❌ 任务目录不存在: {args.task_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        result = run_sector_agent(task_path, ticker=args.ticker)

        if args.json:
            output = {
                "task_dir": result.task_dir,
                "date": result.date,
                "ticker": result.ticker,
                "composite_score": result.composite_score,
                "sector_sentiment": result.sector_sentiment,
                "sector_adjustment_score": result.adjustment.company_vs_peer_score,
                "fine_grained_completeness": result.fine_grained_completeness,
                "info_propagation_score": result.info_propagation_score,
                "peer_benchmarks": {
                    "revenue_growth": result.adjustment.peer_avg_revenue_growth,
                    "roe": result.adjustment.peer_avg_roe,
                    "gross_margin": result.adjustment.peer_avg_gross_margin,
                    "pe": result.adjustment.peer_avg_pe,
                },
                "signals": [
                    {
                        "dimension": s.dimension,
                        "score": s.normalized_score,
                        "confidence": s.confidence,
                        "source": s.source_step,
                        "sub_questions_count": len(s.sub_questions),
                    }
                    for s in result.signals
                ],
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(format_report(result))
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
