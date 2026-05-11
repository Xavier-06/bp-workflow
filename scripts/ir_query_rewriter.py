#!/usr/bin/env python3
"""
IR 研报管线 — LLM 查询改写器

基于 Gap Detector 输出的缺口清单 + 已有证据摘要，生成智能补充搜索词。
策略：逆向验证、同业类比、供应链/上下游验证、官方渠道补查、数据口径校验。

用法：
  python3 scripts/ir_query_rewriter.py --task-id TASK-XXX --entity "英伟达"
  python3 scripts/ir_query_rewriter.py --task-id TASK-XXX --entity "英伟达" --max-new 12
  python3 scripts/ir_query_rewriter.py --task-id TASK-XXX --entity "英伟达" --include-snippets
"""
from __future__ import annotations
import argparse
import json
import os
import re
import ssl
import time
import urllib.request
from pathlib import Path

os.environ.setdefault('SSL_CERT_FILE', '/opt/homebrew/etc/openssl@3/cert.pem')
os.environ.setdefault('REQUESTS_CA_BUNDLE', '/opt/homebrew/etc/openssl@3/cert.pem')

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / 'data' / 'tasks'
CRED_FILE = WORKSPACE / '.credentials' / 'investment-research.env'
CERT_FILE = '/opt/homebrew/etc/openssl@3/cert.pem'

EXTRACT_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'

# 研报查询改写专用 prompt——针对上市公司维度
LLM_REWRITE_SYSTEM = """你是卖方研报高级分析师，擅长发现投研信息盲区并设计高价值搜索查询。

研报写作覆盖以下核心维度：
1. 行情与基础数据（股价/市值/PE/分析师共识）
2. 行业与市场格局（规模/增速/竞争对手/市占率）
3. 商业模式与盈利能力（收入结构/毛利率/护城河/客户）
4. 财务分析与趋势（营收/利润/现金流/资产负债/ROE）
5. 管理层与股权结构（高管/治理/大股东/回购减持）
6. 差异化洞察与非共识（催化剂/被低估/市场盲点/做空）
7. 风险与催化剂（下行风险/监管/竞争威胁/解禁）
8. 估值与投资建议（DCF/可比公司/目标价/评级）

搜索词设计原则：
1. **逆向验证** — 不仅搜看多证据，也搜质疑/做空逻辑/争议
2. **同业类比** — 搜同业公司数据推断标的可能的情况
3. **供应链/上下游验证** — 供应商/客户/合作伙伴是否真实合作
4. **官方渠道补查** — 年报/公告/SEC/HKEX/巨潮/交易所
5. **数据口径校验** — 同一指标用不同关键词交叉验证
6. **时间序列** — 搜最新数据覆盖旧数据
7. **市场情绪** — 搜投资者社区/做空报告/机构持仓变化
8. **中文为主**：搜索词以中文为主，辅以英文专业术语

不要重复已有的查询词。不要搜教科书理论，搜实际的公司数据/事件。
输出纯搜索词列表，每行一个。
"""


def _load_api_key() -> str:
    if CRED_FILE.exists():
        for line in CRED_FILE.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line.startswith('DASHSCOPE_API_KEY=') and not line.startswith('DASHSCOPE_API_KEY_'):
                return line.split('=', 1)[1].strip().strip("'\"")
    return os.environ.get('DASHSCOPE_API_KEY', '').strip("'\"")


def _make_ssl_ctx():
    if Path(CERT_FILE).exists():
        return ssl.create_default_context(cafile=CERT_FILE)
    return ssl.create_default_context()


def _call_llm(prompt: str, api_key: str, temperature: float = 0.5) -> str:
    ctx = _make_ssl_ctx()
    body = json.dumps({
        'model': 'qwen-plus',
        'messages': [
            {'role': 'system', 'content': LLM_REWRITE_SYSTEM},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': temperature,
        'max_tokens': 2048,
        'result_format': 'message',
    }).encode('utf-8')
    req = urllib.request.Request(
        EXTRACT_URL, data=body,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
        method='POST',
    )
    with urllib.request.urlopen(req, context=ctx, timeout=90) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    return data.get('choices', [{}])[0].get('message', {}).get('content', '')


def _parse_queries(content: str) -> list[str]:
    """从 LLM 输出提取查询列表"""
    cleaned = content.strip()
    # 去掉 markdown 代码块
    for block in re.findall(r'```(?:\w+)?\s*\n(.*?)\n```', cleaned, re.DOTALL):
        cleaned = block
        break
    queries = []
    for line in cleaned.split('\n'):
        line = line.strip().lstrip('-•*0123456789.').strip()
        if line and len(line) > 3 and not line.startswith('#') and not line.startswith('{'):
            queries.append(line)
    return queries


# ── 规则 fallback────────────────

STRATEGY_TEMPLATES = {
    'step1_data': [
        '{entity} 最新 股价 市值 PE PB {year}',
        '{entity} analyst consensus rating target price {year}',
        '{entity} 分析师 目标价 买入 卖出 评级 数量',
        '{entity} 分红 回购 金额 {year} {prev_year}',
    ],
    'step2_industry': [
        '{entity} 行业 市场规模 增速 预测 {year}',
        '{entity} 竞争对手 市占率 对比',
        '{entity} peer comparison market share ranking',
        '{entity} 行业政策 政府支持 补贴 {year}',
    ],
    'step3_business': [
        '{entity} 收入 业务 占比 分部 {year}',
        '{entity} 护城河 竞争 优势 壁垒',
        '{entity} 客户 集中度 前五大 依赖',
        '{entity} pricing power gross margin trend',
    ],
    'step4_finance': [
        '{entity} 年报 营收 净利润 现金流 {prev_year} {year}',
        '{entity} free cash flow ROE ROIC trend 3 year',
        '{entity} 资产负债率 债务 短期 长期 {prev_year}',
        '{entity} 财务造假 质疑 审计 保留意见',
    ],
    'step5_mgmt': [
        '{entity} 管理层 变动 CEO CFO 离职',
        '{entity} 大股东 减持 增持 限售 解禁',
        '{entity} 股权激励 RSU 期权 员工持股',
        '{entity} corporate governance board independence',
    ],
    'step6_insight': [
        '{entity} 被低估 催化剂 非共识 看多',
        '{entity} short interest 做空 比例 {year}',
        '{entity} market blind spot overlooked',
        '{entity} 机构 持仓 变化 北向 南向',
    ],
    'step6b_valuation': [
        '{entity} DCF 估值 WACC 终值 敏感性分析',
        '{entity} 可比公司 PE PB PS EV/EBITDA 估值倍数',
        '{entity} analyst consensus target price {year}',
        '{entity} 估值 目标价 盈利预测 收入预测',
    ],
    'step7_risk': [
        '{entity} 风险 监管 诉讼 处罚 调查',
        '{entity} 竞争 威胁 替代 降价',
        '{entity} 解禁 减持 稀释 配股',
        '{entity} bear case downside scenario risk',
    ],
    'step8_master': [
        '{entity} DCF 估值 可比公司 PE PB 同业',
        '{entity} target price recommendation buy sell hold',
        '{entity} 券商 研报 深度 评级',
    ],
    'verification': [
        '{entity} annual report site:sec.gov',
        '{entity} annual results site:hkexnews.hk',
        '{entity} 年报 site:cninfo.com.cn',
        '{entity} earnings call transcript',
    ],
}


def _rule_based_rewrite(missing_dims: list[str], entity: str = '', max_n: int = 12) -> list[str]:
    """规则 fallback——按维度模板生成搜索词"""
    import datetime
    year = datetime.datetime.now().year
    prev_year = year - 1
    queries = []
    for dim in missing_dims:
        templates = STRATEGY_TEMPLATES.get(dim, [])
        for tmpl in templates[:3]:
            q = tmpl.format(entity=entity, year=year, prev_year=prev_year)
            if q:
                queries.append(q)
    # 去重去短
    seen = set()
    deduped = []
    for q in queries:
        ql = q.lower()
        if q not in seen and len(q) > 5:
            seen.add(ql)
            deduped.append(q)
    return deduped[:max_n]


def rewrite(
    task_id: str,
    entity: str = '',
    market: str = 'us',
    max_new: int = 12,
    include_snippets: bool = False,
) -> dict:
    # 1. 读 Gap 报告
    gap_path = TASKS_DIR / f'{task_id}-ir_gap_report.json'
    if not gap_path.exists():
        # 先跑 Gap Detector
        print("⚠ Gap 报告不存在，先跑 ir_gap_detector...")
        if entity:
            from ir_gap_detector import detect
            detect(task_id, entity, market)
        else:
            print("❌ 需要提供 --entity 参数")
            return {'error': 'gap_report_not_found, run ir_gap_detector first'}
    
    gap_data = json.loads(gap_path.read_text(encoding='utf-8'))
    dimensions = gap_data.get('dimensions', {})
    
    # 找出缺口维度
    missing_dims = []
    for dim_key, dim_val in dimensions.items():
        if dim_val.get('status') in ('missing', 'weak', 'partial'):
            missing_dims.append(dim_key)
    
    if not missing_dims:
        print("✅ 所有维度已覆盖，无需改写查询")
        return {'status': 'all_covered', 'queries': []}
    
    # 收集已有证据 URL 和摘要
    existing_queries = gap_data.get('gap_queries', [])
    
    # 构建证据摘要
    evidence_snippets = []
    if include_snippets:
        # 从预搜索文件读取证据摘要
        for pf in sorted(TASKS_DIR.glob(f'{task_id}-search-step*.md')):
            text = pf.read_text(encoding='utf-8')
            # 提取 memo 部分（前 300 字符）
            memo_start = text.find('## Search Memo')
            if memo_start >= 0:
                memo_end = text.find('## Citations', memo_start)
                if memo_end < 0:
                    memo_end = memo_start + 1000
                snippet = text[memo_start:memo_end].strip()[:500]
                if snippet:
                    evidence_snippets.append(f"--- {pf.name} ---\n{snippet}")
    
    # LLM 改写
    api_key = _load_api_key()
    if not api_key:
        print("⚠ 无 DASHSCOPE_API_KEY，使用规则 fallback")
        new_queries = _rule_based_rewrite(missing_dims, entity, max_new)
    else:
        dim_summary = '\n'.join(
            f"- {dimensions[d].get('name', d)} (状态: {dimensions[d].get('status')}, "
            f"关键词覆盖: {dimensions[d].get('keyword_coverage', 'N/A')})"
            for d in missing_dims
        )
        prompt = f"""目标公司：{entity}
市场：{market}

当前缺口维度（{len(missing_dims)}个）：
{dim_summary}

已有证据 URL（{len(existing_queries)} 条）：
"""
        for i, q in enumerate(existing_queries[:10], 1):
            prompt += f"- {q}\n"
        
        if evidence_snippets:
            prompt += f"\n已有证据摘要：\n"
            for s in evidence_snippets[:3]:
                prompt += s[:400] + '\n'
        
        prompt += f"""
请针对以上缺口维度，设计 {max_new} 个高质量搜索词。
要求：
- 覆盖所有缺口维度
- 包含逆向验证、同业类比、上下游验证策略
- 具体、可搜索、不泛泛而谈
"""
        try:
            content = _call_llm(prompt, api_key)
            new_queries = _parse_queries(content)
        except Exception as e:
            print(f"⚠ LLM 改写失败 ({e})，使用规则 fallback")
            new_queries = _rule_based_rewrite(missing_dims, entity, max_new)
    
    # 去重
    existing_lower = {q.lower() for q in existing_queries}
    deduped = []
    for q in new_queries:
        if q.lower() not in existing_lower and len(q) > 3:
            deduped.append(q)
            existing_lower.add(q.lower())
    
    # 写输出
    output = {
        'task_id': task_id,
        'entity': entity,
        'market': market,
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'missing_dimensions': missing_dims,
        'new_queries': deduped[:max_new],
        'total_new': len(deduped),
    }
    
    out_path = TASKS_DIR / f'{task_id}-ir_rewritten_queries.json'
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # 更新 gap queries md
    gap_md_path = TASKS_DIR / f'{task_id}-ir_gap_queries.md'
    existing_lines = []
    if gap_md_path.exists():
        existing_lines = gap_md_path.read_text(encoding='utf-8').split('\n')
    
    md_lines = ['# IR 补充搜索清单（LLM 改写）', '']
    md_lines.append(f'- Task ID: {task_id}')
    md_lines.append(f'- Entity: {entity}')
    md_lines.append(f'- 缺口维度: {len(missing_dims)}')
    md_lines.append(f'- 新查询: {len(deduped)}')
    md_lines.append('- ' + time.strftime('%Y-%m-%d %H:%M'))
    md_lines.append('')
    md_lines.append('## 缺口维度')
    md_lines.append('')
    for d in missing_dims:
        dim_name = dimensions.get(d, {}).get('name', d)
        dim_status = dimensions.get(d, {}).get('status', 'unknown')
        md_lines.append(f'- {dim_name} ({dim_status})')
    md_lines.append('')
    md_lines.append('## 新搜索词')
    md_lines.append('')
    for i, q in enumerate(deduped[:max_new], 1):
        md_lines.append(f'{i}. {q}')
    gap_md_path.write_text('\n'.join(md_lines) + '\n', encoding='utf-8')
    
    # 打印
    print(f"\n{'='*60}")
    print(f"🔄 IR Query Rewriter 完成: {task_id}")
    print(f"   缺口维度: {len(missing_dims)}")
    print(f"   新搜索词: {len(deduped)}")
    print(f"")
    for i, q in enumerate(deduped[:max_new], 1):
        print(f"   {i}. {q}")
    print(f"{'='*60}")
    
    return output


def main():
    ap = argparse.ArgumentParser(description='IR 研报管线 — LLM 查询改写器')
    ap.add_argument('--task-id', required=True, help='Task ID')
    ap.add_argument('--entity', default='', help='Entity name')
    ap.add_argument('--market', default='us', help='Market (us/hk/cn)')
    ap.add_argument('--max-new', type=int, default=12, help='最大新查询数')
    ap.add_argument('--include-snippets', action='store_true',
                     help='包含已有证据摘要供 LLM 参考')
    args = ap.parse_args()

    rewrite(args.task_id, args.entity, args.market, args.max_new, args.include_snippets)


if __name__ == '__main__':
    main()
