#!/usr/bin/env python3
"""
Phase 2A.1 评测 - 重点修复 0% grounded fixtures
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.runner import ResearchRunner
from research.memo_builder import MemoBuilder

# 重点 fixtures（之前 grounded_rate = 0%）
FOCUS_FIXTURES = [
    # company_research
    {'name': 'company_research_tencent', 'task_type': 'company_research', 'query': '研究腾讯', 'entity': '腾讯', 'market': 'hk'},
    {'name': 'company_research_microsoft', 'task_type': 'company_research', 'query': '研究微软', 'entity': '微软', 'market': 'us'},
    {'name': 'company_research_apple', 'task_type': 'company_research', 'query': '研究苹果', 'entity': '苹果', 'market': 'us'},
    {'name': 'company_research_nvidia', 'task_type': 'company_research', 'query': '研究英伟达', 'entity': '英伟达', 'market': 'us'},
    # market_news
    {'name': 'market_news_openai', 'task_type': 'market_news', 'query': 'OpenAI 最近新闻', 'entity': 'OpenAI'},
    {'name': 'market_news_tesla', 'task_type': 'market_news', 'query': '特斯拉最近新闻', 'entity': '特斯拉'},
    {'name': 'market_news_google', 'task_type': 'market_news', 'query': 'Google 最近新闻', 'entity': 'Google'},
    {'name': 'market_news_meta', 'task_type': 'market_news', 'query': 'Meta 最近新闻', 'entity': 'Meta'},
]


def run_eval():
    """运行评测"""
    print("=" * 70)
    print("Phase 2A.1 评测 - 重点修复 0% grounded fixtures")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    import requests
    try:
        resp = requests.get('http://127.0.0.1:18080/healthz', timeout=5, proxies={'http': None, 'https': None})
        if resp.text.strip() != 'OK':
            print("ERROR: SearXNG 不健康")
            return None
        print("SearXNG: OK ✅")
    except Exception as e:
        print(f"ERROR: SearXNG 未运行 - {e}")
        return None
    
    runner = ResearchRunner(max_fetch_per_round=3)
    memo_builder = MemoBuilder()
    
    results = []
    
    for i, fixture in enumerate(FOCUS_FIXTURES):
        print(f"\n[{i+1}/{len(FOCUS_FIXTURES)}] {fixture['name']}")
        print("-" * 50)
        
        start = time.time()
        try:
            state = runner.run(
                task_type=fixture['task_type'],
                query=fixture['query'],
                entity=fixture.get('entity'),
                market=fixture.get('market'),
                max_rounds=1,
            )
            
            memo = memo_builder.build(state)
            elapsed = time.time() - start
            
            result = {
                'name': fixture['name'],
                'task_type': fixture['task_type'],
                'latency': round(elapsed, 2),
                'provider_used': state.provider_used,
                'tavily_request_delta': state.runner_stats.tavily_request_delta,
                'searxng_request_delta': state.runner_stats.searxng_request_delta,
                'direct_sources_hit': state.runner_stats.direct_sources_hit,
                'profile_hit': state.runner_stats.profile_hit,
                'source_families_seen': state.source_families_seen,
                'official_evidence_count': state.runner_stats.official_evidence_count,
                'filing_evidence_count': state.runner_stats.filing_evidence_count,
                'primary_source_count': state.runner_stats.primary_source_count,
                'aggregator_count': state.runner_stats.aggregator_count,
                'missing_publish_time_count': state.runner_stats.missing_publish_time_count,
                'secondary_only_flag': state.secondary_only_flag,
                'official_source_missing': state.official_source_missing,
                'kept_count': len(state.all_evidence),
                'answered_subquestions': len(state.completed_subquestions),
                'key_findings_count': len(memo.key_findings),
                'evidence_gaps_count': len(memo.evidence_gaps),
                'grounded_rate': memo.grounded_rate,
                'rounds_used': state.rounds_used,
                'stop_reason': state.stop_reason,
            }
            
            # 验收判断
            has_official = result['official_evidence_count'] > 0 or result['filing_evidence_count'] > 0
            has_primary = result['primary_source_count'] > 0
            has_findings = result['key_findings_count'] > 0
            
            if has_findings:
                result['status'] = 'PASS'
                print(f"  ✅ PASS")
            else:
                result['status'] = 'FAIL'
                print(f"  ❌ FAIL")
            
            print(f"     profile_hit: {result['profile_hit']}, direct_sources: {result['direct_sources_hit']}")
            print(f"     official: {result['official_evidence_count']}, primary: {result['primary_source_count']}, aggregator: {result['aggregator_count']}")
            print(f"     grounded_rate: {result['grounded_rate']:.1%}, secondary_only: {result['secondary_only_flag']}")
            print(f"     sources: {result['source_families_seen']}")
            
        except Exception as e:
            elapsed = time.time() - start
            result = {
                'name': fixture['name'],
                'status': 'ERROR',
                'error': str(e)[:100],
            }
            print(f"  ❌ ERROR: {str(e)[:50]}")
        
        results.append(result)
    
    # 汇总
    print("\n" + "=" * 70)
    print("评测汇总")
    print("=" * 70)
    
    company_results = [r for r in results if r.get('task_type') == 'company_research']
    news_results = [r for r in results if r.get('task_type') == 'market_news']
    
    print("\n## Company Research")
    for r in company_results:
        status = '✅' if r.get('status') == 'PASS' else '❌'
        grounded = r.get('grounded_rate', 0)
        official = r.get('official_evidence_count', 0)
        print(f"  {status} {r['name']}: grounded={grounded:.0%}, official={official}, profile={r.get('profile_hit', False)}")
    
    print("\n## Market News")
    for r in news_results:
        status = '✅' if r.get('status') == 'PASS' else '❌'
        grounded = r.get('grounded_rate', 0)
        primary = r.get('primary_source_count', 0)
        secondary = r.get('secondary_only_flag', False)
        print(f"  {status} {r['name']}: grounded={grounded:.0%}, primary={primary}, secondary_only={secondary}")
    
    # 统计
    total_official = sum(r.get('official_evidence_count', 0) for r in results)
    total_primary = sum(r.get('primary_source_count', 0) for r in results)
    avg_grounded = sum(r.get('grounded_rate', 0) for r in results) / len(results) if results else 0
    profile_hit_rate = sum(1 for r in results if r.get('profile_hit', False)) / len(results) if results else 0
    
    print(f"\n## 全局统计")
    print(f"  total_official_evidence: {total_official}")
    print(f"  total_primary_source: {total_primary}")
    print(f"  avg_grounded_rate: {avg_grounded:.1%}")
    print(f"  profile_hit_rate: {profile_hit_rate:.1%}")
    
    # 重点检查之前 0% 的 fixtures
    zero_before = ['company_research_tencent', 'company_research_microsoft', 'market_news_openai', 'market_news_tesla']
    improved = []
    still_zero = []
    
    for r in results:
        if r['name'] in zero_before:
            if r.get('grounded_rate', 0) > 0:
                improved.append(r['name'])
            else:
                still_zero.append(r['name'])
    
    print(f"\n## 重点 fixtures 改进情况")
    print(f"  已脱离 0%: {improved}")
    print(f"  仍为 0%: {still_zero}")
    
    # 最终判断
    print("\n" + "=" * 70)
    print("最终判断")
    print("=" * 70)
    
    if len(still_zero) == 0:
        print("✅ 已完成可验收的 Phase 2A")
    elif total_official > 0 or total_primary > 0:
        print("⚠️ 已进入高可信研究阶段（Phase 2A in progress）")
        print(f"   仍有 {len(still_zero)} 个核心 fixture 为 0% grounded")
    else:
        print("❌ 仍停留在最小研究代理 Alpha")
    
    # 保存
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'results': results,
        'summary': {
            'total_official_evidence': total_official,
            'total_primary_source': total_primary,
            'avg_grounded_rate': avg_grounded,
            'profile_hit_rate': profile_hit_rate,
            'improved_from_zero': improved,
            'still_zero': still_zero,
        }
    }
    
    output_path = ROOT / 'data' / 'research' / 'phase2a1_eval.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n结果已保存: {output_path}")
    
    return output


if __name__ == '__main__':
    run_eval()