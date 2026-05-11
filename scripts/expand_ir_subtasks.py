#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

SUBTASK_TEMPLATES = {
    '专题研究类': [
        {
            'subtask_type': 'scope-clarification',
            'owner': '主控 Agent',
            'title': '明确研究范围与输出边界',
            'goal': '把研究对象、研究目的、输出形态、关键关注点明确下来',
            'deliverable': '范围确认清单',
        },
        {
            'subtask_type': 'data-collection',
            'owner': '投研_主笔_数据收集',
            'title': '拉第一轮资料与来源',
            'goal': '收集市场规模、关键玩家、政策/技术变化、可比公司、基础财务/估值线索',
            'deliverable': '第一轮结构化数据包',
        },
        {
            'subtask_type': 'industry-analysis',
            'owner': '投研_主笔_行业分析',
            'title': '生成行业框架草稿',
            'goal': '搭出行业/赛道分析骨架，明确增长驱动、竞争格局、关键变量',
            'deliverable': '行业框架草稿',
        },
    ],
    '晨报类': [
        {
            'subtask_type': 'news-collection',
            'owner': '投研_主笔_数据收集',
            'title': '拉取过去24小时公开信息',
            'goal': '收集新闻、公告、价格和关键事件',
            'deliverable': '晨报原始材料包',
        },
        {
            'subtask_type': 'news-cleanup',
            'owner': '信息清洗 / 摘要 Agent',
            'title': '去重与中文化',
            'goal': '把材料变成可读摘要',
            'deliverable': '中文摘要稿',
        },
    ],
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_id')
    args = ap.parse_args()

    task_path = TASKS_DIR / f'{args.task_id}.json'
    if not task_path.exists():
        raise SystemExit(f'task package not found: {task_path}')
    pkg = load_json(task_path)
    task = pkg['task']
    task_type = task.get('task_type', '专题研究类')
    query = pkg.get('query', task.get('title', ''))
    templates = SUBTASK_TEMPLATES.get(task_type, [])

    subtasks = []
    for i, item in enumerate(templates, 1):
        subtasks.append({
            'subtask_id': f"{args.task_id}-S{i:02d}",
            'task_id': args.task_id,
            'subtask_type': item['subtask_type'],
            'owner': item['owner'],
            'title': item['title'],
            'goal': item['goal'],
            'deliverable': item['deliverable'],
            'status': '待开始',
            'created_at': datetime.now().isoformat(timespec='seconds'),
            'context': {
                'query': query,
                'instruction_keys': pkg.get('instruction_keys', []),
                'task_type': task_type,
            }
        })

    out = {
        'task_id': args.task_id,
        'task_type': task_type,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'subtasks': subtasks,
    }
    out_path = TASKS_DIR / f'{args.task_id}-subtasks.json'
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'task_id': args.task_id, 'subtasks_path': str(out_path), 'count': len(subtasks)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
