#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'


def parse_company(task_id: str) -> dict:
    plan_path = TASKS_DIR / f'{task_id}-S02-search-plan.json'
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        tc = plan.get('target_company', {}) or {}
        ticker = tc.get('ticker', '')
        digits = re.sub(r'\D', '', ticker)
        return {
            'name': tc.get('name', ''),
            'ticker': ticker,
            'code4': digits[-4:].zfill(4) if digits else '',
        }
    return {'name': '', 'ticker': '', 'code4': ''}




def candidate_queries(info: dict, explicit: str = '') -> list[str]:
    if explicit:
        return [explicit]
    name = info.get('name') or ''
    trad = (name.replace('医生', '醫生')
                .replace('医疗', '醫療')
                .replace('药', '藥')
                .replace('业', '業'))
    cands = [trad, name, info.get('code4') or '', info.get('ticker') or '']
    out = []
    for c in cands:
        c = (c or '').strip()
        if c and c not in out:
            out.append(c)
    return out

def run_search(query: str, max_rows: int = 30):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale='zh-HK')
        page.set_default_timeout(60000)
        last = None
        for _ in range(3):
            try:
                page.goto('https://www.hkexnews.hk/search/titlesearch.xhtml?lang=zh', wait_until='domcontentloaded', timeout=60000)
                last = None
                break
            except Exception as e:
                last = e
                page.wait_for_timeout(2000)
        if last:
            raise last
        page.wait_for_timeout(3000)
        page.locator('#searchStockCode').fill(query)
        page.wait_for_timeout(1500)
        try:
            page.locator('#searchStockCode').press('ArrowDown')
            page.wait_for_timeout(300)
            page.locator('#searchStockCode').press('Enter')
            page.wait_for_timeout(500)
        except Exception:
            pass
        page.locator('#hkex_news_header_section .btn-blue').click()
        page.wait_for_timeout(5000)
        rows = page.locator('table tbody tr').evaluate_all(f'''rows => rows.slice(0,{max_rows}).map(r => {{
          const tds = [...r.querySelectorAll('td')].map(td => (td.innerText||'').trim());
          const links = [...r.querySelectorAll('a')].map(a => ({{text:(a.textContent||'').trim(), href:a.href||''}}));
          return {{tds, links}};
        }})''')
        body = page.locator('body').inner_text()[:3000]
        browser.close()
        return rows, body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_id')
    ap.add_argument('--query', default='')
    args = ap.parse_args()
    info = parse_company(args.task_id)
    tried = []
    candidates = candidate_queries(info, args.query)
    rows, body, query = [], '', ''
    for cand in [c for c in candidates if c]:
        query = cand
        tried.append(cand)
        rows, body = run_search(cand)
        if rows:
            break
    out = {
        'task_id': args.task_id,
        'query': query,
        'tried_queries': tried,
        'company': info,
        'row_count': len(rows),
        'rows': rows,
        'body_snippet': body,
    }
    out_dir = TASKS_DIR / args.task_id / 'hkex-playwright'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / 'search-results.json'
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'task_id': args.task_id, 'query': query, 'row_count': len(rows), 'out_path': str(out_path)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
