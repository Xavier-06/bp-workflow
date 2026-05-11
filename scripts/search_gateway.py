#!/usr/bin/env python3
"""
统一搜索网关 v5

搜索栈：
  Layer 0: NeoData 金融数据（A/HK股行情、财报、板块、研报，金融查询优先）
  Layer 1: DDG Python API 直连（清代理，中英文主力）
  Layer 2: SearXNG 8888（Baidu + Bing 补充）
  Layer 3: Google 直接抓取（scrapling 走 7897 代理，自己解析）
  Layer 4: scrapling 深度抓取（对搜索结果做正文提取）
  Layer 5: yfinance 估值数据（IR 管线专用）

接口：
    from scripts.search_gateway import search, search_deep, search_many, verify_engines
    from scripts.search_gateway import fetch_page, yfinance_summary, google_search
    from scripts.search_gateway import neodata_search
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse

import requests
import ssl as _ssl
import time as _time
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from ddgs import http_client2 as _ddgs_hc2
    from random import SystemRandom as _SystemRandom
    _safe_random = _SystemRandom()
    _SAFE_CIPHERS = _ddgs_hc2.DEFAULT_CIPHERS
    def _patched_ssl_context(verify):
        ctx = _ssl.create_default_context(cafile=verify if isinstance(verify, str) else None)
        shuffled = _safe_random.sample(_SAFE_CIPHERS[9:], len(_SAFE_CIPHERS) - 9)
        ctx.set_ciphers(":".join(_SAFE_CIPHERS[:9] + shuffled))
        # 只从安全的策略中随机选择（跳过 TLS 1.3 设置）
        _safe_commands = [
            lambda c: None,
            lambda c: setattr(c, "maximum_version", _ssl.TLSVersion.TLSv1_2),
            lambda c: setattr(c, "options", c.options | _ssl.OP_NO_TICKET),
        ]
        _safe_random.choice(_safe_commands)(ctx)
        return ctx
    _ddgs_hc2._get_random_ssl_context = _patched_ssl_context
except Exception:
    pass

WORKSPACE = Path(__file__).resolve().parent.parent
CERT_PATH = "/opt/homebrew/etc/openssl@3/cert.pem"
if os.path.exists(CERT_PATH):
    os.environ.setdefault("SSL_CERT_FILE", CERT_PATH)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", CERT_PATH)
    os.environ.setdefault("CURL_CA_BUNDLE", CERT_PATH)

SEARXNG_URL = "http://127.0.0.1:8888"
PROXY_URL = "http://127.0.0.1:7897"
DDGS_BIN = os.getenv("DDGS_BIN", "/opt/homebrew/bin/ddgs")

NEODATA_ENDPOINT = os.getenv("NEODATA_ENDPOINT", "https://copilot.tencent.com/agenttool/v1/neodata")
NEODATA_TOKEN_FILE = Path.home() / ".workbuddy" / ".neodata_token"
NEODATA_TOKEN_TTL = 12 * 3600  # 12 hours

_LOCAL = requests.Session()
_LOCAL.trust_env = False

NOISE_HOSTS = [
    # 内容农场 / 低质量聚合站
    "freelancer.com", "formula1.com", "standard.co.uk", "mfrbee.com",
    "company-listing.org", "douyin.com", "zhidao.baidu.com",
    "toutiao.com", "yidianzixun.com", "baijiahao.baidu.com",
    "new.qq.com", "news.163.com", "k.sina.com.cn",
    # 社交媒体 / 个人页面（非官方信息）
    "linkedin.com/in/", "facebook.com", "twitter.com", "youtube.com",
    # 问答平台（内容质量低）
    "wenwen.sogou.com", "zhidao.baidu.com", "bing.com/search?q=",
    # 机器聚合站
    "company-listing.org", "mfrbee.com", "repo-market.com",
    # 外国垃圾站（DDG 对中文公司名返回的噪声）
    "netshoes.com.br", "trauer-in-thueringen.de", "amazon.", "ebay.",
    "alibaba.com/offer", "made-in-china.com", "globalsources.com",
    "europages.", "wlw.de", "kompass.com", "dnb.com",
    # 讣告/婚庆/无关生活服务
    "trauer", "bestattung", "beerdigung", "obituary",
    # 价格比较/购物聚合
    "preisvergleich", "kelkoo", "shopzilla", "pricegrabber",
]


# ── 工具函数 ──────────────────────────────────────────

def _has_chinese(text: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in text)


def _is_noise(row: dict) -> bool:
    url = (row.get("url") or "").lower()
    return any(h in url for h in NOISE_HOSTS)


def _relevance_ok(row: dict, query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return True
    keywords = re.findall(r"[\u4e00-\u9fff]{2,}", q)
    if not keywords:
        keywords = [w.strip("\"'") for w in q.split() if len(w) > 2][:3]
    if not keywords:
        return True
    title = row.get("title", "")
    content = row.get("content", "")
    url = row.get("url", "")
    text = f"{title} {content} {url}".lower()

    # 关键词必须出现在 title 或 content 中（不能只在 URL 里）
    title_content = f"{title} {content}".lower()
    has_keyword_in_body = any(kw.lower() in title_content for kw in keywords)
    if not has_keyword_in_body:
        return False

    # 如果查询包含中文，结果的 title+content 也必须包含中文
    has_chinese_query = _has_chinese(q)
    if has_chinese_query:
        body_text = f"{title} {content}"
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", body_text)
        if len(chinese_chars) < 5:  # 至少5个中文字符才算有意义的中文内容
            return False

    return True


def _dedupe(rows: list, max_results: int, query: str = "") -> list:
    out, seen = [], set()
    for r in rows:
        u = r.get("url", "")
        if not u or u in seen or _is_noise(r):
            continue
        if query and not _relevance_ok(r, query):
            continue
        seen.add(u)
        out.append(r)
    return out[:max_results]


def _clear_proxy_env() -> dict:
    """临时清除代理环境变量，返回备份。"""
    backup = {}
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "all_proxy", "ALL_PROXY"):
        if k in os.environ:
            backup[k] = os.environ.pop(k)
    return backup


def _restore_proxy_env(backup: dict):
    os.environ.update(backup)


# ── 金融查询判定 ────────────────────────────────────────

_FINANCE_KEYWORDS = (
    '股价', '行情', '财报', '营收', '净利润', '估值', '市盈率', '市净率',
    'PE', 'PB', 'PS', '市值', '涨幅', '跌停', '涨停', '资金流向',
    '毛利率', '净利率', 'ROE', 'ROIC', '分红', '股息', '派息',
    '业绩', '年报', '季报', '半年报', '中报', 'EPS', 'EBITDA',
    'stock price', 'market cap', 'earnings', 'revenue', 'valuation',
    'dividend', 'financial', 'balance sheet', 'income statement',
    '板块', '龙头股', '基金', 'ETF', '指数',
)
_STOCK_CODE_PATTERN = re.compile(
    r'\b(\d{6}|0\d{4})\b'  # A股6位/港股5位代码
    r'|[A-Z]{2,5}\.[A-Z]{2}'  # ticker: 600519.SS, 0700.HK, AAPL
    r'|\b[A-Z]{1,5}\b'  # 美股 ticker (短)
)


def _is_finance_query(query: str) -> bool:
    """判断查询是否为金融类查询（用于触发 NeoData Layer 0）。"""
    q_lower = query.lower()
    # 关键词命中
    if any(kw.lower() in q_lower for kw in _FINANCE_KEYWORDS):
        return True
    # 股票代码模式
    if _STOCK_CODE_PATTERN.search(query):
        return True
    return False


# ── Layer 0: NeoData 金融数据 ─────────────────────────

def _neodata_read_token() -> Optional[str]:
    """从缓存文件读取 NeoData token（12 小时有效期）。"""
    try:
        raw = NEODATA_TOKEN_FILE.read_text().strip()
        if not raw:
            return None
        data = json.loads(raw)
        saved_at = data.get("saved_at", 0)
        token = data.get("token", "")
        if not token:
            return None
        if _time.time() - saved_at > NEODATA_TOKEN_TTL:
            return None
        return token
    except (FileNotFoundError, PermissionError, json.JSONDecodeError, TypeError):
        return None


def neodata_search(query: str, data_type: str = "api") -> list:
    """通过 NeoData API 查询金融数据，返回统一格式的搜索结果列表。

    data_type: "api" = 仅结构化数据, "doc" = 仅文章, "all" = 两者都取
    返回格式与 search() 统一：[{"title", "url", "content", "engine", "source"}]
    """
    token = _neodata_read_token()
    if not token:
        return []

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "query": query,
        "channel": "neodata",
        "sub_channel": "workbuddy",
    }
    if data_type != "all":
        payload["data_type"] = data_type

    try:
        resp = requests.post(NEODATA_ENDPOINT, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        body = resp.json()
    except Exception:
        return []

    if body.get("code") != "200" or not body.get("suc"):
        return []

    results = []
    data = body.get("data", {})

    # 结构化 API 数据 → 转为统一搜索结果格式
    api_data = data.get("apiData", {})
    entity_list = api_data.get("entity", [])
    entity_name = entity_list[0].get("name", query) if entity_list else query

    for recall in api_data.get("apiRecall", []):
        content = recall.get("content", "")
        if not content:
            continue
        results.append({
            "title": f"{entity_name} — {recall.get('type', '金融数据')}",
            "url": "",
            "content": content,
            "engine": "neodata",
            "source": "neodata:api",
            "tag": recall.get("tag", ""),
        })

    # 文章数据 → 转为统一搜索结果格式
    doc_data = data.get("docData") or {}
    for group in doc_data.get("docRecall", []):
        for doc in group.get("docList", []):
            title = doc.get("title", "")
            url = doc.get("url", "")
            snippet = doc.get("snippet", "") or doc.get("content", "")
            if not title:
                continue
            results.append({
                "title": title,
                "url": url,
                "content": snippet[:500] if snippet else "",
                "engine": "neodata",
                "source": "neodata:doc",
                "publishedDate": doc.get("publishDate", ""),
            })

    return results


def neodata_summary(entity: str) -> Optional[dict]:
    """通过 NeoData 获取公司估值快照，返回与 yfinance_summary 兼容的 dict。

    仅返回结构化行情数据，用于 valuation_enricher 交叉验证。
    """
    results = neodata_search(f"{entity} 行情 估值", data_type="api")
    if not results:
        return None

    # 从 NeoData 返回的 content 文本中提取关键指标
    content = "\n".join(r.get("content", "") for r in results)
    if not content:
        return None

    def _extract(pattern: str, text: str, as_float: bool = True) -> Any:
        m = re.search(pattern, text)
        if not m:
            return None
        val = m.group(1).replace(",", "").replace("，", "").strip()
        if as_float:
            try:
                return float(val)
            except (ValueError, TypeError):
                return None
        return val

    price = _extract(r'最新价格[：:]\s*([\d,.]+)', content)
    pe = _extract(r'市盈率\(TTM\)[：:]\s*([\d,.]+)', content)
    pb = _extract(r'市净率[：:]\s*([\d,.]+)', content)
    market_cap = _extract(r'(?:流通)?市值\(亿元\)[：:]\s*([\d,.]+)', content)
    volume = _extract(r'成交金额\(万元\)[：:]\s*([\d,.]+)', content)

    if not price:
        return None

    # 市值从亿转为元（与 yfinance 对齐）
    market_cap_raw = market_cap * 1e8 if market_cap else None

    return {
        "ticker": "",
        "price": price,
        "market_cap": market_cap_raw,
        "pe_trailing": pe,
        "pe_forward": None,
        "ps": None,
        "pb": pb,
        "ev_ebitda": None,
        "revenue": None,
        "profit_margin": None,
        "sector": "",
        "industry": "",
        "currency": "CNY",
        "volume_wan": volume,
        "source": "neodata",
    }


# ── Layer 1: DDG Python API 直连 ──────────────────────

def _ddg_search(query: str, max_results: int = 10) -> list:
    """DDG 直连搜索（清掉代理，中英文都好用）。"""
    backup = _clear_proxy_env()
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            region = "cn-zh" if _has_chinese(query) else "wt-wt"
            raw = list(ddgs.text(query, max_results=max_results + 5, region=region))
        parsed = [{
            "title": r.get("title", ""),
            "url": r.get("href", ""),
            "content": r.get("body", ""),
            "engine": "ddg",
            "source": "ddg:direct",
        } for r in raw if r.get("href")]
        return _dedupe(parsed, max_results, query=query)
    except Exception:
        pass
    finally:
        _restore_proxy_env(backup)

    # CLI fallback（也清代理）
    backup2 = _clear_proxy_env()
    try:
        if not os.path.exists(DDGS_BIN):
            return []
        result = subprocess.run(
            [DDGS_BIN, "text", "-k", query, "-m", str(max_results + 5), "-r", "wt-wt"],
            capture_output=True, text=True, timeout=30,
            env={k: v for k, v in os.environ.items()},
        )
        if result.returncode == 0 and result.stdout.strip():
            return _parse_ddgs_text(result.stdout, max_results, query=query)
    except Exception:
        pass
    finally:
        _restore_proxy_env(backup2)
    return []


def _parse_ddgs_text(stdout: str, max_results: int, query: str = "") -> list:
    results, current = [], None
    for line in stdout.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if re.match(r"^\d+\.\s*=+", line):
            if current and current.get("title"):
                results.append(current)
            current = {"title": "", "url": "", "content": "", "engine": "ddg", "source": "ddg:cli"}
            continue
        if current is None:
            continue
        s = line.strip()
        if s.startswith("title"):
            current["title"] = s[5:].strip()
        elif s.startswith("href"):
            current["url"] = s[4:].strip()
        elif s.startswith("body"):
            current["content"] = s[4:].strip()
        elif current.get("content") and not re.match(r"^(title|href|body)\b", s):
            current["content"] += " " + s
    if current and current.get("title"):
        results.append(current)
    return _dedupe(results, max_results, query=query)


# ── Layer 2: SearXNG ──────────────────────────────────

def _searxng_search(query: str, max_results: int = 10, engines: str = "", timeout: int = 25) -> list:
    params: dict[str, Any] = {
        "q": query,
        "format": "json",
        "language": "zh-CN" if _has_chinese(query) else "en",
    }
    if engines:
        params["engines"] = engines
    try:
        r = _LOCAL.get(
            f"{SEARXNG_URL}/search",
            params=params,
            timeout=timeout,
            headers={"User-Agent": "IRSearchGateway/4.0"},
            verify=False,
        )
        r.raise_for_status()
        data = r.json()
        out = []
        for item in data.get("results", []):
            url = item.get("url") or item.get("href", "")
            if not url:
                continue
            out.append({
                "title": item.get("title", ""),
                "url": url,
                "content": item.get("content") or item.get("body", ""),
                "engine": item.get("engine", "searxng"),
                "source": "searxng",
                "publishedDate": item.get("publishedDate", ""),
            })
        return _dedupe(out, max_results, query=query)
    except Exception:
        return []


# ── Layer 3: Google 直接抓取 ──────────────────────────

def google_search(query: str, max_results: int = 10) -> list:
    """走 7897 代理抓 Google 搜索页。
    
    Google 现在返回 JS 渲染页面，Fetcher 无法解析。
    改用 requests + 代理 + 特殊 User-Agent 请求非 JS 版本。
    """
    try:
        lang = "zh-CN" if _has_chinese(query) else "en"
        url = f"https://www.google.com/search?q={quote_plus(query)}&hl={lang}&num={max_results + 5}"
        
        r = requests.get(
            url,
            proxies={"http": PROXY_URL, "https": PROXY_URL},
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
                "Accept": "text/html",
                "Accept-Language": f"{lang},en;q=0.5",
            },
            timeout=20,
        )
        if r.status_code != 200:
            return []

        results = []
        html = r.text
        # Googlebot UA 返回的是简化 HTML，用正则提取
        # 匹配 <a href="/url?q=REAL_URL&...">TITLE</a>
        import re as _re
        for m in _re.finditer(r'<a\s+href="/url\?q=([^&"]+)&[^"]*"[^>]*>(.*?)</a>', html):
            href = m.group(1)
            title_html = m.group(2)
            # 清理 title 中的 HTML 标签
            title = _re.sub(r'<[^>]+>', '', title_html).strip()
            if not href or not title:
                continue
            if any(skip in href for skip in ("google.com", "gstatic.com", "youtube.com/results")):
                continue
            results.append({
                "title": title,
                "url": href,
                "content": "",
                "engine": "google",
                "source": "google:direct",
            })
            if len(results) >= max_results:
                break
        return _dedupe(results, max_results, query=query)
    except Exception:
        return []


# ── Layer 4: scrapling 深度抓取 ───────────────────────

def fetch_page(url: str, timeout: int = 20, use_proxy: bool = False) -> Optional[str]:
    """用 scrapling 抓取页面正文，返回纯文本。"""
    try:
        from scrapling.fetchers import Fetcher
        kwargs: dict[str, Any] = {"stealthy_headers": True, "timeout": timeout}
        if use_proxy:
            kwargs["proxy"] = PROXY_URL
        page = Fetcher.get(url, **kwargs)
        if page.status == 200:
            text = page.get_all_text() or ""
            return text[:50000] if text else None
    except Exception:
        pass
    # requests fallback
    try:
        proxies = {"http": PROXY_URL, "https": PROXY_URL} if use_proxy else None
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}, proxies=proxies)
        r.raise_for_status()
        from html.parser import HTMLParser
        class _Strip(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts: list[str] = []
            def handle_data(self, d: str):
                self.parts.append(d)
        s = _Strip()
        s.feed(r.text)
        return " ".join(s.parts)[:50000]
    except Exception:
        return None


# ── Layer 5: yfinance 估值数据 ────────────────────────

def yfinance_summary(ticker: str) -> Optional[dict]:
    """获取上市公司估值快照（IR 管线专用）。需要走代理访问 Yahoo Finance。"""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info or {}
        if not info.get("regularMarketPrice"):
            return None
        return {
            "ticker": ticker,
            "price": info.get("regularMarketPrice"),
            "market_cap": info.get("marketCap"),
            "pe_trailing": info.get("trailingPE"),
            "pe_forward": info.get("forwardPE"),
            "ps": info.get("priceToSalesTrailing12Months"),
            "pb": info.get("priceToBook"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "revenue": info.get("totalRevenue"),
            "profit_margin": info.get("profitMargins"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "currency": info.get("currency"),
        }
    except Exception:
        return None


# ── 主搜索接口 ────────────────────────────────────────

def search(query: str, max_results: int = 10, timeout: int = 25, prefer: str = "auto") -> list:
    """统一搜索入口。

    prefer:
        auto    - 金融查询先走 NeoData Layer 0，不够再 DDG + SearXNG 补充
        ddg     - 只用 DDG
        searxng  - 只用 SearXNG
        google   - 只用 Google 直接抓取
        multi    - NeoData + DDG + SearXNG + Google 四路合并（最全）
        neodata  - 只用 NeoData
    """
    if prefer == "neodata":
        return neodata_search(query, data_type="all")

    if prefer == "ddg":
        return _ddg_search(query, max_results)

    if prefer == "searxng":
        return _searxng_search(query, max_results, timeout=timeout)

    if prefer == "google":
        return google_search(query, max_results)

    if prefer == "multi":
        s0 = neodata_search(query, data_type="all") if _is_finance_query(query) else []
        s1 = _ddg_search(query, max_results + 5)
        s2 = _searxng_search(query, max_results + 5, timeout=timeout)
        s3 = google_search(query, max_results + 5)
        return _dedupe(s0 + s1 + s2 + s3, max_results, query=query)

    # auto: 金融查询先走 NeoData Layer 0，不够再 DDG + SearXNG 补充
    results = []
    if _is_finance_query(query):
        results = neodata_search(query, data_type="all")
        if len(results) >= max_results:
            return results

    # DDG 优先，不够再补 SearXNG
    ddg_results = _ddg_search(query, max_results)
    results = _dedupe(results + ddg_results, max_results, query=query)
    if len(results) >= max_results:
        return results
    need = max_results - len(results)
    results += _searxng_search(query, need + 3, timeout=timeout)
    return _dedupe(results, max_results, query=query)


def search_deep(query: str, max_results: int = 5, fetch_top_n: int = 3, use_proxy: bool = False) -> list:
    """搜索 + 对 top N 结果做 scrapling 正文抓取。"""
    rows = search(query, max_results=max_results, prefer="multi")
    for row in rows[:fetch_top_n]:
        url = row.get("url", "")
        if not url:
            continue
        # 国外站走代理，国内站直连
        need_proxy = use_proxy or not any(d in url for d in (".cn", "baidu.com", "zhihu.com", "163.com", "qq.com", "sina.com"))
        text = fetch_page(url, use_proxy=need_proxy)
        if text:
            row["full_text"] = text[:8000]
    return rows


def search_many(queries: List[str], max_results: int = 8, prefer: str = "auto") -> Dict[str, list]:
    return {q: search(q, max_results=max_results, prefer=prefer) for q in queries}


def verify_engines() -> dict:
    searxng_ok = False
    try:
        r = _LOCAL.get(f"{SEARXNG_URL}/healthz", timeout=5)
        searxng_ok = r.status_code == 200
    except Exception:
        pass

    ddg_ok = False
    try:
        from ddgs import DDGS
        ddg_ok = True
    except ImportError:
        ddg_ok = os.path.exists(DDGS_BIN)

    scrapling_ok = False
    try:
        from scrapling.fetchers import Fetcher
        scrapling_ok = True
    except ImportError:
        pass

    google_ok = False
    try:
        from scrapling.fetchers import Fetcher
        google_ok = True  # scrapling 可用就能抓 Google
    except ImportError:
        pass

    yf_ok = False
    try:
        import yfinance
        yf_ok = True
    except ImportError:
        pass

    neodata_ok = _neodata_read_token() is not None

    proxy_ok = False
    try:
        r = requests.get("http://127.0.0.1:7897", timeout=3)
        proxy_ok = True
    except Exception:
        try:
            import socket
            s = socket.socket()
            s.settimeout(2)
            s.connect(("127.0.0.1", 7897))
            s.close()
            proxy_ok = True
        except Exception:
            pass

    return {
        "neodata": neodata_ok,
        "ddg": ddg_ok,
        "searxng": searxng_ok,
        "searxng_url": SEARXNG_URL,
        "google_direct": google_ok,
        "scrapling": scrapling_ok,
        "yfinance": yf_ok,
        "proxy": proxy_ok,
        "proxy_url": PROXY_URL,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("-n", "--max-results", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--deep", action="store_true")
    ap.add_argument("--prefer", choices=["auto", "ddg", "searxng", "google", "multi", "neodata"], default="auto")
    args = ap.parse_args()

    if args.verify:
        print(json.dumps(verify_engines(), ensure_ascii=False, indent=2))
        raise SystemExit(0)

    if not args.query:
        ap.error("query required unless --verify")

    if args.deep:
        rows = search_deep(args.query, max_results=args.max_results)
    else:
        rows = search(args.query, max_results=args.max_results, prefer=args.prefer)

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for i, r in enumerate(rows, 1):
            print(f'{i}. [{r.get("source", "?")}] {r.get("title", "")}')
            print(f'   URL: {r.get("url", "")}')
            if r.get("content"):
                print(f'   {r.get("content", "")[:240]}')
            if r.get("full_text"):
                print(f'   [深度抓取: {len(r["full_text"])} chars]')
            print()
