#!/usr/bin/env python3
"""
Research Agent 快速压测（轻量版）
单线程顺序执行，减少任务数
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

# 轻量级压测任务
QUICK_TASKS = [
    {'task_type': 'company_research', 'query': '研究腾讯', 'entity': '腾讯'},
    {'task_type': 'market_news', 'query': 'AI芯片新闻'},
    {'task_type': 'company_research', 'query': '研究苹果', 'entity': '苹果'},
    {'task_type': 'market_news', 'query': '美股市场动态'},
    {'task_type': 'company_research', 'query': '研究微软', 'entity': '微软'},
]


def run_task(task: dict, task_id: int) -> dict:
    """运行单个任务"""
    start = time.time()
    
    try:
        runner = ResearchRunner()
        state = runner.run(
            task_type=task['task_type'],
            query=task['query'],
            entity=task.get('entity'),
            max_rounds=1,  # 只跑 1 轮
        )
        
        elapsed = time.time() - start
        
        return {
            'task_id': task_id,
            'task_type': task['task_type'],
            'query': task['query'],
            'success': True,
            'elapsed': round(elapsed, 2),
            'evidence_count': len(state.all_evidence),
            'answered': len(state.completed_subquestions),
            'total_subquestions': len(state.plan.subquestions),
            'stop_reason': state.stop_reason,
        }
        
    except Exception as e:
        elapsed = time.time() - start
        return {
            'task_id': task_id,
            'task_type': task['task_type'],
            'query': task['query'],
            'success': False,
            'elapsed': round(elapsed, 2),
            'error': str(e),
        }


def main():
    print("="*60)
    print("Research Agent 快速压测")
    print("="*60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 检查 SearXNG
    import requests
    try:
        resp = requests.get('http://127.0.0.1:18080/healthz', timeout=5)
        if resp.text.strip() != 'OK':
            print("ERROR: SearXNG 不健康")
            return 1
        print("SearXNG: OK ✅")
    except Exception as e:
        print(f"ERROR: SearXNG 未运行 - {e}")
        return 1
    
    results = []
    total_start = time.time()
    
    for i, task in enumerate(QUICK_TASKS):
        print(f"\n[{i+1}/{len(QUICK_TASKS)}] {task['task_type']}: {task['query']}")
        
        result = run_task(task, i)
        results.append(result)
        
        if result['success']:
            print(f"  ✅ {result['elapsed']}s, {result['evidence_count']} evidence, {result['answered']}/{result['total_subquestions']} answered")
        else:
            print(f"  ❌ {result['elapsed']}s - {result['error'][:50]}")
    
    total_time = time.time() - total_start
    successful = [r for r in results if r['success']]
    
    # 汇总
    print("\n" + "="*60)
    print("压测结果汇总")
    print("="*60)
    print(f"总耗时: {total_time:.2f}s")
    print(f"成功率: {len(successful)}/{len(results)} ({len(successful)/len(results)*100:.1f}%)")
    
    if successful:
        avg_time = sum(r['elapsed'] for r in successful) / len(successful)
        avg_evidence = sum(r['evidence_count'] for r in successful) / len(successful)
        avg_answered = sum(r['answered'] for r in successful) / len(successful)
        print(f"平均耗时: {avg_time:.2f}s")
        print(f"平均 Evidence: {avg_evidence:.1f}")
        print(f"平均回答子问题: {avg_answered:.1f}")
    
    # 保存
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'total_time': total_time,
        'success_rate': len(successful) / len(results),
        'results': results,
    }
    
    output_path = ROOT / 'data' / 'research' / 'stress_test_quick.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n结果已保存: {output_path}")
    
    # 判断
    if len(successful) >= len(results) * 0.8:
        print("\n✅ 压测通过 (成功率 ≥ 80%)")
        return 0
    else:
        print("\n⚠️ 压测未通过 (成功率 < 80%)")
        return 1


if __name__ == '__main__':
    sys.exit(main())