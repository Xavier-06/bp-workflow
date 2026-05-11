#!/usr/bin/env python3
"""
Phase 2A 评测 - 任务级源路由 + 高可信源
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
from routing.source_router import get_router

# Phase 1 fixtures（回归）
PHASE1_FIXTURES = [
    {'name': 'company_research_alibaba', 'task_type': 'company_research', 'query': '研究阿里巴巴', 'entity': '阿里巴巴', 'market': 'hk'},
    {'name': 'company_research_tencent', 'task_type': 'company_research', 'query': '研究腾讯', 'entity': '腾讯', 'market': 'hk'},
    {'name': 'company_research_nvidia', 'task_type': 'company_research', 'query': '研究英伟达', 'entity': '英伟达', 'market': 'us'},
    {'name': 'market_news_openai', 'task_type': 'market_news', 'query': 'OpenAI 最近新闻', 'entity': 'OpenAI'},
    {'name': 'market_news_google', 'task_type': 'market_news', 'query': 'Google 最近新闻', 'entity': 'Google'},
    {'name': 'market_news_tesla', 'task_type': 'market_news', 'query': '特斯拉最近新闻', 'entity': '特斯拉'},
]

# Phase 2A 新增 fixtures
PHASE2A_FIXTURES = [
    # company_research - 有官方 IR/披露
    {'name': 'company_research_apple', 'task_type': 'company_research', 'query': '研究苹果', 'entity': '苹果', 'market': 'us'},
    {'name': 'company_research_microsoft', 'task_type': 'company_research', 'query': '研究微软', 'entity': '微软', 'market': 'us'},
    # market_news - 有原始媒体报道
    {'name': 'market_news_meta', 'task_type': 'market_news', 'query': 'Meta 最近新闻', 'entity': 'Meta'},
]


def run_eval():
    """运行评测"""
    print("=" * 70)
    print("Phase 2A 评测 - 任务级源路由")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
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
    
    runner = ResearchRunner(max_fetch_per_round=3)
    memo_builder = MemoBuilder()
    
    all_results = []
    
    # Phase 1 回归测试
    print("\n" + "=" * 70)
    print("Phase 1 回归测试")
    print("=" * 70)
    
    for i, fixture in enumerate(PHASE1_FIXTURES):
        print(f"\n[{i+1}/{len(PHASE1_FIXTURES)}] {fixture['name']}")
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
                'phase': 'phase1_regression',
                'latency': round(elapsed, 2),
                'provider_used': state.provider_used,
                'tavily_request_delta': state.runner_stats.tavily_request_delta,
                'kept_count': len(state.all_evidence),
                'answered_subquestions': len(state.completed_subquestions),
                'key_findings_count': len(memo.key_findings),
                'evidence_gaps_count': len(memo.evidence_gaps),
                'official_evidence_count': state.runner_stats.official_evidence_count,
                'filing_evidence_count': state.runner_stats.filing_evidence_count,
                'primary_source_count': state.runner_stats.primary_source_count,
                'aggregator_count': state.runner_stats.aggregator_count,
                'grounded_rate': memo.grounded_rate,
                'source_families_seen': state.source_families_seen,
            }
            
            # Phase 1 验收
            assert result['tavily_request_delta'] == 0
            has_findings_or_gaps = result['key_findings_count'] > 0 or result['evidence_gaps_count'] > 0
            
            if has_findings_or_gaps:
                result['status'] = 'PASS'
                print(f"  ✅ PASS")
            else:
                result['status'] = 'FAIL'
                print(f"  ❌ FAIL")
            
            print(f"     official: {result['official_evidence_count']}, primary: {result['primary_source_count']}")
            print(f"     grounded_rate: {result['grounded_rate']:.1%}")
            
        except Exception as e:
            result = {'name': fixture['name'], 'status': 'ERROR', 'error': str(e)[:50]}
            print(f"  ❌ ERROR: {str(e)[:50]}")
        
        all_results.append(result)
    
    # Phase 2A 新增测试
    print("\n" + "=" * 70)
    print("Phase 2A 新增测试")
    print("=" * 70)
    
    for i, fixture in enumerate(PHASE2A_FIXTURES):
        print(f"\n[{i+1}/{len(PHASE2A_FIXTURES)}] {fixture['name']}")
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
                'phase': 'phase2a_new',
                'latency': round(elapsed, 2),
                'provider_used': state.provider_used,
                'tavily_request_delta': state.runner_stats.tavily_request_delta,
                'kept_count': len(state.all_evidence),
                'answered_subquestions': len(state.completed_subquestions),
                'key_findings_count': len(memo.key_findings),
                'evidence_gaps_count': len(memo.evidence_gaps),
                'official_evidence_count': state.runner_stats.official_evidence_count,
                'filing_evidence_count': state.runner_stats.filing_evidence_count,
                'primary_source_count': state.runner_stats.primary_source_count,
                'aggregator_count': state.runner_stats.aggregator_count,
                'missing_publish_time_count': state.runner_stats.missing_publish_time_count,
                'grounded_rate': memo.grounded_rate,
                'source_families_seen': state.source_families_seen,
            }
            
            # Phase 2A 验收
            has_official = result['official_evidence_count'] > 0 or result['filing_evidence_count'] > 0
            has_findings = result['key_findings_count'] > 0
            
            if has_findings:
                result['status'] = 'PASS'
                print(f"  ✅ PASS")
            else:
                result['status'] = 'FAIL'
                print(f"  ❌ FAIL")
            
            print(f"     official: {result['official_evidence_count']}, filing: {result['filing_evidence_count']}")
            print(f"     primary: {result['primary_source_count']}, aggregator: {result['aggregator_count']}")
            print(f"     grounded_rate: {result['grounded_rate']:.1%}")
            print(f"     sources: {result['source_families_seen']}")
            
        except Exception as e:
            result = {'name': fixture['name'], 'status': 'ERROR', 'error': str(e)[:50]}
            print(f"  ❌ ERROR: {str(e)[:50]}")
        
        all_results.append(result)
    
    # 汇总
    print("\n" + "=" * 70)
    print("评测汇总")
    print("=" * 70)
    
    phase1_results = [r for r in all_results if r.get('phase') == 'phase1_regression']
    phase2a_results = [r for r in all_results if r.get('phase') == 'phase2a_new']
    
    print("\n## Phase 1 回归")
    for r in phase1_results:
        status = '✅' if r.get('status') == 'PASS' else '❌'
        print(f"  {status} {r['name']}: grounded_rate={r.get('grounded_rate', 0):.1%}")
    
    print("\n## Phase 2A 新增")
    for r in phase2a_results:
        status = '✅' if r.get('status') == 'PASS' else '❌'
        print(f"  {status} {r['name']}: official={r.get('official_evidence_count', 0)}, grounded_rate={r.get('grounded_rate', 0):.1%}")
    
    # 统计
    total_official = sum(r.get('official_evidence_count', 0) for r in all_results)
    total_primary = sum(r.get('primary_source_count', 0) for r in all_results)
    total_aggregator = sum(r.get('aggregator_count', 0) for r in all_results)
    avg_grounded = sum(r.get('grounded_rate', 0) for r in all_results) / len(all_results) if all_results else 0
    
    print(f"\n## 全局统计")
    print(f"  official_evidence_total: {total_official}")
    print(f"  primary_source_total: {total_primary}")
    print(f"  aggregator_total: {total_aggregator}")
    print(f"  avg_grounded_rate: {avg_grounded:.1%}")
    
    # 最终判断
    phase1_pass = all(r.get('status') == 'PASS' for r in phase1_results)
    phase2a_pass = all(r.get('status') == 'PASS' for r in phase2a_results)
    
    print("\n" + "=" * 70)
    print("最终判断")
    print("=" * 70)
    
    if not phase1_pass:
        print("❌ 仍停留在最小研究代理 Alpha（Phase 1 回归失败）")
    elif total_official == 0 and total_primary == 0:
        print("❌ 仍停留在最小研究代理 Alpha（无官方/原始源）")
    elif phase2a_pass and total_official > 0:
        print("✅ 已进入高可信研究阶段（Phase 2A in progress）")
    else:
        print("⚠️ 已进入高可信研究阶段（Phase 2A in progress）")
    
    # 保存
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'results': all_results,
        'summary': {
            'total_official_evidence': total_official,
            'total_primary_source': total_primary,
            'total_aggregator': total_aggregator,
            'avg_grounded_rate': avg_grounded,
        }
    }
    
    output_path = ROOT / 'data' / 'research' / 'phase2a_eval.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n结果已保存: {output_path}")
    
    return output


if __name__ == '__main__':
    run_eval()