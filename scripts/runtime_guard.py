#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


@contextmanager
def runtime_lock(lock_path: str | Path, stale_seconds: int = 900):
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    current_pid = os.getpid()
    existing = _read_json(path)
    holder_pid = int(existing.get('pid', 0) or 0)
    holder_started = int(existing.get('started_at', 0) or 0)
    holder_age = max(0, now - holder_started) if holder_started else None

    locked = False
    info = {
        'locked': False,
        'reason': None,
        'existing': existing,
        'pid': current_pid,
        'path': str(path),
    }

    if existing:
        if holder_pid and _pid_alive(holder_pid) and holder_age is not None and holder_age < stale_seconds:
            info['reason'] = 'already_running'
            yield info
            return

    payload = {'pid': current_pid, 'started_at': now}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    locked = True
    info['locked'] = True
    try:
        yield info
    finally:
        if locked:
            latest = _read_json(path)
            if int(latest.get('pid', 0) or 0) == current_pid:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
