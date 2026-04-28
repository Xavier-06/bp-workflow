#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

NOISE = [
    r'Action Another action.*',
    r'定制请求.*',
    r'%PDF-\d.*',
    r'首页.*',
    r'Toggle navigation.*',
]


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def clean_text(s: str) -> str:
    s = re.sub(r'\s+', ' ', s.strip())
    for pat in NOISE:
        s = re.sub(pat, '', s, flags=re.I)
    s = s.replace('|', '｜')
    return s.strip(' -:：|')


def first_sentence(text: str) -> str:
    text = clean_text(text)
    if not text:
        return ''
    parts = re.split(r'(?<=[。！？.!?])\s+', text)
    s = parts[0].strip() if parts else text
    return s[:140]


def claim_from_row(row: dict) -> str:
    title = clean_text(row.get('source_title', ''))
    claim = first_sentence(row.get('claim', ''))
    excerpt = first_sentence(row.get('evidence_excerpt', ''))

    if row.get('section') == '市场规模 / 增长':
        nums = re.findall(r'(\d+(?:\.\d+)?\s*(?:%|万亿|亿元|亿美元|billion|million))', claim + ' ' + excerpt, flags=re.I)
        if nums:
            return f'已有报告给出 AI 医疗市场规模/增速口径，如 {nums[0]}，但仍需统一定义。'
        return f'{title[:50]} 显示 AI 医疗市场增长叙事已形成，但口径仍需统一。'

    if row.get('section') == '关键玩家 / 可比公司':
        if any(k in claim + excerpt for k in ['华为', '腾讯', '阿里', '赛诺菲', 'OpenAI']):
            return '现有证据显示，科技平台、医疗 IT 与制药公司都在切入 AI 医疗，玩家结构尚未分层。'
        return f'{title[:50]} 提供了关键玩家或可比公司线索，但仍需进一步筛选。'

    if row.get('section') == '政策 / 技术变化':
        if any(k in claim + excerpt for k in ['监管', '指引', '条例', '标准', '政策']):
            return '政策与监管材料显示，AI 医疗应用场景与监管框架正在逐步细化。'
        if any(k in claim + excerpt for k in ['多模态', '生成式', '大模型', '技术']):
            return '技术路线材料显示，多模态和生成式 AI 正在成为 AI 医疗的重要推进方向。'
        return f'{title[:50]} 提供了政策/技术变化线索，需继续提纯。'

    return claim or excerpt or title


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('clean_evidence_json')
    args = ap.parse_args()

    data = load_json(Path(args.clean_evidence_json))
    task_id = data['task_id']
    rows = data.get('rows', [])
    cards = []
    seen = set()
    for row in rows:
        claim = claim_from_row(row)
        key = (row.get('section'), claim)
        if not claim or key in seen:
            continue
        seen.add(key)
        cards.append({
            'section': row.get('section'),
            'claim_card': claim,
            'source_title': row.get('source_title'),
            'source_url': row.get('source_url'),
            'confidence': row.get('confidence'),
        })

    out_json = TASKS_DIR / f'{task_id}-claim-cards.json'
    out_md = TASKS_DIR / f'{task_id}-claim-cards.md'
    out_json.write_text(json.dumps({'task_id': task_id, 'cards': cards}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = [f'# Claim Cards - {task_id}', '']
    current = None
    for card in cards:
        if card['section'] != current:
            current = card['section']
            lines += [f'## {current}']
        lines.append(f"- {card['claim_card']}｜{card['confidence']}｜{card['source_title']}")
    out_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'task_id': task_id, 'json': str(out_json), 'md': str(out_md), 'count': len(cards)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
