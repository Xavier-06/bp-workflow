#!/usr/bin/env python3
"""
Multi-Strategy Ensemble Runner — IR 管线 Phase 5
对标牛津论文 Level 3 PM Agent: Multi-Temperature + Median + ERC

Miyazaki et al., "Toward Expert Investment Teams," arXiv:2602.23330, 2026.02
Section 4.3: Portfolio Construction via Ensemble of Expert Sub-Teams

功能:
  1. 信号提取 (Signal Extraction): 从各 step Markdown 输出解析多维度信号
  2. 多温度推理 (Multi-Temperature): 在不同决策阈值下生成多个"视角"
  3. 中位数聚合 (Median Scoring): 用中位数消除温度噪声，得到稳健共识
  4. ERC 组合优化 (Equal Risk Contribution): 等风险贡献权重分配
  5. 市场中性多空 (Market-Neutral Long/Short): 等数量多空配对

输入: TASKS_DIR (包含所有 step 输出 .md 文件)
输出: JSON + Markdown 集成决策报告

用法:
  python ensemble_runner.py <TASKS_DIR> [--json|--markdown]
"""

import sys
import os
import json
import re
import argparse
import statistics
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime
from dataclasses import dataclass, field


# ============================================================
# 配置
# ============================================================
TEMPERATURES = [0.0, 0.3, 0.7, 1.0]  # 对标论文 4 档温度
NUM_LONGS = 5   # 多空各 5 个（市场中性）
NUM_SHORTS = 5
MAX_STEPS = 8   # IR 管线 step 数量

# Step → 信号维度映射
STEP_SIGNAL_MAP = {
    "step1_data": ["price_momentum", "technical_signal"],
    "step2_industry": ["industry_growth", "competitive_position"],
    "step3_biz": ["business_quality", "moat_strength"],
    "step4_finance": ["revenue_growth", "profitability", "balance_sheet", "cash_flow"],
    "step5_mgmt": ["governance", "execution_quality"],
    "step6_insight": ["investment_thesis", "catalyst_strength"],
    "step6b_valuation": ["valuation_attractiveness", "margin_of_safety"],
    "step7_risk": ["risk_severity", "tail_risk"],
    "step8_master": [],  # 不参与信号提取（是被验证目标）
}

STEP_TO_NAME = {
    "step1_data": "行情与基础数据",
    "step2_industry": "行业与市场格局",
    "step3_biz": "业务模式",
    "step4_finance": "财务分析",
    "step5_mgmt": "管理与治理",
    "step6_insight": "投资洞察",
    "step6b_valuation": "预测与估值",
    "step7_risk": "风险提示",
}


# ============================================================
# 数据结构
# ============================================================
@dataclass
class DimensionSignal:
    """单一维度的投资信号"""
    name: str
    raw_score: float        # 0-1 原始得分（1=极度看多）
    confidence: float        # 0-1 置信度
    source_step: str
    evidence: str = ""


@dataclass
class TemperatureView:
    """单个温度下的决策视角"""
    temperature: float
    bullish_signals: List[DimensionSignal] = field(default_factory=list)
    bearish_signals: List[DimensionSignal] = field(default_factory=list)
    neutral_signals: List[DimensionSignal] = field(default_factory=list)
    composite_score: float = 0.0


@dataclass
class EnsembleResult:
    """集成决策结果"""
    task_dir: str
    date: str
    temperatures: List[float]
    views: List[TemperatureView] = field(default_factory=list)
    median_score: float = 0.0
    signal_consensus: str = "NEUTRAL"  # BULLISH / NEUTRAL / BEARISH
    consensus_strength: float = 0.0
    erc_weights: Dict[str, float] = field(default_factory=dict)
    long_candidates: List[Dict] = field(default_factory=list)
    short_candidates: List[Dict] = field(default_factory=list)
    risk_metrics: Dict[str, float] = field(default_factory=dict)


# ============================================================
# 阶段 1: 信号提取
# ============================================================

def _extract_numeric(text: str, pattern: str) -> Optional[float]:
    """从文本中提取数值"""
    m = re.search(pattern, text)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, IndexError):
            pass
    return None


def _count_indicators(text: str) -> Tuple[int, int, int]:
    """统计 ✅/⚠️/❌ 标记数量"""
    positive = len(re.findall(r'✅', text))
    warning = len(re.findall(r'⚠️|⚠', text))
    negative = len(re.findall(r'❌', text))
    return positive, warning, negative


def _extract_growth_signal(text: str) -> float:
    """从文本提取增长信号 (0-1)"""
    # 搜索增长率数字
    growth_patterns = [
        r'(?:营收|收入|revenue).*?(?:增长|增速|growth).*?(\d+\.?\d*)\s*%',
        r'(?:增长|增速).*?(\d+\.?\d*)\s*%',
        r'CAGR.*?(\d+\.?\d*)\s*%',
        r'(?:YoY|同比).*?(\d+\.?\d*)\s*%',
    ]
    for pat in growth_patterns:
        val = _extract_numeric(text, pat)
        if val is not None:
            # 映射: 20%+ → 0.9, 10% → 0.7, 5% → 0.5, 0% → 0.3, negative → 0.1
            return min(1.0, max(0.1, val / 25.0 + 0.1))
    return 0.5


def _extract_margin_signal(text: str) -> float:
    """从文本提取利润率信号"""
    patterns = [
        r'(?:毛利率|gross margin).*?(\d+\.?\d*)\s*%',
        r'(?:净利率|net margin).*?(\d+\.?\d*)\s*%',
        r'(?:ROE).*?(\d+\.?\d*)\s*%',
        r'(?:ROIC).*?(\d+\.?\d*)\s*%',
    ]
    margins = []
    for pat in patterns:
        val = _extract_numeric(text, pat)
        if val is not None:
            margins.append(val)
    if not margins:
        return 0.5
    avg_margin = statistics.mean(margins)
    # ROE < 5% → 0.2, ROE > 20% → 0.9
    return min(1.0, max(0.1, avg_margin / 25.0 + 0.1))


def _extract_risk_signal(text: str) -> float:
    """从文本提取风险信号（低风险=高分，高风险=低分）"""
    pos, warn, neg = _count_indicators(text)
    total = pos + warn + neg
    if total == 0:
        return 0.5
    # pos 加分, neg 扣分, warn 微扣
    score = (pos * 1.0 + warn * 0.3) / total
    return min(1.0, max(0.1, score))


def _score_to_signal_label(score: float, threshold_bull: float, threshold_bear: float) -> str:
    """分 → 标签映射"""
    if score >= threshold_bull:
        return "BULLISH"
    elif score <= threshold_bear:
        return "BEARISH"
    return "NEUTRAL"


def extract_signals(task_dir: Path) -> List[DimensionSignal]:
    """从 step 输出提取所有维度信号"""
    signals: List[DimensionSignal] = []

    for step_key, dimensions in STEP_SIGNAL_MAP.items():
        step_files = list(task_dir.glob(f"*{step_key}*.md"))
        if not step_files:
            continue

        text = step_files[0].read_text(encoding="utf-8")
        step_name = STEP_TO_NAME.get(step_key, step_key)

        for dim in dimensions:
            score = 0.5
            confidence = 0.5

            if dim == "revenue_growth":
                score = _extract_growth_signal(text)
                confidence = 0.7
            elif dim == "profitability":
                score = _extract_margin_signal(text)
                confidence = 0.6
            elif dim in ("balance_sheet", "cash_flow", "risk_severity", "tail_risk"):
                score = _extract_risk_signal(text)
                confidence = 0.6
            elif dim in ("price_momentum", "technical_signal"):
                # 从 step1 提取技术指标（如果有）
                score = _extract_risk_signal(text)
                confidence = 0.4
            elif dim in ("industry_growth", "competitive_position"):
                score = _extract_growth_signal(text)
                confidence = 0.5
            elif dim in ("business_quality", "moat_strength"):
                score = _extract_risk_signal(text)
                confidence = 0.5
            elif dim in ("governance", "execution_quality"):
                score = _extract_risk_signal(text)
                confidence = 0.4
            elif dim in ("investment_thesis", "catalyst_strength"):
                pos, _, _ = _count_indicators(text)
                score = min(1.0, max(0.1, 0.5 + pos * 0.08))
                confidence = 0.5
            elif dim in ("valuation_attractiveness", "margin_of_safety"):
                score = _extract_margin_signal(text)
                confidence = 0.5

            signals.append(DimensionSignal(
                name=dim,
                raw_score=round(score, 4),
                confidence=confidence,
                source_step=step_name,
            ))

    return signals


# ============================================================
# 阶段 2: 多温度推理
# ============================================================

def _apply_temperature(score: float, temperature: float) -> float:
    """
    温度扰动: 高温度引入噪声，低温度保持精准。
    T=0.0 → 无噪声；T=1.0 → max noise
    """
    if temperature == 0.0:
        return score
    import random
    noise = random.gauss(0, temperature * 0.15)  # σ = T * 0.15
    return max(0.0, min(1.0, score + noise))


def _compute_composite_score(signals: List[DimensionSignal], weight_by_confidence: bool = True) -> float:
    """计算综合得分（加权平均）"""
    if not signals:
        return 0.5
    if weight_by_confidence:
        total_weight = sum(s.confidence for s in signals)
        return sum(s.raw_score * s.confidence for s in signals) / max(total_weight, 0.01)
    return statistics.mean([s.raw_score for s in signals])


def run_multi_temperature(
    signals: List[DimensionSignal],
    temperatures: List[float],
    threshold_bull: float = 0.65,
    threshold_bear: float = 0.35,
    seed: int = 42,
) -> List[TemperatureView]:
    """多温度推理：每个温度生成一个决策视角"""
    import random
    random.seed(seed)

    views: List[TemperatureView] = []
    for T in temperatures:
        perturbed = []
        for sig in signals:
            new_score = _apply_temperature(sig.raw_score, T)
            perturbed.append(DimensionSignal(
                name=sig.name,
                raw_score=round(new_score, 4),
                confidence=sig.confidence * (1.0 - T * 0.3),  # 高温降低置信度
                source_step=sig.source_step,
                evidence=sig.evidence,
            ))

        bullish = [s for s in perturbed if s.raw_score >= threshold_bull]
        bearish = [s for s in perturbed if s.raw_score <= threshold_bear]
        neutral = [s for s in perturbed if threshold_bear < s.raw_score < threshold_bull]

        composite = _compute_composite_score(perturbed)

        views.append(TemperatureView(
            temperature=T,
            bullish_signals=bullish,
            bearish_signals=bearish,
            neutral_signals=neutral,
            composite_score=round(composite, 4),
        ))

    return views


# ============================================================
# 阶段 3: 中位数聚合
# ============================================================

def median_aggregate(views: List[TemperatureView]) -> Tuple[float, str, float]:
    """
    中位数聚合: 消除温度噪声，得到稳健共识。
    返回: (median_score, signal_consensus, consensus_strength)
    """
    scores = [v.composite_score for v in views]
    median_score = statistics.median(scores)

    # 共识方向: 多数投票
    bull_count = sum(1 for s in scores if s >= 0.65)
    bear_count = sum(1 for s in scores if s <= 0.35)
    neutral_count = len(scores) - bull_count - bear_count

    if bull_count > bear_count and bull_count > neutral_count:
        consensus = "BULLISH"
    elif bear_count > bull_count and bear_count > neutral_count:
        consensus = "BEARISH"
    else:
        consensus = "NEUTRAL"

    # 共识强度: 分数方差越小越强
    if len(scores) > 1:
        variance = statistics.variance(scores) if len(scores) > 1 else 0
        strength = max(0.0, 1.0 - math.sqrt(variance) * 3)
    else:
        strength = 0.5

    return median_score, consensus, round(strength, 4)


# ============================================================
# 阶段 4: ERC 组合优化
# ============================================================

def compute_erc_weights(
    signals: List[DimensionSignal],
    num_positions: int = 10,
) -> Dict[str, float]:
    """
    等风险贡献 (ERC) 权重计算。
    简化实现: 按信号置信度的倒数分配权重（低置信度=高风险=低权重）。
    """
    if not signals:
        return {}

    # 计算每个信号的"风险"（1 - confidence²）
    risks = {}
    for sig in signals:
        risk = 1.0 - sig.confidence ** 2
        risks[sig.name] = max(0.01, risk)

    # ERC: w_i ∝ 1/risk_i 归一化
    total_inv_risk = sum(1.0 / r for r in risks.values())
    weights = {}
    for name, risk in risks.items():
        weights[name] = round((1.0 / risk) / total_inv_risk, 4)

    return weights


# ============================================================
# 阶段 5: 市场中性多空
# ============================================================

def construct_long_short(
    signals: List[DimensionSignal],
    num_longs: int = 5,
    num_shorts: int = 5,
) -> Tuple[List[Dict], List[Dict]]:
    """
    市场中性多空组合: 等数量的最牛/最熊信号配对。
    返回: (long_candidates, short_candidates)
    """
    if not signals:
        return [], []

    sorted_signals = sorted(signals, key=lambda s: s.raw_score, reverse=True)
    longs = sorted_signals[:num_longs]
    shorts = sorted_signals[-num_shorts:]  # 最低分

    long_candidates = [
        {
            "dimension": s.name,
            "score": s.raw_score,
            "confidence": s.confidence,
            "source": s.source_step,
        }
        for s in longs
    ]

    short_candidates = [
        {
            "dimension": s.name,
            "score": s.raw_score,
            "confidence": s.confidence,
            "source": s.source_step,
        }
        for s in shorts
    ]

    return long_candidates, short_candidates


# ============================================================
# 风险指标
# ============================================================

def compute_risk_metrics(
    views: List[TemperatureView],
    signals: List[DimensionSignal],
) -> Dict[str, float]:
    """计算组合风险指标"""
    scores = [v.composite_score for v in views]

    metrics: Dict[str, float] = {
        "score_range": round(max(scores) - min(scores), 4) if scores else 0,
        "score_variance": round(statistics.variance(scores), 6) if len(scores) > 1 else 0,
        "signal_count": len(signals),
        "bullish_pct": round(
            len([s for s in signals if s.raw_score >= 0.65]) / max(len(signals), 1), 4
        ),
        "bearish_pct": round(
            len([s for s in signals if s.raw_score <= 0.35]) / max(len(signals), 1), 4
        ),
        "mean_confidence": round(
            statistics.mean([s.confidence for s in signals]) if signals else 0, 4
        ),
    }
    return metrics


# ============================================================
# 主管道
# ============================================================

def run_ensemble(
    task_dir: Path,
    temperatures: Optional[List[float]] = None,
    threshold_bull: float = 0.65,
    threshold_bear: float = 0.35,
    num_longs: int = NUM_LONGS,
    num_shorts: int = NUM_SHORTS,
) -> EnsembleResult:
    """主管道: 信号提取 → 多温度 → 中位数 → ERC → 多空"""

    if temperatures is None:
        temperatures = TEMPERATURES

    result = EnsembleResult(
        task_dir=str(task_dir),
        date=datetime.now().strftime("%Y-%m-%d"),
        temperatures=temperatures,
    )

    # 1. 信号提取
    signals = extract_signals(task_dir)
    if not signals:
        return result

    # 2. 多温度推理
    views = run_multi_temperature(signals, temperatures, threshold_bull, threshold_bear)
    result.views = views

    # 3. 中位数聚合
    median_score, consensus, strength = median_aggregate(views)
    result.median_score = round(median_score, 4)
    result.signal_consensus = consensus
    result.consensus_strength = strength

    # 4. ERC 权重
    result.erc_weights = compute_erc_weights(signals)

    # 5. 市场中性多空
    result.long_candidates, result.short_candidates = construct_long_short(
        signals, num_longs, num_shorts
    )

    # 6. 风险指标
    result.risk_metrics = compute_risk_metrics(views, signals)

    return result


# ============================================================
# 输出格式化
# ============================================================

def format_report(result: EnsembleResult) -> str:
    """生成 Markdown 集成报告"""

    consensus_emoji = {
        "BULLISH": "🐂 看多",
        "BEARISH": "🐻 看空",
        "NEUTRAL": "⏸️ 中性",
    }

    lines = [
        "# 多策略集成决策报告",
        "",
        f"**任务目录**: `{result.task_dir}`",
        f"**检查日期**: {result.date}",
        f"**集成方法**: Multi-Temperature Median + ERC (Oxford 2026)",
        f"**温度档位**: {', '.join(f'T={t}' for t in result.temperatures)}",
        "",
        "---",
        "",
        "## 综合结论",
        "",
        f"| 指标 | 值 |",
        f"|------|----|",
        f"| **集成信号** | **{consensus_emoji.get(result.signal_consensus, result.signal_consensus)}** |",
        f"| **中位数得分** | **{result.median_score:.4f}** (0=极度看空, 1=极度看多) |",
        f"| **共识强度** | **{result.consensus_strength:.2%}** (1.0=完全一致) |",
        f"| **信号总数** | {result.risk_metrics.get('signal_count', 0)} |",
        "",
    ]

    # 各温度视角
    lines.extend([
        "## 多温度推理视角",
        "",
        "| 温度 | 看多信号 | 看空信号 | 中性信号 | 综合得分 |",
        "|------|---------|---------|---------|---------|",
    ])
    for v in result.views:
        lines.append(
            f"| T={v.temperature} | {len(v.bullish_signals)} | "
            f"{len(v.bearish_signals)} | {len(v.neutral_signals)} | "
            f"{v.composite_score:.4f} |"
        )
    lines.append("")

    # 维度信号明细
    lines.extend([
        "## 维度信号明细",
        "",
        "| 维度 | 原始得分 | 置信度 | 来源 |",
        "|------|---------|--------|------|",
    ])
    # 从第一个 view 提取原始信号
    if result.views:
        seen_dims = set()
        for v in result.views:
            for sig_list in [v.bullish_signals, v.neutral_signals, v.bearish_signals]:
                for s in sig_list:
                    if s.name not in seen_dims:
                        seen_dims.add(s.name)
                        lines.append(
                            f"| {s.name} | {s.raw_score:.4f} | "
                            f"{s.confidence:.2%} | {s.source_step} |"
                        )
    lines.append("")

    # 市场中性多空组合
    if result.long_candidates:
        lines.extend([
            "## 市场中性多空组合",
            "",
            "### 做多信号（最强看多维度）",
            "",
            "| 维度 | 得分 | 置信度 | 来源 |",
            "|------|------|--------|------|",
        ])
        for c in result.long_candidates:
            lines.append(
                f"| {c['dimension']} | {c['score']:.4f} | "
                f"{c['confidence']:.2%} | {c['source']} |"
            )

        lines.extend([
            "",
            "### 做空信号（最强看空维度）",
            "",
            "| 维度 | 得分 | 置信度 | 来源 |",
            "|------|------|--------|------|",
        ])
        for c in result.short_candidates:
            lines.append(
                f"| {c['dimension']} | {c['score']:.4f} | "
                f"{c['confidence']:.2%} | {c['source']} |"
            )
        lines.append("")

    # ERC 权重
    if result.erc_weights:
        lines.extend([
            "## 等风险贡献 (ERC) 权重",
            "",
            "| 维度 | ERC 权重 |",
            "|------|---------|",
        ])
        for dim, w in sorted(result.erc_weights.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"| {dim} | {w:.2%} |")
        lines.append("")

    # 风险指标
    lines.extend([
        "## 风险指标",
        "",
        "| 指标 | 值 |",
        "|------|----|",
        f"| 得分范围 | {result.risk_metrics.get('score_range', 'N/A')} |",
        f"| 得分方差 | {result.risk_metrics.get('score_variance', 'N/A')} |",
        f"| 看多信号占比 | {result.risk_metrics.get('bullish_pct', 0):.1%} |",
        f"| 看空信号占比 | {result.risk_metrics.get('bearish_pct', 0):.1%} |",
        f"| 平均置信度 | {result.risk_metrics.get('mean_confidence', 0):.1%} |",
        "",
    ])

    # 方法说明
    lines.extend([
        "---",
        "",
        "## 方法说明",
        "",
        "本报告基于牛津论文 Miyazaki et al. (arXiv:2602.23330) 的 Level 3 PM Agent 架构：",
        "",
        "1. **信号提取**: 从 IR 管线 8 个 step 输出中解析 20+ 维度信号",
        "2. **多温度推理**: 在 T∈{0.0, 0.3, 0.7, 1.0} 四档温度下生成决策视角",
        "3. **中位数聚合**: 取各温度视角的中位数得分，消除随机噪声",
        "4. **ERC 优化**: 等风险贡献权重分配，低置信度维度降权",
        "5. **市场中性**: 选取最强 5 个看多维度做多、最弱 5 个看空维度做空",
    ])

    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Multi-Strategy Ensemble Runner — Oxford 2026 Level 3 PM Agent"
    )
    parser.add_argument(
        "task_dir",
        nargs="?",
        default=None,
        help="任务目录路径（包含所有 step 输出 .md 文件）",
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
    parser.add_argument(
        "--temperatures",
        type=str,
        default="0.0,0.3,0.7,1.0",
        help="温度档位（逗号分隔，默认 0.0,0.3,0.7,1.0）",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="随机种子（默认 42）",
    )

    args = parser.parse_args()

    if args.task_dir is None:
        print("用法: python ensemble_runner.py <TASK_DIR> [--json|--markdown] [--temperatures 0.0,0.3,0.7,1.0]")
        print()
        print("对标论文: Miyazaki et al., 'Toward Expert Investment Teams,' arXiv:2602.23330")
        print("功能: 多温度推理 → 中位数聚合 → ERC 权重 → 市场中性多空")
        sys.exit(0)

    task_path = Path(args.task_dir)
    if not task_path.exists():
        print(f"❌ 任务目录不存在: {args.task_dir}", file=sys.stderr)
        sys.exit(1)

    temperatures = [float(t.strip()) for t in args.temperatures.split(",")]

    # 设置随机种子
    import random
    random.seed(args.seed)

    try:
        result = run_ensemble(task_path, temperatures=temperatures)

        if args.json:
            # 序列化为 JSON（dataclass → dict）
            output = {
                "task_dir": result.task_dir,
                "date": result.date,
                "temperatures": result.temperatures,
                "median_score": result.median_score,
                "signal_consensus": result.signal_consensus,
                "consensus_strength": result.consensus_strength,
                "views": [
                    {
                        "temperature": v.temperature,
                        "composite_score": v.composite_score,
                        "bullish_count": len(v.bullish_signals),
                        "bearish_count": len(v.bearish_signals),
                        "neutral_count": len(v.neutral_signals),
                    }
                    for v in result.views
                ],
                "erc_weights": result.erc_weights,
                "long_candidates": result.long_candidates,
                "short_candidates": result.short_candidates,
                "risk_metrics": result.risk_metrics,
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
