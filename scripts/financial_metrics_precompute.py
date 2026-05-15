#!/usr/bin/env python3
"""
财务指标预计算引擎 — IR 管线 Phase 1.2

对标论文：Miyazaki et al., "Toward Expert Investment Teams",
           Oxford EngSci, arXiv:2602.23330, 2026.02
           Quantitative Agent 五大维度

五大维度指标：
  1. Profitability: ROE, ROA, Op Margin, FCF Margin（TTM 口径）
  2. Safety:       Equity Ratio, Current Ratio, D/E（最新季报）
  3. Valuation:    P/E(TTM), EV/EBITDA, Dividend Yield
  4. Efficiency:   Total Asset Turnover, Inventory Turn Days（TTM）
  5. Growth:       Revenue CAGR(3Y), EPS Growth（年报数据）

每个指标输出：当前值 + 环比变化（diff）
"""

import sys
import json
import argparse
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf


# ============================================================
# 核心计算函数
# ============================================================

def _safe_div(a, b):
    """安全除法，b=0 或任一为 None/NaN 时返回 None"""
    if a is None or b is None:
        return None
    try:
        if b == 0 or np.isnan(a) or np.isnan(b):
            return None
        return float(a) / float(b)
    except (TypeError, ValueError):
        return None


def _get_latest(series: pd.Series) -> Optional[float]:
    """获取 Series 最后一个非 NaN 值"""
    valid = series.dropna()
    if len(valid) == 0:
        return None
    return float(valid.iloc[-1])


def _get_prev(series: pd.Series, periods_back: int = 1) -> Optional[float]:
    """获取 Series 倒数第 N 个非 NaN 值"""
    valid = series.dropna()
    if len(valid) <= periods_back:
        return None
    return float(valid.iloc[-(periods_back + 1)])


def calc_roe(net_income: np.ndarray, equity: np.ndarray) -> Tuple[Optional[float], Optional[float]]:
    """ROE = Net Income / Equity × 100%"""
    current = None
    prev = None
    for i in range(len(net_income) - 1, -1, -1):
        val = _safe_div(net_income[i], equity[i])
        if val is not None:
            current = val * 100
            break
    if current is not None:
        for i in range(len(net_income) - 1, 0, -1):
            val = _safe_div(net_income[i - 1], equity[i - 1])
            if val is not None:
                prev = val * 100
                break
    diff = round(current - prev, 2) if current is not None and prev is not None else None
    return round(current, 2) if current else None, diff


def calc_roa(net_income: np.ndarray, total_assets: np.ndarray) -> Tuple[Optional[float], Optional[float]]:
    """ROA = Net Income / Total Assets × 100%"""
    current = _safe_div(_get_latest(pd.Series(net_income)), _get_latest(pd.Series(total_assets)))
    current = round(current * 100, 2) if current else None
    prev_ni = _get_prev(pd.Series(net_income))
    prev_ta = _get_prev(pd.Series(total_assets))
    prev = _safe_div(prev_ni, prev_ta)
    prev = round(prev * 100, 2) if prev else None
    diff = round(current - prev, 2) if current is not None and prev is not None else None
    return current, diff


def calc_op_margin(op_income, revenue) -> Tuple[Optional[float], Optional[float]]:
    """Operating Margin = Operating Income / Revenue × 100%"""
    current = _safe_div(_get_latest(pd.Series(op_income)), _get_latest(pd.Series(revenue)))
    current = round(current * 100, 2) if current else None
    prev_oi = _get_prev(pd.Series(op_income))
    prev_rev = _get_prev(pd.Series(revenue))
    prev = _safe_div(prev_oi, prev_rev)
    prev = round(prev * 100, 2) if prev else None
    diff = round(current - prev, 2) if current is not None and prev is not None else None
    return current, diff


def calc_cagr(values: np.ndarray, years: int = 3) -> Optional[float]:
    """CAGR = (End / Start)^(1/years) - 1 × 100%"""
    valid = [v for v in values if v is not None and v > 0 and not np.isnan(v)]
    if len(valid) < 2:
        return None
    end = valid[-1]
    start = valid[0]
    n = len(valid) - 1  # 实际年数
    if n <= 0 or start <= 0:
        return None
    return round(((end / start) ** (1.0 / n) - 1) * 100, 2)


def calc_eps_growth(eps_values: np.ndarray) -> Tuple[Optional[float], Optional[str]]:
    """EPS Growth = (current - prev) / |prev| × 100%"""
    current = _get_latest(pd.Series(eps_values))
    prev = _get_prev(pd.Series(eps_values))
    if current is None or prev is None:
        return None, None
    if prev == 0:
        return None, "prior EPS=0"
    growth = round((current - prev) / abs(prev) * 100, 2)
    direction = "增长" if growth > 0 else "下滑"
    return growth, direction


def calc_de_ratio(total_debt: np.ndarray, equity: np.ndarray) -> Tuple[Optional[float], Optional[float]]:
    """D/E = Total Debt / Equity"""
    current = _safe_div(_get_latest(pd.Series(total_debt)), _get_latest(pd.Series(equity)))
    current = round(current, 4) if current else None
    prev_d = _get_prev(pd.Series(total_debt))
    prev_e = _get_prev(pd.Series(equity))
    prev = _safe_div(prev_d, prev_e)
    prev = round(prev, 4) if prev else None
    diff = round(current - prev, 4) if current is not None and prev is not None else None
    return current, diff


# ============================================================
# 主计算入口
# ============================================================

def compute_all(ticker: str) -> Dict[str, Any]:
    """
    主入口：输入 yfinance ticker，输出五大维度标准化指标。
    每个指标包含 current 和 diff。
    """
    stock = yf.Ticker(ticker)

    # 获取财务报表
    try:
        income = stock.quarterly_financials
        balance = stock.quarterly_balance_sheet
        cashflow = stock.quarterly_cashflow
        info = stock.info
    except Exception as e:
        raise ValueError(f"获取财务报表失败 ({ticker}): {e}")

    if income is None or income.empty:
        raise ValueError(f"{ticker} 无财务数据")

    # 提取数组
    def _row(df, name, fallback: str = None) -> np.ndarray:
        """提取行数据，TTM 优先"""
        if df is None or df.empty:
            return np.array([])
        if name in df.index:
            return df.loc[name].values[::-1].astype(float)  # 反转为时间顺序
        if fallback and fallback in df.index:
            return df.loc[fallback].values[::-1].astype(float)
        return np.array([])

    net_income = _row(income, "Net Income")
    revenue = _row(income, "Total Revenue")
    op_income = _row(income, "Operating Income")
    revenue_arr = _row(income, "Total Revenue")
    gross_profit = _row(income, "Gross Profit")

    total_assets = _row(balance, "Total Assets")
    total_equity = _row(balance, "Stockholders Equity", "Total Stockholder Equity")
    total_debt = _row(balance, "Total Debt")
    current_assets = _row(balance, "Current Assets")
    current_liab = _row(balance, "Current Liabilities")
    inventory = _row(balance, "Inventory")
    cash = _row(balance, "Cash And Cash Equivalents", "Cash")

    ocf = _row(cashflow, "Operating Cash Flow")
    capex = _row(cashflow, "Capital Expenditure", "Capital Expenditures")

    eps = _row(income, "Diluted EPS", "Basic EPS")

    # --- 估值数据（从 info） ---
    pe_ttm = info.get("trailingPE", None)
    ev_ebitda = info.get("enterpriseToEbitda", None)
    div_yield = info.get("dividendYield", None)
    div_yield = round(div_yield * 100, 2) if div_yield else None

    market_cap = info.get("marketCap", None)
    enterprise_value = info.get("enterpriseValue", None)
    shares_out = info.get("sharesOutstanding", None)
    book_value = info.get("bookValue", None)
    pb = info.get("priceToBook", None)

    result: Dict[str, Any] = {
        "ticker": ticker,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

    # ============================================================
    # 1. Profitability
    # ============================================================
    roe_val, roe_diff = calc_roe(net_income, total_equity)
    roa_val, roa_diff = calc_roa(net_income, total_assets)
    op_margin_val, op_margin_diff = calc_op_margin(op_income, revenue_arr)

    # FCF Margin = (OCF - CapEx) / Revenue × 100%
    ocf_val = _get_latest(pd.Series(ocf))
    capex_val = _get_latest(pd.Series(capex))
    rev_val = _get_latest(pd.Series(revenue_arr))
    fcf = round(ocf_val - abs(capex_val), 2) if ocf_val is not None and capex_val is not None else None
    fcf_margin = _safe_div(fcf, rev_val)
    fcf_margin = round(fcf_margin * 100, 2) if fcf_margin else None

    result["profitability"] = {
        "ROE": {"current": roe_val, "diff_pp": roe_diff},
        "ROA": {"current": roa_val, "diff_pp": roa_diff},
        "Op_Margin": {"current": op_margin_val, "diff_pp": op_margin_diff},
        "FCF_Margin": {"current": fcf_margin, "diff_pp": None},
    }

    # ============================================================
    # 2. Safety
    # ============================================================
    eq_val = _get_latest(pd.Series(total_equity))
    ta_val = _get_latest(pd.Series(total_assets))
    equity_ratio = _safe_div(eq_val, ta_val)
    equity_ratio = round(equity_ratio * 100, 2) if equity_ratio else None

    ca_val = _get_latest(pd.Series(current_assets))
    cl_val = _get_latest(pd.Series(current_liab))
    current_ratio = _safe_div(ca_val, cl_val)
    current_ratio = round(current_ratio, 2) if current_ratio else None

    de_val, de_diff = calc_de_ratio(total_debt, total_equity)

    result["safety"] = {
        "Equity_Ratio": {"current": equity_ratio, "diff_pp": None},
        "Current_Ratio": {"current": current_ratio, "diff_pp": None},
        "D_E": {"current": de_val, "diff": de_diff},
    }

    # ============================================================
    # 3. Valuation
    # ============================================================
    result["valuation"] = {
        "PE_TTM": {"current": round(pe_ttm, 2) if pe_ttm else None, "diff": None},
        "EV_EBITDA": {"current": round(ev_ebitda, 2) if ev_ebitda else None, "diff": None},
        "Dividend_Yield": {"current": div_yield, "diff": None},
        "PB": {"current": round(pb, 2) if pb else None, "diff": None},
    }

    # ============================================================
    # 4. Efficiency
    # ============================================================
    # Total Asset Turnover = Revenue / Total Assets
    asset_turnover = _safe_div(rev_val, ta_val)
    asset_turnover = round(asset_turnover, 4) if asset_turnover else None

    # Inventory Turn Days = (Inventory / COGS) × 365
    cogs = _row(income, "Cost Of Revenue")
    inv_val = _get_latest(pd.Series(inventory))
    cogs_val = _get_latest(pd.Series(cogs))
    inv_turn_days = _safe_div(inv_val, cogs_val)
    inv_turn_days = round(inv_turn_days * 365, 1) if inv_turn_days else None

    result["efficiency"] = {
        "Asset_Turnover": {"current": asset_turnover, "diff": None},
        "Inv_Turn_Days": {"current": inv_turn_days, "diff": None},
    }

    # ============================================================
    # 5. Growth
    # ============================================================
    rev_cagr = calc_cagr(revenue_arr, 3)
    eps_growth, eps_dir = calc_eps_growth(eps)

    # YoY Revenue Growth (最新 vs 1年前)
    rev_current = _get_latest(pd.Series(revenue_arr))
    rev_prev = _get_prev(pd.Series(revenue_arr), 3)  # 4 quarters back
    rev_yoy = round((rev_current - rev_prev) / abs(rev_prev) * 100, 2) if rev_current and rev_prev and rev_prev != 0 else None

    result["growth"] = {
        "Revenue_CAGR_3Y": {"current": rev_cagr, "diff": None},
        "EPS_Growth": {"current": eps_growth, "direction": eps_dir},
        "Revenue_YoY": {"current": rev_yoy, "diff": None},
    }

    # ============================================================
    # 6. 附加市场数据
    # ============================================================
    result["market"] = {
        "Market_Cap_B": round(market_cap / 1e9, 2) if market_cap else None,
        "Enterprise_Value_B": round(enterprise_value / 1e9, 2) if enterprise_value else None,
        "Shares_Outstanding_M": round(shares_out / 1e6, 2) if shares_out else None,
        "Book_Value_Per_Share": round(book_value, 2) if book_value else None,
    }

    return result


# ============================================================
# 输出格式化
# ============================================================

def format_markdown(result: Dict[str, Any]) -> str:
    """生成 Markdown 财务指标摘要表"""

    def fmt(val, suffix=""):
        if val is None:
            return "N/A"
        if isinstance(val, float):
            return f"{val:+.2f}{suffix}" if val != 0 else f"0.00{suffix}"
        return str(val)

    lines = [
        f"## 财务指标预计算摘要 — {result['ticker']}",
        f"_数据截至: {result['date']}_",
        "",
    ]

    # Profitability
    lines.append("### 1. 盈利能力 (Profitability)")
    lines.append("| 指标 | 当前值 | 环比变化 |")
    lines.append("|------|--------|---------|")
    prof = result["profitability"]
    lines.append(f"| ROE | {fmt(prof['ROE']['current'], '%')} | {fmt(prof['ROE']['diff_pp'], 'pp')} |")
    lines.append(f"| ROA | {fmt(prof['ROA']['current'], '%')} | {fmt(prof['ROA']['diff_pp'], 'pp')} |")
    lines.append(f"| 经营利润率 | {fmt(prof['Op_Margin']['current'], '%')} | {fmt(prof['Op_Margin']['diff_pp'], 'pp')} |")
    lines.append(f"| FCF Margin | {fmt(prof['FCF_Margin']['current'], '%')} | — |")
    lines.append("")

    # Safety
    lines.append("### 2. 安全性 (Safety)")
    lines.append("| 指标 | 当前值 | 环比变化 |")
    lines.append("|------|--------|---------|")
    safe = result["safety"]
    lines.append(f"| 权益比率 | {fmt(safe['Equity_Ratio']['current'], '%')} | — |")
    lines.append(f"| 流动比率 | {fmt(safe['Current_Ratio']['current'])} | — |")
    lines.append(f"| D/E | {fmt(safe['D_E']['current'])} | {fmt(safe['D_E']['diff'])} |")
    lines.append("")

    # Valuation
    lines.append("### 3. 估值 (Valuation)")
    lines.append("| 指标 | 当前值 |")
    lines.append("|------|--------|")
    val = result["valuation"]
    lines.append(f"| PE(TTM) | {fmt(val['PE_TTM']['current'], 'x')} |")
    lines.append(f"| EV/EBITDA | {fmt(val['EV_EBITDA']['current'], 'x')} |")
    lines.append(f"| 股息率 | {fmt(val['Dividend_Yield']['current'], '%')} |")
    lines.append(f"| PB | {fmt(val['PB']['current'], 'x')} |")
    lines.append("")

    # Efficiency
    lines.append("### 4. 效率 (Efficiency)")
    lines.append("| 指标 | 当前值 |")
    lines.append("|------|--------|")
    eff = result["efficiency"]
    lines.append(f"| 总资产周转率 | {fmt(eff['Asset_Turnover']['current'], 'x')} |")
    lines.append(f"| 存货周转天数 | {fmt(eff['Inv_Turn_Days']['current'], '天')} |")
    lines.append("")

    # Growth
    lines.append("### 5. 增长 (Growth)")
    lines.append("| 指标 | 当前值 | 方向 |")
    lines.append("|------|--------|------|")
    gro = result["growth"]
    eps_dir = gro["EPS_Growth"].get("direction", "—") if isinstance(gro["EPS_Growth"], dict) else "—"
    lines.append(f"| 营收 CAGR(3Y) | {fmt(gro['Revenue_CAGR_3Y']['current'], '%')} | — |")
    lines.append(f"| EPS Growth | {fmt(gro['EPS_Growth']['current'], '%')} | {eps_dir} |")
    lines.append(f"| 营收 YoY | {fmt(gro['Revenue_YoY']['current'], '%')} | — |")
    lines.append("")

    # Market
    lines.append("### 6. 市场数据")
    lines.append("| 指标 | 当前值 |")
    lines.append("|------|--------|")
    mkt = result["market"]
    lines.append(f"| 市值 | {fmt(mkt['Market_Cap_B'], 'B')} |")
    lines.append(f"| 企业价值 | {fmt(mkt['Enterprise_Value_B'], 'B')} |")
    lines.append(f"| 流通股本 | {fmt(mkt['Shares_Outstanding_M'], 'M')} |")
    lines.append(f"| 每股账面价值 | {fmt(mkt['Book_Value_Per_Share'])} |")

    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="财务指标预计算引擎 — 对标牛津论文 Quantitative Agent 五大维度"
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

    args = parser.parse_args()

    if args.ticker is None:
        print("用法: python financial_metrics_precompute.py <TICKER> [--json|--markdown]")
        print("示例: python financial_metrics_precompute.py 0700.HK --markdown")
        sys.exit(0)

    try:
        result = compute_all(args.ticker)

        if args.markdown:
            print(format_markdown(result))
        elif args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            print(format_markdown(result))
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
