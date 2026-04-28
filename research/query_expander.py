"""
Query Expander - 多角度查询生成器
对每个子问题生成 3-5 个变体，提升 SearXNG 召回覆盖
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ExpandedQuery:
    """展开后的查询"""
    original: str          # 原始子问题
    queries: list[str]     # 生成的查询变体
    strategy: str          # 策略标签
    entity: str
    market: str


class QueryExpander:
    """
    从子问题生成多角度搜索查询
    不需要任何 API，纯规则生成
    """

    # ─── 市场特定查询前缀 ────────────────────────────
    MARKET_PREFIXES = {
        'us':      ['site:sec.gov', 'site:businesswire.com', 'site:prnewswire.com', 'site:globenewswire.com'],
        'hk':      ['site:hkexnews.hk', 'site:hkex.com.hk', '港股', '联交所'],
        'cn':      ['site:sse.com.cn', 'site:szse.cn', 'A股', '上交所', '深交所'],
        'generic': [],
    }

    # ─── 时效性关键词 ─────────────────────────────────
    FRESHNESS_TERMS = {
        'earnings':   ['Q4 2024', 'FY2024', 'full year 2024', 'annual results 2024', '2024年报', '2024业绩'],
        'news':       ['2025', 'latest', 'recent', 'this week', 'this month'],
        'filing':     ['annual report 2024', '20-F', '10-K', 'proxy statement', '年度报告'],
        'guidance':   ['outlook', 'guidance', 'forecast', 'next quarter', '展望', '指引'],
        'management': ['CEO', 'CFO', 'management team', 'board of directors', 'leadership'],
    }

    # ─── 意图关键词 → 查询策略 ───────────────────────
    INTENT_PATTERNS: list[tuple[list[str], str]] = [
        (['revenue', 'profit', 'earnings', 'margin', 'income', '收入', '利润', '营收', '业绩'], 'earnings'),
        (['news', 'recent', 'latest', 'update', '最新', '近期', '新闻', '动态'], 'news'),
        (['filing', 'annual report', '10-K', '20-F', '年报', '财报', '披露'], 'filing'),
        (['guidance', 'outlook', 'forecast', '展望', '预测', '指引', '目标'], 'guidance'),
        (['CEO', 'CFO', 'management', 'executive', '管理层', '高管', '创始人'], 'management'),
        (['risk', 'regulatory', 'lawsuit', 'competition', '风险', '监管', '竞争', '诉讼'], 'risk'),
    ]

    def expand(self, subquestion: str, entity: str, market: str = 'generic') -> ExpandedQuery:
        """
        对一个子问题生成多角度查询
        返回 3-5 个查询变体
        """
        strategy = self._detect_intent(subquestion)
        queries = []

        entity_en = self._to_english_name(entity)
        entity_cn = self._to_chinese_name(entity)

        # 1. 直接查询（原始子问题清洗后）
        direct = self._clean_subquestion(subquestion, entity)
        if direct:
            queries.append(direct)

        # 2. 英文实体 + 策略关键词
        for term in self.FRESHNESS_TERMS.get(strategy, self.FRESHNESS_TERMS['news'])[:2]:
            q = f"{entity_en} {term}"
            if q not in queries:
                queries.append(q)

        # 3. 官方源定向查询
        official_query = self._build_official_query(entity_en, strategy, market)
        if official_query and official_query not in queries:
            queries.append(official_query)

        # 4. 中文查询（如果是港股/A股）
        if market in ('hk', 'cn') and entity_cn:
            cn_q = f"{entity_cn} {self._cn_strategy_term(strategy)}"
            if cn_q not in queries:
                queries.append(cn_q)

        # 5. 媒体覆盖查询
        media_q = self._build_media_query(entity_en, strategy)
        if media_q and media_q not in queries:
            queries.append(media_q)

        return ExpandedQuery(
            original=subquestion,
            queries=queries[:5],  # 最多5个
            strategy=strategy,
            entity=entity,
            market=market,
        )

    def expand_all(self, subquestions: list[str], entity: str, market: str = 'generic') -> list[str]:
        """
        对所有子问题展开，去重后返回查询列表
        典型输入4个子问题 → 输出15-20个查询
        """
        all_queries: list[str] = []
        seen: set[str] = set()

        for sq in subquestions:
            expanded = self.expand(sq, entity, market)
            for q in expanded.queries:
                q_norm = q.strip().lower()
                if q_norm not in seen and len(q.strip()) > 3:
                    seen.add(q_norm)
                    all_queries.append(q)

        return all_queries

    # ─── 内部工具 ─────────────────────────────────────

    def _detect_intent(self, text: str) -> str:
        text_lower = text.lower()
        for keywords, strategy in self.INTENT_PATTERNS:
            if any(kw in text_lower for kw in keywords):
                return strategy
        return 'news'

    def _clean_subquestion(self, sq: str, entity: str) -> str:
        """把子问题转成可搜索的查询短语"""
        # 移除问号和疑问词
        sq = re.sub(r'[?？]', '', sq)
        sq = re.sub(r'^(what|how|why|when|where|who|is|are|does|did|can|的|了解|说明|分析|什么|如何|为什么|请问)', '', sq, flags=re.IGNORECASE).strip()
        
        # 提取核心关键词：去掉实体名后保留意图关键词
        entity_en = self._to_english_name(entity)
        # 从子问题中移除实体名（避免重复）
        for name in [entity, entity_en]:
            if name:
                sq = sq.replace(name, '').strip()
        # 去掉中文停用词
        for w in ['是什么公司', '主要做什么', '最近', '哪些', '关于', '还有', '需要进一步', '核实']:
            sq = sq.replace(w, ' ')
        sq = re.sub(r'\s+', ' ', sq).strip()
        
        # 拼回实体 + 核心关键词
        if sq:
            result = f"{entity_en or entity} {sq}"
        else:
            result = entity_en or entity
        # 清理多余标点和空白
        result = re.sub(r'[^a-zA-Z0-9 一-鿿㐀-䶿.]+', ' ', result)
        result = re.sub(r'\s+', ' ', result).strip()
        return result[:80]

    def _build_official_query(self, entity_en: str, strategy: str, market: str) -> str:
        is_private = market not in ('hk', 'us', 'cn', 'generic')
        if strategy == 'filing':
            if is_private:
                return f'{entity_en} funding revenue valuation financials 2024 2025'
            if market == 'hk':
                return f'{entity_en} annual report site:hkexnews.hk'
            elif market == 'us':
                return f'{entity_en} 10-K site:sec.gov'
        elif strategy == 'earnings':
            if is_private:
                return f'{entity_en} revenue growth funding round business model'
            return f'{entity_en} earnings results press release'
        elif strategy == 'news':
            return f'{entity_en} news 2025'
        elif strategy == 'guidance':
            if is_private:
                return f'{entity_en} expansion plans product roadmap 2025 2026'
            return f'{entity_en} outlook guidance 2025'
        return f'{entity_en} investor relations'

    def _build_media_query(self, entity_en: str, strategy: str) -> str:
        media_sites = 'site:reuters.com OR site:bloomberg.com OR site:ft.com'
        if strategy in ('earnings', 'guidance'):
            return f"{entity_en} results {media_sites}"
        elif strategy == 'risk':
            return f"{entity_en} regulatory risk {media_sites}"
        return f"{entity_en} {media_sites}"

    def _cn_strategy_term(self, strategy: str) -> str:
        mapping = {
            'earnings': '业绩 财报 2024',
            'news': '最新消息 2025',
            'filing': '年度报告 2024',
            'guidance': '业绩展望 指引',
            'management': '管理层 高管',
            'risk': '风险 监管',
        }
        return mapping.get(strategy, '最新动态')

    # ─── 实体名称映射 ──────────────────────────────────
    # 简单的中英文映射，不需要 API

    EN_NAMES = {
        '腾讯': 'Tencent', '阿里巴巴': 'Alibaba', '英伟达': 'Nvidia',
        '特斯拉': 'Tesla', '苹果': 'Apple', '微软': 'Microsoft',
        '谷歌': 'Google', '亚马逊': 'Amazon', '百度': 'Baidu',
        '京东': 'JD.com', '美团': 'Meituan', '字节跳动': 'ByteDance',
        '小米': 'Xiaomi', '华为': 'Huawei', '思摩尔': 'Smoore',
        '思摩尔国际': 'Smoore International', '平安好医生': 'Ping An Good Doctor',
        '中国平安': 'Ping An', '比亚迪': 'BYD', '宁德时代': 'CATL',
        '小鹏': 'Xpeng', '蔚来': 'Nio', '理想': 'Li Auto',
        '快手': 'Kuaishou', '拼多多': 'Pinduoduo', '网易': 'NetEase',
        '携程': 'Trip.com', '海底捞': 'Haidilao', '泡泡玛特': 'Pop Mart',
        '商汤': 'SenseTime', '旷视': 'Megvii', '寒武纪': 'Cambricon',
    }

    CN_NAMES = {v: k for k, v in EN_NAMES.items()}

    def _to_english_name(self, entity: str) -> str:
        return self.EN_NAMES.get(entity, entity)

    def _to_chinese_name(self, entity: str) -> str:
        return self.CN_NAMES.get(entity, '')


# ─── 单例 ─────────────────────────────────────────────
_expander: QueryExpander | None = None


def get_expander() -> QueryExpander:
    global _expander
    if _expander is None:
        _expander = QueryExpander()
    return _expander


def expand_queries(subquestions: list[str], entity: str, market: str = 'generic') -> list[str]:
    """便捷函数：子问题列表 → 展开查询列表"""
    return get_expander().expand_all(subquestions, entity, market)
