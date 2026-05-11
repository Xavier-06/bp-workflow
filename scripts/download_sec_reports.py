#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
import time
from pathlib import Path
from html import unescape

import requests

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) OpenClawResearch/1.0 (contact: local-agent)'
TIMEOUT = 30
TICKER_MAP_URL = 'https://www.sec.gov/files/company_tickers.json'
SUBMISSIONS_URL = 'https://data.sec.gov/submissions/CIK{cik}.json'
ARCHIVES_BASE = 'https://www.sec.gov/Archives/edgar/data/{cik_nozero}/{accession_no_dash}/{primary_document}'


def _headers(accept='application/json, text/html;q=0.9, */*;q=0.5'):
    return {'User-Agent': UA, 'Accept': accept}


def _get(url: str, accept='application/json, text/html;q=0.9, */*;q=0.5', attempts: int = 3):
    last = None
    for i in range(attempts):
        try:
            r = requests.get(url, headers=_headers(accept), timeout=TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            if i < attempts - 1:
                time.sleep(i + 1)
    raise last


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def infer_ticker(task_id: str) -> str:
    search_plan = TASKS_DIR / f'{task_id}-S02-search-plan.json'
    if search_plan.exists():
        plan = load_json(search_plan)
        tc = plan.get('target_company', {}) or {}
        ticker = tc.get('ticker') or ''
        if ticker:
            return ticker.replace('.US', '').replace('.O', '').replace('.N', '').upper()
    pkg = load_json(TASKS_DIR / f'{task_id}.json')
    q = pkg.get('query', '')
    m = re.search(r'\b([A-Z]{1,5})\b', q)
    return m.group(1) if m else ''


def resolve_company(ticker: str) -> dict:
    data = _get(TICKER_MAP_URL).json()
    for _, row in data.items():
        if row.get('ticker', '').upper() == ticker.upper():
            return {'ticker': row['ticker'].upper(), 'title': row.get('title', ''), 'cik_str': str(row.get('cik_str', '')).zfill(10)}
    raise SystemExit(f'ticker not found: {ticker}')


def accession_url(cik_str: str, accession: str, primary_document: str) -> str:
    return ARCHIVES_BASE.format(cik_nozero=str(int(cik_str)), accession_no_dash=accession.replace('-', ''), primary_document=primary_document)


def html_to_text(html: str) -> str:
    html = re.sub(r'(?is)<script.*?>.*?</script>', ' ', html)
    html = re.sub(r'(?is)<style.*?>.*?</style>', ' ', html)
    html = re.sub(r'(?is)<.*?>', ' ', html)
    text = unescape(html)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_id')
    args = ap.parse_args()
    task_id = args.task_id
    ticker = infer_ticker(task_id)
    if not ticker:
        raise SystemExit('cannot infer us ticker from task/search plan')
    company = resolve_company(ticker)
    out_dir = TASKS_DIR / task_id / 'sec'
    out_dir.mkdir(parents=True, exist_ok=True)
    submissions = _get(SUBMISSIONS_URL.format(cik=company['cik_str'])).json()
    (out_dir / 'submissions.json').write_text(json.dumps(submissions, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    recent = submissions.get('filings', {}).get('recent', {})
    forms = recent.get('form', [])
    accs = recent.get('accessionNumber', [])
    dates = recent.get('filingDate', [])
    docs = recent.get('primaryDocument', [])
    saved = []
    seen = {'10-K': 0, '10-Q': 0, '8-K': 0}
    for form, acc, dt, doc in zip(forms, accs, dates, docs):
        base = form.replace('/A', '')
        if base not in seen or seen[base] >= 2:
            continue
        url = accession_url(company['cik_str'], acc, doc)
        try:
            r = _get(url, accept='text/html, text/plain;q=0.9, */*;q=0.5')
            html = r.content.decode('utf-8', errors='ignore')
            stem = f"{dt}_{base}_{doc}".replace('/', '_')
            html_path = out_dir / f'{stem}.html'
            txt_path = out_dir / f'{stem}.txt'
            html_path.write_text(html, encoding='utf-8')
            txt_path.write_text(html_to_text(html), encoding='utf-8')
            saved.append({'form': form, 'date': dt, 'url': url, 'html_path': str(html_path), 'txt_path': str(txt_path)})
            seen[base] += 1
        except Exception:
            continue
    manifest = {'task_id': task_id, 'company': company, 'count': len(saved), 'files': saved}
    manifest_path = out_dir / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'task_id': task_id, 'out_dir': str(out_dir), 'count': len(saved), 'manifest': str(manifest_path)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
