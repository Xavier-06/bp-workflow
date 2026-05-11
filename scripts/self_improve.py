#!/usr/bin/env python3
from __future__ import annotations
import argparse, re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEARN = ROOT/'.learnings'
LEARN.mkdir(exist_ok=True)
FILES = {
    'learning': LEARN/'LEARNINGS.md',
    'error': LEARN/'ERRORS.md',
    'feature': LEARN/'FEATURE_REQUESTS.md',
}

for p in FILES.values():
    p.touch(exist_ok=True)


def next_id(prefix: str, path: Path) -> str:
    today = datetime.now().strftime('%Y%m%d')
    text = path.read_text(encoding='utf-8', errors='ignore')
    nums = [int(x) for x in re.findall(rf'{prefix}-{today}-(\d{{3}})', text)]
    n = max(nums) + 1 if nums else 1
    return f'{prefix}-{today}-{n:03d}'


def append(path: Path, body: str):
    old = path.read_text(encoding='utf-8', errors='ignore')
    if old and not old.endswith('\n'):
        old += '\n'
    path.write_text(old + body + '\n', encoding='utf-8')


def log_learning(summary: str, details: str, category: str, priority: str):
    path = FILES['learning']
    eid = next_id('LRN', path)
    now = datetime.now().isoformat()
    body = f'''## [{eid}] {category}

**Logged**: {now}
**Priority**: {priority}
**Status**: pending
**Area**: docs

### Summary
{summary}

### Details
{details}

### Suggested Action
Promote broadly applicable workflow/tool learnings to AGENTS.md / TOOLS.md / SOUL.md when stable.

### Metadata
- Source: conversation
- Tags: self-improvement, workspace

---
'''
    append(path, body)
    return eid


def log_error(summary: str, error_text: str, context: str, priority: str):
    path = FILES['error']
    eid = next_id('ERR', path)
    now = datetime.now().isoformat()
    body = f'''## [{eid}] workspace

**Logged**: {now}
**Priority**: {priority}
**Status**: pending
**Area**: config

### Summary
{summary}

### Error
```
{error_text}
```

### Context
{context}

### Suggested Fix
Check scripts / trigger chain / skill discovery path and patch the root cause.

### Metadata
- Reproducible: yes
- Tags: self-improvement, workspace

---
'''
    append(path, body)
    return eid


def log_feature(capability: str, user_context: str, complexity: str):
    path = FILES['feature']
    eid = next_id('FEAT', path)
    now = datetime.now().isoformat()
    body = f'''## [{eid}] workspace-capability

**Logged**: {now}
**Priority**: medium
**Status**: pending
**Area**: config

### Requested Capability
{capability}

### User Context
{user_context}

### Complexity Estimate
{complexity}

### Suggested Implementation
Add automation/script/trigger support and verify end-to-end.

### Metadata
- Frequency: first_time
- Related Features: self-improvement, memory-agent

---
'''
    append(path, body)
    return eid


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd')

    l = sp.add_parser('learning')
    l.add_argument('summary')
    l.add_argument('--details', default='')
    l.add_argument('--category', default='best_practice')
    l.add_argument('--priority', default='medium', choices=['low','medium','high','critical'])

    e = sp.add_parser('error')
    e.add_argument('summary')
    e.add_argument('--error-text', default='')
    e.add_argument('--context', default='')
    e.add_argument('--priority', default='high', choices=['low','medium','high','critical'])

    f = sp.add_parser('feature')
    f.add_argument('capability')
    f.add_argument('--user-context', default='')
    f.add_argument('--complexity', default='medium', choices=['simple','medium','complex'])

    args = ap.parse_args()
    if args.cmd == 'learning':
        print(log_learning(args.summary, args.details, args.category, args.priority))
    elif args.cmd == 'error':
        print(log_error(args.summary, args.error_text, args.context, args.priority))
    elif args.cmd == 'feature':
        print(log_feature(args.capability, args.user_context, args.complexity))
    else:
        ap.print_help(); raise SystemExit(1)

if __name__ == '__main__':
    main()
