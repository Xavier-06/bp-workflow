#!/usr/bin/env python3
"""
Phase 3 & 4 — memory_store.py patch script

Patches:
  Phase 3: memory_age() + freshness labels on search results
  Phase 4: LLM selector (vector coarse → LLM top-N)

Writes patched search() back into memory_store.py.

Usage:
  cd $(dirname $(dirname $(realpath $0))) && python3 -c "exec(open('scripts/patch_memory_store_phase34.py').read())"
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent if '__file__' in dir() else Path.cwd()
# When run from workspace root
if Path('memory_agent/memory_store.py').exists():
    STORE = Path('memory_agent/memory_store.py')
else:
    STORE = ROOT / 'memory_agent/memory_store.py'

print(f'📄 Patching {STORE}')
text = STORE.read_text(encoding='utf-8')
original = text

# ── Patch 1: Add memory_age helper (after imports section, before class MemoryStore) ──
HELPER_CODE = '''
# ── Memory Age Helpers (Phase 3) ──
def memory_age_label(timestamp_str: str) -> str:
    """Human-readable age label. 返回 '' / 'today' / 'X days ago'。"""
    if not timestamp_str:
        return ''
    try:
        ts = datetime.fromisoformat(timestamp_str)
        days = (datetime.now() - ts).days
        if days <= 0:
            return 'today'
        elif days == 1:
            return 'yesterday'
        else:
            return f'{days} days ago'
    except (ValueError, TypeError):
        return ''


def freshness_warning(timestamp_str: str) -> str:
    """超过 3 天的记忆返回警告文本，否则空字符串。"""
    if not timestamp_str:
        return ''
    try:
        ts = datetime.fromisoformat(timestamp_str)
        days = (datetime.now() - ts).days
        if days > 3:
            return (
                f'⚠️ 此记忆 {days} 天前记录，是历史快照而非实时状态 — '
                '关键事实请以当前情况为准。'
            )
    except (ValueError, TypeError):
        pass
    return ''

'''

# Insert helper before class MemoryStore
if 'memory_age_label' not in text and 'def memory_age_label' not in text:
    text = text.replace(
        'class MemoryStore:',
        HELPER_CODE + 'class MemoryStore:',
    )
    print('  ✅ Added memory_age_label + freshness_warning helpers')

# ── Patch 2: Add freshness labels to search results ──
# Find the block where results.append({...}) and add age_label + freshness_warning
old_append = '''                results.append({
                    "content": doc,
                    "category": cat_name,
                    "score": round(final_score, 4),
                    "metadata": meta,
                })'''

new_append = '''                # Phase 3: Freshness labels
                ts_str = (meta or {}).get("timestamp", "")
                age = memory_age_label(ts_str)
                warn = freshness_warning(ts_str)

                results.append({
                    "content": doc,
                    "category": cat_name,
                    "score": round(final_score, 4),
                    "metadata": meta,
                    "age_label": age,        # Phase 3
                    "freshness_warning": warn,  # Phase 3
                })'''

if 'age_label' not in text:
    text = text.replace(old_append, new_append)
    print('  ✅ Added age_label + freshness_warning to search results')

# ── Patch 3: LLM selector (Phase 4) ──
# Add select_best_memories method before search() method

SELECTOR_CODE = '''
    # ── Phase 4: LLM Selector ──
    @staticmethod
    def _format_selector_candidate(r: dict, idx: int) -> str:
        """格式化单条候选记忆为 selector 可读格式。"""
        parts = []
        parts.append(f'{idx}. {r["content"][:200]}')
        parts.append(f'   [category={r["category"]}, score={r["score"]:.2f}]')
        if r.get('age_label'):
            parts.append(f'   [age: {r["age_label"]}]')
        return '\\n'.join(parts)

    def select_best_memories(
        self,
        query: str,
        top_k: int = 5,
        candidate_pool: int = 15,
        categories: list[str] = None,
        already_seen: list[str] = None,
    ) -> list[dict]:
        """
        Phase 4: 向量粗筛 → LLM 精选 top-N。
        1. 向量检索 candidate_pool 条候选
        2. LLM 从中选出最相关的 top_k 条
        3. 返回带 age_label + freshness_warning 的结果

        Args:
            query: 原始检索 query
            top_k: 最终返回数量（默认 5）
            candidate_pool: 向量粗筛候选池大小（默认 15）
            categories: 记忆类别过滤
            already_seen: 已展示过的 content 前缀（避免重复）
        """
        import requests
        import sys, os

        # Step 1: 向量粗筛
        candidates = self.search(query, top_k=candidate_pool, categories=categories)
        if not candidates:
            return []

        # 过滤已见
        if already_seen:
            seen_set = set(s[:80] for s in already_seen)
            candidates = [c for c in candidates if c['content'][:80] not in seen_set]

        if len(candidates) <= top_k:
            return candidates

        # Step 2: LLM 精选
        manifest = '\n\n'.join(
            self._format_selector_candidate(c, i)
            for i, c in enumerate(candidates, 1)
        )

        system_prompt = (
            "你是一个记忆检索专家。用户给你一个查询和候选记忆列表（含相关性评分、年龄标签）。\n"
            "请从中选出最相关的 top 5 条记忆（或更少，如果没有那么多匹配的）。\n"
            "评分标准：\n"
            "1. 内容直接与 query 相关\n"
            "2. 提供 query 所需的事实/教训/偏好\n"
            "3. 评分高者优先，但语义相关度 > 数值分数\n"
            "4. 如果候选记忆都不相关，返回空列表\n"
            "\n"
            "以 JSON 格式返回：{\"selected_indices\": [1, 3, 5]}，仅包含序号。不要解释。"
        )

        user_prompt = (
            f"Query: {query}\n\n"
            f"候选记忆:\n{manifest}\n\n"
            f"请选出最相关的最多 {top_k} 条。"
        )

        # 调用本地 qwen-plus
        try:
            # 加载 API key
            dashscope_key = None
            for env_path in [
                Path(__file__).parent.parent / '.credentials/investment-research.env',
                Path(__file__).resolve().parent.parent / '.credentials/investment-research.env',
            ]:
                if env_path.exists():
                    for line in open(env_path, encoding='utf-8'):
                        if line.startswith('DASHSCOPE_API_KEY='):
                            dashscope_key = line.split('=', 1)[1].strip()
                            break
                    if dashscope_key:
                        break

            if not dashscope_key:
                dashscope_key = os.environ.get('DASHSCOPE_API_KEY', '')

            if not dashscope_key:
                return candidates[:top_k]

            import httpx
            resp = httpx.post(
                'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
                json={
                    'model': 'qwen-plus',
                    'messages': [
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': user_prompt},
                    ],
                    'temperature': 0,
                    'response_format': {'type': 'json_object'},
                },
                headers={
                    'Authorization': f'Bearer {dashscope_key}',
                    'Content-Type': 'application/json',
                },
                timeout=15,
            )

            if resp.status_code == 200:
                body = resp.json()
                content = body['choices'][0]['message']['content']
                import json as _json
                parsed = _json.loads(content)
                selected_indices = parsed.get('selected_indices', [])
                selected = []
                for idx in selected_indices:
                    if 1 <= idx <= len(candidates):
                        selected.append(candidates[idx - 1])
                # 补齐到 top_k（如果 LLM 没选够）
                seen_ids = set(id(s) for s in selected)
                for c in candidates:
                    if len(selected) >= top_k:
                        break
                    if id(c) not in seen_ids:
                        selected.append(c)
                return selected[:top_k]
            else:
                print(f'⚠️ LLM selector failed: {resp.status_code}, fallback to vector results')
                return candidates[:top_k]
        except Exception as e:
            print(f'⚠️ LLM selector error: {e}, fallback to vector results')
            return candidates[:top_k]

'''

if 'def select_best_memories' not in text:
    # Insert before the search() method
    text = text.replace(
        '    def search(\n',
        SELECTOR_CODE + '    def search(\n',
    )
    print('  ✅ Added select_best_memories (LLM selector)')

# ── Apply patch ──
if text != original:
    STORE.write_text(text, encoding='utf-8')
    print('✅ Patch applied successfully')
else:
    print('⚠️  No changes detected (already patched?)')

print(f'\nDone. {STORE.name} updated.')
