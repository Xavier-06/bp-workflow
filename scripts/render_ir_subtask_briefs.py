#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

SUBTASK_GUIDANCE = {
    'scope-clarification': {
        'questions': [
            '研究对象是公司、赛道、主题还是事件？',
            '这次输出给谁看？内部判断还是正式汇报？',
            '最终希望产出框架版、短 memo 还是完整长报告？',
            '本轮最关键的 3 个关注点是什么？',
        ],
        'default_actions': [
            '把研究对象、研究目标、输出形式先写清楚。',
            '如果没有更多澄清，先按“赛道框架研究”处理。',
            '把后续数据收集范围限定在市场规模、关键玩家、政策/技术变化、可比公司。',
        ]
    },
    'data-collection': {
        'questions': [
            '优先收哪些维度：市场规模、关键玩家、政策、技术、可比公司、财务？',
            '时间范围是过去 1 年、3 年，还是更长？',
            '本轮是否只要公开信息，不碰付费数据库？',
        ],
        'default_actions': [
            '优先拉公开来源：行业报告摘要、公司官网、公告、政策文件、主流媒体、研究综述。',
            '先做结构化材料包，不急着长篇分析。',
            '每个关键数字必须带来源和日期。',
        ]
    },
    'industry-analysis': {
        'questions': [
            '这次更偏行业概览、竞争格局，还是投资逻辑拆解？',
            '需要覆盖哪些比较维度：增长驱动、竞争格局、政策、估值、风险？',
            '输出希望偏框架，还是偏初步判断？',
        ],
        'default_actions': [
            '先搭出行业分析骨架，再往里填数据。',
            '必须包含增长驱动、竞争格局、关键变量、风险点。',
            '先产出框架草稿，不抢跑到完整结论。',
        ]
    },
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def render_one(subtask: dict) -> str:
    kind = subtask.get('subtask_type', '')
    g = SUBTASK_GUIDANCE.get(kind, {'questions': ['还需要确认哪些边界条件？'], 'default_actions': ['按任务目标推进。']})
    lines = [
        f"# 子任务执行草稿 - {subtask.get('subtask_id')}",
        '',
        f"- 所属任务：{subtask.get('task_id')}",
        f"- 子任务类型：{subtask.get('subtask_type')}",
        f"- 负责人：{subtask.get('owner')}",
        f"- 标题：{subtask.get('title')}",
        f"- 目标：{subtask.get('goal')}",
        f"- 交付物：{subtask.get('deliverable')}",
        '',
        '## 子任务上下文',
        f"- 用户问题：{subtask.get('context', {}).get('query', '')}",
        f"- 任务类型：{subtask.get('context', {}).get('task_type', '')}",
        f"- 指令角色：{', '.join(subtask.get('context', {}).get('instruction_keys', []))}",
        '',
        '## 优先确认的问题',
    ]
    lines.extend([f'- {q}' for q in g['questions']])
    lines += ['', '## 默认执行动作']
    lines.extend([f'- {a}' for a in g['default_actions']])
    lines += [
        '',
        '## 预期输出结构',
        f'- 先给出一版 {subtask.get("deliverable")}',
        '- 明确哪些地方已经有依据，哪些地方还需要补资料',
        '- 不编造，不把未确认内容写成结论',
        '',
        '## 生成说明',
        f'- 生成时间：{datetime.now().isoformat(timespec="seconds")}',
    ]
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_id')
    args = ap.parse_args()

    subtasks_path = TASKS_DIR / f'{args.task_id}-subtasks.json'
    if not subtasks_path.exists():
        raise SystemExit(f'subtasks file not found: {subtasks_path}')
    data = load_json(subtasks_path)
    outputs = []
    for subtask in data.get('subtasks', []):
        out_path = TASKS_DIR / f"{subtask['subtask_id']}.md"
        out_path.write_text(render_one(subtask), encoding='utf-8')
        outputs.append({'subtask_id': subtask['subtask_id'], 'path': str(out_path)})
    print(json.dumps({'task_id': args.task_id, 'count': len(outputs), 'outputs': outputs}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
