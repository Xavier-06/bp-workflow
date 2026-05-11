#!/usr/bin/env python3
"""
market_news 稳定性回归测试
对每个 fixture 连跑 5 次，记录指标
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add workspace to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from search.gateway import SearchGateway


def load_fixtures():
    """加载所有 market_news fixtures"""
    fixtures_dir = Path(__file__).parent.parent / 'config' / 'search' / 'fixtures'
    fixtures = []
    for f in fixtures_dir.glob('market_news_*.json'):
        fixtures.append(json.loads(f.read_text(encoding='utf-8')))
    return fixtures


def run_stability_test(fixture: dict, runs: int = 5) -> dict:
    """对单个 fixture 运行多次测试"""
    gateway = SearchGateway()
    results = []

    print(f"\n{'='*60}")
    print(f"Fixture: {fixture['name']}")
    print(f"Query: {fixture.get('query', 'N/A')}")
    print(f"Expected min kept: {fixture.get('expected_min_kept_count', 0)}")
    print(f"{'='*60}")

    for i in range(runs):
        print(f"\n--- Run {i+1}/{runs} ---")
        
        evidence = gateway.search(
            task_type=fixture['task_type'],
            query=fixture.get('query', ''),
            market=fixture.get('market'),
            ticker=fixture.get('ticker'),
            company=fixture.get('company'),
            freshness_hours=fixture.get('freshness_hours', 72),
            max_results=fixture.get('max_results', 10),
        )

        # 从 last_run 获取详细统计
        last_run = gateway.last_run
        debug_matrix = last_run.get('extra', {}).get('news_debug_matrix', [])
        
        # 计算原始结果数和预过滤后结果
        raw_count = sum(row.get('raw_result_count', 0) for row in debug_matrix)
        fetched_count = sum(row.get('fetched_count', 0) for row in debug_matrix)
        
        # 统计域分布
        all_domains = []
        for row in debug_matrix:
            domains = row.get('top_domains', [])
            all_domains.extend(domains)
        
        # 统计丢弃原因
        drop_counts = last_run.get('drop_reason', {})
        
        result = {
            'run': i + 1,
            'kept_count': len(evidence),
            'raw_result_count': raw_count,
            'fetched_count': fetched_count,
            'top_domains': list(set(all_domains)),
            'drop_reasons': drop_counts,
            'kept_domains': list(set(e.domain for e in evidence)),
        }
        results.append(result)

        print(f"  kept_count: {result['kept_count']}")
        print(f"  raw_count: {raw_count}, fetched: {fetched_count}")
        print(f"  kept domains: {result['kept_domains'][:5]}")
        print(f"  top drop reasons: {dict(list(drop_counts.items())[:3])}")

    # 汇总统计
    kept_counts = [r['kept_count'] for r in results]
    pass_count = sum(1 for c in kept_counts if c >= fixture.get('expected_min_kept_count', 0))
    
    summary = {
        'fixture_name': fixture['name'],
        'expected_min_kept': fixture.get('expected_min_kept_count', 0),
        'runs': runs,
        'pass_count': pass_count,
        'pass_rate': f"{pass_count}/{runs}",
        'passed': pass_count >= runs - 1,  # 5次中至少4次
        'kept_counts': kept_counts,
        'all_kept_domains': list(set(d for r in results for d in r['kept_domains'])),
        'all_top_domains': list(set(d for r in results for d in r['top_domains'])),
        'aggregate_drop_reasons': _aggregate_drop_reasons(results),
    }

    print(f"\n{'='*60}")
    print(f"SUMMARY for {fixture['name']}")
    print(f"  Pass rate: {summary['pass_rate']}")
    print(f"  Passed: {summary['passed']}")
    print(f"  Kept counts: {kept_counts}")
    print(f"{'='*60}")

    return summary


def _aggregate_drop_reasons(results: list) -> dict:
    """聚合所有丢弃原因"""
    from collections import Counter
    all_reasons = Counter()
    for r in results:
        for reason, count in r.get('drop_reasons', {}).items():
            all_reasons[reason] += count
    return dict(all_reasons.most_common(10))


def main():
    fixtures = load_fixtures()
    print(f"Loaded {len(fixtures)} fixtures: {[f['name'] for f in fixtures]}")

    all_summaries = []
    for fixture in fixtures:
        summary = run_stability_test(fixture, runs=5)
        all_summaries.append(summary)

    # 打印最终汇总
    print("\n" + "="*80)
    print("FINAL SUMMARY - ALL FIXTURES")
    print("="*80)
    
    all_passed = True
    for s in all_summaries:
        status = "✅ PASS" if s['passed'] else "❌ FAIL"
        print(f"\n{s['fixture_name']}: {status}")
        print(f"  Expected min: {s['expected_min_kept']}, Got: {s['kept_counts']}")
        print(f"  Pass rate: {s['pass_rate']}")
        print(f"  All kept domains: {s['all_kept_domains'][:5]}")
        if not s['passed']:
            all_passed = False

    # 保存详细结果
    output_path = Path(__file__).parent.parent / 'data' / 'search_gateway' / 'regression_results.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'summaries': all_summaries,
        'overall_passed': all_passed,
    }
    
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n详细结果已保存到: {output_path}")

    if all_passed:
        print("\n🎉 所有 fixture 稳定通过!")
        return 0
    else:
        print("\n⚠️ 部分 fixture 未通过稳定性测试")
        return 1


if __name__ == '__main__':
    sys.exit(main())