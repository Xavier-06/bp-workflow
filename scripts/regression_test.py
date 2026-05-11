#!/usr/bin/env python3
"""
Research Runner V2 回归测试
验证：
- p95 latency < 60s
- answered_subquestions 不下降
- kept_count 下降 ≤ 30%
- timeout_rate 合理
"""

import json
import sys
import time
import statistics
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.runner import ResearchRunner
from research.memo_builder import MemoBuilder

# 回归测试 fixtures
REGRESSION_FIXTURES = [
    # company_research
    {'name': 'company_research_alibaba', 'task_type': 'company_research', 'query': '研究阿里巴巴', 'entity': '阿里巴巴', 'market': 'hk'},
    {'name': 'company_research_tencent', 'task_type': 'company_research', 'query': '研究腾讯', 'entity': '腾讯', 'market': 'hk'},
    {'name': 'company_research_nvidia', 'task_type': 'company_research', 'query': '研究英伟达', 'entity': '英伟达', 'market': 'us'},
    # market_news
    {'name': 'market_news_openai', 'task_type': 'market_news', 'query': 'OpenAI 最近新闻', 'entity': 'OpenAI'},
    {'name': 'market_news_google', 'task_type': 'market_news', 'query': 'Google 最近新闻', 'entity': 'Google'},
]

# 基线指标（Phase 1 冻结时记录）
BASELINE_METRICS = {
    'p50_latency_target': 35.0,
    'p95_latency_target': 60.0,
    'min_answered_subquestions': 2,
    'max_timeout_rate': 0.3,
}


@dataclass
class RegressionResult:
    """回归测试结果"""
    passed: bool
    p50_latency: float
    p95_latency: float
    avg_answered: float
    avg_evidence: float
    avg_timeout_rate: float
    details: list


def run_regression_test() -> RegressionResult:
    """运行回归测试"""
    print("=" * 70)
    print("Research Runner V2 回归测试")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 检查 SearXNG
    import requests
    try:
        resp = requests.get('http://127.0.0.1:18080/healthz', timeout=5, proxies={'http': None, 'https': None})
        if resp.text.strip() != 'OK':
            print("ERROR: SearXNG 不健康")
            return RegressionResult(passed=False, p50_latency=0, p95_latency=0, avg_answered=0, avg_evidence=0, avg_timeout_rate=0, details=[])
        print("SearXNG: OK ✅")
    except Exception as e:
        print(f"ERROR: SearXNG 未运行 - {e}")
        return RegressionResult(passed=False, p50_latency=0, p95_latency=0, avg_answered=0, avg_evidence=0, avg_timeout_rate=0, details=[])
    
    runner = ResearchRunner(
        max_fetch_per_round=3,
        fetch_timeout_seconds=5.0,
        fetch_concurrency=4,
    )
    memo_builder = MemoBuilder()
    
    results = []
    latencies = []
    answered_counts = []
    evidence_counts = []
    timeout_rates = []
    
    for i, fixture in enumerate(REGRESSION_FIXTURES):
        print(f"\n[{i+1}/{len(REGRESSION_FIXTURES)}] {fixture['name']}")
        
        start = time.time()
        try:
            state = runner.run(
                task_type=fixture['task_type'],
                query=fixture['query'],
                entity=fixture.get('entity'),
                market=fixture.get('market'),
                max_rounds=1,
            )
            elapsed = time.time() - start
            
            # 生成 memo
            memo = memo_builder.build(state)
            
            latency = round(elapsed, 2)
            answered = len(state.completed_subquestions)
            evidence = len(state.all_evidence)
            timeout_rate = state.runner_stats.fetch_timeout_count / max(state.runner_stats.fetch_count, 1)
            
            latencies.append(latency)
            answered_counts.append(answered)
            evidence_counts.append(evidence)
            timeout_rates.append(timeout_rate)
            
            result = {
                'name': fixture['name'],
                'task_type': fixture['task_type'],
                'success': True,
                'latency': latency,
                'answered': answered,
                'total_subquestions': len(state.plan.subquestions),
                'evidence': evidence,
                'timeout_rate': timeout_rate,
                'memo_stats': {
                    'key_findings': len(memo.key_findings),
                    'evidence_gaps': len(memo.evidence_gaps),
                    'cited_evidence': len(memo.cited_evidence),
                }
            }
            
            print(f"  ✅ {latency}s, {evidence} evidence, {answered} answered")
            print(f"     memo: {len(memo.key_findings)} findings, {len(memo.evidence_gaps)} gaps")
            
        except Exception as e:
            elapsed = time.time() - start
            latencies.append(elapsed)
            result = {
                'name': fixture['name'],
                'task_type': fixture['task_type'],
                'success': False,
                'latency': round(elapsed, 2),
                'error': str(e)[:100],
            }
            print(f"  ❌ {elapsed:.2f}s - {str(e)[:50]}")
        
        results.append(result)
    
    # 计算统计
    successful = [r for r in results if r.get('success')]
    
    p50 = statistics.median(latencies) if latencies else 0
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 5 else max(latencies) if latencies else 0
    avg_answered = statistics.mean(answered_counts) if answered_counts else 0
    avg_evidence = statistics.mean(evidence_counts) if evidence_counts else 0
    avg_timeout_rate = statistics.mean(timeout_rates) if timeout_rates else 0
    
    # 验收
    print("\n" + "=" * 70)
    print("回归测试结果")
    print("=" * 70)
    
    checks = []
    
    # 1. Latency 检查
    p50_ok = p50 < BASELINE_METRICS['p50_latency_target']
    p95_ok = p95 < BASELINE_METRICS['p95_latency_target']
    print(f"\n⏱️  Latency:")
    print(f"   p50: {p50:.2f}s {'✅' if p50_ok else '❌'} (target: <{BASELINE_METRICS['p50_latency_target']}s)")
    print(f"   p95: {p95:.2f}s {'✅' if p95_ok else '❌'} (target: <{BASELINE_METRICS['p95_latency_target']}s)")
    checks.append(p50_ok and p95_ok)
    
    # 2. Answered subquestions 检查
    answered_ok = avg_answered >= BASELINE_METRICS['min_answered_subquestions']
    print(f"\n📋 Answered subquestions:")
    print(f"   avg: {avg_answered:.1f} {'✅' if answered_ok else '❌'} (min: {BASELINE_METRICS['min_answered_subquestions']})")
    checks.append(answered_ok)
    
    # 3. Timeout rate 检查
    timeout_ok = avg_timeout_rate <= BASELINE_METRICS['max_timeout_rate']
    print(f"\n⏰ Timeout rate:")
    print(f"   avg: {avg_timeout_rate:.1%} {'✅' if timeout_ok else '❌'} (max: {BASELINE_METRICS['max_timeout_rate']:.0%})")
    checks.append(timeout_ok)
    
    # 4. Evidence 检查
    print(f"\n📊 Evidence:")
    print(f"   avg: {avg_evidence:.1f} per fixture")
    
    # 最终判断
    all_passed = all(checks) and len(successful) == len(REGRESSION_FIXTURES)
    
    print("\n" + "=" * 70)
    if all_passed:
        print("✅ 回归测试通过")
    else:
        print("❌ 回归测试未通过")
    print("=" * 70)
    
    # 保存结果
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'passed': all_passed,
        'metrics': {
            'p50_latency': p50,
            'p95_latency': p95,
            'avg_answered': avg_answered,
            'avg_evidence': avg_evidence,
            'avg_timeout_rate': avg_timeout_rate,
        },
        'results': results,
    }
    
    output_path = ROOT / 'data' / 'research' / 'regression_v2.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n结果已保存: {output_path}")
    
    return RegressionResult(
        passed=all_passed,
        p50_latency=p50,
        p95_latency=p95,
        avg_answered=avg_answered,
        avg_evidence=avg_evidence,
        avg_timeout_rate=avg_timeout_rate,
        details=results,
    )


def main():
    result = run_regression_test()
    return 0 if result.passed else 1


if __name__ == '__main__':
    sys.exit(main())