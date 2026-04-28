#!/usr/bin/env python3
"""
IR 研报管线 — LLM 正文信息抽取层

从预搜索得到的证据 URL 中抓取正文，用 qwen-plus 提取结构化事实。
输出 body_content/ir_extracted_facts.json，供 Gap Detector 和深钻使用。

用法:
  python3 scripts/ir_extract_content.py --task-id TASK-XXX [--max-pages 15]
  python3 scripts/ir_extract_content.py --task-id TASK-XXX --entity "英伟达"
"""
from __future__ import annotations
import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from pathlib import Path

os.environ.setdefault('SSL_CERT_FILE', '/opt/homebrew/etc/openssl@3/cert.pem')
os.environ.setdefault('REQUESTS_CA_BUNDLE', '/opt/homebrew/etc/openssl@3/cert.pem')

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / 'data' / 'tasks'
CRED_FILE = WORKSPACE / '.credentials' / 'investment-research.env'
CERT_FILE = '/opt/homebrew/etc/openssl@3/cert.pem'
MAX_WORKERS = 3

EXTRACT_SYSTEM = """你是一个专业投研分析师。你的任务是从网页正文中提取与上市公司研报相关的关键信息。

请提取以下信息（如果文中有的话）：
1. **实体**: 提及的公司全称/简称/股票代码、高管姓名+职务
2. **财务数据**: 收入、利润、EPS、毛利率、经营现金流、估值数据（PE/PB/PS）、融资额
3. **业务数据**: 产品线、收入构成、客户数据、产能、出货量、门店数
4. **治理与股权**: 大股东变更、回购、减持、董事变动、股权激励
5. **事件**: 财报发布、产品发布、并购、诉讼、政策影响、行业事件
6. **风险**: 下行风险、竞争威胁、监管风险、流动性问题
7. **估值观点**: 分析师目标价、评级、看多/看空逻辑

输出格式为严格 JSON：
{
  "entities": [{"name": "公司名", "ticker": "代码", "type": "目标公司|竞品|供应商|客户"}],
  "people": [{"name": "姓名", "title": "职务", "company": "公司"}],
  "financials": [{"metric": "指标", "value": "数值", "period": "期间", "unit": "单位"}],
  "business_data": [{"metric": "指标", "value": "数值", "unit": "单位", "context": "说明"}],
  "governance": [{"type": "回购|减持|增持|董事变动|股权激励", "detail": "说明", "date": "日期"}],
  "events": [{"type": "财报|产品|并购|诉讼|政策", "description": "说明", "date": "日期", "impact": "影响"}],
  "risks": [{"risk": "风险", "severity": "高|中|低", "detail": "说明"}],
  "valuation_views": [{"source": "来源", "rating": "评级", "target_price": "目标价", "thesis": "逻辑"}],
  "authority": "A|B|C",
  "summary": "一段话（100字内）概括核心信息"
}

如果某类信息文中没有提及，用空数组表示，不要编造。
"""

EXTRACT_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
GARBAGE_DOMAINS = {
    'stackoverflow.com', 'github.com', 'npmjs.com', 'pypi.org',
    'twitter.com', 'x.com', 'facebook.com', 'instagram.com',
    'tiktok.com', 'pinterest.com', 'linkedin.com',
}
LOW_VALUE_TITLES = {'access denied', '403 forbidden', '404 not found', 'just a moment', 'captcha'}


def _load_api_key() -> str:
    if CRED_FILE.exists():
        for line in CRED_FILE.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line.startswith('DASHSCOPE_API_KEY=') and not line.startswith('DASHSCOPE_API_KEY_'):
                return line.split('=', 1)[1].strip().strip("'\"")
    return os.environ.get('DASHSCOPE_API_KEY', '')


def _make_ssl_ctx():
    if Path(CERT_FILE).exists():
        return ssl.create_default_context(cafile=CERT_FILE)
    return ssl.create_default_context()


def _call_llm(prompt: str, api_key: str, max_retries=2) -> str:
    for attempt in range(max_retries + 1):
        try:
            ctx = _make_ssl_ctx()
            body = json.dumps({
                'model': 'qwen-plus',
                'messages': [
                    {'role': 'system', 'content': EXTRACT_SYSTEM},
                    {'role': 'user', 'content': prompt},
                ],
                'temperature': 0.2,
                'max_tokens': 2048,
                'result_format': 'message',
            }).encode('utf-8')
            req = urllib.request.Request(
                EXTRACT_URL, data=body,
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
                method='POST',
            )
            with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            return data.get('choices', [{}])[0].get('message', {}).get('content', '')
        except Exception as e:
            if attempt < max_retries:
                time.sleep(2)
                continue
            return f'ERROR: {e}'


def _parse_json_llm(content: str) -> dict:
    cleaned = content.strip()
    # 提取代码块
    for block in re.findall(r'```(?:json)?\s*\n(.*?)\n```', cleaned, re.DOTALL):
        cleaned = block
        break
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    # 尝试找第一个 {
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start:end+1])
        except json.JSONDecodeError:
            pass
    return {'summary': content[:500], 'authority': 'C'}


def _is_garbage(url: str = '', title: str = '') -> bool:
    try:
        from urllib.parse import urlparse
        domain = (urlparse(url).hostname or '').lower().lstrip('www.')
        if domain in GARBAGE_DOMAINS:
            return True
    except Exception:
        pass
    if title.lower() in LOW_VALUE_TITLES:
        return True
    return False


def _fetch_text(url: str, timeout=15) -> tuple[str, str]:
    """返回 (title, text)，失败返回 ('', '')

    三层递进策略：
    1. Scrapling Fetcher — 快速请求 + TLS 指纹模拟（覆盖 90% 场景）
    2. Scrapling StealthyFetcher — 自动绕 Cloudflare 等反爬
    3. requests + BS4 fallback — 兜底
    """
    # ── Layer 1: Scrapling Fetcher (fast, TLS impersonation) ──
    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url, stealthy_headers=True)
        if page and page.status and page.status < 400:
            title = ''
            title_el = page.css('title')
            if title_el:
                title = title_el[0].text.strip() if hasattr(title_el[0], 'text') else str(title_el[0]).strip()
            text = page.get_all_text(separator=' ', strip=True)
            if text and len(text) >= 200:
                return (title or '', text[:8000])
    except Exception:
        pass

    # ── Layer 2: Scrapling StealthyFetcher (Cloudflare bypass) ──
    try:
        from scrapling.fetchers import StealthyFetcher
        page = StealthyFetcher.fetch(url, headless=True, solve_cloudflare=True, network_idle=True)
        if page and page.status and page.status < 400:
            title = ''
            title_el = page.css('title')
            if title_el:
                title = title_el[0].text.strip() if hasattr(title_el[0], 'text') else str(title_el[0]).strip()
            text = page.get_all_text(separator=' ', strip=True)
            if text and len(text) >= 200:
                return (title or '', text[:8000])
    except Exception:
        pass

    # ── Layer 3: requests + BS4 fallback ──
    try:
        import requests
        from bs4 import BeautifulSoup
        r = requests.get(url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
        })
        r.raise_for_status()
        soup = BeautifulSoup(r.content, 'html.parser')
        title_tag = soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else ''
        for tag in soup(['script', 'style', 'nav', 'footer', 'iframe']):
            tag.decompose()
        text = soup.get_text(separator=' ', strip=True)
        return (title or '', text[:8000])
    except Exception:
        return ('', '')


def extract_from_presearch(task_id: str, entity: str = '', max_pages: int = 15) -> dict:
    """从预搜索结果中提取证据 URL 并逐篇 LLM 信息抽取"""
    # 1. 收集 URL
    urls_to_process = []
    seen_urls = set()
    presearch_files = sorted(TASKS_DIR.glob(f'{task_id}-search-step*.md'))

    for pf in presearch_files:
        text = pf.read_text(encoding='utf-8')
        # Format 1: Markdown links [text](url)
        for m in re.finditer(r'\[([^\]]*)\]\((https?://[^)]+)\)', text):
            url = m.group(2).rstrip(').,;\n')
            if url not in seen_urls:
                seen_urls.add(url)
                urls_to_process.append(url)
        # Format 2: Footnote style [N] url
        for m in re.finditer(r'\[\d+\]\s+(https?://\S+)', text):
            url = m.group(1).rstrip(').,;\n')
            if url not in seen_urls:
                seen_urls.add(url)
                urls_to_process.append(url)

    if not urls_to_process:
        # 尝试 JSON 预搜索文件
        for jf in sorted(TASKS_DIR.glob(f'{task_id}-presearch-*.json')):
            try:
                data = json.loads(jf.read_text(encoding='utf-8'))
                for item in (data if isinstance(data, list) else data.get('results', [])):
                    u = item.get('url', '')
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        urls_to_process.append(u)
            except Exception:
                pass

    urls_to_process = urls_to_process[:max_pages]
    print(f"📄 共 {len(urls_to_process)} 个 URL 待处理")

    # 2. 逐篇处理
    api_key = _load_api_key()
    results = []
    for i, url in enumerate(urls_to_process, 1):
        if _is_garbage(url=url):
            print(f"  [{i}/{len(urls_to_process)}] ⏭ 跳过垃圾域名")
            results.append({'url': url, 'status': 'garbage'})
            continue

        print(f"  [{i}/{len(urls_to_process)}] 抓取 {url[:60]}...")
        title, text = _fetch_text(url)
        if not text or len(text) < 200:
            print(f"    ⏭ 正文太短，跳过")
            results.append({'url': url, 'status': 'too_short'})
            continue

        print(f"    正文 {len(text)} 字符，LLM 抽取中...")
        llm_output = _call_llm(
            f"请从以下正文中提取信息。\n\n标题: {title}\n\n正文:\n{text[:6000]}",
            api_key,
        )
        if llm_output.startswith('ERROR'):
            print(f"    ❌ LLM 错误: {llm_output[-80:]}")
            results.append({'url': url, 'status': 'llm_error'})
            continue

        facts = _parse_json_llm(llm_output)
        facts['url'] = url
        facts['title'] = title
        facts['_text_length'] = len(text)
        results.append({'url': url, 'status': 'ok', **facts})
        print(f"    ✅ 权威度: {facts.get('authority')}, 摘要: {facts.get('summary', '')[:60]}")
        time.sleep(0.5)

    # 3. 汇总输出
    body_dir = TASKS_DIR / f'{task_id}_body_content'
    body_dir.mkdir(exist_ok=True)

    output = {
        'task_id': task_id,
        'entity': entity,
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'total_urls': len(urls_to_process),
        'processed': len(results),
        'ok_count': sum(1 for r in results if r.get('status') == 'ok'),
        'results': results,
        # 聚合汇总
        'agg_entities': [],
        'agg_financials': [],
        'agg_events': [],
        'agg_risks': [],
        'agg_valuation_views': [],
    }

    # 聚合
    seen_entities = set()
    for r in results:
        if r.get('status') != 'ok':
            continue
        for e in r.get('entities', []):
            key = e.get('name', '')
            if key and key not in seen_entities:
                seen_entities.add(key)
                output['agg_entities'].append({**e, 'source': r.get('url')})
        for f_item in r.get('financials', []):
            output['agg_financials'].append({**f_item, 'source': r.get('url')})
        for ev in r.get('events', []):
            output['agg_events'].append({**ev, 'source': r.get('url')})
        for risk in r.get('risks', []):
            output['agg_risks'].append({**risk, 'source': r.get('url')})
        for vv in r.get('valuation_views', []):
            output['agg_valuation_views'].append({**vv, 'source': r.get('url')})

    # 写入
    facts_path = body_dir / 'ir_extracted_facts.json'
    facts_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"\n✅ 聚合: {len(output['agg_entities'])} 实体, "
          f"{len(output['agg_financials'])} 财务, {len(output['agg_events'])} 事件, "
          f"{len(output['agg_risks'])} 风险")
    print(f"📁 输出: {facts_path}")

    return output


def main():
    ap = argparse.ArgumentParser(description='IR 正文 LLM 信息抽取')
    ap.add_argument('--task-id', required=True, help='Task ID')
    ap.add_argument('--entity', default='', help='Entity name')
    ap.add_argument('--max-pages', type=int, default=15, help='最多处理页面数')
    args = ap.parse_args()

    extract_from_presearch(args.task_id, args.entity, args.max_pages)


if __name__ == '__main__':
    main()
