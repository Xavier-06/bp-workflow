#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_package')
    ap.add_argument('memo_file')
    args = ap.parse_args()

    pkg = json.loads(Path(args.task_package).read_text(encoding='utf-8'))
    memo = Path(args.memo_file).read_text(encoding='utf-8')
    task_id = pkg['task']['task_id']

    lines = [
        f'# Handoff Note - {task_id}',
        '',
        '## 给建模师',
        '- 当前暂不建议直接建完整财务模型，先统一市场规模口径。',
        '- 建模优先项：市场规模 / 增速 / 可比公司池 / 关键玩家分类。',
        '- 当前最需要补的数据：统一市场定义、中国 vs 全球口径、币种和年份对应关系。',
        '- 暂不建议过早给目标价，先把可比公司与业务分层做扎实。',
        '',
        '## 给总编辑',
        '- 当前稿件适合定位为“框架版 memo”，不宜写成确定性投资结论。',
        '- 可重点突出三点：市场增长叙事已成形、玩家格局尚未分层、监管/技术还在演进。',
        '- 需要避免：直接引用杂乱市场规模数字、把概念股混成核心受益标的、把宣传稿当政策依据。',
        '',
        '## 当前未解问题',
        '- 市场规模与增速口径仍未统一。',
        '- 可比公司池仍需按平台型 / 应用型 / 医疗IT / AI制药重新分层。',
        '- 政策/监管与技术路线还需要进一步去噪与时间线整理。',
        '',
        '## 推荐下一步',
        '1. 统一口径后补一版可比公司表。',
        '2. 整理政策/监管时间线。',
        '3. 在此基础上再写正式投资逻辑与风险收益框架。',
    ]
    out = TASKS_DIR / f'{task_id}-handoff-note.md'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'task_id': task_id, 'output': str(out)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
