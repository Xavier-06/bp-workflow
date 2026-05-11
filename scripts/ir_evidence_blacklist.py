"""
ir_evidence_blacklist.py — 共享的域名黑名单、低信号源分级和 URL 模式黑名单

被 fill_ir_data_packet.py 和 filter_ir_evidence.py 共同引用。
修改一处即可同时生效。

v2 (2026-03-31): 新增来源可靠性分级（TIER_1/2/3/BLACKLIST）
"""
from __future__ import annotations
import re
from urllib.parse import urlparse

# ─── 域名黑名单（完全无关的来源，直接丢弃）────────
DOMAIN_BLACKLIST = {
    # 编程/技术站
    'stackoverflow.com',
    'github.com',
    'npmjs.com',
    'www.npmjs.com',
    'pypi.org',
    'crates.io',
    'rubygems.org',
    'hub.docker.com',
    'gitlab.com',
    'bitbucket.org',
    # 设计/字体
    'design.google',
    'fonts.google.com',
    'dribbble.com',
    'behance.net',
    # 通用工具
    'translate.google.com',
    'maps.google.com',
    'calendar.google.com',
    # 社交媒体（低信号）
    'twitter.com',
    'x.com',
    'facebook.com',
    'instagram.com',
    'tiktok.com',
    'reddit.com',
    # 其他噪音源
    'pinterest.com',
    'quora.com',
    'youtube.com',
    # 聚合/搬运站（不是原始来源）
    'sohu.com',
    'ifeng.com',
    'thepaper.cn',  # 澎湃可以有但需要核实
}

# ─── 来源可靠性分级 ────────────────────────────

# TIER_1: 权威一手来源（年报/交易所/央行/监管机构）
# 用于核心财务数据，可直接引用
TIER_1_DOMAINS = {
    # 交易所/监管
    'hkexnews.hk', 'www1.hkexnews.hk',
    'sec.gov', 'www.sec.gov', 'edgar.sec.gov',
    'csrc.gov.cn',
    'sse.com.cn', 'szse.cn',
    # 央行/政府统计
    'federalreserve.gov', 'bls.gov', 'stats.gov.cn',
    # 公司 IR 页面（需按域名匹配）
    # 通常通过 URL 路径 /investor/ 或 /ir/ 判断
}

# TIER_2: 权威二手来源（主流财经媒体/头部研究机构）
# 可用于补充论据和分析师观点，核心财务数据需交叉验证
TIER_2_DOMAINS = {
    # 国际主流财经媒体
    'reuters.com', 'bloomberg.com', 'ft.com',
    'wsj.com', 'cnbc.com', 'barrons.com',
    'economist.com', 'nikkei.com',
    # 中文主流财经媒体
    'caixin.com', 'yicai.com', '21jingji.com',
    'cls.cn', 'nbd.com.cn',
    # 港股/中概专业
    'aastocks.com', 'etnet.com.hk',
    'hkej.com', 'scmp.com',
    # 行情数据
    'finance.yahoo.com', 'tradingview.com',
    'tipranks.com', 'stockopedia.com',
    # 研究机构
    'mckinsey.com', 'bcg.com', 'bain.com',
    # 行业数据
    'idc.com', 'gartner.com', 'statista.com',
}

# TIER_3: 低可靠性来源（行业自媒体/论坛/不明来源）
# 核心数据不可引用，仅可用于辅助判断/趋势感知
TIER_3_DOMAINS = {
    'zhihu.com',
    'xueqiu.com',  # 雪球——投资者讨论，非权威来源
    'eastmoney.com',  # 东方财富——用户讨论区可靠性低
    'gelonghui.com',
    'wallstreetcn.com',
    'seekingalpha.com',
    'motleyfool.com',
    'investopedia.com',
    # 行业垂直但非权威
    'humanoids.daily',  # 非主流来源
    'humanoidportsnetwork.com',
}

# URL 模式黑名单（匹配 URL 路径的，直接丢弃）
URL_PATTERN_BLACKLIST = [
    r'/search\?',
    r'/404',
    r'error\.html',
    r'captcha',
    r'bot-detection',
    r'login\?',
    r'signup\?',
    r'register\?',
]


def _normalize_domain(url: str) -> str:
    """提取并规范化域名"""
    try:
        parsed = urlparse(url)
        domain = (parsed.hostname or '').lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except Exception:
        return ''


def is_blacklisted_domain(url: str) -> bool:
    """检查 URL 的域名是否在黑名单中"""
    domain = _normalize_domain(url)
    full_domain = (urlparse(url).hostname or '').lower()
    return domain in DOMAIN_BLACKLIST or full_domain in DOMAIN_BLACKLIST


def is_blacklisted_url(url: str) -> bool:
    """检查 URL 路径是否匹配黑名单模式"""
    for pat in URL_PATTERN_BLACKLIST:
        if re.search(pat, url, re.IGNORECASE):
            return True
    return False


def is_blacklisted(url: str) -> bool:
    """综合检查：域名或 URL 模��是否在黑名单中"""
    return is_blacklisted_domain(url) or is_blacklisted_url(url)


def get_source_tier(url: str) -> int:
    """
    返回来源可靠性等级：
    1 = TIER_1（权威一手来源）
    2 = TIER_2（权威二手来源）
    3 = TIER_3（低可靠性来源）
    0 = BLACKLIST（黑名单）
    9 = UNKNOWN（未分类）

    用法：
        tier = get_source_tier("https://www.reuters.com/...")
        if tier <= 2:
            # 可用于核心论据
        elif tier == 3:
            # 仅辅助参考
    """
    if is_blacklisted(url):
        return 0

    domain = _normalize_domain(url)
    full_domain = (urlparse(url).hostname or '').lower()

    # 检查是否是公司 IR 页面（通过路径判断）
    path = urlparse(url).path.lower()
    if any(seg in path for seg in ['/investor', '/ir/', '/annual-report', '/financial']):
        return 1  # 公司 IR 页面视为 TIER_1

    # 检查各级域名
    for d in [domain, full_domain]:
        if d in TIER_1_DOMAINS:
            return 1
        if d in TIER_2_DOMAINS:
            return 2
        if d in TIER_3_DOMAINS:
            return 3

    return 9  # 未分类


def get_tier_label(tier: int) -> str:
    """返回可读的层级标签"""
    return {
        0: '⛔ BLACKLIST',
        1: '🟢 TIER_1 (权威一手)',
        2: '🟡 TIER_2 (权威二手)',
        3: '🟠 TIER_3 (低可靠性)',
        9: '⚪ UNKNOWN (未分类)',
    }.get(tier, '⚪ UNKNOWN')


def audit_sources(urls: list[str]) -> dict:
    """
    批量审计来源列表，返回统计和详情。
    用于 source-audit 步骤。
    """
    results = []
    tier_counts = {0: 0, 1: 0, 2: 0, 3: 0, 9: 0}

    for url in urls:
        tier = get_source_tier(url)
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        results.append({
            'url': url,
            'domain': _normalize_domain(url),
            'tier': tier,
            'tier_label': get_tier_label(tier),
        })

    return {
        'total': len(urls),
        'tier_counts': tier_counts,
        'tier_1_pct': tier_counts[1] / max(len(urls), 1) * 100,
        'blacklisted_count': tier_counts[0],
        'results': results,
    }
