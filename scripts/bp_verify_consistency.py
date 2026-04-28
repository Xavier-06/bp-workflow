#!/usr/bin/env python3
"""
BP 一致性验证（修正版）
- 读取真正的 phase4 输出文件：bp_step4_*.md
- 检查内部痕迹、占位词、结论矛盾
"""
import argparse
import json
import re
from pathlib import Path
from datetime import datetime

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / 'tasks'

LEAK_PATTERNS = [
    (r'/Users/\S+', '内部文件路径'),
    (r'file://\S+', '内部文件 URI'),
    (r'TASK-[\dA-Z-]+', '任务 ID'),
    (r'sessions_spawn', '会话派发指令'),
    (r'\bsubagent\b', '子代理术语'),
    (r'instruction_store\w*', '指令库路径'),
    (r'\.openclaw/\S+', 'OpenClaw 内部路径'),
    (r'scripts/[^\s,.;]+\.py', '脚本路径'),
    (r'thinking=high', '推理参数'),
    (r'Step [0-5]', 'Step 编号'),
    (r'下游子代理', '内部术语'),
    (r'搜索词组合', '内部术语'),
    (r'主控必须', '内部指令'),
]

PLACEHOLDER_PATTERNS = [
    (r'未识[别]?','占位提示：未识别'),
    (r'待补充','占位提示：待补充'),
    (r'需[a-zA-Z\u4e00-\u9fa5]*手动','占位提示：需手动'),
    (r'TODO|XXX','占位提示：TODO/XXX'),
]


def read_steps(task_dir: Path) -> dict:
    mapping = {
        'team': 'bp_step4_team.md',
        'tech': 'bp_step4_tech.md',
        'industry': 'bp_step4_industry.md',
        'competition': 'bp_step4_competition.md',
    }
    out = {}
    for k, fn in mapping.items():
        fp = task_dir / fn
        out[k] = fp.read_text(encoding='utf-8') if fp.exists() else ''
    return out


def check_leaks(text: str) -> list:
    issues = []
    for pattern, label in LEAK_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            issues.append({'type': 'leak', 'label': label, 'count': len(matches), 'examples': list(set(matches))[:3], 'severity': 'error'})
    return issues


def check_placeholders(text: str) -> list:
    issues = []
    for pattern, label in PLACEHOLDER_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            issues.append({'type': 'placeholder', 'label': label, 'count': len(matches), 'examples': list(set(matches))[:3], 'severity': 'warn'})
    return issues


def check_consistency(steps: dict) -> list:
    issues = []
    all_text = '\n'.join(steps.values())
    negative = '不建议' in all_text or '谨慎' in all_text
    positive = '建议推进' in all_text or '推荐' in all_text
    if negative and positive:
        issues.append({'type': 'data_inconsistency', 'label': '存在负面结论与正面推荐并存', 'severity': 'error'})
    return issues


def run(task_id: str) -> dict:
    task_dir = TASKS_DIR / task_id
    steps = read_steps(task_dir)
    all_text = '\n'.join([t for t in steps.values() if t])
    issues = []
    issues.extend(check_leaks(all_text))
    issues.extend(check_placeholders(all_text))
    issues.extend(check_consistency(steps))

    errors = [i for i in issues if i.get('severity') == 'error']
    warns = [i for i in issues if i.get('severity') == 'warn']
    verdict = 'FAIL' if errors else ('WARN' if warns else 'PASS')

    result = {
        'task_id': task_id,
        'verdict': verdict,
        'total_issues': len(issues),
        'errors': len(errors),
        'warnings': len(warns),
        'issues': issues,
        'checked_at': datetime.now().isoformat(),
    }
    (task_dir / 'bp_verify_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{verdict} | issues={len(issues)}')
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task-id', required=True)
    args = ap.parse_args()
    res = run(args.task_id)
    raise SystemExit(0 if res['verdict'] != 'FAIL' else 2)


if __name__ == '__main__':
    main()
