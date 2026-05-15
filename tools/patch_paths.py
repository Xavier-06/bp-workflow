#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path

TEXT_EXTS = {'.py', '.sh', '.md', '.json', '.txt', '.yaml', '.yml', '.plist', '.mjs'}
OLD_HOME = '/Users/xavier/WorkBuddy/20260409155327'
OLD_ROOT = '/Users/xavier/WorkBuddy/20260409155327/ir_runtime'


def patch_file(path: Path, new_root: str, new_home: str) -> int:
    if path.suffix not in TEXT_EXTS:
        return 0
    try:
        text = path.read_text(encoding='utf-8')
    except Exception:
        return 0
    new = text.replace(OLD_ROOT, new_root).replace(OLD_HOME, new_home)
    if new != text:
        path.write_text(new, encoding='utf-8')
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True, help='Extracted workspace root, e.g. /Users/name/.openclaw/workspace')
    args = ap.parse_args()
    root = Path(args.root).resolve()
    new_root = str(root)
    new_home = str(root.parent)
    changed = 0
    for p in root.rglob('*'):
        if p.is_file():
            changed += patch_file(p, new_root, new_home)
    print({'patched_files': changed, 'root': new_root, 'home': new_home})


if __name__ == '__main__':
    main()
