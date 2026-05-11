#!/usr/bin/env python3
"""
Remember Skill — 跨层记忆审查

扫描 brain.md、memory/ 日志、.learnings/、memory-agent 向量库，
找出重复、过时、冲突条目，输出审查报告。
"""
import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERBOSE = False
SCOPE = 'all'


# ── 扫描层 ────────────────────────────────────────────────
def scan_brain_md():
    fp = ROOT / 'brain.md'
    if not fp.exists():
        return []
    text = fp.read_text(encoding='utf-8')
    entries = []
    in_section = False
    for line in text.split('\n'):
        if line.startswith('## '):
            in_section = any(k in line for k in ['Todo', '晋升', '配置', '教训', '铁律', '沟通'])
            continue
        if in_section and line.strip().startswith('- '):
            content = re.sub(r'^- \[[ x]\] ', '', line.strip())
            if len(content) > 15:
                entries.append({
                    'source': 'brain.md',
                    'content': content,
                    'path': str(fp),
                })
    return entries


def scan_memory_logs(days=14):
    memory_dir = ROOT / 'memory'
    entries = []
    cutoff = datetime.now() - timedelta(days=days)
    for f in sorted(memory_dir.glob('????-??-??.md')):
        try:
            fd = datetime.strptime(f.stem, '%Y-%m-%d')
            if fd < cutoff:
                continue
        except ValueError:
            continue
        text = f.read_text(encoding='utf-8')
        m = re.match(r'^---\n.*?\n---\n', text, re.DOTALL)
        body = text[m.end():] if m else text
        current_title = ''
        current_lines = []
        for line in body.split('\n'):
            if line.startswith('## ') or line.startswith('# '):
                if current_title and current_lines:
                    content = '\n'.join(current_lines).strip()
                    if len(content) > 10:
                        entries.append({
                            'source': f'memory/{f.name}',
                            'content': content[:300],
                            'path': str(f),
                            'date': f.stem,
                        })
                current_title = line.strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_title and current_lines:
            content = '\n'.join(current_lines).strip()
            if len(content) > 10:
                entries.append({
                    'source': f'memory/{f.name}',
                    'content': content[:300],
                    'path': str(f),
                    'date': f.stem,
                })
    return entries


def scan_learnings():
    learnings_dir = ROOT / '.learnings'
    if not learnings_dir.exists():
        return []
    entries = []
    for f in sorted(learnings_dir.glob('*.md')):
        text = f.read_text(encoding='utf-8')
        current_heading = ''
        for line in text.split('\n'):
            ls = line.strip()
            if ls.startswith('### '):
                current_heading = ls[4:].strip()
            elif current_heading and ls and not ls.startswith('**') and ls.startswith('- ') and len(ls) > 15:
                entries.append({
                    'source': f'.learnings/{f.name}',
                    'content': ls[:300],
                    'path': str(f),
                })
    return entries


def scan_learnings_errors():
    entries = []
    for fname in ['ERRORS.md', 'LEARNINGS.md']:
        fp = ROOT / '.learnings' / fname
        if not fp.exists():
            continue
        text = fp.read_text(encoding='utf-8')
        for line in text.split('\n'):
            ls = line.strip()
            if ls.startswith('### ') and any(k in ls for k in ['教训', '根因', '修复', '教训:', '根因:', 'Fix', 'Action', 'Suggested']):
                entries.append({
                    'source': f'.learnings/{fname}',
                    'content': ls[:300],
                    'path': str(fp),
                })
    return entries


def scan_memory_agent():
    """通过 venv 子进程调用 memory-agent 列出条目"""
    entries = []
    try:
        import subprocess
        result = subprocess.run(
            [str(ROOT / 'memory_agent/venv/bin/python3'),
             str(ROOT / 'memory_agent/tool.py'), 'list'],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            import json
            data = json.loads(result.stdout)
            # tool.py list returns {category: {sub_name: [{content, ...}]}}
            # or {category: [{content, ...}]}
            for cat_name, items in data.items():
                if isinstance(items, dict):
                    for sub_name, sub_items in items.items():
                        if isinstance(sub_items, list):
                            for item in sub_items:
                                content = item.get('content', '')
                                if content:
                                    entries.append({
                                        'source': f'memory-agent [{sub_name}]',
                                        'content': content[:300],
                                        'path': 'memory_db',
                                    })
                elif isinstance(items, list):
                    for item in items:
                        content = item.get('content', '')
                        if content:
                            entries.append({
                                'source': f'memory-agent [{cat_name}]',
                                'content': content[:300],
                                'path': 'memory_db',
                            })
        elif result.stderr.strip() and VERBOSE:
            print(f'⚠️ memory-agent stderr: {result.stderr[:200]}')
    except Exception as e:
        if VERBOSE:
            print(f'⚠️ memory-agent scan failed: {e}')
    return entries


def scan_memory_md():
    fp = ROOT / 'MEMORY.md'
    if not fp.exists():
        return []
    text = fp.read_text(encoding='utf-8')
    entries = []
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('- ') and len(line) > 15:
            entries.append({
                'source': 'MEMORY.md',
                'content': line[2:].strip()[:300],
                'path': str(fp),
            })
    return entries


# ── 比对引擎 ──────────────────────────────────────────────
def similarity(a, b):
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def find_near_duplicates(entries, threshold=0.65):
    dupes = []
    by_source = defaultdict(list)
    for e in entries:
        by_source[e['source']].append(e)
    sources = list(by_source.keys())
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            for a in by_source[sources[i]]:
                for b in by_source[sources[j]]:
                    a_words = set(a['content'][:60].lower().split())
                    b_words = set(b['content'][:60].lower().split())
                    overlap = len(a_words & b_words) / max(len(a_words | b_words), 1)
                    if overlap < 0.2:
                        continue
                    sim = similarity(a['content'][:100], b['content'][:100])
                    if sim >= threshold:
                        dupes.append((a, b, sim))
    seen = set()
    unique = []
    for a, b, sim in dupes:
        key = tuple(sorted([a['content'][:60], b['content'][:60]]))
        if key not in seen:
            seen.add(key)
            unique.append((a, b, sim))
    return unique


def find_conflicts(entries):
    conflicts = []
    negative_words = ['不要', '禁止', '不用', '不应', '废除', '取消', '禁用']
    positive_words = ['要', '需要', '应该', '推荐', '使用', '启用']
    for i, a in enumerate(entries):
        for j in range(i + 1, len(entries)):
            b = entries[j]
            a_lower = a['content'].lower()
            b_lower = b['content'].lower()
            a_neg = any(w in a_lower for w in negative_words)
            b_neg = any(w in b_lower for w in negative_words)
            a_pos = any(w in a_lower for w in positive_words)
            b_pos = any(w in b_lower for w in positive_words)
            if (a_neg and b_pos) or (a_pos and b_neg):
                a_words = set(a['content'][:60].lower().split())
                b_words = set(b['content'][:60].lower().split())
                overlap = len(a_words & b_words) / max(len(a_words | b_words), 1)
                if overlap >= 0.15:
                    conflicts.append((a, b))
    return conflicts


# ── 报告生成 ──────────────────────────────────────────────
def generate_report(brain, memory_logs, learnings, learnings_err, memory_db, memory_md):
    all_entries = brain + memory_logs + learnings + learnings_err + memory_db + memory_md

    topic_keywords = {
        '搜索/引擎': ['searxng', '搜索', 'tavily', 'ddg', '引擎'],
        '沟通偏好': ['沟通', '简洁', '频繁', '汇报', '进度'],
        'BP 管线': ['bp', '尽调', 'preflight', '子代理'],
        'IR 研报': ['研报', 'ir', '估值'],
        '记忆系统': ['记忆', '去重', '蒸馏', 'category', 'frontmatter', 'dream'],
        '安全/凭证': ['credential', 'key', 'token', '密码', '凭证'],
    }
    by_topic = defaultdict(list)
    for e in all_entries:
        for topic, kws in topic_keywords.items():
            if any(kw in e['content'].lower() for kw in kws):
                by_topic[topic].append(e)
                break

    dedup_candidates = memory_logs + learnings + memory_db + memory_md
    dupes = find_near_duplicates(dedup_candidates)
    conflicts = find_conflicts(all_entries)

    print('=' * 60)
    print('🔍 跨层记忆审查报告')
    print('=' * 60)
    print(f'📊 扫描范围:')
    print(f'   brain.md: {len(brain)} 条')
    print(f'   memory/ (14天): {len(memory_logs)} 条')
    print(f'   .learnings/: {len(learnings)} 条')
    print(f'   .learnings/ERRORS: {len(learnings_err)} 条')
    print(f'   memory-agent: {len(memory_db)} 条')
    print(f'   MEMORY.md: {len(memory_md)} 条')
    print(f'   总计: {len(all_entries)} 条')
    print()

    if dupes:
        print(f'🔄 发现 {len(dupes)} 组近重复')
        print('-' * 40)
        for a, b, sim in sorted(dupes, key=lambda x: -x[2])[:10]:
            print(f'\n  相似度 {sim:.0%}')
            print(f'  [{a["source"]}]')
            print(f'    {a["content"][:100]}')
            print(f'  [{b["source"]}]')
            print(f'    {b["content"][:100]}')
        if len(dupes) > 10:
            print(f'\n  ... 还有 {len(dupes) - 10} 组')
    else:
        print('✅ 未发现近重复条目')

    if conflicts:
        print(f'\n⚠️ 发现 {len(conflicts)} 组潜在冲突')
        print('-' * 40)
        for a, b in conflicts[:5]:
            print(f'\n  [{a["source"]}]')
            print(f'    {a["content"][:100]}')
            print(f'  [{b["source"]}]')
            print(f'    {b["content"][:100]}')
        if len(conflicts) > 5:
            print(f'\n  ... 还有 {len(conflicts) - 5} 组')
    else:
        print('\n✅ 未发现明显冲突')

    print(f'\n📈 主题分布 (top 6)')
    print('-' * 40)
    for topic, items in sorted(by_topic.items(), key=lambda x: -len(x[1]))[:6]:
        sources = set(i['source'] for i in items)
        print(f'  {topic}: {len(items)} 条, {len(sources)} 个来源')

    # ── Phase 6: 白名单检查 ──
    print(f'\n🛡️   Phase 6: 白名单检查 (What NOT to save)')
    print('-' * 40)
    not_save_patterns = {
        '已完成的 checkbox': r'\[x\]',
        '纯状态行': r'^状态[:：]',
        '路径泄漏': r'/Users/xavier/|/tmp/|\.openclaw/.*?scripts/',
        '时间戳泄漏': r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}',
        '任务 ID 泄漏': r'(task|agent|sub-?agent)[- _]?id[:\s]',
    }
    violations = defaultdict(list)
    for e in all_entries:
        c_lower = e['content'].lower()
        for label, pat in not_save_patterns.items():
            if re.search(pat, c_lower):
                violations[label].append(e['source'])

    if violations:
        for label, sources in sorted(violations.items(), key=lambda x: -len(x[1])):
            print(f'  ⚠️ {label}: {len(sources)} 处')
            if VERBOSE:
                for s in set(sources)[:3]:
                    print(f'    - {s}')
    else:
        print('  ✅ 无敏感信息泄漏')

    print(f'\n' + '=' * 60)
    if not dupes and not conflicts and not violations:
        print('✨ 记忆系统干净，无需操作')
    else:
        print(f'💡 建议处理: {len(dupes)} 重复 / {len(conflicts)} 冲突 / {len(violations)} 类敏感')
    print('=' * 60)


def main():
    global VERBOSE, SCOPE
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--scope', default='all',
                        choices=['all', 'brain', 'memory', 'learnings', 'memory-agent', 'memory-md'])
    args = parser.parse_args()
    VERBOSE = args.verbose
    SCOPE = args.scope

    print('🔍 开始跨层记忆审查...\n')
    brain = scan_brain_md() if SCOPE in ('all', 'brain') else []
    memory_logs = scan_memory_logs() if SCOPE in ('all', 'memory') else []
    learnings = scan_learnings() if SCOPE in ('all', 'learnings') else []
    learnings_err = scan_learnings_errors() if SCOPE in ('all', 'learnings') else []
    memory_db = scan_memory_agent() if SCOPE in ('all', 'memory-agent') else []
    memory_md = scan_memory_md() if SCOPE in ('all', 'memory-md') else []
    generate_report(brain, memory_logs, learnings, learnings_err, memory_db, memory_md)


if __name__ == '__main__':
    main()