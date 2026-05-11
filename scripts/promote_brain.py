#!/usr/bin/env python3
from __future__ import annotations
import re
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = ROOT / 'memory'
BRAIN_FILE = ROOT / 'brain.md'

SECTION_SCORES = {
    '重要决定': 5,
    '学到的教训': 4,
    '问题': 2,
    '修复': 3,
    '待办': 1,
    '今日事项': 1,
}

KEYWORDS = {
    '必须': 3, '以后': 3, '决定': 3, '不要': 3, '记住': 3,
    '已配置': 2, '运行中': 2, '规则': 2, '教训': 2, '错误': 2,
    '偏好': 2, '习惯': 2, 'launchd': 2, 'memory-agent': 2,
}

MAX_ITEMS = 8
DAYS_BACK = 14
ANCHOR = '## 自动晋升（高分日志）'


def recent_memory_files():
    today = date.today()
    files = []
    for i in range(DAYS_BACK):
        d = today - timedelta(days=i)
        p = MEMORY_DIR / f'{d.isoformat()}.md'
        if p.exists():
            files.append(p)
    return sorted(files)


def score_item(section: str, text: str) -> int:
    score = SECTION_SCORES.get(section, 0)
    for kw, pts in KEYWORDS.items():
        if kw in text:
            score += pts
    if len(text) > 80:
        score += 1
    if any(x in text for x in ['一次性', '临时', '当前模型', '版本号', 'session']):
        score -= 5
    return score


def extract_candidates(path: Path):
    section = ''
    candidates = []
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if line.startswith('## '):
            section = line[3:].strip()
            continue
        if not line:
            continue
        if line.startswith(('- ', '* ')):
            text = re.sub(r'^[-*]\s+', '', line)
            score = score_item(section, text)
            if score >= 5:
                candidates.append((score, path.stem, section, text))
    return candidates


def update_brain(items):
    if not BRAIN_FILE.exists():
        return 0
    content = BRAIN_FILE.read_text(encoding='utf-8')
    existing = content
    chosen = []
    seen_texts = set()
    for score, day, section, text in sorted(items, key=lambda x: (-x[0], x[1], x[3])):
        if text in seen_texts:
            continue
        if text in existing:
            continue
        chosen.append((score, day, section, text))
        seen_texts.add(text)
        if len(chosen) >= MAX_ITEMS:
            break
    if not chosen:
        return 0

    block = [ANCHOR, '']
    for score, day, section, text in chosen:
        block.append(f'- [{day}] ({section}, score={score}) {text}')
    block.append('')
    block_text = '\n'.join(block)

    if ANCHOR in content:
        content = re.sub(rf'{re.escape(ANCHOR)}[\s\S]*?(\n## |\Z)', block_text + '\n\\1', content, count=1)
    else:
        content = content.rstrip() + '\n\n---\n\n' + block_text
    BRAIN_FILE.write_text(content, encoding='utf-8')
    return len(chosen)


def main():
    items = []
    for p in recent_memory_files():
        items.extend(extract_candidates(p))
    count = update_brain(items)
    print(f'promoted={count}')


if __name__ == '__main__':
    main()
