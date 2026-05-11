"""
Memory Bridge - 主工作区调用 memory_agent 向量记忆的统一接口

用法：
    from memory.memory_bridge import search_memory, add_memory, get_memory_stats

    # 检索
    results = search_memory('腾讯财务数据', top_k=5)

    # 写入
    add_memory('腾讯2024年营收6603亿，同比增长8%', category='key_data')

    # 统计
    stats = get_memory_stats()
"""
from __future__ import annotations
import json
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path

# --- Ensure workspace root is on sys.path for imports ---
WORKSPACE = Path(__file__).resolve().parent.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

ROOT = Path(__file__).resolve().parent.parent
MEMORY_AGENT_DIR = ROOT / 'memory_agent'
VENV_PYTHON = MEMORY_AGENT_DIR / 'venv' / 'bin' / 'python3'

# Inline helper 脚本：在 venv Python 里执行 memory 操作
_HELPER_SCRIPT = '''
import json, sys
sys.path.insert(0, '{memory_agent_dir}')
from memory_store import MemoryStore

def get_stats():
    store = MemoryStore()
    return store.get_stats()

def search(query, top_k=5, categories=None):
    store = MemoryStore()
    results = store.search(query, top_k=top_k, categories=categories)
    return results

def add(content, category=None, metadata=None):
    store = MemoryStore()
    return store.add_memory(content, category=(category or 'conversations'), metadata=metadata)

if __name__ == "__main__":
    args = json.load(sys.stdin)
    action = args.get("action", "stats")
    try:
        if action == "stats":
            result = get_stats()
        elif action == "search":
            result = search(args.get("query", ""), args.get("top_k", 5), args.get("categories"))
        elif action == "add":
            result = add(args.get("content", ""), args.get("category"), args.get("metadata"))
        else:
            result = {{"error": f"unknown action: {{action}}"}}
        print(json.dumps({{"success": True, "result": result}}))
    except Exception as e:
        print(json.dumps({{"success": False, "error": str(e)}}))
'''.format(memory_agent_dir=MEMORY_AGENT_DIR.resolve())


def _run_helper(args: dict) -> dict | None:
    """通过 venv Python 执行 memory 操作"""
    if not VENV_PYTHON.exists():
        return {'error': f'venv python not found at {VENV_PYTHON}'}
    try:
        proc = subprocess.run(
            [str(VENV_PYTHON), '-c', _HELPER_SCRIPT],
            input=json.dumps(args),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            return {'error': proc.stderr.strip()[:500]}
        output = proc.stdout.strip()
        if output:
            return json.loads(output)
        return None
    except subprocess.TimeoutExpired:
        return {'error': 'memory operation timed out'}
    except Exception as e:
        return {'error': str(e)}


def get_memory_stats() -> dict:
    """返回各集合条数"""
    result = _run_helper({'action': 'stats'})
    if result and result.get('success'):
        return {'available': True, **result['result']}
    return {'available': False, 'error': (result or {}).get('error', 'unknown')}


def search_memory(query: str, top_k: int = 5, categories: list[str] | None = None) -> list[dict]:
    """检索相关记忆，自动附加新鲜度标注"""
    from memory.memoryAge import memory_age_days
    from memory.memoryAge import memory_age_str as memory_age_str_fresh
    result = _run_helper({
        'action': 'search',
        'query': query,
        'top_k': top_k,
        'categories': categories,  # None = search all
    })
    if result and result.get('success'):
        memories = result['result'] or []
        for m in memories:
            # 附加新鲜度信息
            ts = m.get('timestamp') or m.get('metadata', {}).get('timestamp', '')
            if ts:
                try:
                    _dt = datetime.fromisoformat(ts)
                    age_ms = int(_dt.timestamp() * 1000)
                    m['age_days'] = memory_age_days(age_ms)
                    m['age_str'] = memory_age_str_fresh(age_ms)
                    m['freshness_warning'] = ''  # handled by memory_agent's freshness
                except Exception:
                    pass
        return memories
    return []


def memory_age_str_fresh(age_ms: int) -> str:
    """返回 'X天前' 格式的年龄"""
    from memory.memoryAge import memory_age_str
    return memory_age_str(age_ms)


def add_memory(content: str, category: str = 'conversations', metadata: dict | None = None) -> str | None:
    """写入一条记忆"""
    result = _run_helper({
        'action': 'add',
        'content': content,
        'category': category,
        'metadata': metadata,
    })
    if result and result.get('success'):
        return result.get('result')
    return None


if __name__ == '__main__':
    print('Memory Bridge Status:')
    stats = get_memory_stats()
    print(stats)
    if stats.get('available'):
        print('\nTest search: 用户偏好')
        results = search_memory('用户偏好', top_k=2)
        print(f'Found {len(results)} results')
        for r in results:
            print(f'  [{r.get("category")}] score={r.get("score")} {r.get("content", "")[:80]}')
