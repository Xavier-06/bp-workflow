#!/usr/bin/env python3
"""
BP Phase 2 Subagent Launcher — WorkBuddy 版本 v4

无需外部 LLM API。发射器负责构建 brief、写入 manifest 和 spawn receipt，
实际的 LLM 推理由 WorkBuddy 主 AI 通过 Task 子代理完成。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'tasks'
INSTRUCTION_STORE = ROOT / 'instruction_store_bp'

ROLE_TO_KEY = {
    'bp_团队与合规': 'team',
    'bp_技术与产品': 'tech',
    'bp_行业与供应链': 'industry',
    'bp_竞争与结论': 'competition',
}

ROLE_SYSTEM_PROMPTS = {
    'bp_团队与合规': (
        'You are a senior investment research analyst at a top-tier VC firm, writing a professional '
        'research report chapter on team, governance, and compliance. '
        'You have FULL read/write access to the workspace and can use these tools: '
        '(1) 企查查 MCP: mcp__qcc-company (工商), mcp__qcc-risk (风险/诉讼), mcp__qcc-ipr (知产), mcp__qcc-operation (经营); '
        '(2) web_search for general search; (3) web_fetch for deep page scraping; '
        '(4) neodata-financial-search for financial data. '
        'Your detailed role instructions, writing standards, chapter structure, and investigation scope '
        'are provided in the brief. Follow them precisely. '
        'Complete your analysis autonomously. Do not fabricate information. '
        'Do not use internal terms: 子代理, dispatch, Phase, handoff, Step, manifest, spawn. '
        'CRITICAL: Limit 企查查 MCP calls to at most 10 per role. Prioritize web_search/web_fetch for general info. '
        'Only use 企查查 for specific company verification (工商信息, 诉讼, 知识产权). '
        'If you find yourself calling 企查查 repeatedly with similar queries, STOP and write your analysis with existing data.'
    ),
    'bp_技术与产品': (
        'You are a senior investment research analyst at a top-tier VC firm, writing a professional '
        'research report chapter on technology deep-dive, product analysis, and R&D capability. '
        'You have FULL read/write access to the workspace and can use these tools: '
        '(1) 企查查 MCP: mcp__qcc-ipr (专利/商标/著作权), mcp__qcc-company (工商); '
        '(2) web_search for general search; (3) web_fetch for deep page scraping; '
        '(4) neodata-financial-search for financial data. '
        'Your detailed role instructions, writing standards, chapter structure, and investigation scope '
        'are provided in the brief. Follow them precisely. '
        'Complete your analysis autonomously. Do not fabricate information. '
        'Do not use internal terms: 子代理, dispatch, Phase, handoff, Step, manifest, spawn. '
        'CRITICAL: Limit 企查查 MCP calls to at most 10 per role. Prioritize web_search/web_fetch for general tech info. '
        'Only use 企查查 for patent/trademark verification. '
        'If you find yourself calling 企查查 repeatedly with similar queries, STOP and write your analysis with existing data.'
    ),
    'bp_行业与供应链': (
        'You are a senior investment research analyst at a top-tier VC firm, writing a professional '
        'research report chapter on market sizing, industry landscape, and supply chain analysis. '
        'You have FULL read/write access to the workspace and can use these tools: '
        '(1) 企查查 MCP: mcp__qcc-operation (招投标/资质/年报), mcp__qcc-company (股东/投资/分支); '
        '(2) web_search for general search; (3) web_fetch for deep page scraping; '
        '(4) neodata-financial-search for financial data. '
        'Your detailed role instructions, writing standards, chapter structure, and investigation scope '
        'are provided in the brief. Follow them precisely. '
        'Complete your analysis autonomously. Do not fabricate information. '
        'Do not use internal terms: 子代理, dispatch, Phase, handoff, Step, manifest, spawn. '
        'CRITICAL: Limit 企查查 MCP calls to at most 10 per role. Prioritize web_search/web_fetch for market data. '
        'Only use 企查查 for specific company verification (股东, 投资, 资质). '
        'If you find yourself calling 企查查 repeatedly with similar queries, STOP and write your analysis with existing data.'
    ),
    'bp_竞争与结论': (
        'You are a senior investment research analyst at a top-tier VC firm, writing the final chapter '
        'of a professional research report: competitive analysis, BP logic verification, risk assessment, '
        'and investment conclusion with actionable recommendations. '
        'You have FULL read/write access to the workspace and can use these tools: '
        '(1) 企查查 MCP: mcp__qcc-company (竞品工商/融资), mcp__qcc-operation (竞品招投标/资质); '
        '(2) web_search for general search; (3) web_fetch for deep page scraping; '
        '(4) neodata-financial-search for listed competitor financials. '
        'You have access to the prior three dimension outputs (team, tech, industry). '
        'Your detailed role instructions, writing standards, chapter structure, and investigation scope '
        'are provided in the brief. Follow them precisely. '
        'Complete your analysis autonomously. Do not fabricate information. '
        'Do not use internal terms: 子代理, dispatch, Phase, handoff, Step, manifest, spawn. '
        'CRITICAL: Limit 企查查 MCP calls to at most 10 per role. Prioritize web_search/web_fetch for competitor info. '
        'Only use 企查查 for specific competitor verification. '
        'If you find yourself calling 企查查 repeatedly with similar queries, STOP and write your analysis with existing data.'
    ),
}


def _slug(role_name: str) -> str:
    return ROLE_TO_KEY.get(role_name, role_name.replace('bp_', '').replace('与', '_').replace(' ', '_'))


def notify_wx(text: str) -> bool:
    try:
        sys.path.insert(0, str(ROOT / 'scripts'))
        from longshao_notify import send_message

        result = send_message(text)
        return result.get('ok', False)
    except Exception:
        return False


def _build_brief(task_id: str, sub: dict, task_dir: Path | None = None) -> Path:
    task_dir = task_dir or TASKS_DIR / task_id
    slug = _slug(sub['role_name'])
    brief_path = task_dir / f'bp_phase2_brief_{slug}.md'

    output_rel = Path(sub['output_file'])
    try:
        output_display = str(output_rel.relative_to(ROOT))
    except Exception:
        output_display = str(output_rel)

    # 加载指令库文件（如果存在）
    instruction_content = ''
    instruction_file = INSTRUCTION_STORE / f'{sub["role_name"]}.md'
    if instruction_file.exists():
        try:
            raw = instruction_file.read_text(encoding='utf-8')
            # 去掉指令库中的内部链路描述（已过时），保留调查范围和证据分级
            cleaned_lines = []
            skip_section = False
            for line in raw.split('\n'):
                if '真实链路' in line or '当前可直接依赖的输入' in line:
                    skip_section = True
                    continue
                if skip_section and line.strip().startswith('## '):
                    skip_section = False
                if skip_section:
                    continue
                # 跳过输出文件和禁止章节（system prompt 已覆盖）
                if line.strip().startswith('## 输出文件') or line.strip().startswith('## 禁止'):
                    skip_section = True
                    continue
                cleaned_lines.append(line)
            instruction_content = '\n'.join(cleaned_lines).strip()
        except Exception:
            pass

    lines = [
        f'# BP Research Brief — {sub["role_name"]}',
        '',
        f'- Output file: `{output_display}`',
        '',
        '## 你的任务',
        '- 写一份专业的投研报告章节（对标一线 VC 研报水准）。',
        '- 先用已有输入完成初稿，再自行做 gap 检测和补充搜索。',
        '- 最终输出必须包含：分析叙事、对比表格、来源 URL。',
        '- 禁止写内部术语：子代理、dispatch、Phase、handoff、Step 0/1/2/3/4/5。',
        '- 直接把最终 Markdown 写到指定 output file。',
        '',
        '## 角色说明',
        sub.get('description', ''),
        '',
    ]

    # 注入指令库内容（调查范围、证据分级等）
    if instruction_content:
        lines += [
            '## 详细调查指引（指令库）',
            '',
            instruction_content,
            '',
        ]

    lines.append('## 关键输入文件（都在 workspace 内）')

    candidates = [
        task_dir / 'bp_ocr_text.txt',
        task_dir / 'bp_step0_profile.json',
        task_dir / 'bp_step0_profile.md',
        task_dir / 'company_verify_report.json',
        task_dir / 'bp_presearch_results.json',
    ]
    candidates += sorted(task_dir.glob('bp_presearch_step*.md'))
    candidates += sorted((task_dir / 'body_content').glob('*.json')) if (task_dir / 'body_content').exists() else []

    for p in candidates:
        if p.exists():
            lines.append(f'- `{p.relative_to(ROOT)}`')

    lines += [
        '',
        '## 子任务键值输入',
        '```json',
        json.dumps(sub.get('key_inputs', {}), ensure_ascii=False, indent=2),
        '```',
        '',
        '## ⚠️ 自主闭环规则（最高优先级）',
        '',
        '你在执行过程中必须自主闭环，不要返回主控等待指示：',
        '1. **发现数据缺口** → 自己补搜（工具优先级见下方），继续推进',
        '2. **来源不足** → 自己搜更多来源，补充到输出中',
        '3. **数据矛盾** → 自己判断哪个更可靠，标注矛盾来源',
        '4. **唯一完成条件** → 输出文件写完',
        '',
        '### 补搜工具优先级',
        '1. **企查查 MCP**（最高优先级）— 工商/风险/知产/经营结构化数据',
        '   - `mcp__qcc-company`：工商信息（股东、注册资本、法人、变更记录）',
        '   - `mcp__qcc-risk`：风险信息（诉讼、失信被执行人、行政处罚）',
        '   - `mcp__qcc-ipr`：知识产权（专利、商标、著作权）',
        '   - `mcp__qcc-operation`：经营信息（招投标、资质许可、年报）',
        '2. `web_search` — 通用搜索（DDG + SearXNG 多路合并）',
        '3. `web_fetch` — 对搜索结果做正文深度抓取',
        '4. `neodata-financial-search` — 金融数据（行情、财报、宏观）',
        '',
        '### 补搜纪律',
        '- 最多补搜 3 轮，避免无限循环',
        '- 补搜结果必须标注来源 URL',
        '- 仍搜不到的标注"经 X 次搜索未找到独立来源"',
        '',
        '## 执行要求',
        '- 先读 OCR / Step0 / 工商验证 / Presearch，再补搜索。',
        '- 你的外部判断必须和来源一一对应。',
        '- 如果某点搜不到，要明确写"未找到独立外部证据"，不要编。',
        '- 直接把最终 Markdown 写到指定 output file。',
    ]

    brief_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return brief_path


def _read_brief_content(brief_path: Path) -> str:
    if not brief_path.exists():
        return ''
    text = brief_path.read_text(encoding='utf-8')
    lines = []
    for line in text.split('\n'):
        lines.append(line)
        if line.strip().startswith('- `') and line.strip().endswith('`'):
            ref = line.strip().lstrip('- `').rstrip('`')
            ref_path = ROOT / ref
            if not ref_path.exists():
                continue
            file_size = ref_path.stat().st_size
            if 'body_content' in str(ref_path):
                continue
            elif 'ocr_text' in ref_path.name:
                try:
                    content = ref_path.read_text(encoding='utf-8')[:15000]
                    lines.append(f'\n```\n{content}\n```\n')
                except Exception:
                    pass
            elif ref_path.suffix == '.json':
                try:
                    content = ref_path.read_text(encoding='utf-8')[:8000]
                    lines.append(f'\n```json\n{content}\n```\n')
                except Exception:
                    pass
            elif ref_path.suffix == '.md':
                try:
                    content = ref_path.read_text(encoding='utf-8')[:8000]
                    lines.append(f'\n```markdown\n{content}\n```\n')
                except Exception:
                    pass
            elif file_size < 5000:
                try:
                    content = ref_path.read_text(encoding='utf-8')[:3000]
                    lines.append(f'\n```\n{content}\n```\n')
                except Exception:
                    pass
    return '\n'.join(lines)[:40000]


def _spawn_one(task_id: str, sub: dict, task_dir: Path | None = None) -> dict:
    task_dir = task_dir or TASKS_DIR / task_id
    slug = _slug(sub['role_name'])
    output_path = Path(sub['output_file'])
    receipt_path = task_dir / f'bp_phase2_spawn_{slug}.json'
    manifest_path = task_dir / f'bp_phase2_manifest_{slug}.json'

    if output_path.exists() and output_path.stat().st_size > 50:
        return {'role': sub['role_name'], 'status': 'already_exists', 'output': str(output_path)}

    brief_path = _build_brief(task_id, sub, task_dir=task_dir)
    label = f'{task_id}-bp-phase2-{slug}'
    brief_content = _read_brief_content(brief_path)
    if not brief_content:
        brief_content = (
            f'Role: {sub["role_name"]}\n'
            f'Task ID: {task_id}\n'
            'Complete due diligence analysis for your assigned dimension.'
        )

    system_prompt = ROLE_SYSTEM_PROMPTS.get(sub['role_name'], ROLE_SYSTEM_PROMPTS['bp_竞争与结论'])
    manifest_data = {
        'task_id': task_id,
        'role': sub['role_name'],
        'slug': slug,
        'label': label,
        'system_prompt': system_prompt,
        'brief_path': str(brief_path),
        'brief_content_preview': brief_content[:500],
        'output_path': str(output_path),
        'timeout': 1200,
        'thinking': 'high',
        'dispatch_mode': 'team_async',
        'mode': 'bypassPermissions',
        'subagent_name': 'code-explorer',
        'team_name_template': 'bp-{task_id}',
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'status': 'pending',
    }
    manifest_path.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding='utf-8')

    receipt = {
        'task_id': task_id,
        'role': sub['role_name'],
        'label': label,
        'status': 'dispatched',
        'runId': f'wb-bp-{int(time.time())}',
        'childSessionKey': f'wb-bp-{task_id}-{slug}',
        'runtime': 'workbuddy-task',
        'thinking': 'high',
        'manifest_path': str(manifest_path),
        'output_path': str(output_path),
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'  📋 已派发 BP 子代理: {sub["role_name"]} → manifest: {manifest_path.name}')

    return {
        'role': sub['role_name'],
        'status': 'dispatched',
        'label': label,
        'runId': receipt['runId'],
        'childSessionKey': receipt['childSessionKey'],
        'output': str(output_path),
        'receipt': str(receipt_path),
        'manifest_path': str(manifest_path),
    }


def get_pending_bp_tasks(task_id: str) -> list[dict]:
    task_dir = TASKS_DIR / task_id
    pending = []
    for role_name, slug in ROLE_TO_KEY.items():
        manifest_path = task_dir / f'bp_phase2_manifest_{slug}.json'
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text(encoding='utf-8'))
            output_path = Path(data.get('output_path', ''))
            if not output_path.exists() and data.get('status') == 'pending':
                pending.append(data)
    return pending


def main():
    ap = argparse.ArgumentParser(description='BP Phase 2 Subagent Launcher — WorkBuddy 版 v4 (Task 子代理)')
    ap.add_argument('--task-id', required=True)
    ap.add_argument('--pending', action='store_true', help='List pending BP tasks for Task dispatch')
    args = ap.parse_args()

    if args.pending:
        pending = get_pending_bp_tasks(args.task_id)
        print(json.dumps(pending, ensure_ascii=False, indent=2))
        return

    task_dir = TASKS_DIR / args.task_id
    dispatch_path = task_dir / 'phase2_dispatch.json'
    if not dispatch_path.exists():
        print(json.dumps({'status': 'no_dispatch', 'task_id': args.task_id}, ensure_ascii=False))
        raise SystemExit(1)

    dispatch = json.loads(dispatch_path.read_text(encoding='utf-8'))
    subs = dispatch.get('subagents', [])
    results = []
    for sub in subs:
        results.append(_spawn_one(args.task_id, sub))
        time.sleep(1)

    dispatched = sum(1 for r in results if r.get('status') == 'dispatched')
    ok = all(r.get('status') in ('dispatched', 'already_exists') for r in results)

    if dispatched > 0:
        notify_wx(f'🐲 BP Phase2 已派发\n任务: {args.task_id}\n已派发: {dispatched}/{len(subs)} roles\n运行时: WorkBuddy Task')

    print(json.dumps({
        'task_id': args.task_id,
        'status': 'ok' if ok else 'partial',
        'results': results,
        'runtime': 'workbuddy-task',
        'pending_tasks': dispatched,
    }, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 2)




_BP_SEARCH_TEMPLATES = {
    'bp_团队与合规': [
        '"{entity}" founder background legal compliance litigation',
        '"{entity}" management governance ownership',
        '"{entity}" 创始人 合规 诉讼 管理层',
    ],
    'bp_技术与产品': [
        '"{entity}" technology product patent R&D',
        '"{entity}" product roadmap customer feedback',
        '"{entity}" 技术 产品 专利 研发',
    ],
    'bp_行业与供应链': [
        '"{entity}" industry supply chain market landscape',
        '"{entity}" upstream downstream suppliers customers',
        '"{entity}" 行业 供应链 市场 产业链',
    ],
    'bp_竞争与结论': [
        '"{entity}" competitors market share differentiation',
        '"{entity}" risk analysis investment thesis',
        '"{entity}" 竞争格局 市场份额 风险 投资逻辑',
    ],
}


def do_supplementary_search(task_id: str, role_name: str, entity: str) -> dict:
    """供主控在BP子代理质量不达标时执行补搜。"""
    templates = _BP_SEARCH_TEMPLATES.get(role_name, [])
    if not templates:
        return {'role': role_name, 'memo_path': '', 'has_results': False}

    sys.path.insert(0, str(ROOT / 'scripts'))
    from search_gateway import search as gateway_search

    memo_lines = []
    seen_urls: set[str] = set()
    collected = []
    for template in templates[:5]:
        query = template.format(entity=entity).strip()
        rows = gateway_search(query, max_results=5, timeout=20)
        for row in rows:
            url = row.get('url', '') or ''
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            collected.append((query, row))

    if collected:
        memo_lines.append(f"## BP 补搜结果 ({len(collected)} 条)\n\n")
        for i, (query, row) in enumerate(collected[:12], 1):
            title = row.get('title', '') or ''
            url = row.get('url', '') or ''
            snippet = row.get('content', '') or row.get('snippet', '') or ''
            engine = row.get('engine', '?')
            memo_lines.append(f"### {i}. [{engine}] {title}\n")
            memo_lines.append(f"Query: {query}\n")
            memo_lines.append(f"URL: {url}\n")
            memo_lines.append(f"{snippet[:300]}\n\n")

    slug = _slug(role_name)
    memo_path = TASKS_DIR / task_id / f'bp_phase2_followup_{slug}.md'
    if memo_lines:
        memo_path.write_text(''.join(memo_lines), encoding='utf-8')
        return {'role': role_name, 'memo_path': str(memo_path), 'has_results': True}
    return {'role': role_name, 'memo_path': '', 'has_results': False}
