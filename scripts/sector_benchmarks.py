#!/usr/bin/env python3
"""
行业基准数据库 — IR 管线 Phase 1.3

对标论文：Miyazaki et al., "Toward Expert Investment Teams",
           Oxford EngSci, arXiv:2602.23330, 2026.02
           Sector Agent 行业对标层

功能：
  1. 股票 → 行业分类映射（申万一级/二级）
  2. 行业基准数据：PE均值、ROE均值、毛利率均值、营收增速均值
  3. 标的 vs 行业基准对比，生成相对位置评估

数据来源：
  - 申万行业分类（硬编码映射表）
  - 行业均值通过 yfinance 获取同行业标的计算
  - 更新策略：每月从公开渠道采集更新

用法：
  python sector_benchmarks.py <TICKER> [--json|--markdown]
  python sector_benchmarks.py 600519.SS --markdown
"""

import sys
import json
import argparse
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

import yfinance as yf

# ============================================================
# 申万一级行业分类映射（A 股 → 行业）
# 维护：每月检查一次分类准确性
# ============================================================

# A股行业代表性标的池（每个行业 5-10 个代表性公司）
# 用于计算行业均值：PE、ROE、毛利率、营收增速
INDUSTRY_PEERS: Dict[str, List[Tuple[str, str]]] = {
    "食品饮料": [
        ("600519.SS", "贵州茅台"),
        ("000858.SZ", "五粮液"),
        ("000568.SZ", "泸州老窖"),
        ("002304.SZ", "洋河股份"),
        ("600809.SS", "山西汾酒"),
    ],
    "医药生物": [
        ("300760.SZ", "迈瑞医疗"),
        ("600276.SS", "恒瑞医药"),
        ("000538.SZ", "云南白药"),
        ("300015.SZ", "爱尔眼科"),
        ("002007.SZ", "华兰生物"),
    ],
    "电子": [
        ("002475.SZ", "立讯精密"),
        ("000725.SZ", "京东方A"),
        ("300433.SZ", "蓝思科技"),
        ("002241.SZ", "歌尔股份"),
        ("603986.SS", "兆易创新"),
    ],
    "计算机": [
        ("002230.SZ", "科大讯飞"),
        ("300033.SZ", "同花顺"),
        ("300454.SZ", "深信服"),
        ("600570.SS", "恒生电子"),
        ("002410.SZ", "广联达"),
    ],
    "电力设备": [
        ("300750.SZ", "宁德时代"),
        ("002594.SZ", "比亚迪"),
        ("601012.SS", "隆基绿能"),
        ("300274.SZ", "阳光电源"),
        ("688005.SS", "容百科技"),
    ],
    "汽车": [
        ("600104.SS", "上汽集团"),
        ("000625.SZ", "长安汽车"),
        ("601238.SS", "广汽集团"),
        ("601633.SS", "长城汽车"),
        ("002920.SZ", "德赛西威"),
    ],
    "银行": [
        ("600036.SS", "招商银行"),
        ("601398.SS", "工商银行"),
        ("000001.SZ", "平安银行"),
        ("600016.SS", "民生银行"),
        ("601166.SS", "兴业银行"),
    ],
    "非银金融": [
        ("601318.SS", "中国平安"),
        ("600030.SS", "中信证券"),
        ("601688.SS", "华泰证券"),
        ("300059.SZ", "东方财富"),
        ("601601.SS", "中国太保"),
    ],
    "房地产": [
        ("000002.SZ", "万科A"),
        ("001979.SZ", "招商蛇口"),
        ("600048.SS", "保利发展"),
        ("600383.SS", "金地集团"),
        ("000069.SZ", "华侨城A"),
    ],
    "通信": [
        ("600050.SS", "中国联通"),
        ("601728.SS", "中国电信"),
        ("300308.SZ", "中际旭创"),
        ("600745.SS", "闻泰科技"),
        ("002396.SZ", "星网锐捷"),
    ],
    "传媒": [
        ("300413.SZ", "芒果超媒"),
        ("002555.SZ", "三七互娱"),
        ("002624.SZ", "完美世界"),
        ("300418.SZ", "昆仑万维"),
        ("603444.SS", "吉比特"),
    ],
    "机械设备": [
        ("600031.SS", "三一重工"),
        ("002050.SZ", "三花智控"),
        ("688188.SS", "柏楚电子"),
        ("300124.SZ", "汇川技术"),
        ("600761.SS", "安徽合力"),
    ],
    "基础化工": [
        ("600309.SS", "万华化学"),
        ("002601.SZ", "龙佰集团"),
        ("600426.SS", "华鲁恒升"),
        ("002064.SZ", "华峰化学"),
        ("600160.SS", "巨化股份"),
    ],
    "国防军工": [
        ("600760.SS", "中航沈飞"),
        ("600893.SS", "航发动力"),
        ("002025.SZ", "航天电器"),
        ("300777.SZ", "中简科技"),
        ("688002.SS", "睿创微纳"),
    ],
    "建筑装饰": [
        ("601668.SS", "中国建筑"),
        ("601390.SS", "中国中铁"),
        ("601800.SS", "中国交建"),
        ("600170.SS", "上海建工"),
        ("002051.SZ", "中工国际"),
    ],
    "交通运输": [
        ("601919.SS", "中远海控"),
        ("600018.SS", "上港集团"),
        ("601111.SS", "中国国航"),
        ("002352.SZ", "顺丰控股"),
        ("600009.SS", "上海机场"),
    ],
    "公用事业": [
        ("600900.SS", "长江电力"),
        ("600886.SS", "国投电力"),
        ("600011.SS", "华能国际"),
        ("601985.SS", "中国核电"),
        ("003816.SZ", "中国广核"),
    ],
    "钢铁": [
        ("600019.SS", "宝钢股份"),
        ("000932.SZ", "华菱钢铁"),
        ("600010.SS", "包钢股份"),
        ("002110.SZ", "三钢闽光"),
        ("600507.SS", "方大特钢"),
    ],
    "有色金属": [
        ("601899.SS", "紫金矿业"),
        ("002460.SZ", "赣锋锂业"),
        ("603799.SS", "华友钴业"),
        ("000630.SZ", "铜陵有色"),
        ("600111.SS", "北方稀土"),
    ],
    "农林牧渔": [
        ("002714.SZ", "牧原股份"),
        ("300498.SZ", "温氏股份"),
        ("000876.SZ", "新希望"),
        ("002311.SZ", "海大集团"),
        ("002385.SZ", "大北农"),
    ],
    "纺织服饰": [
        ("603899.SS", "晨光股份"),
        ("600398.SS", "海澜之家"),
        ("603156.SS", "养元饮品"),
        ("600612.SZ", "老凤祥"),
        ("002563.SZ", "森马服饰"),
    ],
}

# 申万一级行业 → A 股 ticker 列表
INDUSTRY_TICKER_MAP: Dict[str, List[str]] = {
    ind: [p[0] for p in peers] for ind, peers in INDUSTRY_PEERS.items()
}

# 申万二级 → 一级映射（常见子行业）
SUB_TO_MAJOR: Dict[str, str] = {
    "白酒": "食品饮料",
    "啤酒": "食品饮料",
    "乳制品": "食品饮料",
    "调味品": "食品饮料",
    "创新药": "医药生物",
    "医疗器械": "医药生物",
    "消费电子": "电子",
    "半导体": "电子",
    "光学光电子": "电子",
    "软件开发": "计算机",
    "IT服务": "计算机",
    "电池": "电力设备",
    "光伏": "电力设备",
    "风电": "电力设备",
    "乘用车": "汽车",
    "汽车零部件": "汽车",
    "城商行": "银行",
    "股份制银行": "银行",
    "证券": "非银金融",
    "保险": "非银金融",
    "住宅开发": "房地产",
    "商业地产": "房地产",
    "工业自动化": "机械设备",
    "工程机械": "机械设备",
    "特种化工": "基础化工",
    "航空装备": "国防军工",
    "航空航天": "国防军工",
    "港口": "交通运输",
    "高速公路": "交通运输",
    "黄金": "有色金属",
    "铜": "有色金属",
    "锂": "有色金属",
}

# 港股行业映射（代表性的港股 → 对应 A 股行业分类）
HK_PEERS: Dict[str, List[Tuple[str, str]]] = {
    "互联网": [
        ("0700.HK", "腾讯控股"),
        ("9988.HK", "阿里巴巴"),
        ("3690.HK", "美团"),
        ("9618.HK", "京东"),
        ("9888.HK", "百度"),
    ],
    "新能源汽车": [
        ("1211.HK", "比亚迪股份"),
        ("9866.HK", "蔚来"),
        ("2015.HK", "理想汽车"),
        ("9863.HK", "零跑汽车"),
    ],
}

# ============================================================
# 核心函数
# ============================================================

def classify_ticker(ticker: str) -> Tuple[str, List[Tuple[str, str]]]:
    """
    将 ticker 映射到申万行业分类。
    返回 (行业名, [(peer_ticker, peer_name), ...])
    """
    # 1. 检查是否在已知行业池中
    for industry, peers in INDUSTRY_PEERS.items():
        for peer_ticker, peer_name in peers:
            if ticker.upper() == peer_ticker.upper():
                return industry, peers

    # 2. 港股分类
    for industry, peers in HK_PEERS.items():
        for peer_ticker, peer_name in peers:
            if ticker.upper() == peer_ticker.upper():
                return industry, peers

    # 3. 尝试从 yfinance info 获取行业信息
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        sector = info.get("sector", "")
        industry_field = info.get("industry", "")

        # 按关键字归类
        keywords_map = {
            "食品饮料": ["beverage", "food", "alcohol", "alcoholic", "liquor", "食品", "饮料", "酒"],
            "医药生物": ["pharma", "drug", "medical", "healthcare", "hospital", "医药", "医疗", "药"],
            "电子": ["electronic", "semiconductor", "芯片", "电子"],
            "计算机": ["software", "IT", "internet", "cloud", "软件", "云", "互联网"],
            "电力设备": ["battery", "solar", "new energy", "电池", "新能源", "光伏"],
            "汽车": ["auto", "vehicle", "汽车"],
            "银行": ["bank", "银行"],
            "非银金融": ["insurance", "broker", "fintech", "证券", "保险"],
        }

        for industry, keywords in keywords_map.items():
            for kw in keywords:
                if kw.lower() in (sector + " " + industry_field).lower():
                    return industry, INDUSTRY_PEERS.get(industry, [])

        print(f"⚠ ticker {ticker} 无法自动分类到已知行业（sector={sector}, industry={industry_field}），请手动维护 INDUSTRY_PEERS", file=sys.stderr)
        return "未分类", []

    except Exception:
        print(f"⚠ 无法获取 {ticker} 信息", file=sys.stderr)
        return "未分类", []


def _safe_float(val):
    """安全提取 float"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def compute_industry_stats(ticker: str) -> Dict[str, Any]:
    """
    计算目标 ticker 所在行业的基准数据。
    获取所有 peer 的 yfinance info，计算均值。
    """
    industry, peers = classify_ticker(ticker)

    if not peers:
        return {
            "ticker": ticker,
            "industry": industry,
            "error": "未找到同行业标的，无法计算基准",
            "date": datetime.now().strftime("%Y-%m-%d"),
        }

    # 收集所有 peer 的指标
    peer_data: List[Dict[str, Any]] = []
    for peer_ticker, peer_name in peers:
        try:
            stock = yf.Ticker(peer_ticker)
            info = stock.info
            peer_data.append({
                "ticker": peer_ticker,
                "name": peer_name,
                "pe": _safe_float(info.get("trailingPE")),
                "roe": _safe_float(info.get("returnOnEquity")),
                "gross_margin": _safe_float(info.get("grossMargins")),
                "revenue_growth": _safe_float(info.get("revenueGrowth")),
                "market_cap": _safe_float(info.get("marketCap")),
            })
        except Exception as e:
            print(f"⚠ 跳过 {peer_ticker}（{peer_name}）: {e}", file=sys.stderr)
            continue

    if not peer_data:
        return {
            "ticker": ticker,
            "industry": industry,
            "error": "所有同行业标的数据获取失败",
            "date": datetime.now().strftime("%Y-%m-%d"),
        }

    # 计算均值（去极值：去掉 max 和 min 各一个）
    def _calc_stats(values):
        valid = [v for v in values if v is not None and not (isinstance(v, float) and v.__eq__(float('nan')))]
        if len(valid) >= 4:
            # 去极值
            sorted_vals = sorted(valid)
            trimmed = sorted_vals[1:-1]
            avg = sum(trimmed) / len(trimmed)
            q25 = sorted_vals[len(sorted_vals) // 4]
            q75 = sorted_vals[3 * len(sorted_vals) // 4]
        elif len(valid) > 0:
            avg = sum(valid) / len(valid)
            q25 = None
            q75 = None
        else:
            avg = None
            q25 = None
            q75 = None
        return {
            "avg": round(avg, 2) if avg else None,
            "q25": round(q25, 2) if q25 else None,
            "q75": round(q75, 2) if q75 else None,
            "n": len(valid),
        }

    pe_stats = _calc_stats([d["pe"] for d in peer_data])
    roe_stats = _calc_stats([d["roe"] for d in peer_data if d["roe"] is not None])
    roe_pct = {
        "avg": round(roe_stats["avg"] * 100, 2) if roe_stats["avg"] else None,
        "q25": round(roe_stats["q25"] * 100, 2) if roe_stats["q25"] else None,
        "q75": round(roe_stats["q75"] * 100, 2) if roe_stats["q75"] else None,
        "n": roe_stats["n"],
    }
    gm_stats = _calc_stats([d["gross_margin"] for d in peer_data if d["gross_margin"] is not None])
    gm_pct = {
        "avg": round(gm_stats["avg"] * 100, 2) if gm_stats["avg"] else None,
        "q25": round(gm_stats["q25"] * 100, 2) if gm_stats["q25"] else None,
        "q75": round(gm_stats["q75"] * 100, 2) if gm_stats["q75"] else None,
        "n": gm_stats["n"],
    }
    rg_stats = _calc_stats([d["revenue_growth"] for d in peer_data if d["revenue_growth"] is not None])
    rg_pct = {
        "avg": round(rg_stats["avg"] * 100, 2) if rg_stats["avg"] else None,
        "q25": round(rg_stats["q25"] * 100, 2) if rg_stats["q25"] else None,
        "q75": round(rg_stats["q75"] * 100, 2) if rg_stats["q75"] else None,
        "n": rg_stats["n"],
    }

    # 获取目标 ticker 自身的指标
    try:
        target_stock = yf.Ticker(ticker)
        target_info = target_stock.info
        target = {
            "pe": _safe_float(target_info.get("trailingPE")),
            "roe": round(_safe_float(target_info.get("returnOnEquity")) * 100, 2) if target_info.get("returnOnEquity") else None,
            "gross_margin": round(_safe_float(target_info.get("grossMargins")) * 100, 2) if target_info.get("grossMargins") else None,
            "revenue_growth": round(_safe_float(target_info.get("revenueGrowth")) * 100, 2) if target_info.get("revenueGrowth") else None,
            "market_cap": _safe_float(target_info.get("marketCap")),
        }
    except Exception:
        target = {"pe": None, "roe": None, "gross_margin": None, "revenue_growth": None, "market_cap": None}

    # 相对位置判断
    def _relative_position(target_val, industry_avg, industry_q25, industry_q75):
        if target_val is None or industry_avg is None:
            return "N/A"
        if industry_q75 and target_val > industry_q75:
            return "领先"
        if industry_avg and target_val > industry_avg:
            return "中等偏上"
        if industry_q25 and target_val > industry_q25:
            return "中等偏下"
        return "落后"

    # PE 特殊处理：越低越好（对投资者而言）
    def _pe_position(target_pe, industry_avg, industry_q75):
        if target_pe is None or industry_avg is None:
            return "N/A"
        if industry_q75 and target_pe < industry_q75:
            return "相对低估"
        if target_pe < industry_avg:
            return "略低估"
        return "相对高估"

    result = {
        "ticker": ticker,
        "industry": industry,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "peer_count": len(peer_data),
        "peers_used": [d["ticker"] for d in peer_data],
        "benchmarks": {
            "PE_TTM": {**pe_stats},
            "ROE": {**roe_pct},
            "Gross_Margin": {**gm_pct},
            "Revenue_Growth": {**rg_pct},
        },
        "target": target,
        "relative_position": {
            "PE_TTM": _pe_position(target["pe"], pe_stats["avg"], pe_stats["q75"]),
            "ROE": _relative_position(target.get("roe"), roe_pct["avg"], roe_pct["q25"], roe_pct["q75"]),
            "Gross_Margin": _relative_position(target.get("gross_margin"), gm_pct["avg"], gm_pct["q25"], gm_pct["q75"]),
            "Revenue_Growth": _relative_position(target.get("revenue_growth"), rg_pct["avg"], rg_pct["q25"], rg_pct["q75"]),
        },
    }

    # 综合行业吸引力调整分（对标论文 Sector Agent）
    adj_score = 0
    positions = result["relative_position"]
    for metric, pos in positions.items():
        if pos == "领先" or pos == "相对低估":
            adj_score += 5
        elif pos == "落后" or pos == "相对高估":
            adj_score -= 5
        elif pos == "中等偏上":
            adj_score += 2
        elif pos == "中等偏下":
            adj_score -= 2
    result["sector_adjustment"] = max(-20, min(20, adj_score))

    return result


# ============================================================
# 输出格式化
# ============================================================

def format_markdown(result: Dict[str, Any]) -> str:
    """生成 Markdown 行业对标表"""

    def fmt(val, suffix=""):
        if val is None:
            return "N/A"
        return f"{val:.2f}{suffix}" if isinstance(val, float) else str(val)

    if "error" in result:
        return f"## 行业基准数据 — {result['ticker']}\n\n⚠ {result['error']}"

    bm = result["benchmarks"]
    tgt = result["target"]
    rp = result["relative_position"]

    lines = [
        f"## 行业基准对标表 — {result['ticker']}",
        f"_行业: {result['industry']} ｜ 对标样本: {result['peer_count']} 家 ｜ 数据截至: {result['date']}_",
        "",
        "| 指标 | 标的公司 | 行业均值 | 行业25分位 | 行业75分位 | 相对位置 | 调整方向 |",
        "|------|---------|---------|-----------|-----------|---------|---------|",
    ]

    pe_adjust = "正面" if "低估" in rp.get("PE_TTM", "") else ("负面" if "高估" in rp.get("PE_TTM", "") else "中性")
    roe_adjust = "正面" if rp.get("ROE") in ("领先", "中等偏上") else ("负面" if rp.get("ROE") in ("落后", "中等偏下") else "中性")
    gm_adjust = "正面" if rp.get("Gross_Margin") in ("领先", "中等偏上") else ("负面" if rp.get("Gross_Margin") in ("落后", "中等偏下") else "中性")
    rg_adjust = "正面" if rp.get("Revenue_Growth") in ("领先", "中等偏上") else ("负面" if rp.get("Revenue_Growth") in ("落后", "中等偏下") else "中性")

    lines.append(f"| PE(TTM) | {fmt(tgt['pe'], 'x')} | {fmt(bm['PE_TTM']['avg'], 'x')} | {fmt(bm['PE_TTM']['q25'], 'x')} | {fmt(bm['PE_TTM']['q75'], 'x')} | {rp.get('PE_TTM', 'N/A')} | {pe_adjust} |")
    lines.append(f"| ROE | {fmt(tgt['roe'], '%')} | {fmt(bm['ROE']['avg'], '%')} | {fmt(bm['ROE']['q25'], '%')} | {fmt(bm['ROE']['q75'], '%')} | {rp.get('ROE', 'N/A')} | {roe_adjust} |")
    lines.append(f"| 毛利率 | {fmt(tgt['gross_margin'], '%')} | {fmt(bm['Gross_Margin']['avg'], '%')} | {fmt(bm['Gross_Margin']['q25'], '%')} | {fmt(bm['Gross_Margin']['q75'], '%')} | {rp.get('Gross_Margin', 'N/A')} | {gm_adjust} |")
    lines.append(f"| 营收增速 | {fmt(tgt['revenue_growth'], '%')} | {fmt(bm['Revenue_Growth']['avg'], '%')} | {fmt(bm['Revenue_Growth']['q25'], '%')} | {fmt(bm['Revenue_Growth']['q75'], '%')} | {rp.get('Revenue_Growth', 'N/A')} | {rg_adjust} |")
    lines.append("")

    lines.append("### 行业吸引力调整分")
    lines.append(f"- **Sector Adjustment**: **{result.get('sector_adjustment', 0):+d}** (范围 -20~+20)")
    lines.append(f"- 对标样本: {', '.join(result.get('peers_used', []))}")
    lines.append("")

    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="行业基准数据库 — 对标牛津论文 Sector Agent"
    )
    parser.add_argument(
        "ticker",
        nargs="?",
        default=None,
        help="股票代码（yfinance 格式，如 600519.SS, 0700.HK）",
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
        "--list-industries",
        action="store_true",
        help="列出所有已知行业和分类",
    )
    parser.add_argument(
        "--classify-only",
        action="store_true",
        help="仅输出行业分类结果，不计算基准",
    )

    args = parser.parse_args()

    if args.list_industries:
        print("# 行业分类索引\n")
        for ind, peers in INDUSTRY_PEERS.items():
            print(f"## {ind}（{len(peers)} 家）")
            for t, name in peers:
                print(f"- {t} — {name}")
            print()
        sys.exit(0)

    if args.ticker is None:
        print("用法: python sector_benchmarks.py <TICKER> [--json|--markdown|--list-industries|--classify-only]")
        print("示例: python sector_benchmarks.py 600519.SS --markdown")
        sys.exit(0)

    if args.classify_only:
        industry, _ = classify_ticker(args.ticker)
        print(f"{args.ticker} → {industry}")
        sys.exit(0)

    try:
        result = compute_industry_stats(args.ticker)

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
