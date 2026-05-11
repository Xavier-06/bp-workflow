#!/usr/bin/env python3
"""
IR Gap Detector — 研报预搜索证据 vs 研报9个维度的缺口检测

用途:
  1. 跑完 ir_presearch 后，调用此脚本
  2. 分析预搜索证据是否覆盖研报所需的 8 个维度 + 估值预测
  3. 给每个维度 + 每条证据做质量评分
  4. 输出缺口清单 + 针对性搜索词，供后续迭代深钻用

与 BP DD gap_detector 的区别:
  - BP DD: 从 BP OCR 提取定量声称 → 对比搜索验证
  - IR: 从研报 8 个 step 维度 → 检查预搜索证据覆盖率

用法:
  python3 scripts/ir_gap_detector.py --task-id TASK-XXX
  python3 scripts/ir_gap_detector.py --task-id TASK-XXX --entity "英伟达" --market us
  python3 scripts/ir_gap_detector.py --task-id TASK-XXX --use-facts
"""
from __future__ import annotations
import argparse
import json
import re
import urllib.parse
import os
from datetime import datetime
from pathlib import Path

os.environ.setdefault('SSL_CERT_FILE', '/opt/homebrew/etc/openssl@3/cert.pem')
os.environ.setdefault('REQUESTS_CA_BUNDLE', '/opt/homebrew/etc/openssl@3/cert.pem')

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / 'data' / 'tasks'


# ============================================================
# 维度覆盖关键词 (对应研报 8+1 个 step)
# ============================================================

REPORT_DIMENSIONS = {
    'step1_data': {
        'name': '行情与基础数据',
        'keywords': [
            'stock price', 'market cap', 'pe ratio', 'pb ratio', 'eps',
            'shares outstanding', '52-week', '市值', '股价', '市盈率',
            'dividend', '分红', '回购', 'buyback', 'analyst rating',
            'consensus', '目标价', '分析师',
        ],
        'required_count': 3,
    },
    'step2_industry': {
        'name': '行业与市场格局',
        'keywords': [
            'industry', 'market size', 'market share', 'growth rate',
            'competitor', 'competitive landscape', '行业规模', '竞争格局',
            '市场份额', 'TAM', 'SAM', 'industry drivers', '行业增速',
            '玩家', '市占率', '渗透率', 'penetration',
        ],
        'required_count': 3,
    },
    'step3_business': {
        'name': '商业模式与盈利能力',
        'keywords': [
            'business model', 'revenue stream', 'revenue breakdown',
            'gross margin', 'pricing power', 'customer', 'unit economics',
            'moat', '护城河', '收入结构', '商业模式', '盈利能力',
            '毛利率', '客户留存', 'ARPU',
        ],
        'required_count': 3,
    },
    'step4_finance': {
        'name': '财务分析与趋势',
        'keywords': [
            'revenue', 'net profit', 'operating cash flow', 'free cash flow',
            'capex', 'balance sheet', 'debt', 'leverage',
            'ROE', 'ROIC', '利润率', '营收', '净利润', '现金流',
            '资产负债率', '财务分析', 'EBITDA',
        ],
        'required_count': 3,
    },
    'step5_mgmt': {
        'name': '管理层与股权结构',
        'keywords': [
            'CEO', 'management team', 'governance', 'ownership',
            'shareholder', 'insider', 'insider buying', 'insider selling',
            '管理层', '大股东', '股权结构', '公司治理',
            'board of directors', '董事', '减持', '增持',
        ],
        'required_count': 2,
    },
    'step6_insight': {
        'name': '差异化洞察与非共识',
        'keywords': [
            'catalyst', 'bull case', 'non-consensus', 'undervalued',
            'contrarian', '催化剂', '被低估', '非共识',
            'short interest', '看多', '看空',
        ],
        'required_count': 1,
    },
    'step6b_valuation': {
        'name': '预测与估值',
        'keywords': [
            'DCF', 'valuation', 'WACC', 'terminal value', 'sensitivity',
            'target price', 'PE', 'PB', 'PS', 'EV/EBITDA', 'comparable',
            '估值', '目标价', '可比公司', '敏感性分析', '折现',
            'free cash flow', 'discount rate', 'growth rate',
        ],
        'required_count': 2,
    },
    'step7_risk': {
        'name': '风险与催化剂',
        'keywords': [
            'risk', 'downside', 'regulatory', 'competition threat',
            'cash burn', 'dilution', 'lock-up', '风险', '下行',
            '监管风险', '减持压力', '解锁', 'dilution risk',
            'going concern', 'bear case',
        ],
        'required_count': 2,
    },
    'step8_master': {
        'name': '统稿所需交叉验证',
        'keywords': [
            'valuation', 'DCF', 'peer comparison', 'target price',
            'recommendation', '估值', '可比公司', '投资建议',
        ],
        'required_count': 1,
    },
    'verification': {
        'name': '官方/一手验证',
        'keywords': [
            'annual report', 'SEC filing', '10-K', '10-Q', '8-K',
            'earnings call', 'transcript', '年报', '公告',
            'hkex', 'cninfo', 'investor relations', 'IR page',
        ],
        'required_count': 1,
    },
}


# ============================================================
# 来源质量评分
# ============================================================

OFFICIAL_DOMAINS_KEYWORDS = [
    'sec.gov', 'hkexnews.hk', 'cninfo.com.cn', 'sse.com.cn', 'szse.cn',
    'gov.cn', 'investor.', '.ir.', 'annual report', 'investor relations',
    'earnings call', 'transcript',
]

AUTHORITATIVE_DOMAINS = [
    'reuters.com', 'bloomberg.com', 'wsj.com', 'ft.com', 'barrons.com',
    'caixin.com', 'cls.cn', 'yicai.com', '36kr.com', 'huxiu.com',
    'seekingalpha.com', 'morningstar.com', 'marketwatch.com',
    'cnbc.com', 'forbes.com', 'investopedia.com',
    '东方财富网', 'eastmoney.com', 'sina.com.cn/finance',
    'zhitongcaijing', '富途', 'futunn.com', 'xueqiu.com',
    '韭研公社', '萝卜投研', 'choice', 'wind',
]

LOW_SIGNAL_DOMAINS = [
    'tieba.baidu.com', 'douban.com', 'reddit.com',
    'toutiao.com', 'baijiahao.baidu.com',
]


def source_quality_score(url: str, title: str = '', snippet: str = ''):
    """返回 (score: float, label: str)"""
    if not url:
        return (0.0, '未标注')
    try:
        parsed = urllib.parse.urlparse(url)
        domain = (parsed.hostname or '').lower().lstrip('www.')
    except Exception:
        domain = ''

    combined = f'{url} {title} {snippet}'.lower()

    # 一手源
    for kw in OFFICIAL_DOMAINS_KEYWORDS:
        if kw in domain or kw in combined:
            if kw.endswith('.gov') or 'hkexnews' in domain or 'cninfo' in domain:
                return (3.0, 'A+')
            return (2.0, 'A')

    # 权威媒体
    for d in AUTHORITATIVE_DOMAINS:
        if d in domain:
            return (1.5, 'B+')
        if d in combined:
            return (1.0, 'B')

    # 低信号
    for d in LOW_SIGNAL_DOMAINS:
        if d in domain:
            return (0.0, 'C')

    # 默认
    return (0.5, 'C-')


# ============================================================
# 证据解析 — 从预搜索 markdown 文件中提取结构化数据
# ============================================================

def parse_presearch_file(path: Path) -> list[dict]:
    """从预搜索 .md 文件提取证据条目"""
    if not path.exists() or path.stat().st_size < 100:
        return []
    text = path.read_text(encoding='utf-8')
    evidence = []

    # Parse ## 来源 section: markdown links with domains
    # Format: 1. [Title](url) — domain OR with published date
    src_pattern = re.compile(r'\d+\.\s+\[([^\]]+)\]\((https?://[^)]+)\)\s*—\s*(\S+)')
    for m in src_pattern.finditer(text):
        title, url, domain = m.group(1), m.group(2), m.group(3)
        # Strip trailing date like (2025-01-03T00:00:00)
        domain = domain.rstrip(') ')
        if date_match := re.search(r'\((\d{4}-\d{2}-\d{2}T?\d*)\)', domain + ')'):
            domain = domain.replace(date_match.group(0), '').strip()
        evidence.append({
            'url': url,
            'title': title,
            'snippet': '',
            'source_file': str(path.name),
        })

    # Parse ## Citations section: [{url}] {json with title}
    # Format: [https://example.com/] {'index': 1, 'title': '...', 'domain': '...'}
    cit_pattern = re.compile(r'\[(https?://[^\]]+)\]\s*\{.+?["\']title["\']\s*:\s*["\'](.*?)["\'].+?\}')
    for m in cit_pattern.finditer(text):
        url, title = m.group(1), m.group(2)
        evidence.append({
            'url': url,
            'title': title,
            'snippet': '',
            'source_file': str(path.name),
        })

    # Parse Search Memo section for general context
    memo_start = text.find('## Search Memo')
    citations_start = text.find('## Citations')
    if memo_start >= 0 and citations_start > memo_start:
        memo_text = text[memo_start:citations_start].strip()
        # Keep the full memo including markdown — keyword matching is case-insensitive
        if len(memo_text) > 50:
            evidence.append({
                'url': '',
                'title': '',
                'snippet': memo_text[:4000],
                'source_file': str(path.name),
            })

    return evidence

def parse_presearch_json(path: Path) -> list[dict]:
    """如果 presearch 结果以 JSON 存储"""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        results = []
        for item in data if isinstance(data, list) else data.get('results', []):
            results.append({
                'url': item.get('url', ''),
                'title': item.get('title', ''),
                'snippet': item.get('snippet', item.get('body', '')),
                'source_file': str(path.name),
            })
        return results
    except Exception:
        return []


def parse_extracted_facts(path: Path) -> dict:
    """解析 extract_content 输出的结构化事实"""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data
    except Exception:
        return {}


# ============================================================
# 核心检测逻辑
# ============================================================


# ============================================================
# 数据质量门禁 (2026-04-04)
# ============================================================

def _check_presearch_noise(task_id: str, entity: str) -> dict:
    """
    当 Gap 检测发现证据为 0 但预搜索文件存在时，检查是否是搜索噪音导致。
    
    返回:
    - {'has_noise_issue': False} — 正常，无噪音问题
    - {'has_noise_issue': True, 'diagnosis': ..., 'raw_presearch_files': [...]} — 有噪音
    """
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.ir_noise_filter import check_noise_ratio
        
        presearch_files = sorted(TASKS_DIR.glob(f'{task_id}-search-step*.md'))
        if not presearch_files:
            return {'has_noise_issue': False, 'reason': 'no_presearch_files'}
        
        # 检查预搜索文件是否有 content 但没被解析为证据
        total_presearch_size = 0
        empty_evidence_files = []
        
        for pf in presearch_files:
            total_presearch_size += pf.stat().st_size
            text = pf.read_text(encoding='utf-8')
            
            # Count citations (the actual evidence entries)
            citation_count = text.count('[http')
            
            if citation_count == 0 and pf.stat().st_size > 100:
                empty_evidence_files.append(pf.name)
        
        diagnosis = {
            'total_presearch_size_kb': round(total_presearch_size / 1024, 1),
            'presearch_file_count': len(presearch_files),
            'empty_evidence_files': empty_evidence_files,
        }
        
        if empty_evidence_files:
            return {
                'has_noise_issue': True,
                'diagnosis': f"预搜索文件存在但证据提取率为 0。可能原因：1) 搜索噪音过高导致证据被过滤 "
                             f"({len(empty_evidence_files)}/{len(presearch_files)} 文件无有效证据). "
                             f"预搜索总大小: {diagnosis['total_presearch_size_kb']}KB "
                             f"({len(presearch_files)} 个文件).",
                'raw_presearch_files': [str(f) for f in presearch_files],
            }
        
        return {'has_noise_issue': False}
        
    except Exception as e:
        return {'has_noise_issue': False, 'check_error': str(e)}

def detect(task_id: str, entity: str = '', market: str = 'us', use_facts: bool = False) -> dict:
    # 1. 收集所有预搜索结果 + 子代理 step 输出
    all_evidence = []
    all_text_parts = []
    presearch_files = sorted(TASKS_DIR.glob(f'{task_id}-search-step*.md'))
    for pf in presearch_files:
        all_evidence.extend(parse_presearch_file(pf))

    # 1b. 读取子代理 step 输出 (如果有 rich data)
    step_files = sorted(TASKS_DIR.glob(f'{task_id}-step*.md'))
    for sf in step_files:
        if '-search-step' in sf.name:
            continue
        text = sf.read_text(encoding='utf-8')
        all_text_parts.append(text[:5000].lower())

    # JSON 兼容
    json_files = sorted(TASKS_DIR.glob(f'{task_id}-presearch-*.json'))
    for jf in json_files:
        all_evidence.extend(parse_presearch_json(jf))

    # 1b. 读取子代理 step 输出 (如果有)
    step_files = sorted(TASKS_DIR.glob(f'{task_id}-step*.md'))
    for sf in step_files:
        if '-search-step' in sf.name or '-pre-' in sf.name:
            continue  # skip presearch files, handled above
        text = sf.read_text(encoding='utf-8')
        all_text_parts.append(text[:5000].lower())

    # 1d. 数据质量门禁 — 检查预搜索证据是否被噪音淹没 (2026-04-04)
    noise_check = _check_presearch_noise(task_id, entity)
    
    # 2. 加载 LLM 提取的结构化事实 (如果有)
    facts = {}
    if use_facts:
        facts_files = sorted(TASKS_DIR.glob(f'{task_id}-extracted_facts.json'))
        if not facts_files:
            facts_files = sorted(TASKS_DIR.glob('body_content/ir_extracted_facts.json'))
        for ff in facts_files:
            facts.update(parse_extracted_facts(ff))

    # 3. 构建全文本用于维度覆盖检测
    all_text_parts = []
    evidence_with_quality = []
    for ev in all_evidence:
        q_score, q_label = source_quality_score(ev.get('url', ''), ev.get('title', ''), ev.get('snippet', ''))
        ev['quality_score'] = q_score
        ev['quality_label'] = q_label
        evidence_with_quality.append(ev)
        text_blob = f"{ev.get('title', '')} {ev.get('snippet', '')} {ev.get('url', '')}"
        if text_blob.strip():
            all_text_parts.append(text_blob.lower())

    all_text = ' '.join(all_text_parts)

    # 合并结构化事实中的内容
    if facts:
        fact_texts = json.dumps(facts, ensure_ascii=False).lower()
        all_text += ' ' + fact_texts

    # 4. 维度覆盖分析
    dimension_results = {}
    for dim_key, dim_cfg in REPORT_DIMENSIONS.items():
        keywords = dim_cfg['keywords']
        required = dim_cfg['required_count']

        keyword_hits = []
        for kw in keywords:
            if kw.lower() in all_text:
                keyword_hits.append(kw)

        # 计算该维度相关的证据数量和质量
        dim_evidence = []
        dim_quality_total = 0.0
        for ev in evidence_with_quality:
            ev_text = f"{ev.get('title', '')} {ev.get('snippet', '')}".lower()
            hit_count = sum(1 for kw in keywords if kw.lower() in ev_text)
            if hit_count > 0:
                dim_evidence.append({
                    'url': ev.get('url', ''),
                    'title': ev.get('title', ''),
                    'quality': ev.get('quality_label', ''),
                    'score': ev.get('quality_score', 0),
                    'keyword_hits': hit_count,
                })
                dim_quality_total += ev.get('quality_score', 0)

        # 覆盖率
        coverage_ratio = len(keyword_hits) / max(len(keywords), 1)
        has_evidence = len(dim_evidence) >= required
        quality_adequate = dim_quality_total >= 2.0  # 至少一条 A 或两条 B

        # 判定
        if has_evidence and quality_adequate and coverage_ratio >= 0.3:
            status = 'covered'
        elif has_evidence and coverage_ratio >= 0.15:
            status = 'partial'
        elif not has_evidence:
            status = 'missing'
        else:
            status = 'weak'

        dimension_results[dim_key] = {
            'name': dim_cfg['name'],
            'status': status,
            'keyword_coverage': f'{len(keyword_hits)}/{len(keywords)}',
            'keyword_hits': keyword_hits,
            'evidence_count': len(dim_evidence),
            'quality_total': round(dim_quality_total, 1),
            'quality_adequate': quality_adequate,
            'evidence_samples': dim_evidence[:3],
        }

    # 5. 生成缺口搜索词
    gap_queries = []
    entity_search = entity or ''
    entity_en = entity_search  # 简化处理，实际可以用 LLM 翻译

    for dim_key, result in dimension_results.items():
        if result['status'] in ('missing', 'weak'):
            missing_kw = [kw for kw in REPORT_DIMENSIONS[dim_key]['keywords']
                          if kw.lower() not in all_text]
            # 生成搜索词
            for kw in missing_kw[:4]:
                if entity_search:
                    gap_queries.append(f'{entity_search} {kw}')
                    gap_queries.append(f'{entity_en} {kw}')
                else:
                    gap_queries.append(kw)

    # 6. 总体评级
    statuses = [r['status'] for r in dimension_results.values()]
    covered_count = statuses.count('covered')
    partial_count = statuses.count('partial')
    missing_count = statuses.count('missing') + statuses.count('weak')
    total = len(statuses)

    quality_ratio = covered_count / max(total, 1)

    if quality_ratio >= 0.85 and missing_count <= 1:
        overall_grade = 'A'
        overall_label = '数据充足'
    elif quality_ratio >= 0.7:
        overall_grade = 'B'
        overall_label = '基本充足(有缺口)'
    elif quality_ratio >= 0.5:
        overall_grade = 'C'
        overall_label = '明显缺口，需深钻'
    elif quality_ratio >= 0.3:
        overall_grade = 'D'
        overall_label = '信息严重不足'
    else:
        overall_grade = 'E'
        overall_label = '几乎无数据支撑'

    # 7. 构建输出
    result = {
        'task_id': task_id,
        'entity': entity,
        'market': market,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'overall_grade': overall_grade,
        'overall_label': overall_label,
        'total_evidence': len(evidence_with_quality),
        'noise_check': noise_check,  # 2026-04-04: 数据质量门禁
        'dimensions': {
            dim_key: {
                'name': r['name'],
                'status': r['status'],
                'keyword_coverage': r['keyword_coverage'],
                'keyword_hits': r['keyword_hits'],
                'evidence_count': r['evidence_count'],
                'quality_total': r['quality_total'],
                'evidence_samples': r['evidence_samples'],
            }
            for dim_key, r in dimension_results.items()
        },
        'covered_count': covered_count,
        'partial_count': partial_count,
        'missing_count': missing_count,
        'gap_queries': list(dict.fromkeys(gap_queries))[:30],  # 去重，最多30个
        'summary': (
            f'IR Gap 检测完成: {covered_count}/{total} 维度已覆盖，'
            f'{partial_count} 部分覆盖，{missing_count} 缺失/弱。'
            f'总证据 {len(evidence_with_quality)} 条。评级: {overall_grade} — {overall_label}'
        ),
    }

    # 8. 写入文件
    gap_path = TASKS_DIR / f'{task_id}-ir_gap_report.json'
    gap_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                         encoding='utf-8')

    # 写 gap queries markdown 供后续搜索
    gap_md_path = TASKS_DIR / f'{task_id}-ir_gap_queries.md'
    gap_lines = [
        f'# IR Gap 搜索清单',
        f'',
        f'- Task ID: {task_id}',
        f'- Entity: {entity}',
        f'- Grade: {overall_grade} - {overall_label}',
        f'- 已覆盖: {covered_count}/{total} 维度',
        f'- 需补搜: {missing_count} 维度',
        f'- 生成时间: {datetime.now().isoformat(timespec="seconds")}',
        f'',
        f'## 缺口维度',
        f'',
    ]
    for dim_key, r in dimension_results.items():
        if r['status'] in ('missing', 'weak', 'partial'):
            gap_lines.append(f'### {r["name"]} ({r["status"]})')
            gap_lines.append(f'- 关键词覆盖: {r["keyword_coverage"]}')
            gap_lines.append(f'- 缺失关键词: {[kw for kw in REPORT_DIMENSIONS[dim_key]["keywords"] if kw.lower() not in all_text][:5]}')
            gap_lines.append(f'- 证据数: {r["evidence_count"]}')
            gap_lines.append(f'')
    gap_lines.append(f'## 建议搜索词\n')
    for i, q in enumerate(list(dict.fromkeys(gap_queries))[:30], 1):
        gap_lines.append(f'{i}. {q}')
    gap_md_path.write_text('\n'.join(gap_lines) + '\n', encoding='utf-8')

    # 9. 打印摘要
    print(f"\n{'='*60}")
    print(f"🔎 IR Gap Detector 完成: {task_id}")
    print(f"   总证据: {len(evidence_with_quality)} 条")
    print(f"   覆盖: {covered_count}/{total} 维度")
    print(f"   评级: {overall_grade} — {overall_label}")
    print(f"")
    print(f"   维度详情:")
    for dim_key, r in dimension_results.items():
        icon = {'covered': '✅', 'partial': '🟡', 'weak': '🟠', 'missing': '❌'}.get(r['status'], '❓')
        print(f"   {icon} {r['name']:20s} → {r['status']:8s} (关键词 {r['keyword_coverage']}, "
              f"证据 {r['evidence_count']}, 质量 {r['quality_total']})")
    if gap_queries:
        print(f"\n   建议补搜: {len(gap_queries)} 个查询")
    print(f"{'='*60}")

    return result


def main():
    ap = argparse.ArgumentParser(description='IR Gap Detector')
    ap.add_argument('--task-id', required=True, help='Task ID')
    ap.add_argument('--entity', default='', help='Entity name (for query generation)')
    ap.add_argument('--market', default='us', help='Market (us/hk/cn)')
    ap.add_argument('--use-facts', action='store_true',
                     help='Use LLM-extracted structured facts if available')
    args = ap.parse_args()

    detect(args.task_id, args.entity, args.market, args.use_facts)


if __name__ == '__main__':
    main()
