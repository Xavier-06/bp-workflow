#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'
MEMORY_AGENT = ROOT / 'memory_agent'
sys.path.insert(0, str(MEMORY_AGENT))
from instruction_store import InstructionStore  # type: ignore


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def key_points_from_instruction(text: str, keywords: list[str]) -> list[str]:
    lines = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith(('###', '##', '#')):
            continue
        if any(k in s for k in keywords):
            lines.append(s)
    out, seen = [], set()
    for s in lines:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out[:6]


def bullets_from_analysis(text: str, section: str, limit: int = 6) -> list[str]:
    pattern = rf'^### {re.escape(section)}\n([\s\S]*?)(?=^### |^## |\Z)'
    m = re.search(pattern, text, flags=re.M)
    if not m:
        return []
    block = m.group(1)
    items = []
    for raw in block.splitlines():
        s = raw.strip()
        if s.startswith('- ') and '证据：' not in s and '当前缺口' not in s and '当前观察' not in s:
            items.append(s[2:].strip())
    return items[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_package')
    ap.add_argument('analysis_draft')
    args = ap.parse_args()

    pkg = load_json(Path(args.task_package))
    analysis_text = Path(args.analysis_draft).read_text(encoding='utf-8')
    task = pkg['task']
    query = (pkg.get('query') or '')
    ql = query.lower()
    is_nvidia = ('英伟达' in query) or ('nvidia' in ql) or ('nvda' in ql)
    store = InstructionStore()

    supervisor = store.get_instruction('投研_主管') or {}
    risk = store.get_instruction('投研_主笔_风险催化') or {}
    handoff = store.get_instruction('投研_主笔_移交说明') or {}
    docsum = store.get_instruction('投研_文档汇总') or {}
    style = store.get_instruction('投研_模板_卖方券商风格') or {}

    supervisor_points = key_points_from_instruction(supervisor.get('instruction', ''), ['确认任务', '审核', '汇总', '快速模式'])
    risk_points = key_points_from_instruction(risk.get('instruction', ''), ['催化剂', '风险', '量化', 'ESG'])
    handoff_points = key_points_from_instruction(handoff.get('instruction', ''), ['给建模师', '给总编辑', '必须'])
    docsum_points = key_points_from_instruction(docsum.get('instruction', ''), ['规则', '报告结构', '输出'])
    style_points = key_points_from_instruction(style.get('instruction', ''), ['正文结构', '术语统一', '数据与结论分离', '禁止项', '估值写作'])

    if is_nvidia:
        sections = ['财务表现 / 分部结构', '产品路线图 / 供给节奏', '估值 / 目标价', '竞争 / 出口限制 / 风险催化']
    else:
        sections = ['市场规模 / 增长', '关键玩家 / 可比公司', '政策 / 技术变化']
    extracted = {s: bullets_from_analysis(analysis_text, s) for s in sections}

    lines = [f'# Final Memo Draft (Instruction-guided) - {task["task_id"]}', '']
    if is_nvidia:
        lines += [
            '## 投资摘要',
            '- 英伟达当前研究已经形成“财务表现 + 路线图 + 初步估值”三条主线，但风险与估值量化仍不足。',
            '- 本稿按主管/风险/移交/文档汇总/券商模板指令收口，目标是更像正式深研框架，而不是 generic memo。',
            '',
            '## 主管视角',
        ]
        for s in supervisor_points[:3]:
            lines.append(f'- {s}')
        lines += ['', '## 核心逻辑']
        for sec in sections:
            if extracted[sec]:
                lines.append(f'- {sec}：{extracted[sec][0]}')
        lines += ['', '## 分章节正文']
    else:
        lines += ['## 主管视角结论', '- 当前这份输出定位为框架版 memo，不是最终定稿。']

    for sec in sections:
        lines += [f'### {sec}']
        if extracted[sec]:
            for item in extracted[sec]:
                lines.append(f'- {item}')
        else:
            lines.append('- 当前仍需继续补证据。')
        lines.append('')

    lines += ['## 催化剂与风险（按角色指令收口）']
    for s in risk_points[:4]:
        lines.append(f'- {s}')
    if is_nvidia:
        lines += [
            '- 对英伟达来说，当前最关键的风险线是出口限制、客户自研 ASIC、AMD/其他加速器竞争，以及 Blackwell 节奏兑现。',
            '- 当前还缺催化剂时间点与风险影响幅度的量化。',
        ]
    else:
        lines += ['- 当前还缺能直接量化影响的催化剂时间点与风险影响幅度。']

    lines += ['', '## 给建模师 / 总编辑的移交提示']
    for s in handoff_points[:4]:
        lines.append(f'- {s}')
    lines += ['- 建模侧：优先补齐收入拆分、毛利率桥、估值假设。', '- 编辑侧：当前可先写框架版深研，不宜写成确定性投资结论。']

    lines += ['', '## 文档汇总与券商模板约束']
    for s in (docsum_points[:3] + style_points[:3]):
        lines.append(f'- {s}')
    lines += ['- 当前目标是“结构完整、结论克制、来源可追”，不是把搜到的材料直接拼接。']

    lines += ['', '## 下一步建议', '1. 继续补高质量一手来源。', '2. 生成独立估值与预测附表。', '3. 再做一轮正式统稿与风格清洗。']

    out_path = TASKS_DIR / f"{task['task_id']}-final-memo-instruction-guided.md"
    out_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'task_id': task['task_id'], 'output': str(out_path)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
