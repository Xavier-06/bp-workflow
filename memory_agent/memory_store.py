"""
向量记忆模块 - 基于 ChromaDB + 百炼 Embedding
负责：存储/检索 用户偏好、历史错误、关键数据点
"""
import json
import time
import hashlib
import os
from datetime import datetime
from pathlib import Path as _Path
from typing import Optional

import chromadb
from chromadb.config import Settings
import dashscope
from dashscope import TextEmbedding

import config

# 记忆重要性权重（写入时根据来源标记）
IMPORTANCE_WEIGHTS = {
    "user_direct": 0.90,
    "learnings_promoted": 0.80,
    "learnings_resolved": 0.60,
    "learnings_pending": 0.50,
    "auto_task": 0.30,
    "auto_conversation": 0.10,
}


# ── Memory Age Helpers (Phase 3) ──────────────────────
def memory_age_label(timestamp_str: str) -> str:
    """Human-readable age label. 返回 'today' / 'yesterday' / 'X days ago' / ''。"""
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
    """超过 3 天的记忆返回警告文本，否则空字符串。
    借鉴 Claude Code memoryFreshnessText。"""
    if not timestamp_str:
        return ''
    try:
        ts = datetime.fromisoformat(timestamp_str)
        days = (datetime.now() - ts).days
        if days > 3:
            return (
                f'此记忆 {days} 天前记录。记忆是历史快照，不是实时状态。'
                f'关键事实请以当前情况为准。'
            )
    except (ValueError, TypeError):
        pass
    return ''


class MemoryStore:
    """向量记忆库：自动存储和检索对话中的关键信息"""

    def __init__(self):
        dashscope.api_key = config.DASHSCOPE_API_KEY

        self.client = chromadb.PersistentClient(
            path=config.CHROMA_DB_PATH,
            settings=Settings(anonymized_telemetry=False),
        )

        # 旧类别（向后兼容）
        self.preferences = self._get_or_create("user_preferences")
        self.errors = self._get_or_create("past_errors")
        self.data_points = self._get_or_create("key_data")
        self.conversations = self._get_or_create("conversations")
        # 4-layer taxonomy (Claude Code mode)
        self.user = self._get_or_create("user")
        self.feedback = self._get_or_create("feedback")
        self.project = self._get_or_create("project")
        self.reference = self._get_or_create("reference")
        # 新 4 层分类（Claude Code 模式）
        # 4-layer aliases (same as self.user etc above)
        self.user_col = self.user
        self.feedback_col = self.feedback
        self.project_col = self.project
        self.reference_col = self.reference

    def _get_or_create(self, name: str):
        return self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    # ----------------------------------------------------------
    #  Embedding：调用百炼 text-embedding-v2
    # ----------------------------------------------------------
    def _embed(self, texts: list[str]) -> list[list[float]]:
        """批量生成向量，百炼每次最多 25 条"""
        all_embeddings = []
        for i in range(0, len(texts), 25):
            batch = texts[i : i + 25]
            resp = TextEmbedding.call(
                model=config.EMBEDDING_MODEL,
                input=batch,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Embedding 调用失败：{resp.code} - {resp.message}")
            all_embeddings.extend([item["embedding"] for item in resp.output["embeddings"]])
        return all_embeddings

    # ----------------------------------------------------------
    #  写入记忆
    # ----------------------------------------------------------

    def _check_duplicate(
        self,
        content: str,
        category: str = None,
        similarity_threshold: float = 0.90,
    ):
        """检查将要写入的内容是否与现有记忆高度重复。
        返回 (is_duplicate, existing_content, score) 或 (False, None, 0)。"""
        categories = [category] if category else ["user_preferences", "past_errors", "key_data", "conversations", "user", "feedback", "project", "reference"]
        collection_map = {
            "user_preferences": self.preferences,
            "past_errors": self.errors,
            "key_data": self.data_points,
            "conversations": self.conversations,
            "user": self.user_col,
            "feedback": self.feedback_col,
            "project": self.project_col,
            "reference": self.reference_col,
        }
        q_emb = self._embed([content])[0]
        for cat_name in categories:
            col = collection_map.get(cat_name)
            if not col or col.count() == 0:
                continue
            res = col.query(query_embeddings=[q_emb], n_results=min(3, col.count()),
                          include=["documents", "distances"])
            for doc, dist in zip(res["documents"][0], res["distances"][0]):
                raw_cosine = 1 - dist
                if raw_cosine >= similarity_threshold:
                    return True, doc, raw_cosine
        return False, None, 0

    def add_memory(
        self,
        content: str,
        category: str = "conversations",
        metadata: Optional[dict] = None,
        skip_dedup: bool = False,
    ) -> Optional[str]:
        """存入一条记忆。返回 doc_id 或 None（重复/失败）。"""
        if not skip_dedup:
            is_dup, existing, score = self._check_duplicate(content, category)
            if is_dup:
                print(f"⏭️ 重复记忆跳过（相似度 {score:.2f}）：'{content[:60]}...'")
                return None

        if metadata and "importance_weight" not in metadata:
            src = metadata.get("source", "")
            status = metadata.get("status", "")
            if "learnings" in src or status == "promoted":
                metadata["importance_weight"] = float(IMPORTANCE_WEIGHTS["learnings_promoted"])
            elif status == "resolved":
                metadata["importance_weight"] = float(IMPORTANCE_WEIGHTS["learnings_resolved"])
            elif status == "pending":
                metadata["importance_weight"] = float(IMPORTANCE_WEIGHTS["learnings_pending"])
            else:
                metadata["importance_weight"] = float(IMPORTANCE_WEIGHTS["auto_conversation"])
        if not metadata:
            metadata = {"importance_weight": float(IMPORTANCE_WEIGHTS["auto_conversation"])}

        # 新 4 层分类优先匹配，旧类型向后兼容
        collection_map = {
            "user": self.user_col,
            "feedback": self.feedback_col,
            "project": self.project_col,
            "reference": self.reference_col,
            "user_preferences": self.preferences,
            "past_errors": self.errors,
            "key_data": self.data_points,
            "conversations": self.conversations,
        }
        collection = collection_map.get(category, self.conversations)

        doc_id = hashlib.md5(f"{content}{time.time()}".encode()).hexdigest()[:16]

        meta = {
            "timestamp": datetime.now().isoformat(),
            "category": category,
        }
        if metadata:
            meta.update({k: str(v) for k, v in metadata.items()})

        embeddings = self._embed([content])

        collection.add(
            ids=[doc_id],
            embeddings=embeddings,
            documents=[content],
            metadatas=[meta],
        )
        return doc_id

    def add_memories_batch(self, memories: list[dict]) -> dict:
        """批量写入记忆。返回 {"added": N, "skipped": N, "failed": N}。"""
        stats = {"added": 0, "skipped": 0, "failed": 0}
        for mem in memories:
            try:
                result = self.add_memory(
                    content=mem["content"],
                    category=mem.get("category", "conversations"),
                    metadata=mem.get("metadata"),
                )
                if result:
                    stats["added"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                print(f"⚠️ 写入失败：{mem.get('content', '?')} — {e}")
                stats["failed"] += 1
        return stats

    # ----------------------------------------------------------
    #  Phase 4: LLM Selector — 向量粗筛 → LLM 精选
    # ----------------------------------------------------------
    @staticmethod
    def _format_candidate(r: dict, idx: int) -> str:
        """格式化单条候选记忆供 LLM selector 使用。"""
        age = r.get('age_label', '')
        age_part = f', age: {age}' if age else ''
        return f'{idx}. [{r["category"]}, score={r["score"]:.2f}{age_part}] {r["content"][:200]}'

    def select_best_memories(
        self,
        query: str,
        top_k: int = 5,
        candidate_pool: int = 15,
        categories: list[str] = None,
        already_seen: list[str] = None,
    ) -> list[dict]:
        """
        Phase 4: LLM 精选记忆。
        1. 向量检索 candidate_pool 条候选
        2. LLM 选出最相关的 top_k 条
        3. 返回带 age_label + freshness_warning 的结果

        Args:
            query: 查询
            top_k: 最终返回数
            candidate_pool: 向量粗筛候选池大小
            categories: 类别过滤
            already_seen: 已展示记忆前缀列表（去重）
        """
        candidates = self.search(query, top_k=candidate_pool, categories=categories)
        if not candidates:
            return []

        # Filter already-seen
        if already_seen:
            seen_set = set(s[:80] for s in already_seen)
            candidates = [c for c in candidates if c['content'][:80] not in seen_set]

        if len(candidates) <= top_k:
            return candidates

        # Build manifest
        manifest = '\n'.join(
            self._format_candidate(c, i)
            for i, c in enumerate(candidates, 1)
        )

        system_prompt = (
            "You select the most relevant memories for a user query. "
            "Return only a JSON object: {\"selected_indices\": [1, 3, 5]}, "
            "containing at most the requested number of indices (1-based)."
        )
        user_prompt = (
            f"Query: {query}\n\n"
            f"Available memories ({len(candidates)}):\n"
            f"{manifest}\n\n"
            f"Select at most {top_k} most relevant memories."
        )

        try:
            api_key = config.DASHSCOPE_API_KEY or os.environ.get('DASHSCOPE_API_KEY', '')
            if not api_key:
                creds = _Path(__file__).parent.parent / '.credentials/investment-research.env'
                if creds.exists():
                    for line in open(creds, encoding='utf-8'):
                        if line.startswith('DASHSCOPE_API_KEY='):
                            api_key = line.split('=', 1)[1].strip()
                            break

            if not api_key:
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
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                timeout=15,
            )

            if resp.status_code == 200:
                body = resp.json()
                content = body['choices'][0]['message']['content']
                parsed = json.loads(content)
                selected_indices = parsed.get('selected_indices', [])
                selected = []
                for idx in selected_indices:
                    if 1 <= idx <= len(candidates):
                        selected.append(candidates[idx - 1])
                # Top-up if LLM under-selected
                seen_ids = set(id(s) for s in selected)
                for c in candidates:
                    if len(selected) >= top_k:
                        break
                    if id(c) not in seen_ids:
                        selected.append(c)
                return selected[:top_k]
            else:
                print(f"⚠️ LLM selector HTTP {resp.status_code}, fallback to vector")
                return candidates[:top_k]
        except Exception as e:
            print(f"⚠️ LLM selector error: {e}, fallback to vector")
            return candidates[:top_k]

    # ----------------------------------------------------------
    #  检索记忆
    # ----------------------------------------------------------
    def search(
        self,
        query: str,
        top_k: int = None,
        categories: list[str] = None,
    ) -> list[dict]:
        """
        检索相关记忆（Phase 3: 带 age_label + freshness_warning）。
        返回：[{"content": "...", "category": "...", "score": ..., "age_label": "...", "freshness_warning": "...", "metadata": {...}}, ...]
        """
        if top_k is None:
            top_k = config.MEMORY_TOP_K

        if categories is None:
            categories = ["user", "feedback", "project", "reference", "user_preferences", "past_errors", "key_data", "conversations"]

        query_embedding = self._embed([query])[0]
        results = []

        for cat_name in categories:
            collection_map = {
                "user": self.user,
                "feedback": self.feedback,
                "project": self.project,
                "reference": self.reference,
                "user_preferences": self.preferences,
                "past_errors": self.errors,
                "key_data": self.data_points,
                "conversations": self.conversations,
            }
            collection = collection_map.get(cat_name)
            if collection is None or collection.count() == 0:
                continue

            n = min(top_k, collection.count())
            res = collection.query(
                query_embeddings=[query_embedding],
                n_results=n,
                include=["documents", "metadatas", "distances"],
            )

            for doc, meta, dist in zip(
                res["documents"][0],
                res["metadatas"][0],
                res["distances"][0],
            ):
                cosine_score = 1 - dist
                if cosine_score < config.MEMORY_RELEVANCE_THRESHOLD:
                    continue

                import_w = (meta or {}).get("importance_weight", 0.3)
                if isinstance(import_w, str):
                    try:
                        import_w = float(import_w)
                    except ValueError:
                        import_w = 0.3

                ts_str = (meta or {}).get("timestamp", "")
                if ts_str:
                    try:
                        age_days = (datetime.now() - datetime.fromisoformat(ts_str)).days
                        recency = max(0.3, 1.0 - (age_days / 365))
                    except ValueError:
                        recency = 0.5
                else:
                    recency = 0.5

                final_score = cosine_score * 0.45 + import_w * 0.30 + recency * 0.15 + 0.1

                # Phase 3: Freshness labels
                age = memory_age_label(ts_str)
                warn = freshness_warning(ts_str)

                results.append({
                    "content": doc,
                    "category": cat_name,
                    "score": round(final_score, 4),
                    "metadata": meta,
                    "age_label": age,
                    "freshness_warning": warn,
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    # ----------------------------------------------------------
    #  管理功能
    # ----------------------------------------------------------
    def get_stats(self) -> dict:
        """返回各集合的记忆条数（旧 + 新 4 层分类）"""
        return {
            # 新 4 层分类 (Claude Code 模式)
            "user": self.user_col.count(),
            "feedback": self.feedback_col.count(),
            "project": self.project_col.count(),
            "reference": self.reference_col.count(),
            # 旧类别 (向后兼容)
            "user_preferences": self.preferences.count(),
            "past_errors": self.errors.count(),
            "key_data": self.data_points.count(),
            "conversations": self.conversations.count(),
        }

    def get_all(self, category: str = None):
        """列出某类别的全部记忆，或全部"""
        collection_map = {
            "user_preferences": self.preferences,
            "past_errors": self.errors,
            "key_data": self.data_points,
            "conversations": self.conversations,
            "user": self.user_col,
            "feedback": self.feedback_col,
            "project": self.project_col,
            "reference": self.reference_col,
        }
        if category:
            cols = {category: collection_map[category]}
        else:
            cols = collection_map
        result = {}
        for cat_name, col in cols.items():
            items = []
            if col.count() == 0:
                result[cat_name] = items
                continue
            res = col.get(include=["documents", "metadatas"])
            for doc, meta in zip(res["documents"], res["metadatas"]):
                ts_str = meta.get("timestamp", "")
                items.append({
                    "content": doc,
                    "category": cat_name,
                    "metadata": meta,
                    "age_label": memory_age_label(ts_str),
                    "freshness_warning": freshness_warning(ts_str),
                })
            result[cat_name] = items
        return result

    def clear_all(self):
        """清空所有记忆（慎用）"""
        for name in ["user_preferences", "past_errors", "key_data", "conversations"]:
            self.client.delete_collection(name)
        self.__init__()
