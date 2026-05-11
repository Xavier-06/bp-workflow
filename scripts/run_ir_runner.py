#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

TASK_TYPE_OUTPUT = {
    '专题研究类': '研究 memo 草稿',
    '晨报类': '晨报草稿',
    '快报类': '快报草稿',
    '资料整理类': '资料整理稿',
    '回顾类': 'review 草稿',
}

QUESTION_TEMPLATES = {
    '专题研究类': [
        '研究对象具体是什么？是公司、赛道、主题还是事件？',
        '这次研究是给 Xavier 内部判断、给老板汇报，还是形成长期跟踪卡？',
        '本轮最关键的三个关注点分别是什么？',
        '希望最终输出是框架版、短 memo，还是完整长报告？',
    ],
    '晨报类': [
        '发送对象是谁？测试版还是正式版？',
        '时间窗口是过去 24 小时还是更长？',
        '今天最该保留的三类信息是什么？',
    ],
    '快报类': [
        '事件是否已确认足够重要，需要立即发送吗？',
        '当前最可靠的来源有哪些？',
        '这次快报的接收对象是谁？',
    ],
    '资料整理类': [
        '资料范围是什么？输出给谁看？',
        '需要摘要、分类还是原样归档？',
    ],
    '回顾类': [
        '回顾周期范围是什么？',
        '重点是完成项、未完成项还是关键变化？',
    ],
}


def load_task_package(task_id: str) -> tuple[Path, dict]:
    path = TASKS_DIR / f'{task_id}.json'
    if not path.exists():
        raise SystemExit(f'Task package not found: {path}')
    return path, json.loads(path.read_text(encoding='utf-8'))


def summarize_instructions(selected: list[dict]) -> list[str]:
    out = []
    for item in selected:
        key = item.get('key', '')
        desc = item.get('description', '')
        out.append(f'- {key}: {desc}')
    return out


def build_runner_output(pkg: dict) -> str:
    task = pkg['task']
    task_type = task.get('task_type', '专题研究类')
    query = pkg.get('query', task.get('title', ''))
    plan = pkg.get('execution_plan', {})
    output_kind = TASK_TYPE_OUTPUT.get(task_type, '执行草稿')
    questions = QUESTION_TEMPLATES.get(task_type, ['还有哪些边界条件需要确认？'])
    instructions = summarize_instructions(pkg.get('instructions', []))
    steps = plan.get('workflow_steps', [])

    lines = [
        f'# Runner 输出 - {task.get("task_id")}',
        '',
        '## 任务摘要',
        f'- 标题：{task.get("title")}',
        f'- 类型：{task_type}',
        f'- 用户原始需求：{query}',
        f'- 目标输出：{output_kind}',
        '',
        '## 当前系统判断',
        f'- 当前下一步：{task.get("next_action")}',
        f'- 首轮提示：{plan.get("first_step_hint", "")}',
        '',
        '## 参与角色',
    ]
    lines.extend(instructions or ['- 无'])
    lines += ['', '## 计划执行步骤']
    for i, step in enumerate(steps, 1):
        lines.append(f'{i}. {step}')
    lines += ['', '## 首轮执行草稿（主控视角）']

    if task_type == '专题研究类':
        lines += [
            '### A. 研究范围初判',
            f'- 当前判断：这是一项围绕“{query}”的专题研究任务。',
            '- 默认输出形态：先形成框架版 memo，再决定是否扩成完整研报。',
            '- 默认收件对象：Xavier 内部先看。',
            '',
            '### B. 需要尽快确认的问题',
        ]
        lines.extend([f'- {q}' for q in questions])
        lines += [
            '',
            '### C. 如果没有额外澄清，默认先做的第一轮',
            '- 先按“赛道/主题框架研究”处理，而不是单一上市公司尽调。',
            '- 先由数据收集角色拉：市场规模、增长驱动、关键玩家、政策/技术变化、可比公司。',
            '- 先给出 1 页结构化框架，再决定是否继续拆到商业模式 / 财务 / 管理层。',
            '',
            '### D. 预期第一轮交付',
            '- 一个结构化研究框架草稿',
            '- 一组待补充数据清单',
            '- 一组后续应继续深挖的问题',
        ]
    else:
        lines += [
            '### A. 首轮判断',
            f'- 当前按 {task_type} 的标准链路推进。',
            '',
            '### B. 需要确认的问题',
        ]
        lines.extend([f'- {q}' for q in questions])
        lines += [
            '',
            '### C. 第一轮默认动作',
            '- 先按 execution plan 的第 1 步执行。',
        ]

    lines += [
        '',
        '## Runner 备注',
        '- 这份文件是 task package 被执行 runner 消费后的首轮执行草稿。',
        '- 它的作用是让系统从“知道要做什么”推进到“已经开始产出第一轮执行内容”。',
        '',
        f'- 生成时间：{datetime.now().isoformat(timespec="seconds")}',
    ]
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_id')
    args = ap.parse_args()

    package_path, pkg = load_task_package(args.task_id)
    output_path = TASKS_DIR / f'{args.task_id}-runner.md'
    output_path.write_text(build_runner_output(pkg), encoding='utf-8')

    print(json.dumps({
        'task_id': args.task_id,
        'package_path': str(package_path),
        'runner_output': str(output_path),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
