#!/usr/bin/env python3
"""
BP 尽调 Preflight Check v4 — Step 0 前置判断
从 PDF 提取文本中识别：融资阶段 | 商业模式 | 核心收入 | 价值链 | 对标对象 | 股权结构

2026-04-03 升级：
  1. LLM 结构化提取层（qwen-plus），覆盖正则易错字段
  2. Profile 内容哈希，手动修正后不会被管线覆盖

用法：
  python3 scripts/bp_preflight_check.py --task-id TASK-XXX --pdf-text /path/to/extracted.txt

输出：
  tasks/TASK-XXX/bp_step0_profile.json
  tasks/TASK-XXX/bp_step0_profile.md
"""
import argparse
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from pathlib import Path
from datetime import datetime

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / 'tasks'
CRED_FILE = WORKSPACE / '.credentials' / 'investment-research.env'
CERT_FILE = '/opt/homebrew/etc/openssl@3/cert.pem'

# ── 关键词库 ──
VC_KEYWORDS = ['天使', 'angel', 'pre-a', 'a 轮', 'b 轮', 'seed', 'series a', 'pmf',
               '首发', '验证中', '头部客户测试', 'mvp']
PE_KEYWORDS = ['pre-ipo', 'c 轮', 'd 轮', 'series c', '扩产能', '上市准备', '市占率',
               '股东退出', '分红', '批量交付', '连续盈利', '并购']
LATE_VC = ['产线扩建', '市场推广', '规模化', '商业化落地']

ERP_MES = ['erp', 'mes', 'mrp', 'mro', '制造执行', 'catics', 'bom', '信创适配',
           '参数化建模', 'jit 生产', '数字化工厂', '供应链管理软件', '生产排程']
IDM = ['自有产线', '自建工厂', '全产业链', '垂直整合', 'idm']
FABLESS = ['fabless', '无晶圆', '委外']
PLATFORM = ['平台', 'saas', 'paas', '双边市场']
SERVICE = ['系统集成', 'epc', '总包', '总集成']

TECH_KW = ['核心专利', '自主研发', '技术壁垒', '独有技术']
COST_KW = ['成本优势', '规模效应', '性价比']
SOLN_KW = ['一站式', '交钥匙', '整体方案']
CUST_KW = ['客户资源', '渠道优势', '复购']

VALUE_CHAIN = {
    '上游/研发端': ['研发', '材料', '芯片设计', '算法', '底层技术', '核心技术', '实验室'],
    '中游/生产端': ['制造', '生产', '工艺', '良率', '产线', '组装', '加工'],
    '中游/集成端': ['系统集成', '解决方案', '集成', '总包', '整体方案'],
    '下游/服务端': ['服务', '运维', '售后', '运营', '渠道', '销售', '客户'],
    '平台端': ['平台', '生态', '双边市场', '开放', 'api'],
}

# ── DashScope 调用 ──

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


LLM_EXTRACT_SYSTEM = """你是专业投研分析师。请从以下BP文本中提取结构化信息。

提取以下字段：
1. company_name — 公司全称（中文名）
2. founders — 创始人/联合创始人/核心高管（姓名列表，最多5个）
3. products — 主要产品/服务名称或描述（列表）
4. tech_keywords — 技术关键词、核心技术描述（列表）
5. customers — 已知客户或合作伙伴（列表）
6. stage — 融资阶段（天使/A轮/B轮/C轮/Pre-IPO/PE等）
7. manufacturing_mode — 制造模式（如Fabless/IDM/软件/系统集成/平台等）
8. value_chain — 在产业链中的位置（上游/中游/下游/平台）
9. revenue_sources — 收入来源及占比（格式：[{name, percent}])
10. competitors — 对标公司/竞品（列表）
11. financials — 财务数据：revenu(f'{year}年{amount}元'), funding_ask(融资金额), funding_use(资金用途)
12. equity_structure — 股东及持股比例（格式：[{name, percent}])

注意：
- 创始人名字只提真正的创始团队姓名，不要提取"学金"、"奖学金"、"实验"等垃圾匹配
- 公司名要全称，包含"有限公司"等后缀
- 如果某字段信息不足，用空列表/空字符串/未识表示，不要编造
- 所有字段必须输出，即使为空

输出严格 JSON 格式。"""


def _call_qwen_extract(text: str) -> dict:
    api_key = _load_dashscope_key()
    if not api_key:
        return {}

    ctx = _make_ssl_ctx()
    truncated = text[:15000]
    
    body = json.dumps({
        'model': 'qwen-plus',
        'messages': [
            {'role': 'system', 'content': LLM_EXTRACT_SYSTEM},
            {'role': 'user', 'content': f'请从以下BP文本中提取结构化信息：\n\n{truncated}'},
        ],
        'temperature': 0.1,
        'result_format': 'message',
    }).encode('utf-8')

    req = urllib.request.Request(
        'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
        data=body,
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'Authorization': f'Bearer {api_key}',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=90) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
        return _parse_json_response(content)
    except Exception as e:
        print(f"  ⚠ LLM Preflight 调用失败: {e}，使用正则 fallback")
        return {}


def _parse_json_response(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith('```'):
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        if m:
            cleaned = m.group(1).strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    start = content.find('{')
    end = content.rfind('}')
    if start >= 0 and end > start:
        try:
            return json.loads(content[start:end+1])
        except json.JSONDecodeError:
            pass
    return {}


# ── Profile 哈希（手动修正保护） ──

def _compute_profile_hash(profile: dict) -> str:
    """计算 profile 的 SHA256 哈希（排除运行时字段）"""
    exclude_keys = {'profile_hash', 'status', 'warnings', 'created_at', '_manual_fix_note'}
    filtered = {k: v for k, v in sorted(profile.items()) if k not in exclude_keys}
    return hashlib.sha256(json.dumps(filtered, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def _is_manually_fixed(task_dir: Path) -> bool:
    """检测 profile 是否被手动修正过"""
    profile_path = task_dir / 'bp_step0_profile.json'
    if not profile_path.exists():
        return False
    
    with open(profile_path, encoding='utf-8') as f:
        profile = json.load(f)
    
    # 方法1：状态标记
    if profile.get('status') == 'preflight_passed_manual_fix':
        return True
    
    # 方法2：内容哈希不一致
    current_hash = _compute_profile_hash(profile)
    stored_hash = profile.get('profile_hash', '')
    if stored_hash and current_hash != stored_hash:
        return True
    
    return False


# ── 正则提取函数 ──

def _extract_founders(text: str) -> list:
    """行级别创始人/核心人物提取，避免跨行垃圾匹配"""
    results = []
    common_surnames = set("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻水云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅卞齐元康伍余卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚成")

    for line in text.split('\n'):
        line = line.strip()
        if len(line) > 400 or len(line) < 3:
            continue
        if '---' in line:
            continue

        m = re.search(r'创始人\s*([\u4e00-\u9fa5]{2,3})', line)
        if m:
            name = m.group(1)
            if name != '通信' and name not in results:
                results.append(name)
            continue

        for match in re.finditer(r'([\u4e00-\u9fa5]{2,3})[博学]士', line):
            name = match.group(1)
            before_start = match.start()
            before = line[max(0, before_start - 1):before_start]
            if (name[0] in common_surnames
                    and before not in ['学', '奖', '助', '实', '验']
                    and name not in ['学金', '验室', '实验']
                    and name not in results):
                results.append(name)

        for match in re.finditer(r'([A-Z][a-z]{2,10})\s*[：:;,]', line):
            name = match.group(1)
            if name not in results:
                if any(w in line for w in ['博士', '硕士', '专家', '总工', '算法']):
                    results.append(name)

    return results[:8]


def _hits(text: str, kws: list) -> int:
    t = text.lower()
    return sum(1 for k in kws if k.lower() in t)


def _extract_list(text: str, patterns: list, n: int = 5) -> list:
    results = []
    for p in patterns:
        for m in re.finditer(p, text[:30000]):
            try:
                v = m.group(1).strip()
            except (IndexError, TypeError):
                continue
            if v and len(v) > 1 and v not in results:
                results.append(v)
            if len(results) >= n:
                break
        if len(results) >= n:
            break
    return results


def extract_company(text: str) -> str:
    for p in [
        r'([\u4e00-\u9fa5]{2,15}(?:有限公司|科技|软件|技术|集团))',
        r'(?:公司 (?:名称 | 简称)[：:]\s*)([\u4e00-\u9fa5a-zA-Z0-9]{2,20})',
    ]:
        m = re.search(p, text[:3000])
        if m:
            return m.group(1).strip()
    return ''


def identify_stage_full(text: str) -> str:
    t = text[:20000].lower()
    vc_count = _hits(t, VC_KEYWORDS)
    pe_count = _hits(t, PE_KEYWORDS)
    late_count = _hits(t, LATE_VC)

    if pe_count >= 3 or (('c 轮' in t or 'd 轮' in t or 'series c' in t) and pe_count >= 2):
        return 'PE'
    if pe_count >= 1 and late_count >= 1:
        return 'PE/晚期 VC'
    m = re.search(r'研发投入[^\d%]{0,10}(\d+\.?\d*)\s*%', t)
    if m and float(m.group(1)) > 30:
        return 'VC'
    if any(kw in t for kw in ['产线扩建', '市场推广']):
        if vc_count >= 1:
            return 'VC 晚期'
    if any(kw in t for kw in ['并购', '股东退出', '分红', '上市准备']):
        return 'PE'
    if any(kw in t for kw in ['首发', '验证中', '头部客户测试', 'mvp']):
        return 'VC'
    if any(kw in t for kw in ['批量交付', '市占率']):
        m2 = re.search(r'连续\d+年盈利', t)
        if m2:
            return 'PE/晚期 VC'
    if vc_count >= 1:
        return 'VC'
    return '未识别'


def identify_mfg_mode(text: str) -> str:
    t = text.lower()
    for m, kws in [('ERP/MES 工业软件', ERP_MES), ('IDM 自有制造', IDM),
                    ('Fabless 设计', FABLESS), ('平台型', PLATFORM), ('服务/集成', SERVICE)]:
        if _hits(t, kws) > 0:
            return m
    return '未识别'


def identify_value_chain(text: str) -> str:
    t = text.lower()
    scores = {k: _hits(t, v) for k, v in VALUE_CHAIN.items()}
    top = max(scores, key=scores.get)
    if scores[top] == 0:
        return '未识别'
    return top


def extract_revenue_sources(text: str) -> dict:
    sources = []
    for m in re.finditer(r'([\u4e00-\u9fa5a-zA-Z]{2,20}(?:产品 | 服务 | 收入 | 业务 | 软件 | 系统 | 解决方案)?)[：:\s]*(\d+\.?\d*)\s*%', text[:20000]):
        name, pct = m.group(1).strip(), m.group(2).strip()
        if len(name) > 1:
            sources.append({'name': name, 'percent': pct})
    for m in re.finditer(r'(?:主要收入 | 营收占比 | 收入来源 | 业务构成)[^\n]{0,100}', text[:20000]):
        block = m.group(0)
        for mm in re.finditer(r'([^\s，,;；%]{2,20})\s*(\d+\.?\d*)\s*%', block):
            name = mm.group(1).strip()
            pct = mm.group(2).strip()
            if name and name not in [s['name'] for s in sources]:
                sources.append({'name': name, 'percent': pct})
    features = []
    if re.search(r'单一\s*产品', text[:10000]):
        features.append('单一产品')
    if re.search(r'多元 | 多产品', text[:10000]):
        features.append('多元产品')
    if re.search(r'产品.*(?:软件 | 服务)', text[:10000], re.IGNORECASE):
        features.append('产品+服务')
    return {'sources': sources[:5], 'features': features}


def extract_competitors(text: str) -> dict:
    competitors = {'direct': [], 'alternatives': [], 'chain_risks': []}
    company_patterns = [
        r'(?:对标 | 类比 | 类似)[：:\s]*([^\n，,;；]{2,60})',
        r'(?:竞争对手 | 竞品 | 同类)[：:\s]*([^\n，,;；]{2,60})',
        r'(?:如 | 类似 | 相当于)\s*([\u4e00-\u9fa5a-zA-Z]{2,10}(?:科技 | 技术 | 软件 | 系统 | 网络 | 智能 | 数据 | 集团 | 股份))',
    ]
    for p in company_patterns:
        for m in re.finditer(p, text[:30000]):
            name = m.group(1).strip()
            if len(name) > 2 and name not in competitors['direct'] + competitors['alternatives'] + competitors['chain_risks']:
                context = text[max(0, m.start() - 30):m.end() + 30]
                if any(kw in context for kw in ['替代', '新进入者', '跨界', '降维']):
                    competitors['alternatives'].append(name)
                elif any(kw in context for kw in ['上游', '下游', '整合', '自研']):
                    competitors['chain_risks'].append(name)
                else:
                    competitors['direct'].append(name)
    if not competitors['direct']:
        for m in re.finditer(r'(?:行业 | 赛道)[^。\n]{0,80}', text[:20000]):
            ctx = m.group(0).strip()
            if len(ctx) > 5:
                competitors['direct'].append(ctx[:40])
                break
    return competitors


def extract_equity(text: str) -> dict:
    shareholders = []
    for p in [
        r'([\u4e00-\u9fa5a-zA-Z0-9]{2,10})\s*(?:持有 | 持股 | 占股)\s*(\d+\.?\d*)\s*%',
        r'([\u4e00-\u9fa5a-zA-Z0-9]{2,10})[\s:：]*?(\d+\.?\d*)\s*%[的，,]',
    ]:
        for m in re.finditer(p, text[:20000]):
            context = text[max(0, m.start()-30):m.start()]
            if any(kw in context for kw in ['毛利率', '净利率', '利润', '增长']):
                continue
            name = m.group(1).strip()
            pct = m.group(2).strip()
            entry = {'name': name, 'percent': pct}
            if entry not in shareholders:
                shareholders.append(entry)
    return {
        'shareholders': shareholders[:10],
        'has_structure_info': len(shareholders) > 0,
    }


# ── LLM → 正则 合并 ──

def _merge_llm_regex(llm: dict, regex: dict, text: str) -> dict:
    """
    合并 LLM 与正则提取结果。策略：
    - company_name: LLM 优先（LLM 不识别时 fallback 正则）
    - founders: LLM 优先（正则结果作为补充，如果 LLM 识别少）
    - 其他字段：两者合并去重
    """
    merged = {}
    
    # 公司名
    llm_company = (llm.get('company_name') or '').strip()
    regex_company = regex.get('company_name', '')
    merged['company_name'] = llm_company if len(llm_company) > 2 else regex_company
    
    # 创始人
    llm_founders = llm.get('founders', []) or []
    regex_founders = regex.get('founders', []) or []
    if isinstance(llm_founders, str): llm_founders = [llm_founders]
    if isinstance(regex_founders, str): regex_founders = [regex_founders]
    llm_founders = [f for f in llm_founders if f and len(f) > 1]
    regex_founders = [f for f in regex_founders if f and len(f) > 1]
    # LLM 优先，正则补齐（不重复）
    merged['founders'] = list(dict.fromkeys(llm_founders + regex_founders))[:5]
    
    # 产品（合并去重）
    llm_prods = llm.get('products', []) or []
    if isinstance(llm_prods, str): llm_prods = [llm_prods]
    merged['products'] = list(dict.fromkeys(llm_prods + regex.get('products', [])))[:8]
    
    # 技术关键词（合并）
    llm_tech = llm.get('tech_keywords', []) or []
    if isinstance(llm_tech, str): llm_tech = [llm_tech]
    merged['tech_keywords'] = list(dict.fromkeys(llm_tech + regex.get('tech_keywords', [])))[:15]
    
    # 客户（合并）
    llm_cust = llm.get('customers', []) or []
    if isinstance(llm_cust, str): llm_cust = [llm_cust]
    merged['customers'] = list(dict.fromkeys(llm_cust + regex.get('customers', [])))[:20]
    
    # 竞品
    llm_comp = llm.get('competitors', []) or []
    if isinstance(llm_comp, dict):
        merged['competitors'] = llm_comp
    elif llm_comp:
        merged['competitors'] = {'direct': llm_comp, 'alternatives': [], 'chain_risks': []}
    else:
        merged['competitors'] = regex.get('competitors', {'direct': [], 'alternatives': [], 'chain_risks': []})
    
    # 融资阶段
    llm_stage = (llm.get('stage') or '').strip()
    regex_stage = regex.get('stage', '未识别')
    merged['stage'] = llm_stage if len(llm_stage) > 1 else regex_stage
    
    # 制造模式 & 价值链
    merged['manufacturing_mode'] = (llm.get('manufacturing_mode') or regex.get('manufacturing_mode', '未识别'))
    merged['value_chain'] = (llm.get('value_chain') or regex.get('value_chain', '未识别'))
    
    # 财务
    merged['financials'] = regex.get('financials', {})
    if llm.get('financials') and isinstance(llm['financials'], dict):
        merged['financials'].update(llm['financials'])
    
    # 股权
    merged['equity_structure'] = regex.get('equity_structure', {'shareholders': [], 'has_structure_info': False})
    
    # 收入
    llm_rev = llm.get('revenue_sources') or regex.get('revenue_sources', {'sources': [], 'features': []})
    if isinstance(llm_rev, list):
        merged['revenue_sources'] = {'sources': llm_rev, 'features': regex.get('revenue_sources', {}).get('features', [])}
    elif isinstance(llm_rev, dict):
        merged['revenue_sources'] = llm_rev
    
    return merged


# ── 主函数 ──

def _build_profile_regex(text: str) -> dict:
    """纯正则提取（保持兼容旧管线）"""
    company = extract_company(text)
    founders = _extract_founders(text)
    products = _extract_list(text, [
        r'(?:产品 | 解决方案)[：:]\s*([^\n,，;；]{3,100})',
        r'(?:复杂装备制造 | 制造业 | 离散制造)[^\n]{5,60}',
        r'(?:ERP|MES|MRP|生产管理系统)[^\n,。]{5,80}',
    ], 5)
    tech_kws = _extract_list(text, [
        r'(?:核心技术 | 关键技术 | 技术优势)[：:、\s]*([^\n，,;；]{2,60})',
        r'(MRP.{0,30}|COPICS.{0,30}|BOM.{0,30}|B/S.{0,30}|信创.{0,30}|参数化.{0,30})',
    ], 12)
    customers = _extract_list(text, [
        r'(?:客户 | 合作伙伴 | 典型客户)[：:、\s]*([^\n]{5,200})',
        r'((?:中国 [\u4e00-\u9fa5]{2,10}(?:集团 | 有限)))',
    ], 20)
    
    stage = identify_stage_full(text)
    mode = identify_mfg_mode(text)
    value_chain = identify_value_chain(text)
    revenue = extract_revenue_sources(text)
    competitors = extract_competitors(text)
    equity = extract_equity(text)
    
    dims = {k: _hits(text, v) for k, v in [('技术领先', TECH_KW), ('成本效率', COST_KW),
                                           ('方案能力', SOLN_KW), ('客户资源', CUST_KW)]}
    comp_dim = '+'.join(k for k, v in dims.items() if v > 0) or '未识别'
    
    finance = {}
    m = re.search(r'(\d{4})(?:年)?(?:营收 | 收入 | 预计 | 实现)[^\d]*?(\d+(?:\.\d+)?)\s*(万|亿)', text)
    if m:
        finance['revenue'] = f'{m.group(1)} 年{m.group(2)}{m.group(3)}元'
    m = re.search(r'(拟募集 | 本轮 | 计划融资)[^\d]*?(\d+(?:\.\d+)?)\s*(万|亿)', text)
    if m:
        finance['funding_ask'] = f'{m.group(2)}{m.group(3)}元'
    m = re.search(r'(?:主要用于 | 资金用于)[^\n]{5,200}', text)
    if m:
        finance['funding_use'] = m.group(0).strip()
    
    return {
        'company_name': company,
        'founders': founders,
        'products': products,
        'tech_keywords': tech_kws,
        'customers': customers,
        'stage': stage,
        'manufacturing_mode': mode,
        'value_chain': value_chain,
        'core_competition_dimension': comp_dim,
        'competitors': competitors,
        'revenue_sources': revenue,
        'equity_structure': equity,
        'financials': finance,
    }


def run(task_id: str, text: str, auto_detect_manual_fix: bool = True):
    task_dir = TASKS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # ── 手动修正保护 ──
    if auto_detect_manual_fix and _is_manually_fixed(task_dir):
        existing_path = task_dir / 'bp_step0_profile.json'
        profile = json.loads(existing_path.read_text(encoding='utf-8'))
        # 重新计算哈希
        profile['profile_hash'] = _compute_profile_hash(profile)
        with open(existing_path, 'w', encoding='utf-8') as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        print(f"  ✅ Step 0 已手动修正（哈希保护），跳过 preflight")
        return profile

    # ── 并行提取：正则 + LLM ──
    print("  🔍 Running regex extraction...")
    regex_result = _build_profile_regex(text)
    
    print("  🤖 Running LLM extraction (qwen-plus)...")
    start_llm = time.time()
    llm_result = _call_qwen_extract(text)
    llm_time = time.time() - start_llm
    
    if llm_result:
        print(f"  ✅ LLM extraction done ({llm_time:.1f}s)")
        profile_data = _merge_llm_regex(llm_result, regex_result, text)
        source_label = "LLM+Regex 合并"
    else:
        print("  ⚠ LLM 提取未返回，使用正则结果")
        profile_data = regex_result
        source_label = "Regex only"

    # ── 计算竞争力维度 ──
    comp_dim = profile_data.get('core_competition_dimension', '未识别')

    # ── 业务摘要 ──
    revenue = profile_data.get('revenue_sources', {'sources': [], 'features': []})
    biz_parts = []
    if revenue.get('sources'):
        biz_parts.append('收入=' + ', '.join(f'{s["name"]}({s["percent"]}%)' for s in revenue['sources'][:3]))
    elif revenue.get('features'):
        biz_parts.append('收入特征=' + '+'.join(revenue['features']))
    if comp_dim != '未识别':
        biz_parts.append('核心竞争力=' + comp_dim)
    biz_summary = ' | '.join(biz_parts) if biz_parts else '待提取'
    
    competitors = profile_data.get('competitors', {'direct': [], 'alternatives': [], 'chain_risks': []})
    targets_parts = []
    if competitors.get('direct'):
        targets_parts.append('直接对标=' + ','.join(competitors['direct'][:3]))
    if competitors.get('alternatives'):
        targets_parts.append('替代=' + ','.join(competitors['alternatives'][:3]))
    if competitors.get('chain_risks'):
        targets_parts.append('链风险=' + ','.join(competitors['chain_risks'][:3]))
    comp_targets_str = ' | '.join(targets_parts) if targets_parts else '待搜索确认'
    
    finance = profile_data.get('financials', {})

    # ── 组装 profile ──
    company = profile_data.get('company_name', '')
    founders = profile_data.get('founders', [])
    products = profile_data.get('products', [])
    tech_kws = profile_data.get('tech_keywords', [])
    customers = profile_data.get('customers', [])
    stage = profile_data.get('stage', '未识别')
    mode = profile_data.get('manufacturing_mode', '未识别')
    value_chain = profile_data.get('value_chain', '未识别')
    equity = profile_data.get('equity_structure', {'shareholders': [], 'has_structure_info': False})

    profile = {
        'task_id': task_id,
        'task_type': 'bp_尽调类',
        'created_at': datetime.now().isoformat(),
        'company_name': company,
        'founders': founders,
        'products': products,
        'tech_keywords': tech_kws,
        'customers': customers,
        'stage': stage,
        'manufacturing_mode': mode,
        'value_chain': value_chain,
        'core_competition_dimension': comp_dim,
        'business_model_summary': biz_summary,
        'competitors': competitors,
        'competitor_targets_str': comp_targets_str,
        'revenue_sources': revenue,
        'equity_structure': equity,
        'financials': finance,
        'bp_text_length': len(text),
        'extraction_source': source_label,
        'status': 'preflight_passed',
        'warnings': [],
        'profile_hash': '',  # 计算完再填
    }

    # 警告
    if not company:
        profile['warnings'].append('公司名未自动识别')
    if not founders:
        profile['warnings'].append('创始团队未识别')
    if not products:
        profile['warnings'].append('产品描述未识别')
    if stage == '未识别':
        profile['warnings'].append('融资阶段未识别')
    if not revenue.get('sources') and not revenue.get('features'):
        profile['warnings'].append('收入来源未提取')
    if not competitors.get('direct') or all(len(c) > 30 for c in competitors.get('direct', [])):
        profile['warnings'].append('对标对象未识别，需搜索竞品')
    if not equity.get('has_structure_info'):
        profile['warnings'].append('股权结构 BP 未披露')
    if not finance.get('funding_ask'):
        profile['warnings'].append('融资金额 BP 未明确')

    # 计算哈希
    profile['profile_hash'] = _compute_profile_hash(profile)
    # 保存
    with open(task_dir / 'bp_step0_profile.json', 'w', encoding='utf-8') as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    # ── Markdown 输出 ──
    md = f"""# BP Step 0 前置判断 — {company or '目标公司'}

## 核心定位

> {stage} | {mode} | {biz_summary} | {comp_targets_str}
> 提取来源：{source_label}

## 详细信息

| 字段 | 值 |
|------|-----|
| 公司 | {company or '未识别'} |
| 创始人 | {', '.join(founders) if founders else '未识别'} |
| 产品 | {', '.join(products) if products else '未识别'} |
| 技术关键词 | {', '.join(tech_kws[:5]) if tech_kws else '未识别'} |
| 客户 | {', '.join(customers[:5]) if customers else '需核查 LOGO 墙'} |
| 融资阶段 | {stage} |
| 制造模式 | {mode} |
| 价值链定位 | {value_chain} |
| 核心竞争力 | {comp_dim} |
| 商业模式 | {biz_summary} |
| 对标对象 | {comp_targets_str} |
| 融资金额 | {finance.get('funding_ask', '未明确')} |
| 资金用途 | {finance.get('funding_use', '未披露')} |
| 营收 | {finance.get('revenue', '未披露')} |
| 股权结构 | {'已提取' if equity.get('has_structure_info') else '未识别'} |
"""
    if revenue.get('sources'):
        md += '\n### 收入来源\n'
        for s in revenue['sources']:
            md += f'- {s["name"]}: {s["percent"]}%\n'
    if revenue.get('features'):
        md += f'- 特征：{"+".join(revenue["features"])}\n'
    if equity.get('shareholders'):
        md += '\n### 股东结构\n'
        for s in equity['shareholders']:
            md += f'- {s["name"]}: {s["percent"]}%\n'
    if competitors.get('direct'):
        md += '\n### 直接竞品\n'
        for c in competitors['direct'][:3]:
            md += f'- {c}\n'
    if competitors.get('alternatives'):
        md += '\n### 替代威胁\n'
        for c in competitors['alternatives'][:3]:
            md += f'- {c}\n'
    if profile['warnings']:
        md += '\n## ⚠️ 需手动补充\n'
        for w in profile['warnings']:
            md += f'- {w}\n'

    with open(task_dir / 'bp_step0_profile.md', 'w', encoding='utf-8') as f:
        f.write(md)

    print(f'  ✅ Step 0 前置判断完成 ({source_label})')
    print(f'')
    print(f'  {stage} | {mode} | {value_chain}')
    print(f'  核心竞争力：{comp_dim}')
    print(f'  对标：{comp_targets_str}')
    print(f'  创始人：{", ".join(founders) if founders else "未识别"}')
    for w in profile.get('warnings', []):
        print(f'    ⚠ {w}')

    return profile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--pdf-text', required=True)
    args = parser.parse_args()
    with open(args.pdf_text, 'r', encoding='utf-8') as f:
        text = f.read()
    run(args.task_id, text)


if __name__ == '__main__':
    main()
