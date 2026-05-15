# Transfer Manifest

## Bundle Type
Portable IR pipeline runtime bundle for Workbuddy.

## Included
- IR pipeline scripts and shared helpers
- Research/content modules
- Instruction store
- Memory system code (without venv/logs/db)
- Memory bridge + topic memory snapshot
- Install guide + path patcher + env template

## Excluded
- `.credentials/*` real secrets
- `memory_agent/venv/`
- `memory_agent/logs/`
- `memory_agent/memory_db/` (moved to memory snapshot bundle)
- `__pycache__/`, `*.pyc`, backup files
- proactive/reminder/personal automation scripts
- BP pipeline scripts (this bundle is IR-focused)
