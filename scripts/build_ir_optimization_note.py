#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT/'data'/'tasks'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('bundle_json')
    args = ap.parse_args()
    bundle = json.loads(Path(args.bundle_json).read_text(encoding='utf-8'))
    task_id = bundle['task_id']
    note = {
        'task_id': task_id,
        'suggestion': '下一步最值钱的优化不是继续扩搜索，而是把来源质量分层做得更严，再把最终 memo 改成更短、更像投资判断的语言。',
        'why': [
            '当前主链已经能跑通两个真实题目，说明“有没有”不是问题。',
            '现在的主要瓶颈在来源噪音和成稿语言，而不是流程缺失。',
            '如果继续横向加功能，收益不如纵向把来源清洗和最终写作再提一档。',
        ],
        'recommended_actions': [
            '给来源加白名单 / 黑名单层级',
            '将政策 / 监管 / 蓝皮书 / 媒体分别打标签',
            'final memo 再压成更像“投资 memo”的句子，而不是研究过程句',
        ]
    }
    out = TASKS / f'{task_id}-optimization-note.json'
    out.write_text(json.dumps(note, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(out), 'task_id': task_id}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
