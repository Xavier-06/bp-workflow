"""
Search Gateway - WorkBuddy IR Pipeline 版本
搜索提供商: SearXNG (可选) → Yahoo Finance Skill → DDG (免密钥)
Tavily 已永久移除，无需 API 密钥
"""

from __future__ import annotations
import logging
import os

from collections import Counter
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from functools import lru_cache
import json
import re
import sys
import time
from urllib.parse import urlparse, urlunparse
from pathlib import Path

# WorkBuddy 版: SearXNG + Yahoo + DDG，无需 Tavily
from search.adapters import SearXNGAdapter, DDGAdapter, YahooAdapter
from search.config import ROOT, domain_lists, load_env_file, query_plans, searxng_urls
from search.fetch import fetch_hit
from search.models import Evidence, ProviderResult, QueryPlan, SearchHit

logger = logging.getLogger(__name__)

# WorkBuddy 版白名单
PHASE1_PROVIDER_WHITELIST = {'searxng', 'ddg', 'yahoo'}


def _load_market_news_rules() -> dict:
    """加载 market_news 专用规则配置"""
    rules_path = ROOT / 'config' / 'search' / 'market_news_rules.json'
    if rules_path.exists():
        return json.loads(rules_path.read_text(encoding='utf-8'))
    return {}


@lru_cache(maxsize=1)
def market_news_rules() -> dict:
    return _load_market_news_rules()


class SearchGateway:
    """搜索网关 - WorkBuddy IR Pipeline 版本
    
    提供商优先级: SearXNG(可选) → Yahoo Finance Skill → DDG
    无需任何 API 密钥，所有搜索免密钥。
    Tavily 已永久移除。
    SearXNG 自动启动：首次使用时自动检测并拉起本地实例。
    """
    
    NEWS_ENGINES = 'bing news'
    _searxng_auto_started = False

    def __init__(self):
        load_env_file()
        
        # 注册搜索适配器
        self.adapters = {}
        
        # 1. SearXNG (可选，本地自建搜索，自动启动)
        self._ensure_searxng_running()
        self.adapters['searxng'] = SearXNGAdapter(searxng_urls())
        
        # 2. Yahoo Finance Skill (免密钥，金融查询首选)
        self.adapters['yahoo'] = YahooAdapter()
        
        # 3. DDG (免密钥，通用搜索兜底)
        self.adapters['ddg'] = DDGAdapter()
        
        # Tavily 已永久移除 - 忽略环境变量
        _ = os.environ.get('TAVILY_API_KEY', '')
        
        self.metrics_path = ROOT / 'data' / 'search_gateway' / 'metrics.json'
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        self.last_run: dict = {}

    def get_registered_providers(self) -> list[str]:
        """返回已注册的 provider 列表"""
        return list(self.adapters.keys())
    
    @classmethod
    def _ensure_searxng_running(cls) -> None:
        """自动检测并启动 SearXNG 本地实例（仅一次）"""
        if cls._searxng_auto_started:
            return
        cls._searxng_auto_started = True
        try:
            # 动态导入避免循环依赖
            import importlib
            scripts_dir = str(Path(__file__).resolve().parent.parent / 'scripts')
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            mgr = importlib.import_module('searxng_manager')
            ok = mgr.auto_start()
            if ok:
                logger.info('SearXNG auto-start: OK')
            else:
                logger.warning('SearXNG auto-start: FAILED (will use DDG fallback)')
        except Exception as exc:
            logger.warning('SearXNG auto-start error: %s (will use DDG fallback)', exc)
    
    def is_phase1_compliant(self) -> bool:
        """检查是否符合 Phase 1 规范"""
        return set(self.adapters.keys()).issubset(PHASE1_PROVIDER_WHITELIST)

    def plan_for(self, task_type: str) -> QueryPlan:
        plans = query_plans()
        return QueryPlan.from_dict(task_type, plans[task_type])

    def search(self, task_type: str, query: str, market: str | None = None, ticker: str | None = None, company: str | None = None, freshness_hours: int | None = None, max_results: int = 10, need_full_text: bool = True) -> list[Evidence]:
        plan = self.plan_for(task_type)
        freshness_hours = plan.freshness_hours if freshness_hours is None else freshness_hours
        max_results = min(max_results, plan.max_results)
        need_full_text = need_full_text if need_full_text is not None else plan.need_full_text

        if task_type == 'market_news':
            return self._search_market_news(plan, query=query, market=market, ticker=ticker, company=company, freshness_hours=freshness_hours, max_results=max_results)

        rendered_query = self._render_query(plan, query=query, market=market, ticker=ticker, company=company)
        hits, provider_results = self._run_provider_queries(
            query_texts=[rendered_query],
            market=market or 'generic',
            ticker=ticker or '',
            max_results=max_results,
            freshness_hours=freshness_hours,
            allow_fallback=plan.allow_fallback,
        )
        evidence, drop_counts = self._generic_hits_to_evidence(
            hits[:max_results],
            market=market or 'generic',
            ticker=ticker or '',
            freshness_hours=freshness_hours,
            need_full_text=need_full_text,
        )
        self._record_observation(
            task_type=task_type,
            query=rendered_query,
            provider_results=provider_results,
            query_result_count=len(hits[:max_results]),
            kept_count=len(evidence),
            drop_counts=drop_counts,
        )
        return evidence

    def _search_market_news(self, plan: QueryPlan, *, query: str, market: str | None, ticker: str | None, company: str | None, freshness_hours: int | None, max_results: int) -> list[Evidence]:
        query_texts = self._render_market_news_queries(query=query, company=company)
        provider_results: list[ProviderResult] = []
        all_hits: list[SearchHit] = []
        debug_rows: list[dict] = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        kept: list[Evidence] = []
        total_drop_counts: Counter[str] = Counter()

        for query_text in query_texts:
            hits, provider_batch = self._run_provider_queries(
                query_texts=[query_text],
                market=market or 'generic',
                ticker=ticker or '',
                max_results=max_results,
                freshness_hours=freshness_hours,
                allow_fallback=plan.allow_fallback,
                engines=self.NEWS_ENGINES,
            )
            provider_results.extend(provider_batch)
            all_hits.extend(hits)
            prefiltered, prefilter_blocked_count, top_domains = self._prefilter_news_hits(hits)
            fetched_count = 0
            dated_count = 0
            undated_count = 0
            duplicate_count = 0
            kept_count = 0
            query_drop_counts: Counter[str] = Counter()

            for hit in prefiltered:
                ev = fetch_hit(hit)
                fetched_count += 1
                if ev.published_at:
                    dated_count += 1
                else:
                    undated_count += 1
                if self._news_evidence_gate(ev, freshness_hours=freshness_hours, seen_urls=seen_urls, seen_titles=seen_titles):
                    kept.append(ev)
                    kept_count += 1
                else:
                    if 'duplicate_url' in ev.drop_reasons or 'duplicate_title' in ev.drop_reasons or 'duplicate_similar_title' in ev.drop_reasons:
                        duplicate_count += 1
                    for reason in ev.drop_reasons:
                        query_drop_counts[reason] += 1
                        total_drop_counts[reason] += 1

            debug_rows.append({
                'query_text': query_text,
                'raw_result_count': len(hits),
                'prefilter_blocked_count': prefilter_blocked_count,
                'fetched_count': fetched_count,
                'dated_count': dated_count,
                'undated_count': undated_count,
                'duplicate_count': duplicate_count,
                'kept_count': kept_count,
                'top_domains': top_domains,
                'top_drop_reasons': query_drop_counts.most_common(5),
            })

        self._record_observation(
            task_type='market_news',
            query=' | '.join(query_texts),
            provider_results=provider_results,
            query_result_count=len(all_hits),
            kept_count=len(kept),
            drop_counts=dict(total_drop_counts),
            extra={'news_debug_matrix': debug_rows},
        )
        return kept

    def _run_provider_queries(self, *, query_texts: list[str], market: str, ticker: str, max_results: int, freshness_hours: int | None, allow_fallback: bool, engines: str | None = None) -> tuple[list[SearchHit], list[ProviderResult]]:
        hits: list[SearchHit] = []
        provider_results: list[ProviderResult] = []
        
        # Smart routing: financial queries try Yahoo first
        is_financial = bool(ticker) or self._looks_like_ticker(query_texts[0] if query_texts else '')
        
        # Provider order based on query type
        if is_financial:
            # Financial queries: Yahoo → SearXNG → DDG
            provider_order = ['yahoo', 'searxng', 'ddg']
        else:
            # General queries: SearXNG → DDG → Yahoo (Yahoo only for finance)
            provider_order = ['searxng', 'ddg', 'yahoo']
        
        for query_text in query_texts:
            for provider_name in provider_order:
                adapter = self.adapters.get(provider_name)
                if not adapter:
                    continue
                
                # Phase 1 保护：只允许白名单中的 provider
                if provider_name not in PHASE1_PROVIDER_WHITELIST:
                    raise RuntimeError(f"Phase 1 violation: provider '{provider_name}' is not allowed. Only {PHASE1_PROVIDER_WHITELIST} are permitted.")
                
                started = time.perf_counter()
                search_kwargs = {
                    'market': market,
                    'ticker': ticker,
                    'max_results': max_results,
                    'freshness_hours': freshness_hours,
                    'allow_fallback': allow_fallback,
                }
                if engines and provider_name == 'searxng':
                    search_kwargs['engines'] = engines
                
                provider_hits = adapter.search(query_text, **search_kwargs)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                provider_results.append(ProviderResult(
                    provider=provider_name,
                    ok=bool(provider_hits),
                    elapsed_ms=elapsed_ms,
                    hits=provider_hits,
                    error=getattr(adapter, 'last_failure', None),
                    result_count=len(provider_hits),
                    healthcheck_ok=getattr(adapter, 'last_healthcheck_ok', None),
                    fallback_used=bool(getattr(adapter, 'last_used_fallback', False)),
                ))
                hits.extend(provider_hits)
                if provider_hits:
                    break
        return hits, provider_results

    @staticmethod
    def _looks_like_ticker(query: str) -> bool:
        """Heuristic: does the query look like a stock ticker or company name?"""
        import re
        q = query.strip()
        if re.match(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?$', q):
            return True
        if re.match(r'^\d{6}$', q):
            return True
        finance_kw = {'stock', 'share', '股价', '股票', '行情', '市值', '财报', 'earnings', 'revenue', 'price target', 'PE', '估值'}
        q_lower = q.lower()
        return any(kw in q_lower for kw in finance_kw)

    def _render_query(self, plan: QueryPlan, *, query: str, market: str | None, ticker: str | None, company: str | None) -> str:
        template = plan.query or '{query}'
        company_value = company or query
        rendered = template.format(query=query or '', market=market or '', ticker=ticker or '', company=company_value).strip()
        return rendered or query

    def _render_market_news_queries(self, *, query: str, company: str | None) -> list[str]:
        base = (company or query).strip()
        out = [
            f'{base}',
            f'{base} 最新消息',
            f'{base} 发布 宣布',
        ]
        if re.search(r'[A-Za-z]', base):
            out.append(f'{base}')
        deduped = []
        seen = set()
        for item in out:
            key = item.strip().lower()
            if key and key not in seen:
                deduped.append(item)
                seen.add(key)
        return deduped[:3]

    def _prefilter_news_hits(self, hits: list[SearchHit]) -> tuple[list[SearchHit], int, list[str]]:
        rules = market_news_rules()
        cfg = domain_lists()
        
        blocking = rules.get('blocking', {})
        blocked_domains = blocking.get('blocked_domains', cfg.get('news_blocked_domains', []))
        blocked_url_patterns = blocking.get('blocked_url_patterns', cfg.get('news_blocked_url_patterns', []))
        blocked_title_patterns = blocking.get('blocked_title_patterns', cfg.get('news_blocked_title_patterns', []))
        
        domain_counter: Counter[str] = Counter()
        kept: list[SearchHit] = []
        blocked_count = 0
        for hit in hits:
            domain_counter[hit.domain] += 1
            if self._is_news_candidate(hit, blocked_domains, blocked_url_patterns, blocked_title_patterns):
                kept.append(hit)
            else:
                blocked_count += 1
        return kept, blocked_count, [d for d, _ in domain_counter.most_common(5)]

    def _is_news_candidate(self, hit: SearchHit, blocked_domains: list[str], blocked_url_patterns: list[str], blocked_title_patterns: list[str]) -> bool:
        domain = (hit.domain or '').lower()
        url = (hit.url or '').lower()
        title = (hit.title or '').lower()
        if any(blocked == domain or blocked in domain for blocked in blocked_domains):
            return False
        if any(pat.lower() in url for pat in blocked_url_patterns):
            return False
        if any(pat.lower() in title for pat in blocked_title_patterns):
            return False
        if len((hit.title or '').strip()) < 8:
            return False
        return True

    def _looks_like_detail_url(self, url: str) -> bool:
        parsed = urlparse(url)
        path = parsed.path.lower()
        if path in {'', '/'}:
            return False
        if re.search(r'/\d{4}/\d{2}/\d{2}/', path):
            return True
        if re.search(r'/doc-|/article/|/rain/a/|newsdetail_forward_|/art', path):
            return True
        if path.count('/') >= 2 and not path.endswith('/'):
            return True
        return False

    def _generic_hits_to_evidence(self, hits: list[SearchHit], *, market: str, ticker: str, freshness_hours: int | None, need_full_text: bool) -> tuple[list[Evidence], dict[str, int]]:
        seen_url: set[str] = set()
        accepted: list[Evidence] = []
        drop_counter: Counter[str] = Counter()
        blocked_domains = set(domain_lists().get('blocked_domains', []))
        for hit in hits:
            ev = fetch_hit(hit) if need_full_text else Evidence(title=hit.title, url=hit.url, domain=hit.domain, source_type=hit.source_type, engine=hit.engine, published_at=hit.published_at, snippet=hit.snippet, market=market, ticker=ticker, fetch_status='partial', meta={'rank': hit.rank, 'raw_score': hit.raw_score})
            ev.market = market
            ev.ticker = ticker
            key_url = ev.url.strip().lower()
            text_blob = (ev.full_text or ev.snippet or '').strip()
            if key_url in seen_url:
                ev.drop_reasons.append('duplicate_url')
            if any(blocked == ev.domain or blocked in ev.domain for blocked in blocked_domains):
                ev.drop_reasons.append('blocked_domain')
            if need_full_text and (ev.fetch_status == 'failed' or not ev.full_text):
                if 'fetch_failed' not in ev.drop_reasons:
                    ev.drop_reasons.append('fetch_failed')
            if freshness_hours and ev.published_at and self._is_too_old(ev.published_at, freshness_hours):
                ev.drop_reasons.append('too_old')
            if len(text_blob) < 120:
                ev.drop_reasons.append('thin_content')
            ev.accepted = not ev.drop_reasons
            if ev.accepted:
                seen_url.add(key_url)
                accepted.append(ev)
            else:
                for reason in ev.drop_reasons:
                    drop_counter[reason] += 1
        return accepted, dict(drop_counter)

    def _news_evidence_gate(self, ev: Evidence, *, freshness_hours: int | None, seen_urls: set[str], seen_titles: set[str]) -> bool:
        rules = market_news_rules()
        cfg = domain_lists()
        
        trust_tiers = rules.get('trust_tiers', {})
        preferred_domains = trust_tiers.get('trusted_news_domains', cfg.get('news_preferred_domains', []))
        
        quality_gates = rules.get('quality_gates', {})
        soft_drop_reasons = set(quality_gates.get('soft_drop_reasons', []))
        hard_drop_reasons = set(quality_gates.get('hard_drop_reasons', []))
        min_content_length = quality_gates.get('min_content_length', 220)
        
        time_rules = rules.get('time_rules', {})
        allow_missing_time = time_rules.get('allow_missing_time_with_content', False)
        
        key_url = self._canonical_url(ev.url)
        title_key = self._normalize_title(ev.title)
        text_blob = (ev.full_text or ev.snippet or '').strip()

        if len(text_blob) < min_content_length:
            ev.drop_reasons.append('thin_content')
        
        if not ev.published_at:
            ev.time_source = 'none'
            ev.time_confidence = 'low'
            if not allow_missing_time or len(text_blob) < min_content_length:
                ev.drop_reasons.append('missing_publish_time')
        elif freshness_hours and self._is_too_old(ev.published_at, freshness_hours):
            ev.drop_reasons.append('too_old')
        
        if key_url in seen_urls:
            ev.drop_reasons.append('duplicate_url')
        if title_key in seen_titles:
            ev.drop_reasons.append('duplicate_title')
        if self._is_similar_title(title_key, seen_titles):
            ev.drop_reasons.append('duplicate_similar_title')
        
        if not any(dom in ev.domain for dom in preferred_domains):
            ev.drop_reasons.append('untrusted_news_source')

        hard_drops = [r for r in ev.drop_reasons if r in hard_drop_reasons]
        soft_drops = [r for r in ev.drop_reasons if r in soft_drop_reasons]
        
        ev.accepted = len(hard_drops) == 0
        
        if ev.accepted and len(soft_drops) >= 2:
            ev.accepted = False
        
        if ev.accepted:
            seen_urls.add(key_url)
            seen_titles.add(title_key)
        return ev.accepted

    def _canonical_url(self, url: str) -> str:
        parsed = urlparse(url)
        clean = parsed._replace(query='', fragment='')
        return urlunparse(clean).rstrip('/')

    def _normalize_title(self, title: str) -> str:
        text = re.sub(r'\s+', '', title.lower())
        text = re.sub(r'[\-_|｜:：【】\[\]（）()“”"\'\.,，。！？!？]', '', text)
        return text

    def _is_similar_title(self, title_key: str, seen_titles: set[str]) -> bool:
        rules = market_news_rules()
        dedupe = rules.get('dedupe', {})
        threshold = dedupe.get('title_similarity_threshold', 0.9)
        for existing in seen_titles:
            if SequenceMatcher(None, title_key, existing).ratio() >= threshold:
                return True
        return False

    def _is_too_old(self, published_at: str, freshness_hours: int) -> bool:
        try:
            dt = parsedate_to_datetime(published_at) if ',' in published_at else datetime.fromisoformat(published_at.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt < datetime.now(timezone.utc) - timedelta(hours=freshness_hours)
        except Exception:
            return False

    def _record_observation(self, *, task_type: str, query: str, provider_results: list[ProviderResult], query_result_count: int, kept_count: int, drop_counts: dict[str, int], extra: dict | None = None) -> None:
        metrics = self._load_metrics()
        for pr in provider_results:
            metrics['provider_request_count'][pr.provider] = metrics['provider_request_count'].get(pr.provider, 0) + 1
            if pr.healthcheck_ok is True:
                metrics['healthcheck']['pass'] += 1
            elif pr.healthcheck_ok is False:
                metrics['healthcheck']['fail'] += 1
            metrics['query_result_count'][pr.provider] = metrics['query_result_count'].get(pr.provider, 0) + pr.result_count
            if pr.fallback_used:
                metrics['fallback']['used'] += 1
            else:
                metrics['fallback']['not_used'] += 1
        metrics['kept_count'] += kept_count
        for reason, count in drop_counts.items():
            metrics['drop_reason'][reason] = metrics['drop_reason'].get(reason, 0) + count
        self.last_run = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'task_type': task_type,
            'query': query,
            'provider_results': [
                {
                    'provider': pr.provider,
                    'ok': pr.ok,
                    'elapsed_ms': pr.elapsed_ms,
                    'result_count': pr.result_count,
                    'healthcheck_ok': pr.healthcheck_ok,
                    'fallback_used': pr.fallback_used,
                    'error': pr.error,
                }
                for pr in provider_results
            ],
            'query_result_count': query_result_count,
            'kept_count': kept_count,
            'drop_reason': drop_counts,
        }
        if extra:
            self.last_run.update(extra)
        metrics['last_run'] = self.last_run
        self.metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')

    def _load_metrics(self) -> dict:
        if self.metrics_path.exists():
            try:
                return json.loads(self.metrics_path.read_text(encoding='utf-8'))
            except Exception:
                pass
        return {
            'provider_request_count': {},
            'healthcheck': {'pass': 0, 'fail': 0},
            'query_result_count': {},
            'kept_count': 0,
            'drop_reason': {},
            'fallback': {'used': 0, 'not_used': 0},
            'last_run': {},
        }


@lru_cache(maxsize=1)
def get_gateway() -> SearchGateway:
    return SearchGateway()


def search(task_type: str, query: str, **kwargs) -> list[Evidence]:
    return get_gateway().search(task_type=task_type, query=query, **kwargs)