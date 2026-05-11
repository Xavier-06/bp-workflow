#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

VALID_PACKS = [
    'industry',
    'data-collection',
    'valuation',
    'risk-catalyst',
    'differentiation',
]


def load_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return default


def load_existing_plan(task_id: str) -> tuple[Path, dict]:
    path = TASKS_DIR / f'{task_id}-S02-search-plan.json'
    if not path.exists():
        raise SystemExit(f'search plan not found: {path}')
    return path, load_json(path)


def discover_gap_packs(task_id: str) -> list[tuple[str, Path, dict]]:
    found = []
    for slug in VALID_PACKS:
        path = TASKS_DIR / f'{task_id}-gap-pack-{slug}.json'
        if path.exists():
            found.append((slug, path, load_json(path)))
    return found


def extract_queries(pack: dict) -> list[str]:
    out = []
    for item in pack.get('priority_queries', []) or []:
        if isinstance(item, dict):
            if 'query' in item and item['query']:
                out.append(item['query'])
            for q in item.get('queries', []) or []:
                if q:
                    out.append(q)
    return out


def extract_sources(pack: dict) -> list[str]:
    out = []
    for item in pack.get('priority_sources', []) or []:
        if isinstance(item, dict):
            src = item.get('source')
            if src:
                out.append(src)
            for s in item.get('sources', []) or []:
                if s:
                    out.append(s)
    return out


def extract_gaps(pack: dict) -> list[str]:
    out = []
    for item in pack.get('evidence_gaps', []) or []:
        if isinstance(item, dict):
            gap = item.get('gap') or item.get('current_state') or item.get('why_blocking')
            if gap:
                out.append(gap)
    return out


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def build_recovery_groups(packs: list[tuple[str, Path, dict]]) -> tuple[list[dict], list[str], list[str]]:
    groups = []
    extra_hints = []
    gap_summaries = []
    title_map = {
        'industry': 'Gap Recovery / 行业结构与竞争',
        'data-collection': 'Gap Recovery / 数据与一致预期',
        'valuation': 'Gap Recovery / 估值与目标价',
        'risk-catalyst': 'Gap Recovery / 风险催化',
        'differentiation': 'Gap Recovery / 差异化洞察',
    }
    for slug, path, pack in packs:
        queries = dedupe_keep_order(extract_queries(pack))
        sources = dedupe_keep_order(extract_sources(pack))
        gaps = dedupe_keep_order(extract_gaps(pack))
        if queries:
            groups.append({
                'sub_question': title_map.get(slug, f'Gap Recovery / {slug}'),
                'queries': queries[:10],
                'source_pack': path.name,
                'role_key': pack.get('role_key', slug),
            })
        extra_hints.extend(sources[:8])
        gap_summaries.extend(gaps[:6])
    return groups, dedupe_keep_order(extra_hints), dedupe_keep_order(gap_summaries)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task-id', required=True)
    ap.add_argument('--suffix', default='S02R1')
    args = ap.parse_args()

    base_path, plan = load_existing_plan(args.task_id)
    packs = discover_gap_packs(args.task_id)
    if not packs:
        raise SystemExit('no valid gap packs found')

    recovery_groups, extra_hints, gap_summaries = build_recovery_groups(packs)
    recovery_queries = []
    for group in recovery_groups:
        recovery_queries.extend(group.get('queries', []))

    new_plan = dict(plan)
    new_plan['generated_at'] = new_plan.get('generated_at')
    new_plan['subtask_id'] = f"{args.task_id}-{args.suffix}"
    new_plan['recovery_from'] = str(base_path)
    new_plan['gap_packs_used'] = [path.name for _, path, _ in packs]
    new_plan['recovery_mode'] = 'gap-pack-upgrade'
    new_plan['sub_questions'] = dedupe_keep_order((plan.get('sub_questions') or []) + [g['sub_question'] for g in recovery_groups])
    new_plan['query_groups'] = (plan.get('query_groups') or []) + recovery_groups
    new_plan['search_queries'] = dedupe_keep_order((plan.get('search_queries') or []) + recovery_queries)
    new_plan['source_hints'] = dedupe_keep_order((plan.get('source_hints') or []) + extra_hints)
    notes = plan.get('notes', '')
    upgrade_note = '已根据有效 gap packs 增补 recovery queries / source hints，用于补齐估值、竞争、出口限制等主线证据。'
    new_plan['notes'] = notes + (' | ' if notes else '') + upgrade_note
    new_plan['recovery_gap_summary'] = gap_summaries

    out_path = TASKS_DIR / f'{args.task_id}-{args.suffix}-search-plan.json'
    out_path.write_text(json.dumps(new_plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'task_id': args.task_id,
        'base_plan': str(base_path),
        'output': str(out_path),
        'gap_packs_used': new_plan['gap_packs_used'],
        'added_query_groups': len(recovery_groups),
        'added_queries': len(recovery_queries),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
