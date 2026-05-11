#!/usr/bin/env python3
"""
Research Runner V2 性能压测
验收目标：
- p50 < 35s
- p95 < 60s
- 压测不中断
- answered_subquestions 下降 ≤ 1
- kept_count 下降 ≤ 30%
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
import statistics

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.runner import ResearchRunner, ResearchState

# 压测任务（与基线相同）
BENCHMARK_TASKS = [
    {'task_type': 'company_research', 'query': '研究阿里巴巴', 'entity': '阿里巴巴'},
    {'task_type': 'company_research', 'query': '研究英伟达', 'entity': '英伟达'},
    {'task_type': 'company_research', 'query': '研究OpenAI', 'entity': 'OpenAI'},
    {'task_type': 'company_research', 'query': '研究腾讯', 'entity': '腾讯'},
    {'task_type': 'company_research', 'query': '研究特斯拉', 'entity': '特斯拉'},
    {'task_type': 'market_news', 'query': 'Google 最近新闻'},
    {'task_type': 'market_news', 'query': '英伟达最近发生了什么'},
    {'task_type': 'market_news', 'query': 'OpenAI 最近新闻'},
    {'task_type': 'market_news', 'query': '美股市场动态'},
]

# 基线数据（来自 2026-03-25 的测试结果）
BASELINE = {
    'company_research_alibaba': {'evidence': 6, 'answered': 4},
    'company_research_nvidia': {'evidence': 6, 'answered': 0},
    'company_research_openai': {'evidence': 6, 'answered': 4},
    'company_research_tencent': {'evidence': 6, 'answered': 4},
    'company_research_tesla': {'evidence': 6, 'answered': 0},
    'market_news_google': {'evidence': 6, 'answered': 3},
    'market_news_nvidia': {'evidence': 6, 'answered': 0},
    'market_news_openai': {'evidence': 6, 'answered': 3},
    'market_news_us_stocks': {'evidence': 6, 'answered': 3},
}


def run_benchmark(snippet_only: bool = False):
    """运行压测"""
    print("=" * 70)
    print(f"Research Runner V2 Benchmark {'(snippet_only)' if snippet_only else ''}")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 检查 SearXNG
    import requests
    try:
        resp = requests.get('http://127.0.0.1:18080/healthz', timeout=5)
        if resp.text.strip() != 'OK':
            print("ERROR: SearXNG 不健康")
            return None
        print("SearXNG: OK ✅")
    except Exception as e:
        print(f"ERROR: SearXNG 未运行 - {e}")
        return None
    
    runner = ResearchRunner(
        max_fetch_per_round=3,
        fetch_timeout_seconds=5.0,
        fetch_concurrency=4,
        snippet_only=snippet_only,
    )
    
    results = []
    latencies = []
    fetch_counts = []
    fetch_timeout_rates = []
    
    for i, task in enumerate(BENCHMARK_TASKS):
        task_name = task['query'].replace('研究', 'company_research_').replace(' ', '_').replace('最近', '')[:30]
        
        print(f"\n[{i+1}/{len(BENCHMARK_TASKS)}] {task['task_type']}: {task['query']}")
        
        start = time.time()
        try:
            state = runner.run(
                task_type=task['task_type'],
                query=task['query'],
                entity=task.get('entity'),
                max_rounds=1,  # 只跑 1 轮
            )
            elapsed = time.time() - start
            
            latency = round(elapsed, 2)
            evidence_count = len(state.all_evidence)
            answered = len(state.completed_subquestions)
            total_subq = len(state.plan.subquestions)
            
            fetch_count = state.runner_stats.fetch_count
            fetch_timeout_rate = state.runner_stats.fetch_timeout_count / max(fetch_count, 1)
            
            latencies.append(latency)
            fetch_counts.append(fetch_count)
            fetch_timeout_rates.append(fetch_timeout_rate)
            
            # 与基线对比
            baseline = BASELINE.get(task_name, {'evidence': 6, 'answered': 0})
            evidence_delta = evidence_count - baseline['evidence']
            answered_delta = answered - baseline['answered']
            
            result = {
                'task_name': task_name,
                'task_type': task['task_type'],
                'success': True,
                'latency': latency,
                'evidence_count': evidence_count,
                'answered': answered,
                'total_subquestions': total_subq,
                'fetch_count': fetch_count,
                'fetch_timeout_rate': fetch_timeout_rate,
                'baseline_evidence': baseline['evidence'],
                'baseline_answered': baseline['answered'],
                'evidence_delta': evidence_delta,
                'answered_delta': answered_delta,
                'runner_stats': state.runner_stats.to_dict(),
            }
            
            print(f"  ✅ {latency}s, {evidence_count} evidence ({evidence_delta:+d}), "
                  f"{answered}/{total_subq} answered ({answered_delta:+d})")
            print(f"     fetch: {fetch_count}, timeout_rate: {fetch_timeout_rate:.1%}")
            
        except Exception as e:
            elapsed = time.time() - start
            latencies.append(elapsed)
            result = {
                'task_name': task_name,
                'task_type': task['task_type'],
                'success': False,
                'latency': round(elapsed, 2),
                'error': str(e)[:100],
            }
            print(f"  ❌ {elapsed:.2f}s - {str(e)[:50]}")
        
        results.append(result)
    
    # 统计
    successful = [r for r in results if r.get('success')]
    
    if not successful:
        print("\n所有任务失败！")
        return None
    
    # 核心指标
    p50 = statistics.median(latencies)
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 5 else max(latencies)  # 95th percentile
    avg_fetch = statistics.mean(fetch_counts) if fetch_counts else 0
    avg_timeout_rate = statistics.mean(fetch_timeout_rates) if fetch_timeout_rates else 0
    
    # 质量对比
    total_baseline_evidence = sum(BASELINE.get(r['task_name'], {'evidence': 0})['evidence'] for r in successful)
    total_evidence = sum(r['evidence_count'] for r in successful)
    evidence_drop_rate = 1 - (total_evidence / max(total_baseline_evidence, 1))
    
    total_baseline_answered = sum(BASELINE.get(r['task_name'], {'answered': 0})['answered'] for r in successful)
    total_answered = sum(r['answered'] for r in successful)
    answered_drop = total_baseline_answered - total_answered
    
    # 汇总
    print("\n" + "=" * 70)
    print("BENCHMARK RESULTS")
    print("=" * 70)
    
    print(f"\n📊 性能指标:")
    print(f"   p50 latency: {p50:.2f}s {'✅' if p50 < 35 else '❌'} (target: <35s)")
    print(f"   p95 latency: {p95:.2f}s {'✅' if p95 < 60 else '❌'} (target: <60s)")
    print(f"   avg fetch count: {avg_fetch:.1f}")
    print(f"   avg fetch timeout rate: {avg_timeout_rate:.1%}")
    
    print(f"\n📈 质量对比:")
    print(f"   evidence drop rate: {evidence_drop_rate:.1%} {'✅' if evidence_drop_rate <= 0.3 else '❌'} (target: ≤30%)")
    print(f"   answered drop: {answered_drop} {'✅' if answered_drop <= 1 else '❌'} (target: ≤1)")
    
    print(f"\n✅ 成功率: {len(successful)}/{len(results)} ({len(successful)/len(results)*100:.0f}%)")
    
    # 验收
    all_pass = (
        p50 < 35 and
        p95 < 60 and
        evidence_drop_rate <= 0.3 and
        answered_drop <= 1
    )
    
    if all_pass:
        print("\n🎉 验收通过！")
    else:
        print("\n⚠️ 验收未通过")
    
    # 保存结果
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'snippet_only': snippet_only,
        'metrics': {
            'p50_latency': p50,
            'p95_latency': p95,
            'avg_fetch_count': avg_fetch,
            'avg_fetch_timeout_rate': avg_timeout_rate,
            'evidence_drop_rate': evidence_drop_rate,
            'answered_drop': answered_drop,
        },
        'results': results,
    }
    
    output_path = ROOT / 'data' / 'research' / 'benchmark_v2.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n结果已保存: {output_path}")
    
    return output


def main():
    # 先跑 snippet_only 模式（最快）
    print("\n" + "🔥" * 35)
    print("PHASE 1: snippet_only 模式")
    print("🔥" * 35)
    
    result1 = run_benchmark(snippet_only=True)
    
    print("\n" + "=" * 70)
    print("等待 3 秒...")
    time.sleep(3)
    
    # 再跑正常模式
    print("\n" + "🔥" * 35)
    print("PHASE 2: 正常模式（带 fetch）")
    print("🔥" * 35)
    
    result2 = run_benchmark(snippet_only=False)
    
    # 最终汇总
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    
    for name, result in [('snippet_only', result1), ('normal', result2)]:
        if result:
            m = result['metrics']
            print(f"\n{name}:")
            print(f"  p50: {m['p50_latency']:.2f}s, p95: {m['p95_latency']:.2f}s")
            print(f"  evidence drop: {m['evidence_drop_rate']:.1%}, answered drop: {m['answered_drop']}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())