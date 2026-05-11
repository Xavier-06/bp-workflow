#!/usr/bin/env python3
"""
IR 研报交付 — 生成报告并通过 ClawBot/WorkBuddy 文档媒体链投递

交付流程：
1. 生成来源审计 + 执行审计
2. 生成券商风格 Word 报告
3. 将最终 Markdown 注册到 media-index
4. 通过 message-queue + attachments 引用文档投递给用户

说明：
- 当前已验证 Markdown 文档可通过 media-index + attachments 形成真实文档引用链
- docx 仍保留本地生成，但微信/ClawBot 首版交付先以 Markdown 文档送达为主
- `wx_notify.py --file` 已降级为纯文本路径提示，不再作为真实附件发送方案
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK_LEDGER = ROOT / 'scripts' / 'task_ledger.py'
PROACTIVE = ROOT / 'scripts' / 'run_proactive_cycle.py'
REGISTER_MEDIA = ROOT / 'scripts' / 'register_delivery_media.py'


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def progress(task_id: str, msg: str, stage: str):
    run(['python3', str(TASK_LEDGER), 'progress', task_id, msg, '--stage', stage])
    run(['python3', str(PROACTIVE)])


def send_document_delivery(task_id: str, markdown_path: str, message: str, session_id: str) -> dict:
    r = run([
        'python3',
        str(REGISTER_MEDIA),
        markdown_path,
        '--session-id', session_id,
        '--text', f'🐲 研报交付通知\n\n📋 任务: {task_id}\n💬 {message}'
    ])
    if r.returncode != 0:
        return {'ok': False, 'error': r.stderr or r.stdout}
    try:
        return json.loads(r.stdout)
    except Exception:
        return {'ok': False, 'error': r.stdout}


def main():
    ap = argparse.ArgumentParser(description='IR 研报交付（文档媒体投递）')
    ap.add_argument('task_id')
    ap.add_argument('--session-id', required=True, help='目标 WorkBuddy 会话 ID，用于 media-index/消息关联')
    ap.add_argument('--message', default='研报已生成，请直接查看文档。')
    ap.add_argument('--skip-audit', action='store_true', help='跳过审计生成')
    args = ap.parse_args()

    tid = args.task_id
    step8_path = ROOT / 'data' / 'tasks' / f'{tid}-step8_master.md'
    if not step8_path.exists():
        progress(tid, '交付阻塞：最终 Markdown 不存在', 'deliver-fail')
        raise SystemExit(2)

    if not args.skip_audit:
        progress(tid, '开始交付阶段：生成来源审计与执行审计', 'deliver-start')
        r1 = run(['python3', str(ROOT / 'scripts' / 'build_ir_source_audit.py'), tid])
        r2 = run(['python3', str(ROOT / 'scripts' / 'build_ir_execution_audit.py'), tid])
        if r1.returncode != 0 or r2.returncode != 0:
            progress(tid, f'交付阻塞：审计构建失败。source_audit={r1.returncode}, execution_audit={r2.returncode}', 'deliver-fail')
            raise SystemExit(3)

    progress(tid, '开始生成券商风格 Word 报告', 'deliver-build-docx')
    r3 = run(['python3', str(ROOT / 'scripts' / 'build_ir_broker_report_docx.py'), tid])
    if r3.returncode != 0:
        progress(tid, f'交付阻塞：Word生成失败 code={r3.returncode}', 'deliver-fail')
        raise SystemExit(4)
    docx_payload = json.loads(r3.stdout)
    docx_path = docx_payload['output']

    progress(tid, '开始通过 ClawBot 文档媒体链投递 Markdown 研报', 'deliver-send-doc')
    result = send_document_delivery(tid, str(step8_path), args.message, args.session_id)
    if not result.get('ok'):
        progress(tid, f'文档投递失败: {result}', 'deliver-notify-fail')
        raise SystemExit(5)

    progress(tid, '文档投递已发送 ✅', 'deliver-notify-sent')
    progress(tid, '交付完成 ✅', 'deliver-done')
    print(json.dumps({
        'task_id': tid,
        'markdown': str(step8_path),
        'docx': docx_path,
        'delivery': result,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
