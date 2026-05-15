#!/usr/bin/env python3
"""
估值数据补充 — NeoData (A/HK优先) + yfinance 双源获取实时估值指标

被 ir_company_verify.py 引用，提供 enrich_with_yahoo(entity) 接口。
返回 dict 包含 ticker / price / pe_ratio / ps_ratio / pb_ratio / market_cap 等。

数据源策略：
- A/HK 股：NeoData 优先（原生中文数据，字段更全），yfinance 交叉验证
- 美股：yfinance 主力
- 价格差异 >5% 自动标注警告

Ticker 解析策略（按优先级）：
1. 直接格式匹配（A股6位代码、港股代码）
2. 内置 + 持久化缓存映射（中文名 → ticker）
3. yfinance Search API（英文关键词搜索）
4. Web 搜索兜底（搜 "公司名 stock code"）
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False


# ── 常量 ──────────────────────────────────────────────────────

_RUNTIME_ROOT = Path(__file__).resolve().parent.parent
_TICKER_CACHE_PATH = _RUNTIME_ROOT / "data" / "ticker_cache.json"

_A_SHARE_PATTERN = re.compile(r'^(\d{6})$')
_A_SHARE_PREFIXES = {
    '6': 'SS',   # 沪市主板
    '0': 'SZ',   # 深市主板/中小板
    '3': 'SZ',   # 创业板
    '8': 'BJ',   # 北交所
    '4': 'BJ',   # 北交所
    '9': 'SS',   # 科创板（688xxx → SS）
}

_HK_PATTERN = re.compile(r'^(\d{4,5})\.?HK$', re.IGNORECASE)

# ── 内置名称映射（种子数据，不会被覆盖） ──────────────────────

_BUILTIN_NAME_MAP: dict[str, str] = {
    # A 股
    '东江环保': '002672.SZ',
    '宁德时代': '300750.SZ',
    '比亚迪': '002594.SZ',
    '贵州茅台': '600519.SS',
    '中国平安': '601318.SS',
    # 港股
    '阿里巴巴': '9988.HK',
    '腾讯': '0700.HK',
    '泡泡玛特': '9992.HK',
    '美团': '3690.HK',
    '小米': '1810.HK',
    '京东': '9618.HK',
    '网易': '9999.HK',
    '哔哩哔哩': '9626.HK',
    '快手': '1024.HK',
    '百度': '9888.HK',
    '理想汽车': '2015.HK',
    '蔚来': '9866.HK',
    '小鹏汽车': '9868.HK',
    '海底捞': '6862.HK',
    '农夫山泉': '9633.HK',
    '李宁': '2331.HK',
    '安踏体育': '2020.HK',
    '优必选': '9880.HK',
    '港仔机器人': '0370.HK',
    '国华集团': '0370.HK',
}

# 中文名 → 英文搜索关键词（用于 yfinance Search，它对英文名更友好）
_CN_TO_EN_SEARCH: dict[str, str] = {
    '泡泡玛特': 'POP MART',
    '阿里巴巴': 'Alibaba',
    '腾讯': 'Tencent',
    '美团': 'Meituan',
    '小米': 'Xiaomi',
    '京东': 'JD.com',
    '网易': 'NetEase',
    '哔哩哔哩': 'Bilibili',
    '快手': 'Kuaishou',
    '百度': 'Baidu',
    '理想汽车': 'Li Auto',
    '蔚来': 'NIO',
    '小鹏汽车': 'XPeng',
    '海底捞': 'Haidilao',
    '农夫山泉': 'Nongfu Spring',
    '李宁': 'Li Ning',
    '安踏体育': 'ANTA Sports',
    '宁德时代': 'CATL',
    '比亚迪': 'BYD',
    '贵州茅台': 'Moutai',
    '中国平安': 'Ping An',
    '商汤': 'SenseTime',
    '微盟': 'Weimob',
    '阅文集团': 'China Literature',
    '小米集团': 'Xiaomi',
    '中芯国际': 'SMIC',
    '药明生物': 'WuXi Biologics',
    '舜宇光学': 'Sunny Optical',
    '金斯瑞': 'GenScript',
    '携程': 'Trip.com',
    '哔哩哔哩': 'Bilibili',
    '周大福': 'Chow Tai Fook',
    '新东方': 'New Oriental Education',
    '名创优品': 'MINISO',
    '微盟集团': 'Weimob',
    '雅迪科技': 'Yadea',
    '海尔智家': 'Haier Smart Home',
    '长城汽车': 'Great Wall Motor',
    '吉利汽车': 'Geely Auto',
    '中国飞鹤': 'China Feihe',
    '思摩尔': 'Smoore',
    '雾芯科技': 'RLX Technology',
    '优必选': 'UBTECH Robotics',
}


# ── 持久化缓存 ──────────────────────────────────────────────

def _load_cache() -> dict[str, str]:
    """从磁盘加载 ticker 缓存。"""
    try:
        if _TICKER_CACHE_PATH.exists():
            with open(_TICKER_CACHE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_cache(cache: dict[str, str]) -> None:
    """将 ticker 缓存写入磁盘。"""
    try:
        _TICKER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_TICKER_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except OSError:
        pass  # 缓存写入失败不影响主流程


def _cache_ticker(entity: str, ticker: str) -> None:
    """将发现的映射写入持久化缓存。"""
    cache = _load_cache()
    cache[entity] = ticker
    _save_cache(cache)


# ── Ticker 解析 ──────────────────────────────────────────────

def _guess_ticker_from_entity(entity: str) -> list[str]:
    """根据实体名猜测可能的 yfinance ticker，返回候选列表。"""
    candidates: list[str] = []

    # 1. 如果已经像 ticker（纯6位数字 = A股代码）
    m = _A_SHARE_PATTERN.match(entity.strip())
    if m:
        code = m.group(1)
        suffix = _A_SHARE_PREFIXES.get(code[0], 'SZ')
        candidates.append(f"{code}.{suffix}")

    # 2. 如果像港股代码
    m = _HK_PATTERN.match(entity.strip())
    if m:
        candidates.append(f"{int(m.group(1)):04d}.HK")

    # 3. 内置名称映射
    if entity in _BUILTIN_NAME_MAP:
        candidates.insert(0, _BUILTIN_NAME_MAP[entity])

    # 4. 持久化缓存
    cache = _load_cache()
    if entity in cache and cache[entity] not in candidates:
        candidates.insert(0, cache[entity])

    return candidates


def _is_chinese(text: str) -> bool:
    """检查文本是否主要包含中文字符。"""
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    return chinese_chars > len(text) * 0.3


def _yf_search_pick(search_terms: list[str]) -> str | None:
    """对一组搜索词逐个调 yf.Search，返回第一个命中的 ticker。

    优先选 .HK/.SS/.SZ/.BJ 后缀的结果，次选有公司名匹配的。
    """
    if not _YF_AVAILABLE:
        return None
    for term in search_terms:
        try:
            results = yf.Search(term, max_results=5)
            for quote in results.quotes:
                symbol = quote.get('symbol', '')
                if any(symbol.endswith(s) for s in ('.HK', '.SS', '.SZ', '.BJ')):
                    return symbol
            for quote in results.quotes:
                symbol = quote.get('symbol', '')
                shortname = quote.get('shortname', '').lower()
                longname = quote.get('longname', '').lower()
                term_lower = term.lower()
                if symbol and symbol != term:
                    if term_lower in shortname or term_lower in longname:
                        return symbol
        except Exception:
            continue
    return None


def _search_ticker_via_yfinance(entity: str) -> str | None:
    """通过 yfinance Search API 搜索 ticker。

    策略：
    1. 有英文映射 → 直接搜英文名
    2. 纯中文名 → 先搜中文（零成本尝试）→ web 查英文名 → 搜英文名
    3. 英文名/代码 → 直接搜
    """
    if not _YF_AVAILABLE:
        return None

    search_terms = []

    en_name = _CN_TO_EN_SEARCH.get(entity)
    if en_name:
        search_terms.append(en_name)
    elif _is_chinese(entity):
        # 中文名也试一下（偶尔能命中）
        search_terms.append(entity)
        # 再用 web 搜索找英文名
        web_en = _find_english_name_via_web(entity)
        if web_en:
            search_terms.append(web_en)
    else:
        search_terms.append(entity)

    return _yf_search_pick(search_terms)


def _find_english_name_via_web(entity: str) -> str | None:
    """通过 web 搜索查找中文公司名的英文名。

    多策略：DuckDuckGo Lite + 从搜索结果中提取英文公司名。
    """
    import subprocess
    from html import unescape

    queries = [
        f'{entity} english name stock listed company',
        f'{entity} 英文名 上市公司',
        f'{entity} english name company',
    ]

    noise = {'Yahoo Finance', 'Stock Price', 'Market Cap', 'Hong Kong',
             'United States', 'New York', 'Annual Report', 'Click Here',
             'View More', 'Read More', 'Sign Up', 'Log In', 'Privacy Policy',
             'Terms Of Service', 'All Rights Reserved', 'About Us'}

    for query in queries:
        try:
            result = subprocess.run(
                ['curl', '-s', 'https://duckduckgo.com/lite/',
                 '-d', f'q={query}',
                 '--max-time', '10'],
                capture_output=True, text=True, timeout=15
            )
            text = unescape(result.stdout)
            # 匹配 2-5 个首字母大写单词组成的公司名
            matches = re.findall(r'\b((?:[A-Z][a-z]+\s+){1,4}[A-Z][a-z]+)\b', text)
            for m in matches:
                m = m.strip()
                if m not in noise and len(m) > 4:
                    return m
            # 也匹配全大写的公司名（如 UBTECH, CATL）
            upper_matches = re.findall(r'\b([A-Z]{3,15})\b', text)
            upper_noise = {'HTML', 'HTTP', 'HTTPS', 'NASDAQ', 'NYSE', 'YAHOO',
                           'STOCK', 'PRICE', 'PDF', 'CEO', 'CFO', 'IPO', 'ETF',
                           'USD', 'HKD', 'CNY', 'RMB', 'GET', 'POST', 'THE'}
            for m in upper_matches:
                if m not in upper_noise and len(m) >= 3:
                    return m
        except Exception:
            continue

    return None


def _search_ticker_via_web(entity: str) -> str | None:
    """Web 搜索兜底：通过 search_gateway (SearXNG) 查找 ticker 代码。

    从搜索结果的 title/content 中正则提取股票代码。
    支持 A 股（6位数字）、港股（4-5位.HK）、美股（大写字母）。
    """
    import sys
    sys.path.insert(0, str(_RUNTIME_ROOT / "scripts"))

    queries = [
        f'{entity} 股票代码',
        f'{entity} stock ticker yahoo finance',
    ]

    for query in queries:
        try:
            from search_gateway import search as _gw_search
            results = _gw_search(query, max_results=5, timeout=10)
        except Exception:
            try:
                from searxng_search import search as _old_search
                results = _old_search(query, max_results=5, timeout=10)
            except Exception:
                continue

        # 从所有结果的 title + content 中提取代码
        combined = ' '.join(
            f"{r.get('title', '')} {r.get('content', '')} {r.get('snippet', '')}"
            for r in results
        )

        # 港股代码（4-5位数字.HK）
        hk_matches = re.findall(r'\b(\d{4,5})\.HK\b', combined, re.IGNORECASE)
        if hk_matches:
            code = hk_matches[0]
            return f"{int(code):04d}.HK"

        # 港股代码（括号里的5位数字，如 (00291)）
        hk_paren = re.findall(r'[（(]\s*(0\d{4})\s*[）)]', combined)
        if hk_paren:
            code = hk_paren[0]
            return f"{int(code):04d}.HK"

        # A 股代码（括号或空格后的6位数字）
        a_matches = re.findall(r'[（(]\s*(\d{6})\s*[）)]', combined)
        if a_matches:
            code = a_matches[0]
            suffix = _A_SHARE_PREFIXES.get(code[0], 'SZ')
            return f"{code}.{suffix}"

        # A 股代码（6位数字.SS/SZ/BJ）
        a_dot_matches = re.findall(r'\b(\d{6})\.(?:SS|SZ|BJ)\b', combined)
        if a_dot_matches:
            code = a_dot_matches[0]
            suffix = _A_SHARE_PREFIXES.get(code[0], 'SZ')
            return f"{code}.{suffix}"

        # 美股代码（1-5个大写字母，排除噪声）
        us_matches = re.findall(r'\b([A-Z]{2,5})\b', combined)
        noise = {'HTML', 'HTTP', 'HTTPS', 'NASDAQ', 'NYSE', 'YAHOO', 'STOCK',
                 'PRICE', 'PDF', 'CEO', 'CFO', 'IPO', 'ETF', 'USD', 'HKD',
                 'CNY', 'RMB', 'SEC', 'EDGAR', 'THE', 'AND', 'FOR', 'NOT'}
        for m in us_matches:
            if m not in noise:
                return m

    return None


def _resolve_ticker(entity: str) -> str | None:
    """完整 ticker 解析流程：缓存 → 映射 → yfinance Search → web 搜索。

    找到后自动缓存，下次直接命中。
    """
    # 1. 快速路径：已有候选（映射 + 缓存）
    candidates = _guess_ticker_from_entity(entity)
    if candidates:
        # 验证候选是否有效（由 enrich_with_yahoo 调用方验证）
        return candidates[0]

    # 2. yfinance Search（英文搜索）
    ticker = _search_ticker_via_yfinance(entity)
    if ticker:
        _cache_ticker(entity, ticker)
        return ticker

    # 3. Web 搜索兜底
    ticker = _search_ticker_via_web(entity)
    if ticker:
        _cache_ticker(entity, ticker)
        return ticker

    return None


# ── 安全浮点转换 ──────────────────────────────────────────────

def _safe_float(val: Any) -> Any:
    """Convert to float if possible, else return original."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return val


# ── 主接口 ──────────────────────────────────────────────────

def _is_a_hk_stock(entity: str) -> bool:
    """判断实体是否为 A 股或港股标的（用于决定 NeoData 优先级）。"""
    e = entity.strip()
    # A 股代码
    if _A_SHARE_PATTERN.match(e):
        return True
    # 港股代码
    if _HK_PATTERN.match(e):
        return True
    # 内置映射中有（都是 A/HK 股）
    if entity in _BUILTIN_NAME_MAP:
        return True
    # 持久化缓存中有 A/HK 后缀
    cache = _load_cache()
    ticker = cache.get(entity, '')
    if any(ticker.endswith(s) for s in ('.HK', '.SS', '.SZ', '.BJ')):
        return True
    # 中文名（大概率是 A/HK）
    if _is_chinese(entity):
        return True
    return False


def _enrich_with_neodata(entity: str) -> Optional[dict[str, Any]]:
    """通过 NeoData 获取 A/HK 股估值数据。

    返回与 yfinance 兼容的 dict 格式，如果 NeoData 不可用或无数据返回 None。
    """
    try:
        import sys
        scripts_dir = str(_RUNTIME_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from search_gateway import neodata_summary
        summary = neodata_summary(entity)
        if not summary or not summary.get('price'):
            return None
        return {
            'ticker': summary.get('ticker', ''),
            'company_name': entity,
            'price': _safe_float(summary.get('price')),
            'currency': summary.get('currency', 'CNY'),
            'pe_ratio': _safe_float(summary.get('pe_trailing')),
            'forward_pe': _safe_float(summary.get('pe_forward')),
            'ps_ratio': _safe_float(summary.get('ps')),
            'pb_ratio': _safe_float(summary.get('pb')),
            'market_cap': summary.get('market_cap'),
            '52w_high': None,
            '52w_low': None,
            'revenue_ttm': summary.get('revenue'),
            'eps': None,
            'dividend_yield': None,
            'beta': None,
            'volume': None,
            'avg_volume': None,
            'volume_wan': summary.get('volume_wan'),
            'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'data_source': 'neodata',
        }
    except Exception:
        return None


def _cross_validate(primary: dict, secondary: dict, entity: str) -> dict:
    """交叉验证两个数据源的价格，差异 >5% 则标注警告。

    primary 的字段优先保留，secondary 用于填补 primary 缺失的字段。
    """
    result = dict(primary)

    # 填补 primary 缺失的字段
    for key in ('52w_high', '52w_low', 'revenue_ttm', 'eps', 'dividend_yield', 'beta',
                'forward_pe', 'ps_ratio', 'volume', 'avg_volume'):
        if not result.get(key) and secondary.get(key):
            result[key] = secondary[key]

    # 价格交叉验证
    p_price = primary.get('price')
    s_price = secondary.get('price')
    if p_price and s_price:
        diff_pct = abs(p_price - s_price) / s_price * 100
        if diff_pct > 5:
            result['price_warning'] = (
                f"⚠️ 数据源价格差异 {diff_pct:.1f}%: "
                f"{primary.get('data_source', 'primary')}={p_price}, "
                f"{secondary.get('data_source', 'secondary')}={s_price}。"
                f"已采用 {primary.get('data_source', 'primary')} 数据。"
            )
        else:
            result['price_warning'] = None

    # PE 交叉验证
    p_pe = primary.get('pe_ratio')
    s_pe = secondary.get('pe_ratio')
    if p_pe and s_pe and isinstance(p_pe, (int, float)) and isinstance(s_pe, (int, float)):
        pe_diff = abs(p_pe - s_pe) / s_pe * 100
        if pe_diff > 10:
            result['pe_warning'] = (
                f"⚠️ 数据源 PE 差异 {pe_diff:.1f}%: "
                f"{primary.get('data_source', 'primary')}={p_pe}, "
                f"{secondary.get('data_source', 'secondary')}={s_pe}"
            )

    return result


def enrich_with_yahoo(entity: str) -> dict[str, Any]:
    """获取估值数据。A/HK 股优先 NeoData + yfinance 交叉验证；美股用 yfinance。

    Args:
        entity: 公司名称或股票代码

    Returns:
        dict with keys: ticker, price, pe_ratio, ps_ratio, pb_ratio,
                        market_cap, 52w_high, 52w_low, revenue_ttm,
                        eps, dividend_yield, beta
        Empty dict if nothing found.
    """
    if not _YF_AVAILABLE:
        return {'error': 'yfinance not installed'}

    # 统一通过 _resolve_ticker 获取候选 ticker（映射 → 缓存 → yf.Search → Web搜索）
    resolved = _resolve_ticker(entity)
    if not resolved:
        return {}

    # 判断是否为 A/HK 股 — 决定 NeoData 优先级
    is_ahk = _is_a_hk_stock(entity)

    # ── NeoData 路径（A/HK 股优先） ──
    neodata_result = None
    if is_ahk:
        neodata_result = _enrich_with_neodata(entity)
        if neodata_result and resolved:
            neodata_result['ticker'] = resolved

    # ── yfinance 路径（始终尝试，用于交叉验证或美股主力） ──
    yf_result = None
    try:
        t = yf.Ticker(resolved)
        info = t.info
        if info and info.get('regularMarketPrice'):
            # 公司名验证
            company_name = info.get('shortName', info.get('longName', ''))
            if _is_chinese(entity) and not _validate_company_match(entity, company_name, resolved):
                _remove_cache_entry(entity)
            else:
                yf_result = {
                    'ticker': resolved,
                    'company_name': company_name,
                    'price': _safe_float(info.get('regularMarketPrice') or info.get('currentPrice')),
                    'currency': info.get('currency', ''),
                    'pe_ratio': _safe_float(info.get('trailingPE') or info.get('forwardPE')),
                    'forward_pe': _safe_float(info.get('forwardPE')),
                    'ps_ratio': _safe_float(info.get('priceToSalesTrailing12Months')),
                    'pb_ratio': _safe_float(info.get('priceToBook')),
                    'market_cap': info.get('marketCap'),
                    '52w_high': _safe_float(info.get('fiftyTwoWeekHigh')),
                    '52w_low': _safe_float(info.get('fiftyTwoWeekLow')),
                    'revenue_ttm': info.get('totalRevenue'),
                    'eps': _safe_float(info.get('trailingEps')),
                    'dividend_yield': _safe_float(info.get('dividendYield')),
                    'beta': _safe_float(info.get('beta')),
                    'volume': info.get('volume'),
                    'avg_volume': info.get('averageVolume'),
                    'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'data_source': 'yfinance',
                }
    except Exception:
        pass

    # ── 合并结果 ──
    if is_ahk and neodata_result and yf_result:
        # A/HK 股：NeoData 主力 + yfinance 交叉验证
        return _cross_validate(neodata_result, yf_result, entity)
    elif is_ahk and neodata_result:
        return neodata_result
    elif yf_result:
        return yf_result
    elif neodata_result:
        return neodata_result
    else:
        return {}


def _validate_company_match(entity: str, company_name: str, ticker: str) -> bool:
    """验证 yfinance 返回的公司是否与查询实体匹配。

    防止中文公司名误匹配到不相关的 ticker（如 "XYZ" 匹配到 Block Inc.）。
    """
    if not company_name:
        return False

    # ticker 在内置映射中 → 一定正确（人工维护的）
    if _BUILTIN_NAME_MAP.get(entity) == ticker:
        return True

    # ticker 有交易所后缀（.HK/.SS/.SZ/.BJ）→ 大概率正确
    if any(ticker.endswith(s) for s in ('.HK', '.SS', '.SZ', '.BJ')):
        return True

    # 英文公司名匹配检查（用于美股等）
    en_name = _CN_TO_EN_SEARCH.get(entity, '').lower()
    name_lower = company_name.lower()
    if en_name and en_name in name_lower:
        return True

    # 无交易所后缀 + 无名称匹配 → 拒绝
    return False


def _remove_cache_entry(entity: str) -> None:
    """从缓存中删除指定条目。"""
    try:
        cache = _load_cache()
        if entity in cache:
            del cache[entity]
            _save_cache(cache)
    except Exception:
        pass


# ── CLI ───────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Yahoo Finance 估值数据补充')
    parser.add_argument('entity', help='公司名称或股票代码')
    args = parser.parse_args()

    result = enrich_with_yahoo(args.entity)
    if result:
        for k, v in result.items():
            print(f"  {k}: {v}")
    else:
        print("未找到估值数据")
