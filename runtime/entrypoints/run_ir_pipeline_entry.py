from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.orchestrator.state_store import run_pipeline
from runtime.profiles.base import JobContext
from runtime.profiles.ir_profile import IRProfile


RUNTIME_ROOT = Path(__file__).resolve().parents[2]


def run_ir_job(
    job_id: str,
    entity: str = "",
    query: str = "",
    market: str = "us",
    ticker: str = "",
    english_name: str = "",
    max_extract_pages: int = 15,
    rounds: int = 3,
    use_facts: bool = True,
    max_new_queries: int = 12,
    include_snippets: bool = False,
    session_id: str = "",
    dispatch_max_wait: int = 1800,
    dispatch_poll_interval: int = 30,
    migrate_phases: list[str] | None = None,
    legacy_fallback: bool = False,
    start_phase: str | None = None,
) -> dict:
    profile = IRProfile(runtime_root=RUNTIME_ROOT)
    job_ctx = JobContext(
        job_id=job_id,
        entity=entity,
        query=query,
        market=market,
        metadata={
            "ticker": ticker,
            "english_name": english_name,
            "max_extract_pages": max_extract_pages,
            "rounds": rounds,
            "use_facts": use_facts,
            "max_new_queries": max_new_queries,
            "include_snippets": include_snippets,
            "market": market,
            "session_id": session_id,
            "dispatch_max_wait": dispatch_max_wait,
            "dispatch_poll_interval": dispatch_poll_interval,
            "migrate_phases": migrate_phases or [],
            "legacy_fallback": legacy_fallback,
        },
    )
    return run_pipeline(profile=profile, job_ctx=job_ctx, runtime_root=RUNTIME_ROOT,
                        start_phase=start_phase)
