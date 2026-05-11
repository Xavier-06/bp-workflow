#!/usr/bin/env python3
"""
BP 尽调管线 — 正文提取层 v2

1. requests + bs4 (静态 HTML)
2. Playwright (JS 渲染 fallback)
3. LLM 信息抽取（qwen-plus）：从正文提取结构化事实

每篇文章的处理流程：
  抓取 → 清洗 → LLM 抽取结构化事实 → 写入证据库

用法:
  python3 scripts/extract_content.py --task-id TASK-XXX [--max-pages 20]
"""
import re
import json
import os
import ssl
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / "tasks"
CRED_FILE = WORKSPACE / '.credentials' / 'investment-research.env'
CERT_FILE = '/opt/homebrew/etc/openssl@3/cert.pem'

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TIMEOUT = 15

# 域名黑名单
DOMAIN_BLACKLIST = [
    'guba.eastmoney.com', 'zhihu.com/question', 'zhidao.baidu.com',
    'wenda.so.com', 'wenwen.sogou.com', 'tieba.baidu.com',
    'weibo.com', 'douyin.com',
]


def _is_blacklisted(url: str) -> bool:
    """检查 URL 是否在域名黑名单中"""
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or ''
        host_lower = host.lower()
        return any(bl in host_lower for bl in DOMAIN_BLACKLIST)
    except Exception:
        return False


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ── LLM extraction config ──

LLM_EXTRACT_SYSTEM = """你是一个专业投研尽调分析师。你的任务是从网页正文中提取与BP尽调相关的关键信息。

请提取以下信息（如果文中有的话）：
1. **公司/人物**: 提及的公司全称、简称、创始人/高管姓名+职务
2. **财务数据**: 收入、利润、融资额、估值、营收、订单金额等数字
3. **技术指标**: 产品型号、规格参数、性能指标
4. **市场数据**: 市占率、排名、客户数量、出货量
5. **关键事件**: 签约、融资、诉讼、处罚、IPO、产品发布
6. **声称/争议**: 文中提到的争议性说法、质疑、负面评价
7. **来源可信度**: 判断文章本身的权威性（官方/权威媒体/自媒体/论坛）

输出格式为严格 JSON：
{
  "entities": ["公司1", "公司2"],
  "people": [{"name": "姓名", "title": "职务"}],
  "financials": [{"type": "融资额", "value": "5000万", "unit": "CNY", "context": "2024年A轮"}],
  "tech_specs": [{"metric": "芯片制程", "value": "28nm", "context": ""}],
  "market_data": [{"metric": "市占率", "value": "15%", "context": "对讲机芯片国内"}],
  "events": [{"type": "签约", "description": "与XX签署战略合作", "date": "2025-03"}],
  "claims": [{"claim": "声称内容", "is_disputed": true/false, "context": "相关背景"}],
  "authority": "🅰|🅱|🅲",
  "summary": "一文段（100字内）概括核心信息"
}

如果某类信息文中没有提及，用空数组表示，不要编造。
"""

EXTRACT_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'


def _load_dashscope_key() -> str:
    """加载 DASHSCOPE_API_KEY，自动去引号"""
    key = None
    if CRED_FILE.exists():
        with open(CRED_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith('DASHSCOPE_API_KEY=') and not line.startswith('DASHSCOPE_API_KEY_'):
                    raw = line.split('=', 1)[1].strip()
                    key = raw.strip("'\"")
                    break
    if not key:
        key = os.environ.get('DASHSCOPE_API_KEY', '').strip("'\"")
    return key if key else ""


def _make_ssl_ctx() -> ssl.SSLContext:
    if Path(CERT_FILE).exists():
        os.environ['SSL_CERT_FILE'] = CERT_FILE
        return ssl.create_default_context(cafile=CERT_FILE)
    return ssl.create_default_context()


def _llm_extract(text: str, max_retries: int = 3) -> dict:
    """用千问-plus做LLM信息抽取，失败自动重试"""
    api_key = _load_dashscope_key()
    if not api_key:
        return {"error": "no_api_key", "fallback": "text_only"}

    ctx = _make_ssl_ctx()
    # 截断到12000字，控制token
    truncated_text = text[:12000] if text else ""
    
    body = json.dumps({
        'model': 'qwen-plus',
        'messages': [
            {'role': 'system', 'content': LLM_EXTRACT_SYSTEM},
            {'role': 'user', 'content': f'请分析以下网页内容并提取结构化信息：\n\n{truncated_text}'},
        ],
        'temperature': 0.2,
        'result_format': 'message',
    }).encode('utf-8')

    req = urllib.request.Request(
        EXTRACT_URL,
        data=body,
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'Authorization': f'Bearer {api_key}',
        },
        method='POST',
    )
    
    last_error = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
            parsed = _parse_json_response(content)
            if parsed:
                return parsed
            return {"error": "parse_failed", "raw": content[:500]}
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                import time
                wait = 2 ** (attempt + 1)  # 2s, 4s, 8s
                time.sleep(wait)
    
    return {"error": f"retries_exhausted ({last_error})"}


def _parse_json_response(content: str) -> dict:
    """Best-effort parse JSON from LLM output"""
    cleaned = content.strip()
    if cleaned.startswith('```'):
        lines = cleaned.split('\n')
        lines = [l for l in lines if not l.strip().startswith('```')]
        cleaned = '\n'.join(lines).strip()
    # 尝试找JSON代码块
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if json_match:
        cleaned = json_match.group(1).strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    # 尝试从长文本中提取第一个JSON对象
    start = content.find('{')
    end = content.rfind('}')
    if start >= 0 and end > start:
        try:
            return json.loads(content[start:end+1])
        except json.JSONDecodeError:
            pass
    return None


# ── Page fetching ──

def _clean_soup(soup: BeautifulSoup) -> str:
    """从 BeautifulSoup 提取正文文本"""
    for t in soup(["script", "style", "nav", "footer", "aside", "header", "noscript", "iframe", "form"]):
        t.decompose()
    
    body = soup.find("article") or soup.find("main") or soup.find("body")
    if not body:
        return ""
    
    lines = []
    for el in body.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "blockquote"]):
        txt = el.get_text(strip=True)
        if len(txt) > 8:
            lines.append(txt)
    
    return "\n".join(lines)[:8000]


def fetch_static(url: str) -> dict:
    """requests + bs4 抓取静态页"""
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, verify=True)
        ct = resp.headers.get("Content-Type", "")
        if "text/html" not in ct and "application/xhtml" not in ct:
            return {"title": "", "text": "", "status": "skip", "reason": f"非 HTML: {ct}"}
        
        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.find("h1").get_text(strip=True) if soup.find("h1") else ""
        text = _clean_soup(soup)
        
        if len(text) > 50:
            return {"title": title, "text": text, "status": "ok", "len": len(text), "engine": "requests+bs4"}
        
        return {"title": title, "text": text, "status": "empty", "len": len(text), "engine": "requests+bs4"}
    except Exception as e:
        return {"title": "", "text": "", "status": "fail", "reason": str(e)}


def fetch_js(url: str) -> dict:
    """Playwright 抓取 JS 渲染页"""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"User-Agent": UA})
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            title = soup.find("h1").get_text(strip=True) if soup.find("h1") else ""
            text = _clean_soup(soup)
            browser.close()
        
        if len(text) > 50:
            return {"title": title, "text": text, "status": "ok", "len": len(text), "engine": "playwright"}
        
        return {"title": title, "text": text, "status": "empty", "len": len(text), "engine": "playwright"}
    except Exception as e:
        return {"title": "", "text": "", "status": "fail", "reason": str(e)}


def fetch_url(url: str) -> dict:
    """先静态后 JS"""
    r1 = fetch_static(url)
    if r1["status"] == "ok":
        return r1
    
    r2 = fetch_js(url)
    return r2


def run(task_id: str, max_pages: int = 20, do_llm_extract: bool = True) -> dict:
    """从 presearch 结果中提取正文 + LLM 信息抽取"""
    task_dir = TASKS_DIR / task_id
    urls = []
    
    for md_file in sorted(task_dir.glob("bp_presearch_*.md")):
        with open(md_file, encoding="utf-8") as f:
            content = f.read()
        found = re.findall(r"\*\*URL\*\*\s*:\s*(https?://[^\s]+)", content)
        urls.extend(found[:3])
    
    # 去重 + 黑名单过滤
    urls = list(dict.fromkeys(urls))
    urls = [u for u in urls if not _is_blacklisted(u)]
    urls = urls[:max_pages]
    
    if not urls:
        print("  ⚠ 没有可抓取的 URL")
        return {"status": "no_urls"}
    
    print(f"📖 正文提取: {len(urls)} 个 URL (LLM 提取: {'on' if do_llm_extract else 'off'})")
    
    results = []
    extracted_facts = []
    success = 0
    llm_success = 0
    
    for i, url in enumerate(urls, 1):
        print(f"  [{i}/{len(urls)}] {url[:60]}... ", end="", flush=True)
        # Retry with exponential backoff
        data = None
        for attempt in range(3):
            data = fetch_url(url)
            if data.get("status") == "ok":
                break
            if attempt < 2:
                import time as _t
                _t.sleep(2)
        
        if data["status"] == "ok":
            success += 1
            print(f"✅ {data['engine']} | {data['len']} 字", end="")
            
            # LLM 信息抽取
            if do_llm_extract and data.get("text"):
                print(" → 🤖 extracting... ", end="", flush=True)
                extraction = _llm_extract(data["text"])
                if "error" not in extraction:
                    llm_success += 1
                    print(f"✅ {extraction.get('authority', '?')}", end="")
                    data["llm_extracted"] = extraction
                    
                    # 保存结构化事实
                    domain = urlparse(url).netloc
                    extracted_facts.append({
                        "source_url": url,
                        "source_domain": domain,
                        "title": data.get("title", ""),
                        "authority": extraction.get("authority", ""),
                        "summary": extraction.get("summary", ""),
                        "entities": extraction.get("entities", []),
                        "people": extraction.get("people", []),
                        "financials": extraction.get("financials", []),
                        "tech_specs": extraction.get("tech_specs", []),
                        "market_data": extraction.get("market_data", []),
                        "events": extraction.get("events", []),
                        "claims": extraction.get("claims", []),
                    })
                else:
                    print(f"⚠ LLM: {extraction.get('error', '?')}", end="")
                    data["llm_extracted"] = extraction
        
        else:
            print(f"❌ {data.get('reason', data['status'])}", end="")
        
        print()
        data["url"] = url
        results.append(data)
        time.sleep(0.5)
    
    print(f"\n✅ 正文提取: {success}/{len(urls)} 成功 | LLM 抽取: {llm_success} 篇")
    
    # 保存抓取结果（原始 + LLM 抽取）
    body_dir = task_dir / "body_content"
    body_dir.mkdir(exist_ok=True)
    with open(body_dir / "results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    # 保存结构化事实库（独立文件，供 Gap Detector / Gap-Driven 使用）
    if extracted_facts:
        facts_path = body_dir / "extracted_facts.json"
        with open(facts_path, "w", encoding="utf-8") as f:
            json.dump(extracted_facts, f, ensure_ascii=False, indent=2)
        print(f"  📋 结构化事实库: {len(extracted_facts)} 篇 → {facts_path}")
    
    return {"urls": len(urls), "success": success, "llm_extracted": llm_success, "status": "done"}


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--task-id", required=True)
    p.add_argument("--max-pages", type=int, default=20)
    p.add_argument("--no-llm", action="store_true", help="跳过 LLM 信息抽取")
    args = p.parse_args()
    run(args.task_id, max_pages=args.max_pages, do_llm_extract=not args.no_llm)


if __name__ == "__main__":
    main()
