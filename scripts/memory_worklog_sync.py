#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEMORY_SYSTEM = ROOT / 'memory_system'
ENV_FILE = ROOT / '.credentials' / 'investment-research.env'
TASKS_JSON = ROOT / 'data' / 'tasks' / 'tasks.json'

if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, str(MEMORY_SYSTEM))
from work_log import WorkLog  # type: ignore


def load_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return default


def sync_active_context(task_id: str):
    pkg_path = ROOT / 'data' / 'tasks' / f'{task_id}.json'
    tasks = load_json(TASKS_JSON, {'tasks': []})
    task = next((t for t in tasks.get('tasks', []) if t.get('task_id') == task_id), None)
    pkg = load_json(pkg_path, {}) or {}

    if not task:
        raise SystemExit(f'task not found: {task_id}')

    wl = WorkLog()
    lines = [
        f'# 当前主任务',
        '',
        f'- task_id: {task.get("task_id")}',
        f'- 标题: {task.get("title")}',
        f'- 类型: {task.get("task_type")}',
        f'- 状态: {task.get("status")}',
        f'- 当前下一步: {task.get("next_action")}',
    ]
    query = pkg.get('query')
    if query:
        lines.append(f'- 原始查询: {query}')
    keys = pkg.get('instruction_keys') or []
    if keys:
        lines.append(f'- 指令包: {", ".join(keys)}')
    mem = pkg.get('memory_context', {}) or {}
    if mem.get('ok') and mem.get('results'):
        lines += ['', '## 自动检索到的长期记忆']
        for item in mem.get('results', [])[:5]:
            lines.append(f"- [{item.get('category')}] {item.get('content')}")

    wl.update_active_context('\n'.join(lines) + '\n')
    return {'status': 'ok', 'task_id': task_id}


def rebuild_todos():
    tasks = load_json(TASKS_JSON, {'tasks': []})
    active = [t for t in tasks.get('tasks', []) if t.get('status') in ('待开始', '进行中', '待确认', '已阻塞')]
    active.sort(key=lambda x: (x.get('updated_at') or x.get('created_at') or ''), reverse=True)
    lines = []
    for t in active[:20]:
        pri = '高' if t.get('status') in ('待确认', '已阻塞') else '普通'
        lines.append(f"- [ ] **[{pri}]** {t.get('task_id')}｜{t.get('title')}｜{t.get('status')}｜下一步：{t.get('next_action')}")
    wl = WorkLog()
    wl.update_todos('\n'.join(lines) + ('\n' if lines else ''))

    # keep ACTIVE_CONTEXT aligned with newest active task; clear when no active task
    if active:
        latest = active[0]
        try:
            sync_active_context(latest['task_id'])
        except Exception:
            pass
    else:
        wl.update_active_context('# 当前活跃上下文\n\n*当前无活跃任务*\n')

    return {'status': 'ok', 'active_count': len(active), 'latest_active': active[0].get('task_id') if active else None}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd')

    s1 = sub.add_parser('task')
    s1.add_argument('task_id')

    sub.add_parser('todos')

    args = ap.parse_args()
    if args.cmd == 'task':
        print(json.dumps(sync_active_context(args.task_id), ensure_ascii=False, indent=2))
    elif args.cmd == 'todos':
        print(json.dumps(rebuild_todos(), ensure_ascii=False, indent=2))
    else:
        ap.print_help()
        raise SystemExit(1)


if __name__ == '__main__':
    main()
