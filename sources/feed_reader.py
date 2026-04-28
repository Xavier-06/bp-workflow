"""
Feed Reader - Phase 2A.2
RSS/Atom feed 解析器，用于 market_news
"""

from __future__ import annotations
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import certifi
import ssl
import os

# SSL 配置
os.environ.setdefault('SSL_CERT_FILE', certifi.where())
os.environ.setdefault('REQUESTS_CA_BUNDLE', certifi.where())


@dataclass
class FeedItem:
    """Feed 条目"""
    title: str
    url: str
    published_at: str | None
    source_name: str
    source_family: str  # official, trusted_media, aggregator
    canonical_url: str
    snippet: str = ""
    is_official: bool = False
    
    def to_dict(self) -> dict:
        return {
            'title': self.title,
            'url': self.url,
            'published_at': self.published_at,
            'source_name': self.source_name,
            'source_family': self.source_family,
            'canonical_url': self.canonical_url,
            'is_official': self.is_official,
        }


class FeedReader:
    """
    RSS/Atom Feed 解析器
    
    职责：
    1. 拉取 RSS/Atom feed
    2. 解析 title/link/published_at
    3. URL canonicalize
    """
    
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self._init_session()
    
    def _init_session(self):
        """初始化 requests session"""
        import requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; OpenClawFeedBot/1.0)',
            'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml',
        })
    
    def fetch_feed(self, feed_url: str) -> list[FeedItem]:
        """获取并解析 feed"""
        try:
            resp = self.session.get(feed_url, timeout=self.timeout, verify=False)
            resp.raise_for_status()
            
            content = resp.content
            return self._parse_feed(content, feed_url)
            
        except Exception as e:
            print(f"  Feed fetch error: {feed_url[:50]}... - {str(e)[:50]}")
            return []
    
    def _parse_feed(self, content: bytes, feed_url: str) -> list[FeedItem]:
        """解析 RSS/Atom feed"""
        items = []
        
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            # 尝试修复常见的 XML 问题
            try:
                text = content.decode('utf-8', errors='ignore')
                # 移除 BOM
                text = text.lstrip('\ufeff')
                root = ET.fromstring(text)
            except Exception:
                return []
        
        source_name = urlparse(feed_url).netloc
        
        # 检测 feed 类型
        is_atom = root.tag.endswith('feed')
        
        if is_atom:
            # Atom feed
            for entry in root.findall('.//{http://www.w3.org/2005/Atom}entry')[:10]:
                item = self._parse_atom_entry(entry, source_name)
                if item:
                    items.append(item)
        else:
            # RSS feed
            for item_elem in root.findall('.//item')[:10]:
                item = self._parse_rss_item(item_elem, source_name)
                if item:
                    items.append(item)
        
        return items
    
    def _parse_rss_item(self, item_elem, source_name: str) -> FeedItem | None:
        """解析 RSS item"""
        title_elem = item_elem.find('title')
        link_elem = item_elem.find('link')
        pubdate_elem = item_elem.find('pubDate')
        description_elem = item_elem.find('description')
        
        if title_elem is None or link_elem is None:
            return None
        
        title = title_elem.text or ""
        url = link_elem.text or ""
        
        if not title or not url:
            return None
        
        published_at = None
        if pubdate_elem is not None and pubdate_elem.text:
            published_at = self._parse_date(pubdate_elem.text)
        
        snippet = ""
        if description_elem is not None and description_elem.text:
            snippet = description_elem.text[:200]
        
        canonical_url = self._canonicalize_url(url)
        
        return FeedItem(
            title=title.strip(),
            url=url.strip(),
            published_at=published_at,
            source_name=source_name,
            source_family='official',  # 来自 profile 的 feed 都是 official
            canonical_url=canonical_url,
            snippet=snippet,
            is_official=True,
        )
    
    def _parse_atom_entry(self, entry_elem, source_name: str) -> FeedItem | None:
        """解析 Atom entry"""
        ns = '{http://www.w3.org/2005/Atom}'
        
        title_elem = entry_elem.find(f'{ns}title')
        link_elems = entry_elem.findall(f'{ns}link')
        published_elem = entry_elem.find(f'{ns}published') or entry_elem.find(f'{ns}updated')
        summary_elem = entry_elem.find(f'{ns}summary')
        
        if title_elem is None:
            return None
        
        title = title_elem.text or ""
        url = ""
        
        for link_elem in link_elems:
            href = link_elem.get('href', '')
            rel = link_elem.get('rel', '')
            if href and rel != 'self':
                url = href
                break
        
        if not title or not url:
            return None
        
        published_at = None
        if published_elem is not None and published_elem.text:
            published_at = self._parse_date(published_elem.text)
        
        snippet = ""
        if summary_elem is not None and summary_elem.text:
            snippet = summary_elem.text[:200]
        
        canonical_url = self._canonicalize_url(url)
        
        return FeedItem(
            title=title.strip(),
            url=url.strip(),
            published_at=published_at,
            source_name=source_name,
            source_family='official',
            canonical_url=canonical_url,
            snippet=snippet,
            is_official=True,
        )
    
    def _parse_date(self, date_str: str) -> str | None:
        """解析日期字符串"""
        date_str = date_str.strip()
        
        # 尝试多种格式
        formats = [
            '%a, %d %b %Y %H:%M:%S %z',
            '%a, %d %b %Y %H:%M:%S GMT',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%dT%H:%M:%S%z',
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except ValueError:
                continue
        
        # ISO 格式尝试
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.isoformat()
        except ValueError:
            pass
        
        return None
    
    def _canonicalize_url(self, url: str) -> str:
        """URL 标准化"""
        parsed = urlparse(url)
        # 移除常见追踪参数
        clean_path = parsed.path
        return f"{parsed.scheme}://{parsed.netloc}{clean_path}"
    
    def fetch_newsroom_page(self, url: str) -> list[FeedItem]:
        """从 newsroom 页面提取新闻链接"""
        try:
            import requests
            from content.fetcher import ContentFetcher
            
            fetcher = ContentFetcher(timeout=self.timeout)
            doc = fetcher.fetch(url)
            
            if not doc.text:
                return []
            
            # 从页面提取链接
            items = []
            links = re.findall(r'href=["\']([^"\']*(?:news|blog|press|article)[^"\']*)["\']', doc.text, re.I)
            
            seen = set()
            for link in links[:10]:
                if link.startswith('/'):
                    link = f"https://{urlparse(url).netloc}{link}"
                elif not link.startswith('http'):
                    continue
                
                if link in seen:
                    continue
                seen.add(link)
                
                items.append(FeedItem(
                    title="",  # 需要后续填充
                    url=link,
                    published_at=None,
                    source_name=urlparse(url).netloc,
                    source_family='official',
                    canonical_url=link,
                    is_official=True,
                ))
            
            return items
            
        except Exception as e:
            print(f"  Newsroom parse error: {str(e)[:50]}")
            return []


# 全局实例
_reader: FeedReader | None = None

def get_feed_reader() -> FeedReader:
    global _reader
    if _reader is None:
        _reader = FeedReader()
    return _reader