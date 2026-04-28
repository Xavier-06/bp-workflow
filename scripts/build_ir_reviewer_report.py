#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

BAD_PATTERNS = [
    ('boilerplate', r'Action Another action|定制请求 获取广泛的市场洞察|数据库云登录|Toggle navigation'),
    ('pdf-binary', r'%PDF-\d'),
    ('html-noise', r'<[^>]+>|首页 新闻 体育 财经|财经 焦点 股票'),
]


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def extract_numbers(text: str) -> dict:
    percents = re.findall(r'(\d+(?:\.\d+)?)\s*%', text)
    amounts = re.findall(r'(\d+(?:\.\d+)?)\s*(万亿|亿元|亿美元|billion|million)', text, flags=re.I)
    years = re.findall(r'20\d{2}', text)
    return {
        'percents': sorted(set(percents)),
        'amounts': sorted(set([f'{a}{u}' for a, u in amounts])),
        'years': sorted(set(years)),
    }


def review_rows(rows: list[dict]) -> dict:
    issues = []
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get('section', '其他')].append(row)

    for row in rows:
        claim = row.get('claim', '') or ''
        excerpt = row.get('evidence_excerpt', '') or ''
        merged = f'{claim} {excerpt}'
        for label, pat in BAD_PATTERNS:
            if re.search(pat, merged, flags=re.I):
                issues.append({
                    'type': 'noise',
                    'severity': 'high' if label in ('pdf-binary', 'boilerplate') else 'medium',
                    'section': row.get('section'),
                    'source_title': row.get('source_title'),
                    'detail': f'检测到 {label} 噪音',
                })
                break
        if row.get('confidence') == 'low':
            issues.append({
                'type': 'confidence',
                'severity': 'medium',
                'section': row.get('section'),
                'source_title': row.get('source_title'),
                'detail': '该证据置信度较低，建议后续补强或降权处理',
            })

    # conflict scan for market size / growth
    growth_rows = grouped.get('市场规模 / 增长', [])
    percent_bag = defaultdict(list)
    amount_bag = defaultdict(list)
    for row in growth_rows:
        nums = extract_numbers(f"{row.get('claim','')} {row.get('evidence_excerpt','')}")
        for p in nums['percents']:
            percent_bag[p].append(row.get('source_title'))
        for a in nums['amounts']:
            amount_bag[a].append(row.get('source_title'))
    if len(percent_bag) >= 3:
        issues.append({
            'type': 'conflict',
            'severity': 'medium',
            'section': '市场规模 / 增长',
            'source_title': None,
            'detail': f'增长率口径较多，当前抓到 {list(percent_bag.keys())[:6]}，需要统一时间区间与口径',
        })
    if len(amount_bag) >= 3:
        issues.append({
            'type': 'conflict',
            'severity': 'medium',
            'section': '市场规模 / 增长',
            'source_title': None,
            'detail': f'市场规模口径较多，当前抓到 {list(amount_bag.keys())[:6]}，需要统一市场定义与币种',
        })

    summary = {
        'issue_count': len(issues),
        'high': sum(1 for x in issues if x['severity'] == 'high'),
        'medium': sum(1 for x in issues if x['severity'] == 'medium'),
        'low': sum(1 for x in issues if x['severity'] == 'low'),
    }
    return {'summary': summary, 'issues': issues}


def render_md(task_id: str, review: dict) -> str:
    lines = [
        f'# Reviewer Report - {task_id}',
        '',
        '## 审稿摘要',
        f"- 问题总数：{review['summary']['issue_count']}",
        f"- 高优先级：{review['summary']['high']}",
        f"- 中优先级：{review['summary']['medium']}",
        f"- 低优先级：{review['summary']['low']}",
        '',
        '## 主要问题',
    ]
    if not review['issues']:
        lines.append('- 暂未发现明显问题。')
    else:
        for item in review['issues']:
            who = f"｜{item['source_title']}" if item.get('source_title') else ''
            lines.append(f"- [{item['severity']}] {item['section']}｜{item['type']}{who}：{item['detail']}")
    lines += [
        '',
        '## 审稿建议',
        '1. 先清洗高噪音来源（特别是 PDF 二进制残留和模板站 boilerplate）。',
        '2. 对市场规模/增长率建立统一口径，不同报告必须标明年份、币种、范围。',
        '3. 对低置信度与宣传味来源降权，优先保留机构报告、监管文件、官网来源。',
        '4. analysis draft 应只引用 reviewer 通过的证据条目。',
    ]
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('evidence_json')
    args = ap.parse_args()
    p = Path(args.evidence_json)
    data = load_json(p)
    task_id = data.get('task_id', p.stem.replace('-evidence', ''))
    review = review_rows(data.get('rows', []))
    out_json = TASKS_DIR / f'{task_id}-reviewer.json'
    out_md = TASKS_DIR / f'{task_id}-reviewer.md'
    out_json.write_text(json.dumps({'task_id': task_id, **review}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    out_md.write_text(render_md(task_id, review), encoding='utf-8')
    print(json.dumps({'task_id': task_id, 'reviewer_json': str(out_json), 'reviewer_md': str(out_md), 'summary': review['summary']}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
