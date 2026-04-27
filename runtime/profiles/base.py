from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

PhaseHandler = Callable[["JobContext"], dict[str, Any]]


@dataclass
class PipelineProfile:
    """Base profile contract for shared IR/BP orchestration."""

    name: str
    job_type: str
    phase_handlers: dict[str, PhaseHandler] = field(default_factory=dict)

    def phases(self) -> list[str]:
        return list(self.phase_handlers.keys())

    def run_phase(self, phase_name: str, job_ctx: "JobContext") -> dict[str, Any]:
        handler = self.phase_handlers.get(phase_name)
        if handler is None:
            raise KeyError(f"Phase '{phase_name}' is not registered for profile '{self.name}'")
        return handler(job_ctx)

    def search_policy(self) -> dict[str, Any]:
        return {}

    def verification_policy(self) -> dict[str, Any]:
        return {}


@dataclass
class JobContext:
    """Normalized runtime context passed through the orchestrator kernel."""

    job_id: str
    entity: str = ""
    query: str = ""
    market: str = "us"
    metadata: dict[str, Any] = field(default_factory=dict)
    workspace: Optional[Any] = None  # JobWorkspace — injected by kernel before phase execution
