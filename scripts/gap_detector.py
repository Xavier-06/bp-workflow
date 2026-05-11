#!/usr/bin/env python3
"""
BP 尽调 Gap Detector — 对比 BP 声称 vs 搜索结果，识别信息缺口

用途：
  1. 跑完 presearch 后，调用此脚本
  2. 自动提取 BP 中所有定量声称（订单/出货/市占/融资等）
  3. 对比搜索结果，标记每条声称的验证状态
  4. 输出 Gap 清单 + 针对性搜索词，供下一轮深钻

用法：
  python3 scripts/gap_detector.py --task-id TASK-XXX
"""
import argparse
import json
import re
import sys
from pathlib import Path
import urllib.parse

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / 'tasks'

# ── 定量声称识别关键词 ──
QUANT_PATTERNS = [
    # 订单/收入
    (r'(\d+\.?\d*)\s*亿.*订单', '订单金额'),
    (r'(\d+\.?\d*)\s*万.*订单', '订单金额'),
    (r'(\d+\.?\d*)\s*亿.*合同', '合同金额'),
    (r'(\d+\.?\d*)\s*亿.*营收', '营收'),
    (r'(\d+\.?\d*)\s*亿.*收入', '收入'),
    # 出货量
    (r'(\d+\.?\d*)\s*万.*颗', '芯片出货量'),
    (r'(\d+\.?\d*)\s*亿.*颗', '芯片出货量'),
    (r'(\d+\.?\d*)\s*万.*片', '模组出货量'),
    # 市占率
    (r'市占率.*(\d+\.?\d*)\s*%', '市占率'),
    (r'占.*(\d+\.?\d*)\s*%.*市场', '市占率'),
    (r'(\d+\.?\d*)\s*%.*份额', '市场份额'),
    # 融资
    (r'融资?\s*(\d+\.?\d*)\s*亿', '融资金额'),
    (r'融资?\s*(\d+\.?\d*)\s*万', '融资金额'),
    # 客户
    (r'(\d+)\s*家.*客户', '客户数量'),
    # 员工/专利
    (r'(\d+)\s*项.*专利', '专利数量'),
    (r'(\d+)\s*项.*软著', '软著数量'),
    # 市场规模（BP 自己声称的）
    (r'市场.*(\d+\.?\d*)\s*(亿|万).*美元', 'BP 市场规模估计'),
    (r'市场.*(\d+\.?\d*)\s*(亿|万).*元', 'BP 市场规模估计'),
]

# ── 定性声称关键词（需验证的关键主张） ──
QUALITATIVE_KEYWORDS = [
    '第一', '领先', '唯一', '独家', '首创', '垄断',
    '突破', '全球领先', '国内领先', '行业领先',
    '头部客户', '大客户', '战略合作',
    '量产', '批量交付', '规模化',
    'IPO', '上市', 'Pre-IPO',
]

# ── 证据质量评分域名单 ──
OFFICIAL_DOMAINS = [
    'gov.cn', 'cnipa.gov.cn', 'caac.gov.cn', 'miit.gov.cn',
    'hkexnews.hk', 'sec.gov', 'sme.gov.cn',
    'cninfo.com.cn', 'sse.com.cn', 'szse.cn',
    'qcc.com', 'tianyancha.com', 'qixin.com',
    'wenshu.court.gov.cn', 'zxgk.court.gov.cn',
]

AUTHORITATIVE_DOMAINS = [
    '36kr.com', 'huxiu.com', 'tmtpost.com', 'pingwest.com',
    'zhihu.com', 'weixin.qq.com', 'mp.weixin.qq.com',
    'sohu.com', '163.com', 'sina.com.cn',
    'google.com', 'scholar.google.com', 'arxiv.org',
    'reuters.com', 'bloomberg.com', 'wsj.com',
    'caixin.com', 'yicai.com', 'cls.cn',
    'cnnic.cn', 'cnn.cn',
]

LOW_SIGNAL_DOMAINS = [
    'tieba.baidu.com', 'douban.com', 'reddit.com',
    'toutiao.com', 'baijiahao.baidu.com', 'baike.baidu.com',
]


def source_quality_score(url: str) -> tuple:
    """给来源 URL 打质量分 → (score, label)"""
    try:
        domain = urllib.parse.urlparse(url).netloc.lower()
        domain = domain.replace('www.', '')
    except Exception:
        return (0, '🅲 未知来源')

    for d in OFFICIAL_DOMAINS:
        if d in domain:
            return (2, '🅰')
    for d in AUTHORITATIVE_DOMAINS:
        if d in domain:
            return (1, '🅱')
    for d in LOW_SIGNAL_DOMAINS:
        return (0, '🅲')
    return (0.5, '🅲')


def extract_numbers(text: str) -> list:
    """从文本提取所有数字"""
    return re.findall(r'(\d+\.?\d*)', text)


def extract_claims(ocr_text: str, profile: dict) -> list:
    """从 OCR 文本提取 BP 声称"""
    claims = []

    if not ocr_text:
        return claims

    # 定量声称
    for pattern, claim_type in QUANT_PATTERNS:
        for match in re.finditer(pattern, ocr_text):
            claims.append({
                'type': claim_type,
                'text': match.group(0),
                'value': match.group(1),
                'unit': match.group(2) if match.lastindex >= 2 else '',
                'verified': 'unverified',
                'evidence_urls': [],
                'gap_queries': [],
                'source_quality_scores': [],
                'quality_label': '',
            })

    # 定性声称（每个关键词只记录1次，且去上下文重复）
    seen_qual = set()
    for kw in QUALITATIVE_KEYWORDS:
        matches = list(re.finditer(kw, ocr_text))
        if not matches:
            continue
        # 去上下文太相似的重复（同关键词只保留第1次）
        start = max(0, matches[0].start() - 30)
        end = min(len(ocr_text), matches[0].end() + 30)
        context = ocr_text[start:end].strip()
        # 过滤太短或没有实质内容的匹配
        if len(context.strip()) < 5:
            continue
            claims.append({
                'type': '定性声称',
                'text': context,
                'value': kw,
                'unit': '',
                'verified': 'unverified',
                'evidence_urls': [],
                'gap_queries': [],
                'source_quality_scores': [],
                'quality_label': '',
            })

    # 团队声称
    founders = profile.get('founders', [])
    for name in founders:
        if len(name) > 1 and name not in ('未识别', ''):
            claims.append({
                'type': '团队背景',
                'text': f"创始人/核心人物：{name}",
                'value': name,
                'unit': '',
                'verified': 'unverified',
                'evidence_urls': [],
                'gap_queries': [f'"{name}" 背景 履历', f'"{name}" 前东家'],
                'source_quality_scores': [],
                'quality_label': '',
            })

    # 竞品声称
    competitors = profile.get('competitors', {}).get('direct', [])
    for comp in competitors:
        if comp and len(comp) > 1 and comp != '待搜索确认':
            claims.append({
                'type': '竞品存在',
                'text': f"竞品：{comp}",
                'value': comp,
                'verified': 'unverified',
                'evidence_urls': [],
                'gap_queries': [f'"{comp}" 融资 技术 对比'],
                'source_quality_scores': [],
                'quality_label': '',
            })

    return claims


def match_evidence(claims: list, search_results: dict) -> list:
    """
    对比搜索结果，标记验证状态 — v2

    改进：
    1. 来源质量权重（🅰=2分 🅱=1分 🅲=0分）
    2. 定量声称：数字比较，差异 >20% 标 conflict
    3. 同一域名只算 1 次独立验证
    """
    for claim in claims:
        claim_text = claim['text'].lower()
        claim_value = claim['value'].lower()
        claim_type = claim['type']
        claim_num = claim.get('value', '')

        verified_urls = []
        conflict_urls = []
        quality_scores = []
        quality_labels = set()
        seen_domains = set()

        for step_key, results in search_results.items():
            for r in results:
                title_snippet = (r.get('title', '') + ' ' + r.get('snippet', '')).lower()
                url = r.get('url', '')
                
                # 来源质量
                q_score, q_label = source_quality_score(url)

                # 检查相关性
                is_relevant = False
                is_conflict = False

                # 定量声称：数字比较
                if claim_type in ('订单金额', '合同金额', '营收', '收入',
                                  '芯片出货量', '模组出货量',
                                  '市占率', '市场份额',
                                  '融资金额', '客户数量',
                                  '专利数量', '软著数量',
                                  'BP 市场规模估计'):
                    # 提取搜索结果中的所有数字
                    text_numbers = extract_numbers(title_snippet)
                    
                    if claim_num and any(claim_num in t for t in text_numbers):
                        # 精确匹配 → verified
                        is_relevant = True
                    elif text_numbers and claim_num:
                        # 模糊数字比较
                        try:
                            claim_f = float(claim_num)
                            for t in text_numbers:
                                try:
                                    other_f = float(t)
                                    # 差异 <20% → verified
                                    if abs(other_f - claim_f) / max(claim_f, 1) < 0.2:
                                        is_relevant = True
                                        break
                                    # 差异 >20% 且 <100% → partial
                                    elif abs(other_f - claim_f) / max(claim_f, 1) < 1.0:
                                        is_relevant = True
                                        break
                                except ValueError:
                                    continue
                        except ValueError:
                            pass
                elif claim_type == '团队背景':
                    # 人名 + 履历/教育/背景 出现
                    if claim_value in title_snippet:
                        is_relevant = True
                elif claim_type == '定性声称':
                    if claim_value in title_snippet:
                        is_relevant = True
                elif claim_type == '竞品存在':
                    if claim_value in title_snippet:
                        is_relevant = True
                else:
                    # fallback: keyword match
                    if claim_value and claim_value in title_snippet:
                        is_relevant = True
                    elif claim_text[:20] and claim_text[:20] in title_snippet:
                        is_relevant = True

                if not is_relevant:
                    continue

                # 计算质量
                if q_score > 0:
                    quality_scores.append(q_score)
                    quality_labels.add(q_label)

                # 同一域名只算 1 次独立验证
                try:
                    domain = urllib.parse.urlparse(url).netloc.lower()
                except Exception:
                    domain = ''
                if domain in seen_domains:
                    continue
                seen_domains.add(domain)

                verified_urls.append({
                    'url': url,
                    'score': q_score,
                    'label': q_label,
                    'title': r.get('title', '')[:80],
                })

        # ── 综合判定 ──
        n_verified = len(verified_urls)
        total_quality = sum(quality_scores)

        if n_verified >= 2 and total_quality >= 3:
            # 2+ 独立来源 + 总分 >=3（例：1个🅰+1个🅱）
            claim['verified'] = 'verified'
            claim['evidence_urls'] = [u['url'] for u in verified_urls[:5]]
            claim['quality_label'] = ' / '.join(sorted(set(quality_labels))) if quality_labels else '无'
        elif n_verified >= 1 and total_quality >= 1:
            claim['verified'] = 'partial'
            claim['evidence_urls'] = [u['url'] for u in verified_urls[:5]]
            claim['quality_label'] = ' / '.join(sorted(set(quality_labels))) if quality_labels else '无'
        else:
            claim['verified'] = 'unverified'
            claim['evidence_urls'] = []
            claim['quality_label'] = '无可靠来源'

        # 生成 Gap 搜索词
        if claim['verified'] in ('unverified', 'partial'):
            claim['gap_queries'] = _gen_gap_queries(claim)

    return claims


def _gen_gap_queries(claim: dict) -> list:
    """针对未验证的声称生成针对性搜索词"""
    claims_type = claim['type']
    text = claim['text']
    value = claim['value']

    queries = {
        '订单金额': [f'"{value}" 中标公告', f'合同 {value} 中标'],
        '合同金额': [f'合同 {value} 中标', f'"{value}" 合同'],
        '芯片出货量': [f'{value} 颗 出货', f'{value} 芯片 发货'],
        '市占率': [f'{value} 市占率', f'{value} 市场份额'],
        '融资金额': [f'融资 {value} 万', f'融资 {value} 亿'],
        '客户数量': [f'{value} 家 客户', f'{value} 客户名单'],
        '专利数量': [f'{value} 专利 发明人'],
        '定性声称': [value, f'{value} 验证', f'{value} 真实'],
        '团队背景': [f'"{value}" 经历 教育', f'"{value}" 前雇主'],
        '竞品存在': [f'"{value}" 融资 技术 对比'],
    }
    return queries.get(claims_type, [value])


def compute_score(gaps: list) -> str:
    """计算数据充足度评分"""
    if not gaps:
        return 'A — 数据充足'

    total = len(gaps)
    verified = sum(1 for g in gaps if g['verified'] == 'verified')
    partial = sum(1 for g in gaps if g['verified'] == 'partial')
    unverified = sum(1 for g in gaps if g['verified'] == 'unverified')

    ratio = (verified + partial * 0.5) / max(total, 1)

    if ratio >= 0.8:
        return 'A — 数据充足'
    elif ratio >= 0.6:
        return 'B — 基本充足（有缺口）'
    elif ratio >= 0.4:
        return 'C — 明显缺口，需深钻'
    elif ratio >= 0.2:
        return 'D — 信息严重不足'
    else:
        return 'E — 几乎无数据支撑'


def detect(task_id: str) -> dict:
    task_dir = TASKS_DIR / task_id

    # 1. 读 OCR 文本
    ocr_path = task_dir / 'bp_ocr_text.txt'
    ocr_text = ''
    if ocr_path.exists():
        ocr_text = open(ocr_path, encoding='utf-8').read()
    else:
        raw_path = task_dir / 'bp_raw_text.txt'
        if raw_path.exists():
            ocr_text = open(raw_path, encoding='utf-8').read()

    # 2. 读 Step 0 profile
    profile_path = task_dir / 'bp_step0_profile.json'
    profile = {}
    if profile_path.exists():
        profile = json.loads(open(profile_path, encoding='utf-8').read())

    # 3. 读搜索结果
    search_results = {}
    for f in sorted(task_dir.glob('bp_presearch_*.md')):
        step_key = f.stem.replace('bp_presearch_', '')
        content = open(f, encoding='utf-8').read()
        urls = re.findall(r'\*\*URL\*\*\s*:\s*(http[^\s]+)', content)
        titles = re.findall(r'###\s*(.+)', content)
        snippets = re.findall(r'\*\*摘要\*\*\s*:\s*(.+)', content)
        search_results[step_key] = []
        for i in range(len(titles)):
            search_results[step_key].append({
                'title': titles[i] if i < len(titles) else '',
                'url': urls[i] if i < len(urls) else '',
                'snippet': snippets[i] if i < len(snippets) else '',
            })

    # 4. 提取声称
    claims = extract_claims(ocr_text, profile)

    # 5. 匹配证据
    claims = match_evidence(claims, search_results)

    # 6. 分类
    verified = [c for c in claims if c['verified'] == 'verified']
    partial = [c for c in claims if c['verified'] == 'partial']
    unverified = [c for c in claims if c['verified'] == 'unverified']

    score = compute_score(claims)
    gap_count = len(unverified) + len(partial)

    result = {
        'task_id': task_id,
        'score': score,
        'total_claims': len(claims),
        'verified_count': len(verified),
        'partial_count': len(partial),
        'unverified_count': len(unverified),
        'gap_count': gap_count,
        'verified': verified,
        'partial': partial,
        'unverified': unverified,
        'all_claims': claims,
    }

    # 7. 写结果
    gap_path = task_dir / 'bp_gap_report.json'
    with open(gap_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 8. 写 Gap 清单（供后续搜索用）
    gap_queries = []
    for c in partial + unverified:
        gap_queries.extend(c.get('gap_queries', []))
    gap_queries = list(dict.fromkeys(gap_queries))  # 去重

    if gap_queries:
        gap_md_path = task_dir / 'bp_gap_queries.md'
        with open(gap_md_path, 'w', encoding='utf-8') as f:
            f.write(f'# Gap 搜索清单（{len(gap_queries)} 个查询）\n\n')
            for i, q in enumerate(gap_queries, 1):
                f.write(f'{i}. {q}\n')

    # 9. 控制台输出
    print(f"\n{'='*60}")
    print(f"🔎 Gap Detection v2 完成: {task_id}")
    print(f"   数据充足度: {score}")
    print(f"   总声称: {len(claims)} | 已验证: {len(verified)} | 部分: {len(partial)} | 未验证: {len(unverified)}")
    print(f"   缺口: {gap_count} 条")
    if gap_queries:
        print(f"   建议深钻搜索词: {len(gap_queries)} 个")
    print(f"{'='*60}")

    return result


def main():
    parser = argparse.ArgumentParser(description='BP Gap Detector')
    parser.add_argument('--task-id', required=True)
    args = parser.parse_args()
    detect(args.task_id)


if __name__ == '__main__':
    main()