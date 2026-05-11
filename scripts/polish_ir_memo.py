#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('claim_cards_json')
    args = ap.parse_args()
    data = load_json(Path(args.claim_cards_json))
    task_id = data['task_id']
    cards = data.get('cards', [])

    by_section = {}
    for card in cards:
        by_section.setdefault(card['section'], []).append(card)

    lines = [
        f'# Polished Memo v3 - {task_id}',
        '',
        '## 核心判断',
        '- AI 医疗方向已经形成较清晰的增长叙事，但市场规模与增速口径仍未统一，现阶段更适合先做框架判断，而不是下确定性结论。',
        '- 关键玩家层面已经能拉出一轮公司与产业链线索，但真正可比公司仍需按业务属性重新分层。',
        '- 政策与技术变化层面的证据已明显改善，下一步重点是继续压缩宣传性来源、保留正式监管与高质量机构口径。',
        '',
        '## 当前研究骨架',
        '### 市场规模 / 增长',
    ]
    for c in by_section.get('市场规模 / 增长', [])[:3]:
        lines.append(f"- {c['claim_card']}")
    if not by_section.get('市场规模 / 增长'):
        lines.append('- 当前仍需补统一口径。')

    lines += ['', '### 关键玩家 / 可比公司']
    for c in by_section.get('关键玩家 / 可比公司', [])[:3]:
        lines.append(f"- {c['claim_card']}")
    if not by_section.get('关键玩家 / 可比公司'):
        lines.append('- 当前仍需补可比公司分层。')

    lines += ['', '### 政策 / 技术变化']
    for c in by_section.get('政策 / 技术变化', [])[:3]:
        lines.append(f"- {c['claim_card']}")
    if not by_section.get('政策 / 技术变化'):
        lines.append('- 当前仍需补政策与技术变化材料。')

    lines += [
        '',
        '## 风险提示',
        '- 第一，市场规模与增长率仍有多口径冲突，不能直接拿单一报告做结论。',
        '- 第二，关键玩家名单已出现，但可比公司池仍需进一步分层和筛选。',
        '- 第三，政策与技术材料虽然补强了，但仍需继续提纯来源。',
        '',
        '## 下一步建议',
        '1. 统一市场规模口径（中国/全球、整体/细分、币种、年份）。',
        '2. 把关键玩家拆成平台型、应用型、医疗IT、AI制药几类。',
        '3. 把政策/监管整理成时间线，再进入更正式的投资逻辑分析。',
        '',
        '## 说明',
        '- 这版 memo 使用 claim cards 重写，目标是显著降低原文味。',
    ]
    out = TASKS_DIR / f'{task_id}-memo-polished-v3.md'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'task_id': task_id, 'output': str(out)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
