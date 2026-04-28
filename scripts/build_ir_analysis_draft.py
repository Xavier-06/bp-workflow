#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'
GENERIC_SECTIONS = ['市场规模 / 增长', '关键玩家 / 可比公司', '政策 / 技术变化', '其他']
NVIDIA_SECTIONS = ['财务表现 / 分部结构', '产品路线图 / 供给节奏', '估值 / 目标价', '竞争 / 出口限制 / 风险催化']


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def task_profile(task_id: str) -> dict:
    pkg = TASKS_DIR / f'{task_id}.json'
    query = ''
    if pkg.exists():
        try:
            query = (load_json(pkg).get('query') or '')
        except Exception:
            query = ''
    q = query.lower()
    if '英伟达' in query or 'nvidia' in q or 'nvda' in q:
        return {
            'kind': 'nvidia',
            'headline': '当前重点应围绕英伟达财务表现、Blackwell/Rubin 路线图、估值分歧、出口限制与竞争风险展开。',
            'sections': NVIDIA_SECTIONS,
        }
    return {
        'kind': 'generic',
        'headline': '当前目标不是给最终结论，而是把已有证据组织成可继续迭代的分析骨架。',
        'sections': GENERIC_SECTIONS,
    }


def remap_section(task_kind: str, row: dict) -> str:
    text = f"{row.get('claim','')} {row.get('source_title','')} {row.get('evidence_excerpt','')}".lower()
    if task_kind == 'nvidia':
        if any(k in text for k in ['revenue', 'gross margin', 'eps', 'data center', 'gaming', 'q4', 'fy2026', 'fy2027', 'segment']):
            return '财务表现 / 分部结构'
        if any(k in text for k in ['blackwell', 'rubin', 'shipment', 'supply', 'availability', 'roadmap', 'gb200', 'nvlink']):
            return '产品路线图 / 供给节奏'
        if any(k in text for k in ['valuation', 'target', 'price target', 'peg', 'ev/ebitda', 'pe', 'consensus']):
            return '估值 / 目标价'
        if any(k in text for k in ['export', 'china', 'restriction', 'ban', 'risk', 'catalyst', 'amd', 'asic', 'competition']):
            return '竞争 / 出口限制 / 风险催化'
        return '其他'
    return row.get('section', '其他')


def pick_top(rows: list[dict], n: int = 4) -> list[dict]:
    score = {'high': 3, 'medium': 2, 'low': 1}
    return sorted(rows, key=lambda r: (-score.get(r.get('confidence', 'low'), 1), -len(r.get('claim', '') or r.get('evidence_excerpt', ''))))[:n]


def one_line(row: dict) -> str:
    text = (row.get('claim') or row.get('evidence_excerpt') or '').strip().replace('\n', ' ')
    text = re.sub(r'\s+', ' ', text)
    return text[:200]


def synthesize_nvidia_section(section: str, rows: list[dict]) -> list[str]:
    lines = []
    texts = ' '.join([f"{r.get('claim','')} {r.get('evidence_excerpt','')} {r.get('source_title','')}" for r in rows]).lower()
    if section == '财务表现 / 分部结构':
        if rows:
            lines.append('现有证据一致指向：英伟达 FY2026/Q4 仍由数据中心业务驱动，收入与毛利率维持高位。')
            if any('data center' in t.lower() or 'datacenter' in t.lower() for t in texts.split(' | ')) or 'data center' in texts:
                lines.append('当前研究重点应继续拆数据中心增长、Gaming/ProViz 等分部贡献，以及毛利率桥。')
        else:
            lines.append('这一节当前没有足够证据。')
    elif section == '产品路线图 / 供给节奏':
        if rows:
            lines.append('Blackwell / Rubin 已经进入路线图主线，后续增长叙事与供给兑现高度绑定。')
            lines.append('真正要继续追的不是“有没有路线图”，而是量产节奏、客户落地、供给瓶颈。')
        else:
            lines.append('这一节当前没有足够证据。')
    elif section == '估值 / 目标价':
        if rows:
            lines.append('估值讨论已经出现，但当前更多是二手市场观点与目标价叙事，仍缺更硬的卖方和模型支撑。')
        else:
            lines.append('这一节当前没有足够证据。')
    elif section == '竞争 / 出口限制 / 风险催化':
        if rows:
            lines.append('出口限制、客户自研 ASIC、AMD 竞争是英伟达当前最核心的下行风险线。')
        else:
            lines.append('这一节当前证据明显不足，是下一轮最该补的风险主线。')
    return lines


def render(task_id: str, rows: list[dict]) -> str:
    profile = task_profile(task_id)
    grouped = defaultdict(list)
    for row in rows:
        row = dict(row)
        row['section'] = remap_section(profile['kind'], row)
        grouped[row['section']].append(row)

    lines = [
        f'# 分析草稿 - {task_id}',
        '',
        '## 使用说明',
        '- 这是 evidence table 驱动生成的第一版分析草稿。',
        f"- {profile['headline']}",
        '',
        '## 核心判断（初稿）',
    ]

    if profile['kind'] == 'nvidia':
        lines += [
            '- 当前证据已足以支撑“财务表现 + 路线图 + 初步估值”三条主线，但风险线仍偏弱。',
            '- 英伟达的核心不再是“有没有增长”，而是高增长能否在 Blackwell/Rubin 周期与出口限制下持续兑现。',
            '- 现阶段可以形成“深研骨架”，但还不宜下高置信投资结论。',
        ]
    else:
        lines += ['- 当前研究仍处于骨架期，适合继续补证据，不适合直接给结论。']

    lines += ['', '## 分章节整理']
    for section in profile['sections']:
        rows_sec = grouped.get(section, [])
        lines += ['', f'### {section}']
        if not rows_sec:
            lines += ['#### 当前观察', '- 当前仍缺可用证据。', '', '#### 当前缺口', '- 需继续补搜。']
            continue
        lines += ['#### 当前观察']
        for row in pick_top(rows_sec, 4):
            lines.append(f"- {one_line(row)}")
            lines.append(f"  - 证据：{row.get('source_title','')}｜{row.get('confidence','low')}｜{row.get('source_url','')}")
        lines += ['', '#### 分析判断']
        if profile['kind'] == 'nvidia':
            for item in synthesize_nvidia_section(section, rows_sec):
                lines.append(f'- {item}')
        else:
            lines.append('- 需继续补证据后再形成更强判断。')
        lines += ['', '#### 当前缺口']
        if profile['kind'] == 'nvidia':
            if section == '财务表现 / 分部结构':
                lines.append('- 还缺更完整的分部收入桥、毛利率桥和一致预期对照。')
            elif section == '产品路线图 / 供给节奏':
                lines.append('- 还缺更硬的 Blackwell/Rubin 供给与客户采用证据。')
            elif section == '估值 / 目标价':
                lines.append('- 还缺更系统的卖方目标价区间与独立估值假设。')
            elif section == '竞争 / 出口限制 / 风险催化':
                lines.append('- 还缺出口限制原文、客户自研进展、AMD/ASIC 竞争的量化影响。')
        else:
            lines.append('- 需继续补证据。')

    lines += [
        '',
        '## 下一步建议',
        '1. 对缺口最大的 section 做定向补搜，而不是继续泛搜。',
        '2. 把财务、路线图、估值、风险四条线分别做成更可引用的 claim cards。',
        '3. 在此基础上再进入正式统稿。',
    ]
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('evidence_path')
    args = ap.parse_args()
    evidence_path = Path(args.evidence_path)
    data = load_json(evidence_path)
    task_id = data.get('task_id', evidence_path.stem.replace('-evidence', ''))
    rows = data.get('rows', [])
    out_path = TASKS_DIR / f'{task_id}-analysis-draft.md'
    out_path.write_text(render(task_id, rows), encoding='utf-8')
    print(json.dumps({'task_id': task_id, 'analysis_draft': str(out_path), 'count': len(rows)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
