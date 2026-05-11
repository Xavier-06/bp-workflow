#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime

from runtime_guard import runtime_lock

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'
SELECTOR = ROOT / 'scripts' / 'select_next_ir_task.py'
CHECKLIST = TASKS_DIR / 'p3-checklist.json'
IR_RUNTIME = ROOT / 'config' / 'ir-runtime.json'
SEARCH_PLAN_SCRIPT = ROOT / 'scripts' / 'generate_ir_search_plan.py'
RUN_IR_TASK = ROOT / 'scripts' / 'run_ir_task.py'
SUBAGENT_HANDOFF = ROOT / 'scripts' / 'build_ir_subagent_handoff.py'
DISPATCH_SUBAGENT = ROOT / 'scripts' / 'dispatch_ir_subagent_via_agent.py'
PROACTIVE = ROOT / 'scripts' / 'run_proactive_cycle.py'
TASK_LEDGER = ROOT / 'scripts' / 'task_ledger.py'
VERIFY_STEP1 = ROOT / 'scripts' / 'verify_step1_completeness.py'
VERIFY_CONSISTENCY = ROOT / 'scripts' / 'verify_cross_step_consistency.py'
LAST_RUN = TASKS_DIR / 'last-execution-loop.json'
LOOP_STATE = TASKS_DIR / 'execution-loop-state.json'
LOCK_PATH = TASKS_DIR / 'execution-loop.lock'

# lock should outlive long steps (launchd interval is 120s)
LOCK_STALE_SECONDS = 7200

# guard against true loops (e.g., artifact never appears)
MAX_REPEAT_DECISIONS = 4

# Per-step timeouts (seconds). Longest step is fill_packet (web fetch).
STEP_TIMEOUTS = {
    'expand_subtasks': 60,
    'generate_search_plan': 60,
    'render_packet': 60,
    'fill_packet': 900,
    'verify_step1': 60,
    'build_evidence': 120,
    'build_reviewer': 120,
    'filter_evidence': 60,
    'build_analysis': 180,
    'build_memo': 240,
    'build_instruction_guided_memo': 180,
    'verify_consistency': 60,
    'assemble_bundle': 120,
    'apply_source_upgrade_v2': 1200,
}

LONG_ACTIONS = {'fill_packet'}
HEARTBEAT_EVERY_SECONDS = 300

ACTION_OWNER = {
    'expand_subtasks': 'orchestrator',
    'generate_search_plan': 'builder_search',
    'render_packet': 'builder_search',
    'fill_packet': 'builder_search',
    'verify_step1': 'reviewer',
    'build_evidence': 'builder_search',
    'build_reviewer': 'reviewer',
    'filter_evidence': 'reviewer',
    'build_analysis': 'builder_analysis',
    'build_memo': 'builder_analysis',
    'build_instruction_guided_memo': 'writer',
    'verify_consistency': 'reviewer',
    'assemble_bundle': 'writer',
    'apply_source_upgrade_v2': 'builder_search',
    'request_search_plan_review': 'builder_search',
    'request_clean_evidence_review': 'reviewer',
    'request_analysis_writer_polish': 'writer',
    'await_search_plan_review': 'orchestrator',
    'await_clean_evidence_review': 'orchestrator',
    'await_analysis_writer_polish': 'orchestrator',
    'fail_search_plan_review': 'reviewer',
    'fail_clean_evidence_review': 'reviewer',
    'fail_analysis_writer_polish': 'writer',
}


def sh(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return p.stdout.strip()


def run_noisy(cmd: list[str], timeout_s: int | None = None) -> dict:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        return {'code': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr, 'timeout': False}
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or '') if isinstance(e.stdout, str) else ''
        err = (e.stderr or '') if isinstance(e.stderr, str) else ''
        return {'code': 124, 'stdout': out, 'stderr': err, 'timeout': True, 'timeout_s': timeout_s}


def load_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _task_package(task_id: str) -> dict:
    return load_json(TASKS_DIR / f'{task_id}.json', {}) or {}


def append_manifest(task_id: str, event: dict):
    mpath = TASKS_DIR / f'{task_id}-execution-manifest.json'
    data = load_json(mpath)
    if not data:
        pkg = _task_package(task_id)
        task_type = ((pkg.get('task') or {}).get('task_type')) or ''
        data = {
            'task_id': task_id,
            'created_at': datetime.now().isoformat(timespec='seconds'),
            'execution_mode': 'subagent-gated-script-pipeline' if subagent_enabled_for(task_type) else 'single-orchestrator-script-pipeline',
            'model_route': pkg.get('model_route', {}),
            'instruction_keys': pkg.get('instruction_keys', []),
            'events': [],
        }
    e = dict(event)
    e['at'] = datetime.now().isoformat(timespec='seconds')
    data.setdefault('events', []).append(e)
    data['updated_at'] = datetime.now().isoformat(timespec='seconds')
    save_json(mpath, data)


def run_step_cmd(task_id: str, action: str, cmd: list[str], timeout_s: int | None = None) -> dict:
    start = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    next_hb = start + HEARTBEAT_EVERY_SECONDS

    while True:
        ret = proc.poll()
        now = time.time()
        elapsed = int(now - start)

        if ret is not None:
            out, err = proc.communicate()
            return {
                'code': ret,
                'stdout': out or '',
                'stderr': err or '',
                'timeout': False,
                'elapsed_s': elapsed,
            }

        if now >= next_hb:
            mins = max(1, elapsed // 60)
            add_progress(task_id, f'步骤仍在执行：{action}（已运行约 {mins} 分钟）', stage=f'{action}-heartbeat', flush=True)
            append_manifest(task_id, {'type': 'heartbeat', 'action': action, 'elapsed_s': elapsed})
            next_hb += HEARTBEAT_EVERY_SECONDS

        if timeout_s and elapsed > timeout_s:
            proc.kill()
            out, err = proc.communicate()
            return {
                'code': 124,
                'stdout': out or '',
                'stderr': err or '',
                'timeout': True,
                'timeout_s': timeout_s,
                'elapsed_s': elapsed,
            }

        time.sleep(1)




def clean_evidence_stats(task_id: str) -> dict:
    p = TASKS_DIR / f'{task_id}-evidence-clean.json'
    data = load_json(p, {}) or {}
    return {
        'exists': p.exists(),
        'kept_count': data.get('kept_count', 0),
        'dropped_count': data.get('dropped_count', 0),
        'path': str(p),
    }


def ir_runtime_config() -> dict:
    return load_json(IR_RUNTIME, {}) or {}


def subagent_enabled_for(task_type: str) -> bool:
    runtime = ir_runtime_config()
    routing = runtime.get('routing', {})
    policy = routing.get('subagent_policy', {}) or {}
    if not policy.get('enabled'):
        return False
    spawn_when = policy.get('spawn_when', []) or []
    if task_type in spawn_when:
        return True
    return task_type == '专题研究类'


def subagent_hook_paths(task_id: str) -> dict[str, dict[str, Path]]:
    return {
        'search-plan-review': {
            'brief': TASKS_DIR / f'{task_id}-search-plan-review-brief.md',
            'spawn_receipt': TASKS_DIR / f'{task_id}-search-plan-review-spawn.json',
            'result': TASKS_DIR / f'{task_id}-search-plan-review.json',
        },
        'clean-evidence-review': {
            'brief': TASKS_DIR / f'{task_id}-clean-evidence-review-brief.md',
            'spawn_receipt': TASKS_DIR / f'{task_id}-clean-evidence-review-spawn.json',
            'result': TASKS_DIR / f'{task_id}-clean-evidence-review.json',
        },
        'analysis-writer-polish': {
            'brief': TASKS_DIR / f'{task_id}-analysis-writer-polish-brief.md',
            'spawn_receipt': TASKS_DIR / f'{task_id}-analysis-writer-polish-spawn.json',
            'result': TASKS_DIR / f'{task_id}-analysis-writer-polish.json',
            'output': TASKS_DIR / f'{task_id}-analysis-polished.md',
        },
    }


def load_subagent_result(path: Path) -> dict:
    data = load_json(path, {}) or {}
    return data if isinstance(data, dict) else {}


def load_subagent_spawn_receipt(path: Path) -> dict:
    data = load_json(path, {}) or {}
    return data if isinstance(data, dict) else {}


def valid_subagent_spawn_receipt(data: dict, hook: str) -> bool:
    return (
        isinstance(data, dict)
        and data.get('hook') == hook
        and (data.get('childSessionKey') or data.get('runId'))
    )


def subagent_hook_gate(task_id: str, hook: str) -> dict | None:
    paths = subagent_hook_paths(task_id)[hook]
    if not paths['brief'].exists():
        return {
            'action': f"request_{hook.replace('-', '_')}",
            'cmd': ['/usr/bin/env python3', str(SUBAGENT_HANDOFF), task_id, '--hook', hook],
            'artifact': str(paths['brief']),
            'hook': hook,
            'spawn_receipt_path': str(paths['spawn_receipt']),
            'await_path': str(paths['result']),
        }

    receipt = load_subagent_spawn_receipt(paths['spawn_receipt'])
    if not valid_subagent_spawn_receipt(receipt, hook):
        return {
            'action': f"dispatch_{hook.replace('-', '_')}",
            'cmd': ['/usr/bin/env python3', str(DISPATCH_SUBAGENT), task_id, '--hook', hook],
            'artifact': str(paths['spawn_receipt']),
            'brief': str(paths['brief']),
            'result': str(paths['result']),
            'hook': hook,
            'reason': 'missing_real_subagent_spawn_receipt',
        }

    result = load_subagent_result(paths['result'])
    if not result:
        return {
            'action': f"await_{hook.replace('-', '_')}",
            'cmd': None,
            'artifact': str(paths['result']),
            'hook': hook,
            'spawn_receipt': receipt,
        }

    if result.get('approved') is False:
        # search-plan-review: soft gate — log suggestions, continue pipeline
        if hook == 'search-plan-review':
            suggestions_path = TASKS_DIR / f'{task_id}-search-plan-review-suggestions.json'
            suggestions_path.write_text(json.dumps({
                'summary': result.get('summary', ''),
                'blocking_issues': result.get('blocking_issues', []),
                'suggestions': result.get('suggestions', []),
                'soft_approved': True,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            # Treat as passed — return None to continue
            return None
        return {
            'action': f"fail_{hook.replace('-', '_')}",
            'cmd': None,
            'artifact': str(paths['result']),
            'hook': hook,
            'result': result,
            'spawn_receipt': receipt,
        }

    if hook == 'analysis-writer-polish':
        out_path = Path(result.get('output_path') or result.get('polished_analysis_path') or paths['output'])
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        if not out_path.exists():
            return {
                'action': f"await_{hook.replace('-', '_')}",
                'cmd': None,
                'artifact': str(out_path),
                'hook': hook,
                'spawn_receipt': receipt,
            }
    return None


def analysis_source_path(task_id: str, default_path: Path) -> Path:
    paths = subagent_hook_paths(task_id).get('analysis-writer-polish', {})
    result = load_subagent_result(paths.get('result', Path('/nonexistent')))
    if result.get('approved'):
        out_path = Path(result.get('output_path') or paths.get('output', default_path))
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        if out_path.exists():
            return out_path
    return default_path


def summarize_task_result(task_id: str) -> str:
    stats = clean_evidence_stats(task_id)
    memo_path = TASKS_DIR / f'{task_id}-final-memo.md'
    quality = '待评估'
    if memo_path.exists():
        memo = memo_path.read_text(encoding='utf-8')[:4000]
        if ('当前仍缺可用证据' in memo) or ('待核查' in memo):
            quality = '未过线（仍有待核查/缺证据）'
        else:
            quality = '基础可读（需人工复核）'
    bundle_path = TASKS_DIR / f'{task_id}-bundle.json'
    bundle_status = 'unknown'
    if bundle_path.exists():
        bundle = load_json(bundle_path, {}) or {}
        bundle_status = bundle.get('status') or 'unknown'
    return (
        f"闭环结果：clean evidence kept={stats.get('kept_count', 0)}，dropped={stats.get('dropped_count', 0)}；"
        f"memo质量={quality}；bundle={bundle_status}。"
    )


def tier_memory_hint(task: dict) -> dict:
    title = task.get('title', '')
    notes = task.get('notes', '')
    if '压测' in title or 'review' in title.lower() or '验收' in title:
        return {'tier': 'HOT', 'reason': '当前压测/验收任务，需保留在活跃上下文'}
    if any(k in notes for k in ['偏好', '规则', '长期']):
        return {'tier': 'WARM', 'reason': '涉及稳定规则/偏好'}
    return {'tier': 'HOT', 'reason': '默认活跃任务进入 HOT；阶段总结再晋升到 WARM/COLD'}

def ensure_selection() -> dict:
    out = sh(['/usr/bin/env python3', str(SELECTOR)])
    return json.loads(out)


def append_note_once(text: str, piece: str) -> str:
    parts = [p.strip() for p in (text or '').split('|') if p.strip()]
    if piece not in parts:
        parts.append(piece)
    return ' | '.join(parts)


def trim_error(text: str, limit: int = 240) -> str:
    text = (text or '').strip().replace('\n', ' | ')
    return text[:limit] if text else '执行失败，无详细报错'


def update_task(task_id: str, **kwargs):
    cmd = ['/usr/bin/env python3', str(TASK_LEDGER), 'update', task_id]
    mapping = {
        'status': '--status',
        'next_action': '--next-action',
        'notes': '--notes',
        'blocked_reason': '--blocked-reason',
        'output_path': '--output-path',
    }
    for k, flag in mapping.items():
        v = kwargs.get(k)
        if v is not None:
            cmd.extend([flag, str(v)])
    sh(cmd)


def add_progress(task_id: str, message: str, stage: str, flush: bool = True):
    cmd = ['/usr/bin/env python3', str(TASK_LEDGER), 'progress', task_id, message, '--stage', stage]
    subprocess.run(cmd, capture_output=True, text=True)
    if flush:
        # push this specific event immediately; retry briefly if proactive lock is busy
        proactive_cmd = [
            'python3', str(PROACTIVE),
            '--progress-only',
            '--task-id', task_id,
            '--stage', stage,
            '--latest-only',
        ]
        for _ in range(20):
            p = subprocess.run(proactive_cmd, capture_output=True, text=True)
            out = (p.stdout or '').strip()
            if 'lock_skipped' not in out:
                break
            time.sleep(0.5)


def ensure_checklist() -> dict:
    data = load_json(CHECKLIST)
    if not data:
        data = {
            'updated_at': datetime.now().isoformat(timespec='seconds'),
            'steps': {
                'P3-1-selector': {'status': 'pending', 'note': ''},
                'P3-2-execution-loop': {'status': 'pending', 'note': ''},
                'P3-3-proactive-communication': {'status': 'pending', 'note': ''},
                'P3-4-workflow-hardening': {'status': 'pending', 'note': ''},
                'P3-5-test-case-validation': {'status': 'pending', 'note': '英伟达重跑验收待执行'},
            }
        }
    text_search = SEARCH_PLAN_SCRIPT.read_text(encoding='utf-8') if SEARCH_PLAN_SCRIPT.exists() else ''
    text_run_ir = RUN_IR_TASK.read_text(encoding='utf-8') if RUN_IR_TASK.exists() else ''
    text_proactive = PROACTIVE.read_text(encoding='utf-8') if PROACTIVE.exists() else ''
    runtime = load_json(IR_RUNTIME, {}) or {}
    roles = runtime.get('routing', {}).get('agent_role_assignment', {})

    steps = data['steps']
    execution_text = (ROOT / 'scripts' / 'run_ir_execution_loop.py').read_text(encoding='utf-8')
    steps['P3-1-selector'] = {'status': 'done' if SELECTOR.exists() else 'pending', 'note': 'select_next_ir_task.py 已落地'}
    steps['P3-2-execution-loop'] = {
        'status': 'done' if ('--execute' in execution_text) else 'in_progress',
        'note': 'execution loop 已支持 execute 模式' if ('--execute' in execution_text) else 'run_ir_execution_loop.py 首版'
    }
    proactive_ok = ('synthetic keepalive disabled' in text_proactive and 'synthetic periodic checkin disabled' in text_proactive)
    steps['P3-3-proactive-communication'] = {
        'status': 'done' if proactive_ok else 'in_progress',
        'note': '已关闭伪进度，只保留真实阶段消息' if proactive_ok else '待继续收口'
    }
    workflow_ok = (
        '投研_主笔_预测与估值' in text_run_ir and
        'company-report' in text_search and
        roles.get('orchestrator')
    )
    steps['P3-4-workflow-hardening'] = {
        'status': 'done' if workflow_ok else 'in_progress',
        'note': '模型分工/query模板/预测估值主笔已接入' if workflow_ok else '待整体验证'
    }
    data['updated_at'] = datetime.now().isoformat(timespec='seconds')
    save_json(CHECKLIST, data)
    return data


def checklist_ready(checklist: dict) -> bool:
    steps = checklist.get('steps', {})
    return all(steps.get(k, {}).get('status') == 'done' for k in ['P3-1-selector', 'P3-2-execution-loop', 'P3-3-proactive-communication', 'P3-4-workflow-hardening'])




def is_manual_managed_task(task: dict) -> bool:
    title = (task.get('title') or '')
    notes = (task.get('notes') or '')
    notes_lower = notes.lower()
    # explicit override: allow auto-managed tasks to pass through planning loop
    if 'auto-managed' in notes_lower or 'auto_managed' in notes_lower or '自动推进' in notes:
        return False
    keywords = ['压测', '验收', '嵌入', '技能', 'review', 'skill']
    return any(k in title for k in keywords) or any(k in notes for k in ['direct-implementation', 'pressure-test', 'embed vetted skills'])

def planning_step_from_task(task: dict) -> dict:
    task_id = task['task_id']
    plan_md = TASKS_DIR / f'{task_id}-workplan.md'
    state_json = TASKS_DIR / f'{task_id}-workstate.json'
    status_md = TASKS_DIR / f'{task_id}-status-snapshot.md'
    queue_md = TASKS_DIR / f'{task_id}-queue-handoff.md'

    if not plan_md.exists():
        content = (
            f"# Workplan - {task_id}\n\n"
            f"- 任务标题：{task.get('title')}\n"
            f"- 当前下一步：{task.get('next_action')}\n"
            "- 目标：把投研智能体主线重新接回，并补队列连续自驱。\n\n"
            "## 本轮工作项\n"
            "1. 生成系统状态快照\n"
            "2. 生成队列交接说明\n"
            "3. 完成本轮整备并释放下一个主任务\n"
        )
        plan_md.write_text(content, encoding='utf-8')
        return {'action': 'create_workplan', 'cmd': None, 'artifact': str(plan_md)}

    state = load_json(state_json, {'step': 0, 'done': []})

    # custom manual step for TASK-20260318-020: apply source-upgrade-v2 and rebuild outputs
    if task_id == 'TASK-20260318-020' and state.get('step', 0) >= 2:
        if state.get('step') == 2:
            state['step'] = 3
            state.setdefault('done', []).append('apply_source_upgrade_v2')
            save_json(state_json, state)
            return {
                'action': 'apply_source_upgrade_v2',
                'cmd': ['/usr/bin/env python3', str(ROOT/'scripts'/'apply_source_upgrade_v2.py'), '--task-id', 'TASK-20260318-019'],
                'artifact': str(TASKS_DIR / 'TASK-20260318-019-final-memo.md')
            }
        if state.get('step', 0) >= 3:
            return {'action': 'complete', 'cmd': None, 'artifact': str(state_json)}

    if state['step'] == 0:
        selection = ensure_selection()
        checklist = ensure_checklist()
        content = [
            f"# Status Snapshot - {task_id}\n",
            f"生成时间：{datetime.now().isoformat(timespec='seconds')}\n\n",
            "## Checklist\n",
            json.dumps(checklist.get('steps', {}), ensure_ascii=False, indent=2),
            "\n\n## Selection\n",
            json.dumps(selection, ensure_ascii=False, indent=2),
            "\n",
        ]
        status_md.write_text(''.join(content), encoding='utf-8')
        state['step'] = 1
        state['done'].append('status_snapshot')
        save_json(state_json, state)
        return {'action': 'create_status_snapshot', 'cmd': None, 'artifact': str(status_md)}

    if state['step'] == 1:
        queue = {
            'generated_at': datetime.now().isoformat(timespec='seconds'),
            'next_primary_after_close': 'none-yet',
            'rule': 'When this planning task closes, selector should pick the highest-priority active task or stay idle if none.',
            'tests': [
                'single-task autonomous close works',
                'planning task no longer loops on planning_complete',
                'next task can be selected without user prompt'
            ]
        }
        queue_md.write_text('# Queue Handoff\n\n' + json.dumps(queue, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        state['step'] = 2
        state['done'].append('queue_handoff')
        save_json(state_json, state)
        return {'action': 'create_queue_handoff', 'cmd': None, 'artifact': str(queue_md)}

    if state['step'] >= 2:
        return {'action': 'complete', 'cmd': None, 'artifact': str(state_json)}

    return {'action': 'planning_complete', 'cmd': None, 'artifact': str(plan_md)}


def research_step_from_task(task_id: str, task_type: str = '专题研究类') -> dict:
    # 对话路径完成检测：如果 step8_master 已存在，直接返回 complete
    # 避免管线继续推进已经通过对话路径完成的任务
    conversation_master = TASKS_DIR / f'{task_id}-step8_master.md'
    if conversation_master.exists() and conversation_master.stat().st_size > 1000:
        return {'action': 'complete', 'cmd': None, 'note': 'conversation-path already completed (step8_master exists)'}

    outputs = {
        'package': TASKS_DIR / f'{task_id}.json',
        'subtasks': TASKS_DIR / f'{task_id}-subtasks.json',
        's02_plan': TASKS_DIR / f'{task_id}-S02-search-plan.json',
        's02_packet': TASKS_DIR / f'{task_id}-S02-packet.md',
        's02_filled': TASKS_DIR / f'{task_id}-S02-packet-filled.md',
        'step1_verify': TASKS_DIR / f'{task_id}-step1-verify.json',
        'evidence': TASKS_DIR / f'{task_id}-evidence.json',
        'reviewer': TASKS_DIR / f'{task_id}-reviewer.json',
        'evidence_clean': TASKS_DIR / f'{task_id}-evidence-clean.json',
        'analysis': TASKS_DIR / f'{task_id}-analysis-draft.md',
        'analysis_polished': TASKS_DIR / f'{task_id}-analysis-polished.md',
        'memo': TASKS_DIR / f'{task_id}-final-memo.md',
        'instruction_guided_memo': TASKS_DIR / f'{task_id}-final-memo-instruction-guided.md',
        'consistency_check': TASKS_DIR / f'{task_id}-consistency-check.json',
        'bundle': TASKS_DIR / f'{task_id}-bundle.json',
    }
    subagent_mode = subagent_enabled_for(task_type)

    if not outputs['subtasks'].exists():
        return {'action': 'expand_subtasks', 'cmd': ['/usr/bin/env python3', str(ROOT/'scripts'/'expand_ir_subtasks.py'), task_id], 'artifact': str(outputs['subtasks'])}
    if not outputs['s02_plan'].exists():
        return {'action': 'generate_search_plan', 'cmd': ['/usr/bin/env python3', str(ROOT/'scripts'/'generate_ir_search_plan.py'), f'{task_id}-S02'], 'artifact': str(outputs['s02_plan'])}
    if subagent_mode:
        gate = subagent_hook_gate(task_id, 'search-plan-review')
        if gate:
            return gate
    if not outputs['s02_packet'].exists():
        return {'action': 'render_packet', 'cmd': ['/usr/bin/env python3', str(ROOT/'scripts'/'render_ir_data_packet.py'), str(outputs['s02_plan'])], 'artifact': str(outputs['s02_packet'])}
    if not outputs['s02_filled'].exists():
        return {'action': 'fill_packet', 'cmd': ['/usr/bin/env python3', str(ROOT/'scripts'/'fill_ir_data_packet.py'), str(outputs['s02_plan'])], 'artifact': str(outputs['s02_filled'])}

    # ── 门禁 1：Step 1 数据包完整性检查 ──
    # fill_packet 已完成（s02_filled 存在），在 build_evidence 之前强制检查数据覆盖率
    if not outputs['step1_verify'].exists():
        return {
            'action': 'verify_step1',
            'cmd': [
                '/usr/bin/env python3',
                str(VERIFY_STEP1),
                '--task-id', task_id,
                '--file', str(outputs['s02_filled']),
            ],
            'artifact': str(outputs['step1_verify']),
        }
    # 如果 verify_step1 结果是 BLOCK，阻塞管线
    step1_result = load_json(outputs['step1_verify'], {})
    if step1_result and step1_result.get('verdict') == 'BLOCK':
        return {
            'action': 'gate_step1_block',
            'cmd': None,
            'artifact': str(outputs['step1_verify']),
            'gate': step1_result,
            'reason': step1_result.get('reason', '数据包完整性门禁未通过'),
        }

    if not outputs['evidence'].exists():
        return {'action': 'build_evidence', 'cmd': ['/usr/bin/env python3', str(ROOT/'scripts'/'build_ir_evidence_table.py'), str(outputs['s02_filled'])], 'artifact': str(outputs['evidence'])}
    if not outputs['reviewer'].exists():
        return {'action': 'build_reviewer', 'cmd': ['/usr/bin/env python3', str(ROOT/'scripts'/'build_ir_reviewer_report.py'), str(outputs['evidence'])], 'artifact': str(outputs['reviewer'])}
    if not outputs['evidence_clean'].exists():
        return {'action': 'filter_evidence', 'cmd': ['/usr/bin/env python3', str(ROOT/'scripts'/'filter_ir_evidence.py'), str(outputs['evidence']), str(outputs['reviewer'])], 'artifact': str(outputs['evidence_clean'])}
    if subagent_mode:
        stats = clean_evidence_stats(task_id)
        if stats['exists'] and stats['kept_count'] > 0:
            gate = subagent_hook_gate(task_id, 'clean-evidence-review')
            if gate:
                return gate
    if not outputs['analysis'].exists():
        stats = clean_evidence_stats(task_id)
        if stats['exists'] and stats['kept_count'] <= 0:
            return {'action': 'gate_no_clean_evidence', 'cmd': None, 'artifact': stats['path'], 'gate': stats}
        return {'action': 'build_analysis', 'cmd': ['/usr/bin/env python3', str(ROOT/'scripts'/'build_ir_analysis_draft.py'), str(outputs['evidence_clean'])], 'artifact': str(outputs['analysis'])}
    if subagent_mode:
        gate = subagent_hook_gate(task_id, 'analysis-writer-polish')
        if gate:
            return gate
    analysis_source = analysis_source_path(task_id, outputs['analysis'])
    if not outputs['memo'].exists():
        return {'action': 'build_memo', 'cmd': ['/usr/bin/env python3', str(ROOT/'scripts'/'build_ir_final_memo.py'), str(analysis_source)], 'artifact': str(outputs['memo'])}
    if not outputs['instruction_guided_memo'].exists():
        return {'action': 'build_instruction_guided_memo', 'cmd': ['/usr/bin/env python3', str(ROOT/'scripts'/'build_ir_instruction_guided_memo.py'), str(outputs['package']), str(analysis_source)], 'artifact': str(outputs['instruction_guided_memo'])}

    # ── 门禁 2：跨 Step 数据一致性检查 ──
    # 在 assemble_bundle 之前，检查所有 step 文件的数据一致性
    if not outputs['consistency_check'].exists():
        return {
            'action': 'verify_consistency',
            'cmd': [
                '/usr/bin/env python3',
                str(VERIFY_CONSISTENCY),
                '--task-id', task_id,
            ],
            'artifact': str(outputs['consistency_check']),
        }
    # 如果 consistency check 结果是 FAIL（有 ERROR 级不一致），阻塞管线
    consistency_result = load_json(outputs['consistency_check'], {})
    if consistency_result and consistency_result.get('verdict') == 'FAIL':
        return {
            'action': 'gate_consistency_fail',
            'cmd': None,
            'artifact': str(outputs['consistency_check']),
            'gate': consistency_result,
            'reason': consistency_result.get('reason', '跨章节数据不一致'),
        }

    if not outputs['bundle'].exists():
        return {'action': 'assemble_bundle', 'cmd': ['/usr/bin/env python3', str(ROOT/'scripts'/'assemble_ir_bundle.py'), task_id], 'artifact': str(outputs['bundle'])}
    return {'action': 'complete', 'cmd': None}

def maybe_promote_test_case(selection: dict, execute: bool) -> dict | None:
    support = selection.get('support_task')
    if not support or support.get('task_id') != 'TASK-20260317-034':
        return None
    if support.get('status') != '已阻塞':
        return None
    decision = {
        'action': 'promote_test_case',
        'task_id': support['task_id'],
        'reason': 'P3-1~P3-4 已完成，允许测试用例重新进入主链验收',
        'executed': False,
    }
    if execute:
        update_task(support['task_id'], status='进行中', next_action='按主链重跑：从 search plan / packet / evidence 开始', notes='P3 前四步已收口，恢复为测试验收任务')
        decision['executed'] = True
    return decision


def update_loop_state(task_id: str | None, action: str | None) -> dict:
    state = load_json(LOOP_STATE, {'task_id': None, 'action': None, 'repeat_count': 0, 'updated_at': None})
    if task_id and action and state.get('task_id') == task_id and state.get('action') == action:
        state['repeat_count'] = int(state.get('repeat_count', 0)) + 1
    else:
        state = {'task_id': task_id, 'action': action, 'repeat_count': 1 if task_id and action else 0, 'updated_at': None}
    state['updated_at'] = datetime.now().isoformat(timespec='seconds')
    save_json(LOOP_STATE, state)
    return state


def _resolve_recipient_target(recipient: str) -> str:
    """按 task recipient 字段解析飞书发送目标。谁让做的就发给谁。"""
    recipients_path = ROOT / 'config' / 'recipients.json'
    data = load_json(recipients_path, {})
    recipients = data.get('recipients', {})
    if recipient in recipients:
        return recipients[recipient]['target']
    for key, val in recipients.items():
        if val.get('display_name', '').lower() == recipient.lower():
            return val['target']
    return recipients.get('xavier', {}).get('target', 'user:ou_fc4728374aeed4fb302026963720c08c')


def write_last_run(result: dict):
    save_json(LAST_RUN, result)


# --- Dual-task support: when primary is waiting (await/dispatch/blocked), advance support_task ---
SUPPORT_LOOP_STATE = TASKS_DIR / 'execution-loop-state-support.json'

def update_support_loop_state(task_id: str | None, action: str | None) -> dict:
    state = load_json(SUPPORT_LOOP_STATE, {'task_id': None, 'action': None, 'repeat_count': 0, 'updated_at': None})
    if task_id and action and state.get('task_id') == task_id and state.get('action') == action:
        state['repeat_count'] = int(state.get('repeat_count', 0)) + 1
    else:
        state = {'task_id': task_id, 'action': action, 'repeat_count': 1 if task_id and action else 0, 'updated_at': None}
    state['updated_at'] = datetime.now().isoformat(timespec='seconds')
    save_json(SUPPORT_LOOP_STATE, state)
    return state


def _primary_is_waiting(action: str) -> bool:
    """True if primary's action means it can't make progress this tick."""
    return (
        action.startswith('await_')
        or action.startswith('dispatch_')
        or action in ('blocked', 'gate_no_clean_evidence', 'gate_step1_block', 'gate_consistency_fail', 'blocked_by_repeat_guard')
    )


def _try_advance_support(support: dict, execute: bool, result: dict) -> bool:
    """Attempt to advance support_task as a research task.
    Returns True if support was advanced (result['support_decision'] is set)."""
    if not support:
        return False
    if support.get('task_type') != '专题研究类':
        return False
    s_status = support.get('status')
    if s_status in ('已阻塞', '已完成', '待开始'):
        return False

    s_task_id = support['task_id']
    s_step = research_step_from_task(s_task_id, support.get('task_type', '专题研究类'))
    s_loop = update_support_loop_state(s_task_id, s_step.get('action'))
    s_action = s_step.get('action') or ''

    # repeat guard for support
    if s_loop.get('repeat_count', 0) >= MAX_REPEAT_DECISIONS and s_action != 'complete' and not s_action.startswith('await_'):
        reason = f"[support] execution-loop 重复 {s_loop['repeat_count']} 次停在 {s_action}，已自动熔断"
        if execute:
            update_task(s_task_id, status='已阻塞', next_action='人工复核', blocked_reason=reason,
                        notes=append_note_once(support.get('notes', ''), 'support repeat-guard blocked'))
        result['support_decision'] = {'action': 'blocked_by_repeat_guard', 'reason': reason, 'task_id': s_task_id}
        return True

    # If support is also waiting, nothing to do
    if _primary_is_waiting(s_action):
        result['support_decision'] = {'action': s_action, 'task_id': s_task_id, 'note': 'support also waiting'}
        return True

    if execute and s_step.get('cmd'):
        timeout_s = STEP_TIMEOUTS.get(s_action)
        if s_loop.get('repeat_count') == 1:
            eta_min = max(1, int((timeout_s or 60) / 60))
            add_progress(s_task_id, f"[support] 开始步骤：{s_action}｜预计约 {eta_min} 分钟", stage=f"{s_action}-start", flush=True)

        update_task(s_task_id, status='进行中', next_action=f'[support] 执行中：{s_action}（timeout={timeout_s}s）')
        subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'task', s_task_id], capture_output=True, text=True)

        append_manifest(s_task_id, {
            'type': 'step_start', 'action': s_action,
            'owner': ACTION_OWNER.get(s_action, 'orchestrator'),
            'cmd': s_step.get('cmd'), 'timeout_s': timeout_s,
            'execution_slot': 'support',
        })

        s_step['result'] = run_step_cmd(s_task_id, s_action, s_step['cmd'], timeout_s=timeout_s)
        s_step['executed'] = True

        if s_step['result'].get('timeout'):
            reason = f"[support] 步骤 {s_action} 超时（>{timeout_s}s），已自动阻塞"
            update_task(s_task_id, status='已阻塞', next_action=f'排查 {s_action} 超时原因',
                        blocked_reason=reason, notes=append_note_once(support.get('notes', ''), 'support timeout blocked'))
            add_progress(s_task_id, reason, stage=f"{s_action}-timeout", flush=True)
            append_manifest(s_task_id, {'type': 'step_end', 'action': s_action, 'owner': ACTION_OWNER.get(s_action, 'orchestrator'),
                                         'status': 'timeout', 'elapsed_s': s_step['result'].get('elapsed_s'), 'execution_slot': 'support'})
        elif s_step['result']['code'] != 0:
            reason = trim_error(s_step['result'].get('stderr') or s_step['result'].get('stdout'))
            update_task(s_task_id, status='已阻塞', next_action=f'排查 {s_action} 失败',
                        blocked_reason=reason, notes=append_note_once(support.get('notes', ''), 'support command failed'))
            add_progress(s_task_id, f"[support] 步骤失败：{s_action}。原因：{reason}", stage=f"{s_action}-fail", flush=True)
            append_manifest(s_task_id, {'type': 'step_end', 'action': s_action, 'owner': ACTION_OWNER.get(s_action, 'orchestrator'),
                                         'status': 'failed', 'elapsed_s': s_step['result'].get('elapsed_s'), 'execution_slot': 'support'})
        else:
            add_progress(s_task_id, f"[support] 步骤完成：{s_action} ✅", stage=f"{s_action}-done", flush=True)
            append_manifest(s_task_id, {'type': 'step_end', 'action': s_action, 'owner': ACTION_OWNER.get(s_action, 'orchestrator'),
                                         'status': 'ok', 'elapsed_s': s_step['result'].get('elapsed_s'), 'execution_slot': 'support'})

    elif execute and s_action == 'complete':
        update_task(s_task_id, status='已完成', next_action='[support] 自驱执行闭环完成',
                    notes=append_note_once(support.get('notes', ''), 'support auto-completed'))
        subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'task', s_task_id], capture_output=True, text=True)
        subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'task_memory_sync.py'), s_task_id], capture_output=True, text=True)
        add_progress(s_task_id, '[support] 任务完成 ✅', stage='task-complete', flush=True)
        add_progress(s_task_id, summarize_task_result(s_task_id), stage='task-result', flush=True)
        append_manifest(s_task_id, {'type': 'task_end', 'status': 'completed', 'execution_slot': 'support'})
        s_step['executed'] = True

    result['support_decision'] = s_step
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--execute', action='store_true')
    args = ap.parse_args()

    with runtime_lock(LOCK_PATH, stale_seconds=LOCK_STALE_SECONDS) as lock:
        if not lock['locked']:
            result = {
                'generated_at': datetime.now().isoformat(timespec='seconds'),
                'decision': {'action': 'lock_skipped', 'reason': lock['reason'], 'lock_path': lock['path']}
            }
            write_last_run(result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        selection = ensure_selection()
        checklist = ensure_checklist()
        primary = selection.get('primary_task')
        support = selection.get('support_task')

        result = {
            'generated_at': datetime.now().isoformat(timespec='seconds'),
            'primary_task': primary,
            'support_task': support,
            'decision': None,
        }

        if not primary:
            result['decision'] = {'action': 'idle', 'reason': 'no primary task'}
            update_loop_state(None, 'idle')
            write_last_run(result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        # meta task gate
        if primary['task_id'] == 'TASK-20260317-035':
            if checklist_ready(checklist):
                promote = maybe_promote_test_case(selection, args.execute)
                result['decision'] = promote or {'action': 'meta-ready', 'reason': 'P3-1~P3-4 已就位，可转测试验收'}
            else:
                result['decision'] = {
                    'action': 'meta-progress',
                    'reason': 'P3 主链仍在建设中；测试用例先不自动推进',
                    'checklist': checklist['steps'],
                }
            update_loop_state(primary['task_id'], result['decision'].get('action'))
            write_last_run(result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        # status gates
        status = primary.get('status')

        if status == '已阻塞':
            loop_state = update_loop_state(primary['task_id'], 'blocked')
            repeat = loop_state.get('repeat_count', 0)
            # 首次 blocked 或每 20 次，发飞书通知
            NOTIFY_INTERVALS = {1, 50}
            if repeat in NOTIFY_INTERVALS:
                try:
                    import subprocess as _sp
                    _msg = (
                        f'⚠️ 任务持续阻塞\n'
                        f'任务：{primary.get("title", primary["task_id"])}\n'
                        f'原因：{primary.get("blocked_reason") or "review-gate blocked"}\n'
                        f'已重复：{repeat} 次\n'
                        f'需要人工干预：{primary.get("next_action", "")}'
                    )
                    # 2026-04-13: WorkBuddy 版 — 用龙少微信替代 openclaw message send
                    try:
                        from longshao_notify import send_message as _send_wx
                        _send_wx(_msg)
                    except Exception:
                        pass
                except Exception:
                    pass
            # 超过 50 次不再重复计入，避免无意义刷新
            if repeat > 50:
                result['decision'] = {'action': 'blocked', 'reason': f'task blocked (repeat={repeat}); waiting for human fix - notification sent at milestones'}
                write_last_run(result)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return
            result['decision'] = {'action': 'blocked', 'reason': 'task blocked; waiting for human fix'}
            # --- DUAL-TASK: primary blocked, try support ---
            if support and support.get('task_type') == '专题研究类':
                _try_advance_support(support, args.execute, result)
            write_last_run(result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        # 不再等待人工确认；若历史上有待确认任务，自动恢复继续执行
        if status == '待确认' and args.execute:
            update_task(primary['task_id'], status='进行中', next_action='自动恢复执行（已取消确认闸门）', notes=append_note_once(primary.get('notes', ''), 'auto-resume-from-await-confirm'))
            add_progress(primary['task_id'], '收到：取消确认闸门。任务自动继续执行。', stage='auto-resume', flush=True)

        # research workflow
        if primary['task_type'] == '专题研究类':
            step = research_step_from_task(primary['task_id'], primary['task_type'])
            loop_state = update_loop_state(primary['task_id'], step.get('action'))
            action = step.get('action') or ''

            # loop guard (no progress) — waiting for subagent results should not trip the fuse
            if loop_state.get('repeat_count', 0) >= MAX_REPEAT_DECISIONS and action != 'complete' and not action.startswith('await_'):
                reason = f"execution-loop 重复 {loop_state['repeat_count']} 次停在 {action}，已自动熔断待人工复核"
                if args.execute:
                    update_task(primary['task_id'], status='已阻塞', next_action='人工复核该步骤为什么未产出预期 artifact', blocked_reason=reason, notes=append_note_once(primary.get('notes', ''), 'execution-loop repeat-guard blocked'))
                result['decision'] = {'action': 'blocked_by_repeat_guard', 'reason': reason, 'repeat_count': loop_state['repeat_count'], 'artifact': step.get('artifact')}
                write_last_run(result)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return

            # ── 新增门禁 gate 处理 ──
            if args.execute and action == 'gate_step1_block':
                gate = step.get('gate', {})
                reason = step.get('reason', f"Step 1 数据包完整性门禁未通过：{gate.get('reason', '')}")
                update_task(primary['task_id'], status='已阻塞',
                            next_action='补搜关键数据或手动补充数据包后删除 step1-verify.json 重跑',
                            blocked_reason=reason,
                            notes=append_note_once(primary.get('notes', ''), f"step1-verify BLOCK: critical={gate.get('critical_coverage', 0)}, overall={gate.get('score', 0)}"))
                add_progress(primary['task_id'], f"🚫 数据包门禁 BLOCK：{reason}", stage='step1-verify-block', flush=True)
                append_manifest(primary['task_id'], {
                    'type': 'gate_block', 'action': 'gate_step1_block', 'owner': 'reviewer',
                    'status': 'blocked', 'reason': reason,
                    'critical_coverage': gate.get('critical_coverage'),
                    'overall_score': gate.get('score'),
                    'not_filled_markers': gate.get('not_filled_markers'),
                })
                step['executed'] = True
                step['status_update'] = '已阻塞'
                step['blocked_reason'] = reason
            elif args.execute and action == 'gate_consistency_fail':
                gate = step.get('gate', {})
                reason = step.get('reason', f"跨章节数据一致性检查失败：{gate.get('reason', '')}")
                update_task(primary['task_id'], status='已阻塞',
                            next_action='修正不一致数据后删除 consistency-check.json 重跑',
                            blocked_reason=reason,
                            notes=append_note_once(primary.get('notes', ''), f"consistency-check FAIL: errors={gate.get('error_count', 0)}, warnings={gate.get('warning_count', 0)}"))
                add_progress(primary['task_id'], f"🚫 一致性门禁 FAIL：{reason}", stage='consistency-check-fail', flush=True)
                append_manifest(primary['task_id'], {
                    'type': 'gate_block', 'action': 'gate_consistency_fail', 'owner': 'reviewer',
                    'status': 'blocked', 'reason': reason,
                    'error_count': gate.get('error_count'),
                    'warning_count': gate.get('warning_count'),
                })
                step['executed'] = True
                step['status_update'] = '已阻塞'
                step['blocked_reason'] = reason
            elif args.execute and action == 'gate_no_clean_evidence':
                gate = step.get('gate', {})
                reason = f"review gate 未通过：clean evidence kept_count={gate.get('kept_count', 0)}，禁止继续进入 analysis/memo"
                update_task(primary['task_id'], status='已阻塞', next_action='提升 query 对题性 / 来源质量 / clean evidence kept_count 后再继续', blocked_reason=reason, notes=append_note_once(primary.get('notes', ''), 'review-gate blocked: no clean evidence'))
                add_progress(primary['task_id'], reason, stage='review-gate-block', flush=True)
                append_manifest(primary['task_id'], {'type': 'gate_block', 'action': 'gate_no_clean_evidence', 'owner': 'reviewer', 'status': 'blocked', 'reason': reason})
                step['executed'] = True
                step['status_update'] = '已阻塞'
                step['blocked_reason'] = reason
            elif args.execute and action.startswith('fail_'):
                hook_result = step.get('result', {}) or {}
                blocking = hook_result.get('blocking_issues') or []
                summary = hook_result.get('summary') or 'subagent review 未通过'
                reason = summary if not blocking else f"{summary}｜{'; '.join(blocking[:3])}"
                update_task(primary['task_id'], status='已阻塞', next_action=f'处理 {step.get("hook")} 未通过的问题后再继续', blocked_reason=reason, notes=append_note_once(primary.get('notes', ''), f'{step.get("hook")} blocked'))
                add_progress(primary['task_id'], f"Subagent gate 未通过：{step.get('hook')}。原因：{reason}", stage=f"{action}-block", flush=True)
                append_manifest(primary['task_id'], {'type': 'gate_block', 'action': action, 'owner': ACTION_OWNER.get(action, 'reviewer'), 'status': 'blocked', 'reason': reason, 'hook': step.get('hook')})
                step['executed'] = True
                step['status_update'] = '已阻塞'
                step['blocked_reason'] = reason
            elif args.execute and action.startswith('dispatch_') and not step.get('cmd'):
                hook = step.get('hook') or action
                next_action = f'需要真实派发 subagent：{hook}（brief={step.get("brief")}; spawn_receipt={step.get("artifact")})'
                update_task(primary['task_id'], status='进行中', next_action=next_action, notes=append_note_once(primary.get('notes', ''), f'dispatch required: {hook}'))
                if loop_state.get('repeat_count') == 1:
                    add_progress(primary['task_id'], f'检测到 subagent hook 已建但尚未真实派发：{hook}。必须先 sessions_spawn，再继续主链。', stage=f'{action}-dispatch', flush=True)
                    append_manifest(primary['task_id'], {'type': 'subagent_dispatch_required', 'action': action, 'owner': 'orchestrator', 'hook': hook, 'brief': step.get('brief'), 'spawn_receipt': step.get('artifact')})
                step['executed'] = True
                step['status_update'] = '等待subagent派发'
            elif args.execute and action.startswith('await_'):
                waiting_for = step.get('hook') or action
                next_action = f'等待 subagent 结果：{waiting_for} -> {step.get("artifact")}'
                update_task(primary['task_id'], status='进行中', next_action=next_action, notes=append_note_once(primary.get('notes', ''), f'awaiting {waiting_for}'))
                if loop_state.get('repeat_count') == 1:
                    add_progress(primary['task_id'], f'已进入 subagent gate：{waiting_for}。已看到真实 spawn receipt，等待结果文件后继续主链。', stage=f'{action}-wait', flush=True)
                    append_manifest(primary['task_id'], {'type': 'subagent_wait', 'action': action, 'owner': 'orchestrator', 'hook': waiting_for, 'artifact': step.get('artifact'), 'spawn_receipt': (step.get('spawn_receipt') or {}).get('childSessionKey')})
                step['executed'] = True
                step['status_update'] = '等待subagent结果'
            elif args.execute and step.get('cmd'):
                timeout_s = STEP_TIMEOUTS.get(action)

                # tell Xavier step progress with ETA (only first time per step action)
                if loop_state.get('repeat_count') == 1:
                    eta_min = max(1, int((timeout_s or 60) / 60))
                    add_progress(primary['task_id'], f"开始步骤：{action}｜预计约 {eta_min} 分钟", stage=f"{action}-start", flush=True)

                update_task(primary['task_id'], status='进行中', next_action=f'执行中：{action}（timeout={timeout_s}s）')
                subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'task', primary['task_id']], capture_output=True, text=True)
                subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'todos'], capture_output=True, text=True)

                append_manifest(primary['task_id'], {
                    'type': 'step_start',
                    'action': action,
                    'owner': ACTION_OWNER.get(action, 'orchestrator'),
                    'cmd': step.get('cmd'),
                    'timeout_s': timeout_s,
                })

                step['result'] = run_step_cmd(primary['task_id'], action, step['cmd'], timeout_s=timeout_s)
                step['executed'] = True

                if step['result'].get('timeout'):
                    reason = f"步骤 {action} 超时（>{timeout_s}s），已自动阻塞"
                    update_task(primary['task_id'], status='已阻塞', next_action=f'排查 {action} 超时原因（网络/抓取/解析）', blocked_reason=reason, notes=append_note_once(primary.get('notes', ''), 'execution-loop timeout blocked'))
                    subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'task', primary['task_id']], capture_output=True, text=True)
                    subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'todos'], capture_output=True, text=True)
                    add_progress(primary['task_id'], f"{reason}。我已停止等待，避免你以为卡死。", stage=f"{action}-timeout", flush=True)
                    step['status_update'] = '已阻塞'
                    step['blocked_reason'] = reason
                    append_manifest(primary['task_id'], {'type': 'step_end', 'action': action, 'owner': ACTION_OWNER.get(action, 'orchestrator'), 'status': 'timeout', 'elapsed_s': step['result'].get('elapsed_s'), 'reason': reason})
                elif step['result']['code'] != 0:
                    reason = trim_error(step['result'].get('stderr') or step['result'].get('stdout'))
                    update_task(primary['task_id'], status='已阻塞', next_action=f'排查 {action} 为什么失败', blocked_reason=reason, notes=append_note_once(primary.get('notes', ''), 'execution-loop command failed'))
                    subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'task', primary['task_id']], capture_output=True, text=True)
                    subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'todos'], capture_output=True, text=True)
                    add_progress(primary['task_id'], f"步骤失败：{action}。已自动阻塞，原因：{reason}", stage=f"{action}-fail", flush=True)
                    step['status_update'] = '已阻塞'
                    step['blocked_reason'] = reason
                    append_manifest(primary['task_id'], {'type': 'step_end', 'action': action, 'owner': ACTION_OWNER.get(action, 'orchestrator'), 'status': 'failed', 'elapsed_s': step['result'].get('elapsed_s'), 'reason': reason})
                else:
                    add_progress(primary['task_id'], f"步骤完成：{action} ✅", stage=f"{action}-done", flush=True)
                    append_manifest(primary['task_id'], {'type': 'step_end', 'action': action, 'owner': ACTION_OWNER.get(action, 'orchestrator'), 'status': 'ok', 'elapsed_s': step['result'].get('elapsed_s'), 'artifact': step.get('artifact')})

            elif args.execute and action == 'complete':
                update_task(primary['task_id'], status='已完成', next_action='自驱执行闭环完成', notes=append_note_once(primary.get('notes', ''), 'execution-loop auto-completed'))
                subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'task', primary['task_id']], capture_output=True, text=True)
                subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'todos'], capture_output=True, text=True)
                subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'task_memory_sync.py'), primary['task_id']], capture_output=True, text=True)
                add_progress(primary['task_id'], '任务完成：自驱执行闭环完成 ✅', stage='task-complete', flush=True)
                add_progress(primary['task_id'], summarize_task_result(primary['task_id']), stage='task-result', flush=True)
                append_manifest(primary['task_id'], {'type': 'task_end', 'status': 'completed'})
                step['executed'] = True
                step['status_update'] = '已完成'

            result['decision'] = step


            # --- DUAL-TASK: if primary is waiting, try advancing support_task ---
            primary_action = step.get('action') or ''
            if _primary_is_waiting(primary_action) and support and support.get('task_type') == '专题研究类':
                _try_advance_support(support, args.execute, result)

            write_last_run(result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        # planning workflow
        if primary['task_type'] == '资料整理类':
            if is_manual_managed_task(primary):
                result['decision'] = {'action': 'manual_managed', 'reason': 'manual implementation task; do not auto-close via planning loop'}
                update_loop_state(primary['task_id'], 'manual_managed')
                write_last_run(result)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return

            step = planning_step_from_task(primary)
            loop_state = update_loop_state(primary['task_id'], step.get('action'))

            if loop_state.get('repeat_count', 0) >= MAX_REPEAT_DECISIONS and step.get('action') not in ('complete',):
                reason = f"planning state machine 重复 {loop_state['repeat_count']} 次停在 {step.get('action')}，已自动熔断"
                if args.execute:
                    update_task(primary['task_id'], status='已阻塞', next_action='人工检查 planning state machine 为什么未推进', blocked_reason=reason, notes=append_note_once(primary.get('notes', ''), 'planning repeat-guard blocked'))
                result['decision'] = {'action': 'blocked_by_repeat_guard', 'reason': reason, 'repeat_count': loop_state['repeat_count'], 'artifact': step.get('artifact')}
                write_last_run(result)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return

            if args.execute and step.get('action') == 'complete':
                update_task(primary['task_id'], status='已完成', next_action='planning loop closed automatically', notes=append_note_once(primary.get('notes', ''), 'planning-state auto-completed'))
                subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'task', primary['task_id']], capture_output=True, text=True)
                subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'todos'], capture_output=True, text=True)
                add_progress(primary['task_id'], '任务完成：planning loop 已自动收口 ✅', stage='task-complete', flush=True)
                add_progress(primary['task_id'], f"闭环结果：planning 任务收口完成；当前 next_action={primary.get('next_action') or 'n/a'}。", stage='task-result', flush=True)
                step['executed'] = True
                step['status_update'] = '已完成'
            elif args.execute and step.get('action') != 'complete':
                action = step.get('action')
                timeout_s = STEP_TIMEOUTS.get(action)
                if loop_state.get('repeat_count') == 1:
                    eta_min = max(1, int((timeout_s or 60) / 60))
                    add_progress(primary['task_id'], f"开始步骤：{action}｜预计约 {eta_min} 分钟", stage=f"{action}-start", flush=True)

                if step.get('cmd'):
                    update_task(primary['task_id'], status='进行中', next_action=f'执行中：{action}（timeout={timeout_s}s）', notes=append_note_once(primary.get('notes', ''), 'execution-loop planning step'))
                    subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'task', primary['task_id']], capture_output=True, text=True)
                    subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'todos'], capture_output=True, text=True)
                    step['result'] = run_step_cmd(primary['task_id'], action, step['cmd'], timeout_s=timeout_s)
                    step['executed'] = True

                    if step['result'].get('timeout'):
                        reason = f"步骤 {action} 超时（>{timeout_s}s），已自动阻塞"
                        update_task(primary['task_id'], status='已阻塞', next_action=f'排查 {action} 超时原因（网络/抓取/解析）', blocked_reason=reason, notes=append_note_once(primary.get('notes', ''), 'execution-loop timeout blocked'))
                        subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'task', primary['task_id']], capture_output=True, text=True)
                        subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'todos'], capture_output=True, text=True)
                        add_progress(primary['task_id'], f"{reason}。我已停止等待，避免你以为卡死。", stage=f"{action}-timeout", flush=True)
                        step['status_update'] = '已阻塞'
                        step['blocked_reason'] = reason
                    elif step['result']['code'] != 0:
                        reason = trim_error(step['result'].get('stderr') or step['result'].get('stdout'))
                        update_task(primary['task_id'], status='已阻塞', next_action=f'排查 {action} 为什么失败', blocked_reason=reason, notes=append_note_once(primary.get('notes', ''), 'execution-loop command failed'))
                        subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'task', primary['task_id']], capture_output=True, text=True)
                        subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'todos'], capture_output=True, text=True)
                        add_progress(primary['task_id'], f"步骤失败：{action}。已自动阻塞，原因：{reason}", stage=f"{action}-fail", flush=True)
                        step['status_update'] = '已阻塞'
                        step['blocked_reason'] = reason
                    else:
                        add_progress(primary['task_id'], f"步骤完成：{action} ✅", stage=f"{action}-done", flush=True)
                        step['status_update'] = '进行中'

                else:
                    update_task(primary['task_id'], status='进行中', next_action='继续按 planning state machine 推进', notes=append_note_once(primary.get('notes', ''), 'execution-loop planning step'))
                    subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'task', primary['task_id']], capture_output=True, text=True)
                    subprocess.run(['/usr/bin/env python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'todos'], capture_output=True, text=True)
                    step['executed'] = True
                    step['status_update'] = '进行中'
            else:
                step['executed'] = bool(args.execute)

            result['decision'] = step
            write_last_run(result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        result['decision'] = {'action': 'unsupported', 'reason': 'task type not yet supported'}
        update_loop_state(primary['task_id'], 'unsupported')
        write_last_run(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
