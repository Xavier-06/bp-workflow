#!/usr/bin/env python3
from __future__ import annotations
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = ROOT / 'memory'
HOT_DIR = MEMORY_DIR / 'hot'
WARM_DIR = MEMORY_DIR / 'warm'
HOT_FILE = HOT_DIR / 'HOT_MEMORY.md'
WARM_FILE = WARM_DIR / 'WARM_MEMORY.md'
STATE_FILE = MEMORY_DIR / 'tiering-state.json'
USER_FILE = ROOT / 'USER.md'
LONG_FILE = ROOT / 'MEMORY.md'
TASKS_FILE = MEMORY_DIR / 'tasks.md'


def read_text(path: Path) -> str:
    if not path.exists():
        return ''
    return path.read_text(encoding='utf-8', errors='ignore')


def ensure_dirs():
    HOT_DIR.mkdir(parents=True, exist_ok=True)
    WARM_DIR.mkdir(parents=True, exist_ok=True)


def extract_section(text: str, heading: str) -> str:
    pattern = rf"^## {re.escape(heading)}\n(.*?)(?=\n## |\Z)"
    m = re.search(pattern, text, flags=re.S | re.M)
    return m.group(1).strip() if m else ''


def parse_active_tasks(tasks_md: str) -> list[dict]:
    items = []
    blocks = re.split(r'\n(?=## \[)', tasks_md)
    for block in blocks:
        if not block.startswith('## ['):
            continue
        lines = [x.rstrip() for x in block.splitlines() if x.strip()]
        title = re.sub(r'^## \[[^\]]+\]\s*', '', lines[0]).strip()
        status = next((l.split(':', 1)[1].strip() for l in lines if l.startswith('- **Status**:')), '')
        if '完成' in status or '失败' in status:
            continue
        updated = next((l.split(':', 1)[1].strip() for l in lines if l.startswith('- **Updated**:')), '')
        notes = next((l.split(':', 1)[1].strip() for l in lines if l.startswith('- **Notes**:')), '')
        result = next((l.split(':', 1)[1].strip() for l in lines if l.startswith('- **Result**:')), '')
        items.append({'title': title, 'status': status, 'updated': updated, 'notes': notes, 'result': result})
    return items[:5]


def today_file() -> Path:
    return MEMORY_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.md"


def build_hot() -> str:
    tasks = parse_active_tasks(read_text(TASKS_FILE))
    today = read_text(today_file())
    todos = extract_section(today, '待办')
    decisions = extract_section(today, '重要决定')

    lines = [
        '# HOT Memory',
        '',
        f'- Updated: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        '- Purpose: 当前活跃任务、最近决策、下一步动作。只保留短期必须用的信息。',
        '',
        '## Active Tasks',
    ]
    if tasks:
        for idx, t in enumerate(tasks, 1):
            lines += [
                f'{idx}. {t["title"]}',
                f'   - 状态: {t["status"]}',
                f'   - 更新: {t["updated"]}',
                f'   - 下一步/备注: {t["notes"] or t["result"] or "（无）"}',
            ]
    else:
        lines.append('（无）')

    lines += ['', '## Today Decisions']
    if decisions:
        for line in decisions.splitlines():
            if line.strip():
                lines.append(line)
    else:
        lines.append('（无）')

    lines += ['', '## Today TODO']
    if todos:
        for line in todos.splitlines():
            if line.strip():
                lines.append(line)
    else:
        lines.append('（无）')

    lines += [
        '',
        '## HOT Rules',
        '- 只保留未来 1-3 次对话内真的会用到的信息。',
        '- 已完成任务不要留在 HOT。',
        '- 不存明文密钥，只存根路径或引用。',
        '',
    ]
    return '\n'.join(lines)


def build_warm() -> str:
    user = read_text(USER_FILE)
    long = read_text(LONG_FILE)

    def find_bullets(text: str, keys: list[str]) -> list[str]:
        out = []
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith('|'):
                continue
            if s.startswith('#') and not any(k in s for k in keys):
                continue
            if any(k in s for k in keys):
                out.append(s)
        return out

    prefs = find_bullets(user + '\n' + long, ['Communication style', 'Work style', '痛点', '称呼', '时区', '终极目标', '核心目标'])
    rules = [
        '- review / 记忆更新默认：update existing > append duplicate',
        '- 子代理派单必须按依赖顺序：先数据/来源/骨架，再分析，再写作',
        '- 最终 Word 表格由主控按模板生成，不靠通用 markdown 粗转',
        '- writer 只在章节齐全后启动；reviewer 只在 final draft 存在后启动',
        '- heartbeat 默认旁路巡检，不进入主执行链',
    ]

    lines = [
        '# WARM Memory',
        '',
        f'- Updated: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        '- Purpose: 用户长期偏好、稳定工作方式、已固化 workflow 规则。',
        '',
        '## Stable User Context',
    ]
    lines += prefs or ['（无）']
    lines += ['', '## Stable Workflow Rules']
    lines += rules
    lines += ['', '## References', '- USER.md', '- MEMORY.md', '- AGENTS.md', '- TOOLS.md', '']
    return '\n'.join(lines)


def main():
    ensure_dirs()
    HOT_FILE.write_text(build_hot(), encoding='utf-8')
    WARM_FILE.write_text(build_warm(), encoding='utf-8')
    state = {
        'updated_at': datetime.now().isoformat(timespec='seconds'),
        'hot_file': str(HOT_FILE),
        'warm_file': str(WARM_FILE),
        'today_file': str(today_file()),
        'active_tasks_count': len(parse_active_tasks(read_text(TASKS_FILE))),
        'mode': 'daily-tiering',
    }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
