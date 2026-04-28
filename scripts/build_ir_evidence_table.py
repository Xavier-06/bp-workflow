#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'


GENERIC_SECTION_RULES = {
    '市场规模 / 增长': ['市场规模', '增长', 'cagr', '增速', '规模'],
    '关键玩家 / 可比公司': ['公司', '龙头', '可比', '玩家', '上市', '厂商'],
    '政策 / 技术变化': ['政策', '监管', '技术', '路线', '医保', '审批', 'ai'],
}

COMPANY_SECTION_RULES = {
    '财务表现 / 分部结构': ['revenue', 'gross margin', 'datacenter', 'gaming', 'earnings', 'q4', 'fy2026', 'fy2027', 'segment'],
    '产品路线图 / 供给节奏': ['blackwell', 'rubin', 'shipment', 'supply', 'availability', 'roadmap', 'launch', 'gb200', 'nvlink'],
    '估值 / 目标价': ['valuation', 'target price', 'price target', 'consensus', 'goldman', 'jpmorgan', 'peg', 'pe', 'ev/ebitda'],
    '竞争 / 出口限制 / 风险催化': ['export', 'china', 'restriction', 'amd', 'custom asic', 'competition', 'risk', 'catalyst', 'guidance'],
}

VALID_SECTIONS = {'市场规模 / 增长', '关键玩家 / 可比公司', '政策 / 技术变化', '财务表现 / 分部结构', '产品路线图 / 供给节奏', '估值 / 目标价', '竞争 / 出口限制 / 风险催化', '关键来源清单'}
IGNORE_BULLETS = {
    '待补充', '暂未命中明确结果，待补搜。', '搜索阶段使用 Tavily 发现候选来源。', '正文阶段使用 Scrapling 抓取页面 body 并提取正文片段。'
}
IGNORE_PREFIXES = ('哪些口径', '哪些公司', '政策和技术变化里', '记录市场规模', '优先保留', '如果没有直接口径', '列出主要公司', '优先列龙头', '若有估值口径', '记录近期政策变化', '分清事实', '有时间线时优先保留')
LOW_SIGNAL_EXACT = {'Investor Resources', '## Quarterly Results', 'Rubin Readiness', '| | | | | | |'}
LOW_SIGNAL_PATTERNS = ['please enable js', 'disable any ad blocker', 'cookies', 'sign up here', 'market talk', 'roundup: market talk']
HIGH_VALUE_DOMAINS = ['reuters.com', 'bloomberg.com', 'wsj.com', 'ft.com', 'cnbc.com', 'investor.nvidia.com', 'nvidianews.nvidia.com', 'sec.gov']


def normalize_line(s: str) -> str:
    s = re.sub(r'\s+', ' ', s.strip())
    s = re.sub(r'^[\-•\d\.\s]+', '', s)
    return s


def route_section(text: str) -> str:
    t = text.lower()
    rules = COMPANY_SECTION_RULES if any(k in t for k in ['nvidia', 'nvda', 'blackwell', 'rubin', 'datacenter', 'gross margin']) else GENERIC_SECTION_RULES
    for section, kws in rules.items():
        if any(kw in t for kw in kws):
            return section
    return '其他'


def is_low_signal(title: str, claim: str, excerpt: str, url: str) -> bool:
    t = (title or '').strip()
    c = (claim or '').strip()
    e = (excerpt or '').strip().lower()
    u = (url or '').lower()
    high_value_claim = len(c) >= 80 and any(k in c.lower() for k in ['china', 'export', 'target', 'price', 'consensus', 'valuation', 'margin', 'blackwell', 'rubin', 'competition', 'asic'])
    if t in LOW_SIGNAL_EXACT or c in LOW_SIGNAL_EXACT:
        return True
    if c.startswith('|') or c.startswith('## ') or c.startswith('Investor Resources'):
        return True
    if len(c) <= 20 and not any(k in c.lower() for k in ['china', 'target', 'price', 'margin', 'blackwell', 'rubin', 'guidance']):
        return True
    combo = ' '.join([t.lower(), c.lower(), e, u])
    if any(p in combo for p in LOW_SIGNAL_PATTERNS):
        if high_value_claim and any(d in u for d in HIGH_VALUE_DOMAINS):
            return False
        return True
    return False


def confidence_score(title: str, url: str, excerpt: str, claim: str = '') -> str:
    score = 0
    u = (url or '').lower()
    c = (claim or '').strip()
    if url:
        score += 1
    if excerpt and len(excerpt) >= 80 and 'please enable js' not in excerpt.lower():
        score += 1
    if len(c) >= 80:
        score += 1
    if any(x in u for x in HIGH_VALUE_DOMAINS):
        score += 2
    if any(x in u for x in ['gov', 'edu', 'official']):
        score += 1
    if any(x in title for x in ['报告', '市场规模', '监管', '产业链', '龙头', 'target', 'price', 'guidance']):
        score += 1
    if score >= 5:
        return 'high'
    if score >= 3:
        return 'medium'
    return 'low'


def should_ignore_bullet(text: str, section: str) -> bool:
    if section not in VALID_SECTIONS:
        return True
    if not text or text in IGNORE_BULLETS:
        return True
    if any(text.startswith(p) for p in IGNORE_PREFIXES):
        return True
    if text in {'查询列表', '建议来源', '当前已填内容', '待验证 / 待补资料', '采集说明'}:
        return True
    return False


def parse_packet(path: Path):
    lines = path.read_text(encoding='utf-8').splitlines()
    rows = []
    section = '其他'
    current = None
    for raw in lines:
        line = raw.rstrip()
        if line.startswith('## '):
            section = line[3:].strip()
            current = None
            continue
        if line.startswith('### '):
            # subsection markers like 查询列表/建议来源/采集说明/当前已填内容
            current = None
            continue
        if line.startswith('- ') and '｜' not in line and not line.startswith('- 所属任务') and not line.startswith('- 原始需求') and not line.startswith('- 规范化主题') and not line.startswith('- 查询数量') and not line.startswith('- 命中结果') and not line.startswith('- 生成时间'):
            text = normalize_line(line)
            if should_ignore_bullet(text, section):
                continue
            current = {
                'section': section,
                'source_title': text,
                'claim': '',
                'evidence_excerpt': '',
                'source_url': '',
                'source_type': 'web',
            }
            rows.append(current)
            continue
        if current is None:
            continue
        if 'Tavily 摘要：' in line or '摘要：' in line:
            current['claim'] = normalize_line(line.split('：', 1)[1])
        elif 'Scrapling 正文摘录：' in line or '正文摘录：' in line:
            current['evidence_excerpt'] = normalize_line(line.split('：', 1)[1])
        elif '来源：' in line:
            src = line.split('来源：', 1)[1].strip()
            current['source_url'] = src.split()[-1] if src else ''
            if current['source_url'].lower().endswith('.pdf') or '.pdf?' in current['source_url'].lower():
                current['source_type'] = 'pdf'

    dedup = []
    seen = set()
    for r in rows:
        # require at least one of claim/excerpt/url to avoid template/query pollution
        if not (r['claim'] or r['evidence_excerpt'] or r['source_url']):
            continue
        if is_low_signal(r['source_title'], r['claim'], r['evidence_excerpt'], r['source_url']):
            continue
        key = (r['source_title'], r['source_url'], r['claim'][:80])
        if key in seen:
            continue
        seen.add(key)
        text = f"{r['source_title']} {r['claim']} {r['evidence_excerpt']}"
        r['section'] = route_section(text)
        r['confidence'] = confidence_score(r['source_title'], r['source_url'], r['evidence_excerpt'], r['claim'])
        dedup.append(r)
    return dedup


def render_md(rows: list[dict], task_id: str) -> str:
    lines = [
        f'# Evidence Table - {task_id}',
        '',
        '| Section | Claim | Source | Type | Confidence |',
        '|---|---|---|---|---|',
    ]
    for r in rows:
        claim = (r['claim'] or r['evidence_excerpt'] or '')[:120].replace('|', '｜')
        source = f"[{r['source_title'][:48]}]({r['source_url']})" if r['source_url'] else r['source_title'][:48]
        lines.append(f"| {r['section']} | {claim} | {source} | {r['source_type']} | {r['confidence']} |")
    lines += ['', '## Notes', '- 这是一版结构化证据表，用来给后续分析层和 reviewer 使用。', '- claim 为摘要层结论，evidence_excerpt 为正文证据片段。']
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('packet_path')
    args = ap.parse_args()
    packet_path = Path(args.packet_path)
    rows = parse_packet(packet_path)
    task_id = packet_path.name.split('-S')[0]
    json_path = TASKS_DIR / f'{task_id}-evidence.json'
    md_path = TASKS_DIR / f'{task_id}-evidence.md'
    json_path.write_text(json.dumps({'task_id': task_id, 'rows': rows}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    md_path.write_text(render_md(rows, task_id), encoding='utf-8')
    print(json.dumps({'task_id': task_id, 'json_path': str(json_path), 'md_path': str(md_path), 'count': len(rows)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
