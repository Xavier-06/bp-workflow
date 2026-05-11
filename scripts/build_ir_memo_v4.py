#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('claim_cards_json')
    ap.add_argument('risk_table')
    ap.add_argument('handoff_note')
    args = ap.parse_args()

    cards = load_json(Path(args.claim_cards_json)).get('cards', [])
    task_id = load_json(Path(args.claim_cards_json)).get('task_id')

    by_section = {}
    for c in cards:
        by_section.setdefault(c['section'], []).append(c)

    lines = [
        f'# Memo v4 - {task_id}',
        '',
        '## 核心判断',
        '- AI 医疗已经具备清晰的成长叙事，但现阶段更适合先做框架研究，不宜过早下确定性投资结论。',
        '- 当前最大的研究障碍不是“没故事”，而是市场规模口径分散、可比公司分层不清、政策材料噪音较多。',
        '- 因此下一阶段的重点，不是继续盲目扩资料，而是统一口径、筛可比、清政策。',
        '',
        '## 当前看到的三条主线',
        '### 1. 市场规模 / 增长',
    ]
    for c in by_section.get('市场规模 / 增长', [])[:2]:
        lines.append(f"- {c['claim_card']}")
    if not by_section.get('市场规模 / 增长'):
        lines.append('- 当前仍缺统一口径的市场规模与增速数据。')

    lines += ['', '### 2. 关键玩家 / 可比公司']
    for c in by_section.get('关键玩家 / 可比公司', [])[:3]:
        lines.append(f"- {c['claim_card']}")
    if not by_section.get('关键玩家 / 可比公司'):
        lines.append('- 当前仍缺清晰的玩家分层和可比公司池。')

    lines += ['', '### 3. 政策 / 技术变化']
    for c in by_section.get('政策 / 技术变化', [])[:3]:
        lines.append(f"- {c['claim_card']}")
    if not by_section.get('政策 / 技术变化'):
        lines.append('- 当前仍缺足够扎实的政策与技术变化材料。')

    lines += [
        '',
        '## 当前最值得盯的缺口',
        '- **口径统一**：不同市场规模和增速数据混用了不同年份、币种和定义。',
        '- **可比分层**：需要把平台型、应用型、医疗IT、AI制药分开看。',
        '- **政策提纯**：要把正式监管口径和媒体/宣传性材料分开。',
        '',
        '## 风险提示',
        '- 如果口径不统一，后续估值和空间判断会直接失真。',
        '- 如果可比公司池不干净，容易把题材股错当成核心受益标的。',
        '- 如果政策材料不提纯，研究结论会被二次传播内容带偏。',
        '',
        '## 建议下一步',
        '1. 先做市场规模口径对齐表。',
        '2. 再做关键玩家 / 可比公司分层表。',
        '3. 最后把政策 / 监管 / 技术路线整理成时间线。',
        '',
        '## 交付定位',
        '- 这版文稿适合作为“框架版 memo”。',
        '- 可以给 Xavier 内部先看，不建议直接外发成正式投资结论。',
    ]

    out = TASKS_DIR / f'{task_id}-memo-v4.md'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'task_id': task_id, 'output': str(out)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
