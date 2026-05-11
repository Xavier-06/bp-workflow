#!/usr/bin/env python3
"""
Context Analysis — 对话/文本的 Token 分布分析
对标 free-code 的 contextAnalysis.ts

功能：
1. 分析文本的 token 估算分布
2. 统计工具调用模式（如果包含工具调用标记）
3. 重复内容检测（同一个文件/内容被多次引用）
4. 人类 vs 助手消息比例估算

对标 free-code 的 TokenStats：
- toolRequests: 工具调用次数估算
- toolResults: 工具结果占比
- humanMessages: 人类消息估算
- assistantMessages: 助手消息估算
- duplicateFileReads: 重复文件读取检测
- total: 总 token 估算

用法（独立运行）：
  python3 context_analysis.py --file memory/2026-04-05.md
  python3 context_analysis.py --dir data/tasks/TASK-XXX/ --json

用法（集成到管线）：
  from context_analysis import analyze_text, print_report
  report = analyze_text(text)
  print_report(report)
"""
import argparse
import json
import sys
from pathlib import Path
from collections import Counter

WORKSPACE = Path(__file__).resolve().parent.parent


def estimate_tokens(text: str) -> int:
    """
    估算 token 数量。
    英文：~4 chars/token
    中文：~1.5 chars/token
    混合：取平均值 ~2.5 chars/token

    对标 free-code 的 roughTokenCountEstimation
    """
    if not text:
        return 0

    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total_chars = len(text)
    en_chars = total_chars - cn_chars

    # 中文 ~1.5 chars/token, 英文 ~4 chars/token
    return int(cn_chars / 1.5 + en_chars / 4)


def analyze_text(text: str, label: str = 'unknown') -> dict:
    """
    对标 free-code 的 analyzeContext()

    分析文本结构，返回类似 TokenStats 的报告。
    """
    if not text:
        return {
            'label': label,
            'total_tokens': 0,
            'total_chars': 0,
            'lines': 0,
            'sections': 0,
            'code_blocks': 0,
            'links': 0,
            'tables': 0,
            'lists': 0,
            'headers': 0,
            'duplicate_content_ratio': 0.0,
            'cn_ratio': 0.0,
            'tool_calls': 0,
            'tool_results': 0,
        }

    lines = text.split('\n')
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')

    # 统计结构元素
    headers = sum(1 for l in lines if l.startswith('#'))
    code_blocks = text.count('```') // 2
    links = text.count('http')
    tables = sum(1 for l in lines if l.strip().startswith('|'))
    lists = sum(1 for l in lines if l.strip().startswith(('-', '*', '+', '1.', '2.')))
    sections = headers

    # 工具调用标记（如果文本包含管线工具调用痕迹）
    tool_calls = sum(1 for kw in ['Bash(', 'Read(', 'Grep(', 'Write(', 'Edit(',
                                   'Tool:', 'tool_use', 'function_call'] if kw in text)
    tool_results = sum(1 for kw in ['tool_result', 'output:', '结果:', '返回值'] if kw in text)

    # 重复内容检测（对标 free-code 的 duplicateFileReads）
    line_counts = Counter(l.strip() for l in lines if len(l.strip()) > 20)
    total_lines = len([l for l in lines if len(l.strip()) > 20])
    dup_lines = sum(c - 1 for c in line_counts.values() if c > 1)
    dup_ratio = dup_lines / max(total_lines, 1)

    return {
        'label': label,
        'total_tokens': estimate_tokens(text),
        'total_chars': len(text),
        'lines': len(lines),
        'sections': sections,
        'code_blocks': code_blocks,
        'links': links,
        'tables': tables,
        'lists': lists,
        'headers': headers,
        'duplicate_content_ratio': round(dup_ratio, 3),
        'cn_ratio': round(cn_chars / max(len(text), 1), 3),
        'tool_calls': tool_calls,
        'tool_results': tool_results,
    }


def analyze_directory(dir_path: str, pattern: str = '*.md') -> list[dict]:
    """分析目录下所有文件的 token 分布"""
    p = Path(dir_path)
    results = []
    for f in sorted(p.glob(pattern)):
        if f.is_file():
            text = f.read_text(encoding='utf-8', errors='ignore')
            report = analyze_text(text, label=f.name)
            results.append(report)
    return results


def print_report(reports):
    """格式化打印报告"""
    if not isinstance(reports, list):
        reports = [reports]

    total_tokens = sum(r['total_tokens'] for r in reports)
    total_chars = sum(r['total_chars'] for r in reports)
    total_dup = sum(r['duplicate_content_ratio'] for r in reports) / max(len(reports), 1)

    print(f"Context Analysis Report ({len(reports)} files)")
    print(f"{'='*60}")
    print(f"  Total tokens:  ~{total_tokens:,}")
    print(f"  Total chars:   {total_chars:,}")
    print(f"  Avg dup ratio: {total_dup:.1%}")
    print(f"{'='*60}")

    for r in reports:
        cn_pct = r['cn_ratio'] * 100
        dup_pct = r['duplicate_content_ratio'] * 100
        print(f"\n  {r['label']}")
        print(f"    Tokens: ~{r['total_tokens']:,} | Chars: {r['total_chars']:,} | Lines: {r['lines']}")
        print(f"    CN ratio: {cn_pct:.0f}% | Dup: {dup_pct:.0f}%")
        print(f"    Headers: {r['headers']} | Code: {r['code_blocks']} | Links: {r['links']}")
        print(f"    Tables: {r['tables']} | Lists: {r['lists']}")
        if r['tool_calls'] > 0:
            print(f"    Tool calls: {r['tool_calls']} | Results: {r['tool_results']}")


def analyze_pipeline_task(task_id: str, pipeline: str = 'ir') -> list[dict]:
    """
    管线任务专用分析。
    分析一个任务的所有 step 文件，返回整体 token 分布。
    """
    if pipeline == 'ir':
        tasks_dir = WORKSPACE / 'data' / 'tasks'
        step_names = ['step1_data', 'step2_industry', 'step3_biz',
                      'step4_finance', 'step5_mgmt', 'step6_insight',
                      'step6b_valuation', 'step7_risk', 'step8_master']
        files = [(tasks_dir / f'{task_id}-{s}.md') for s in step_names]
    else:
        # BP pipeline
        tasks_dir = WORKSPACE / 'tasks'
        task_dir = tasks_dir / task_id
        if task_dir.exists():
            files = sorted(task_dir.glob(f'{task_id}-step*.md'))
        else:
            files = []

    reports = []
    for f in files:
        if f.exists():
            text = f.read_text(encoding='utf-8', errors='ignore')
            reports.append(analyze_text(text, label=f.name))

    return reports


def main():
    p = argparse.ArgumentParser(description='Context Analysis')
    p.add_argument('--file', help='分析单个文件')
    p.add_argument('--dir', help='分析目录')
    p.add_argument('--task-id', help='分析管线任务')
    p.add_argument('--pipeline', choices=['bp', 'ir'], default='ir')
    p.add_argument('--json', action='store_true')
    args = p.parse_args()

    reports = []

    if args.file:
        text = Path(args.file).read_text(encoding='utf-8', errors='ignore')
        reports = [analyze_text(text, label=Path(args.file).name)]

    elif args.dir:
        reports = analyze_directory(args.dir)

    elif args.task_id:
        reports = analyze_pipeline_task(args.task_id, args.pipeline)

    else:
        p.print_help()
        return

    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        print_report(reports)


if __name__ == '__main__':
    main()


def post_compact_cleanup(task_id: str = None, cache_dirs: list = None):
    """
    对标 free-code 的 runPostCompactCleanup()：
    在管线阶段完成后清理缓存和临时文件。
    
    对标 free-code 的清理项：
    - clearSystemPromptSections → 清理管线临时配置
    - clearSessionMessagesCache → 清理任务临时文件
    - clearClassifierApprovals → 清理验证临时状态
    """
    import glob
    
    cleaned = []
    
    if cache_dirs is None:
        cache_dirs = [
            WORKSPACE / 'data' / 'tasks' / f'{task_id}-*.tmp',
            WORKSPACE / 'tasks' / f'{task_id}-*.tmp',
        ]
    
    # 清理 .tmp 文件
    for pattern in cache_dirs:
        if task_id:
            for f in WORKSPACE.rglob(f'{task_id}*.tmp'):
                if f.is_file():
                    f.unlink()
                    cleaned.append(str(f))
    
    # 清理 __pycache__ 中的 stale .pyc 文件
    if task_id:
        for pyc in WORKSPACE.rglob('**/__pycache__/*.pyc'):
            if task_id in str(pyc):
                pyc.unlink()
                cleaned.append(str(pyc))
    
    return {
        'cleaned_files': cleaned,
        'count': len(cleaned),
        'note': f'清理了 {len(cleaned)} 个临时文件'
    }

