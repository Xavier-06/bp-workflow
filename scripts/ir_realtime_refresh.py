#!/usr/bin/env python3
"""
IR Realtime Data Refresh — Phase 5 统稿前拉最新行情注入
========================================================

Perplexity 生成报告前会拉最新数据。我们也一样。

功能：
  1. Yahoo Finance 拉最新股价/市值/PE/52周范围（us/hk/cn）
  2. 写入 TASKS_DIR/{task_id}-realtime-data.json
  3. 返回 Markdown 片段，供 DOCX 生成时注入

用法：
  python3 scripts/ir_realtime_refresh.py --task-id TASK-XXX --entity "英伟达" --ticker NVDA --market us
"""
from __future__ import annotations
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / 'data' / 'tasks'
SCRIPTS_DIR = WORKSPACE / 'scripts'

# Market → Yahoo symbol suffix
MARKET_SUFFIX = {'us': '', 'hk': '.HK', 'cn': '.SS'}

def fetch_yahoo_finance(ticker: str, market: str = 'us') -> dict:
    """
    通过 yf CLI 或 yfinance 获取实时行情。
    """
    symbol = ticker.upper() + MARKET_SUFFIX.get(market, '')
    result = {
        'ticker': ticker,
        'market': market,
        'symbol': symbol,
        'fetched_at': datetime.now().isoformat(timespec='seconds'),
    }

    # 方法 1：yf CLI
    try:
        import subprocess
        cmd = [str(WORKSPACE / 'bin' / 'yf'), 'quote', ticker]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0 and proc.stdout.strip():
            output = proc.stdout.strip()
            # Parse key: value pairs
            for line in output.split('\n'):
                if ':' in line:
                    key, _, value = line.partition(':')
                    key = key.strip().lower().replace(' ', '_')
                    value = value.strip()
                    if key and value:
                        try:
                            if '.' in value:
                                result[key] = float(value)
                            else:
                                result[key] = int(value.replace(',', ''))
                        except ValueError:
                            result[key] = value
            return result
    except Exception:
        pass

    # 方法 2：yfinance Python 库
    try:
        import yfinance as yf
        stock = yf.Ticker(symbol)
        info = stock.fast_info
        result.update({
            'price': getattr(info, 'last_price', None),
            'previous_close': getattr(info, 'previous_close', None),
            'market_cap': getattr(info, 'market_cap', None),
            'day_high': getattr(info, 'day_high', None),
            'day_low': getattr(info, 'day_low', None),
            'fifty_day_average': getattr(info, 'fifty_day_average', None),
            'two_hundred_day_average': getattr(info, 'two_hundred_day_average', None),
        })
        # Additional info
        try:
            si = stock.info
            result.update({
                'trailing_pe': si.get('trailingPE'),
                'forward_pe': si.get('forwardPE'),
                'eps': si.get('trailingEps'),
                'dividend_yield': si.get('dividendYield'),
                'beta': si.get('beta'),
                'volume': si.get('volume'),
                'avg_volume': si.get('averageVolume'),
            })
        except:
            pass
        return result
    except Exception:
        pass

    # 方法 3：search_gateway 搜索最新信息
    try:
        import sys
        sys.path.insert(0, str(SCRIPTS_DIR))
        from search_gateway import search
        query = f"{ticker} stock price market cap PE ratio {datetime.now().year}"
        results = search(query, max_results=5)
        if results:
            result['search_based'] = [{'title': r.get('title', ''), 'snippet': r.get('snippet', '')} for r in results[:5]]
        return result
    except Exception:
        pass

    result['error'] = 'Failed to fetch real-time data from all sources'
    return result


def generate_realtime_md(data: dict, entity: str = '') -> str:
    """生成 Markdown 片段，用于注入 DOCX。"""
    lines = [f"\n## 实时数据更新 ({data.get('fetched_at', '')})\n"]
    if entity:
        lines.append(f"**{entity} ({data.get('ticker', '')})** 最新行情：\n")

    mapping = {
        'price': ('最新价', ''),
        'previous_close': ('前收盘', ''),
        'market_cap': ('市值', ''),
        'trailing_pe': ('市盈率 (TTM)', ''),
        'forward_pe': ('远期市盈率', ''),
        'eps': ('EPS', ''),
        'dividend_yield': ('股息率', ''),
        'beta': ('Beta', ''),
        'day_high': ('日内高', ''),
        'day_low': ('日内低', ''),
        'volume': ('成交量', ''),
    }

    for key, (label, unit) in mapping.items():
        val = data.get(key)
        if val is not None:
            lines.append(f"- {label}: {val}" + (f" {unit}" if unit else ""))

    # 计算涨跌
    price = data.get('price')
    prev = data.get('previous_close')
    if price and prev and prev != 0:
        change = price - prev
        pct = change / prev * 100
        arrow = '🔴' if change < 0 else '🟢'
        lines.append(f"- 涨跌: {arrow} {change:+.2f} ({pct:+.2f}%)")

    if data.get('error'):
        lines.append(f"\n> ⚠️ 实时数据获取失败: {data['error']}")

    return '\n'.join(lines)


def refresh_realtime_data(task_id: str, ticker: str = '', entity: str = '', market: str = 'us') -> dict:
    """
    Phase 5 统稿前执行实时数据刷新。
    返回 (data, markdown_snippet)。
    """
    from pathlib import Path as _Path

    # 尝试从 task package 获取 ticker
    pkg_path = TASKS_DIR / f'{task_id}.json'
    if not ticker and pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text())
            ticker = pkg.get('ticker', pkg.get('symbol', ''))
        except:
            pass

    if not ticker:
        return {'error': 'No ticker available', 'md_snippet': ''}

    data = fetch_yahoo_finance(ticker, market)

    # 写入文件
    out_path = TASKS_DIR / f'{task_id}-realtime-data.json'
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    md = generate_realtime_md(data, entity)

    return {**data, 'md_snippet': md, 'saved_to': str(out_path)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task-id', required=True)
    ap.add_argument('--ticker', default='')
    ap.add_argument('--entity', default='')
    ap.add_argument('--market', default='us', choices=['us', 'hk', 'cn'])
    args = ap.parse_args()

    result = refresh_realtime_data(args.task_id, args.ticker, args.entity, args.market)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
