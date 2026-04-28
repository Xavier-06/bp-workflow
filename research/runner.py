"""
Research Runner - v3 迭代搜索
核心升级：
1. 多轮迭代搜索（最多 3 轮）
2. Gap 检测 → 自动补搜
3. Citation 追踪
4. 研究计划透明输出
5. SearXNG + DDG 双源
6. Yahoo Finance 估值补充
"""

from __future__ import annotations
from dataclasses import dataclass, field
from collections import defaultdict
import time, re, subprocess, os, json
from urllib.parse import urlparse

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.planner import ResearchPlan, ResearchPlanner
from search.adapters.searxng import SearXNGAdapter
from search.adapters.ddg import DDGAdapter
from search.models import Evidence, SearchHit
from content.fetcher import ContentFetcher, FetchedDoc
from routing.source_router import SourceRouter, get_router
from routing.source_gate import SourceGate, get_gate
from sources.entity_profile import get_entity_profile, EntitySourceProfile
from sources.url_fetch_path import URLFirstDirectFetcher, DirectFetchResult, get_direct_fetcher
from content.page_classifier import classify_page, PageClassification, LOW_VALUE_TYPES
from research.query_expander import QueryExpander, get_expander

ENTITY_ALIASES = {
    '英伟达': ['nvidia', '英伟达', '辉达'],
    '阿里巴巴': ['alibaba', '阿里巴巴', '阿里'],
    '腾讯': ['tencent', '腾讯', '腾讯控股'],
    '特斯拉': ['tesla', '特斯拉'],
    '苹果': ['apple', '苹果'],
    '微软': ['microsoft', '微软'],
    '谷歌': ['google', '谷歌', 'alphabet'],
    '亚马逊': ['amazon', '亚马逊'],
    'openai': ['openai'],
    'meta': ['meta', 'facebook'],
}

# ─── 研究维度定义（用于 gap 检测）─────────────────
RESEARCH_DIMENSIONS = {
    'company_research': [
        ('business_model', ['revenue', 'business', 'product', 'service', 'segment', '业务', '收入', '产品', 'operations', 'platform', 'ecosystem', '生态', '平台']),
        ('financials', ['earnings', 'profit', 'margin', 'revenue', 'income', 'eps', '利润', '营收', '业绩',
                        'financial', 'results', 'quarter', 'annual', 'fiscal', 'sales', 'cost', 'cash flow',
                        '财务', '净利', '毛利', '现金流', '年报', '季报', '业绩会', 'ebitda', 'guidance']),
        ('recent_events', ['news', 'announce', 'launch', 'release', 'update', '最新', '发布', '动态',
                           'recently', 'latest', 'new', 'just', '近期', '今年', '2025', '2026']),
        ('risks', ['risk', 'regulatory', 'competition', 'lawsuit', 'challenge', '机遇', '挑战', '政策', '合规',
                   '竞争对手', '市场份额', 'macro', '风险', '竞争', '监管',
                   'threat', 'concern', 'headwind', 'uncertainty', 'sanction', 'tariff', 'ban',
                   '不确定', '阻力', '制裁', '关税', '下行', '压力', '诉讼', 'antitrust']),
        ('management', ['ceo', 'cfo', 'executive', 'management', 'leadership', '创始人', '董事会',
                        '治理', '股权', '激励', 'founder', 'board', 'governance', '管理层', '高管',
                        'chairman', 'president', 'director', 'appoint', '任命', '离职', '接任']),
    ],
    'market_news': [
        ('breaking', ['break', 'urgent', 'just', 'happening', '突发', '快讯']),
        ('analysis', ['analysis', 'outlook', 'forecast', 'trend', '分析', '展望']),
        ('data', ['data', 'report', 'statistics', 'numbers', '数据', '报告']),
    ],
}

# Gap 检测阈值（从 2 降到 1 减少 false negative）
COVERAGE_THRESHOLD = 1



_searxng_cache: dict[str, tuple[bool, float]] = {}
_SEARXNG_CACHE_TTL = 120  # 2 分钟内不重复探测


def ensure_searxng_running() -> bool:
    """快速探测本地 SearXNG，带进程级缓存避免重复超时。

    ResearchRunner 每次 __init__ 都会调用此函数。
    如果 SearXNG 不可达，不缓存的话 N 次调用 × 15s/次 = 管线卡死。
    """
    import requests

    now = time.time()
    cached = _searxng_cache.get('result')
    if cached:
        val, ts = cached
        if now - ts < _SEARXNG_CACHE_TTL:
            return val

    candidate_urls = [
        'http://127.0.0.1:8888',
    ]

    def _session():
        s = requests.Session()
        s.trust_env = False
        return s

    def _healthy(base_url: str) -> bool:
        try:
            with _session() as s:
                r = s.get(f'{base_url}/healthz', timeout=2)
                return r.ok and r.text.strip() == 'OK'
        except Exception:
            return False

    # 1) 先直接探测，不做任何启动动作
    for base_url in candidate_urls:
        if _healthy(base_url):
            _searxng_cache['result'] = (True, now)
            return True

    manager_py = ROOT / 'scripts' / 'searxng_manager.py'
    local_start_sh = ROOT / 'scripts' / 'start_local_searxng.sh'

    # 2) 最多快速启动一次，不阻塞重试循环
    if manager_py.exists():
        try:
            subprocess.run(
                ['python3', str(manager_py), 'start'],
                capture_output=True,
                timeout=12,
                cwd=str(ROOT),
            )
        except Exception:
            pass
    elif local_start_sh.exists():
        try:
            subprocess.run(
                [str(local_start_sh), 'start'],
                capture_output=True,
                timeout=12,
                cwd=str(ROOT),
            )
        except Exception:
            pass

    # 3) 只短等一次再探测，避免卡住初始化
    time.sleep(0.8)
    for base_url in candidate_urls:
        if _healthy(base_url):
            _searxng_cache['result'] = (True, now)
            return True

    _searxng_cache['result'] = (False, now)
    return False


@dataclass
class SourcePathState:
    profile_hit: bool = False
    official_path_used: bool = False
    feed_path_used: bool = False
    search_fallback_used: bool = False
    browser_fallback_used: bool = False
    aggregator_fallback_used: bool = False
    direct_url_fetch_count: int = 0
    feed_hit_count: int = 0
    searxng_healthy: bool = False


@dataclass
class RunnerStats:
    search_time_ms: int = 0
    fetch_time_ms: int = 0
    fetch_count: int = 0
    fetch_success_count: int = 0
    searxng_request_delta: int = 0
    ddg_request_delta: int = 0
    official_evidence_count: int = 0
    filing_evidence_count: int = 0
    primary_source_count: int = 0
    aggregator_count: int = 0
    missing_publish_time_count: int = 0
    total_rounds: int = 0
    
    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class SubquestionStatus:
    question: str
    status: str  # unanswered | partially_answered | answered
    evidence_ids: list[str] = field(default_factory=list)
    confidence: str = 'low'


@dataclass
class GapAnalysis:
    """某一轮结束后的 gap 分析"""
    round_num: int
    dimensions_covered: list[str] = field(default_factory=list)
    dimensions_missing: list[str] = field(default_factory=list)
    unanswered_subquestions: list[str] = field(default_factory=list)
    suggested_queries: list[str] = field(default_factory=list)
    should_continue: bool = False
    reason: str = ''


@dataclass
class ResearchState:
    plan: ResearchPlan
    completed_subquestions: list[str] = field(default_factory=list)
    unanswered_subquestions: list[str] = field(default_factory=list)
    partially_answered_subquestions: list[str] = field(default_factory=list)
    evidence_by_subquestion: dict[str, list[Evidence]] = field(default_factory=lambda: defaultdict(list))
    subquestion_status: dict[str, SubquestionStatus] = field(default_factory=dict)
    all_evidence: list[Evidence] = field(default_factory=list)
    rounds_used: int = 0
    stop_reason: str | None = None
    runner_stats: RunnerStats = field(default_factory=RunnerStats)
    provider_used: str = 'searxng+ddg'
    source_families_seen: list[str] = field(default_factory=list)
    gap_reasons: list[str] = field(default_factory=list)
    secondary_only_flag: bool = False
    official_source_missing: bool = False
    source_path_state: SourcePathState = field(default_factory=SourcePathState)
    expanded_queries: dict = field(default_factory=dict)
    gap_analyses: list[GapAnalysis] = field(default_factory=list)
    valuation_data: dict = field(default_factory=dict)  # Phase 4: Yahoo Finance 估值数据
    # citation 追踪
    citation_map: dict[str, dict] = field(default_factory=dict)  # url -> {index, title, domain}
    used_queries: set[str] = field(default_factory=set)  # 已搜过的查询（去重用）



# ─── 垃圾页面标题（抓到这些直接丢弃）────────────
GARBAGE_TITLES = {
    'access denied', '403 forbidden', '404 not found',
    'just a moment', 'attention required', 'please wait',
    'sorry, you have been blocked', 'page not found',
    'error', 'captcha', 'bot detection',
    'are you a robot', 'security check',
}

# 域名黑名单：与投研完全无关的来源，搜到即丢弃
GARBAGE_DOMAINS = {
    'stackoverflow.com', 'github.com', 'npmjs.com', 'www.npmjs.com',
    'pypi.org', 'crates.io', 'rubygems.org', 'hub.docker.com',
    'gitlab.com', 'bitbucket.org',
    'design.google', 'fonts.google.com', 'dribbble.com', 'behance.net',
    'translate.google.com', 'maps.google.com', 'calendar.google.com',
    'twitter.com', 'x.com', 'facebook.com', 'instagram.com',
    'tiktok.com', 'pinterest.com',
}

def _is_garbage_evidence(ev, entity: str = '') -> bool:
    """检查 evidence 是否是垃圾页面或与实体无关"""
    # 域名黑名单检查
    url = getattr(ev, 'url', '') or ''
    if url:
        from urllib.parse import urlparse as _urlparse
        try:
            _host = (_urlparse(url).hostname or '').lower()
            _host_clean = _host.lstrip('www.')
            if _host in GARBAGE_DOMAINS or _host_clean in GARBAGE_DOMAINS:
                return True
        except Exception:
            pass
    title_lower = (ev.title or '').strip().lower()
    if title_lower in GARBAGE_TITLES:
        return True
    if any(g in title_lower for g in ['access denied', '403 forbidden', 'just a moment', 'captcha']):
        return True
    # 正文太短且标题可疑
    text = ev.full_text or ev.snippet or ''
    if len(text.strip()) < 50 and title_lower in ('', 'untitled'):
        return True
    # 实体相关性检查：官方源/信任源豁免，其余必须包含实体名
    if entity:
        # 官方源/信任媒体不做相关性过滤
        sf = getattr(ev, 'source_family', '') or ''
        if sf in ('official', 'official_newsroom', 'filings', 'trusted_media', 'primary_wire'):
            return False
        entity_lower = entity.lower()
        content = f"{ev.title or ''} {ev.snippet or ''}".lower()
        # 构建双语检查词组
        import sys as _sys
        _sys.path.insert(0, str(ROOT)) if str(ROOT) not in _sys.path else None
        try:
            from research.query_expander import get_expander
            _exp = get_expander()
            entity_en = _exp._to_english_name(entity).lower()
        except Exception:
            entity_en = entity_lower
        # 检查变体：中文名、英文全名、英文名前几个词
        en_words = entity_en.split()
        check_terms = [entity_lower, entity_en]
        # 加英文名前两个词的组合（如 "ping an"）
        if len(en_words) >= 2:
            check_terms.append(' '.join(en_words[:2]))
        has_entity = any(t in content for t in check_terms if len(t) >= 3)
        if not has_entity and len(content) > 100:
            return True
    return False

class ResearchRunner:
    """研究执行器 - v3 迭代搜索"""
    
    MAX_ROUNDS = 3
    
    def __init__(self, max_fetch_per_round: int = 8, fetch_timeout: int = 20, snippet_only: bool = False, max_rounds: int = 3, notify: bool = False):
        self.planner = ResearchPlanner()
        self.max_fetch_per_round = max_fetch_per_round
        self.fetch_timeout = fetch_timeout
        self.snippet_only = snippet_only
        self.content_fetcher = ContentFetcher(timeout=fetch_timeout) if not snippet_only else None
        self.direct_fetcher = get_direct_fetcher()
        self.source_gate = get_gate()
        self.max_rounds = min(max_rounds, self.MAX_ROUNDS)
        self.notify = notify
        
        self.searxng_healthy = ensure_searxng_running()
        self.adapter = SearXNGAdapter(['http://127.0.0.1:18080', 'http://127.0.0.1:8888']) if self.searxng_healthy else None
        self.expander = get_expander()
        self.ddg_adapter = DDGAdapter()
        # ⚠️ 2026-04-04: CN instance (18081) deprecated — use DDG for Chinese
        self.ddg_primary_for_chinese = True
    
    def run(self, task_type: str, query: str, **kwargs) -> ResearchState:
        plan = self.planner.plan(task_type, query, **kwargs)
        entity_profile = get_entity_profile(plan.entity)
        router = get_router(task_type)
        
        state = ResearchState(plan=plan, unanswered_subquestions=plan.subquestions.copy())
        state.source_path_state.profile_hit = entity_profile is not None
        state.source_path_state.searxng_healthy = self.searxng_healthy
        
        for sq in plan.subquestions:
            state.subquestion_status[sq] = SubquestionStatus(question=sq, status='unanswered')
        
        # ─── 输出研究计划 ───────────────────────────
        self._print_research_plan(plan, state)
        
        # ─── Round 0: URL-first 直抓 ─────────────────
        print(f"\n{'='*60}")
        print(f"  ROUND 0: URL-first Direct Fetch")
        print(f"{'='*60}")
        self._run_direct_fetch(state, entity_profile, task_type)
        
        # ─── Round 1-N: 迭代搜索 ─────────────────────
        for round_num in range(1, self.max_rounds + 1):
            self._update_subquestion_status(state)
            gap = self._analyze_gaps(state, round_num, task_type)
            state.gap_analyses.append(gap)
            
            if not gap.should_continue:
                print(f"\n  ✅ 搜索收敛 (Round {round_num}): {gap.reason}")
                state.stop_reason = gap.reason
                break
            
            print(f"\n{'='*60}")
            print(f"  ROUND {round_num}: Iterative Search")
            print(f"  Gap: {gap.dimensions_missing}")
            print(f"  Queries: {gap.suggested_queries[:3]}...")
            print(f"{'='*60}")
            
            self._run_search_round(state, router, entity_profile, gap.suggested_queries)
            state.rounds_used = round_num
        else:
            state.stop_reason = f'max_rounds_reached ({self.max_rounds})'
        
        # ─── 收尾 ────────────────────────────────────
        self._update_subquestion_status(state)
        gate_result = self.source_gate.check(task_type, state.all_evidence, [])
        state.official_source_missing = gate_result.official_source_missing
        state.secondary_only_flag = gate_result.secondary_only
        state.gap_reasons.extend(gate_result.gaps)
        self._update_source_stats(state)
        self._build_citation_map(state)
        
        # Phase 4: Yahoo Finance 估值补充
        if task_type == 'company_research':
            try:
                from tasks.valuation_enricher import enrich_with_yahoo
                state.valuation_data = enrich_with_yahoo(plan.entity)
                if state.valuation_data:
                    print(f"  Yahoo Finance: {state.valuation_data.get('ticker')} "
                          f"price={state.valuation_data.get('price')} "
                          f"PE={state.valuation_data.get('pe_ratio')}")
                else:
                    print("  Yahoo Finance: no ticker found")
            except Exception as e:
                print(f"  Yahoo Finance: error - {e}")
        
        self._print_summary(state)
        return state
    
    # ─── 研究计划输出 ──────────────────────────────
    
    def _print_research_plan(self, plan: ResearchPlan, state: ResearchState):
        print(f"\n{'='*60}")
        print(f"  📋 RESEARCH PLAN")
        print(f"{'='*60}")
        print(f"  Entity: {plan.entity}")
        print(f"  Market: {plan.market}")
        print(f"  Task: {plan.task_type}")
        print(f"  Max rounds: {self.max_rounds}")
        print(f"\n  Sub-questions:")
        for i, sq in enumerate(plan.subquestions, 1):
            print(f"    {i}. {sq}")
        
        # 展开查询
        expanded_queries: dict[str, list[str]] = {}
        for sq in plan.subquestions:
            expanded_queries[sq] = self.expander.expand(sq, plan.entity, plan.market).queries
        state.expanded_queries = expanded_queries
        total = sum(len(v) for v in expanded_queries.values())
        print(f"\n  Expanded to {total} search queries")

        # 飞书推送研究计划（仅 notify=True 时触发）
        if self.notify:
            try:
                import subprocess as _sp
                _lines = [
                    '📋 研究计划启动：' + plan.entity,
                    '任务类型：' + plan.task_type + ' | 市场：' + plan.market,
                    '最大轮数：' + str(self.max_rounds),
                    '',
                    '子问题：',
                ]
                for i, sq in enumerate(plan.subquestions, 1):
                    _lines.append(f'  {i}. {sq}')
                _lines.append('展开查询数：' + str(total))
                _msg = '\n'.join(_lines)
                # 2026-04-13: WorkBuddy 版 — 用龙少微信替代 `openclaw message send --channel feishu`
                try:
                    import sys as _sys
                    from pathlib import Path as _P
                    _sys.path.insert(0, str(_P(__file__).resolve().parent.parent / 'scripts'))
                    from longshao_notify import send_message as _send_wx
                    _send_wx(f"📋 {plan.entity} 研究计划\n\n{_msg}")
                except Exception:
                    pass
            except Exception:
                pass
    
    # ─── Round 0: 直抓 ────────────────────────────
    
    def _run_direct_fetch(self, state: ResearchState, entity_profile, task_type: str):
        if not entity_profile:
            print("  No entity profile, skipping direct fetch")
            return
        
        if task_type == 'company_research':
            direct_results = self.direct_fetcher.fetch_company_sources(state.plan.entity)
        else:
            direct_results = self.direct_fetcher.fetch_news_sources(state.plan.entity)
        
        state.source_path_state.official_path_used = len(direct_results) > 0
        state.source_path_state.direct_url_fetch_count = len(direct_results)
        state.source_path_state.feed_hit_count = sum(1 for r in direct_results if r.source_type == 'feed')
        
        added = 0
        for result in direct_results:
            if result.success and result.title:
                ev = self._direct_result_to_evidence(result)
                if _is_garbage_evidence(ev, entity=state.plan.entity):
                    ev.accepted = False
                    continue
                state.all_evidence.append(ev)
                if ev.source_family not in state.source_families_seen:
                    state.source_families_seen.append(ev.source_family)
                added += 1
        print(f"  Direct fetch: {len(direct_results)} attempted, {added} added")
    
    # ─── Gap 分析 ──────────────────────────────────
    
    def _analyze_gaps(self, state: ResearchState, round_num: int, task_type: str) -> GapAnalysis:
        """分析当前 evidence 覆盖了哪些维度，缺哪些"""
        gap = GapAnalysis(round_num=round_num)
        
        # 统计已有 evidence 的文本
        all_text = ''
        for ev in state.all_evidence:
            if ev.accepted:
                all_text += f' {ev.title} {ev.snippet or ""} {(ev.full_text or "")[:2000]}'
        all_text_lower = all_text.lower()
        
        # 检查各维度覆盖
        dimensions = RESEARCH_DIMENSIONS.get(task_type, RESEARCH_DIMENSIONS.get('company_research', []))
        for dim_name, keywords in dimensions:
            hits = sum(1 for kw in keywords if kw in all_text_lower)
            if hits >= COVERAGE_THRESHOLD:
                gap.dimensions_covered.append(dim_name)
            else:
                gap.dimensions_missing.append(dim_name)
        
        # 检查子问题覆盖
        for sq, status in state.subquestion_status.items():
            if status.status == 'unanswered':
                gap.unanswered_subquestions.append(sq)
        
        # 判断是否继续
        accepted_count = sum(1 for e in state.all_evidence if e.accepted)
        
        if not gap.dimensions_missing and not gap.unanswered_subquestions:
            # 官方源直抓后至少还要跑一轮搜索补充新闻/财务数据
            if accepted_count >= 8 or round_num > 1:
                gap.should_continue = False
                gap.reason = f'所有维度已覆盖，{accepted_count} 条证据'
                return gap
            # 否则继续搜索补充更多证据
            gap.dimensions_missing = ['recent_news', 'financials_detail']
        
        if accepted_count >= 15:
            gap.should_continue = False
            gap.reason = f'证据充足 ({accepted_count} 条)，不再补搜'
            return gap
        
        if round_num > self.max_rounds:
            gap.should_continue = False
            gap.reason = f'已达最大轮数 {self.max_rounds}'
            return gap
        
        # 生成补充查询
        gap.should_continue = True
        gap.reason = f'缺失维度: {gap.dimensions_missing}, 未答子问题: {len(gap.unanswered_subquestions)}'
        gap.suggested_queries = self._generate_gap_queries(state.plan.entity, state.plan.market, gap, state.used_queries)
        
        return gap
    
    def _generate_gap_queries(self, entity: str, market: str, gap: GapAnalysis, used_queries: set[str] | None = None) -> list[str]:
        """为缺失维度生成定向查询"""
        queries = []
        entity_en = self.expander._to_english_name(entity)
        
        dim_query_templates = {
            'business_model': [f'{entity_en} business model revenue segments', f'{entity_en} products services overview'],
            'financials': [f'{entity_en} earnings results 2024 2025', f'{entity_en} revenue profit margin quarterly',
                             f'{entity_en} annual revenue financial results', f'{entity_en} valuation funding financials'],
            'recent_events': [f'{entity_en} news 2026', f'{entity_en} latest announcement'],
            'risks': [f'{entity_en} risks challenges regulatory', f'{entity_en} competition threats',
                          f'{entity_en} antitrust lawsuit sanctions concerns', f'{entity_en} market headwinds uncertainty'],
            'management': [f'{entity_en} CEO management team leadership', f'{entity_en} executive changes'],
            'breaking': [f'{entity_en} breaking news today', f'{entity_en} just announced'],
            'analysis': [f'{entity_en} analysis outlook forecast', f'{entity_en} market trend'],
            'data': [f'{entity_en} data report statistics', f'{entity_en} market share numbers'],
        }
        
        for dim in gap.dimensions_missing:
            templates = dim_query_templates.get(dim, [f'{entity_en} {dim}'])
            queries.extend(templates[:2])
        
        # 对未答子问题也生成查询
        for sq in gap.unanswered_subquestions[:2]:
            expanded = self.expander.expand(sq, entity, market)
            queries.extend(expanded.queries[:2])
        
        # 去重：排除已搜过的查询
        used = used_queries or set()
        seen = set()
        deduped = []
        for q in queries:
            q_lower = q.strip().lower()
            if q_lower not in seen and q_lower not in used:
                seen.add(q_lower)
                deduped.append(q)
        
        # 如果全被去重了，生成变体查询
        if not deduped and gap.dimensions_missing:
            entity_en = self.expander._to_english_name(entity)
            for dim in gap.dimensions_missing[:3]:
                deduped.append(f'{entity_en} {dim} latest 2026')
                deduped.append(f'{entity_en} {dim} analysis report')
        
        return deduped[:8]
    
    # ─── 搜索轮 ───────────────────────────────────
    
    def _run_search_round(self, state: ResearchState, router: SourceRouter, entity_profile, queries: list[str] | None = None) -> dict:
        plan = state.plan
        
        if not queries:
            # 第一轮用 expander 的展开查询
            queries = []
            for sq_queries in state.expanded_queries.values():
                queries.extend(sq_queries)
            seen = set()
            deduped = []
            for q in queries:
                if q not in seen:
                    seen.add(q)
                    deduped.append(q)
            queries = deduped[:10]
        
        print(f"\n  Searching {len(queries)} queries...")
        for i, q in enumerate(queries[:5], 1):
            print(f"    {i}. {q[:60]}")
        
        all_hits: list[SearchHit] = []
        search_start = time.perf_counter()

        # 串行统一搜索 - 统一走 scripts.search_gateway，避免 research 层直接碰不稳定引擎实现
        from scripts.search_gateway import search as gateway_search

        def search_one(query: str) -> list:
            results = []
            try:
                rows = gateway_search(query, max_results=8, timeout=20)
                for row in rows:
                    url = row.get('url', '')
                    if not url:
                        continue
                    results.append(SearchHit(
                        title=row.get('title', ''),
                        url=url,
                        domain=urlparse(url).netloc.lower(),
                        engine=row.get('engine', 'gateway') or 'gateway',
                        source_type='aggregator',
                        market=plan.market,
                        ticker='',
                        snippet=row.get('content', '') or row.get('snippet', '') or '',
                        published_at=row.get('publishedDate', '') or '',
                        rank=max(1, 100 - len(results)),
                        raw_score=float(max(0, 100 - len(results))),
                    ))
                # 粗略统计：按返回源判断计数
                if any((r.get('source', '') or '').startswith('searxng:') for r in rows):
                    state.runner_stats.searxng_request_delta += 1
                if any((r.get('source', '') or '').startswith('ddg:') for r in rows) or any((r.get('source', '') or '') == 'ddg:adapter' for r in rows):
                    state.runner_stats.ddg_request_delta += 1
            except Exception as e:
                print(f"    Gateway search error ({query[:30]}): {str(e)[:60]}")
            return results

        for query in queries[:5]:
            try:
                all_hits.extend(search_one(query))
            except Exception as e:
                print(f"    Search error ({query[:30]}): {e}")

        
        # 记录已搜过的查询
        for q in queries[:8]:
            state.used_queries.add(q.lower())
        search_ms = int((time.perf_counter() - search_start) * 1000)
        state.runner_stats.search_time_ms += search_ms
        print(f"\n  Raw hits: {len(all_hits)} ({search_ms}ms)")
        
        # URL 去重
        seen_urls = set(e.url for e in state.all_evidence)
        unique_hits = []
        for hit in all_hits:
            if hit.url not in seen_urls:
                seen_urls.add(hit.url)
                unique_hits.append(hit)
        
        print(f"  After dedup: {len(unique_hits)} new URLs")
        
        # Fetch + classify + filter
        added_count = 0
        fetch_start = time.perf_counter()
        
        for hit in unique_hits[:self.max_fetch_per_round]:
            domain = hit.domain or ''
            source_info = router.classify_evidence_source(domain, hit.url)
            
            if entity_profile and entity_profile.is_official_domain(domain):
                source_info['is_official'] = True
                source_info['source_family'] = 'official'
            
            # Fetch 正文
            full_text = ''
            fetch_title = hit.title
            if self.content_fetcher and not self.snippet_only:
                try:
                    doc = self.content_fetcher.fetch(hit.url, snippet=hit.snippet)
                    if doc.fetch_status == 'ok' and doc.text:
                        full_text = doc.text
                        fetch_title = doc.title or hit.title
                        state.runner_stats.fetch_count += 1
                        state.runner_stats.fetch_success_count += 1
                        
                        page_cls = classify_page(
                            url=hit.url, title=fetch_title,
                            text=full_text, entity=state.plan.entity,
                        )
                        if page_cls.is_low_value:
                            continue
                    else:
                        state.runner_stats.fetch_count += 1
                except Exception:
                    state.runner_stats.fetch_count += 1
            
            ev = Evidence.from_hit(hit, source_info)
            if full_text:
                ev.full_text = full_text
                ev.snippet = full_text[:500]
            ev.title = fetch_title
            
            # accept 逻辑：官方源 / 可信媒体 / 有足够正文内容
            sf = source_info.get('source_family', 'other')
            if source_info.get('is_filing') or sf in ['filings', 'official', 'official_newsroom', 'trusted_media', 'primary_wire']:
                ev.accepted = True
                ev.confidence = 'high' if sf in ['official', 'filings'] else 'medium'
            elif full_text and len(full_text) > 500:
                # 有实质正文就接受
                ev.accepted = True
                ev.confidence = 'medium'
            elif (ev.snippet or '') and len(ev.snippet or '') >= 100:
                ev.accepted = True
                ev.confidence = 'low'
            
            # snippet_only 模式：有足够长的 snippet 就 accept
            if self.snippet_only and not ev.accepted:
                snippet_len = len(ev.snippet or '')
                if snippet_len >= 80:
                    ev.accepted = True
                    ev.confidence = 'medium'
                elif snippet_len >= 30:
                    ev.accepted = True
                    ev.confidence = 'low'
            
            if _is_garbage_evidence(ev, entity=state.plan.entity):
                continue
            state.all_evidence.append(ev)
            added_count += 1
            
            if ev.source_family not in state.source_families_seen:
                state.source_families_seen.append(ev.source_family)
        
        fetch_ms = int((time.perf_counter() - fetch_start) * 1000)
        state.runner_stats.fetch_time_ms += fetch_ms
        state.source_path_state.search_fallback_used = True
        print(f"  Added {added_count} evidence ({fetch_ms}ms fetch)")
        
        return {'hits': len(all_hits), 'unique': len(unique_hits), 'added': added_count}
    
    # ─── Citation 构建 ─────────────────────────────
    
    def _build_citation_map(self, state: ResearchState):
        """为所有 accepted evidence 建 citation 编号"""
        idx = 1
        for ev in state.all_evidence:
            if ev.accepted and ev.url not in state.citation_map and not _is_garbage_evidence(ev):
                state.citation_map[ev.url] = {
                    'index': idx,
                    'title': ev.title,
                    'domain': ev.domain,
                    'url': ev.url,
                    'published_at': ev.published_at or '',
                }
                idx += 1
    
    def get_citations_markdown(self, state: ResearchState) -> str:
        """输出 markdown 格式的来源列表"""
        if not state.citation_map:
            return ''
        lines = ['## Sources\n']
        for url, info in sorted(state.citation_map.items(), key=lambda x: x[1]['index']):
            idx = info['index']
            title = info['title'][:80]
            domain = info['domain']
            lines.append(f'{idx}. [{title}]({url}) — {domain}')
        return '\n'.join(lines)
    
    # ─── 辅助 ──────────────────────────────────────
    
    def _direct_result_to_evidence(self, result: DirectFetchResult) -> Evidence:
        page_cls = classify_page(url=result.url, title=result.title, text=result.text or '', entity='')
        confidence = 'high' if result.is_official else 'medium'
        # 官方源强制 accept，不被 page_classifier 否决
        if result.is_official:
            accepted = result.success
        elif page_cls.is_low_value:
            accepted = False
            confidence = 'low'
        else:
            accepted = result.success
        
        return Evidence(
            title=result.title, url=result.url, domain=result.domain,
            source_type=result.source_type,
            source_family='official' if result.is_official else 'other',
            is_official=result.is_official, is_filing=result.source_type == 'filing',
            is_primary=result.is_official, published_at=result.published_at or '',
            snippet=result.text[:500] if result.text else '',
            full_text=result.text, confidence=confidence,
            fetch_status='ok' if result.success else 'failed', accepted=accepted,
        )
    
    def _update_subquestion_status(self, state: ResearchState) -> None:
        plan = state.plan
        for sq in plan.subquestions:
            sq_evidence = [ev for ev in state.all_evidence if self._evidence_matches_question(ev, sq, plan.entity)]
            if sq_evidence:
                state.evidence_by_subquestion[sq] = sq_evidence
                official = [e for e in sq_evidence if e.is_official]
                sq_status = state.subquestion_status[sq]
                if official:
                    sq_status.status = 'answered'
                    sq_status.confidence = 'high'
                else:
                    sq_status.status = 'partially_answered'
                    sq_status.confidence = 'medium'
                sq_status.evidence_ids = [e.url for e in sq_evidence]
                if sq in state.unanswered_subquestions:
                    state.unanswered_subquestions.remove(sq)
                    if sq_status.status == 'answered':
                        state.completed_subquestions.append(sq)
                    else:
                        state.partially_answered_subquestions.append(sq)
    
    def _update_source_stats(self, state: ResearchState) -> None:
        stats = state.runner_stats
        for ev in state.all_evidence:
            if ev.is_official: stats.official_evidence_count += 1
            if ev.is_filing: stats.filing_evidence_count += 1
            if ev.is_primary: stats.primary_source_count += 1
            if ev.source_family == 'aggregator': stats.aggregator_count += 1
            if not ev.published_at: stats.missing_publish_time_count += 1
        stats.total_rounds = state.rounds_used
    
    def _evidence_matches_question(self, evidence: Evidence, question: str, entity: str) -> bool:
        evidence_text = f"{evidence.title} {evidence.snippet or ''}".lower()
        entity_lower = entity.lower()
        aliases = ENTITY_ALIASES.get(entity, [entity_lower])
        for alias in aliases:
            if alias.lower() in evidence_text:
                return True
        return entity_lower in evidence_text
    
    def _print_summary(self, state: ResearchState):
        accepted = [e for e in state.all_evidence if e.accepted]
        print(f"\n{'='*60}")
        print(f"  📊 RESEARCH SUMMARY")
        print(f"{'='*60}")
        print(f"  Entity: {state.plan.entity}")
        print(f"  Rounds: {state.rounds_used}")
        print(f"  Stop reason: {state.stop_reason}")
        print(f"  Total evidence: {len(state.all_evidence)}")
        print(f"  Accepted: {len(accepted)}")
        print(f"  Citations: {len(state.citation_map)}")
        print(f"  Sources: {state.source_families_seen}")
        
        if state.valuation_data:
            print(f"  Valuation: {state.valuation_data.get('ticker')} "
                  f"${state.valuation_data.get('price')} "
                  f"PE={state.valuation_data.get('pe_ratio')}")
        
        if state.gap_analyses:
            last_gap = state.gap_analyses[-1]
            print(f"  Covered: {last_gap.dimensions_covered}")
            print(f"  Missing: {last_gap.dimensions_missing}")
        
        print(f"\n  Sub-question status:")
        for sq, status in state.subquestion_status.items():
            icon = '✅' if status.status == 'answered' else '🟡' if status.status == 'partially_answered' else '❌'
            print(f"    {icon} [{status.confidence}] {sq[:50]}...")


def run_research(task_type: str, query: str, **kwargs) -> ResearchState:
    runner_keys = {'max_fetch_per_round', 'fetch_timeout', 'snippet_only', 'max_rounds'}
    runner_kwargs = {k: v for k, v in kwargs.items() if k in runner_keys}
    return ResearchRunner(**runner_kwargs).run(task_type, query, **kwargs)