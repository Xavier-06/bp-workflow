#!/usr/bin/env python3
"""
filter_ir_evidence.py — 证据过滤（含域名黑名单 + 置信度 + reviewer 问题）

在 evidence 收集后、进入分析/写作前运行。
过滤掉无关来源、低质量来源、垃圾来源。

增加：
    - 域名黑名单（stackoverflow, npmjs, google fonts 等）
    - URL 模式黑名单（搜索页面、错误页面）
    - 过时证据降级（发布时间超过 2 年且非年报/披露类）
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

# 引用共享黑名单模块
from ir_evidence_blacklist import is_blacklisted_domain, is_blacklisted_url

# ─── 过时证据阈值 ─────────────────────────────────
# 超过此天数的非披露类来源降级为 low confidence
STALE_THRESHOLD_DAYS = 730  # 2 年

# 例外：这些来源类型即使过时也保留（年报/季报/监管披露）
STALE_EXEMPT_FAMILIES = {
    'filings', 'official', 'official_newsroom', 'annual_report',
    'quarterly_report', 'regulatory',
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def is_stale(row: dict) -> bool:
    """检查证据是否过时"""
    published = row.get('published_at', '') or ''
    if not published:
        return False  # 没有发布日期不判定过时

    source_family = row.get('source_family', '') or ''
    if source_family in STALE_EXEMPT_FAMILIES:
        return False

    try:
        # 尝试解析日期
        for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d', '%Y/%m/%d']:
            try:
                pub_date = datetime.strptime(published[:19], fmt)
                if (datetime.now() - pub_date) > timedelta(days=STALE_THRESHOLD_DAYS):
                    return True
                return False
            except ValueError:
                continue
    except Exception:
        pass
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('evidence_json')
    ap.add_argument('reviewer_json')
    args = ap.parse_args()

    evidence = load_json(Path(args.evidence_json))
    reviewer = load_json(Path(args.reviewer_json))
    task_id = evidence.get('task_id')

    # Build issue map from reviewer
    issue_map = {}
    for item in reviewer.get('issues', []):
        title = item.get('source_title')
        if not title:
            continue
        issue_map.setdefault(title, []).append(item)

    kept = []
    dropped = []

    for row in evidence.get('rows', []):
        url = row.get('source_url', '') or row.get('url', '') or ''
        title = row.get('source_title', '') or row.get('title', '') or ''

        # 1. 域名黑名单
        if is_blacklisted_domain(url):
            dropped.append({'row': row, 'reason': 'domain-blacklist', 'detail': url})
            continue

        # 2. URL 模式黑名单
        if is_blacklisted_url(url):
            dropped.append({'row': row, 'reason': 'url-pattern-blacklist', 'detail': url})
            continue

        # 3. Reviewer 标记的高噪音
        issues = issue_map.get(title, [])
        severities = {i.get('severity') for i in issues}
        types = {i.get('type') for i in issues}
        if 'high' in severities and 'noise' in types:
            dropped.append({'row': row, 'reason': 'high-noise'})
            continue

        # 4. 低置信度
        if row.get('confidence') == 'low':
            dropped.append({'row': row, 'reason': 'low-confidence'})
            continue

        # 5. 过时证据降级
        if is_stale(row):
            dropped.append({'row': row, 'reason': 'stale-evidence', 'detail': row.get('published_at', '')})
            continue

        kept.append(row)

    out = {
        'task_id': task_id,
        'kept_count': len(kept),
        'dropped_count': len(dropped),
        'rows': kept,
        'dropped': dropped,
    }

    json_path = TASKS_DIR / f'{task_id}-evidence-clean.json'
    md_path = TASKS_DIR / f'{task_id}-evidence-clean.md'
    json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    lines = [
        f'# Clean Evidence - {task_id}',
        '',
        f'- 保留证据：{len(kept)}',
        f'- 剔除证据：{len(dropped)}',
        '',
        '## 保留证据',
    ]
    for row in kept:
        lines.append(f"- [{row.get('section', '')}] {row.get('source_title', '')}｜{row.get('confidence', '')}｜{row.get('source_url', '')}")
    lines += ['', '## 剔除证据']
    for item in dropped:
        row = item['row']
        reason = item['reason']
        detail = item.get('detail', '')
        lines.append(f"- [{reason}] {row.get('source_title', '')}｜{row.get('source_url', '')} {('(' + detail + ')') if detail else ''}")

    md_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({
        'task_id': task_id,
        'clean_json': str(json_path),
        'clean_md': str(md_path),
        'kept': len(kept),
        'dropped': len(dropped),
        'drop_reasons': {r['reason']: sum(1 for d in dropped if d['reason'] == r['reason']) for r in dropped},
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
