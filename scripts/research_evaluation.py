#!/usr/bin/env python3
"""
Research Agent 评测脚本
测试 ResearchPlanner -> ResearchRunner -> MemoBuilder 完整流程
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.planner import ResearchPlanner
from research.runner import ResearchRunner
from research.memo_builder import MemoBuilder


def load_fixtures() -> list[dict]:
    """加载所有 fixtures"""
    fixtures_dir = ROOT / 'config' / 'research' / 'fixtures'
    fixtures = []
    for f in sorted(fixtures_dir.glob('*.json')):
        fixtures.append(json.loads(f.read_text(encoding='utf-8')))
    return fixtures


def run_fixture(fixture: dict) -> dict:
    """运行单个 fixture"""
    print(f"\n{'='*60}")
    print(f"Fixture: {fixture['name']}")
    print(f"Type: {fixture['task_type']}")
    print(f"Input: {fixture['input']}")
    print(f"{'='*60}")
    
    result = {
        'fixture_name': fixture['name'],
        'task_type': fixture['task_type'],
        'input': fixture['input'],
        'expected_min_kept': fixture.get('expected_min_kept_count', 1),
        'expected_min_answered': fixture.get('expected_min_answered_subquestions', 1),
    }
    
    try:
        # 1. Planner
        print("\n[1] Planning...")
        planner = ResearchPlanner()
        plan = planner.plan(
            task_type=fixture['task_type'],
            query=fixture['input'],
            market=fixture.get('market'),
            freshness_hours=fixture.get('freshness_hours', 72),
            max_rounds=fixture.get('max_rounds', 2),
        )
        
        print(f"  Entity: {plan.entity}")
        print(f"  Market: {plan.market}")
        print(f"  Subquestions ({len(plan.subquestions)}):")
        for i, sq in enumerate(plan.subquestions, 1):
            print(f"    {i}. {sq[:50]}...")
        
        result['plan'] = {
            'entity': plan.entity,
            'market': plan.market,
            'subquestions_count': len(plan.subquestions),
            'subquestions': plan.subquestions,
        }
        
        # 2. Runner
        print("\n[2] Running research...")
        runner = ResearchRunner()
        state = runner.run(
            task_type=fixture['task_type'],
            query=fixture['input'],
            market=fixture.get('market'),
            freshness_hours=fixture.get('freshness_hours', 72),
            max_rounds=fixture.get('max_rounds', 2),
        )
        
        print(f"  Rounds used: {state.rounds_used}")
        print(f"  Stop reason: {state.stop_reason}")
        print(f"  Total evidence: {len(state.all_evidence)}")
        print(f"  Answered questions: {len(state.completed_subquestions)}/{len(plan.subquestions)}")
        
        result['runner'] = {
            'rounds_used': state.rounds_used,
            'stop_reason': state.stop_reason,
            'total_evidence': len(state.all_evidence),
            'answered_subquestions': len(state.completed_subquestions),
            'unanswered_subquestions': len(state.unanswered_subquestions),
        }
        
        # 3. Memo
        print("\n[3] Building memo...")
        builder = MemoBuilder()
        memo = builder.build(state)
        
        print(f"  Title: {memo.title}")
        print(f"  Key findings: {len(memo.key_findings)}")
        print(f"  Evidence gaps: {len(memo.evidence_gaps)}")
        print(f"  Cited evidence: {len(memo.cited_evidence)}")
        
        result['memo'] = {
            'title': memo.title,
            'executive_summary': memo.executive_summary[:100] + '...',
            'key_findings_count': len(memo.key_findings),
            'evidence_gaps_count': len(memo.evidence_gaps),
            'cited_evidence_count': len(memo.cited_evidence),
        }
        
        # 判断是否通过
        passed = (
            len(state.all_evidence) >= fixture.get('expected_min_kept_count', 1) and
            len(state.completed_subquestions) >= fixture.get('expected_min_answered_subquestions', 1)
        )
        
        result['passed'] = passed
        result['status'] = '✅ PASS' if passed else '❌ FAIL'
        
        print(f"\nResult: {result['status']}")
        print(f"  Evidence: {len(state.all_evidence)} >= {fixture.get('expected_min_kept_count', 1)}")
        print(f"  Answered: {len(state.completed_subquestions)} >= {fixture.get('expected_min_answered_subquestions', 1)}")
        
    except Exception as e:
        result['error'] = str(e)
        result['passed'] = False
        result['status'] = '❌ ERROR'
        print(f"\nERROR: {e}")
    
    return result


def main():
    print("Research Agent 评测")
    print("="*60)
    
    # 检查 SearXNG
    import requests
    try:
        resp = requests.get('http://127.0.0.1:18080/healthz', timeout=5, proxies={'http': None, 'https': None})
        print(f"SearXNG: {resp.text.strip()}")
    except Exception as e:
        print(f"ERROR: SearXNG not available: {e}")
        return 1
    
    fixtures = load_fixtures()
    print(f"\nLoaded {len(fixtures)} fixtures")
    
    results = []
    for fixture in fixtures:
        result = run_fixture(fixture)
        results.append(result)
        time.sleep(1)
    
    # 汇总
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)
    
    company_results = [r for r in results if r.get('task_type') == 'company_research']
    market_results = [r for r in results if r.get('task_type') == 'market_news']
    
    print(f"\n[company_research] {len(company_results)} fixtures:")
    for r in company_results:
        print(f"  {r.get('status', '?')} {r['fixture_name']}")
        print(f"      evidence={r.get('runner', {}).get('total_evidence', 0)}, "
              f"answered={r.get('runner', {}).get('answered_subquestions', 0)}")
    
    print(f"\n[market_news] {len(market_results)} fixtures:")
    for r in market_results:
        print(f"  {r.get('status', '?')} {r['fixture_name']}")
        print(f"      evidence={r.get('runner', {}).get('total_evidence', 0)}, "
              f"answered={r.get('runner', {}).get('answered_subquestions', 0)}")
    
    # 统计
    passed = sum(1 for r in results if r.get('passed'))
    total = len(results)
    
    print(f"\n总计: {passed}/{total} fixtures 通过")
    
    # 保存结果
    output_path = ROOT / 'data' / 'research' / 'evaluation_results.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'results': results,
        'summary': {
            'total': total,
            'passed': passed,
            'failed': total - passed,
        }
    }
    
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n结果已保存: {output_path}")
    
    if passed == total:
        print("\n🎉 所有评测通过!")
        return 0
    elif passed >= total * 0.5:
        print(f"\n⚠️ 部分评测通过 ({passed}/{total})")
        return 0
    else:
        print(f"\n❌ 大部分评测未通过 ({passed}/{total})")
        return 1


if __name__ == '__main__':
    sys.exit(main())