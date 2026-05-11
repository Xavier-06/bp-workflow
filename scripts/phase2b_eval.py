#!/usr/bin/env python3
"""
Phase 2B 评测 - 结构化市场数据
valuation_check × 3 + market_snapshot × 3

注意: tasks.valuation_check 和 tasks.market_snapshot 模块为可选依赖，
      缺失时对应评测部分将自动跳过。
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from tasks.valuation_check import run_valuation_check
except ImportError:
    run_valuation_check = None

try:
    from tasks.market_snapshot import run_market_snapshot
except ImportError:
    run_market_snapshot = None

# Fixtures
VALUATION_FIXTURES = [
    {'name': 'valuation_check_nvidia', 'entity': '英伟达'},
    {'name': 'valuation_check_apple', 'entity': 'Apple'},
    {'name': 'valuation_check_microsoft', 'entity': '微软'},
]

SNAPSHOT_FIXTURES = [
    {'name': 'market_snapshot_tesla', 'entity': '特斯拉'},
    {'name': 'market_snapshot_google', 'entity': 'Google'},
    {'name': 'market_snapshot_meta', 'entity': 'Meta'},
]


def run_eval():
    """运行评测"""
    print("=" * 70)
    print("Phase 2B 评测 - 结构化市场数据")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 检查 yfinance
    try:
        import yfinance
        print(f"yfinance: {yfinance.__version__} ✅")
    except ImportError:
        print("yfinance: 未安装 ❌")
        print("请运行: pip install yfinance")
        return None
    
    results = []
    
    # A. Valuation Check
    print("\n" + "=" * 70)
    print("A. Valuation Check")
    print("=" * 70)
    
    if run_valuation_check is None:
        print("⚠️ tasks.valuation_check 模块不可用，跳过")
    else:
        for i, fixture in enumerate(VALUATION_FIXTURES):
            print(f"\n[{i+1}/{len(VALUATION_FIXTURES)}] {fixture['name']}")
            print("-" * 50)
            
            start = time.time()
            result_obj = run_valuation_check(fixture['entity'])
            elapsed = time.time() - start
            
            result = {
                'name': fixture['name'],
                'task_type': 'valuation_check',
                'entity': fixture['entity'],
                'ticker': result_obj.ticker,
                'success': result_obj.success,
                'elapsed': round(elapsed, 2),
            }
            
            if result_obj.valuation_view:
                vv = result_obj.valuation_view
                result['fields_present'] = vv.fields_present
                result['fields_missing'] = vv.fields_missing
                result['as_of'] = vv.as_of
                result['source'] = vv.source
                result['summary'] = vv.get_summary()
                result['caveats_count'] = len(vv.caveats)
            else:
                result['fields_present'] = []
                result['fields_missing'] = ['ticker_not_found']
                result['summary'] = result_obj.summary
            
            # 验收
            has_ticker = bool(result['ticker'])
            has_price = 'price' in result.get('fields_present', [])
            has_pe_or_ps = 'pe_ratio' in result.get('fields_present', []) or 'ps_ratio' in result.get('fields_present', [])
            
            if has_ticker and has_price and has_pe_or_ps:
                result['status'] = 'PASS'
                print(f"  ✅ PASS")
            elif has_ticker and has_price:
                result['status'] = 'PARTIAL'
                print(f"  ⚠️ PARTIAL")
            else:
                result['status'] = 'FAIL'
                print(f"  ❌ FAIL")
            
            print(f"     ticker={result['ticker']}, fields={result.get('fields_present', [])}")
            print(f"     missing={result.get('fields_missing', [])}")
            print(f"     summary: {result.get('summary', 'N/A')[:60]}")
            
            results.append(result)
    
    # B. Market Snapshot
    print("\n" + "=" * 70)
    print("B. Market Snapshot")
    print("=" * 70)
    
    if run_market_snapshot is None:
        print("⚠️ tasks.market_snapshot 模块不可用，跳过")
    else:
        for i, fixture in enumerate(SNAPSHOT_FIXTURES):
            print(f"\n[{i+1}/{len(SNAPSHOT_FIXTURES)}] {fixture['name']}")
            print("-" * 50)
            
            start = time.time()
            result_obj = run_market_snapshot(fixture['entity'])
            elapsed = time.time() - start
            
            result = {
                'name': fixture['name'],
                'task_type': 'market_snapshot',
                'entity': fixture['entity'],
                'ticker': result_obj.ticker,
                'exchange': result_obj.exchange,
                'success': result_obj.success,
                'elapsed': round(elapsed, 2),
                'fields_present': result_obj.fields_present,
                'fields_missing': result_obj.fields_missing,
                'as_of': result_obj.as_of,
                'source': result_obj.source,
            }
            
            # 验收
            has_ticker = bool(result['ticker'])
            has_price = 'price' in result['fields_present']
            has_volume_or_52w = 'volume' in result['fields_present'] or '52w_high' in result['fields_present']
            
            if has_ticker and has_price and has_volume_or_52w:
                result['status'] = 'PASS'
                print(f"  ✅ PASS")
            elif has_ticker and has_price:
                result['status'] = 'PARTIAL'
                print(f"  ⚠️ PARTIAL")
            else:
                result['status'] = 'FAIL'
                print(f"  ❌ FAIL")
            
            print(f"     ticker={result['ticker']}, exchange={result['exchange']}")
            print(f"     fields={result['fields_present']}, missing={result['fields_missing']}")
            
            results.append(result)
    
    if not results:
        print("\n⚠️ 无评测模块可用，退出")
        return None
    
    # 汇总
    print("\n" + "=" * 70)
    print("评测汇总")
    print("=" * 70)
    
    valuation_results = [r for r in results if r['task_type'] == 'valuation_check']
    snapshot_results = [r for r in results if r['task_type'] == 'market_snapshot']
    
    print("\n## Valuation Check")
    for r in valuation_results:
        status = '✅' if r['status'] == 'PASS' else ('⚠️' if r['status'] == 'PARTIAL' else '❌')
        print(f"  {status} {r['name']}: ticker={r['ticker']}, fields={len(r.get('fields_present', []))}")
    
    print("\n## Market Snapshot")
    for r in snapshot_results:
        status = '✅' if r['status'] == 'PASS' else ('⚠️' if r['status'] == 'PARTIAL' else '❌')
        print(f"  {status} {r['name']}: ticker={r['ticker']}, fields={len(r.get('fields_present', []))}")
    
    # 统计
    pass_count = sum(1 for r in results if r['status'] == 'PASS')
    partial_count = sum(1 for r in results if r['status'] == 'PARTIAL')
    fail_count = sum(1 for r in results if r['status'] == 'FAIL')
    
    print(f"\n## 统计")
    print(f"  PASS: {pass_count}/{len(results)}")
    print(f"  PARTIAL: {partial_count}/{len(results)}")
    print(f"  FAIL: {fail_count}/{len(results)}")
    
    # 最终判断
    print("\n" + "=" * 70)
    print("最终判断")
    print("=" * 70)
    
    if pass_count == len(results):
        print("✅ 已完成可验收的 Phase 2B")
    elif pass_count >= 4 and fail_count == 0:
        print("⚠️ 已进入\"高可信研究 + 市场数据核验\"阶段（Phase 2B in progress）")
    else:
        print("❌ Phase 2B 尚在结构化数据接入阶段")
    
    # 保存
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'results': results,
        'summary': {
            'pass': pass_count,
            'partial': partial_count,
            'fail': fail_count,
        }
    }
    
    output_path = ROOT / 'data' / 'research' / 'phase2b_eval.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n结果已保存: {output_path}")
    
    return output


if __name__ == '__main__':
    run_eval()
