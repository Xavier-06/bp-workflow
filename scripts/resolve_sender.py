#!/usr/bin/env python3
"""Resolve a Feishu sender_id to a recipient key.

Usage:
    python3 scripts/resolve_sender.py <sender_id>
    python3 scripts/resolve_sender.py --name "周欣"
    python3 scripts/resolve_sender.py --name "周总"

Returns the recipient key (e.g. 'zhouzong') or 'xavier' as fallback.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECIPIENTS_PATH = ROOT / 'config' / 'recipients.json'


def load_recipients() -> dict:
    with open(RECIPIENTS_PATH, encoding='utf-8') as f:
        return json.load(f)


def resolve_by_sender_id(sender_id: str) -> str:
    data = load_recipients()
    sender_map = data.get('sender_map', {})
    # Try exact match
    if sender_id in sender_map:
        return sender_map[sender_id]
    # Try stripping 'ou_' prefix
    stripped = sender_id.replace('ou_', '')
    if stripped in sender_map:
        return sender_map[stripped]
    return 'xavier'


def resolve_by_name(name: str) -> str:
    data = load_recipients()
    recipients = data.get('recipients', {})
    name_lower = name.lower().strip()
    for key, val in recipients.items():
        if val.get('display_name', '').lower() == name_lower:
            return key
        if val.get('real_name', '').lower() == name_lower:
            return key
    # Fuzzy: check if name is contained in display_name or real_name
    for key, val in recipients.items():
        if name_lower in val.get('display_name', '').lower():
            return key
        if name_lower in (val.get('real_name') or '').lower():
            return key
    return 'xavier'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sender_id', nargs='?', default='')
    ap.add_argument('--name', default='')
    args = ap.parse_args()

    if args.name:
        result = resolve_by_name(args.name)
    elif args.sender_id:
        result = resolve_by_sender_id(args.sender_id)
    else:
        result = 'xavier'

    print(result)


if __name__ == '__main__':
    main()
