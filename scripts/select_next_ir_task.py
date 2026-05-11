#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / 'data' / 'tasks' / 'tasks.json'
OUT = ROOT / 'data' / 'tasks' / 'next-task-selection.json'

ACTIVE_STATUSES = {'进行中', '待开始', '待确认', '已阻塞'}
EXCLUDE_NOTE_KEYWORDS = ['弃用', '无效产物', '测试样例关闭', '占位任务', '伪多智能体流程']
EXCLUDE_TITLE_KEYWORDS = ['测试']

PRIORITY_BY_STATUS = {
    '待确认': 100,
    '已阻塞': 90,
    '进行中': 80,
    '待开始': 70,
}

PRIORITY_BY_TYPE = {
    '专题研究类': 30,
    '资料整理类': 20,
    '晨报类': 15,
    '快报类': 15,
    '回顾类': 10,
}


def load_tasks() -> list[dict]:
    data = json.loads(TASKS.read_text(encoding='utf-8'))
    return data.get('tasks', [])


def is_excluded(task: dict) -> tuple[bool, str]:
    notes = task.get('notes', '') or ''
    title = task.get('title', '') or ''
    for kw in EXCLUDE_NOTE_KEYWORDS:
        if kw in notes:
            return True, f'notes contains {kw}'
    for kw in EXCLUDE_TITLE_KEYWORDS:
        if kw in title and '投研智能体落地' not in title:
            return True, f'title contains {kw}'
    return False, ''


def score_task(task: dict) -> int:
    score = 0
    score += PRIORITY_BY_STATUS.get(task.get('status', ''), 0)
    score += PRIORITY_BY_TYPE.get(task.get('task_type', ''), 0)

    recipient = task.get('recipient', '')
    if recipient == 'xavier':
        score += 15
    if recipient == 'internal':
        score += 5

    title = task.get('title', '')
    notes = task.get('notes', '')
    next_action = task.get('next_action', '')

    if '主任务' in notes or '主任务' in next_action:
        score += 50
    if 'proactive operator' in title.lower() or '自驱' in title or '工作流总整备' in title:
        score += 40
    if '英伟达' in title:
        score -= 20  # 当前只是测试用例
    if task.get('status') == '已阻塞':
        score += 10  # blocked but may need decision/repair first

    # newer updates slightly preferred among same class
    updated_at = task.get('updated_at') or task.get('created_at') or ''
    if updated_at:
        try:
            ts = datetime.fromisoformat(updated_at)
            age_minutes = max(0, int((datetime.now() - ts).total_seconds() // 60))
            score += max(0, 20 - min(age_minutes, 20))
        except Exception:
            pass
    return score


def main():
    tasks = load_tasks()
    candidates = []
    excluded = []
    for task in tasks:
        if task.get('status') not in ACTIVE_STATUSES:
            continue
        bad, reason = is_excluded(task)
        if bad:
            excluded.append({'task_id': task.get('task_id'), 'title': task.get('title'), 'reason': reason})
            continue
        candidates.append({
            'task_id': task.get('task_id'),
            'title': task.get('title'),
            'task_type': task.get('task_type'),
            'status': task.get('status'),
            'recipient': task.get('recipient'),
            'next_action': task.get('next_action'),
            'notes': task.get('notes'),
            'score': score_task(task),
        })
    candidates.sort(key=lambda x: x['score'], reverse=True)
    primary = candidates[0] if candidates else None
    support = candidates[1] if len(candidates) > 1 else None
    result = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'primary_task': primary,
        'support_task': support,
        'candidate_count': len(candidates),
        'excluded_count': len(excluded),
        'excluded': excluded,
        'rule': 'Only 1 primary + at most 1 support task should remain active; test/invalid tasks are excluded.'
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
