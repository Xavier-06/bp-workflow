#!/usr/bin/env python3
"""
Phase 1 最终验收评测 - Tavily 隔离版
确保：
- tavily_request_delta == 0
- provider_used == searxng
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Phase 1 检查：确保没有 Tavily
from search.gateway import PHASE1_PROVIDER_WHITELIST, get_gateway

# 验证 Phase 1 配置
gateway = get_gateway()
registered_providers = gateway.get_registered_providers()
assert 'tavily' not in registered_providers, f"Phase 1 violation: tavily is registered! providers={registered_providers}"
assert gateway.is_phase1_compliant(), "Phase 1 violation: gateway not compliant"

print("=" * 70)
print("Phase 1 配置检查")
print("=" * 70)
print(f"✅ Tavily 未注册")
print(f"✅ 已注册 providers: {registered_providers}")
print(f"✅ 白名单: {PHASE1_PROVIDER_WHITELIST}")

from research.runner import ResearchRunner
from research.memo_builder import MemoBuilder

# 记录初始 metrics
metrics_path = ROOT / 'data' / 'search_gateway' / 'metrics.json'
initial_metrics = {}
if metrics_path.exists():
    initial_metrics = json.loads(metrics_path.read_text(encoding='utf-8'))
initial_tavily_count = initial_metrics.get('provider_request_count', {}).get('tavily', 0)
initial_searxng_count = initial_metrics.get('provider_request_count', {}).get('searxng', 0)

print(f"\n初始状态:")
print(f"  tavily requests: {initial_tavily_count}")
print(f"  searxng requests: {initial_searxng_count}")

# 6 个 fixtures
FIXTURES = [
    {'name': 'company_research_alibaba', 'task_type': 'company_research', 'query': '研究阿里巴巴', 'entity': '阿里巴巴', 'market': 'hk'},
    {'name': 'company_research_tencent', 'task_type': 'company_research', 'query': '研究腾讯', 'entity': '腾讯', 'market': 'hk'},
    {'name': 'company_research_nvidia', 'task_type': 'company_research', 'query': '研究英伟达', 'entity': '英伟达', 'market': 'us'},
    {'name': 'market_news_openai', 'task_type': 'market_news', 'query': 'OpenAI 最近新闻', 'entity': 'OpenAI'},
    {'name': 'market_news_google', 'task_type': 'market_news', 'query': 'Google 最近新闻', 'entity': 'Google'},
    {'name': 'market_news_tesla', 'task_type': 'market_news', 'query': '特斯拉最近新闻', 'entity': '特斯拉'},
]


def run_eval():
    """运行评测"""
    print("\n" + "=" * 70)
    print("Phase 1 最终验收评测")
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
    
    for i, fixture in enumerate(FIXTURES):
        print(f"\n[{i+1}/{len(FIXTURES)}] {fixture['name']}")
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
                'urls_fetched_count': state.runner_stats.fetch_count,
                'kept_count': len(state.all_evidence),
                'answered_subquestions': len(state.completed_subquestions),
                'partially_answered': len(state.partially_answered_subquestions),
                'unanswered': len(state.unanswered_subquestions),
                'key_findings_count': len(memo.key_findings),
                'evidence_gaps_count': len(memo.evidence_gaps),
                'cited_evidence_count': len(memo.cited_evidence),
                'rounds_used': state.rounds_used,
                'stop_reason': state.stop_reason,
            }
            
            # Phase 1 检查
            assert result['tavily_request_delta'] == 0, f"Phase 1 violation: tavily_request_delta={result['tavily_request_delta']}"
            assert result['provider_used'] == 'searxng', f"Phase 1 violation: provider_used={result['provider_used']}"
            
            # 验收判断
            if fixture['task_type'] == 'company_research':
                has_findings_or_gaps = result['key_findings_count'] > 0 or result['evidence_gaps_count'] > 0
                answered_ok = result['answered_subquestions'] >= 3 or (result['answered_subquestions'] + result['partially_answered']) >= 3
                
                if has_findings_or_gaps and answered_ok:
                    result['status'] = 'PASS'
                    print(f"  ✅ PASS")
                else:
                    result['status'] = 'FAIL'
                    print(f"  ❌ FAIL")
            else:
                has_evidence = result['cited_evidence_count'] >= 1
                has_findings = result['key_findings_count'] >= 1
                
                if has_evidence and has_findings:
                    result['status'] = 'PASS'
                    print(f"  ✅ PASS")
                else:
                    result['status'] = 'FAIL'
                    print(f"  ❌ FAIL")
            
            print(f"     provider: {result['provider_used']}, tavily_delta: {result['tavily_request_delta']}")
            print(f"     {result['answered_subquestions']} answered, {result['partially_answered']} partial")
            print(f"     {result['key_findings_count']} findings, {result['evidence_gaps_count']} gaps")
            print(f"     urls_fetched: {result['urls_fetched_count']}, Latency: {result['latency']}s")
            
        except Exception as e:
            elapsed = time.time() - start
            result = {
                'name': fixture['name'],
                'task_type': fixture['task_type'],
                'latency': round(elapsed, 2),
                'status': 'ERROR',
                'error': str(e)[:100],
            }
            print(f"  ❌ ERROR: {str(e)[:50]}")
        
        results.append(result)
    
    # 检查 Tavily 是否被调用
    final_metrics = {}
    if metrics_path.exists():
        final_metrics = json.loads(metrics_path.read_text(encoding='utf-8'))
    final_tavily_count = final_metrics.get('provider_request_count', {}).get('tavily', 0)
    tavily_delta = final_tavily_count - initial_tavily_count
    
    print("\n" + "=" * 70)
    print("Tavily 隔离验证")
    print("=" * 70)
    print(f"  初始 tavily requests: {initial_tavily_count}")
    print(f"  最终 tavily requests: {final_tavily_count}")
    print(f"  tavily_request_delta: {tavily_delta}")
    
    if tavily_delta == 0:
        print("  ✅ Tavily 完全隔离")
    else:
        print("  ❌ Tavily 被调用！Phase 1 违规")
    
    # 汇总
    print("\n" + "=" * 70)
    print("评测汇总")
    print("=" * 70)
    
    company_results = [r for r in results if r.get('task_type') == 'company_research']
    news_results = [r for r in results if r.get('task_type') == 'market_news']
    
    print("\n## Company Research (3 fixtures)")
    for r in company_results:
        status_icon = {'PASS': '✅', 'FAIL': '❌', 'ERROR': '💥'}.get(r.get('status'), '?')
        print(f"  {status_icon} {r['name']}: {r.get('answered_subquestions', 0)} answered, {r.get('key_findings_count', 0)} findings, {r.get('evidence_gaps_count', 0)} gaps")
    
    print("\n## Market News (3 fixtures)")
    for r in news_results:
        status_icon = {'PASS': '✅', 'FAIL': '❌', 'ERROR': '💥'}.get(r.get('status'), '?')
        print(f"  {status_icon} {r['name']}: {r.get('cited_evidence_count', 0)} evidence, {r.get('key_findings_count', 0)} findings")
    
    # 最终判断
    pass_count = sum(1 for r in results if r.get('status') == 'PASS')
    fail_count = sum(1 for r in results if r.get('status') in ['FAIL', 'ERROR'])
    
    print("\n" + "=" * 70)
    print("最终判断")
    print("=" * 70)
    
    if tavily_delta != 0:
        print("❌ 仍停留在检索基础设施阶段（Tavily 未隔离）")
    elif fail_count > 0:
        print("❌ 仍停留在检索基础设施阶段（评测未通过）")
    elif pass_count == len(results):
        print("✅ 已达到可 sign-off 的 Deep Research Lite Phase 1")
    else:
        print("⚠️ 已进入最小研究代理 Alpha")
    
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'tavily_isolated': tavily_delta == 0,
        'tavily_request_delta': tavily_delta,
        'results': results,
        'summary': {
            'total': len(results),
            'pass': pass_count,
            'fail': fail_count,
        }
    }
    
    output_path = ROOT / 'data' / 'research' / 'phase1_final_eval.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n结果已保存: {output_path}")
    
    return output


if __name__ == '__main__':
    run_eval()