#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any

import requests

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) OpenClawResearch/1.0 (contact: local-agent)'
TIMEOUT = 30
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / 'reports' / 'sec_combo'

TICKER_MAP_URL = 'https://www.sec.gov/files/company_tickers.json'
SUBMISSIONS_URL = 'https://data.sec.gov/submissions/CIK{cik}.json'
COMPANYFACTS_URL = 'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
ARCHIVES_BASE = 'https://www.sec.gov/Archives/edgar/data/{cik_nozero}/{accession_no_dash}/{primary_document}'

METRIC_CANDIDATES = {
    'Revenue': ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'],
    'Operating Income': ['OperatingIncomeLoss'],
    'Net Income': ['NetIncomeLoss', 'ProfitLoss'],
    'Operating Cash Flow': ['NetCashProvidedByUsedInOperatingActivities', 'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations'],
    'CapEx': ['PaymentsToAcquirePropertyPlantAndEquipment', 'CapitalExpendituresIncurredButNotYetPaid'],
    'Total Assets': ['Assets'],
    'Total Liabilities': ['Liabilities'],
    'Stockholders Equity': ['StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'],
    'Diluted Shares': ['WeightedAverageNumberOfDilutedSharesOutstanding', 'CommonStockSharesOutstanding'],
    'Diluted EPS': ['EarningsPerShareDiluted'],
}

RISK_KEYWORDS = {
    'litigation': ['litigation', 'lawsuit', 'legal proceeding'],
    'regulatory': ['regulation', 'regulatory', 'investigation', 'compliance'],
    'cybersecurity': ['cybersecurity', 'cyber attack', 'data breach', 'security incident'],
    'supply_chain': ['supply chain', 'supplier', 'manufacturing disruption'],
    'china_geo': ['china', 'tariff', 'trade restriction', 'geopolitical'],
    'ai_competition': ['artificial intelligence', 'ai', 'competition', 'innovation'],
    'going_concern': ['going concern'],
    'material_weakness': ['material weakness', 'internal control'],
}

EIGHT_K_ITEM_MAP = {
    '1.01': '重大协议',
    '1.02': '重大协议终止',
    '1.03': '破产或接管',
    '2.01': '收购/处置完成',
    '2.02': '业绩披露',
    '2.03': '债务触发/融资义务',
    '2.05': '重组成本',
    '2.06': '减值',
    '3.01': '退市/上市规则问题',
    '4.01': '审计师变更',
    '4.02': '财报不再可靠/重述',
    '5.02': '董事高管变动',
    '5.03': '章程变更',
    '7.01': 'Reg FD/投资者沟通',
    '8.01': '其他重大事项',
    '9.01': '财务报表与附件',
}


def _headers(accept: str = 'application/json, text/xml, application/xml;q=0.9, text/html;q=0.8, */*;q=0.5'):
    return {'User-Agent': UA, 'Accept': accept}


def _get_with_retry(url: str, accept: str, attempts: int = 3):
    last_err = None
    for i in range(attempts):
        try:
            r = requests.get(url, headers=_headers(accept), timeout=TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as e:
            last_err = e
            if i < attempts - 1:
                time.sleep(1.5 * (i + 1))
    raise last_err


def http_get_json(url: str) -> Any:
    r = _get_with_retry(url, 'application/json, text/xml, application/xml;q=0.9, text/html;q=0.8, */*;q=0.5')
    return r.json()


def http_get_text(url: str) -> str:
    r = _get_with_retry(url, 'text/html, text/plain;q=0.9, application/xhtml+xml, */*;q=0.5')
    return r.content.decode('utf-8', errors='ignore')


def html_to_text(html: str) -> str:
    html = re.sub(r'(?is)<script.*?>.*?</script>', ' ', html)
    html = re.sub(r'(?is)<style.*?>.*?</style>', ' ', html)
    html = re.sub(r'(?i)<br\s*/?>', '\n', html)
    html = re.sub(r'(?i)</p\s*>', '\n', html)
    html = re.sub(r'(?is)<.*?>', ' ', html)
    text = unescape(html)
    text = text.replace('\xa0', ' ')
    text = re.sub(r'\r', '\n', text)
    text = re.sub(r'\n{2,}', '\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


def clean_excerpt(text: str, limit: int = 260) -> str:
    text = re.sub(r'\s+', ' ', text or '').strip()
    return text[:limit] + ('…' if len(text) > limit else '')


def looks_noisy(text: str) -> bool:
    if not text:
        return True
    sample = text[:240]
    alpha = sum(ch.isalpha() for ch in sample)
    digits = sum(ch.isdigit() for ch in sample)
    if alpha < 40:
        return True
    if digits > alpha:
        return True
    if sample.lower().count('true') + sample.lower().count('false') >= 4:
        return True
    return False


def load_ticker_map() -> dict[str, dict]:
    data = http_get_json(TICKER_MAP_URL)
    out = {}
    for _, row in data.items():
        ticker = row.get('ticker', '').upper()
        if ticker:
            out[ticker] = row
    return out


def resolve_company(ticker: str | None, cik: str | None) -> dict:
    if cik:
        cik_digits = re.sub(r'\D', '', cik).zfill(10)
        submissions = http_get_json(SUBMISSIONS_URL.format(cik=cik_digits))
        return {
            'ticker': ticker or submissions.get('tickers', [''])[0],
            'title': submissions.get('name', ''),
            'cik_str': cik_digits,
        }
    if not ticker:
        raise SystemExit('Need --ticker or --cik')
    row = load_ticker_map().get(ticker.upper())
    if not row:
        raise SystemExit(f'Ticker not found in SEC map: {ticker}')
    return {
        'ticker': row.get('ticker', '').upper(),
        'title': row.get('title', ''),
        'cik_str': str(row.get('cik_str', '')).zfill(10),
    }


def accession_url(cik_str: str, accession: str, primary_document: str) -> str:
    return ARCHIVES_BASE.format(
        cik_nozero=str(int(cik_str)),
        accession_no_dash=accession.replace('-', ''),
        primary_document=primary_document,
    )


def build_recent_filings(submissions: dict, limit_each: int = 3) -> dict[str, list[dict]]:
    recent = submissions.get('filings', {}).get('recent', {})
    forms = recent.get('form', [])
    accession_numbers = recent.get('accessionNumber', [])
    filing_dates = recent.get('filingDate', [])
    primary_docs = recent.get('primaryDocument', [])
    primary_desc = recent.get('primaryDocDescription', [])

    out: dict[str, list[dict]] = {'10-K': [], '10-Q': [], '8-K': []}
    for form, accession, filing_date, primary_doc, desc in zip(forms, accession_numbers, filing_dates, primary_docs, primary_desc):
        base_form = form.replace('/A', '')
        if base_form not in out:
            continue
        out[base_form].append({
            'form': form,
            'filing_date': filing_date,
            'accession_number': accession,
            'primary_document': primary_doc,
            'description': desc,
        })
    for form in out:
        out[form] = out[form][:limit_each]
    return out


def _pick_unit(units: dict[str, list[dict]], metric_name: str) -> tuple[str, list[dict]] | tuple[None, None]:
    prefs = ['USD/shares', 'USD', 'shares']
    if metric_name == 'Diluted Shares':
        prefs = ['shares', 'USD/shares']
    if metric_name == 'Diluted EPS':
        prefs = ['USD/shares', 'USD']
    for pref in prefs:
        if pref in units:
            return pref, units[pref]
    for key, vals in units.items():
        return key, vals
    return None, None


def _pick_latest_fact(vals: list[dict], annual: bool) -> dict | None:
    form_pref = ['10-K', '10-K/A'] if annual else ['10-Q', '10-Q/A']
    filtered = [v for v in vals if v.get('form') in form_pref]
    if not filtered:
        return None
    filtered.sort(key=lambda v: (v.get('filed', ''), v.get('end', '')), reverse=True)
    return filtered[0]


def extract_metrics(companyfacts: dict) -> dict[str, dict]:
    facts = companyfacts.get('facts', {}).get('us-gaap', {})
    result: dict[str, dict] = {}
    for label, candidates in METRIC_CANDIDATES.items():
        chosen = None
        for concept in candidates:
            node = facts.get(concept)
            if not node:
                continue
            unit_name, vals = _pick_unit(node.get('units', {}), label)
            if not vals:
                continue
            annual = _pick_latest_fact(vals, annual=True)
            quarterly = _pick_latest_fact(vals, annual=False)
            chosen = {
                'concept': concept,
                'unit': unit_name,
                'annual': annual,
                'quarterly': quarterly,
            }
            break
        if chosen:
            result[label] = chosen
    return result


def format_value(value: Any, unit: str | None) -> str:
    if value is None:
        return 'N/A'
    try:
        num = float(value)
    except Exception:
        return str(value)
    if unit == 'shares':
        return f'{num:,.0f} shares'
    if unit == 'USD/shares':
        return f'${num:,.2f}'
    if unit == 'USD':
        if abs(num) >= 1_000_000_000:
            return f'${num/1_000_000_000:,.2f}B'
        if abs(num) >= 1_000_000:
            return f'${num/1_000_000:,.2f}M'
        return f'${num:,.0f}'
    return f'{num:,.2f} {unit or ""}'.strip()


def extract_risk_factors(filing_url: str) -> dict:
    try:
        html = http_get_text(filing_url)
        text = html_to_text(html)
    except Exception as e:
        return {'url': filing_url, 'error': str(e), 'risk_hits': [], 'excerpt': ''}

    lower = text.lower()
    candidates = []
    starts = [m.start() for m in re.finditer(r'item\s+1a[\.\s\-:]*risk factors', lower)]
    if not starts:
        starts = [m.start() for m in re.finditer(r'item\s+1a', lower)]
    if not starts:
        starts = [m.start() for m in re.finditer(r'risk factors', lower)]
    for start in starts:
        possible_ends = []
        for marker in ['item 1b', 'item 2', 'unresolved staff comments', 'properties']:
            idx = lower.find(marker, start + 1200)
            if idx != -1:
                possible_ends.append(idx)
        end = min(possible_ends) if possible_ends else len(text)
        section = text[start:end]
        if len(section) < 1500:
            continue
        # skip obvious table-of-contents chunks and later cross-references
        head = section[:500]
        if len(re.findall(r'Item\s+\d', head, flags=re.I)) >= 4 or 'table of contents' in head.lower() or 'item 1b' in head.lower():
            continue
        if not re.search(r'item\s+1a[\.\s\-:]*risk factors', head, flags=re.I) and 'risk factors' not in head.lower():
            continue
        if re.search(r"under the heading [‘’“\"']risk factors[‘’”\"']", head, flags=re.I):
            continue
        section_lower = section.lower()
        hit_rows = []
        total_hits = 0
        for key, patterns in RISK_KEYWORDS.items():
            count = sum(section_lower.count(p) for p in patterns)
            if count:
                hit_rows.append({'risk': key, 'count': count})
                total_hits += count
        candidates.append((start, total_hits, len(section), hit_rows, section))

    if not candidates:
        return {'url': filing_url, 'risk_hits': [], 'excerpt': '', 'note': 'Item 1A not located'}

    # prefer strongest risk section, not the latest stray cross-reference
    candidates.sort(key=lambda x: (x[1], x[2], -x[0]), reverse=True)
    _, _, _, hits, section = candidates[0]
    hits.sort(key=lambda x: x['count'], reverse=True)
    return {
        'url': filing_url,
        'risk_hits': hits,
        'excerpt': clean_excerpt(section, 600),
    }


def analyze_8k(filing_url: str, filing: dict) -> dict:
    try:
        html = http_get_text(filing_url)
        text = html_to_text(html)
    except Exception as e:
        return {'url': filing_url, 'error': str(e), 'items': [], 'category_labels': [], 'excerpt': ''}
    item_codes = re.findall(r'Item\s+(\d+\.\d{2})', text, flags=re.I)
    unique_codes = []
    for code in item_codes:
        if code not in unique_codes:
            unique_codes.append(code)

    labels = [EIGHT_K_ITEM_MAP.get(code, f'8-K Item {code}') for code in unique_codes[:6]]
    desc = clean_excerpt(filing.get('description') or '', 180)

    excerpt = ''
    if unique_codes:
        first = unique_codes[0]
        m = re.search(rf'(Item\s+{re.escape(first)}[\s\S]{{0,900}})', text, flags=re.I)
        if m:
            excerpt = clean_excerpt(m.group(1), 320)
    if not excerpt or looks_noisy(excerpt):
        excerpt = ''

    return {
        'url': filing_url,
        'items': unique_codes[:6],
        'category_labels': labels,
        'description': desc,
        'excerpt': excerpt,
    }


def build_report(company: dict, submissions: dict, companyfacts: dict) -> tuple[dict, str]:
    filings = build_recent_filings(submissions)
    metrics = extract_metrics(companyfacts)
    cik_str = company['cik_str']

    latest_10k = filings.get('10-K', [None])[0]
    risk_factor_review = None
    if latest_10k:
        risk_factor_review = extract_risk_factors(accession_url(cik_str, latest_10k['accession_number'], latest_10k['primary_document']))

    eight_k_reviews = []
    for filing in filings.get('8-K', []):
        filing_url = accession_url(cik_str, filing['accession_number'], filing['primary_document'])
        eight_k_reviews.append({
            'filing_date': filing['filing_date'],
            'form': filing['form'],
            **analyze_8k(filing_url, filing),
        })

    structured = {
        'company': company,
        'sources': {
            'companyfacts': COMPANYFACTS_URL.format(cik=cik_str),
            'submissions': SUBMISSIONS_URL.format(cik=cik_str),
        },
        'recent_filings': filings,
        'metrics': metrics,
        'risk_factor_review': risk_factor_review,
        'eight_k_reviews': eight_k_reviews,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
    }

    lines: list[str] = []
    lines.append(f'# SEC + Financial Analyst Combo — {company["title"]} ({company.get("ticker") or "N/A"})')
    lines.append('')
    lines.append('## Source Snapshot')
    lines.append(f'- Company: {company["title"]}')
    lines.append(f'- Ticker: {company.get("ticker") or "N/A"}')
    lines.append(f'- CIK: {cik_str}')
    lines.append(f'- Company Facts: {structured["sources"]["companyfacts"]}')
    lines.append(f'- Submissions: {structured["sources"]["submissions"]}')
    lines.append('')

    lines.append('## Recent Filing Deck')
    for form in ['10-K', '10-Q', '8-K']:
        lines.append(f'### {form}')
        items = filings.get(form) or []
        if not items:
            lines.append('- None found')
            continue
        for item in items:
            url = accession_url(cik_str, item['accession_number'], item['primary_document'])
            desc = item.get('description') or item.get('primary_document')
            lines.append(f'- {item["filing_date"]} | {item["form"]} | {desc} | {url}')
        lines.append('')

    lines.append('## Financial Summary (SEC XBRL)')
    lines.append('| Metric | Latest Annual | Latest Quarter | Concept |')
    lines.append('|---|---:|---:|---|')
    for metric_name, detail in metrics.items():
        annual = detail.get('annual') or {}
        quarterly = detail.get('quarterly') or {}
        annual_val = format_value(annual.get('val'), detail.get('unit'))
        quarter_val = format_value(quarterly.get('val'), detail.get('unit'))
        lines.append(f'| {metric_name} | {annual_val} | {quarter_val} | `{detail.get("concept")}` |')
    lines.append('')

    lines.append('## Risk Factor Snapshot (Latest 10-K Item 1A)')
    if risk_factor_review:
        if risk_factor_review.get('error'):
            lines.append(f'- Risk factor extraction failed: {risk_factor_review["error"]}')
        elif risk_factor_review.get('risk_hits'):
            for row in risk_factor_review['risk_hits'][:8]:
                lines.append(f'- {row["risk"]}: mentions={row["count"]}')
            lines.append(f'- Filing URL: {risk_factor_review["url"]}')
            if risk_factor_review.get('excerpt'):
                lines.append(f'- Excerpt: {risk_factor_review["excerpt"]}')
        else:
            lines.append('- No obvious keyword hits extracted; review raw 10-K manually.')
    else:
        lines.append('- No 10-K available in recent filings.')
    lines.append('')

    lines.append('## Recent 8-K Event Map')
    if eight_k_reviews:
        for review in eight_k_reviews:
            labels = ' / '.join(review.get('category_labels') or ['未识别 item'])
            lines.append(f'- {review["filing_date"]} | {labels}')
            if review.get('description'):
                lines.append(f'  - Description: {review["description"]}')
            if review.get('excerpt'):
                lines.append(f'  - Excerpt: {review["excerpt"]}')
            lines.append(f'  - Filing URL: {review["url"]}')
    else:
        lines.append('- No recent 8-K found.')
    lines.append('')

    lines.append('## Analyst Workboard (Financial Analyst Skill)')
    lines.append('### Intake')
    lines.append(f'- Scope suggestion: equity research memo + comps + optional DCF for {company["title"]}.')
    lines.append('- Currency / units: keep explicit in every table (default USD, millions if useful).')
    lines.append('- As-of date: use latest filing date above and state it in every output.')
    lines.append('')
    lines.append('### Mandatory Sections')
    lines.append('- Thesis / key question')
    lines.append('- Filing-backed financial summary')
    lines.append('- Recent 8-K / material events review')
    lines.append('- Risk-factor delta and concentration review')
    lines.append('- Risks / catalysts')
    lines.append('- Comps table (if peers available)')
    lines.append('- DCF assumptions table (if valuation requested)')
    lines.append('')
    lines.append('### Quality Rules')
    lines.append('- Raw SEC filing links must be included; do not rely only on secondary summaries.')
    lines.append('- Separate “observed from filing” vs “analyst inference”.')
    lines.append('- If key metrics are missing from companyfacts, say so explicitly instead of filling from imagination.')
    lines.append('- If risk-factor extraction looks thin, escalate to manual review instead of pretending coverage is complete.')
    lines.append('')
    lines.append('### Next Step Prompts')
    lines.append('- Compare latest 10-K Item 1A against prior year for newly added or elevated risks.')
    lines.append('- Review latest 8-Ks for management changes, financings, restructurings, or guidance changes.')
    lines.append('- Build a comps set and valuation bridge before making a view on upside/downside.')
    lines.append('')

    return structured, '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ticker')
    ap.add_argument('--cik')
    ap.add_argument('--output-prefix')
    args = ap.parse_args()

    company = resolve_company(args.ticker, args.cik)
    submissions = http_get_json(SUBMISSIONS_URL.format(cik=company['cik_str']))
    companyfacts = http_get_json(COMPANYFACTS_URL.format(cik=company['cik_str']))
    structured, report = build_report(company, submissions, companyfacts)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prefix = args.output_prefix or f"{(company.get('ticker') or company['cik_str']).lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    md_path = OUT_DIR / f'{prefix}.md'
    json_path = OUT_DIR / f'{prefix}.json'
    md_path.write_text(report, encoding='utf-8')
    json_path.write_text(json.dumps(structured, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'md_path': str(md_path), 'json_path': str(json_path), 'company': company}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
