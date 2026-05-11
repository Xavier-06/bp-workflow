#!/usr/bin/env python3
"""
Skill Search — 按需发现技能
对标 free-code 的 toolSearch.ts：动态发现，不是一次性全加载。

功能：
1. 扫描 skills/ 目录下所有 SKILL.md 的 frontmatter
2. 支持关键词搜索（name + description + tags）
3. 返回匹配的技能列表（名称、描述、路径）
4. 可返回匹配度评分

用法：
  python3 skill_search.py "记忆"           # 搜关键词
  python3 skill_search.py "记忆" --json    # JSON 输出
  python3 skill_search.py --list           # 列出所有
"""
import argparse
import json
import re
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
SKILLS_DIR = WORKSPACE / 'skills'


def scan_skills(skills_dir=None, include_content=False):
    """扫描所有 skill 的 frontmatter"""
    if skills_dir is None:
        skills_dir = SKILLS_DIR

    skills = []
    fm_re = re.compile(r'^---\n(.*?)\n---\n', re.DOTALL)

    for skill_path in sorted(skills_dir.iterdir()):
        if not skill_path.is_dir():
            continue
        sk_md = skill_path / 'SKILL.md'
        if not sk_md.exists():
            continue

        text = sk_md.read_text(encoding='utf-8')
        m = fm_re.match(text)
        meta = {}
        body = text

        if m:
            body = text[m.end():]
            for line in m.group(1).split('\n'):
                if ':' in line:
                    k, v = line.split(':', 1)
                    meta[k.strip()] = v.strip().strip('"\'')

        skill_info = {
            'name': meta.get('name', sk_md.parent.name),
            'description': meta.get('description', ''),
            'path': str(sk_md),
            'token_estimate': len(body) // 4,
        }

        if include_content:
            skill_info['content'] = body[:2000]

        skills.append(skill_info)

    return skills


def search_skills(query, max_results=10, skills_dir=None, include_content=False):
    """搜索技能，按关键词匹配"""
    skills = scan_skills(skills_dir)
    query_lower = query.lower()

    scored = []
    for s in skills:
        score = 0
        name = s['name'].lower()
        desc = s['description'].lower()

        if query_lower in name:
            score += 10
        if query_lower in desc:
            score += 5

        for word in query_lower.split():
            if word in name:
                score += 3
            if word in desc:
                score += 1

        if score > 0:
            scored.append({**s, 'score': score})

    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:max_results]


def list_all_skills(skills_dir=None):
    """列出所有可用技能（含 token 估算）"""
    skills = scan_skills(skills_dir)
    total_tokens = sum(s['token_estimate'] for s in skills)

    print(f"共 {len(skills)} 个技能")
    print(f"总 token 估算: {total_tokens} (~{total_tokens * 4} 字符)")
    print()

    for s in skills:
        print(f"  {s['name']:30s} | ~{s['token_estimate']} tok | {s['description'][:60]}")

    return len(skills), total_tokens


def main():
    p = argparse.ArgumentParser(description='Skill Search')
    p.add_argument('query', nargs='?', help='搜索关键词')
    p.add_argument('--json', action='store_true')
    p.add_argument('--list', action='store_true')
    p.add_argument('--content', action='store_true', help='包含内容预览')
    args = p.parse_args()

    if args.list:
        n, tot = list_all_skills()
        if args.json:
            print(json.dumps(scan_skills(include_content=args.content), ensure_ascii=False, indent=2))
        return

    if not args.query:
        p.print_help()
        return

    results = search_skills(args.query, include_content=args.content)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        if results:
            q = args.query
            print(f"搜索 '{q}' 找到 {len(results)} 个匹配:")
            for s in results:
                print(f"  ({s['score']}) {s['name']}")
                print(f"      {s['description'][:100]}")
                if args.content and s.get('content'):
                    print(f"      内容预览: {s['content'][:200]}...")
        else:
            q = args.query
            print(f"搜索 '{q}' 无匹配")
            print("提示: 运行 --list 查看所有可用技能")


if __name__ == '__main__':
    main()
