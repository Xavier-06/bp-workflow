#!/usr/bin/env python3
"""
技术指标预计算引擎 — IR 管线 Phase 1.2

对标论文：Miyazaki et al., "Toward Expert Investment Teams",
           Oxford EngSci, arXiv:2602.23330, 2026.02
           Technical Agent 技术面分析

11 项标准化技术指标：
  RoC:  5d / 10d / 20d / 30d / 60d / 90d / 180d / 360d
  RSI:  14d
  MACD: MACD 线 / 信号线 / 柱状图
  KDJ:  K / D / J
  BB:   布林带 Z-score（BB_Z）
  Vol:  20 日年化波动率

用法：
  python technical_indicators.py <TICKER> [--json|--markdown]
  python technical_indicators.py 0700.HK --markdown
"""

import sys
import json
import argparse
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf


# ============================================================
# 指标计算
# ============================================================

def _safe_float(val) -> Optional[float]:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return round(float(val), 4)


def calc_rsi(prices: np.ndarray, period: int = 14) -> Optional[float]:
    """RSI = 100 - 100/(1 + RS)，RS = 平均涨幅 / 平均跌幅"""
    if len(prices) < period + 1:
        return None
    deltas = np.diff(prices[-period - 1:])
    gains = np.maximum(deltas, 0)
    losses = np.abs(np.minimum(deltas, 0))
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def calc_macd(prices: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """MACD = EMA(fast) - EMA(slow)，返回 (MACD_line, Signal_line, Histogram)"""
    if len(prices) < slow + signal:
        return None, None, None
    series = pd.Series(prices)
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return (
        round(float(macd_line.iloc[-1]), 4),
        round(float(signal_line.iloc[-1]), 4),
        round(float(histogram.iloc[-1]), 4),
    )


def calc_kdj(prices: np.ndarray, highs: np.ndarray, lows: np.ndarray,
             n: int = 9, m1: int = 3, m2: int = 3) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """KDJ 指标：K / D / J"""
    if len(prices) < n + m1 + m2:
        return None, None, None

    def _rsv(idx):
        h = np.max(highs[idx - n + 1:idx + 1])
        l = np.min(lows[idx - n + 1:idx + 1])
        c = prices[idx]
        if h == l:
            return 50.0
        return (c - l) / (h - l) * 100

    k_vals = []
    d_vals = []
    prev_k = 50.0
    prev_d = 50.0

    for i in range(n - 1, len(prices)):
        rsv = _rsv(i)
        k = prev_k * (m1 - 1) / m1 + rsv / m1
        d = prev_d * (m2 - 1) / m2 + k / m2
        k_vals.append(k)
        d_vals.append(d)
        prev_k = k
        prev_d = d

    if not k_vals:
        return None, None, None

    k = round(k_vals[-1], 2)
    d = round(d_vals[-1], 2)
    j = round(3 * k - 2 * d, 2)
    return k, d, j


def calc_roc(prices: np.ndarray, period: int) -> Optional[float]:
    """Rate of Change = (price_now - price_periods_ago) / price_periods_ago × 100%"""
    if len(prices) < period + 1:
        return None
    return round((prices[-1] - prices[-period - 1]) / prices[-period - 1] * 100, 2)


def calc_volatility(prices: np.ndarray, period: int = 20) -> Optional[float]:
    """年化波动率 (基于日对数收益率)"""
    if len(prices) < period + 1:
        return None
    log_returns = np.diff(np.log(prices[-period - 1:]))
    daily_std = np.std(log_returns)
    return round(daily_std * np.sqrt(252) * 100, 2)


def calc_bb_z(prices: np.ndarray, period: int = 20) -> Optional[float]:
    """布林带 Z-score = (price - MA) / (2 * σ)"""
    if len(prices) < period:
        return None
    window = prices[-period:]
    ma = np.mean(window)
    std = np.std(window)
    if std == 0:
        return 0.0
    return round((prices[-1] - ma) / (2 * std), 4)


# ============================================================
# 主计算函数
# ============================================================

def compute_all(ticker: str, lookback_days: int = 400) -> Dict[str, Any]:
    """
    主入口：输入 yfinance ticker，输出 11 项标准化技术指标。
    """
    stock = yf.Ticker(ticker)

    # 获取历史价格（多拉一些数据确保长周期 RoC 有足够数据）
    end_date = datetime.now()
    start_date = end_date - timedelta(days=max(lookback_days, 400))
    hist = stock.history(start=start_date.strftime("%Y-%m-%d"),
                         end=end_date.strftime("%Y-%m-%d"))

    if hist.empty:
        raise ValueError(f"{ticker} 无历史价格数据")

    closes = hist["Close"].values.astype(float)
    highs = hist["High"].values.astype(float)
    lows = hist["Low"].values.astype(float)
    last_date = hist.index[-1].strftime("%Y-%m-%d")
    latest_price = float(closes[-1])

    # 计算所有指标
    roc_periods = [5, 10, 20, 30, 60, 90, 180, 360]
    roc = {}
    for p in roc_periods:
        roc[f"RoC_{p}d"] = calc_roc(closes, p)

    rsi = calc_rsi(closes, 14)
    macd_m, macd_s, macd_h = calc_macd(closes)
    kdj_k, kdj_d, kdj_j = calc_kdj(closes, highs, lows)
    vol_20 = calc_volatility(closes, 20)
    bb_z = calc_bb_z(closes, 20)

    # 补充：价格位置信息
    ma_20 = round(float(np.mean(closes[-20:])), 2) if len(closes) >= 20 else None
    ma_60 = round(float(np.mean(closes[-60:])), 2) if len(closes) >= 60 else None
    ma_120 = round(float(np.mean(closes[-120:])), 2) if len(closes) >= 120 else None
    ma_200 = round(float(np.mean(closes[-200:])), 2) if len(closes) >= 200 else None

    # 短期动量方向
    roc_5 = roc.get("RoC_5d")
    roc_20 = roc.get("RoC_20d")
    roc_60 = roc.get("RoC_60d")
    short_dir = "↑" if (roc_5 and roc_5 > 0) else ("↓" if (roc_5 and roc_5 < 0) else "→")
    mid_dir = "↑" if (roc_20 and roc_20 > 0) else ("↓" if (roc_20 and roc_20 < 0) else "→")
    long_dir = "↑" if (roc_60 and roc_60 > 0) else ("↓" if (roc_60 and roc_60 < 0) else "→")

    return {
        "ticker": ticker,
        "date": end_date.strftime("%Y-%m-%d"),
        "last_trading_day": last_date,
        "latest_price": round(latest_price, 2),
        "price_moving_averages": {
            "MA_20": ma_20,
            "MA_60": ma_60,
            "MA_120": ma_120,
            "MA_200": ma_200,
        },
        "roc": roc,
        "momentum_direction": {
            "short": short_dir,
            "medium": mid_dir,
            "long": long_dir,
        },
        "rsi": {"RSI_14": rsi},
        "macd": {
            "MACD_line": macd_m,
            "Signal_line": macd_s,
            "Histogram": macd_h,
            "direction": "金叉" if (macd_m and macd_s and macd_m > macd_s) else ("死叉" if (macd_m and macd_s and macd_m < macd_s) else "N/A"),
        },
        "kdj": {
            "K": kdj_k,
            "D": kdj_d,
            "J": kdj_j,
        },
        "bollinger": {
            "BB_Z": bb_z,
            "position": "超买区" if (bb_z and bb_z > 1.0) else ("超卖区" if (bb_z and bb_z < -1.0) else ("正常区" if bb_z else "N/A")),
        },
        "volatility": {
            "Volatility_20_annualized": vol_20,
        },
    }


# ============================================================
# 输出格式化
# ============================================================

def format_markdown(result: Dict[str, Any]) -> str:
    """生成 Markdown 技术指标摘要表"""

    def fmt(val, suffix=""):
        if val is None:
            return "N/A"
        if isinstance(val, float):
            return f"{val:+.2f}{suffix}" if val < 0 and val != 0 else f"{val:.2f}{suffix}"
        return str(val)

    lines = [
        f"## 技术指标摘要 — {result['ticker']}",
        f"_最新交易日: {result.get('last_trading_day', 'N/A')} ｜ 最新价: {result.get('latest_price', 'N/A')} ｜ 数据截至: {result['date']}_",
        "",
    ]

    # 价格 & 均线
    lines.append("### 价格与均线")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    ma = result.get("price_moving_averages", {})
    lines.append(f"| 最新价 | {result.get('latest_price', 'N/A')} |")
    lines.append(f"| MA(20) | {fmt(ma.get('MA_20'))} |")
    lines.append(f"| MA(60) | {fmt(ma.get('MA_60'))} |")
    lines.append(f"| MA(120) | {fmt(ma.get('MA_120'))} |")
    lines.append(f"| MA(200) | {fmt(ma.get('MA_200'))} |")
    lines.append("")

    # RoC 多周期
    lines.append("### 动量指标 — RoC 多周期")
    lines.append("| 周期 | RoC |")
    lines.append("|------|-----|")
    for period, val in result["roc"].items():
        lines.append(f"| {period.replace('RoC_', '')} | {fmt(val, '%')} |")
    lines.append("")

    # 动量方向
    md = result["momentum_direction"]
    lines.append(f"**动量方向**：短期 {md.get('short', '→')} ｜ 中期 {md.get('medium', '→')} ｜ 长期 {md.get('long', '→')}")
    lines.append("")

    # RSI
    lines.append("### 趋势指标")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    rsi = result["rsi"]
    lines.append(f"| RSI(14) | {fmt(rsi.get('RSI_14'))} |")
    lines.append("")

    # MACD
    lines.append("### MACD")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    macd = result["macd"]
    lines.append(f"| MACD 线 | {fmt(macd.get('MACD_line'))} |")
    lines.append(f"| 信号线 | {fmt(macd.get('Signal_line'))} |")
    lines.append(f"| 柱状图 | {fmt(macd.get('Histogram'))} |")
    lines.append(f"| 方向 | {macd.get('direction', 'N/A')} |")
    lines.append("")

    # KDJ
    lines.append("### KDJ")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    kdj = result["kdj"]
    lines.append(f"| K | {fmt(kdj.get('K'))} |")
    lines.append(f"| D | {fmt(kdj.get('D'))} |")
    lines.append(f"| J | {fmt(kdj.get('J'))} |")
    lines.append("")

    # Bollinger
    lines.append("### 布林带")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    bb = result["bollinger"]
    lines.append(f"| BB Z-score (20d) | {fmt(bb.get('BB_Z'))} |")
    lines.append(f"| 位置 | {bb.get('position', 'N/A')} |")
    lines.append("")

    # Volatility
    lines.append("### 波动率")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    vol = result["volatility"]
    lines.append(f"| 年化波动率 (20d) | {fmt(vol.get('Volatility_20_annualized'), '%')} |")

    return "\n".join(lines)


def format_json_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    """生成简化 JSON（适合嵌入 step brief）"""
    return {
        "ticker": result["ticker"],
        "date": result["date"],
        "last_trading_day": result.get("last_trading_day"),
        "latest_price": result.get("latest_price"),
        "roc": result["roc"],
        "rsi_14": result["rsi"].get("RSI_14"),
        "macd_m": result["macd"].get("MACD_line"),
        "macd_s": result["macd"].get("Signal_line"),
        "macd_h": result["macd"].get("Histogram"),
        "kdj_k": result["kdj"].get("K"),
        "kdj_d": result["kdj"].get("D"),
        "kdj_j": result["kdj"].get("J"),
        "bb_z": result["bollinger"].get("BB_Z"),
        "vol_20": result["volatility"].get("Volatility_20_annualized"),
        "ma_20": result["price_moving_averages"].get("MA_20"),
        "ma_60": result["price_moving_averages"].get("MA_60"),
        "ma_200": result["price_moving_averages"].get("MA_200"),
    }


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="技术指标预计算引擎 — 对标牛津论文 Technical Agent"
    )
    parser.add_argument(
        "ticker",
        nargs="?",
        default=None,
        help="股票代码（yfinance 格式，如 0700.HK, AAPL）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON 格式输出（供 Agent 消费）",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Markdown 表格格式输出（供 step brief 嵌入）",
    )
    parser.add_argument(
        "--json-summary",
        action="store_true",
        help="简化 JSON 格式（仅关键指标，适合嵌入 step brief）",
    )

    args = parser.parse_args()

    if args.ticker is None:
        print("用法: python technical_indicators.py <TICKER> [--json|--markdown|--json-summary]")
        print("示例: python technical_indicators.py 0700.HK --markdown")
        sys.exit(0)

    try:
        result = compute_all(args.ticker)

        if args.json_summary:
            print(json.dumps(format_json_summary(result), ensure_ascii=False, indent=2))
        elif args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        elif args.markdown:
            print(format_markdown(result))
        else:
            print(format_markdown(result))
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
