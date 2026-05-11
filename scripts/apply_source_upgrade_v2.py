#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from html import unescape

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

DEFAULT_CERT = '/opt/homebrew/etc/openssl@3/cert.pem'
DEFAULT_CERT_DIR = '/opt/homebrew/etc/openssl@3/certs'


def ensure_ssl_env():
    if os.path.exists(DEFAULT_CERT) and not os.environ.get('SSL_CERT_FILE'):
        os.environ['SSL_CERT_FILE'] = DEFAULT_CERT
        os.environ['REQUESTS_CA_BUNDLE'] = DEFAULT_CERT
        os.environ['CURL_CA_BUNDLE'] = DEFAULT_CERT
    if os.path.exists(DEFAULT_CERT_DIR) and not os.environ.get('SSL_CERT_DIR'):
        os.environ['SSL_CERT_DIR'] = DEFAULT_CERT_DIR


def clean_text(text: str) -> str:
    text = unescape(text or '')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_with_bs4(html: str):
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:
        return None
    soup = BeautifulSoup(html, 'html.parser')
    title = ''
    if soup.title and soup.title.get_text():
        title = soup.title.get_text(strip=True)
    desc = ''
    tag = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', attrs={'property': 'og:description'})
    if tag and tag.get('content'):
        desc = tag['content']
    excerpt = ''
    for p in soup.find_all('p'):
        t = ' '.join(p.stripped_strings)
        if len(t) >= 80:
            excerpt = t
            break
    if not excerpt:
        for p in soup.find_all('p'):
            t = ' '.join(p.stripped_strings)
            if len(t) >= 40:
                excerpt = t
                break
    return clean_text(title), clean_text(desc), clean_text(excerpt)


def extract_with_regex(html: str):
    title = ''
    desc = ''
    excerpt = ''
    m = re.search(r'<title[^>]*>(.*?)</title>', html, flags=re.I | re.S)
    if m:
        title = m.group(1)
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html, flags=re.I | re.S)
    if not m:
        m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']', html, flags=re.I | re.S)
    if m:
        desc = m.group(1)
    m = re.search(r'<p[^>]*>(.*?)</p>', html, flags=re.I | re.S)
    if m:
        excerpt = re.sub(r'<[^>]+>', ' ', m.group(1))
    return clean_text(title), clean_text(desc), clean_text(excerpt)


def fetch_metadata(url: str):
    try:
        import requests
    except Exception as e:
        return {'ok': False, 'error': f'requests import failed: {e}'}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36'
    }
    try:
        r = requests.get(url, headers=headers, timeout=25)
        r.raise_for_status()
        if r.encoding:
            text = r.text
        else:
            r.encoding = r.apparent_encoding
            text = r.text
        data = extract_with_bs4(text) or extract_with_regex(text)
        title, desc, excerpt = data
        return {'ok': True, 'title': title, 'desc': desc, 'excerpt': excerpt}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def parse_source_upgrade(md_text: str):
    items = []
    current_section = None
    current_item = None
    lines = md_text.splitlines()
    for line in lines:
        s = line.strip()
        if s.startswith('### '):
            current_section = s[4:].strip()
            continue
        m = re.match(r'^\d+\.\s*\*\*(.+?)\*\*', s)
        if m:
            if current_item:
                items.append(current_item)
            current_item = {
                'section': current_section,
                'title_hint': m.group(1).strip(),
                'urls': [],
                'why': '',
                'tier': None,
            }
            continue
        if 'URL:' in s:
            url = s.split('URL:', 1)[1].strip()
            if current_item and url:
                current_item['urls'].append(url)
            continue
        if 'Why it matters:' in s:
            if current_item:
                current_item['why'] = s.split('Why it matters:', 1)[1].strip()
            continue
        if 'Tier:' in s:
            if current_item:
                m = re.search(r'(\d+)', s)
                if m:
                    current_item['tier'] = int(m.group(1))
            continue
    if current_item:
        items.append(current_item)
    entries = []
    for item in items:
        for url in item.get('urls', []) or []:
            entries.append({
                'section': item.get('section') or '',
                'title_hint': item.get('title_hint') or '',
                'why': item.get('why') or '',
                'tier': item.get('tier'),
                'url': url,
            })
    return entries


def normalize_section(section: str) -> str:
    s = section or ''
    if '估值' in s:
        return '估值 / 目标价'
    if '竞争' in s or '出口限制' in s or '风险催化' in s:
        return '竞争 / 出口限制 / 风险催化'
    if '产品路线图' in s or '供给节奏' in s:
        return '产品路线图 / 供给节奏'
    return s or '其他'


def confidence_from_tier(tier: int | None) -> str:
    if tier == 1:
        return 'high'
    if tier == 2:
        return 'medium'
    if tier == 3:
        return 'low'
    return 'low'


def load_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(cmd: list[str]):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\n{p.stderr or p.stdout}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task-id', default='TASK-20260318-019')
    ap.add_argument('--source-upgrade')
    ap.add_argument('--force-rebuild', action='store_true')
    ap.add_argument('--no-rebuild', action='store_true')
    args = ap.parse_args()

    ensure_ssl_env()

    task_id = args.task_id
    source_md = Path(args.source_upgrade) if args.source_upgrade else (TASKS_DIR / f'{task_id}-source-upgrade-v2.md')
    if not source_md.exists():
        print(f'ERROR: source-upgrade file not found: {source_md}', file=sys.stderr)
        sys.exit(1)

    evidence_path = TASKS_DIR / f'{task_id}-evidence.json'
    data = load_json(evidence_path, {'task_id': task_id, 'rows': []}) or {'task_id': task_id, 'rows': []}
    rows = data.get('rows', []) or []
    existing_urls = {r.get('source_url') for r in rows if r.get('source_url')}

    entries = parse_source_upgrade(source_md.read_text(encoding='utf-8'))
    if not entries:
        print('No entries parsed from source-upgrade-v2.')
        sys.exit(0)

    added = 0
    errors = []
    for e in entries:
        url = e['url']
        if url in existing_urls:
            continue
        meta = fetch_metadata(url)
        if meta.get('ok'):
            title = meta.get('title') or e.get('title_hint') or url
            desc = meta.get('desc') or ''
            excerpt = meta.get('excerpt') or ''
        else:
            title = e.get('title_hint') or url
            desc = ''
            excerpt = ''
            errors.append({'url': url, 'error': meta.get('error')})

        claim = desc or excerpt
        if not claim:
            why = e.get('why') or e.get('title_hint') or '待核查'
            claim = f"待核查：{why}"

        row = {
            'section': normalize_section(e.get('section') or ''),
            'source_title': clean_text(title),
            'claim': clean_text(claim),
            'evidence_excerpt': clean_text(excerpt or desc),
            'source_url': url,
            'source_type': 'web',
            'confidence': confidence_from_tier(e.get('tier')),
        }
        rows.append(row)
        existing_urls.add(url)
        added += 1

    data['rows'] = rows
    save_json(evidence_path, data)

    print(f'Updated evidence: +{added} rows (total={len(rows)})')
    if errors:
        print(f'Fetch errors: {len(errors)}')
        for e in errors[:5]:
            print(f"- {e['url']} :: {e['error']}")

    if args.no_rebuild:
        print('Skip rebuild (--no-rebuild).')
        return

    if added == 0 and not args.force_rebuild:
        print('No new rows added; skip rebuild. Use --force-rebuild to rebuild anyway.')
        return

    package = TASKS_DIR / f'{task_id}.json'
    reviewer = TASKS_DIR / f'{task_id}-reviewer.json'
    evidence_clean = TASKS_DIR / f'{task_id}-evidence-clean.json'
    analysis = TASKS_DIR / f'{task_id}-analysis-draft.md'
    memo = TASKS_DIR / f'{task_id}-final-memo.md'
    instruction_memo = TASKS_DIR / f'{task_id}-final-memo-instruction-guided.md'

    run(['python3', str(ROOT/'scripts'/'build_ir_reviewer_report.py'), str(evidence_path)])
    run(['python3', str(ROOT/'scripts'/'filter_ir_evidence.py'), str(evidence_path), str(reviewer)])
    run(['python3', str(ROOT/'scripts'/'build_ir_analysis_draft.py'), str(evidence_clean)])
    run(['python3', str(ROOT/'scripts'/'build_ir_final_memo.py'), str(analysis)])
    if package.exists():
        run(['python3', str(ROOT/'scripts'/'build_ir_instruction_guided_memo.py'), str(package), str(analysis)])
    else:
        print(f'WARN: package missing, skip instruction-guided memo: {package}')
    run(['python3', str(ROOT/'scripts'/'assemble_ir_bundle.py'), task_id])

    print('Rebuild completed.')


if __name__ == '__main__':
    main()
