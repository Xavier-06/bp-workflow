#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

SECTION_PROMPTS = {
    '市场规模 / 增长': [
        '记录市场规模、历史增长率、未来预期增速。',
        '优先保留带年份和来源的数字。',
        '如果没有直接口径，标记“待补充”。',
    ],
    '关键玩家 / 可比公司': [
        '列出主要公司、定位、竞争关系。',
        '优先列龙头、潜在挑战者、可比上市公司。',
        '若有估值口径，写明来源与日期。',
    ],
    '政策 / 技术变化': [
        '记录近期政策变化、监管表态、技术路线变化。',
        '分清事实、行业判断、潜在影响。',
        '有时间线时优先保留。',
    ],
    '初步来源清单': [
        '记录已经找到的来源和待搜来源。',
        '尽量按机构/官网/媒体分类。',
        '每条来源附一句用途说明。',
    ],
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def render_packet(plan: dict) -> str:
    lines = [
        f"# 资料包草稿 - {plan.get('subtask_id')}",
        '',
        f"- 所属任务：{plan.get('task_id')}",
        f"- 生成时间：{plan.get('generated_at')}",
        '',
        '## 研究子问题',
    ]
    for q in plan.get('sub_questions', []):
        lines.append(f'- {q}')
    lines += ['', '## 搜索计划摘要', '### 查询分组']
    for group in plan.get('query_groups', []):
        lines.append(f"- 子问题：{group.get('sub_question')}")
        for q in group.get('queries', []):
            lines.append(f"  - 查询：{q}")
    lines += ['', '### 建议来源']
    for s in plan.get('source_hints', []):
        lines.append(f'- {s}')

    for section in plan.get('expected_sections', []):
        lines += ['', f'## {section}', '### 采集说明']
        for item in SECTION_PROMPTS.get(section, ['- 待补充']):
            lines.append(f'- {item}')
        lines += ['','### 当前已填内容','- 待补充','','### 待验证 / 待补资料','- 待补充']

    lines += [
        '',
        '## 资料包使用说明',
        '- 这是第一轮资料包草稿模板，目的是把搜索计划转成可逐步填充的研究材料。',
        '- 后续真实搜索结果应优先写进对应章节，而不是散落在聊天里。',
        '- 所有数字、判断、引用都应尽量附来源与日期。',
        '',
        f'- 模板生成时间：{datetime.now().isoformat(timespec="seconds")}',
    ]
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('search_plan_path')
    args = ap.parse_args()

    plan_path = Path(args.search_plan_path)
    if not plan_path.exists():
        raise SystemExit(f'search plan not found: {plan_path}')
    plan = load_json(plan_path)
    out_path = TASKS_DIR / f"{plan['subtask_id']}-packet.md"
    out_path.write_text(render_packet(plan), encoding='utf-8')
    print(json.dumps({'subtask_id': plan['subtask_id'], 'packet_path': str(out_path)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
