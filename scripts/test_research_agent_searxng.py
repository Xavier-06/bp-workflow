#!/usr/bin/env python3
"""
Research Agent 测试脚本 (仅使用 SearXNG)
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
from search.fetch import fetch_hit
from search.models import Evidence
from research.memo_builder import MemoBuilder
from research.runner import ResearchState


def searxng_search(query: str, max_results: int = 10) -> list[Evidence]:
    """使用 SearXNG 进行搜索"""
    adapter = SearXNGAdapter(['http://127.0.0.1:18080'])
    hits = adapter.search(query, max_results=max_results, allow_fallback=False)
    
    evidence = []
    for hit in hits:
        ev = fetch_hit(hit)
        evidence.append(ev)
    
    return evidence


def test_fixture(fixture: dict) -> dict:
    """测试单个 fixture"""
    print(f"\n{'='*60}")
    print(f"Fixture: {fixture['name']}")
    print(f"Input: {fixture['input']}")
    print(f"Task Type: {fixture['task_type']}")
    print(f"{'='*60}")
    
    # 1. 生成计划
    planner = ResearchPlanner()
    plan = planner.plan(
        task_type=fixture['task_type'],
        query=fixture['input'],
        entity=fixture.get('entity'),
        market=fixture.get('market'),
        max_rounds=fixture.get('max_rounds', 3),
        freshness_hours=fixture.get('freshness_hours', 72),
    )
    
    print(f"\nPlan: {len(plan.subquestions)} subquestions")
    for i, sq in enumerate(plan.subquestions, 1):
        print(f"  {i}. {sq[:50]}...")
    
    # 2. 执行研究 (简化版，不使用完整的 Runner)
    all_evidence = []
    evidence_by_sq = {}
    
    for query_template in plan.query_templates[:3]:
        print(f"\nSearching: {query_template[:40]}...")
        try:
            evidence = searxng_search(query_template, max_results=5)
            print(f"  Found: {len(evidence)} evidence")
            all_evidence.extend(evidence)
            time.sleep(0.5)
        except Exception as e:
            print(f"  Error: {e}")
    
    # 按子问题分配证据
    for sq in plan.subquestions:
        evidence_by_sq[sq] = []
        for ev in all_evidence:
            # 简单关键词匹配
            sq_words = set(sq.lower().split())
            ev_text = f"{ev.title} {ev.snippet or ''}".lower()
            if any(w in ev_text for w in sq_words if len(w) > 1):
                evidence_by_sq[sq].append(ev)
    
    # 计算已回答的子问题
    completed = [sq for sq in plan.subquestions if len(evidence_by_sq.get(sq, [])) > 0]
    
    # 3. 构建 State 和 Memo
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
    
    print(f"\nResults:")
    print(f"  Total evidence: {len(all_evidence)}")
    print(f"  Answered: {len(completed)}/{len(plan.subquestions)}")
    print(f"  Key findings: {len(memo.key_findings)}")
    print(f"  Evidence gaps: {len(memo.evidence_gaps)}")
    
    # 检查是否通过
    passed = (
        len(all_evidence) >= fixture.get('expected_min_kept_count', 1) and
        len(completed) >= fixture.get('expected_min_answered_subquestions', 1)
    )
    
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"\n{status}")
    
    return {
        'fixture_name': fixture['name'],
        'task_type': fixture['task_type'],
        'passed': passed,
        'evidence_count': len(all_evidence),
        'answered_subquestions': len(completed),
        'total_subquestions': len(plan.subquestions),
        'key_findings_count': len(memo.key_findings),
        'evidence_gaps_count': len(memo.evidence_gaps),
        'memo_title': memo.title,
    }


def load_fixtures() -> list[dict]:
    """加载所有研究 fixtures"""
    fixtures_dir = ROOT / 'config' / 'research' / 'fixtures'
    fixtures = []
    for f in sorted(fixtures_dir.glob('*.json')):
        fixtures.append(json.loads(f.read_text(encoding='utf-8')))
    return fixtures


def main():
    print("Research Agent 测试 (仅使用 SearXNG)")
    print("="*60)
    
    # 检查 SearXNG
    import requests
    try:
        resp = requests.get('http://127.0.0.1:18080/healthz', timeout=5)
        print(f"SearXNG healthcheck: {resp.text.strip()}")
    except Exception as e:
        print(f"ERROR: SearXNG not available: {e}")
        return 1
    
    fixtures = load_fixtures()
    print(f"\nLoaded {len(fixtures)} fixtures")
    
    results = []
    for fixture in fixtures:
        try:
            result = test_fixture(fixture)
            results.append(result)
        except Exception as e:
            print(f"\nERROR: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                'fixture_name': fixture['name'],
                'passed': False,
                'error': str(e),
            })
    
    # 汇总
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)
    
    company_results = [r for r in results if r.get('task_type') == 'company_research']
    news_results = [r for r in results if r.get('task_type') == 'market_news']
    
    print(f"\nCompany Research ({len(company_results)} fixtures):")
    for r in company_results:
        status = "✅" if r.get('passed') else "❌"
        print(f"  {status} {r['fixture_name']}: {r.get('answered_subquestions', 0)}/{r.get('total_subquestions', 0)} questions, {r.get('evidence_count', 0)} evidence")
    
    print(f"\nMarket News ({len(news_results)} fixtures):")
    for r in news_results:
        status = "✅" if r.get('passed') else "❌"
        print(f"  {status} {r['fixture_name']}: {r.get('evidence_count', 0)} evidence")
    
    # 保存结果
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'results': results,
        'summary': {
            'total': len(results),
            'passed': sum(1 for r in results if r.get('passed')),
            'failed': sum(1 for r in results if not r.get('passed')),
        }
    }
    
    output_path = ROOT / 'data' / 'research' / 'test_results.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n结果已保存到: {output_path}")
    
    if all(r.get('passed') for r in results):
        print("\n🎉 所有测试通过!")
        return 0
    else:
        print("\n⚠️ 部分测试未通过")
        return 1


if __name__ == '__main__':
    sys.exit(main())