#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess, re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TODAY = ROOT/'memory'/f'{date.today().isoformat()}.md'
LEARN = ROOT/'.learnings'/'LEARNINGS.md'
ERRORS = ROOT/'.learnings'/'ERRORS.md'
FEATURES = ROOT/'.learnings'/'FEATURE_REQUESTS.md'
FILES = [
    'skills/using-superpowers/SKILL.md',
    'brain.md',
    'SOUL.md',
    'USER.md',
]


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return {'code': p.returncode, 'stdout': p.stdout.strip(), 'stderr': p.stderr.strip()}


def pending_count(path: Path) -> int:
    if not path.exists():
        return 0
    text = path.read_text(encoding='utf-8', errors='ignore')
    return len(re.findall(r'\*\*Status\*\*: pending', text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('message', nargs='?', default='')
    args = ap.parse_args()

    checks = {
        'required_files': [],
        'today_memory_exists': TODAY.exists(),
        'memory_check': None,
        'skills_script': None,
        'learnings_review': {
            'files_exist': {
                'LEARNINGS.md': LEARN.exists(),
                'ERRORS.md': ERRORS.exists(),
                'FEATURE_REQUESTS.md': FEATURES.exists(),
            },
            'pending_counts': {
                'learnings': pending_count(LEARN),
                'errors': pending_count(ERRORS),
                'features': pending_count(FEATURES),
            },
            'review_hint': 'Before major tasks, review pending learnings/errors/features if counts are non-zero.'
        }
    }

    for rel in FILES:
        p = ROOT / rel
        checks['required_files'].append({'file': rel, 'exists': p.exists()})

    if args.message:
        checks['memory_check'] = run(['python3', str(ROOT/'scripts'/'memory_auto.py'), 'check', args.message])
    checks['skills_script'] = run(['bash', str(ROOT/'scripts'/'check-skills.sh')])

    print(json.dumps(checks, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
