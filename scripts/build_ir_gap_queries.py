#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

SECTION_QUERY_MAP = {
    '市场规模 / 增长': [
        '{topic} 市场规模 2025 2026 CAGR',
        '{topic} 市场规模 预测 报告',
        '{topic} 中国 市场规模 增速',
    ],
    '关键玩家 / 可比公司': [
        '{topic} 龙头 公司 上市公司',
        '{topic} 产业链 公司名单',
        '{topic} 可比公司 估值',
    ],
    '政策 / 技术变化': [
        '{topic} 政策 监管 最新',
        '{topic} 医疗 AI 监管 政策 中国',
        '{topic} 技术 路线 医疗 生成式 AI',
    ],
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def infer_topic(task_id: str) -> str:
    packet = TASKS_DIR / f'{task_id}.json'
    if packet.exists():
        data = load_json(packet)
        return data.get('query', '').replace('做一份', '').replace('研究框架', '').strip() or task_id
    return task_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('reviewer_json')
    args = ap.parse_args()
    reviewer = load_json(Path(args.reviewer_json))
    task_id = reviewer['task_id']
    topic = infer_topic(task_id).replace('赛道', '').strip()
    sections = []
    for issue in reviewer.get('issues', []):
        if issue.get('type') in ('noise', 'conflict', 'confidence') and issue.get('section') and issue['section'] not in sections:
            sections.append(issue['section'])
    queries = []
    for section in sections:
        for tpl in SECTION_QUERY_MAP.get(section, []):
            queries.append({'section': section, 'query': tpl.format(topic=topic)})
    out = {
        'task_id': task_id,
        'topic': topic,
        'generated_from': str(Path(args.reviewer_json)),
        'queries': queries,
    }
    out_path = TASKS_DIR / f'{task_id}-gap-queries.json'
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'task_id': task_id, 'gap_queries': str(out_path), 'count': len(queries)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
