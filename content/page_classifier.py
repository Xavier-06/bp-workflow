"""
Page-Type Classifier + Content-Quality Gate
Phase: Official Source Resolution

对已抓取的页面进行分类和质量判断：
1. 判断页面属于哪类 (press_release, policy_page, ir_landing_page, etc.)
2. 低价值页面不得直接进入 findings
3. IR landing page 必须继续 resolve
4. 正文质量 gate: 过滤掉垃圾正文
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

# ─── 页面类型定义 ─────────────────────────────────

PageType = Literal[
    'press_release',
    'newsroom_article',
    'ir_release',
    'filing_page',
    'filing_document',
    'earnings_release',
    'investor_landing_page',
    'policy_page',
    'navigation_page',
    'error_page',
    'blog_post',
    'news_article',
    'unknown',
]

# 低价值页面类型——不可直接进入 findings
# v2: investor_landing_page 不算低价值，只是需要继续 resolve
LOW_VALUE_TYPES: set[str] = {
    'policy_page',
    'navigation_page',
    'error_page',
}

# 需要继续 resolve 的页面类型
NEEDS_RESOLUTION_TYPES: set[str] = {
    'investor_landing_page',
    'navigation_page',
}

# ─── 关键词模式 ─────────────────────────────────────

# URL 路径模式 → 页面类型 (IR 路径优先，避免被 policy 匹配)
URL_PATH_PATTERNS: list[tuple[str, PageType]] = [
    (r'/investor', 'investor_landing_page'),
    (r'/ir/', 'investor_landing_page'),
    (r'/privacy', 'policy_page'),
    (r'/cookie', 'policy_page'),
    (r'/terms', 'policy_page'),
    (r'/legal', 'policy_page'),
    (r'/disclaimer', 'policy_page'),
    (r'/404', 'error_page'),
    (r'/not-found', 'error_page'),
    (r'/error', 'error_page'),
    (r'/press[-_]?release', 'press_release'),
    (r'/news[-_]?release', 'press_release'),
    (r'/earnings', 'earnings_release'),
    (r'/quarterly[-_]results', 'earnings_release'),
    (r'/annual[-_]report', 'filing_document'),
    (r'/10-[kK]', 'filing_document'),
    (r'/20-[fF]', 'filing_document'),
    (r'/sec[-_]?filing', 'filing_page'),
    (r'/filings', 'filing_page'),
    (r'/blog/', 'blog_post'),
    (r'/newsroom/', 'newsroom_article'),
    (r'/news/', 'newsroom_article'),
]

# 标题/内容关键词 → 页面类型（命中时加分）
CONTENT_SIGNALS: dict[PageType, list[str]] = {
    'policy_page': [
        'privacy policy', 'cookie policy', 'terms of service',
        'terms of use', 'legal notice', 'data protection',
        'your privacy', 'we use cookies', 'cookie consent',
        'gdpr', 'ccpa', 'data processing',
    ],
    'press_release': [
        'press release', 'news release', 'for immediate release',
        'media contact', 'investor contact',
    ],
    'earnings_release': [
        'quarterly results', 'quarterly earnings', 'fiscal quarter',
        'reports financial results', 'earnings per share',
        'revenue of', 'net income', 'operating income',
        'diluted eps', 'gaap', 'non-gaap',
    ],
    'filing_document': [
        'form 10-k', 'form 20-f', 'annual report',
        'form 10-q', 'quarterly report', 'form 8-k',
    ],
    'investor_landing_page': [
        'investor relations', 'investor overview',
        'shareholder information', 'stock information',
        'financial highlights', 'corporate governance',
    ],
    'navigation_page': [
        'site map', 'sitemap', 'page not found',
    ],
    'error_page': [
        'page not found', '404 error', 'this page does not exist',
        'the page you requested', 'page cannot be found',
    ],
}

# 实质信号词——有这些词说明是有价值的内容
SUBSTANCE_SIGNALS = [
    'revenue', 'earnings', 'quarter', 'annual', 'fiscal',
    'financial', 'results', 'profit', 'loss', 'growth',
    'million', 'billion', 'percent', 'guidance', 'outlook',
    'segment', 'operating', 'margin', 'cash flow', 'dividend',
    'filing', 'announcement', 'report', 'release',
    'acquisition', 'merger', 'partnership', 'agreement',
    'market share', 'competition', 'regulatory',
]


@dataclass
class PageClassification:
    """页面分类结果"""
    page_type: PageType
    confidence: float  # 0.0 ~ 1.0
    is_low_value: bool
    needs_resolution: bool
    quality_gate_passed: bool
    quality_reasons: list[str]
    substance_score: float  # 实质内容得分 0.0 ~ 1.0
    
    def to_dict(self) -> dict:
        return {
            'page_type': self.page_type,
            'confidence': round(self.confidence, 2),
            'is_low_value': self.is_low_value,
            'needs_resolution': self.needs_resolution,
            'quality_gate_passed': self.quality_gate_passed,
            'quality_reasons': self.quality_reasons,
            'substance_score': round(self.substance_score, 2),
        }


class PageClassifier:
    """
    页面类型分类器
    
    判断逻辑：
    1. URL 路径模式匹配
    2. 标题关键词匹配
    3. 正文关键词匹配
    4. 正文质量 gate
    """
    
    def classify(
        self,
        url: str,
        title: str,
        text: str,
        entity: str = '',
    ) -> PageClassification:
        """
        分类一个已抓取的页面
        
        Args:
            url: 页面 URL
            title: 页面标题
            text: 正文内容
            entity: 实体名（用于判断是否相关）
        
        Returns:
            PageClassification
        """
        scores: dict[PageType, float] = {}
        
        url_lower = url.lower()
        title_lower = (title or '').lower()
        text_lower = (text or '').lower()[:5000]  # 只看前 5000 字
        
        # 1. URL 路径匹配
        for pattern, ptype in URL_PATH_PATTERNS:
            if re.search(pattern, url_lower):
                scores[ptype] = scores.get(ptype, 0) + 3.0
        
        # 2. 标题 + 正文关键词匹配
        combined = title_lower + ' ' + text_lower
        for ptype, keywords in CONTENT_SIGNALS.items():
            hit_count = sum(1 for kw in keywords if kw in combined)
            if hit_count > 0:
                scores[ptype] = scores.get(ptype, 0) + hit_count * 1.5
        
        # 3. 特殊：IR landing page 检测
        #    - URL 是 /investor 或 /ir 的根路径
        #    - 内容很短或是导航链接集合
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        if re.match(r'^/(investor|ir|investors?)$', path, re.I):
            scores['investor_landing_page'] = scores.get('investor_landing_page', 0) + 5.0
        
        # 4. 确定最终类型
        if not scores:
            page_type: PageType = 'unknown'
            type_confidence = 0.0
        else:
            page_type = max(scores, key=scores.get)
            max_score = scores[page_type]
            type_confidence = min(1.0, max_score / 8.0)
        
        # 5. 正文质量 gate
        quality_reasons: list[str] = []
        substance_score = 0.0
        
        if not text or len(text.strip()) < 100:
            quality_reasons.append('text_too_short')
        else:
            # 计算实质内容占比
            substance_hits = sum(1 for s in SUBSTANCE_SIGNALS if s in text_lower)
            substance_score = min(1.0, substance_hits / 5.0)
            
            # 检查垃圾内容占比
            policy_hits = sum(1 for kw in CONTENT_SIGNALS['policy_page'] if kw in text_lower)
            if policy_hits >= 3:
                quality_reasons.append('policy_content_dominant')
            
            # 检查实体相关性
            if entity:
                entity_lower = entity.lower()
                entity_parts = re.split(r'[\s/,]+', entity_lower)
                entity_found = any(part in text_lower for part in entity_parts if len(part) >= 2)
                if not entity_found:
                    quality_reasons.append('entity_not_mentioned')
            
            # 检查是否缺乏实质信号
            if substance_score < 0.2:
                quality_reasons.append('no_substance_signals')
        
        # 6. 综合判定
        is_low_value = page_type in LOW_VALUE_TYPES
        needs_resolution = page_type in NEEDS_RESOLUTION_TYPES
        
        # v2: 对权威域名放宽质量 gate
        domain = urlparse(url).netloc.lower()
        authoritative_domains = ['sec.gov', 'hkexnews.hk', 'reuters.com', 'bloomberg.com', 
                                 'ft.com', 'wsj.com', 'cnbc.com', 'yahoo.com', 'finance.yahoo.com']
        is_authoritative = any(ad in domain for ad in authoritative_domains)
        
        # 权威域名即使有些质量问题也放行
        if is_authoritative:
            quality_gate_passed = len(quality_reasons) <= 1  # 允许 1 个小问题
        else:
            quality_gate_passed = len(quality_reasons) == 0 and not is_low_value
        
        # 如果内容质量很差，即使类型正确也不过 gate
        if quality_reasons and page_type not in LOW_VALUE_TYPES:
            # 仅当类型不是明确的低价值类型时，才用 quality 来决定
            if 'text_too_short' in quality_reasons and 'policy_content_dominant' in quality_reasons:
                quality_gate_passed = False
        
        return PageClassification(
            page_type=page_type,
            confidence=type_confidence,
            is_low_value=is_low_value,
            needs_resolution=needs_resolution,
            quality_gate_passed=quality_gate_passed,
            quality_reasons=quality_reasons,
            substance_score=substance_score,
        )


class IRLandingResolver:
    """
    IR Landing Page Resolver
    
    当命中 investor_landing_page 时，从 HTML 中提取实质链接：
    - Press releases
    - Earnings releases
    - Filing pages
    - PDF attachments
    - Results presentations
    """
    
    # 需要找的链接类型及其 URL 模式
    RESOLUTION_PATTERNS: list[tuple[str, str]] = [
        ('press_release', r'press[-_]?release|news[-_]?release'),
        ('earnings_release', r'earnings|quarterly[-_]?results|results[-_]?presentation'),
        ('filing_page', r'sec[-_]?filing|filings|annual[-_]?report|10-[kK]|20-[fF]'),
        ('pdf_document', r'\.pdf'),
        ('financial_results', r'financial[-_]?results|financial[-_]?highlights'),
    ]
    
    def resolve(self, html: str, base_url: str) -> list[dict]:
        """
        从 IR landing page 的 HTML 中提取可继续抓取的链接
        
        Returns:
            list of {url, link_type, anchor_text}
        """
        from urllib.parse import urljoin
        
        links: list[dict] = []
        seen_urls: set[str] = set()
        
        # 提取所有 <a> 标签
        for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
            href = m.group(1).strip()
            anchor = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            
            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue
            
            full_url = urljoin(base_url, href)
            
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            
            # 检查链接类型
            link_text = (href + ' ' + anchor).lower()
            for link_type, pattern in self.RESOLUTION_PATTERNS:
                if re.search(pattern, link_text, re.I):
                    links.append({
                        'url': full_url,
                        'link_type': link_type,
                        'anchor_text': anchor[:200],
                    })
                    break
        
        return links


# ─── 全局实例 ──────────────────────────────────────

_classifier: PageClassifier | None = None
_resolver: IRLandingResolver | None = None


def get_classifier() -> PageClassifier:
    global _classifier
    if _classifier is None:
        _classifier = PageClassifier()
    return _classifier


def get_resolver() -> IRLandingResolver:
    global _resolver
    if _resolver is None:
        _resolver = IRLandingResolver()
    return _resolver


def classify_page(url: str, title: str, text: str, entity: str = '') -> PageClassification:
    """便捷函数"""
    return get_classifier().classify(url, title, text, entity)
