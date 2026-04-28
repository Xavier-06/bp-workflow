"""
Source Router - Phase 2A 任务级源路由
支持更智能的域名匹配和官方源识别
"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent

# 官方域名指示器
OFFICIAL_DOMAIN_SUFFIXES = ['.com', '.cn', '.com.cn', '.org', '.net']
OFFICIAL_PATH_PATTERNS = ['/about', '/ir', '/investor', '/company', '/newsroom', '/press', '/news', '/blog']

# 排除域名（这些即使匹配后缀也不算官方）
EXCLUDE_DOMAINS = [
    'zhihu.com', 'toutiao.com', 'baidu.com', 'google.com', 'bing.com',
    'yahoo.com', 'sohu.com', 'sina.com.cn', '163.com', 'qq.com',
    'ifeng.com', 'eastmoney.com', 'xueqiu.com', 'weibo.com',
    'youtube.com', 'twitter.com', 'facebook.com', 'reddit.com',
]

# 披露域名
FILING_DOMAINS = ['sec.gov', 'hkexnews.hk', 'hkgnews.hkex.com.hk', 'gov']

# 权威媒体
TRUSTED_MEDIA_DOMAINS = [
    'bloomberg.com', 'reuters.com', 'ft.com', 'wsj.com', 'cnbc.com',
    'techcrunch.com', 'theverge.com', 'wired.com', 'arstechnica.com',
    'caixin.com', 'latepost.com', '36kr.com',
    # 新闻稿 / 财经分析
    'prnewswire.com', 'businesswire.com', 'globenewswire.com',
    'stockanalysis.com', 'macrotrends.net', 'wisesheets.io',
    'theregister.com', 'techradar.com', 'venturebeat.com',
    'nikkei.com', 'scmp.com', 'hkfp.com',
    'futunn.com', 'moomoo.com', 'eastmoney.com',
    'investing.com', 'marketwatch.com', 'seekingalpha.com',
]


@dataclass
class SourceFamily:
    family: str
    domains: list[str]
    priority: int
    description: str
    
    def matches(self, domain: str) -> bool:
        domain_lower = domain.lower()
        for pattern in self.domains:
            if pattern.startswith('.'):
                if domain_lower.endswith(pattern) or pattern[1:] in domain_lower:
                    return True
            elif pattern in domain_lower:
                return True
        return False


@dataclass
class SourcePolicy:
    task_type: str
    source_families: list[SourceFamily]
    query_templates: dict[str, str]
    gap_rules: list[str]
    
    def get_source_family(self, domain: str) -> str:
        """获取源类型"""
        domain_lower = domain.lower()
        
        # 先检查披露
        if any(fd in domain_lower for fd in FILING_DOMAINS):
            return 'filings'
        
        # 检查排除列表
        if any(ex in domain_lower for ex in EXCLUDE_DOMAINS):
            # 检查是否是权威媒体
            if any(tm in domain_lower for tm in TRUSTED_MEDIA_DOMAINS):
                return 'trusted_media'
            return 'aggregator'
        
        # 检查官方新闻室
        if any(np in domain_lower for np in ['newsroom.', 'press.', 'news.', 'blog.', 'about.']):
            return 'official_newsroom'
        
        # 检查官方指示器
        for family in self.source_families:
            if family.matches(domain):
                return family.family
        
        # 默认判断：如果域名看起来像公司官网
        if self._looks_like_official_domain(domain):
            return 'official'
        
        return 'other'
    
    def _looks_like_official_domain(self, domain: str) -> bool:
        """判断是否看起来像公司官网"""
        domain_lower = domain.lower()
        
        # 排除已知的非官方域名
        if any(ex in domain_lower for ex in EXCLUDE_DOMAINS):
            return False
        
        # 检查是否有官方路径
        # 注：这里我们只能检查域名，路径在 URL 中
        
        # 简单判断：短域名 + .com/.cn 后缀
        parts = domain_lower.split('.')
        if len(parts) == 2 or (len(parts) == 3 and parts[-2] == 'com'):
            # 例如 apple.com, nvidia.com, apple.com.cn
            return True
        
        return False
    
    def get_priority(self, domain: str) -> int:
        family = self.get_source_family(domain)
        for sf in self.source_families:
            if sf.family == family:
                return sf.priority
        return 0
    
    def is_official(self, domain: str) -> bool:
        family = self.get_source_family(domain)
        return family in ['official', 'filings', 'official_newsroom']
    
    def is_primary(self, domain: str) -> bool:
        family = self.get_source_family(domain)
        return family in ['official', 'filings', 'official_newsroom', 'primary_wire', 'trusted_media', 'trusted_news']
    
    def is_aggregator(self, domain: str) -> bool:
        return self.get_source_family(domain) == 'aggregator'


def load_source_policy(task_type: str) -> SourcePolicy:
    config_path = ROOT / 'config' / 'sources' / 'source_policy.json'
    
    if not config_path.exists():
        return _default_policy(task_type)
    
    config = json.loads(config_path.read_text(encoding='utf-8'))
    task_config = config.get(task_type, {})
    
    families = []
    for fc in task_config.get('source_priority', []):
        families.append(SourceFamily(
            family=fc['family'],
            domains=fc.get('domains', []),
            priority=fc.get('priority', 5),
            description=fc.get('description', ''),
        ))
    
    return SourcePolicy(
        task_type=task_type,
        source_families=families,
        query_templates=task_config.get('query_templates', {}),
        gap_rules=task_config.get('gap_rules', []),
    )


def _default_policy(task_type: str) -> SourcePolicy:
    return SourcePolicy(
        task_type=task_type,
        source_families=[],
        query_templates={},
        gap_rules=[],
    )


class SourceRouter:
    """源路由器"""
    
    def __init__(self, task_type: str):
        self.task_type = task_type
        self.policy = load_source_policy(task_type)
    
    def classify_evidence_source(self, domain: str, url: str = '') -> dict:
        """分类证据来源"""
        # 同时检查域名和 URL 路径
        domain_lower = domain.lower()
        url_lower = url.lower() if url else ''
        
        # 检查 URL 路径是否有官方指示器
        has_official_path = any(pattern in url_lower for pattern in ['/about', '/ir', '/investor', '/company', '/newsroom', '/press'])
        
        family = self.policy.get_source_family(domain)
        
        # 如果有官方路径，提升分类
        if has_official_path and family == 'other':
            family = 'official'
        
        return {
            'source_family': family,
            'priority': self.policy.get_priority(domain),
            'is_official': self.policy.is_official(domain) or has_official_path,
            'is_filing': family == 'filings',
            'is_primary': self.policy.is_primary(domain),
            'is_aggregator': self.policy.is_aggregator(domain),
        }
    
    def prioritize_hits(self, hits: list) -> list:
        """按源优先级排序"""
        scored = []
        for hit in hits:
            domain = getattr(hit, 'domain', '') or urlparse(getattr(hit, 'url', '')).netloc
            url = getattr(hit, 'url', '')
            info = self.classify_evidence_source(domain, url)
            scored.append((info['priority'], hit))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return [hit for _, hit in scored]
    
    def get_task_specific_queries(self, entity: str) -> list[str]:
        queries = []
        for template in self.policy.query_templates.values():
            queries.append(template.format(entity=entity))
        return queries
    
    def check_gap_rules(self, evidence_list: list) -> list[str]:
        gaps = []
        
        has_official = any(
            getattr(e, 'is_official', False) or 
            self.policy.is_official(getattr(e, 'domain', '') or urlparse(getattr(e, 'url', '')).netloc)
            for e in evidence_list
        )
        
        has_filing = any(
            getattr(e, 'is_filing', False) or
            self.policy.get_source_family(getattr(e, 'domain', '') or urlparse(getattr(e, 'url', '')).netloc) == 'filings'
            for e in evidence_list
        )
        
        only_secondary = all(
            not self.policy.is_primary(getattr(e, 'domain', '') or urlparse(getattr(e, 'url', '')).netloc)
            for e in evidence_list
        ) if evidence_list else True
        
        if 'no_official_source' in self.policy.gap_rules and not has_official:
            gaps.append("缺少官方来源（IR/官网）支撑")
        
        if 'no_filing_source' in self.policy.gap_rules and not has_filing:
            gaps.append("缺少监管披露（SEC/HKEX）支撑")
        
        return gaps


def get_router(task_type: str) -> SourceRouter:
    return SourceRouter(task_type)