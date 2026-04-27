from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobWorkspace:
    root: Path
    state_dir: Path
    briefs_dir: Path
    search_dir: Path
    extraction_dir: Path
    artifacts_dir: Path
    outputs_dir: Path
    verification_dir: Path
    delivery_dir: Path


def build_job_workspace(root: Path, job_id: str) -> JobWorkspace:
    job_root = root / "jobs" / job_id
    workspace = JobWorkspace(
        root=job_root,
        state_dir=job_root / "state",
        briefs_dir=job_root / "briefs",
        search_dir=job_root / "search",
        extraction_dir=job_root / "extraction",
        artifacts_dir=job_root / "artifacts",
        outputs_dir=job_root / "outputs",
        verification_dir=job_root / "verification",
        delivery_dir=job_root / "delivery",
    )
    for path in workspace.__dict__.values():
        path.mkdir(parents=True, exist_ok=True)
    return workspace
