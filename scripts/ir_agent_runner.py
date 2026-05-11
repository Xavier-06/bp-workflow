#!/usr/bin/env python3
"""
IR Agent Runner — WorkBuddy 主 AI 的执行入口

读取 manifest 文件，输出结构化的 Task 子代理 prompt。
主 AI 用法：
  1. python3 ir_agent_runner.py --manifest <path> → 输出 prompt
  2. 用 WorkBuddy Task 子代理执行 prompt
  3. 子代理输出写入 manifest 中指定的 output_path
  4. python3 ir_agent_runner.py --complete <manifest_path> → 更新状态

2026-04-13: 初始版本
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'


def read_manifest(manifest_path: str) -> dict:
    """读取 manifest 文件"""
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f'Manifest not found: {manifest_path}')
    return json.loads(path.read_text(encoding='utf-8'))


def build_task_prompt(manifest: dict) -> str:
    """根据 manifest 构建给 WorkBuddy Task 子代理的完整 prompt"""
    lines = [
        f"# IR Research Task: {manifest.get('role', manifest.get('step', 'unknown'))}",
        f"",
        f"## System Instructions",
        f"",
        manifest.get('system_prompt', 'Complete the investment research task.'),
        f"",
        f"## Task Details",
        f"",
        f"- Task ID: {manifest.get('task_id', 'unknown')}",
        f"- Role: {manifest.get('role', manifest.get('step', 'unknown'))}",
        f"- Entity: {manifest.get('entity', 'N/A')}",
        f"- Market: {manifest.get('market', 'N/A')}",
        f"",
    ]
    
    # Brief file reference
    brief_path = manifest.get('brief_path', '')
    if brief_path:
        lines.extend([
            f"## Brief File",
            f"",
            f"Read the brief file at: `{brief_path}`",
            f"",
        ])
    
    # For IR steps: include prior step outputs reference
    step = manifest.get('step', '')
    if step:
        lines.extend([
            f"## Output Requirements",
            f"",
            f"- Write your analysis as Markdown to: `{manifest.get('output_path', 'unknown')}`",
            f"- Minimum 3000 characters",
            f"- At least 3 source citations (URLs)",
            f"- Multiple sections with ## headers",
            f"- Do NOT fabricate information — use '未找到独立外部证据' for unverified claims",
            f"",
        ])
    
    # For review hooks: include result format
    hook = manifest.get('hook', '')
    if hook:
        result_kind = manifest.get('result_kind', 'json')
        lines.extend([
            f"## Review Output",
            f"",
            f"- Write review result JSON to: `{manifest.get('result_path', 'unknown')}`",
            f"- Result kind: {result_kind}",
        ])
        if manifest.get('output_path'):
            lines.append(f"- Write polished output to: `{manifest['output_path']}`")
        lines.append(f"")
    
    return '\n'.join(lines)


def mark_complete(manifest_path: str, output_size: int = 0) -> dict:
    """标记 manifest 为已完成"""
    path = Path(manifest_path)
    if not path.exists():
        return {'error': 'manifest not found'}
    
    data = json.loads(path.read_text(encoding='utf-8'))
    data['status'] = 'completed'
    data['completed_at'] = datetime.now().isoformat(timespec='seconds')
    data['output_size'] = output_size
    
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


def mark_failed(manifest_path: str, error: str = '') -> dict:
    """标记 manifest 为失败"""
    path = Path(manifest_path)
    if not path.exists():
        return {'error': 'manifest not found'}
    
    data = json.loads(path.read_text(encoding='utf-8'))
    data['status'] = 'failed'
    data['failed_at'] = datetime.now().isoformat(timespec='seconds')
    data['error'] = error[:500]
    
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


def main():
    ap = argparse.ArgumentParser(description='IR Agent Runner — Task 子代理执行入口')
    ap.add_argument('--manifest', help='Manifest file path')
    ap.add_argument('--prompt', action='store_true', help='Output task prompt for WorkBuddy Task subagent')
    ap.add_argument('--complete', action='store_true', help='Mark manifest as completed')
    ap.add_argument('--fail', action='store_true', help='Mark manifest as failed')
    ap.add_argument('--error', default='', help='Error message for --fail')
    ap.add_argument('--list-pending', action='store_true', help='List all pending manifests for a task')
    ap.add_argument('--task-id', help='Task ID for --list-pending')
    args = ap.parse_args()

    if args.list_pending and args.task_id:
        # Scan for all pending manifests
        pending = []
        for f in TASKS_DIR.glob(f'{args.task_id}-manifest-*.json'):
            data = json.loads(f.read_text(encoding='utf-8'))
            if data.get('status') == 'pending':
                output_path = Path(data.get('output_path', ''))
                if not output_path.exists():
                    pending.append({
                        'manifest': str(f),
                        'step': data.get('step', data.get('hook', '?')),
                        'role': data.get('role', '?'),
                        'status': 'pending',
                    })
        # Also check review manifests
        for f in TASKS_DIR.glob(f'{args.task_id}-*-manifest.json'):
            data = json.loads(f.read_text(encoding='utf-8'))
            if data.get('status') == 'pending':
                result_path = Path(data.get('result_path', ''))
                if not result_path.exists():
                    pending.append({
                        'manifest': str(f),
                        'step': data.get('hook', '?'),
                        'role': data.get('role', '?'),
                        'status': 'pending',
                    })
        print(json.dumps(pending, ensure_ascii=False, indent=2))
        return

    if not args.manifest:
        ap.print_help()
        return

    manifest = read_manifest(args.manifest)

    if args.prompt:
        prompt = build_task_prompt(manifest)
        print(prompt)
    elif args.complete:
        output_path = Path(manifest.get('output_path', ''))
        size = output_path.stat().st_size if output_path.exists() else 0
        result = mark_complete(args.manifest, size)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.fail:
        result = mark_failed(args.manifest, args.error)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # Default: output the prompt
        prompt = build_task_prompt(manifest)
        print(prompt)


if __name__ == '__main__':
    main()
