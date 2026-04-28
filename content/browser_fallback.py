"""
Browser Fallback - Phase 2A.3
白名单域名级 JS 渲染 fallback
仅用于 openai.com 等需要 JavaScript 渲染的域名
"""

from __future__ import annotations
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import certifi

# SSL 配置
os.environ.setdefault('SSL_CERT_FILE', certifi.where())

# 白名单域名（仅这些域名启用浏览器 fallback）
BROWSER_FALLBACK_WHITELIST = {
    'openai.com',
    'chat.openai.com',
}


@dataclass
class BrowserFetchResult:
    """浏览器抓取结果"""
    url: str
    success: bool
    title: str = ""
    text: str = ""
    published_at: str | None = None
    domain: str = ""
    article_links: list[str] = None
    elapsed_ms: int = 0
    error: str | None = None
    fallback_used: bool = True
    fallback_reason: str = ""


class BrowserFallback:
    """
    浏览器渲染 fallback
    
    仅对白名单域名启用，仅用于 JavaScript 渲染的页面。
    """
    
    def __init__(self, timeout: int = 30, headless: bool = True):
        self.timeout = timeout
        self.headless = headless
        self._playwright = None
        self._browser = None
    
    def is_whitelisted(self, url: str) -> bool:
        """检查 URL 是否在白名单中"""
        domain = urlparse(url).netloc.lower()
        for whitelisted in BROWSER_FALLBACK_WHITELIST:
            if whitelisted in domain:
                return True
        return False
    
    def fetch(self, url: str, reason: str = "js_rendering_required") -> BrowserFetchResult:
        """使用浏览器抓取页面"""
        start = time.perf_counter()
        
        if not self.is_whitelisted(url):
            return BrowserFetchResult(
                url=url,
                success=False,
                error="domain_not_whitelisted",
                fallback_used=False,
                fallback_reason="Domain not in browser fallback whitelist",
            )
        
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                page = browser.new_page()
                
                # 设置超时
                page.set_default_timeout(self.timeout * 1000)
                
                # 访问页面
                page.goto(url, wait_until="networkidle")
                
                # 等待内容加载
                time.sleep(2)
                
                # 提取标题
                title = page.title()
                
                # 提取正文
                text = page.inner_text("body")
                
                # 提取文章链接（用于 blog 索引页）
                article_links = self._extract_article_links(page, url)
                
                # 提取发布时间
                published_at = self._extract_published_at(page)
                
                browser.close()
                
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                
                return BrowserFetchResult(
                    url=url,
                    success=True,
                    title=title,
                    text=text[:15000] if text else "",
                    published_at=published_at,
                    domain=urlparse(url).netloc,
                    article_links=article_links,
                    elapsed_ms=elapsed_ms,
                    fallback_used=True,
                    fallback_reason=reason,
                )
                
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return BrowserFetchResult(
                url=url,
                success=False,
                error=str(e)[:100],
                elapsed_ms=elapsed_ms,
                fallback_used=True,
                fallback_reason=reason,
            )
    
    def _extract_article_links(self, page, base_url: str) -> list[str]:
        """从页面提取文章链接"""
        links = []
        
        try:
            # OpenAI blog 特定的链接模式
            article_selectors = [
                'a[href*="/blog/"]',
                'a[href*="/research/"]',
                'article a',
                '.post-link',
                '.article-link',
            ]
            
            seen = set()
            for selector in article_selectors:
                elements = page.query_selector_all(selector)
                for elem in elements[:10]:
                    href = elem.get_attribute('href')
                    if href:
                        # 处理相对链接
                        if href.startswith('/'):
                            href = f"https://{urlparse(base_url).netloc}{href}"
                        elif not href.startswith('http'):
                            continue
                        
                        # 过滤非文章链接
                        if any(x in href for x in ['twitter.com', 'facebook.com', 'linkedin.com']):
                            continue
                        
                        if href not in seen:
                            seen.add(href)
                            links.append(href)
                
                if links:
                    break
        
        except Exception:
            pass
        
        return links[:10]
    
    def _extract_published_at(self, page) -> str | None:
        """提取发布时间"""
        try:
            # 尝试从 meta 标签提取
            time_selectors = [
                'meta[property="article:published_time"]',
                'meta[name="publishdate"]',
                'meta[name="date"]',
                'time[datetime]',
            ]
            
            for selector in time_selectors:
                elem = page.query_selector(selector)
                if elem:
                    content = elem.get_attribute('content') or elem.get_attribute('datetime')
                    if content:
                        return content
        except Exception:
            pass
        
        return None


# 全局实例
_fallback: BrowserFallback | None = None

def get_browser_fallback() -> BrowserFallback:
    global _fallback
    if _fallback is None:
        _fallback = BrowserFallback()
    return _fallback

def is_browser_fallback_enabled_for(url: str) -> bool:
    """检查 URL 是否启用了浏览器 fallback"""
    return get_browser_fallback().is_whitelisted(url)