#!/usr/bin/env python3
"""
Research Agent 测试脚本 (简化版，不抓正文)
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.planner import ResearchPlanner
from search.adapters.searxng import SearXNGAdapter
from search.models import Evidence
from research.memo_builder import MemoBuilder
from research.runner import ResearchState


def searxng_search(query: str, max_results: int = 10) -> list[Evidence]:
    """使用 SearXNG 进行搜索，不抓正文"""
    adapter = SearXNGAdapter(['http://127.0.0.1:18080'])
    hits = adapter.search(query, max_results=max_results, allow_fallback=False)
    
    # 直接转成 Evidence，不抓正文
    evidence = []
    for hit in hits:
        ev = Evidence(
            title=hit.title,
            url=hit.url,
            domain=hit.domain,
            engine=hit.engine,
            source_type=hit.source_type,
            snippet=hit.snippet,
            published_at=hit.published_at,
            fetch_status='partial',
        )
        evidence.append(ev)
    
    return evidence


def test_fixture(fixture: dict) -> dict:
    """测试单个 fixture"""
    print(f"\n{'='*60}")
    print(f"Fixture: {fixture['name']}")
    print(f"Input: {fixture['input']}")
    print(f"{'='*60}")
    
    # 1. 生成计划
    planner = ResearchPlanner()
    plan = planner.plan(
        task_type=fixture['task_type'],
        query=fixture['input'],
        entity=fixture.get('entity'),
        market=fixture.get('market'),
    )
    
    print(f"Subquestions: {len(plan.subquestions)}")
    
    # 2. 执行搜索
    all_evidence = []
    evidence_by_sq = {}
    
    for query_template in plan.query_templates[:2]:
        print(f"  Searching: {query_template[:30]}...", end='', flush=True)
        try:
            evidence = searxng_search(query_template, max_results=3)
            print(f" -> {len(evidence)}")
            all_evidence.extend(evidence)
            time.sleep(0.3)
        except Exception as e:
            print(f" -> ERROR: {e}")
    
    # 按子问题分配证据
    for sq in plan.subquestions:
        evidence_by_sq[sq] = [e for e in all_evidence if any(w in f"{e.title} {e.snippet}".lower() for w in sq.lower().split() if len(w) > 1)]
    
    # 计算已回答的子问题
    completed = [sq for sq in plan.subquestions if len(evidence_by_sq.get(sq, [])) > 0]
    
    # 3. 构建 Memo
    state = ResearchState(
        plan=plan,
        completed_subquestions=completed,
        unanswered_subquestions=[sq for sq in plan.subquestions if sq not in completed],
        evidence_by_subquestion=evidence_by_sq,
        all_evidence=all_evidence,
        rounds_used=1,
        stop_reason='single_round_test',
    )
    
    builder = MemoBuilder()
    memo = builder.build(state)
    
    print(f"Result: {len(all_evidence)} evidence, {len(completed)}/{len(plan.subquestions)} questions")
    
    passed = len(all_evidence) >= fixture.get('expected_min_kept_count', 1)
    print(f"{'✅ PASS' if passed else '❌ FAIL'}")
    
    return {
        'fixture_name': fixture['name'],
        'task_type': fixture['task_type'],
        'passed': passed,
        'evidence_count': len(all_evidence),
        'answered_subquestions': len(completed),
        'total_subquestions': len(plan.subquestions),
    }


def load_fixtures() -> list[dict]:
    fixtures_dir = ROOT / 'config' / 'research' / 'fixtures'
    fixtures = []
    for f in sorted(fixtures_dir.glob('*.json')):
        fixtures.append(json.loads(f.read_text(encoding='utf-8')))
    return fixtures


def main():
    print("Research Agent 测试 (简化版)")
    print("="*60)
    
    import requests
    try:
        resp = requests.get('http://127.0.0.1:18080/healthz', timeout=5)
        print(f"SearXNG: {resp.text.strip()}")
    except Exception as e:
        print(f"ERROR: SearXNG not available: {e}")
        return 1
    
    fixtures = load_fixtures()
    print(f"Fixtures: {len(fixtures)}")
    
    results = [test_fixture(f) for f in fixtures]
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for r in results:
        status = "✅" if r['passed'] else "❌"
        print(f"{status} {r['fixture_name']}: {r['evidence_count']} evidence, {r['answered_subquestions']}/{r['total_subquestions']} questions")
    
    passed_count = sum(1 for r in results if r['passed'])
    print(f"\nPassed: {passed_count}/{len(results)}")
    
    return 0 if passed_count == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())