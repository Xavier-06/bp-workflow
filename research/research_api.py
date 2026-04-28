"""
Research API - 主链接口，subagent 直接调用
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.runner import ResearchRunner
from research.memo_builder import build_memo


def _fetch_memory_context(entity: str, query: str) -> str:
    """从向量记忆检索相关上下文，失败静默返回空字符串"""
    try:
        sys.path.insert(0, str(ROOT))
        from memory.memory_bridge import search_memory
        results = search_memory(f'{entity} {query}', top_k=5)
        if not results:
            return ''
        lines = ['## 历史记忆 (来自向量库)']
        for r in results:
            lines.append(f'- [{r["category"]}] {r["content"]}')
        return '\n'.join(lines)
    except Exception:
        return ''


def _save_research_to_memory(entity: str, result: dict) -> None:
    """把本次研究的关键发现存入向量记忆"""
    try:
        from memory.memory_bridge import add_memory
        # 存估值数据
        val = result.get('valuation_data', {})
        if val and val.get('price'):
            content = (
                f"{entity} 最新行情："
                f"价格={val.get('price')} "
                f"PE={val.get('pe_ratio')} "
                f"市值={val.get('market_cap')} "
                f"52W高={val.get('52w_high')} 低={val.get('52w_low')}"
            )
            add_memory(content, category='key_data', metadata={'entity': entity, 'type': 'valuation'})
        # 存 accepted evidence 数量作为研究质量记录
        accepted = result.get('accepted_count', 0)
        rounds = result.get('rounds_used', 0)
        add_memory(
            f"{entity} 研究完成：{accepted} 条 accepted evidence，{rounds} 轮搜索",
            category='key_data',
            metadata={'entity': entity, 'type': 'research_summary'}
        )
    except Exception:
        pass


_runner_cache: dict[str, ResearchRunner] = {}


def _get_or_create_runner(snippet_only: bool, max_rounds: int) -> ResearchRunner:
    """复用 ResearchRunner 实例，避免每条 query 都重建（含 SearXNG 探测等重操作）。"""
    cache_key = f'{snippet_only}:{max_rounds}'
    runner = _runner_cache.get(cache_key)
    if runner is None:
        runner = ResearchRunner(
            max_fetch_per_round=8,
            snippet_only=snippet_only,
            max_rounds=max_rounds,
        )
        _runner_cache[cache_key] = runner
    return runner


def run_research(
    query: str,
    entity: str,
    market: str = 'us',
    task_type: str = 'company_research',
    max_rounds: int = 3,
    snippet_only: bool = False,
    save_to_memory: bool = True,
) -> dict:
    """
    主链一键调用。返回 dict，包含：
    - memo_markdown: str  # 完整 markdown 报告
    - accepted_count: int
    - rounds_used: int
    - stop_reason: str
    - citation_map: dict
    - valuation_data: dict  # Yahoo Finance 数据（如有）
    - memory_context: str   # 历史向量记忆（如有）
    """
    # 1. 检索历史记忆作为上下文
    memory_context = _fetch_memory_context(entity, query)
    if memory_context:
        print(f'  [Memory] 检索到 {memory_context.count(chr(10))} 条历史记忆')

    # 2. 执行搜索（复用 runner 实例）
    runner = _get_or_create_runner(snippet_only, max_rounds)
    state = runner.run(task_type, query, entity=entity, market=market)

    # 3. 构建 memo
    memo = build_memo(state)
    md = memo.to_markdown() if hasattr(memo, 'to_markdown') else _fallback_md(memo)

    result = {
        'memo_markdown': md,
        'accepted_count': sum(1 for e in state.all_evidence if e.accepted),
        'rounds_used': state.rounds_used,
        'stop_reason': state.stop_reason or '',
        'citation_map': state.citation_map,
        'valuation_data': getattr(state, 'valuation_data', {}),
        'memory_context': memory_context,
        'entity': entity,
        'market': market,
    }

    # 4. 把本次结果存入记忆
    if save_to_memory:
        _save_research_to_memory(entity, result)

    return result


def _fallback_md(memo) -> str:
    lines = [f'# {memo.title}', '', memo.executive_summary, '']
    for f in memo.key_findings:
        lines.append(f'- {f.finding}')
    return '\n'.join(lines)


if __name__ == '__main__':
    import json
    entity = sys.argv[1] if len(sys.argv) > 1 else '腾讯'
    market = sys.argv[2] if len(sys.argv) > 2 else 'hk'
    result = run_research(f'研究{entity}', entity=entity, market=market, max_rounds=2, snippet_only=True)
    print(f"accepted: {result['accepted_count']}, rounds: {result['rounds_used']}")
    if result.get('memory_context'):
        print('Memory context found:', result['memory_context'][:200])
    print(result['memo_markdown'][:500])
