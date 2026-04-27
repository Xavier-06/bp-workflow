from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.orchestrator.state_store import run_pipeline
from runtime.profiles.base import JobContext
from runtime.profiles.bp_profile import BPProfile


RUNTIME_ROOT = Path(__file__).resolve().parents[2]


def run_bp_job(
    job_id: str,
    entity: str = "",
    query: str = "",
    market: str = "cn",
    input_file: str = "",
    ticker: str = "",
    english_name: str = "",
    rounds: int = 3,
    max_new_queries: int = 12,
    use_facts: bool = True,
    dispatch_max_wait: int = 1800,
    dispatch_poll_interval: int = 30,
    session_id: str = "",
    migrate_phases: list[str] | None = None,
    start_phase: str | None = None,
) -> dict[str, Any]:
    """BP pipeline 入口 — shared kernel 分步派发版

    Args:
        job_id: 任务 ID
        entity: 实体名称（公司名）
        query: 查询关键词
        market: 市场（cn/us/hk）
        input_file: BP 文件路径（PDF/PPTX/DOCX/图片）
        ticker: 股票代码
        english_name: 英文名
        rounds: 子代理内部 gap-driven 补搜轮次上限
        max_new_queries: 每轮最大新查询数
        use_facts: gap 检测是否使用 facts
        dispatch_max_wait: dispatch 轮询最大等待（秒）
        dispatch_poll_interval: dispatch 轮询间隔（秒）
        session_id: 会话 ID（交付通知用）
        migrate_phases: 指定迁移的 phase 列表
        start_phase: 从指定阶段开始执行（用于恢复）
    """
    profile = BPProfile(runtime_root=RUNTIME_ROOT)

    metadata: dict[str, Any] = {
        "input_file": input_file,
        "ticker": ticker,
        "english_name": english_name,
        "rounds": rounds,
        "max_new_queries": max_new_queries,
        "use_facts": use_facts,
        "dispatch_max_wait": dispatch_max_wait,
        "dispatch_poll_interval": dispatch_poll_interval,
        "session_id": session_id,
        "migrate_phases": migrate_phases or [],
    }

    job_ctx = JobContext(
        job_id=job_id,
        entity=entity,
        query=query,
        market=market,
        metadata=metadata,
    )

    return run_pipeline(
        profile=profile,
        job_ctx=job_ctx,
        runtime_root=RUNTIME_ROOT,
        start_phase=start_phase,
    )
