"""
URL-first Direct Fetcher - Phase 2A.3
支持 OpenAI 专用路径和浏览器 fallback
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
import re

import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sources.entity_profile import get_entity_profile, EntitySourceProfile
from sources.feed_reader import FeedReader, FeedItem, get_feed_reader
from content.fetcher import ContentFetcher, FetchedDoc
from content.browser_fallback import BrowserFallback, BrowserFetchResult, get_browser_fallback


@dataclass
class DirectFetchResult:
    """直接抓取结果"""
    url: str
    source_type: str
    success: bool
    title: str = ""
    text: str = ""
    published_at: str | None = None
    domain: str = ""
    is_official: bool = True
    browser_fallback_used: bool = False
    error: str | None = None


class URLFirstDirectFetcher:
    """
    URL-first 直接抓取器 - Phase 2A.3
    支持 OpenAI 专用路径和浏览器 fallback
    """
    
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.content_fetcher = ContentFetcher(timeout=timeout)
        self.feed_reader = get_feed_reader()
        self.browser_fallback = get_browser_fallback()
    
    def fetch_company_sources(self, entity: str) -> list[DirectFetchResult]:
        """直接抓取公司研究源"""
        profile = get_entity_profile(entity)
        
        if not profile:
            print(f"  No profile for {entity}")
            return []
        
        results = []
        
        # 1. IR URLs
        for url in profile.ir_urls:
            print(f"  Fetching IR: {url[:50]}...")
            result = self._fetch_url(url, 'ir', profile)
            if result.success:
                results.append(result)
        
        # 2. Newsroom URLs
        for url in profile.newsroom_urls:
            print(f"  Fetching Newsroom: {url[:50]}...")
            result = self._fetch_url(url, 'newsroom', profile)
            if result.success:
                results.append(result)
        
        # 3. Official domains
        for domain in profile.official_domains:
            url = f"https://{domain}"
            print(f"  Fetching Official: {url[:50]}...")
            result = self._fetch_url(url, 'official', profile)
            if result.success:
                results.append(result)
        
        return results
    
    def fetch_news_sources(self, entity: str) -> list[DirectFetchResult]:
        """直接抓取新闻源 - Phase 2A.3 增强版"""
        profile = get_entity_profile(entity)
        
        if not profile:
            return []
        
        results = []
        
        # 1. RSS Feeds
        for feed_url in profile.rss_feeds:
            print(f"  Fetching Feed: {feed_url[:50]}...")
            feed_items = self.feed_reader.fetch_feed(feed_url)
            
            for item in feed_items[:5]:
                results.append(DirectFetchResult(
                    url=item.url,
                    source_type='feed',
                    success=True,
                    title=item.title,
                    text=item.snippet,
                    published_at=item.published_at,
                    domain=urlparse(item.url).netloc,
                    is_official=True,
                ))
        
        # 2. Sitemap（新增）
        for sitemap_url in profile.sitemap_urls:
            print(f"  Fetching Sitemap: {sitemap_url[:50]}...")
            sitemap_results = self._fetch_sitemap(sitemap_url, profile)
            results.extend(sitemap_results)
        
        # 3. Blog/Newsroom URLs（可能需要浏览器 fallback）
        for url in profile.blog_urls + profile.newsroom_urls:
            print(f"  Fetching Blog/Newsroom: {url[:50]}...")
            
            # 先尝试静态抓取
            result = self._fetch_url(url, 'newsroom', profile)
            
            # 如果失败且需要浏览器 fallback
            if not result.success and profile.needs_browser_fallback():
                print(f"    Static fetch failed, trying browser fallback...")
                result = self._fetch_with_browser(url, 'newsroom', profile)
            
            if result.success:
                results.append(result)
                
                # 如果是索引页，提取文章链接
                if result.text and len(result.text) < 5000:
                    # 可能是索引页，尝试提取链接
                    article_results = self._extract_articles_from_page(url, profile)
                    results.extend(article_results)
        
        return results
    
    def _fetch_url(self, url: str, source_type: str, profile: EntitySourceProfile) -> DirectFetchResult:
        """抓取单个 URL"""
        try:
            doc = self.content_fetcher.fetch(url)
            
            # 检查是否成功
            success = doc.fetch_status == 'ok' and doc.text and len(doc.text) > 100
            
            return DirectFetchResult(
                url=url,
                source_type=source_type,
                success=success,
                title=doc.title,
                text=doc.text or "",
                published_at=doc.published_at,
                domain=doc.domain,
                is_official=True,
                error=None if success else "empty_or_failed",
            )
            
        except Exception as e:
            return DirectFetchResult(
                url=url,
                source_type=source_type,
                success=False,
                error=str(e)[:100],
            )
    
    def _fetch_with_browser(self, url: str, source_type: str, profile: EntitySourceProfile) -> DirectFetchResult:
        """使用浏览器 fallback 抓取"""
        try:
            result = self.browser_fallback.fetch(
                url,
                reason=profile.browser_fallback_reason or "js_rendering_required"
            )
            
            return DirectFetchResult(
                url=url,
                source_type=source_type,
                success=result.success,
                title=result.title,
                text=result.text,
                published_at=result.published_at,
                domain=result.domain,
                is_official=True,
                browser_fallback_used=True,
                error=result.error,
            )
            
        except Exception as e:
            return DirectFetchResult(
                url=url,
                source_type=source_type,
                success=False,
                browser_fallback_used=True,
                error=str(e)[:100],
            )
    
    def _fetch_sitemap(self, sitemap_url: str, profile: EntitySourceProfile) -> list[DirectFetchResult]:
        """从 sitemap 提取文章链接"""
        results = []
        
        try:
            import requests
            import xml.etree.ElementTree as ET
            
            resp = requests.get(sitemap_url, timeout=10, verify=False)
            
            if resp.status_code != 200:
                return results
            
            root = ET.fromstring(resp.content)
            
            # 提取 URL
            urls = []
            for url_elem in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}url'):
                loc = url_elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
                if loc is not None and loc.text:
                    url = loc.text
                    # 过滤：只要 blog/research/news 相关的
                    if any(x in url.lower() for x in ['blog', 'research', 'news', 'press']):
                        urls.append(url)
            
            # 抓取前 5 个
            for url in urls[:5]:
                result = self._fetch_url(url, 'sitemap', profile)
                if result.success:
                    results.append(result)
            
            print(f"    Sitemap: found {len(urls)} article URLs, fetched {len(results)}")
            
        except Exception as e:
            print(f"    Sitemap error: {str(e)[:50]}")
        
        return results
    
    def _extract_articles_from_page(self, page_url: str, profile: EntitySourceProfile) -> list[DirectFetchResult]:
        """从页面提取文章链接"""
        results = []
        
        try:
            # 使用浏览器 fallback 提取链接
            if profile.needs_browser_fallback():
                browser_result = self.browser_fallback.fetch(page_url)
                
                if browser_result.article_links:
                    print(f"    Found {len(browser_result.article_links)} article links")
                    
                    for article_url in browser_result.article_links[:3]:
                        result = self._fetch_url(article_url, 'newsroom', profile)
                        if result.success:
                            results.append(result)
        
        except Exception as e:
            print(f"    Article extraction error: {str(e)[:50]}")
        
        return results


# 全局实例
_fetcher: URLFirstDirectFetcher | None = None

def get_direct_fetcher() -> URLFirstDirectFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = URLFirstDirectFetcher()
    return _fetcher