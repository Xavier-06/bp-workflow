#!/usr/bin/env python3
"""
Research Agent 压力测试
- 并发压力
- 快速连续请求
- 混合任务类型
- 错误容忍
"""

import json
import sys
import time
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import random

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.planner import ResearchPlanner
from research.runner import ResearchRunner
from search.adapters.searxng import SearXNGAdapter
from search.models import Evidence


# 压测配置
STRESS_CONFIG = {
    'concurrent_tasks': 5,       # 同时运行的任务数
    'total_tasks': 20,           # 总任务数
    'task_interval': 0.1,        # 任务间隔（秒）
    'timeout_per_task': 120,     # 单任务超时
}

# 测试任务集（混合类型）
STRESS_TASKS = [
    {'task_type': 'company_research', 'query': '研究阿里巴巴', 'entity': '阿里巴巴'},
    {'task_type': 'company_research', 'query': '研究英伟达', 'entity': '英伟达'},
    {'task_type': 'company_research', 'query': '研究特斯拉', 'entity': '特斯拉'},
    {'task_type': 'company_research', 'query': '研究腾讯', 'entity': '腾讯'},
    {'task_type': 'company_research', 'query': '研究苹果', 'entity': '苹果'},
    {'task_type': 'company_research', 'query': '研究微软', 'entity': '微软'},
    {'task_type': 'company_research', 'query': '研究谷歌', 'entity': '谷歌'},
    {'task_type': 'company_research', 'query': '研究亚马逊', 'entity': '亚马逊'},
    {'task_type': 'company_research', 'query': '研究Meta', 'entity': 'Meta'},
    {'task_type': 'company_research', 'query': '研究Netflix', 'entity': 'Netflix'},
    {'task_type': 'market_news', 'query': 'AI芯片最新动态'},
    {'task_type': 'market_news', 'query': '美联储最新政策'},
    {'task_type': 'market_news', 'query': '中国科技股新闻'},
    {'task_type': 'market_news', 'query': '加密货币市场新闻'},
    {'task_type': 'market_news', 'query': '全球股市最新动态'},
    {'task_type': 'market_news', 'query': '电动汽车行业新闻'},
    {'task_type': 'market_news', 'query': '半导体行业新闻'},
    {'task_type': 'market_news', 'query': '云计算市场新闻'},
    {'task_type': 'market_news', 'query': '元宇宙最新进展'},
    {'task_type': 'market_news', 'query': '人工智能监管新闻'},
]


def run_single_task(task: dict, task_id: int) -> dict:
    """运行单个研究任务"""
    start_time = time.time()
    
    try:
        runner = ResearchRunner()
        state = runner.run(
            task_type=task['task_type'],
            query=task['query'],
            entity=task.get('entity'),
            max_rounds=2,  # 压测时限制轮数
        )
        
        elapsed = time.time() - start_time
        
        return {
            'task_id': task_id,
            'task_type': task['task_type'],
            'query': task['query'],
            'success': True,
            'elapsed_seconds': round(elapsed, 2),
            'rounds_used': state.rounds_used,
            'stop_reason': state.stop_reason,
            'evidence_count': len(state.all_evidence),
            'answered_subquestions': len(state.completed_subquestions),
            'total_subquestions': len(state.plan.subquestions),
            'error': None,
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            'task_id': task_id,
            'task_type': task['task_type'],
            'query': task['query'],
            'success': False,
            'elapsed_seconds': round(elapsed, 2),
            'error': str(e),
        }


def stress_test_concurrent():
    """并发压测"""
    print("\n" + "="*60)
    print("并发压力测试")
    print("="*60)
    print(f"配置: {STRESS_CONFIG['concurrent_tasks']} 并发, 共 {STRESS_CONFIG['total_tasks']} 任务")
    
    results = []
    start_time = time.time()
    
    # 随机选择任务
    tasks = random.sample(STRESS_TASKS, min(STRESS_CONFIG['total_tasks'], len(STRESS_TASKS)))
    if len(tasks) < STRESS_CONFIG['total_tasks']:
        tasks = tasks * (STRESS_CONFIG['total_tasks'] // len(tasks) + 1)
        tasks = tasks[:STRESS_CONFIG['total_tasks']]
    
    with ThreadPoolExecutor(max_workers=STRESS_CONFIG['concurrent_tasks']) as executor:
        futures = {}
        for i, task in enumerate(tasks):
            future = executor.submit(run_single_task, task, i)
            futures[future] = i
            time.sleep(STRESS_CONFIG['task_interval'])
        
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            
            status = "✅" if result['success'] else "❌"
            elapsed = result['elapsed_seconds']
            print(f"  {status} Task {result['task_id']:2d}: {result['task_type']:20s} - {result['query'][:25]:25s} ({elapsed}s)")
    
    total_time = time.time() - start_time
    
    # 统计
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    
    avg_time = sum(r['elapsed_seconds'] for r in successful) / len(successful) if successful else 0
    avg_evidence = sum(r['evidence_count'] for r in successful) / len(successful) if successful else 0
    avg_answered = sum(r['answered_subquestions'] for r in successful) / len(successful) if successful else 0
    
    print("\n" + "-"*60)
    print("并发压测结果:")
    print(f"  总耗时: {total_time:.2f}s")
    print(f"  成功率: {len(successful)}/{len(results)} ({len(successful)/len(results)*100:.1f}%)")
    print(f"  平均耗时: {avg_time:.2f}s")
    print(f"  平均 Evidence: {avg_evidence:.1f}")
    print(f"  平均回答子问题: {avg_answered:.1f}")
    
    if failed:
        print(f"\n失败任务 ({len(failed)}):")
        for r in failed:
            print(f"  ❌ Task {r['task_id']}: {r['error'][:50]}")
    
    return {
        'test_type': 'concurrent',
        'total_time': total_time,
        'success_rate': len(successful) / len(results),
        'avg_time': avg_time,
        'avg_evidence': avg_evidence,
        'results': results,
    }


def stress_test_rapid_fire():
    """快速连续压测（无间隔）"""
    print("\n" + "="*60)
    print("快速连续压测")
    print("="*60)
    print(f"配置: 10 个任务，无间隔快速执行")
    
    results = []
    start_time = time.time()
    
    tasks = random.sample(STRESS_TASKS, 10)
    
    for i, task in enumerate(tasks):
        print(f"  Task {i+1}/10: {task['task_type'][:15]:15s} - {task['query'][:20]:20s} ...", end='', flush=True)
        result = run_single_task(task, i)
        results.append(result)
        
        status = "✅" if result['success'] else "❌"
        elapsed = result['elapsed_seconds']
        print(f" {status} ({elapsed}s)")
    
    total_time = time.time() - start_time
    
    successful = [r for r in results if r['success']]
    
    print("\n" + "-"*60)
    print("快速连续压测结果:")
    print(f"  总耗时: {total_time:.2f}s")
    print(f"  成功率: {len(successful)}/{len(results)} ({len(successful)/len(results)*100:.1f}%)")
    print(f"  平均耗时: {sum(r['elapsed_seconds'] for r in successful) / len(successful):.2f}s")
    
    return {
        'test_type': 'rapid_fire',
        'total_time': total_time,
        'success_rate': len(successful) / len(results),
        'results': results,
    }


def check_searxng_health():
    """检查 SearXNG 健康"""
    import requests
    try:
        resp = requests.get('http://127.0.0.1:18080/healthz', timeout=5)
        if resp.text.strip() == 'OK':
            return True
    except:
        pass
    return False


def main():
    print("="*60)
    print("Research Agent 压力测试")
    print("="*60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 检查 SearXNG
    if not check_searxng_health():
        print("ERROR: SearXNG 未运行")
        print("请先启动: cd tools/searxng && ./start.sh")
        return 1
    
    print("SearXNG: OK ✅")
    
    all_results = []
    
    # 1. 快速连续压测
    result1 = stress_test_rapid_fire()
    all_results.append(result1)
    
    # 等待一下
    print("\n等待 5 秒...")
    time.sleep(5)
    
    # 2. 并发压测
    result2 = stress_test_concurrent()
    all_results.append(result2)
    
    # 汇总
    print("\n" + "="*60)
    print("压测汇总")
    print("="*60)
    
    for r in all_results:
        print(f"\n{r['test_type']}:")
        print(f"  成功率: {r['success_rate']*100:.1f}%")
        print(f"  总耗时: {r['total_time']:.2f}s")
    
    # 保存结果
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'tests': all_results,
    }
    
    output_path = ROOT / 'data' / 'research' / 'stress_test_results.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n结果已保存: {output_path}")
    
    # 判断通过
    all_success = all(r['success_rate'] >= 0.8 for r in all_results)
    if all_success:
        print("\n🎉 压测通过！成功率 ≥ 80%")
        return 0
    else:
        print("\n⚠️ 压测未通过，成功率 < 80%")
        return 1


if __name__ == '__main__':
    sys.exit(main())