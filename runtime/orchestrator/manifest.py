from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class AssignmentManifest:
    job_id: str
    role: str
    step: str
    brief_path: str
    output_path: str
    timeout: int
    thinking: str = "high"
    status: str = "pending"
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["metadata"] is None:
            payload["metadata"] = {}
        return payload


def write_manifest(path: Path, manifest: AssignmentManifest) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
