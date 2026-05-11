#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'
TASKS_DIR.mkdir(parents=True, exist_ok=True)

ROLE_PACKS = {
    '专题研究类': [
        '投研_主管',
        '投研_主笔_数据收集',
        '投研_主笔_行业分析',
        '投研_主笔_商业模式',
        '投研_主笔_财务分析',
        '投研_主笔_预测与估值',
        '投研_主笔_管理层',
        '投研_主笔_差异化洞察',
        '投研_主笔_风险催化',
        '投研_主笔_移交说明',
        '投研_模板_卖方券商风格',
        '投研_文档汇总',
    ],
    '晨报类': [
        '投研_主管',
        '投研_主笔_数据收集',
        '投研_主笔_行业分析',
        '投研_主笔_风险催化',
        '投研_文档汇总',
    ],
    '快报类': [
        '投研_主管',
        '投研_主笔_数据收集',
        '投研_主笔_风险催化',
        '投研_文档汇总',
    ],
    '资料整理类': [
        '投研_主管',
        '投研_主笔_数据收集',
        '投研_文档汇总',
    ],
    '回顾类': [
        '投研_主管',
        '投研_主笔_移交说明',
        '投研_模板_卖方券商风格',
        '投研_文档汇总',
    ],
}

WORKFLOW_STEPS = {
    '晨报类': [
        '搜索采集 Agent 拉取过去 24 小时公开信息',
        '信息清洗 / 摘要 Agent 做中文化、去重与结构整理',
        '研究分析 Agent 补充市场驱动因素 / 今日关注',
        '文档生成 Agent 产出正式文档并通过质量闸门',
        '主控 Agent 校验发送对象并决定发送 / 阻塞',
    ],
    '专题研究类': [
        '主控 Agent 明确研究范围、研究目的、输出形态',
        '数据收集角色先拉资料并补来源',
        '行业 / 商业模式 / 财务 / 预测估值 / 管理层 / 差异化 / 风险角色分别形成模块结论',
        '主控 Agent 审核后交给文档汇总角色统稿，并按卖方券商模板做格式与口径校正',
        '记忆与任务追踪链记录待跟踪问题、未解项和下一步',
    ],
    '快报类': [
        '搜索采集 Agent 抢第一轮信息',
        '摘要 Agent 压成短稿',
        '研究分析 Agent 回答发生了什么、为什么重要、可能影响什么',
        '文档生成 Agent 输出一页快报',
        '主控 Agent 决定直接发送还是待确认',
    ],
    '资料整理类': [
        '主控 Agent 定义资料范围和输出形式',
        '数据收集 Agent 聚合原始材料',
        '文档汇总角色输出可继续编辑的整理稿',
    ],
    '回顾类': [
        '记忆与任务追踪链汇总日志 / 待办 / 输出',
        '主控 Agent 提炼关键变化与未完成项',
        '文档汇总角色生成 review 草稿',
    ],
}


ROLE_STAGE_MAP = {
    '专题研究类': {
        'orchestrator': ['接任务', '拆任务', '状态流转', '汇总汇报'],
        'builder_search': ['search plan', 'packet', 'packet-filled', 'evidence'],
        'reviewer': ['reviewer', 'evidence-clean'],
        'builder_analysis': ['analysis-draft', 'final-memo'],
        'writer': ['final-memo-instruction-guided', 'bundle'],
    }
}

SUBAGENT_HOOKS = {
    '专题研究类': [
        {
            'hook': 'search-plan-review',
            'when': 'generate_search_plan 之后、render_packet 之前',
            'owner': 'builder_search',
            'output': 'search-plan-review.json',
            'purpose': '检查 query pack 是否对题，必要时直接修订 search plan 原文件。',
        },
        {
            'hook': 'clean-evidence-review',
            'when': 'filter_evidence 之后、build_analysis 之前',
            'owner': 'reviewer',
            'output': 'clean-evidence-review.json',
            'purpose': '决定 clean evidence 是否足以支持进入 analysis；不足就拦截。',
        },
        {
            'hook': 'analysis-writer-polish',
            'when': 'build_analysis 之后、build_memo 之前',
            'owner': 'writer',
            'output': 'analysis-polished.md + analysis-writer-polish.json',
            'purpose': '把 analysis draft 收口成更适合 final memo 消费的 polished analysis。',
        },
    ]
}

RECALL_POLICY = [
    '研究任务创建前先 recall 相关长期记忆',
    'analysis/memo 前若 recall 与 clean evidence 都弱，应显式标记上下文不足',
    '任务完成后区分 HOT/WARM/COLD 写回',
]

HANDOFF_PROTOCOL = [
    '做了什么',
    '产物在哪',
    '怎么验',
    '已知问题',
    '下一步交给谁',
]

REVIEW_GATES = [
    'packet-filled -> evidence -> reviewer -> evidence-clean -> analysis -> memo -> instruction-guided memo',
    '若 evidence-clean 没有可用证据，不允许进入 analysis/memo',
    'instruction-guided memo 不能替代 evidence 质量，只负责结构与口径收口',
]

FIRST_STEP_HINT = {
    '晨报类': '先检查收件人、时间窗口和当天数据源可用性。',
    '专题研究类': '先把研究对象、研究目标、重点关注方向写清楚，再拉第一轮资料。',
    '快报类': '先确认事件是否值得发快报，并收集第一轮信息来源。',
    '资料整理类': '先明确资料范围、输出格式和最终用途。',
    '回顾类': '先汇总周期内日志、待办、输出与关键变化。',
}


def sh(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return p.stdout.strip()


def list_tasks() -> list[dict]:
    return json.loads(sh(['python3', str(ROOT/'scripts'/'task_ledger.py'), 'list']))


def get_task(task_id: str) -> dict:
    return next(t for t in list_tasks() if t['task_id'] == task_id)


def update_task(task_id: str, **kwargs) -> dict:
    cmd = ['python3', str(ROOT/'scripts'/'task_ledger.py'), 'update', task_id]
    mapping = {
        'status': '--status',
        'owner': '--owner',
        'recipient': '--recipient',
        'next_action': '--next-action',
        'blocked_reason': '--blocked-reason',
        'output_path': '--output-path',
        'notes': '--notes',
    }
    for key, flag in mapping.items():
        value = kwargs.get(key)
        if value is not None:
            cmd.extend([flag, str(value)])
    sh(cmd)
    return get_task(task_id)


def create_task(title: str, task_type: str, recipient: str, next_action: str, notes: str) -> dict:
    out = sh([
        'python3', str(ROOT/'scripts'/'task_ledger.py'), 'create', title,
        '--task-type', task_type,
        '--status', '待开始',
        '--owner', '主控 Agent',
        '--recipient', recipient,
        '--next-action', next_action,
        '--notes', notes,
    ])
    return json.loads(out)


def load_by_key(key: str) -> dict:
    return json.loads(sh(['python3', str(ROOT/'scripts'/'load_ir_instruction.py'), '--key', key, '--full']))['selected'][0]


def select_instructions(query: str, explicit_key: str | None, top_k: int, task_type: str) -> list[dict]:
    selected: list[dict] = []
    if explicit_key:
        selected.append(load_by_key(explicit_key))
    else:
        out = sh(['python3', str(ROOT/'scripts'/'load_ir_instruction.py'), query, '--top-k', str(top_k), '--full'])
        selected.extend(json.loads(out).get('selected', []))

    keys = {item.get('key') for item in selected}
    for key in ROLE_PACKS.get(task_type, ['投研_主管']):
        if key not in keys:
            selected.append(load_by_key(key))
            keys.add(key)
    return selected




def model_route(task_type: str) -> dict:
    return json.loads(sh(['python3', str(ROOT/'scripts'/'route_ir_model.py'), '--task-type', task_type, '--stage', 'controller']))



def fetch_memory_context(query: str, top_k: int = 5) -> dict:
    cmd = ['bash', str(ROOT/'scripts'/'memory-cmd.sh'), 'search', query, '--top-k', str(top_k)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return {'ok': False, 'results': [], 'error': (p.stderr or p.stdout).strip()[:300]}
    try:
        results = json.loads(p.stdout)
    except Exception:
        return {'ok': False, 'results': [], 'error': 'memory search parse failed'}
    return {'ok': True, 'results': results}


def fetch_memory_runtime_context() -> dict:
    cmd = ['bash', str(ROOT/'scripts'/'memory-cmd.sh'), 'context']
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return {'active_context': '', 'todos': '', 'ok': False}
    try:
        data = json.loads(p.stdout)
        data['ok'] = True
        return data
    except Exception:
        return {'active_context': '', 'todos': '', 'ok': False}

def build_execution_plan(task_type: str, instruction_keys: list[str], query: str) -> dict:
    steps = WORKFLOW_STEPS.get(task_type, ['主控 Agent 拆任务并推进执行'])
    return {
        'task_type': task_type,
        'query': query,
        'instruction_keys': instruction_keys,
        'workflow_steps': steps,
        'first_step_hint': FIRST_STEP_HINT.get(task_type, '先明确任务目标与输出要求。'),
        'primary_owner': '主控 Agent',
        'status_flow': ['待开始', '进行中', '待汇总', '待确认', '已完成', '已阻塞'],
        'orchestration_states': ['Inbox', 'Assigned', 'In Progress', 'Review', 'Done', 'Failed'],
        'role_stage_map': ROLE_STAGE_MAP.get(task_type, {}),
        'handoff_protocol': HANDOFF_PROTOCOL,
        'review_gates': REVIEW_GATES if task_type == '专题研究类' else [],
        'subagent_hooks': SUBAGENT_HOOKS.get(task_type, []),
        'recall_policy': RECALL_POLICY,
    }


def write_execution_brief(task: dict, query: str, selected: list[dict], plan: dict, memory_context: dict | None = None, runtime_memory: dict | None = None) -> Path:
    brief_path = TASKS_DIR / f"{task['task_id']}-brief.md"
    lines = [
        f"# 执行简报 - {task['task_id']}",
        '',
        f"- 任务标题：{task['title']}",
        f"- 任务类型：{task['task_type']}",
        f"- 接收对象：{task['recipient']}",
        f"- 当前状态：{task['status']}",
        f"- 用户问题：{query}",
        '',
        '## 已注入角色 / 指令',
    ]
    for item in selected:
        lines.append(f"- {item.get('key')}｜{item.get('name')}｜{item.get('description', '')}")
    route = model_route(task['task_type'])
    lines += ['', '## 模型路由', f"- 主控优先模型：{route['preferred_model']}", f"- fallback 模型：{route['fallback_model']}", f"- fallback 前是否要先告知 Xavier：{route['fallback_notice_required']}", '', '## 标准执行步骤']
    for i, step in enumerate(plan['workflow_steps'], 1):
        lines.append(f"{i}. {step}")
    if plan.get('role_stage_map'):
        lines += ['', '## 执行角色映射']
        for role, outputs in plan['role_stage_map'].items():
            lines.append(f"- {role}: {', '.join(outputs)}")
    if plan.get('handoff_protocol'):
        lines += ['', '## Handoff 协议']
        for item in plan['handoff_protocol']:
            lines.append(f"- {item}")
    if plan.get('review_gates'):
        lines += ['', '## Review Gates']
        for item in plan['review_gates']:
            lines.append(f"- {item}")
    if plan.get('subagent_hooks'):
        lines += ['', '## Subagent Hooks（GPT-5.4）']
        for item in plan['subagent_hooks']:
            lines.append(f"- {item.get('hook')}｜时点：{item.get('when')}｜角色：{item.get('owner')}｜产物：{item.get('output')}")
            lines.append(f"  - 目的：{item.get('purpose')}")
    mem = memory_context or {}
    runtime_mem = runtime_memory or {}
    if mem.get('ok') and mem.get('results'):
        lines += ['', '## 相关长期记忆（自动检索）']
        for item in mem.get('results', [])[:5]:
            lines.append(f"- [{item.get('category')}] {item.get('content')} (score={item.get('score')})")
    else:
        lines += ['', '## 相关长期记忆（自动检索）', '- 未命中高相关长期记忆，后续分析需更多依赖 clean evidence。']
    if runtime_mem.get('active_context'):
        lines += ['', '## 当前活跃上下文（memory_system）', runtime_mem.get('active_context')]
    if runtime_mem.get('todos'):
        lines += ['', '## 当前待办（memory_system）', runtime_mem.get('todos')]

    if plan.get('recall_policy'):
        lines += ['', '## Recall Policy']
        for item in plan['recall_policy']:
            lines.append(f'- {item}')

    lines += [
        '',
        '## 首轮动作',
        f"- {plan['first_step_hint']}",
        '',
        '## 主控当前下一步',
        f"- {task['next_action']}",
        '',
        '## 备注',
        '- 这是执行入口自动生成的首轮上下文草稿，用于让主控立即开工，而不是只停在建账。',
    ]
    brief_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return brief_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('title')
    ap.add_argument('--query', default='')
    ap.add_argument('--task-type', default='专题研究类')
    ap.add_argument('--recipient', default='xavier')
    ap.add_argument('--instruction-key')
    ap.add_argument('--top-k', type=int, default=3)
    ap.add_argument('--auto-start', action='store_true')
    args = ap.parse_args()

    query = args.query or args.title
    selected = select_instructions(query, args.instruction_key, args.top_k, args.task_type)
    instruction_keys = [item.get('key') for item in selected if item.get('key')]
    memory_context = fetch_memory_context(query, top_k=5)
    runtime_memory = fetch_memory_runtime_context()

    task = create_task(
        title=args.title,
        task_type=args.task_type,
        recipient=args.recipient,
        next_action='读取任务包中的 instructions 并开始执行' if args.auto_start else '人工确认后开始执行',
        notes=f'query={query}; instruction_keys={instruction_keys}'
    )

    plan = build_execution_plan(args.task_type, instruction_keys, query)
    route = model_route(args.task_type)
    package = {
        'task': task,
        'query': query,
        'instruction_keys': instruction_keys,
        'instructions': selected,
        'memory_context': memory_context,
        'runtime_memory': runtime_memory,
        'execution_plan': plan,
        'model_route': route,
        'created_at': datetime.now().isoformat(timespec='seconds')
    }
    package_path = TASKS_DIR / f"{task['task_id']}.json"
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    next_action = f"按 execution brief 执行第1步：{plan['workflow_steps'][0]}"
    task = update_task(
        task['task_id'],
        status='进行中' if args.auto_start else None,
        output_path=str(package_path),
        next_action=next_action,
    )

    brief_path = write_execution_brief(task, query, selected, plan, memory_context, runtime_memory)
    subprocess.run(['python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'task', task['task_id']], capture_output=True, text=True)
    subprocess.run(['python3', str(ROOT/'scripts'/'memory_worklog_sync.py'), 'todos'], capture_output=True, text=True)

    runner_output = None
    if args.auto_start:
        runner_raw = sh(['python3', str(ROOT/'scripts'/'run_ir_runner.py'), task['task_id']])
        runner_output = json.loads(runner_raw)['runner_output']
        task = update_task(
            task['task_id'],
            output_path=f"{package_path}; {brief_path}; {runner_output}",
            next_action='查看 runner 输出，决定是否直接进入数据收集/搜索阶段',
        )
    else:
        task = update_task(task['task_id'], output_path=f"{package_path}; {brief_path}")

    print(json.dumps({
        'task': task,
        'package_path': str(package_path),
        'brief_path': str(brief_path),
        'runner_output': runner_output,
        'instruction_keys': instruction_keys,
        'execution_plan': plan,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
