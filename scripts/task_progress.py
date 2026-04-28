#!/usr/bin/env python3
from __future__ import annotations
import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str]):
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_id')
    ap.add_argument('message')
    ap.add_argument('--stage', default='progress')
    ap.add_argument('--status', choices=['待开始','进行中','待汇总','待确认','已完成','已阻塞'])
    ap.add_argument('--next-action')
    ap.add_argument('--flush', action='store_true')
    args = ap.parse_args()

    cmd = ['python3', str(ROOT/'scripts'/'task_ledger.py'), 'progress', args.task_id, args.message, '--stage', args.stage]
    if args.status:
        cmd.extend(['--status', args.status])
    if args.next_action is not None:
        cmd.extend(['--next-action', args.next_action])
    run(cmd)

    if args.flush:
        run(['python3', str(ROOT/'scripts'/'run_proactive_cycle.py')])


if __name__ == '__main__':
    main()
