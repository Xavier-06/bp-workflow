#!/usr/bin/env python3
"""
Subagent Retry Manager — 子代理派发与自动重试

解决：子代理超时后如何正确处理
原则：
1. 超时时 → 自动派发新子代理（最多重试 N 次）
2. 永远不编报告替代搜索
"""

import time
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError

# 子代理超时时间（秒）
SUBAGENT_TIMEOUT = 1200  # 20 分钟
MAX_RETRIES = 2

def spawn_with_retry(spawn_func, task_kwargs, timeout=SUBAGENT_TIMEOUT, max_retries=MAX_RETRIES):
    """
    带重试的子代理派发
    
    Args:
        spawn_func: sessions_spawn 函数
        task_kwargs: 任务参数
        timeout: 单次超时时间（秒）
        max_retries: 最大重试次数
    
    Returns:
        (success, result_dict)
    """
    for attempt in range(max_retries + 1):
        print(f"  🚀 [尝试 {attempt+1}/{max_retries+1}] 派发子代理（超时: {timeout}s）")
        try:
            # 用 ThreadPoolExecutor 实现超时
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(spawn_func, **task_kwargs)
                result = future.result(timeout=timeout)
                
                # 成功
                if result.get('status') in ['completed', 'success']:
                    print(f"  ✅ 子代理完成")
                    return True, result
                else:
                    print(f"  ⚠️ 子代理返回异常状态: {result.get('status')}")
                    raise Exception(f"子代理异常: {result.get('status')}")
        
        except TimeoutError:
            if attempt < max_retries:
                print(f"  ⏰ 超时，正在重新派发...")
            else:
                print(f"  ❌ 超时，已重试 {max_retries} 次，均失败")
                return False, {'status': 'timeout', 'attempts': attempt + 1}
        
        except Exception as e:
            if attempt < max_retries:
                print(f"  ⚠️ 异常: {e}，正在重新派发...")
            else:
                print(f"  ❌ 异常，已重试 {max_retries} 次: {e}")
                return False, {'status': 'error', 'error': str(e), 'attempts': attempt + 1}
        
        # 重试前等待
        if attempt < max_retries:
            time.sleep(5)
    
    return False, {'status': 'failed'}

def spawn_team_verification(company, founder):
    """
    团队验证子代理的 spawn 函数
    
    返回: {'status': 'completed', 'report': markdown_string, 'verification_results': dict}
    """
    # 这个函数应该调用 sessions_spawn 创建子代理
    # 这里先提供一个 search-based fallback
    from search_gateway import search
    
    verification = {
        'founder_verified': False,
        'team_verified': False,
        'company_verified': False,
        'search_results': {},
        'report': ''
    }
    
    # 生成搜索关键词
    queries = [
        f"{founder} {company} 创始人",
        f"{founder} 中山大学 教授",
        f"{company} 工商信息 天眼查 企查查",
    ]
    
    all_results = {}
    for q in queries:
        r = search(q, max_results=10)
        all_results[q] = r or []
        time.sleep(0.3)
    
    verification['search_results'] = {q: len(r) for q, r in all_results.items()}
    
    # 判断搜索结果
    if any(len(r) > 0 for r in all_results.values()):
        verification['founder_verified'] = True
    
    # 生成报告
    report_lines = [
        "# 团队与合规验证报告",
        f"## 搜索验证结果",
        f"### 公司: {company}",
        f"### 创始人: {founder}",
    ]
    
    for query, results in all_results.items():
        if results:
            report_lines.append(f"\n### ✅ {query}")
            report_lines.append(f"搜索到 {len(results)} 条结果:")
            for i, r in enumerate(results[:3], 1):
                report_lines.append(f"{i}. {r.get('title', '')} — {r.get('url', '')}")
        else:
            report_lines.append(f"\n### ❌ {query}")
            report_lines.append("搜索无结果")
    
    verification['report'] = '\n'.join(report_lines)
    verification['status'] = 'completed'
    
    return verification

def test_retry_logic():
    """测试重试逻辑"""
    print("测试 1: 正常情况")
    def success_func(**kwargs):
        return {'status': 'completed', 'data': 'test'}
    
    success, result = spawn_with_retry(success_func, {})
    print(f"  结果: {success}, {result}")
    
    print("\n测试 2: 超时情况")
    def timeout_func(**kwargs):
        time.sleep(3)
        return {'status': 'completed'}
    
    success, result = spawn_with_retry(timeout_func, {}, timeout=1, max_retries=2)
    print(f"  结果: {success}, {result}")
    
    return success

if __name__ == '__main__':
    test_retry_logic()
