"""
Content Fetcher - Phase 1 正文抽取层
使用 Scrapling 只做单页抓取和正文提取，不做搜索
"""

from __future__ import annotations
import os
import re
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from typing import Literal
from urllib.parse import urlparse

import certifi

# Suppress InsecureRequestWarning — Scrapling uses verify=False
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# SSL 配置
CERT = '/opt/homebrew/etc/openssl@3/cert.pem'
if os.path.exists(CERT):
    os.environ.setdefault('SSL_CERT_FILE', CERT)
    os.environ.setdefault('REQUESTS_CA_BUNDLE', CERT)


@dataclass
class FetchedDoc:
    """抓取的文档"""
    url: str
    final_url: str  # 重定向后的最终 URL
    title: str
    published_at: str | None
    text: str  # 正文
    domain: str
    extraction_method: str  # scrapling, requests, snippet
    fetch_status: Literal['ok', 'partial', 'failed']
    confidence: str  # high, medium, low
    error: str | None = None
    meta: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            'url': self.url,
            'final_url': self.final_url,
            'title': self.title,
            'published_at': self.published_at,
            'text': self.text[:500] if self.text else '',
            'domain': self.domain,
            'extraction_method': self.extraction_method,
            'fetch_status': self.fetch_status,
            'confidence': self.confidence,
            'error': self.error,
        }


# 发布时间提取模式
TIME_PATTERNS = [
    (r'property=["\']article:published_time["\'][^>]*content=["\']([^"\']+)', 'meta'),
    (r'name=["\']pubdate["\'][^>]*content=["\']([^"\']+)', 'meta'),
    (r'name=["\']publishdate["\'][^>]*content=["\']([^"\']+)', 'meta'),
    (r'itemprop=["\']datePublished["\'][^>]*content=["\']([^"\']+)', 'meta'),
    (r'<time[^>]*datetime=["\']([^"\']+)', 'html'),
    (r'(\d{4}-\d{2}-\d{2})', 'text'),
    (r'(\d{4}/\d{2}/\d{2})', 'text'),
]

MONTHS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


def extract_text_from_html(html: str) -> str:
    """从 HTML 提取纯文本"""
    # 移除脚本、样式等
    html = re.sub(r'(?is)<script.*?>.*?</script>', ' ', html)
    html = re.sub(r'(?is)<style.*?>.*?</style>', ' ', html)
    html = re.sub(r'(?is)<noscript.*?>.*?</noscript>', ' ', html)
    html = re.sub(r'(?is)<!--.*?-->', ' ', html)
    
    # 替换块级元素为换行
    html = re.sub(r'(?i)<br\s*/?>', '\n', html)
    html = re.sub(r'(?i)</p>', '\n', html)
    html = re.sub(r'(?i)</div>', '\n', html)
    html = re.sub(r'(?i)</h[1-6]>', '\n', html)
    
    # 移除所有标签
    text = re.sub(r'(?s)<[^>]+>', ' ', html)
    
    # 清理
    text = unescape(text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    
    return text.strip()


def extract_published_at(html: str, url: str) -> str | None:
    """提取发布时间"""
    for pattern, source in TIME_PATTERNS:
        m = re.search(pattern, html, re.I)
        if m:
            val = m.group(1)
            # 尝试解析
            try:
                # ISO 格式
                if 'T' in val or '-' in val:
                    dt = datetime.fromisoformat(val.replace('Z', '+00:00'))
                    return dt.isoformat()
            except:
                pass
            
            # YYYY/MM/DD 格式
            m2 = re.match(r'(\d{4})/(\d{2})/(\d{2})', val)
            if m2:
                return f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}T00:00:00+00:00"
    
    # 从 URL 提取
    m = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', url)
    if m:
        return f"{m.group(1)}-{m2.group(2)}-{m.group(3)}T00:00:00+00:00"
    
    return None


def extract_title(html: str) -> str | None:
    """提取标题"""
    # <title> 标签
    m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
    if m:
        title = m.group(1).strip()
        # 清理常见的后缀
        title = re.sub(r'\s*[-|｜]\s*[^-|｜]+$', '', title)
        return title[:200] if title else None
    
    # og:title
    m = re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)', html, re.I)
    if m:
        return m.group(1).strip()[:200]
    
    return None


# Suppress InsecureRequestWarning — Scrapling uses requests with verify=False
# through proxies, which triggers urllib3 warnings on every request
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure Scrapling globally
try:
    from scrapling import Fetcher as _F
    _F.configure(auto_match=False, follow_redirects=True, verify=False)
except Exception:
    pass

class ContentFetcher:
    """
    内容抓取器 - Phase 1
    
    只负责：
    1. 单页抓取
    2. 正文提取
    3. 标题/时间提取
    
    不负责：
    - 搜索发现
    - 全站爬取
    - 代理池
    - 反爬编排
    """
    
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self._init_scrapling()
    
    def _init_scrapling(self):
        """初始化 Scrapling"""
        try:
            from scrapling import Fetcher
            Fetcher.configure(auto_match=False, follow_redirects=True, verify=False)
            self.fetcher = Fetcher()
            self._scrapling_available = True
        except Exception as e:
            self._scrapling_available = False
            self._scrapling_error = str(e)
    
    def fetch(self, url: str, snippet: str | None = None) -> FetchedDoc:
        """
        抓取单个 URL
        
        Args:
            url: 目标 URL
            snippet: 可选的摘要（作为 fallback）
        
        Returns:
            FetchedDoc
        """
        domain = urlparse(url).netloc.lower()
        
        if not url.startswith('http'):
            return FetchedDoc(
                url=url,
                final_url=url,
                title='',
                published_at=None,
                text=snippet or '',
                domain=domain,
                extraction_method='none',
                fetch_status='failed',
                confidence='low',
                error='invalid_url',
            )
        
        # PDF 直接提取
        if url.lower().endswith('.pdf'):
            try:
                from content.pdf_extractor import extract_pdf_url
                text = extract_pdf_url(url)
                if text:
                    return FetchedDoc(
                        url=url,
                        final_url=url,
                        title=url.split('/')[-1].replace('.pdf', '') or 'PDF Document',
                        published_at=None,
                        text=text,
                        domain=domain,
                        extraction_method='pdf',
                        fetch_status='ok',
                        confidence='high',
                    )
            except Exception as e:
                pass
        
        # 尝试用 Scrapling 抓取
        if self._scrapling_available:
            try:
                return self._fetch_with_scrapling(url, domain, snippet)
            except Exception as e:
                # Scrapling 失败，fallback 到 requests
                pass
        
        # Fallback: 使用 requests
        try:
            return self._fetch_with_requests(url, domain, snippet)
        except Exception as e:
            # 最终 fallback: 使用 snippet
            return FetchedDoc(
                url=url,
                final_url=url,
                title='',
                published_at=None,
                text=snippet or '',
                domain=domain,
                extraction_method='snippet',
                fetch_status='partial',
                confidence='low',
                error=str(e)[:100],
            )
    
    def _fetch_with_scrapling(self, url: str, domain: str, snippet: str | None) -> FetchedDoc:
        """使用 Scrapling 抓取"""
        from scrapling import Fetcher
        
        fetcher = Fetcher()
        response = fetcher.fetch(url, timeout=self.timeout)
        
        # 获取最终 URL
        final_url = response.url or url
        
        # 获取 HTML
        html = response.text if hasattr(response, 'text') else ''
        
        if not html:
            # Scrapling 没有返回 HTML，可能 body 是 bytes
            if hasattr(response, 'body'):
                html = response.body.decode('utf-8', errors='ignore') if isinstance(response.body, bytes) else response.body
        
        if not html:
            return FetchedDoc(
                url=url,
                final_url=final_url,
                title='',
                published_at=None,
                text=snippet or '',
                domain=domain,
                extraction_method='scrapling',
                fetch_status='failed',
                confidence='low',
                error='empty_response',
            )
        
        # 提取内容
        title = extract_title(html) or ''
        published_at = extract_published_at(html, final_url)
        text = extract_text_from_html(html)
        
        # 计算置信度
        confidence = self._calculate_confidence(domain, text, published_at)
        
        return FetchedDoc(
            url=url,
            final_url=final_url,
            title=title,
            published_at=published_at,
            text=text,
            domain=domain,
            extraction_method='scrapling',
            fetch_status='ok' if text else 'partial',
            confidence=confidence,
            meta={'html_length': len(html)},
        )
    
    def _fetch_with_requests(self, url: str, domain: str, snippet: str | None) -> FetchedDoc:
        """使用 requests 抓取（fallback）"""
        import requests
        
        resp = requests.get(
            url,
            timeout=self.timeout,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; OpenClawBot/1.0)'},
            verify=False,
        )
        
        final_url = resp.url or url
        html = resp.text
        
        title = extract_title(html) or ''
        published_at = extract_published_at(html, final_url)
        text = extract_text_from_html(html)
        
        confidence = self._calculate_confidence(domain, text, published_at)
        
        return FetchedDoc(
            url=url,
            final_url=final_url,
            title=title,
            published_at=published_at,
            text=text,
            domain=domain,
            extraction_method='requests',
            fetch_status='ok' if text else 'partial',
            confidence=confidence,
            meta={'status_code': resp.status_code},
        )
    
    def _calculate_confidence(self, domain: str, text: str, published_at: str | None) -> str:
        """计算置信度"""
        score = 0
        
        # 有正文
        if text and len(text) > 200:
            score += 2
        elif text and len(text) > 50:
            score += 1
        
        # 有时间
        if published_at:
            score += 1
        
        # 官方源
        if any(official in domain for official in ['ir.', 'investor', 'sec.gov', 'hkex', 'gov']):
            score += 2
        
        # 权威媒体
        trusted = ['reuters.com', 'bloomberg.com', 'ft.com', 'wsj.com', 'techcrunch.com', 'theverge.com']
        if any(t in domain for t in trusted):
            score += 1
        
        if score >= 4:
            return 'high'
        elif score >= 2:
            return 'medium'
        else:
            return 'low'
    
    def fetch_multiple(self, urls: list[str], snippets: list[str | None] | None = None,
                     max_workers: int = 8) -> list[FetchedDoc]:
        """批量抓取（并发，默认 8 线程）"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = [None] * len(urls)

        def _fetch_one(idx, url, snippet):
            try:
                return idx, self.fetch(url, snippet)
            except Exception as e:
                return idx, FetchedDoc(
                    url=url, final_url=url, title='',
                    published_at=None, text='',
                    domain=urlparse(url).netloc if url.startswith('http') else '',
                    extraction_method='failed', fetch_status='failed',
                    confidence='low', error=str(e)[:100],
                )

        workers = min(max_workers, len(urls)) if urls else 1
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for i, url in enumerate(urls):
                snippet = snippets[i] if snippets and i < len(snippets) else None
                fut = executor.submit(_fetch_one, i, url, snippet)
                futures[fut] = i

            for fut in as_completed(futures, timeout=180):
                try:
                    idx, doc = fut.result()
                    results[idx] = doc
                except Exception:
                    idx = futures[fut]
                    results[idx] = FetchedDoc(
                        url=urls[idx], final_url=urls[idx], title='',
                        published_at=None, text='',
                        domain=urlparse(urls[idx]).netloc if urls[idx].startswith('http') else '',
                        extraction_method='failed', fetch_status='failed',
                        confidence='low', error='timeout_or_exception',
                    )

        # Replace any None (shouldn't happen, but defensive)
        for i in range(len(results)):
            if results[i] is None:
                results[i] = FetchedDoc(
                    url=urls[i], final_url=urls[i], title='',
                    published_at=None, text='',
                    domain=urlparse(urls[i]).netloc if urls[i].startswith('http') else '',
                    extraction_method='failed', fetch_status='failed',
                    confidence='low', error='unknown',
                )

        return results


# 全局实例
_fetcher: ContentFetcher | None = None

def get_fetcher() -> ContentFetcher:
    """获取全局 Fetcher 实例"""
    global _fetcher
    if _fetcher is None:
        _fetcher = ContentFetcher()
    return _fetcher

def fetch(url: str, snippet: str | None = None) -> FetchedDoc:
    """便捷函数"""
    return get_fetcher().fetch(url, snippet)