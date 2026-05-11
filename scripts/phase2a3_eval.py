#!/usr/bin/env python3
"""
Phase 2A.3 评测 - OpenAI blocker 修复
只跑 4 个关键 fixtures
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

# 只跑 4 个关键 fixtures
TEST_FIXTURES = [
    # market_news
    {'name': 'market_news_openai', 'task_type': 'market_news', 'query': 'OpenAI 最近新闻', 'entity': 'OpenAI'},
    {'name': 'market_news_google', 'task_type': 'market_news', 'query': 'Google 最近新闻', 'entity': 'Google'},
    {'name': 'market_news_meta', 'task_type': 'market_news', 'query': 'Meta 最近新闻', 'entity': 'Meta'},
    # company_research
    {'name': 'company_research_microsoft', 'task_type': 'company_research', 'query': '研究微软', 'entity': '微软'},
]


def run_eval():
    """运行评测"""
    print("=" * 70)
    print("Phase 2A.3 评测 - OpenAI Blocker 修复")
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
    
    runner = ResearchRunner()
    memo_builder = MemoBuilder()
    
    results = []
    
    for i, fixture in enumerate(TEST_FIXTURES):
        print(f"\n[{i+1}/{len(TEST_FIXTURES)}] {fixture['name']}")
        print("-" * 50)
        
        start = time.time()
        try:
            state = runner.run(
                task_type=fixture['task_type'],
                query=fixture['query'],
                entity=fixture.get('entity'),
            )
            
            memo = memo_builder.build(state)
            elapsed = time.time() - start
            
            path_state = state.source_path_state
            
            result = {
                'name': fixture['name'],
                'task_type': fixture['task_type'],
                'latency': round(elapsed, 2),
                'tavily_request_delta': state.runner_stats.tavily_request_delta,
                
                # Phase 2A.3 核心指标
                'profile_hit': path_state.profile_hit,
                'official_path_used': path_state.official_path_used,
                'feed_path_used': path_state.feed_path_used,
                'browser_fallback_used': getattr(path_state, 'browser_fallback_used', False),
                'search_fallback_used': path_state.search_fallback_used,
                'direct_url_fetch_count': path_state.direct_url_fetch_count,
                'feed_hit_count': path_state.feed_hit_count,
                
                'official_evidence_count': state.runner_stats.official_evidence_count,
                'primary_source_count': state.runner_stats.primary_source_count,
                'aggregator_count': state.runner_stats.aggregator_count,
                
                'secondary_only_flag': state.secondary_only_flag,
                'kept_count': len(state.all_evidence),
                'key_findings_count': len(memo.key_findings),
                'grounded_rate': memo.grounded_rate,
                'source_families_seen': state.source_families_seen,
            }
            
            # 验收判断
            has_official = result['official_evidence_count'] > 0
            has_primary = result['primary_source_count'] > 0
            has_findings = result['key_findings_count'] > 0
            
            if has_findings:
                result['status'] = 'PASS'
                print(f"  ✅ PASS")
            else:
                result['status'] = 'FAIL'
                print(f"  ❌ FAIL")
            
            print(f"     profile={path_state.profile_hit}, direct={path_state.direct_url_fetch_count}, browser_fb={result['browser_fallback_used']}")
            print(f"     official={result['official_evidence_count']}, primary={result['primary_source_count']}, aggregator={result['aggregator_count']}")
            print(f"     grounded={result['grounded_rate']:.0%}, search_fb={path_state.search_fallback_used}")
            
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
    
    # 重点检查 OpenAI
    openai_result = next((r for r in results if 'openai' in r['name'].lower()), None)
    
    if openai_result:
        grounded = openai_result.get('grounded_rate', 0)
        official = openai_result.get('official_evidence_count', 0)
        browser_fb = openai_result.get('browser_fallback_used', False)
        
        print(f"\n## OpenAI News 关键指标:")
        print(f"  grounded_rate: {grounded:.0%}")
        print(f"  official_evidence_count: {official}")
        print(f"  browser_fallback_used: {browser_fb}")
        print(f"  status: {openai_result.get('status', 'UNKNOWN')}")
    
    # 其他回归检查
    google_result = next((r for r in results if 'google' in r['name'].lower()), None)
    meta_result = next((r for r in results if 'meta' in r['name'].lower()), None)
    msft_result = next((r for r in results if 'microsoft' in r['name'].lower()), None)
    
    print(f"\n## 回归检查:")
    print(f"  Google news: {google_result.get('grounded_rate', 0):.0%} grounded" if google_result else "N/A")
    print(f"  Meta news: {meta_result.get('grounded_rate', 0):.0%} grounded" if meta_result else "N/A")
    print(f"  Microsoft: {msft_result.get('grounded_rate', 0):.0%} grounded" if msft_result else "N/A")
    
    # 最终判断
    print("\n" + "=" * 70)
    print("最终判断")
    print("=" * 70)
    
    if openai_result and openai_result.get('grounded_rate', 0) > 0:
        print("✅ 已完成可验收的 Phase 2A")
        print("   OpenAI news 已脱离 0% grounded")
    elif openai_result and openai_result.get('browser_fallback_used', False):
        print("⚠️ Phase 2A 主路径已完成，但仍有 1 个域名级 blocker 待处理")
        print("   OpenAI browser fallback 已启用但未能成功提取内容")
    else:
        print("❌ 仍停留在高可信研究阶段（Phase 2A in progress）")
        print("   OpenAI news 仍为 0% grounded")
    
    # 保存
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'results': results,
    }
    
    output_path = ROOT / 'data' / 'research' / 'phase2a3_eval.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n结果已保存: {output_path}")
    
    return output


if __name__ == '__main__':
    run_eval()