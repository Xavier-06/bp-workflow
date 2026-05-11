#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'tasks' / 'ir-memory-boundary.json'

status = {
    'primary_memory': ['memory_agent', 'instruction_store'],
    'daily_memory': ['memory/YYYY-MM-DD.md'],
    'lessons': ['.learnings/'],
    'final_reports_index': ['reports/'],
    'workflow_artifacts_index': ['data/tasks/'],
    'native_memory_primary': False,
    'current_state': 'workspace-memory-primary',
    'gaps': [
        'OpenClaw native memory 还没有并成主存储',
        'memory_agent / daily logs / learnings 之间还缺统一索引视图',
        '还没有一个单入口脚本总结当前研究任务应从哪些记忆源优先读取',
    ],
    'next_actions': [
        '补一个 research 任务开场时的 memory source summary',
        '把 instruction_store 与 memory_agent 的检索边界写成统一检查脚本',
        '明确哪些内容升级进 native memory，哪些继续留在 workspace-memory',
    ]
}
OUT.write_text(json.dumps(status, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(OUT)
