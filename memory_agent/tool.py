#!/usr/bin/env python3
"""
Memory Agent Tool — v2（四层分类法）

借鉴 Claude Code 记忆设计：user / feedback / project / reference
用法：
  python3 tool.py add "内容" --type user        # 用户角色/偏好
  python3 tool.py add "内容" --type feedback     # 纠正/确认
  python3 tool.py add "内容" --type project      # 项目目标/决策
  python3 tool.py add "内容" --type reference    # 外部系统位置
  python3 tool.py search "关键词"
  python3 tool.py stats
"""

import argparse
import json
import sys
from pathlib import Path

MEMORY_AGENT_DIR = Path(__file__).resolve().parent
VENV_PYTHON = MEMORY_AGENT_DIR / "venv" / "bin" / "python3"

# The helper script that runs inside the venv
HELPER_SCRIPT = '''
import json, sys, os
sys.path.insert(0, sys.argv[1])
from memory_store import MemoryStore

def get_stats():
    store = MemoryStore()
    return store.get_stats()

def search(query, top_k=5, categories=None):
    store = MemoryStore()
    return store.search(query, top_k=top_k, categories=categories)

def add(content, category=None, metadata=None):
    store = MemoryStore()
    return store.add_memory(content, category=category or "user", metadata=metadata)

if __name__ == "__main__":
    args = json.loads(sys.stdin.read())
    action = args.get("action", "stats")
    try:
        if action == "stats":
            result = get_stats()
        elif action == "search":
            result = search(
                args.get("query", ""),
                args.get("top_k", 5),
                args.get("categories"),
            )
        elif action == "add":
            result = add(
                args.get("content", ""),
                args.get("category"),
                args.get("metadata"),
            )
        else:
            result = {"error": f"unknown action: {action}"}
        print(json.dumps({"success": True, "result": result}))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
'''

TYPE_MAP = {
    "user": "user",
    "feedback": "feedback",
    "project": "project",
    "reference": "reference",
    # Legacy types
    "preferences": "user",
    "errors": "feedback",
    "data_points": "project",
}


def run_memory_action(action: str, **kwargs) -> dict:
    """Execute a memory action in the venv"""
    import subprocess

    payload = {
        "action": action,
        **kwargs,
    }

    if VENV_PYTHON.exists():
        try:
            proc = subprocess.run(
                [VENV_PYTHON, "-c", HELPER_SCRIPT, str(MEMORY_AGENT_DIR)],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return json.loads(proc.stdout.strip())
        except Exception as e:
            return {"success": False, "error": str(e)}
    else:
        return {"success": False, "error": f"venv Python 未找到: {VENV_PYTHON}"}


def main():
    parser = argparse.ArgumentParser(description="Memory Agent Tool (Layers)")
    sub = parser.add_subparsers(dest="command")

    # Search
    search_p = sub.add_parser("search", help="Search memories")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("-k", "--top-k", type=int, default=5)
    search_p.add_argument("--type", help="Filter by type (user/feedback/project/reference)")

    # Add
    add_p = sub.add_parser("add", help="Add memory")
    add_p.add_argument("content", help="Memory content")
    add_p.add_argument(
        "--type",
        choices=["user", "feedback", "project", "reference",
                 "preferences", "errors", "data_points"],
        default="user",
        help="Memory type (4-layer taxonomy)",
    )

    # Stats
    sub.add_parser("stats", help="Show memory stats")

    args = parser.parse_args()

    if args.command == "search":
        categories = [args.type] if args.type else None
        if hasattr(args, "type") and args.type:
            categories = [TYPE_MAP.get(args.type, args.type)]
        else:
            categories = None
        result = run_memory_action("search", query=args.query, top_k=args.top_k, categories=categories)
        if result.get("success"):
            for item in result["result"]:
                print(f"[{item.get('category', '?')}] {item.get('content', '')[:100]}")
        else:
            print(f"Error: {result.get('error')}")

    elif args.command == "add":
        category = TYPE_MAP.get(args.type, args.type)
        result = run_memory_action("add", content=args.content, category=category)
        if result.get("success"):
            print(f"✅ Memory saved as {category}: {args.content[:80]}")
        else:
            print(f"❌ Failed: {result.get('error')}")

    elif args.command == "stats":
        result = run_memory_action("stats")
        if result.get("success"):
            stats = result["result"]
            print(f"Total memories: {stats.get('count', 0)}")
            if 'categories' in stats:
                for cat, count in stats['categories'].items():
                    print(f"  {cat}: {count}")
        else:
            print(f"Error: {result.get('error')}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
