#!/usr/bin/env python3
"""
IR 管线搜索噪音过滤器

解决管线搜索中"简称歧义"导致的噪音淹没问题。

用法：
    from scripts.ir_noise_filter import build_search_query, check_noise_ratio
    
    # 自动加排除词
    query = build_search_query("TK Group", "TK GROUP HLDG injection mold")
    # → "TK GROUP HLDG injection mold" (已过滤)
    
    # 检查结果噪音比率
    ratio, report = check_noise_ratio(results)
"""

# ============================================================
# 短名歧义映射 — 当公司简称是通用词时，自动追加排除词
# ============================================================

AMBIGUOUS_SHORT_NAMES = {
    # 格式: 歧义短名 → (排除词列表, 必须包含词列表)
    'tk': {
        'exclude': ['-TikTok', '-Tik Tok', '-tkinter', '-python tk', 'python tkinter'],
        'require': ['Group', 'HLDG', 'Holdings', 'mold', '注塑', '模具', '东江集团', '02283', '2283.HK'],
    },
    '东江': {
        'exclude': ['-河流', '-历史', '-镇', '-毛文龙', '-满清', '-辽东', '-增城', '-江西', '-珠江'],
        'require': ['集团', '控股', '模具', '注塑', '02283', '2283', 'TK Group', 'HLDG'],
    },
    'byd': {
        'exclude': ['-build your dreams', '-王传福'],  # 如果搜索 BYD 但其实是比亚迪
    },
    'mi': {
        'exclude': ['-Xiaomi', '-雷军', '-小米', '-miui'],  # 如果搜索 MI 但不是小米
    },
}

# ============================================================
# IR 管线专属：搜索结果噪音判断
# ============================================================

# 高噪音域（搜索结果中出现这些域名，大概率是无关内容）
HIGH_NOISE_DOMAINS = [
    # 通用平台（对 IR 无价值）
    'youtube.com',
    'play.google.com',
    'apps.apple.com',
    'stackoverflow.com',
    'github.com',  # 除非是科技公司
    'zhihu.com/question',  # 知乎问答（非专栏/文章）
    # Python/编程社区（对非科技公司是噪音）
]

# 中噪音域（需结合上下文判断）
MEDIUM_NOISE_DOMAINS = [
    'zhihu.com',
    'reddit.com',
    'quora.com',
]


def is_noise_high_noise_domain(url: str) -> bool:
    """判断 URL 是否属于高噪音域"""
    if not url:
        return True
    url_lower = url.lower()
    return any(d in url_lower for d in HIGH_NOISE_DOMAINS)


def build_search_query(entity: str, base_query: str, market: str = 'us') -> str:
    """
    构建搜索查询，自动处理歧义短名噪音。
    
    Args:
        entity: 标的名（中文/英文）
        base_query: 原始搜索词
        market: us/hk/cn
        
    Returns:
        过滤后的搜索词
    """
    # 对港股市场，自动追加排除词处理歧义短名
    # 检查实体名中是否有歧义词
    entity_lower = entity.lower()
    
    for short_name, config in AMBIGUOUS_SHORT_NAMES.items():
        if short_name in entity_lower or short_name.upper() in entity:
            # 找到歧义词，追加排除词
            exclude_words = config.get('exclude', [])
            if exclude_words:
                # 如果是 SearXNG（支持标准搜索引擎语法），直接加排除词
                return f"{base_query} {' '.join(exclude_words)}"
    
    # 非歧义短名，直接返回原始查询
    return base_query


def check_noise_ratio(results: list[dict], entity: str = '') -> tuple[float, dict]:
    """
    检查搜索结果的噪音比率。
    
    Args:
        results: 搜索结果列表 [{title, url, content, ...}]
        entity: 标的名（用于判断标题中是否含公司名）
        
    Returns:
        (noise_ratio, {total, noise_count, noise_items, high_noise_domains})
    """
    if not results:
        return (1.0, {
            'total': 0,
            'noise_count': 0,
            'noise_items': [],
            'high_noise_domains': [],
        })
    
    total = len(results)
    noise_items = []
    high_noise_domains_found = set()
    
    # 判断标准：标题或内容中不包含实体名（且域名是高噪音）
    entity_keywords = []
    if entity:
        # 提取中英文实体关键词
        for c in entity:
            if '\u4e00' <= c <= '\u9fff' or c.isalpha():
                entity_keywords.append(c.lower())
        
        # 也检查股票代码（如 02283, 2283.HK）
        import re
        stock_matches = re.findall(r'\d{4,6}\.?HK?', entity, re.IGNORECASE)
        entity_keywords.extend([m.lower() for m in stock_matches])
    
    for r in results:
        url = r.get('url', '').lower()
        title = r.get('title', '').lower()
        content = r.get('content', r.get('snippet', '')).lower()
        
        # 检查是否高噪音域名
        if any(d in url for d in HIGH_NOISE_DOMAINS):
            noise_items.append({
                'url': r.get('url', ''),
                'title': r.get('title', ''),
                'reason': 'high_noise_domain',
            })
            for d in HIGH_NOISE_DOMAINS:
                if d in url:
                    high_noise_domains_found.add(d)
            continue
        
        # 如果实体名不在标题/内容中，也可能是噪音
        if entity_keywords:
            found_keyword = False
            for kw in entity_keywords:
                if kw and (kw in title or kw in content):
                    found_keyword = True
                    break
            if not found_keyword and len(entity_keywords) > 1:
                noise_items.append({
                    'url': r.get('url', ''),
                    'title': r.get('title', ''),
                    'reason': 'no_entity_keyword',
                })
    
    noise_count = len(noise_items)
    ratio = noise_count / total if total > 0 else 1.0
    
    return (ratio, {
        'total': total,
        'noise_count': noise_count,
        'noise_items': noise_items[:5],  # 最多报告 5 条
        'high_noise_domains': list(high_noise_domains_found),
    })

# ============================================================
# 实体名称歧义映射 — 港股公司名与历史/地理/文化词重名
# ============================================================

AMBIGUOUS_ENTITY_NAMES = {
    '东江': {
        'hk_suffix': ' 02283 港股 注塑模具',
        'exclude': ['-毛文龙', '-袁崇焕', '-东江湖', '-东江镇', '-东江纵队', '-毛文龙', '-知乎'],
    },
    '长江': {
        'hk_suffix': ' 港股 股票',
        'exclude': ['-中国最长河流', '-旅游', '-三峡', '-李白'],
    },
    '黄河': {
        'hk_suffix': ' 港股 股票',
        'exclude': ['-中国第二长河', '-旅游', '-壶口瀑布'],
    },
    '天山': {
        'hk_suffix': ' 港股 股票',
        'exclude': ['-新疆', '-天池', '-雪山', '-旅游'],
    },
    '万达': {
        'hk_suffix': ' 港股 股票',  # 万达已退市，但作为示例
    },
}


def build_hk_disambiguated_query(entity: str, base_query: str, market: str) -> str:
    """
    对港股实体名做消歧处理。
    
    如果实体名在 AMBIGUOUS_ENTITY_NAMES 中有定义，
    自动追加股票代码 + '港股'后缀 + 排除词。
    
    Args:
        entity: 公司实体名（如"东江集团控股"）
        base_query: 原始搜索词
        market: us/hk/cn
        
    Returns:
        消歧后的搜索词
    """
    if market != 'hk':
        return base_query
    
    for amb_name, config in AMBIGUOUS_ENTITY_NAMES.items():
        # 检查实体名是否包含歧义词
        if amb_name in entity or entity in amb_name:
            # 匹配到歧义实体名，应用消歧
            hk_suffix = config.get('hk_suffix', ' 港股 股票')
            exclude_words = config.get('exclude', [])
            
            # 方案：基础查询 + 港股后缀 + 排除词
            disambiguated = f"{base_query}{hk_suffix}"
            if exclude_words:
                disambiguated = f"{disambiguated} {' '.join(exclude_words)}"
            return disambiguated
    
    return base_query
