#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET

import requests

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) OpenClawResearch/1.0 (contact: local-agent)'
TIMEOUT = 25

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class FeedItem:
    source: str
    bucket: str
    title: str
    link: str
    summary: str
    published_at: str | None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in (
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%d %H:%M:%S%z',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d',
    ):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def clean(text: str | None) -> str:
    text = text or ''
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def fetch_xml(url: str) -> str:
    last_err = None
    for _ in range(3):
        try:
            r = requests.get(url, headers={'User-Agent': UA}, timeout=TIMEOUT)
            r.raise_for_status()
            return r.content.decode('utf-8-sig', errors='ignore').lstrip('\ufeff')
        except Exception as e:
            last_err = e
    raise last_err


def _child_text(node, names: Iterable[str]) -> str | None:
    for name in names:
        child = node.find(name)
        if child is not None and child.text:
            return child.text.strip()
    return None


def parse_feed(xml_text: str, source: str, bucket: str) -> list[FeedItem]:
    root = ET.fromstring(xml_text)
    items: list[FeedItem] = []

    # RSS 2.0
    for item in root.findall('.//item'):
        title = clean(_child_text(item, ['title']))
        link = clean(_child_text(item, ['link']))
        summary = clean(_child_text(item, ['description', 'summary']))
        published = _child_text(item, ['pubDate', 'published', 'updated'])
        items.append(FeedItem(source=source, bucket=bucket, title=title, link=link, summary=summary, published_at=published))

    if items:
        return items

    # Atom
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    for entry in root.findall('.//atom:entry', ns):
        title = clean(_child_text(entry, ['{http://www.w3.org/2005/Atom}title', 'title']))
        summary = clean(_child_text(entry, ['{http://www.w3.org/2005/Atom}summary', '{http://www.w3.org/2005/Atom}content', 'summary']))
        published = _child_text(entry, ['{http://www.w3.org/2005/Atom}updated', '{http://www.w3.org/2005/Atom}published', 'updated'])
        link = ''
        for link_node in entry.findall('{http://www.w3.org/2005/Atom}link') + entry.findall('link'):
            href = link_node.attrib.get('href')
            if href:
                link = href
                break
        items.append(FeedItem(source=source, bucket=bucket, title=title, link=link, summary=summary, published_at=published))
    return items


CRYPTO_FEEDS = [
    ('CoinDesk', 'crypto', 'https://www.coindesk.com/arc/outboundfeeds/rss/'),
    ('Cointelegraph', 'crypto', 'https://cointelegraph.com/rss'),
    ('The Block', 'crypto', 'https://www.theblock.co/rss.xml'),
]

BASELINE_FEEDS = [
    ('BBC Business', 'business', 'https://feeds.bbci.co.uk/news/business/rss.xml'),
    ('Fed Press', 'macro_official', 'https://www.federalreserve.gov/feeds/press_all.xml'),
    ('BLS Latest', 'macro_official', 'https://www.bls.gov/feed/bls_latest.rss'),
    ('SEC Press', 'reg_official', 'https://www.sec.gov/rss/news/press.xml'),
]

SECTION_RULES = {
    '隔夜行情': [r'bitcoin', r'btc', r'ethereum', r'eth', r'crypto', r'solana', r'price', r'rally', r'surge', r'falls?', r'drops?'],
    '宏观': [r'cpi', r'ppi', r'inflation', r'federal reserve', r'fed', r'fomc', r'payroll', r'jobs report', r'unemployment', r'\brates?\b', r'u\.?s\.? treasury', r'treasury yields?'],
    '监管': [r'\bsec\b', r'cftc', r'regulat', r'enforcement', r'stablecoin', r'compliance'],
    'ETF': [r'\betf\b', r'inflows?', r'outflows?', r'blackrock', r'grayscale', r'fidelity', r'spot bitcoin', r'spot ethereum'],
    '机构动态': [r'microstrategy', r'blackrock', r'coinbase', r'fidelity', r'ark invest', r'institution'],
}

OFFICIAL_MACRO_PATTERNS = [r'cpi', r'ppi', r'inflation', r'fomc', r'federal reserve', r'payroll', r'jobs report', r'unemployment', r'rates?']


def match_section(text: str) -> list[str]:
    text = text.lower()
    hits = []
    for section, patterns in SECTION_RULES.items():
        if any(re.search(p, text) for p in patterns):
            hits.append(section)
    return hits


def item_dt(item: FeedItem) -> datetime:
    return parse_dt(item.published_at) or datetime(1970, 1, 1, tzinfo=timezone.utc)


def dedupe(items: list[FeedItem], limit: int = 5) -> list[dict]:
    out = []
    seen = set()
    for item in sorted(items, key=item_dt, reverse=True):
        key = (item.title.lower(), item.link)
        if not item.title or key in seen:
            continue
        seen.add(key)
        out.append(asdict(item))
        if len(out) >= limit:
            break
    return out


def build_guard(hours: int = 36) -> dict:
    cutoff = now_utc() - timedelta(hours=hours)
    fetched: list[FeedItem] = []
    feed_errors: list[dict] = []

    for source, bucket, url in CRYPTO_FEEDS + BASELINE_FEEDS:
        try:
            xml_text = fetch_xml(url)
            items = parse_feed(xml_text, source=source, bucket=bucket)
            for item in items:
                dt = parse_dt(item.published_at)
                if dt and dt < cutoff:
                    continue
                fetched.append(item)
        except Exception as e:
            feed_errors.append({'source': source, 'url': url, 'error': str(e)})

    sections: dict[str, list[FeedItem]] = {k: [] for k in SECTION_RULES}
    official_macro_events: list[FeedItem] = []

    for item in fetched:
        text = f'{item.title} {item.summary}'.lower()
        for section in match_section(text):
            sections[section].append(item)
        if item.bucket == 'macro_official' and any(re.search(p, text) for p in OFFICIAL_MACRO_PATTERNS):
            official_macro_events.append(item)

    section_json = {name: dedupe(items, limit=4) for name, items in sections.items()}
    official_macro_json = dedupe(official_macro_events, limit=4)
    recent_business = dedupe([i for i in fetched if i.bucket in {'business', 'macro_official', 'reg_official'}], limit=8)
    recent_crypto = dedupe([i for i in fetched if i.bucket == 'crypto'], limit=8)

    failures: list[str] = []
    warnings: list[str] = []
    if len(recent_crypto) < 2:
        failures.append('近36小时加密 RSS 新鲜度不足（crypto feed < 2）')
    if official_macro_json and not section_json.get('宏观'):
        failures.append('官方宏观源已检测到事件，但宏观栏没有命中')
    if len(recent_business) < 2:
        warnings.append('主流/官方 business-macro feed 偏少，建议人工复核')
    if feed_errors and len(feed_errors) >= 3:
        warnings.append('多条 RSS 拉取失败，新闻基线稳定性下降')

    return {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'hours': hours,
        'ok': not failures,
        'failures': failures,
        'warnings': warnings,
        'feed_errors': feed_errors,
        'recent_crypto': recent_crypto,
        'recent_business': recent_business,
        'official_macro_events': official_macro_json,
        'sections': section_json,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=int, default=36)
    ap.add_argument('--output')
    args = ap.parse_args()

    data = build_guard(hours=args.hours)
    content = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(content + '\n', encoding='utf-8')
    print(content)
    raise SystemExit(0 if data['ok'] else 2)


if __name__ == '__main__':
    main()
