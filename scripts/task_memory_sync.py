#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / 'data' / 'tasks'
MEMCMD = ROOT / 'scripts' / 'memory-cmd.sh'


def run_add(content: str, memory_type: str):
    return subprocess.run(['bash', str(MEMCMD), 'add', content, '--type', memory_type], capture_output=True, text=True)


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_id')
    args = ap.parse_args()

    pkg = TASKS / f'{args.task_id}.json'
    if not pkg.exists():
        raise SystemExit(f'task package not found: {pkg}')

    data = load_json(pkg)
    task = data.get('task', {})
    query = data.get('query', '')
    keys = data.get('instruction_keys', [])
    title = task.get('title', args.task_id)

    memories = []
    # durable task fact
    memories.append((f"任务归档：{title}｜task_type={task.get('task_type')}｜instruction_keys={keys}", 'data_points'))

    # preference / standard if query hints style constraints
    if any(k in query for k in ['高盛', '摩根', '华泰', '券商风格', '事实与推算']):
        memories.append(("Xavier 对正式研报的硬约束：卖方券商风格、事实/推算分栏、内部协作提示不得进入正文。", 'preferences'))

    # source audit summary if present
    sa = TASKS / f'{args.task_id}-source-audit.json'
    if sa.exists():
        audit = load_json(sa)
        counts = audit.get('counts', {})
        memories.append((f"来源审计：{args.task_id} retrieved_fact={counts.get('retrieved_fact',0)} estimate_or_inference={counts.get('estimate_or_inference',0)} process_or_query={counts.get('process_or_query',0)}", 'data_points'))

    added = []
    for content, t in memories:
        p = run_add(content, t)
        added.append({'type': t, 'content': content, 'ok': p.returncode == 0, 'stdout': (p.stdout or '').strip(), 'stderr': (p.stderr or '').strip()})

    print(json.dumps({'task_id': args.task_id, 'added': added}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
