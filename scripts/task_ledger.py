#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / 'data' / 'tasks' / 'tasks.json'

DEFAULTS = {
    'status': '待开始',
    'owner': '主控 Agent',
    'recipient': 'internal',
    'next_action': '',
    'blocked_reason': '',
    'output_path': '',
    'notes': ''
}

VALID_STATUS = ['待开始', '进行中', '待汇总', '待确认', '已完成', '已阻塞']


def now_iso():
    return datetime.now().isoformat(timespec='seconds')


def load_store():
    if not STORE.exists():
        STORE.parent.mkdir(parents=True, exist_ok=True)
        STORE.write_text(json.dumps({'meta': {'version': 1, 'updated_at': None}, 'tasks': []}, ensure_ascii=False, indent=2)+"\n", encoding='utf-8')
    return json.loads(STORE.read_text(encoding='utf-8'))


def save_store(data):
    data.setdefault('meta', {})['updated_at'] = now_iso()
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding='utf-8')


def next_id(tasks):
    today = datetime.now().strftime('%Y%m%d')
    nums = []
    for t in tasks:
        tid = t.get('task_id', '')
        if tid.startswith(f'TASK-{today}-'):
            try:
                nums.append(int(tid.rsplit('-', 1)[1]))
            except Exception:
                pass
    n = max(nums) + 1 if nums else 1
    return f'TASK-{today}-{n:03d}'


def ensure_task_shape(task: dict) -> dict:
    task.setdefault('progress_updates', [])
    task.setdefault('proactive_alerted_at', None)
    return task


def find_task(data, task_id):
    for t in data.get('tasks', []):
        if t.get('task_id') == task_id:
            return ensure_task_shape(t)
    raise SystemExit(f'Task not found: {task_id}')


def cmd_create(args):
    data = load_store()
    task = ensure_task_shape({
        'task_id': next_id(data['tasks']),
        'title': args.title,
        'task_type': args.task_type,
        'status': args.status,
        'owner': args.owner,
        'recipient': args.recipient,
        'next_action': args.next_action,
        'blocked_reason': '',
        'output_path': args.output_path,
        'notes': args.notes,
        'created_at': now_iso(),
        'updated_at': now_iso(),
    })
    data['tasks'].append(task)
    save_store(data)
    print(json.dumps(task, ensure_ascii=False, indent=2))


def cmd_list(args):
    data = load_store()
    tasks = [ensure_task_shape(t) for t in data.get('tasks', [])]
    if args.status:
        tasks = [t for t in tasks if t.get('status') == args.status]
    if args.open_only:
        tasks = [t for t in tasks if t.get('status') not in ('已完成',)]
    print(json.dumps(tasks, ensure_ascii=False, indent=2))


def cmd_update(args):
    data = load_store()
    task = find_task(data, args.task_id)
    if args.status:
        task['status'] = args.status
    if args.owner:
        task['owner'] = args.owner
    if args.recipient:
        task['recipient'] = args.recipient
    if args.next_action is not None:
        task['next_action'] = args.next_action
    if args.blocked_reason is not None:
        task['blocked_reason'] = args.blocked_reason
    if args.output_path is not None:
        task['output_path'] = args.output_path
    if args.notes is not None:
        task['notes'] = args.notes
    task['updated_at'] = now_iso()
    save_store(data)
    print(json.dumps(task, ensure_ascii=False, indent=2))


def cmd_progress(args):
    data = load_store()
    task = find_task(data, args.task_id)
    event = {
        'message': args.message,
        'stage': args.stage,
        'created_at': now_iso(),
        'sent_at': None,
    }
    task.setdefault('progress_updates', []).append(event)
    if args.status:
        task['status'] = args.status
    if args.next_action is not None:
        task['next_action'] = args.next_action
    task['updated_at'] = now_iso()
    save_store(data)
    print(json.dumps({'task_id': task['task_id'], 'progress_event': event}, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd')

    c = sp.add_parser('create')
    c.add_argument('title')
    c.add_argument('--task-type', default='资料整理类')
    c.add_argument('--status', choices=VALID_STATUS, default=DEFAULTS['status'])
    c.add_argument('--owner', default=DEFAULTS['owner'])
    c.add_argument('--recipient', default=DEFAULTS['recipient'])
    c.add_argument('--next-action', default=DEFAULTS['next_action'])
    c.add_argument('--output-path', default=DEFAULTS['output_path'])
    c.add_argument('--notes', default=DEFAULTS['notes'])
    c.set_defaults(func=cmd_create)

    l = sp.add_parser('list')
    l.add_argument('--status', choices=VALID_STATUS)
    l.add_argument('--open-only', action='store_true')
    l.set_defaults(func=cmd_list)

    u = sp.add_parser('update')
    u.add_argument('task_id')
    u.add_argument('--status', choices=VALID_STATUS)
    u.add_argument('--owner')
    u.add_argument('--recipient')
    u.add_argument('--next-action')
    u.add_argument('--blocked-reason')
    u.add_argument('--output-path')
    u.add_argument('--notes')
    u.set_defaults(func=cmd_update)

    p = sp.add_parser('progress')
    p.add_argument('task_id')
    p.add_argument('message')
    p.add_argument('--stage', default='progress')
    p.add_argument('--status', choices=VALID_STATUS)
    p.add_argument('--next-action')
    p.set_defaults(func=cmd_progress)

    args = ap.parse_args()
    if not getattr(args, 'cmd', None):
        ap.print_help(); raise SystemExit(1)
    args.func(args)

if __name__ == '__main__':
    main()
