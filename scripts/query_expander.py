#!/usr/bin/env python3
"""
查询扩展器 v2 — 把 1 个查询扩展成 5-10 个不同角度的变体

对标 Perplexity Deep Research 的查询改写策略：
1. 规则扩展（引号/同义词/时间/官源/dir/竞品对比）
2. LLM 智能改写（基于已有证据盲区分析）

用法：
  from query_expander import expand_for_bp, llm_rewrite_queries
  queries = expand_for_bp(profile)
  new_queries = llm_rewrite_queries(base_queries, evidence_urls, entity="公司名")
"""
import json
import os
import re
import ssl
import time
import urllib.request
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
CRED_FILE = WORKSPACE / '.credentials' / 'investment-research.env'
CERT_FILE = '/opt/homebrew/etc/openssl@3/cert.pem'

SYN_MAP = {
    '核心': ['关键', '主要', '基础'],
    '竞争力': ['优势', '护城河', '壁垒'],
    '技术': ['工艺', '架构', '方案'],
    '客户': ['用户', '甲方', '采购方'],
    '市场': ['行业', '赛道', '领域'],
}

def _expand_query(query: str, mode: str = "full") -> list:
    results = [query]
    # 精确匹配
    if len(query) > 3 and '"' not in query:
        results.append(f'"{query}"')
    # 同义词扩展
    for word, syns in SYN_MAP.items():
        if word in query:
            for s in syns[:2]:
                v = query.replace(word, s, 1)
                if v != query: results.append(v)
            break
    # 时间扩展
    if mode in ("full", "time"):
        results.append(f"{query} 2024")
        results.append(f"{query} 2025")
        results.append(f"{query} 2026")
    if mode == "full":
        results.append(f'{query} site:gov.cn')
        results.append(f'{query} site:cnipa.gov.cn')
        results.append(f'{query} 招投标 中标 公示')
        results.append(f'{query} 竞品 OR 对比 OR 评价')
    return results[:8]


def expand_for_bp(profile: dict) -> list:
    company = profile.get('company_name', '')
    if not company or company in ('未识别', '', '未知'):
        return []
    all_q = []
    all_q.extend(_expand_query(company))
    for name in profile.get('founders', [])[:3]:
        if len(name) > 1 and name not in ('未识别', ''):
            all_q.extend(_expand_query(f'{name} 创始人'))
            all_q.append(f'"{name}" 纠纷 OR 诉讼')
    for prod in profile.get('products', [])[:3]:
        if prod and prod not in ('未识别', ''):
            all_q.extend(_expand_query(prod))
    for tech in profile.get('tech_keywords', [])[:3]:
        if tech and tech not in ('未识别', ''):
            all_q.extend(_expand_query(tech))
    for comp in profile.get('competitors', {}).get('direct', [])[:3]:
        if comp and len(comp) < 30:
            all_q.extend(_expand_query(comp))
    mode = profile.get('manufacturing_mode', '')
    if mode:
        all_q.extend(_expand_query(f'{mode} 行业'))
    return list(dict.fromkeys(all_q))


# ── LLM 查询改写（v2：修复 + 增强） ──

LLM_REWRITE_SYSTEM = """你是资深投研尽调专家，擅长发现信息盲区并设计高价值搜索查询。

你的任务：分析已有的证据库，判断还缺什么信息，然后设计搜索词来填补盲区。

搜索词设计原则：
1. **逆向验证** - 不仅搜"支持"的证据，也搜"质疑/反驳"的证据
2. **类比搜索** - 搜类似技术/商业模式的其他公司，推断目标公司可能的情况
3. **关键人物搜索** - 创始人/核心成员的过往履历、诉讼、纠纷
4. **官方渠道补查** - 政府公示、专利、诉讼文书、招投标
5. **供应链验证** - 上游供应商、下游客户是否真的合作
6. **竞对对比** - 同赛道玩家的数据对比
7. **行业常识验证** - 行业基准数据验证BP声称是否合理
8. **用中文搜索**：搜索词必须是中文

请针对给定的 gap queries 和已有证据，输出能真正找到新信息的搜索词。
不要重复已有的查询词。
不要搜纯理论/教科书内容，要搜实际的公司/事件/数据。
"""

EXTRACT_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'


def _load_dashscope_key() -> str:
    key = None
    if CRED_FILE.exists():
        with open(CRED_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith('DASHSCOPE_API_KEY=') and not line.startswith('DASHSCOPE_API_KEY_'):
                    raw = line.split('=', 1)[1].strip()
                    key = raw.strip("'\"")
                    break
    if not key:
        key = os.environ.get('DASHSCOPE_API_KEY', '').strip("'\"")
    return key if key else ""


def _make_ssl_ctx() -> ssl.SSLContext:
    if Path(CERT_FILE).exists():
        os.environ['SSL_CERT_FILE'] = CERT_FILE
        return ssl.create_default_context(cafile=CERT_FILE)
    return ssl.create_default_context()


def _parse_json_from_text(content: str) -> list:
    """从LLM输出中提取JSON数组"""
    # 尝试完整解析
    cleaned = content.strip()
    if cleaned.startswith('```'):
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        if m:
            cleaned = m.group(1).strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return [q for q in result if isinstance(q, str)]
        if isinstance(result, dict):
            queries = result.get('queries', result.get('search_terms', result.get('gap_queries', [])))
            if isinstance(queries, list):
                return [q for q in queries if isinstance(q, str)]
    except json.JSONDecodeError:
        pass
    # fallback: 提取每行看起来像查询的
    queries = []
    for line in content.split('\n'):
        line = line.strip().lstrip('-•*').strip()
        if line and len(line) > 3 and not line.startswith('#') and not line.startswith('{'):
            queries.append(line)
    return queries


def llm_rewrite_queries(
    base_queries: list,
    evidence_urls: list = None,
    entity: str = "",
    max_n: int = 8,
    evidence_snippets: list = None,
) -> list:
    """
    基于已有证据盲区，用 LLM 生成补充搜索词。
    
    Args:
        base_queries: 当前 gap 查询列表
        evidence_urls: 已有证据 URL 列表
        entity: 公司名称（帮助LLM聚焦）
        max_n: 最大返回查询数
        evidence_snippets: 关键证据摘要文本（可选，帮助LLM更智能改写）
    
    Returns:
        新搜索词列表
    """
    api_key = _load_dashscope_key()
    if not api_key:
        # fallback: 用规则生成高级查询
        return _rule_based_rewrite(base_queries, entity, max_n)
    
    ctx = _make_ssl_ctx()
    
    # 构建 prompt 上下文
    evidence_summary = ""
    if evidence_urls:
        evidence_summary = f"\n\n已有证据URL（{len(evidence_urls)}个）：\n"
        for u in evidence_urls[:15]:
            evidence_summary += f"- {u}\n"
    
    snippet_summary = ""
    if evidence_snippets:
        snippet_summary = f"\n已有证据摘要：\n"
        total_chars = 0
        for s in evidence_snippets:
            total_chars += len(s)
            if total_chars > 5000:
                snippet_summary += "...(已截断)\n"
                break
            snippet_summary += f"- {s}\n"
    
    base_summary = "\n".join(f"- {q}" for q in base_queries[:20])
    
    prompt = f"""目标公司：{entity}

当前缺口查询（{len(base_queries)}个）：
{base_summary}

{evidence_summary}
{snippet_summary}

请分析以上信息，判断：
1. 还需要验证哪些关键信息（特别是 BP 声称但还没找到的证据）
2. 从哪些角度可能找到突破口
3. 设计 8-12 个高质量的搜索词

要求：
- 每个搜索词用一行输出，纯查询词，不要编号
- 搜索词应包含：逆向验证、类比搜索、供应链验证等策略
- 搜索词要具体，不要泛泛而谈
"""
    
    body = json.dumps({
        'model': 'qwen-plus',
        'messages': [
            {'role': 'system', 'content': LLM_REWRITE_SYSTEM},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.5,
        'result_format': 'message',
    }).encode('utf-8')

    req = urllib.request.Request(
        EXTRACT_URL,
        data=body,
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'Authorization': f'Bearer {api_key}',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
        parsed = _parse_json_from_text(content)
        
        # 去重 + 过滤已有的 base 查询
        existing = set(base_queries)
        new_queries = []
        for q in parsed:
            if q and q not in existing and len(q) > 2:
                new_queries.append(q)
                if len(new_queries) >= max_n:
                    break
        
        return new_queries
    except Exception as e:
        print(f"  ⚠ LLM 改写失败: {e}，使用规则 fallback")
        return _rule_based_rewrite(base_queries, entity, max_n)


def _rule_based_rewrite(queries: list, entity: str = "", max_n: int = 8) -> list:
    """规则 fallback：当 LLM 不可用时"""
    new = []
    # 逆向验证
    for q in queries[:5]:
        new.append(f"{q} 质疑 OR 争议 OR 失败")
    # 供应链
    if entity:
        new.append(f"{entity} 供应商 OR 合作伙伴 OR 客户")
        new.append(f"{entity} 诉讼 OR 纠纷 OR 处罚")
        new.append(f"{entity} 专利 OR 软著 OR 知识产权")
    # 类比搜索
    tech_keywords = ["芯片", "AI", "云计算", "物联网", "机器人"]
    for kw in tech_keywords:
        if kw in str(queries):
            for comp in ["华为", "小米", "百度", "商汤", "旷视", "地平线"]:
                new.append(f"{comp} {kw} 对标")
                break
            break
    # 官渠道
    if entity:
        new.append(f"{entity} site:gov.cn OR site:cnipa.gov.cn")
        new.append(f"{entity} 招投标 site:chinabidding.cn")
    return list(dict.fromkeys(new))[:max_n]


if __name__ == '__main__':
    p = {'company_name': '静远达智', 'founders': ['谢豪律'], 'manufacturing_mode': '芯片'}
    qs = expand_for_bp(p)
    print(f'{len(qs)} 查询:')
    for i, q in enumerate(qs[:15], 1):
        print(f'  {i}. {q}')
    
    print("\nLLM 改写测试:")
    base = ["静远达智 出货量", "静远达智 融资"]
    new = llm_rewrite_queries(base, entity="静远达智")
    for i, q in enumerate(new, 1):
        print(f'  {i}. {q}')
