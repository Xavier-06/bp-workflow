#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / 'data' / 'tasks' / 'tasks.json'


def now_iso():
    return datetime.now().isoformat(timespec='seconds')


def load_store() -> dict:
    if not STORE.exists():
        return {'meta': {'version': 1, 'updated_at': None}, 'tasks': []}
    return json.loads(STORE.read_text(encoding='utf-8'))


def save_store(data: dict):
    data.setdefault('meta', {})['updated_at'] = now_iso()
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def append_note_once(notes: str, piece: str) -> str:
    parts = [p.strip() for p in (notes or '').split('|') if p.strip()]
    if piece not in parts:
        parts.append(piece)
    return ' | '.join(parts)



def awaiting_action(notes: str) -> str | None:
    # find the last await-confirm:<action> marker
    parts = [p.strip() for p in (notes or '').split('|') if p.strip()]
    for part in reversed(parts):
        m = re.match(r'^await-confirm:(.+)$', part)
        if m:
            return m.group(1).strip()
    return None


def find_latest_pending(tasks: list[dict]) -> dict | None:
    pending = [t for t in tasks if t.get('status') == '待确认']
    pending.sort(key=lambda t: t.get('updated_at') or t.get('created_at') or '', reverse=True)
    return pending[0] if pending else None


def find_task(tasks: list[dict], task_id: str) -> dict | None:
    for t in tasks:
        if t.get('task_id') == task_id:
            return t
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('message', nargs='?', default='')
    ap.add_argument('--task-id')
    ap.add_argument('--action')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    data = load_store()
    tasks = data.get('tasks', [])

    task_id = args.task_id
    action = args.action

    msg = (args.message or '').strip()

    # Parse free-form message like: "确认 TASK-20260318-006 start" or "确认" or "暂停 TASK-..."
    if msg and not task_id:
        m = re.search(r'(TASK-\d{8}-\d{3})', msg)
        if m:
            task_id = m.group(1)
        if msg.startswith('确认'):
            # action is the last token if provided
            toks = msg.split()
            if len(toks) >= 3:
                action = toks[2]
            elif len(toks) == 2:
                action = 'continue'
            else:
                action = 'continue'
        elif msg.startswith('暂停'):
            action = 'pause'

    if not task_id:
        t = find_latest_pending(tasks)
        if not t:
            print(json.dumps({'status': 'no_pending', 'message': 'no 待确认 task found'}, ensure_ascii=False, indent=2))
            return
        task_id = t['task_id']

    t = find_task(tasks, task_id)
    if not t:
        raise SystemExit(f'Task not found: {task_id}')

    action = (action or 'continue').strip()

    # If user just says '确认', map it to the concrete awaiting action (start/fill_packet/...)
    if action == 'continue':
        aa = awaiting_action(t.get('notes','') or '')
        if aa:
            action = aa

    if action in ('pause', '暂停'):
        t['status'] = '已阻塞'
        t['blocked_reason'] = '用户暂停'
        t['next_action'] = '等待 Xavier 解除暂停/改需求'
        t['notes'] = append_note_once(t.get('notes',''), 'user-paused')
    else:
        # confirmation
        t['notes'] = append_note_once(t.get('notes',''), f'confirmed:{action}')

        # resume
        if action == 'start':
            t['status'] = '待开始'
        elif t.get('status') == '待确认':
            t['status'] = '进行中'

        t['next_action'] = f'已确认（{action}），等待 execution loop 继续推进'

    t['updated_at'] = now_iso()

    out = {'status': 'ok', 'task_id': task_id, 'action': action, 'new_status': t.get('status')}

    if args.dry_run:
        print(json.dumps(out | {'dry_run': True}, ensure_ascii=False, indent=2))
        return

    save_store(data)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
