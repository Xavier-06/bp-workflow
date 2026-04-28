#!/usr/bin/env python3
"""
BP 尽调 Pre-Search v3 — 基于 Step 0 的搜索靶心执行全网搜索
零 API 费用：SearXNG + DDG + Scrapling

用法：
  python3 scripts/bp_presearch.py --task-id TASK-XXX

前置依赖：
  tasks/TASK-XXX/bp_step0_profile.json

修复（2026-04-01）：
  - 修复搜索词生成逻辑：不再用噪音词
  - 新增：知网、Web of Science、行业协会白皮书搜索
  - 新增：竞对研发/专利布局搜索
  - 新增：对标公司搜索（使用 Step 0 提取的直接竞品）
"""
import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / 'tasks'
SCRIPTS_DIR = WORKSPACE / 'scripts'

sys.path.insert(0, str(SCRIPTS_DIR))
try:
    from query_expander import expand_for_bp, expand_query
except ImportError:
    expand_for_bp = lambda p: []
    expand_query = lambda q, e="", m="full": []

try:
    sys.path.insert(0, str(SCRIPTS_DIR))
    from search_gateway import search as do_search
except ImportError:
    # Fallback: 直接调 searxng_search + ddgs (向后兼容)
    try:
        from searxng_search import search as _searx_search
        def do_search(query: str, max_results: int = 8) -> list:
            try:
                return _searx_search(query, max_results=max_results, timeout=25)
            except Exception:
                pass
            return []
    except ImportError:
        def do_search(query: str, max_results: int = 8) -> list:
            return []


# ── 噪音词过滤 ──
NOISE_WORDS = [
    '报价', '交付拖期', '部门', '职责',
    '和独特', '我们的优势',
]

# 域名黑名单：搜到高价值但信噪比太低的来源直接丢弃
DOMAIN_BLACKLIST = [
    'guba.eastmoney.com',       # 东方财富股吧
    'zhihu.com/question',       # 知乎问答（非专栏）
    'zhidao.baidu.com',         # 百度知道
    'wenda.so.com',             # 360 问答
    'wenwen.sogou.com',         # 搜狗问问
    'tieba.baidu.com',          # 贴吧
    'weibo.com',                # 微博（噪音太大）
    'douyin.com',               # 抖音
]


def _is_blacklisted(url: str) -> bool:
    """检查 URL 是否在域名黑名单中"""
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or ''
        host_lower = host.lower()
        return any(bl in host_lower for bl in DOMAIN_BLACKLIST)
    except Exception:
        return False


def is_noise(token: str) -> bool:
    t = token.strip().lower()
    if len(t) < 2:
        return True
    if any(n in t for n in NOISE_WORDS):
        return True
    return False


def clean_keywords(kws: list) -> list:
    return [k.strip() for k in kws if not is_noise(k) and len(k.strip()) > 1]


def generate_queries(profile: dict) -> dict:
    company = profile.get('company_name', '')
    if company in ('未识别', ''):
        company = ''
    founders = clean_keywords(profile.get('founders', []))
    products = clean_keywords(profile.get('products', []))
    tech_kws = clean_keywords(profile.get('tech_keywords', []))
    competitors = profile.get('competitors', {})
    direct_comps = clean_keywords(competitors.get('direct', []))
    stage = profile.get('stage', '')
    mode = profile.get('manufacturing_mode', '')
    value_chain = profile.get('value_chain', '')

    queries = {}

    # ── Step 2：团队与合规 ──
    q_team = []
    for name in founders[:5]:
        q_team.append(f'"{name}" 创始人 OR CEO OR CTO OR 总经理')
        q_team.append(f'"{name}" 纠纷 OR 诉讼 OR 失信 OR 被执行')
        q_team.append(f'"{name}" 履历 OR 背景 OR 教育')
    if company:
        q_team.append(f'"{company}" 法律诉讼 OR 行政处罚 OR 经营异常')
        q_team.append(f'"{company}" 股权 OR 股东 OR 实控人 变更')
    queries['step2_team_compliance'] = q_team

    # ── Step 1：护城河锚定 ──
    q_moat = []
    if company:
        q_moat.append(f'"{company}" 核心竞争力 OR 护城河 OR 壁垒')
    # 只搜具体技术名，不搜碎片词
    real_techs = [t for t in tech_kws if len(t) > 3 and any(c.isalnum() for c in t)]
    for tech in real_techs[:3]:
        q_moat.append(f'"{tech}" 技术壁垒 OR 专利 OR 核心')
        q_moat.append(f'"{tech}" 替代技术 OR 被淘汰')
    queries['step1_moat_anchor'] = q_moat

    # ── Step 3：技术与产品 ──
    q_tech = []
    # 产品验证（招投标/客户）
    for prod in products[:3]:
        q_tech.append(f'"{prod}" 招投标 OR 中标 OR 采购 公示')
        q_tech.append(f'"{prod}" 客户 OR 用户 OR 反馈')
    # 学术/专利搜索（知网、Google Scholar、CNIPA、Google Patents）
    for kw in (real_techs[:5] or products[:2]):
        q_tech.append(f'"{kw}" site:scholar.google.com')
        q_tech.append(f'"{kw}" 学术论文 OR 研究 OR 论文')
        q_tech.append(f'"{kw}" 专利 site:cpquery.cponline.cnipa.gov.cn')
        q_tech.append(f'"{kw}" 专利 site:patents.google.com')
    # 中国软著搜索
    if company:
        q_tech.append(f'"{company}" 软著 OR 软件著作权')
        q_tech.append(f'"{company}" 商标 site:sbj.cnipa.gov.cn')
    queries['step3_tech_product'] = q_tech

    # ── Step 4：行业与供应链 ──
    q_ind = []
    # 行业报告/白皮书
    if mode:
        q_ind.append(f'{mode} 市场规模 2024 2025 第三方报告')
        q_ind.append(f'{mode} 行业白皮书 OR 技术路线图')
    if stage:
        q_ind.append(f'{"ERP MES" if "ERP" in mode else mode} 创业公司 OR 融资 OR 估值')
        q_ind.append(f'{"ERP MES" if "ERP" in mode else mode} 公司 融资 2024 2025')
    if company:
        q_ind.append(f'"{company}" 供应商 OR 合作伙伴 OR 渠道')
        q_ind.append(f'"{company}" 客户 列表 OR 案例')
    # 行业协会/白皮书
    q_ind.append(f'{"工业软件" if "ERP" in mode else mode} 行业 白皮书 OR 研究报告')
    queries['step4_industry_supply'] = q_ind

    # ── Step 5：竞争与对标 ──
    q_comp = []
    # 直接竞品对比
    for comp in direct_comps[:5]:
        # 过滤过长的赛道描述
        if len(comp) > 30:
            continue
        q_comp.append(f'"{comp}" 竞品 OR 同类 OR 市场份额')
        q_comp.append(f'"{comp}" 融资 OR 估值 OR 客户')
    # 如果没提取到具体竞争对手，用模式+赛道搜索
    if not any(len(c) <= 30 for c in direct_comps):
        if company:
            q_comp.append(f'"{company}" 竞争对手 OR 竞品 OR 市场份额')
        if mode:
            q_comp.append(f'{mode} 竞争对手 OR 竞品 OR 行业排名')
            q_comp.append(f'{mode} 对比 OR 比较 OR 哪家')
    # 巨头布局/跨界威胁
    q_comp.append(f'{"工业软件" if "ERP" in mode else mode} 巨头 OR 跨界 OR 新进入者')
    queries['step5_competition_conclusion'] = q_comp

    return queries


def run(task_id: str):
    task_dir = TASKS_DIR / task_id
    profile_path = task_dir / 'bp_step0_profile.json'
    if not profile_path.exists():
        print(f'❌ 未找到 {profile_path}，先运行 bp_preflight_check.py', file=sys.stderr)
        sys.exit(1)

    with open(profile_path, 'r', encoding='utf-8') as f:
        profile = json.load(f)

    company = profile.get('company_name', '')
    print(f'📡 BP Pre-Search: {task_id} ({company})')
    print(f'   创始人: {", ".join(profile.get("founders", [])[:3])}')
    print(f'   产品: {", ".join(profile.get("products", [])[:3])}')
    print(f'   技术: {", ".join(profile.get("tech_keywords", [])[:5])}')
    print(f'   对标: {", ".join(profile.get("competitors", {}).get("direct", [])[:3])}')
    print()

    queries = generate_queries(profile)

    # ── 查询扩展：在模板查询基础上加智能变体 ──
    extra_q = expand_for_bp(profile)
    if extra_q:
        existing = set()
        for qs in queries.values():
            existing.update(qs)
        deduped = [q for q in extra_q if q not in existing][:15]
        if deduped:
            queries['step6_expanded_queries'] = deduped
            print(f'  🔄 查询扩展：模板查询 + {len(deduped)} 个智能变体')
    all_results = {}
    total_q = sum(len(v) for v in queries.values())
    total_r = 0
    q_idx = 0

    for step_key, step_qs in queries.items():
        step_results = []
        print(f'── {step_key} ({len(step_qs)} 搜索词) ──')

        for q in step_qs:
            q_idx += 1
            print(f'  [{q_idx}/{total_q}] {q[:70]}...', end=' ')
            results = do_search(q, max_results=8)
            print(f'→ {len(results)} 条')

            seen = set()
            for r in results:
                url = r.get('url', r.get('href', ''))
                if url in seen or _is_blacklisted(url):
                    continue
                seen.add(url)
                step_results.append({
                    'query': q,
                    'title': r.get('title', ''),
                    'url': url,
                    'snippet': r.get('content', r.get('body', ''))[:500],
                    'source': r.get('source', ''),
                })

            total_r += len(results)
            time.sleep(0.3)

        all_results[step_key] = step_results

        # 写 Markdown
        md = [f'# BP 搜索 — {step_key}', '',
              f'**任务**: {task_id}', f'**时间**: {datetime.now().isoformat()}',
              f'**搜索词**: {len(step_qs)} | **命中**: {len(step_results)}', '']
        for r in step_results:
            md.append(f'### {r["title"]}')
            md.append(f'- **URL**: {r["url"]}')
            md.append(f'- **来源查询**: {r["query"]}')
            md.append(f'- **摘要**: {r["snippet"][:300]}')
            md.append('')

        md_path = task_dir / f'bp_presearch_{step_key}.md'
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(md))
        print(f'  → {md_path}\n')

    # 总结果
    summary = {
        'task_id': task_id,
        'created_at': datetime.now().isoformat(),
        'total_queries': total_q,
        'total_results': total_r,
        'results_by_step': {k: len(v) for k, v in all_results.items()},
    }
    with open(task_dir / 'bp_presearch_results.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f'✅ Pre-Search 完成')
    print(f'   搜索词: {total_q} | 命中: {total_r}')
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task-id', required=True)
    args = parser.parse_args()
    run(args.task_id)


if __name__ == '__main__':
    main()


# ── 查询扩展（对接 query_expander） ──
try:
    from query_expander import expand_for_bp
    from query_expander import expand_query
    _HAS_EXPANDER = True
except ImportError:
    _HAS_EXPANDER = False
    expand_for_bp = lambda p: []
    expand_query = lambda q, e="", m="full": []


def expand_queries_with_ai(profile: dict, existing_queries: dict) -> list[str]:
    """用 query_expander 扩展 presearch 查询，补充模板外的盲区"""
    if not _HAS_EXPANDER:
        return []
    
    expanded = expand_for_bp(profile)
    
    # 去重：已有的不重复
    existing_set = set()
    for qs in existing_queries.values():
        for q in qs:
            existing_set.add(q)
    
    new_q = [q for q in expanded if q not in existing_set]
    return new_q[:15]  # 最多补 15 个


