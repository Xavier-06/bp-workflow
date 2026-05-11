#!/usr/bin/env python3
from pathlib import Path
import os, sys

os.environ['SSL_CERT_FILE'] = '/opt/homebrew/etc/openssl@3/cert.pem'
sys.path.insert(0, str(Path(__file__).parent))

from ir_gap_detector import parse_presearch_file, REPORT_DIMENSIONS

TASKS_DIR = Path('data/tasks')
TEST = 'TASK-20260329-001'

files = sorted(TASKS_DIR.glob(f'{TEST}-search-step*.md'))
print(f"Found {len(files)} presearch files")

all_text_parts = []
for pf in files:
    evs = parse_presearch_file(pf)
    print(f"\n{pf.name}: {len(evs)} evidence items")
    for ev in evs[:2]:
        print(f"  url={ev['url'][:50] if ev['url'] else '(none)'}")
        print(f"  title={ev['title'][:60] if ev['title'] else '(none)'}")
        print(f"  snippet_len={len(ev.get('snippet', ''))}")
        if ev.get('snippet') and len(ev['snippet']) > 10:
            print(f"  snippet_start={ev['snippet'][:120]}...")
        tb = f"{ev.get('title','')} {ev.get('snippet','')} {ev.get('url','')}"
        if tb.strip():
            all_text_parts.append(tb.lower())

all_text = ' '.join(all_text_parts)
print(f"\n=== Total searchable text: {len(all_text)} chars ===")

# Test keywords for step1_data
print(f"\n=== step1_data keywords test ===")
for kw in REPORT_DIMENSIONS['step1_data']['keywords']:
    found = kw.lower() in all_text
    print(f"  {'✅' if found else '❌'} '{kw}'")
