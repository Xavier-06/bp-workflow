#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'


def extract_section(text: str, header: str) -> str:
    pattern = rf'^### {re.escape(header)}\n([\s\S]*?)(?=^### |^## |\Z)'
    m = re.search(pattern, text, flags=re.M)
    return m.group(1).strip() if m else ''


def bullets_from_section(section_text: str, limit: int = 6) -> list[str]:
    lines = []
    for raw in section_text.splitlines():
        s = raw.strip()
        if s.startswith('- ') and '证据：' not in s and '当前缺口' not in s and '当前观察' not in s:
            lines.append(s[2:].strip())
    return lines[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('analysis_draft')
    args = ap.parse_args()
    path = Path(args.analysis_draft)
    text = path.read_text(encoding='utf-8')
    task_id = path.stem.replace('-analysis-draft', '')
    q = ''
    pkg = TASKS_DIR / f'{task_id}.json'
    if pkg.exists():
        try:
            q = (json.loads(pkg.read_text(encoding='utf-8')).get('query') or '')
        except Exception:
            q = ''
    ql = q.lower()
    is_nvidia = ('英伟达' in q) or ('nvidia' in ql) or ('nvda' in ql)

    sections = ['财务表现 / 分部结构', '产品路线图 / 供给节奏', '估值 / 目标价', '竞争 / 出口限制 / 风险催化'] if is_nvidia else ['市场规模 / 增长', '关键玩家 / 可比公司', '政策 / 技术变化']
    extracted = {s: bullets_from_section(extract_section(text, s)) for s in sections}

    lines = [f'# Final Memo Draft - {task_id}', '']
    if is_nvidia:
        lines += [
            '## 投资摘要',
            '- 英伟达当前仍是 AI 算力主线核心受益者，财务表现与路线图证据已能支撑“深研骨架”成立。',
            '- 但现阶段对估值、出口限制、客户自研和竞争冲击的量化仍然不足，因此只能给框架版判断，不能直接下高置信投资结论。',
            '',
            '## 核心逻辑',
        ]
        for sec in sections:
            if extracted[sec]:
                lines.append(f'- {sec}：{extracted[sec][0]}')
        lines += ['', '## 分章节正文']
    else:
        lines += ['## 核心结论', '- 当前版本仍是框架版草稿，需继续补证据。', '', '## 当前研究框架']

    for sec in sections:
        lines += [f'### {sec}']
        if extracted[sec]:
            for item in extracted[sec]:
                lines.append(f'- {item}')
        else:
            lines.append('- 当前仍需补搜。')
        lines.append('')

    lines += [
        '## 当前缺口',
        '- 高质量来源密度仍不足。',
        '- 独立估值/预测附表尚未生成。',
        '- 正文仍未达到正式卖方深研标准。',
        '',
        '## 下一步建议',
        '1. 继续补高质量一手来源与卖方摘要。',
        '2. 生成更完整的估值与预测附表。',
        '3. 再做一轮正式统稿。',
    ]

    out_path = TASKS_DIR / f'{task_id}-final-memo.md'
    out_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'task_id': task_id, 'final_memo': str(out_path)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
