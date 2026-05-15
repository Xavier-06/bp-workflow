#!/usr/bin/env python3
"""
IR Subagent Launcher — 真正用 sessions_spawn 发射子代理的脚本

2026-04-05 修复：
  - Step 2/3/4/5 只依赖 step1 → 并行发射而非串行
  - Step 6 依赖 step2+3, step7 依赖 step3+4 → 分两波并行
  - Step 8 依赖全部 → 最后串行
  - 总耗时从 80 分钟降到 ~25 分钟

2026-04-04 升级：
  - 每个 step 写完后立刻做质量检查（来源可信度 + 内容完整性）
  - 低于阈值自动补搜 + 重写（最多 1 次重试）
  - 对标 Perplexity Deep Research：先写 → 自查 → 缺就补搜 → 重写

对话模式和自动化管线共用。每个 step 会：
1. 读取 instruction_store 里对应角色的指令
2. 生成 task brief（包含搜索结果、前置产物路径等）
3. 通过 openclaw agent 调用 sessions_spawn 创建真实 subagent
4. 写入 spawn receipt
5. 等待结果文件 → 质量检查 → 不达标则补搜重写
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'
INSTRUCTION_STORE = ROOT / 'instruction_store_ir'

# 质量线
STEP_QUALITY_THRESHOLD = 3

# Step 角色名
STEP_ROLE = {
    'step1_data': '投研_主笔_数据收集',
    'step2_industry': '投研_主笔_行业分析',
    'step3_biz': '投研_主笔_商业模式',
    'step4_finance': '投研_主笔_财务分析',
    'step5_mgmt': '投研_主笔_管理层',
    'step6_insight': '投研_主笔_差异化洞察',
    'step6b_valuation': '投研_主笔_预测与估值',
    'step7_risk': '投研_主笔_风险催化',
    'step8_master': '投研_主笔_文档汇总',
}

# 步间依赖关系（实际图结构）
STEP_DEPS = {
    'step1_data': [],
    'step2_industry': ['step1_data'],
    'step3_biz': ['step1_data'],
    'step4_finance': ['step1_data'],
    'step5_mgmt': ['step1_data'],
    'step6_insight': ['step1_data', 'step2_industry', 'step3_biz', 'step6b_valuation'],
    'step6b_valuation': ['step1_data', 'step2_industry', 'step4_finance'],
    'step7_risk': ['step1_data', 'step3_biz', 'step4_finance', 'step6b_valuation'],
    'step8_master': ['step1_data', 'step2_industry', 'step3_biz', 'step4_finance', 'step5_mgmt', 'step6_insight', 'step6b_valuation', 'step7_risk'],
}

# 并行发射波次（按依赖拓扑排序）
# Wave 1: step1（独立）
# Wave 2: step2,3,4,5（只依赖 step1 → 并行）
# Wave 3: step6,7（依赖 wave2 → 并行）
# Wave 4: step8（依赖全部 → 串行）
LAUNCH_WAVES = [
    ['step1_data'],
    ['step2_industry', 'step3_biz', 'step4_finance', 'step5_mgmt'],
    ['step6b_valuation'],
    ['step6_insight', 'step7_risk'],
    ['step8_master'],
]

# 超时
STEP_TIMEOUTS = {
    'step1_data': 900,
    'step2_industry': 900,
    'step3_biz': 900,
    'step4_finance': 900,
    'step5_mgmt': 900,
    'step6_insight': 900,
    'step6b_valuation': 900,
    'step7_risk': 900,
    'step8_master': 1800,
}

# Step 查询关键词（用于自动补搜）
_STEP_KEYWORDS = {
    'step1_data': 'stock price market cap PE ratio EPS dividend analyst rating 市值 股价 市盈率',
    'step2_industry': 'industry market size market share growth rate TAM penetration competitive landscape 行业规模 竞争格局',
    'step3_biz': 'business model product revenue customer supply chain 商业模式 产品线 客户 收入结构',
    'step4_finance': 'financial report revenue profit margin cash flow ROE debt 财报 营收 毛利率 净利润 现金流',
    'step5_mgmt': 'management board governance ownership ESG compensation 管理层 董事会 股权结构 治理',
    'step6_insight': 'catalyst valuation target price investment thesis risk-reward 催化剂 估值 目标价 投资亮点',
    'step6b_valuation': 'DCF valuation PE PB PS EV/EBITDA target price WACC comparable company valuation model 目标价 估值',
    'step7_risk': 'risk regulatory litigation competition macro threat 风险 监管 诉讼 竞争威胁 宏观',
    'step8_master': '',
}


def load_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return default


def step_output_path(task_id: str, step: str) -> Path:
    return TASKS_DIR / f'{task_id}-{step}.md'


def step_spawn_receipt_path(task_id: str, step: str) -> Path:
    return TASKS_DIR / f'{task_id}-spawn-receipt-{step}.json'


def step_result_path(task_id: str, step: str) -> Path:
    return TASKS_DIR / f'{task_id}-result-{step}.json'


def deps_ready(task_id: str, step: str) -> tuple[bool, list[str]]:
    """检查依赖步骤的输出文件是否已存在"""
    missing = []
    for dep in STEP_DEPS.get(step, []):
        if not step_output_path(task_id, dep).exists():
            missing.append(dep)
    return len(missing) == 0, missing


def load_instruction(role_key: str) -> str:
    """加载角色指令（instruction_store）"""
    instruction_map = {
        'step1_data': '投研_主笔_行情数据',
        'step2_industry': '投研_主笔_行业格局',
        'step3_biz': '投研_主笔_业务模式',
        'step4_finance': '投研_主笔_财务分析',
        'step5_mgmt': '投研_主笔_管理层',
        'step6_insight': '投研_主笔_差异化洞察',
        'step6b_valuation': '投研_主笔_预测与估值',
        'step7_risk': '投研_主笔_风险催化',
        'step8_master': '投研_主笔_文档汇总',
    }
    role_file = INSTRUCTION_STORE / f'{instruction_map.get(role_key, role_key)}.md'
    if role_file.exists():
        return role_file.read_text(encoding='utf-8')
    return f'Role instructions for {role_key} not found.'


def build_step_brief(task_id: str, step: str, entity: str = '', query: str = '') -> str:
    """构建子代理任务 brief"""
    role_key = step
    instruction = load_instruction(role_key)
    brief_lines = [
        f'# Step Brief: {STEP_ROLE.get(step, step)} ({step})',
        f'',
        f'Task: {task_id}',
        f'Entity: {entity}',
        f'Query: {query}',
        f'',
        f'## Role Instruction',
        f'',
        instruction,
        f'',
        f'## Pre-search Results',
        f'',
    ]
    
    # Attach pre-search results if available
    search_path = TASKS_DIR / f'{task_id}-search-{step}.md'
    if search_path.exists():
        brief_lines.append(search_path.read_text(encoding='utf-8'))
    else:
        brief_lines.append('_No pre-search results available._')
    
    # Attach prior step outputs if dependencies exist
    for dep in STEP_DEPS.get(step, []):
        dep_path = step_output_path(task_id, dep)
        if dep_path.exists():
            brief_lines.append(f'')
            brief_lines.append(f'## Prior Step Output: {dep}')
            brief_lines.append(f'')
            text = dep_path.read_text(encoding='utf-8')
            brief_lines.append(text[:5000])  # 截断
            brief_lines.append(f'')
            brief_lines.append(f'_（以上为 {dep} 的完整输出，截断显示前 5000 字符）_')
    
    return '\n'.join(brief_lines)


def _check_step_quality(task_id: str, step: str) -> dict:
    """单 step 质量评估 (0-5 分)"""
    output_path = step_output_path(task_id, step)
    if not output_path.exists():
        return {'score': 0, 'verdict': 'fail', 'issues': ['output file missing']}
    
    text = output_path.read_text(encoding='utf-8')
    content_len = len(text)
    urls = text.count('http')
    sections = text.count('## ')
    
    score = 0
    issues = []
    
    if content_len < 500:
        score = 0
        issues.append(f'内容过短 ({content_len} 字符)')
    elif content_len < 1000:
        score = 1
        issues.append(f'内容偏少 ({content_len} 字符)')
    elif content_len < 3000:
        score = 2
        issues.append(f'内容尚可 ({content_len} 字符)')
    elif content_len < 6000:
        score = 3
    elif content_len < 10000:
        score = 4
    else:
        score = 5
    
    if urls < 2:
        score = max(0, score - 1)
        issues.append(f'来源不足 ({urls} 个 URL)')
    
    if sections < 3:
        score = max(0, score - 1)
        issues.append(f'章节不足 ({sections} 个)')
    
    threshold = STEP_QUALITY_THRESHOLD
    
    return {
        'score': score,
        'content_length': content_len,
        'url_count': urls,
        'section_count': sections,
        'threshold': threshold,
        'verdict': 'pass' if score >= threshold else 'fail',
        'issues': issues,
    }


def _do_targeted_search(entity: str, step: str, market: str = 'us') -> str:
    """针对某个 step 做补搜，用完整实体名（截断问题修复）"""
    kw = _STEP_KEYWORDS.get(step, '')
    if not kw:
        return ''
    
    # 🔧 修复：始终使用完整实体名，不被截断
    query = f"{entity} {kw}".strip()
    memo_lines = []

    # 尝试 research API
    try:
        import sys
        sys.path.insert(0, str(ROOT / 'scripts'))
        from research.research_api import run_research
        r = run_research(query=query, entity=entity, market=market, max_rounds=2, snippet_only=True)
        memo = r.get('memo_markdown', '')
        if memo:
            memo_lines.append(f"## Research API 补搜结果\n\n{memo}")
    except Exception:
        pass

    # 如果 research API 没产出，尝试 search_gateway
    if not memo_lines:
        try:
            from scripts.search_gateway import search
            results = search(query, max_results=10)
            if results:
                memo_lines.append(f"## DDG 补搜结果 ({len(results)} 条)\n\n")
                for i, r in enumerate(results, 1):
                    memo_lines.append(f"### {i}. {r.get('title', '')}\n")
                    memo_lines.append(f"URL: {r.get('url', '')}\n")
                    memo_lines.append(f"{r.get('content', '')[:300]}\n\n")
        except Exception:
            pass

    return '\n'.join(memo_lines)


def _rewrite_step(task_id: str, step: str, entity: str, query: str,
                  quality: dict, market: str = 'us', timeout: int = 900) -> dict:
    """质量不达标 → 补搜 + 重写。"""
    step_name = STEP_ROLE.get(step, step)

    # 1. 补搜
    print(f"  🔍 补搜 ({step_name})...")
    memo = _do_targeted_search(entity, step, market)

    memo_path = TASKS_DIR / f'{task_id}-{step}-followup-research.md'
    if memo:
        memo_path.write_text(memo, encoding='utf-8')
        print(f"  📝 补搜结果已写入 {memo_path.name}")
    else:
        print(f"  ⚠ 补搜无结果，用已有内容重写")

    # 2. 重新写 brief
    brief = build_step_brief(task_id, step, entity, query)
    brief_path = TASKS_DIR / f'{task_id}-brief-{step}.md'
    
    # Append memo to brief
    rewrite_brief = brief
    if memo_path.exists():
        rewrite_brief += f'\n\n## 补充搜索笔记\n- 文件: `{memo_path}`\n- 必读其中内容\n'
    brief_path.write_text(rewrite_brief, encoding='utf-8')

    # 3. 清理旧输出
    output_path = step_output_path(task_id, step)
    receipt_path = step_spawn_receipt_path(task_id, step)
    for p in (output_path, receipt_path):
        if p.exists():
            p.unlink()

    # 4. Re-spawn
    step_info = launch_step(task_id, step, entity, query, timeout=timeout, dry_run=False, market=market)
    if step_info.get('status') != 'spawned':
        return {'status': 'rewrite_spawn_failed', 'error': (step_info.get('error', '') or '')[:500]}

    # 5. Wait
    wait_info = wait_for_output(task_id, step, timeout=timeout)
    
    if wait_info.get('status') != 'completed':
        return {'status': 'rewrite_output_timeout'}

    # 6. 重新质量检查
    new_quality = _check_step_quality(task_id, step)
    return {
        'status': 'rewrite_completed',
        'new_quality_report': new_quality,
        'steps': [step_info, wait_info],
    }


def build_step_brief(task_id: str, step: str, entity: str = '', query: str = '') -> str:
    """构建子代理任务 brief"""
    role_key = step
    instruction = load_instruction(role_key)
    
    brief_lines = [
        f'# Step Brief: {STEP_ROLE.get(step, step)} ({step})',
        f'',
        f'Task: {task_id}',
        f'Entity: {entity}',
        f'Query: {query}',
        f'',
        f'## Role Instruction',
        f'',
        instruction,
        f'',
        f'## Pre-search Results',
        f'',
    ]
    
    # Pre-search
    search_path = TASKS_DIR / f'{task_id}-search-{step}.md'
    if search_path.exists():
        brief_lines.append(search_path.read_text(encoding='utf-8'))
    else:
        brief_lines.append('_No pre-search results._')
    
    # Prior steps
    for dep in STEP_DEPS.get(step, []):
        dep_path = step_output_path(task_id, dep)
        if dep_path.exists():
            brief_lines.append(f'')
            brief_lines.append(f'## Prior Step Output: {dep}')
            brief_lines.append(f'')
            brief_lines.append(dep_path.read_text(encoding='utf-8')[:5000])
            brief_lines.append(f'_（完整 {dep} 输出，截断显示前 5000 字符）_')
    
    return '\n'.join(brief_lines)


def launch_step(task_id: str, step: str, entity: str = '', query: str = '',
                timeout: int = 900, dry_run: bool = False, market: str = 'us') -> dict:
    """启动单个子代理 step。"""
    output_path = step_output_path(task_id, step)
    receipt_path = step_spawn_receipt_path(task_id, step)
    result_path = step_result_path(task_id, step)

    # 检查依赖
    ready, missing = deps_ready(task_id, step)
    if not ready:
        return {
            'step': step,
            'status': 'blocked',
            'reason': f'Dependencies not ready: {missing}',
        }

    # 构建 brief
    brief = build_step_brief(task_id, step, entity, query)
    brief_path = TASKS_DIR / f'{task_id}-brief-{step}.md'
    brief_path.write_text(brief, encoding='utf-8')

    if dry_run:
        return {
            'step': step,
            'status': 'dry_run',
            'brief_path': str(brief_path),
            'output_path': str(output_path),
        }

    # 清理旧输出
    for p in (receipt_path, result_path):
        if p.exists():
            p.unlink()

    # 启动子代理
    label = f'{task_id}-{step}'
    rel_brief = str(brief_path.relative_to(ROOT))
    rel_output = str(output_path.relative_to(ROOT))

    child_task = (
        f'You are the {step} subagent for IR task {task_id}. '
        f'Read the brief at `{rel_brief}` and follow it exactly. '
        f'Write your output to `{rel_output}`. '
        f'Your output MUST include at least 3 source citations (URLs). '
        f'When done, stop. Do not modify other files.'
    )

    message = (
        f'Use the sessions_spawn tool exactly once with runtime "subagent", mode "run", cleanup "keep", '
        f'thinking "high", label "{label}", and task "{child_task}". '
        f'After the tool returns accepted, write a JSON file to `{str(receipt_path.relative_to(ROOT))}` containing keys '
        f'task_id, step, hook, label, status, runId, childSessionKey, runtime, thinking. '
        f'Set runtime to "subagent", thinking to "high". Then stop without waiting for child completion.'
    )

    cmd = [
        'openclaw', 'agent', '--agent', 'main',
        '--thinking', 'high', '--timeout', str(min(timeout, 120)), '--json',
        '--message', message,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    if proc.returncode != 0:
        return {
            'step': step,
            'status': 'spawn_failed',
            'error': (proc.stderr or proc.stdout or '')[:500],
        }

    # 验证 spawn receipt
    receipt = load_json(receipt_path, {})
    if not (isinstance(receipt, dict) and (receipt.get('childSessionKey') or receipt.get('runId'))):
        return {
            'step': step,
            'status': 'receipt_invalid',
            'error': f'Spawn receipt missing or invalid at {receipt_path}',
        }

    return {
        'step': step,
        'status': 'spawned',
        'label': label,
        'childSessionKey': receipt.get('childSessionKey'),
        'runId': receipt.get('runId'),
        'thinking': 'high',
        'brief_path': str(brief_path),
        'output_path': str(output_path),
        'receipt_path': str(receipt_path),
    }


def wait_for_output(task_id: str, step: str, timeout: int = 900, poll_interval: int = 15) -> dict:
    """等待 step 输出文件出现"""
    output_path = step_output_path(task_id, step)
    start = time.time()
    while time.time() - start < timeout:
        if output_path.exists() and output_path.stat().st_size > 100:
            return {
                'step': step,
                'status': 'completed',
                'output_path': str(output_path),
                'output_size': output_path.stat().st_size,
                'elapsed_s': int(time.time() - start),
            }
        time.sleep(poll_interval)
    return {
        'step': step,
        'status': 'timeout',
        'timeout_s': timeout,
        'elapsed_s': int(time.time() - start),
    }


MAX_SPAWN_RETRIES = 2  # 超时/失效后自动补发次数


def _spawn_retry_loop(task_id: str, step: str, entity: str, query: str, timeout: int, market: str, max_retries: int = MAX_SPAWN_RETRIES) -> tuple:
    """
    循环：发射 → 等待输出 → 超时则补发同样的任务（不补搜，原样重试）
    返回 (launch_result, wait_result, retry_count)
    retry_count 记录补发次数。
    """
    retry = 0
    step_name = STEP_ROLE.get(step, step)

    while retry <= max_retries:
        launch_result = launch_step(task_id, step, entity, query, timeout, market=market)
        wait_result = None

        if launch_result.get('status') == 'spawned':
            print(f"  ⏳ 等待 {step_name} 输出 (超时 {timeout}s)...")
            wait_result = wait_for_output(task_id, step, timeout)

            if wait_result.get('status') == 'completed':
                output_path = step_output_path(task_id, step)
                size_str = f"{output_path.stat().st_size:,} bytes" if output_path.exists() else "?"
                print(f"  ✅ {step_name} 完成 ({size_str})")
                return launch_result, wait_result, retry

            # 超时 → 补发，用同样的 brief 原样重试
            if retry < max_retries:
                retry += 1
                print(f"  ⏱  {step_name} 超时（{wait_result.get('elapsed_s', '?')}s），准备第 {retry} 次补发...")
                continue
            else:
                # 全部重试用完
                print(f"  ❌ {step_name} 超时，已补发 {max_retries} 次仍未产出输出")
                return launch_result, wait_result, retry

        else:
            # spawn 失败 → 补发（同样 brief 原样重试）
            if retry < max_retries:
                retry += 1
                err = (launch_result.get('error', '') or '')[:200]
                print(f"  ⚠ {step_name} spawn 失败 ({launch_result.get('status', '?')})，错误: {err}")
                print(f"     准备第 {retry} 次补发...")
                # 清理旧 receipt 让下次 spawn 不冲突
                receipt_path = step_spawn_receipt_path(task_id, step)
                if receipt_path.exists():
                    receipt_path.unlink()
                continue
            else:
                # 全部重试用完
                print(f"  ❌ {step_name} spawn 失败，已补发 {max_retries} 次仍未成功")
                wait_result = {'step': step, 'status': 'spawn_stuck'}
                return launch_result, wait_result, retry

    return launch_result, wait_result, retry


def launch_and_verify(task_id: str, step: str, entity: str = '', query: str = '',
                      timeout: int = 900, market: str = 'us', retries: int = 1) -> dict:
    """
    完整流程：
    1. 发射 → 等待输出（超时自动补发，最多 MAX_SPAWN_RETRIES 次）
    2. 产出文件后做质检
    3. 质检不达标则补搜 + 重写
    """
    results = []

    # --- 阶段1：发射 + 超时补发 ---
    launch_result, wait_result, spawn_retries = _spawn_retry_loop(
        task_id, step, entity, query, timeout, market
    )
    results.append(launch_result)
    if wait_result:
        results.append(wait_result)

    # spawn 彻底失败
    if wait_result and wait_result.get('status') == 'spawn_stuck':
        return {
            'step': step,
            'status': 'spawn_failed',
            'steps': results,
            'error': launch_result.get('error', 'spawn exhausted all retries'),
            'spawn_retries': spawn_retries,
        }

    # 等待输出超时
    if not wait_result or wait_result.get('status') != 'completed':
        return {
            'step': step,
            'status': 'output_timeout',
            'steps': results,
            'error': 'Output file not created after retries',
            'spawn_retries': spawn_retries,
        }

    # --- 阶段2：质检 ---
    quality = _check_step_quality(task_id, step)

    result = {
        'step': step,
        'status': 'completed',
        'quality_score': quality.get('score', 0),
        'quality_threshold': quality.get('threshold', STEP_QUALITY_THRESHOLD),
        'quality_passed': quality.get('verdict') == 'pass',
        'quality_report': quality,
        'steps': results,
        'retries_used': 0,
        'spawn_retries': spawn_retries,
    }

    if quality.get('verdict') == 'fail':
        print(f"  ❌ {STEP_ROLE.get(step, step)} 质量不达标: {quality.get('score', 0)}/{quality.get('threshold', STEP_QUALITY_THRESHOLD)}")
        print(f"     {' | '.join(quality.get('issues', [])[:3])}")

    # --- 阶段3：质检不达标 → 补搜重写 ---
    for retry in range(retries):
        if quality.get('score', 0) >= STEP_QUALITY_THRESHOLD:
            break

        print(f"  🔄 第 {retry + 1} 次重试: 补搜 + 重写")
        rewrite_result = _rewrite_step(task_id, step, entity, query, quality, market=market, timeout=timeout)
        results.append(rewrite_result)

        if 'new_quality_report' in rewrite_result:
            quality = rewrite_result['new_quality_report']

        result = {
            **result,
            'status': 'completed_with_retries' if rewrite_result.get('status') == 'rewrite_completed' else rewrite_result.get('status', 'retry_unknown'),
            'retries_used': retry + 1,
            'quality_report': rewrite_result.get('new_quality_report', quality),
            'quality_score': rewrite_result.get('new_quality_report', {}).get('score', 0),
            'quality_passed': rewrite_result.get('new_quality_report', {}).get('verdict') == 'pass',
            'steps': results,
        }

    return result


def launch_wave(task_id: str, steps: list[str], entity: str, query: str, market: str) -> dict:
    """
    并行发射一组无依赖关系（或依赖已满足）的 step。
    用 ThreadPoolExecutor 并发，每个 step 独立 launch_and_verify。
    """
    results = []
    quality_summary = {}
    
    max_workers = min(len(steps), 6)  # 最多 6 并发
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for step in steps:
            timeout = STEP_TIMEOUTS.get(step, 600)
            fut = executor.submit(launch_and_verify, task_id, step, entity, query, timeout, market)
            futures[fut] = step
        
        for fut in as_completed(futures, timeout=1200):
            step = futures[fut]
            try:
                step_result = fut.result()
            except Exception as e:
                step_result = {
                    'step': step,
                    'status': 'exception',
                    'error': str(e)[:200],
                }
            
            results.append(step_result)
            quality_summary[step] = {
                'score': step_result.get('quality_score', 0),
                'passed': step_result.get('quality_passed', False),
                'retries': step_result.get('retries_used', 0),
            }
            
            status = step_result.get('status', 'unknown')
            step_name = STEP_ROLE.get(step, step)
            if status in ('completed', 'completed_with_retries'):
                print(f"  ✅ {step_name} 完成 (质量: {step_result.get('quality_score', '?')}/{STEP_QUALITY_THRESHOLD})")
            elif status in ('spawn_failed', 'blocked', 'output_timeout'):
                print(f"  ❌ {step_name} 失败 ({status})")
            else:
                print(f"  ⚠️ {step_name} 状态: {status}")
    
    # 按 STEP_ORDER 排序结果（保证输出顺序一致）
    step_map = {r['step']: r for r in results}
    ordered_results = [step_map[s] for s in steps if s in step_map]
    
    return {
        'results': ordered_results,
        'quality_summary': quality_summary,
    }


def launch_all(task_id: str, entity: str = '', query: str = '', dry_run: bool = False, market: str = 'us') -> dict:
    """
    按依赖拓扑并行发射所有 step。
    
    波次：
    Wave 1: step1_data（独立）
    Wave 2: step2,3,4,5（只依赖 step1 → 并行发射）
    Wave 3: step6,7（依赖 wave2 → 等 wave2 全部完成后并行）
    Wave 4: step8（依赖全部 → 串行）
    """
    all_results = []
    all_quality = {}
    
    for wave_idx, wave_steps in enumerate(LAUNCH_WAVES):
        print(f"\n{'=' * 50}")
        print(f"🌊 Wave {wave_idx + 1}: {', '.join(wave_steps)}")
        print(f"{'=' * 50}")
        
        # 检查依赖
        for step in wave_steps:
            ready, missing = deps_ready(task_id, step)
            if not ready:
                print(f"  ⚠️ {step} 依赖未满足: {missing}，跳过")
                continue
        
        if dry_run:
            for step in wave_steps:
                result = launch_step(task_id, step, entity, query, STEP_TIMEOUTS.get(step, 600), dry_run=True)
                all_results.append(result)
            continue
        
        wave_result = launch_wave(task_id, wave_steps, entity, query, market)
        all_results.extend(wave_result['results'])
        all_quality.update(wave_result['quality_summary'])
    
    passed = sum(1 for v in all_quality.values() if v.get('passed', False))
    total = len(all_quality)
    
    return {
        'task_id': task_id,
        'entity': entity,
        'mode': 'parallel_waves',
        'dry_run': dry_run,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'steps': all_results,
        'quality_summary': all_quality,
        'total_steps_launched': sum(1 for r in all_results if r.get('status') in ('completed', 'completed_with_retries', 'spawned')),
        'total_steps_completed': sum(1 for r in all_results if r.get('status') in ('completed', 'completed_with_retries')),
        'quality_passed': passed,
        'quality_total': total,
    }


def main():
    ap = argparse.ArgumentParser(description='IR Subagent Launcher (with quality gate + parallel waves)')
    ap.add_argument('--task-id', required=True, help='Task ID')
    ap.add_argument('--step', choices=list(STEP_DEPS.keys()), help='Single step to launch')
    ap.add_argument('--all', action='store_true', help='Launch all steps (parallel waves)')
    ap.add_argument('--entity', default='', help='Entity name (e.g. 东江集团控股)')
    ap.add_argument('--query', default='', help='Research query')
    ap.add_argument('--market', default='us', choices=['us', 'hk', 'cn'], help='Market')
    ap.add_argument('--dry-run', action='store_true', help='Show what would be launched')
    ap.add_argument('--retries', type=int, default=1, help='Max quality-gated retries')
    args = ap.parse_args()

    if args.step:
        timeout = STEP_TIMEOUTS.get(args.step, 600)
        result = launch_and_verify(args.task_id, args.step, args.entity, args.query, timeout, market=args.market)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.all:
        result = launch_all(args.task_id, args.entity, args.query, args.dry_run, args.market)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        ap.print_help()


if __name__ == '__main__':
    main()
