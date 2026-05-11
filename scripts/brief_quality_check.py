#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parent.parent
RECIPIENTS = ROOT / 'config' / 'recipients.json'

PLACEHOLDER_PATTERNS = [
    r'TODO',
    r'在此粘贴',
    r'示例指令',
    r'placeholder',
]

KIND_RULES = {
    'iran': {
        'min_paragraphs': 18,
        'min_chars': 1000,
        'min_sources': 4,
        'topic_keywords': ['伊朗', '美国', '霍尔木兹', '油价', '谈判', '中东'],
        'required_sections': ['核心结论', '战事进展', '外交表态', '市场影响', '中国相关', '重点观察', '说明'],
        'manual_review_warn_phrase': '建议稍后人工复核',
    },
    'crypto': {
        'min_paragraphs': 18,
        'min_chars': 1000,
        'min_sources': 4,
        'topic_keywords': ['比特币', '以太坊', '加密', 'ETF', 'BTC', 'ETH', 'SEC', 'Fed', 'CPI', 'PPI'],
        'required_sections': ['市场概览', '隔夜行情', '宏观', '监管', 'ETF', '机构动态', '市场驱动因素', '今日关注', '说明'],
        'manual_review_warn_phrase': '该部分今晨公开新闻结果不足',
    },
    'asset': {
        'min_paragraphs': 16,
        'min_chars': 800,
        'min_sources': 4,
        'topic_keywords': ['美元', '美债', '黄金', '加密货币', 'Fed', '收益率', '风险提示'],
        'required_sections': ['核心观点', '美元', '美债', '黄金', '加密货币', '联动观察', '今日总结', '风险提示', '说明'],
        'manual_review_warn_phrase': '建议稍后人工复核',
    },
    'generic': {
        'min_paragraphs': 10,
        'min_chars': 400,
        'min_sources': 0,
        'topic_keywords': [],
        'required_sections': [],
        'manual_review_warn_phrase': '',
    }
}


def load_recipient(alias: str | None):
    if not alias or not RECIPIENTS.exists():
        return None
    data = json.loads(RECIPIENTS.read_text(encoding='utf-8'))
    return data.get('recipients', {}).get(alias)


def read_docx(path: Path):
    doc = Document(str(path))
    paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    return paras


def normalize(line: str) -> str:
    line = re.sub(r'\s+', ' ', line.strip())
    line = re.sub(r'^[-•*\d.\s]+', '', line)
    return line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--kind', choices=['iran', 'crypto', 'asset', 'generic'], default='generic')
    ap.add_argument('--recipient-alias')
    args = ap.parse_args()

    path = Path(args.path)
    rules = KIND_RULES[args.kind]
    out = {
        'path': str(path),
        'kind': args.kind,
        'ok': True,
        'warnings': [],
        'failures': [],
        'metrics': {},
        'checks': []
    }

    def add_check(name: str, ok: bool, detail_ok: str, detail_fail: str):
        detail = detail_ok if ok else detail_fail
        out['checks'].append({'name': name, 'ok': ok, 'detail': detail})
        if not ok:
            out['ok'] = False
            out['failures'].append(detail)

    def add_warn(detail: str):
        out['warnings'].append(detail)

    if not path.exists():
        add_check('file_exists', False, f'文件不存在: {path}', f'文件不存在: {path}')
        print(json.dumps(out, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    paras = read_docx(path)
    full_text = '\n'.join(paras)
    out['metrics']['paragraph_count'] = len(paras)
    out['metrics']['char_count'] = len(full_text)

    add_check('paragraph_count', len(paras) >= rules['min_paragraphs'], f'段落数达标: {len(paras)} >= {rules["min_paragraphs"]}', f'段落数过少: {len(paras)} < {rules["min_paragraphs"]}')
    add_check('char_count', len(full_text) >= rules['min_chars'], f'正文长度达标: {len(full_text)} >= {rules["min_chars"]}', f'正文长度过短: {len(full_text)} < {rules["min_chars"]}')

    bad_hits = []
    for pat in PLACEHOLDER_PATTERNS:
        if re.search(pat, full_text, flags=re.I):
            bad_hits.append(pat)
    add_check('placeholder_scan', not bad_hits, '未发现占位/示例文本', f'存在占位/示例文本: {", ".join(bad_hits)}')

    normalized = [normalize(p) for p in paras if len(normalize(p)) >= 12]
    seen = {}
    dups = []
    for p in normalized:
        seen[p] = seen.get(p, 0) + 1
    for k, v in seen.items():
        if v >= 3:
            dups.append((k[:60], v))
    add_check('duplicate_paragraphs', not dups, '未发现重复段落>=3次', '存在重复段落>=3次: ' + '; '.join([f'{k} x{v}' for k, v in dups]))
    out['metrics']['duplicate_triplets'] = len(dups)

    source_count = full_text.count('参考链接：') + full_text.count('来源：') + len(re.findall(r'https?://', full_text))
    out['metrics']['source_count'] = source_count
    add_check('source_count', source_count >= rules['min_sources'], f'来源/链接数量达标: {source_count} >= {rules["min_sources"]}', f'来源/链接数量不足: {source_count} < {rules["min_sources"]}')

    missing_sections = [s for s in rules['required_sections'] if s not in full_text]
    add_check('required_sections', not missing_sections, '必需章节齐全', '缺少必需章节: ' + ', '.join(missing_sections))

    topic_hits = sum(1 for k in rules['topic_keywords'] if k in full_text)
    out['metrics']['topic_hits'] = topic_hits
    if rules['topic_keywords']:
        add_check('topic_coverage', topic_hits >= max(2, len(rules['topic_keywords']) // 3), f'主题关键词覆盖达标: hits={topic_hits}', f'主题关键词覆盖不足: hits={topic_hits}')

    rec = load_recipient(args.recipient_alias)
    if rec:
        display = rec.get('display_name', '')
        top_text = '\n'.join(paras[:4])
        add_check('recipient_match', display in top_text, f'文档头部已发现接收对象标识: {display}', f'文档头部未发现接收对象标识: {display}')

    markdownish = [p for p in paras if p.strip().startswith('#') or p.strip().startswith('###')]
    if markdownish:
        add_warn(f'检测到 markdown 风格段落 {len(markdownish)} 处')

    warn_phrase = rules.get('manual_review_warn_phrase') or ''
    if warn_phrase:
        count = full_text.count(warn_phrase)
        out['metrics']['manual_review_phrases'] = count
        if count >= 2:
            add_check('manual_review_density', False, '', f'人工复核提示过多: {count} 处')
        elif count == 1:
            add_warn('存在 1 处“需人工复核”提示，建议人工快速过目')

    long_paras = [p for p in paras if len(p) >= 320]
    if long_paras:
        add_warn(f'存在超长段落 {len(long_paras)} 处，可能是抓取脏数据未清洗干净')

    print(json.dumps(out, ensure_ascii=False, indent=2))
    raise SystemExit(0 if out['ok'] else 2)


if __name__ == '__main__':
    main()
