#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEM = ROOT/'scripts'/'memory-cmd.sh'

SEARCH_HINTS = [
    '记得', '记住', '之前说过', '按我习惯', '偏好', '风格', '复盘', '总结', '报告', 'brain', '长期', '教训', '错误'
]
ADD_HINTS = [
    '记住这个', '记一下', '以后别忘', '不要再', '下次别', '以后要', '决定', '长期', '规则', '偏好'
]


def sh(args):
    return subprocess.run(args, capture_output=True, text=True)


def should_search(text: str) -> bool:
    return any(k in text for k in SEARCH_HINTS)


def infer_type(text: str) -> str:
    if any(k in text for k in ['不要再', '下次别', '错误', '教训', '踩坑', '失败', '纠正']):
        return 'feedback'
    if any(k in text for k in ['偏好', '风格', '习惯', '按我习惯', '喜欢', '角色', '知道', '了解']):
        return 'user'
    if any(k in text for k in ['决定', '决策', '确认', '采用', '改用', '项目', '目标', '谁在', '为什么', '冻结']):
        return 'project'
    return 'reference'


def cmd_check(text: str):
    out = {
        'should_search': should_search(text),
        'should_add': any(k in text for k in ADD_HINTS),
        'suggested_type': infer_type(text),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_search(query: str, top_k: int):
    res = sh(['bash', str(MEM), 'search', query, '--top-k', str(top_k)])
    sys.stdout.write(res.stdout)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        sys.exit(res.returncode)


def cmd_add(content: str, memory_type: str | None):
    t = memory_type or infer_type(content)
    res = sh(['bash', str(MEM), 'add', content, '--type', t])
    sys.stdout.write(res.stdout)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        sys.exit(res.returncode)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd')

    c = sp.add_parser('check')
    c.add_argument('text')

    s = sp.add_parser('search')
    s.add_argument('query')
    s.add_argument('--top-k', type=int, default=5)

    a = sp.add_parser('add')
    a.add_argument('content')
    a.add_argument('--type', choices=['user','feedback','project','reference'])

    args = ap.parse_args()
    if args.cmd == 'check':
        cmd_check(args.text)
    elif args.cmd == 'search':
        cmd_search(args.query, args.top_k)
    elif args.cmd == 'add':
        cmd_add(args.content, args.type)
    else:
        ap.print_help(); sys.exit(1)

if __name__ == '__main__':
    main()
