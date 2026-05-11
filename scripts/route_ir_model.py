#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT/'config'/'ir-runtime.json'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task-type', default='专题研究类')
    ap.add_argument('--stage', default='controller')
    args = ap.parse_args()
    data = json.loads(CFG.read_text(encoding='utf-8'))
    routing = data.get('routing', {})
    per = routing.get('task_type_stage_models', {})
    model = per.get(args.task_type, {}).get(args.stage)
    if not model:
        model = routing.get('primary_controller')
    out = {
        'task_type': args.task_type,
        'stage': args.stage,
        'preferred_model': model,
        'fallback_model': routing.get('fallback_controller'),
        'fallback_notice_required': routing.get('fallback_notice_required', True)
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
