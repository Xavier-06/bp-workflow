#!/usr/bin/env python3
"""
market_news metrics 报告生成器
生成 pass_rate_by_fixture, trusted_domain_kept_rate, top_drop_reasons 等指标
"""

import json
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
METRICS_PATH = ROOT / 'data' / 'search_gateway' / 'metrics.json'
REGRESSION_PATH = ROOT / 'data' / 'search_gateway' / 'regression_results.json'
FIXTURES_DIR = ROOT / 'config' / 'search' / 'fixtures'


def load_metrics() -> dict:
    if METRICS_PATH.exists():
        return json.loads(METRICS_PATH.read_text(encoding='utf-8'))
    return {}


def load_regression_results() -> dict:
    if REGRESSION_PATH.exists():
        return json.loads(REGRESSION_PATH.read_text(encoding='utf-8'))
    return {}


def generate_report() -> dict:
    """生成 market_news 专项 metrics 报告"""
    metrics = load_metrics()
    regression = load_regression_results()
    
    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'summary': {
            'total_provider_requests': sum(metrics.get('provider_request_count', {}).values()),
            'total_kept_count': metrics.get('kept_count', 0),
            'healthcheck_pass': metrics.get('healthcheck', {}).get('pass', 0),
            'healthcheck_fail': metrics.get('healthcheck', {}).get('fail', 0),
        },
        'drop_analysis': {
            'top_drop_reasons': _get_top_drop_reasons(metrics, 10),
            'drop_reason_percentages': _get_drop_percentages(metrics),
        },
        'provider_stats': {
            'request_count': metrics.get('provider_request_count', {}),
            'query_result_count': metrics.get('query_result_count', {}),
            'fallback_usage': metrics.get('fallback', {}),
        },
        'fixture_results': _analyze_fixtures(regression),
        'recommendations': [],
    }
    
    # 生成建议
    report['recommendations'] = _generate_recommendations(report)
    
    return report


def _get_top_drop_reasons(metrics: dict, limit: int = 10) -> list[tuple[str, int]]:
    drop_reasons = metrics.get('drop_reason', {})
    return sorted(drop_reasons.items(), key=lambda x: x[1], reverse=True)[:limit]


def _get_drop_percentages(metrics: dict) -> dict[str, float]:
    drop_reasons = metrics.get('drop_reason', {})
    total = sum(drop_reasons.values())
    if total == 0:
        return {}
    return {k: round(v / total * 100, 1) for k, v in drop_reasons.items()}


def _analyze_fixtures(regression: dict) -> dict:
    """分析 fixture 回归测试结果"""
    summaries = regression.get('summaries', [])
    if not summaries:
        return {'status': 'no_data', 'fixtures': []}
    
    fixtures = []
    for s in summaries:
        fixture = {
            'name': s.get('fixture_name', 'unknown'),
            'pass_rate': s.get('pass_rate', '0/0'),
            'passed': s.get('passed', False),
            'expected_min_kept': s.get('expected_min_kept', 0),
            'kept_counts': s.get('kept_counts', []),
            'avg_kept': round(sum(s.get('kept_counts', [0])) / max(len(s.get('kept_counts', [1])), 1), 2),
            'all_kept_domains': s.get('all_kept_domains', [])[:5],
        }
        fixtures.append(fixture)
    
    overall_passed = regression.get('overall_passed', False)
    
    return {
        'status': 'passed' if overall_passed else 'failed',
        'overall_passed': overall_passed,
        'fixtures': fixtures,
        'pass_rate_by_fixture': {
            f['name']: f['pass_rate'] for f in fixtures
        },
    }


def _generate_recommendations(report: dict) -> list[str]:
    """基于 metrics 生成改进建议"""
    recommendations = []
    
    drop_analysis = report.get('drop_analysis', {})
    top_drops = drop_analysis.get('top_drop_reasons', [])
    
    if not top_drops:
        recommendations.append('无数据，请先运行回归测试')
        return recommendations
    
    # 分析主要问题
    top_reason, top_count = top_drops[0] if top_drops else ('', 0)
    drop_pcts = drop_analysis.get('drop_reason_percentages', {})
    
    if top_reason == 'untrusted_news_source':
        recommendations.append('主要损耗：untrusted_news_source，建议扩展 trusted_news_domains 白名单')
    elif top_reason == 'too_old':
        recommendations.append('主要损耗：too_old，建议增加 freshness_hours 或放宽时间限制')
    elif top_reason == 'missing_publish_time':
        recommendations.append('主要损耗：missing_publish_time，建议改进时间推断规则')
    elif top_reason == 'thin_content':
        recommendations.append('主要损耗：thin_content，建议降低 min_content_length 阈值')
    elif top_reason == 'fetch_failed':
        recommendations.append('主要损耗：fetch_failed，建议检查网络或增加重试机制')
    
    # 检查 fixture 通过率
    fixture_results = report.get('fixture_results', {})
    if fixture_results.get('status') == 'failed':
        failed_fixtures = [f for f in fixture_results.get('fixtures', []) if not f.get('passed')]
        if failed_fixtures:
            recommendations.append(f'未通过 fixture: {", ".join(f["name"] for f in failed_fixtures)}')
    
    return recommendations


def print_report(report: dict) -> None:
    """打印人类可读的报告"""
    print("=" * 60)
    print("market_news METRICS REPORT")
    print(f"Generated: {report['generated_at']}")
    print("=" * 60)
    
    # Summary
    print("\n📊 SUMMARY")
    print("-" * 40)
    summary = report['summary']
    print(f"  Total provider requests: {summary['total_provider_requests']}")
    print(f"  Total kept count: {summary['total_kept_count']}")
    print(f"  Healthcheck: {summary['healthcheck_pass']} pass / {summary['healthcheck_fail']} fail")
    
    # Drop Analysis
    print("\n📉 DROP ANALYSIS")
    print("-" * 40)
    print("  Top drop reasons:")
    for reason, count in report['drop_analysis']['top_drop_reasons'][:5]:
        pct = report['drop_analysis']['drop_reason_percentages'].get(reason, 0)
        print(f"    - {reason}: {count} ({pct}%)")
    
    # Provider Stats
    print("\n🔌 PROVIDER STATS")
    print("-" * 40)
    provider = report['provider_stats']
    print(f"  Request count: {provider['request_count']}")
    print(f"  Fallback usage: used={provider['fallback_usage'].get('used', 0)}, not_used={provider['fallback_usage'].get('not_used', 0)}")
    
    # Fixture Results
    print("\n🧪 FIXTURE RESULTS")
    print("-" * 40)
    fixture = report['fixture_results']
    print(f"  Status: {fixture['status']}")
    if fixture['fixtures']:
        for f in fixture['fixtures']:
            status = "✅" if f['passed'] else "❌"
            print(f"    {status} {f['name']}: pass_rate={f['pass_rate']}, avg_kept={f['avg_kept']}")
    
    # Recommendations
    print("\n💡 RECOMMENDATIONS")
    print("-" * 40)
    for rec in report['recommendations']:
        print(f"  • {rec}")
    
    print("\n" + "=" * 60)


def main():
    report = generate_report()
    print_report(report)
    
    # 保存报告
    output_path = ROOT / 'data' / 'search_gateway' / 'market_news_metrics_report.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nReport saved to: {output_path}")


if __name__ == '__main__':
    main()