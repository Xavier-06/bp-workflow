#!/usr/bin/env python3
"""
IR Subagent Launcher — WorkBuddy 版本 v3

无需外部 LLM API。发射器负责：
1. 构建 step brief（角色指令 + pre-search + 前序 step 输出）
2. 写入 spawn receipt（让 execution-loop 知道 step 已发射）
3. 写入 agent task manifest（让主 AI 知道需要执行什么）

实际的 LLM 推理由 WorkBuddy 主 AI 通过 Task 子代理完成：
- 方式 A（推荐）: 主 AI 读取 manifest，用 Task 工具逐 step 派发
- 方式 B（CLI）: python3 ir_agent_runner.py --manifest <path> 逐 step 执行
- 方式 C（DashScope 回退）: 如果 DASHSCOPE_API_KEY 可用，可直调

保留原有 8-step 拓扑、4-wave 并行发射、质量门控、补搜重写机制。

2026-04-13 v1: DashScope 直调版
2026-04-13 v3: 改为 WorkBuddy Task 子代理版（无外部 API 依赖）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'
INSTRUCTION_STORE = ROOT / 'instruction_store_ir'

# 质量线
STEP_QUALITY_THRESHOLD = 3

# Step 角色名
STEP_ROLE = {
    'step1_data': '投研_主笔_数据收集',
    'step2_industry': '投研_主笔_行业分析',
    'step3_biz': '投研_主笔_商业模式',
    'step4_finance': '投研_主笔_财务分析',
    'step5_mgmt': '投研_主笔_管理层',
    'step_macro': '投研_主笔_宏观分析',
    'step6_insight': '投研_主笔_差异化洞察',
    'step6b_valuation': '投研_主笔_预测与估值',
    'step7_risk': '投研_主笔_风险催化',
    'step8_master': '投研_主笔_文档汇总',
}

# 步间依赖关系
STEP_DEPS = {
    'step1_data': [],
    'step2_industry': ['step1_data'],
    'step3_biz': ['step1_data'],
    'step4_finance': ['step1_data'],
    'step5_mgmt': ['step1_data'],
    'step_macro': [],
    'step6_insight': ['step1_data', 'step2_industry', 'step3_biz', 'step6b_valuation'],
    'step6b_valuation': ['step1_data', 'step2_industry', 'step4_finance'],
    'step7_risk': ['step1_data', 'step3_biz', 'step4_finance', 'step6b_valuation'],
    'step8_master': ['step1_data', 'step2_industry', 'step3_biz', 'step4_finance', 'step5_mgmt', 'step_macro', 'step6_insight', 'step6b_valuation', 'step7_risk'],
}

# 并行发射波次
LAUNCH_WAVES = [
    ['step1_data'],
    ['step2_industry', 'step3_biz', 'step4_finance', 'step5_mgmt', 'step_macro'],
    ['step6b_valuation'],
    ['step6_insight', 'step7_risk'],
    ['step8_master'],
]

# 超时
STEP_TIMEOUTS = {
    'step1_data': 900,
    'step2_industry': 900,
    'step3_biz': 900,
    'step4_finance': 900,
    'step5_mgmt': 900,
    'step_macro': 900,
    'step6_insight': 900,
    'step6b_valuation': 900,
    'step7_risk': 900,
    'step8_master': 1800,
}

# Step 查询关键词（用于自动补搜）
_STEP_KEYWORDS = {
    'step1_data': 'stock price market cap PE ratio EPS dividend analyst rating 市值 股价 市盈率',
    'step2_industry': 'industry market size market share growth rate TAM penetration competitive landscape 行业规模 竞争格局',
    'step3_biz': 'business model product revenue customer supply chain 商业模式 产品线 客户 收入结构',
    'step4_finance': 'financial report revenue profit margin cash flow ROE debt 财报 营收 毛利率 净利润 现金流',
    'step5_mgmt': 'management board governance ownership ESG compensation 管理层 董事会 股权结构 治理',
    'step_macro': 'CPI PMI interest rate LPR GDP inflation monetary policy 宏观 利率 通胀 PMI 社融',
    'step6_insight': 'catalyst valuation target price investment thesis risk-reward 催化剂 估值 目标价 投资亮点',
    'step6b_valuation': 'DCF valuation PE PB PS EV/EBITDA target price WACC comparable company valuation model 目标价 估值',
    'step7_risk': 'risk regulatory litigation competition macro threat 风险 监管 诉讼 竞争威胁 宏观',
    'step8_master': '',
}

_STEP_QUERY_TEMPLATES = {
    'step1_data': [
        '"{entity}" stock price market cap PE EPS analyst rating',
        '"{entity}" investor relations results announcement',
        'site:hkexnews.hk "{entity}" results announcement',
    ],
    'step2_industry': [
        '"{entity}" industry market size competitive landscape',
        '"{entity}" market share industry report',
        '"{entity}" 行业 竞争格局 市场规模',
    ],
    'step3_biz': [
        '"{entity}" business model revenue segments',
        '"{entity}" products services overview',
        '"{entity}" 商业模式 收入结构 产品',
    ],
    'step4_finance': [
        '"{entity}" financial report revenue profit margin cash flow ROE debt',
        '"{entity}" annual report results announcement revenue profit',
        'site:hkexnews.hk "{entity}" annual report',
        'site:hkexnews.hk "{entity}" results announcement',
        '"{entity}" 财报 营收 毛利率 净利润 现金流',
    ],
    'step5_mgmt': [
        '"{entity}" CEO management team leadership governance',
        '"{entity}" executive changes board ownership',
        '"{entity}" 管理层 董事会 股权结构 治理',
    ],
    'step_macro': [
        '"{entity}" sector macro impact CPI PMI interest rate',
        'China macro economy GDP inflation monetary policy latest',
        '宏观 利率 通胀 PMI 社融 最新数据',
    ],
    'step6_insight': [
        '"{entity}" investment thesis valuation target price catalyst',
        '"{entity}" analyst report target price catalyst',
        '"{entity}" 投资逻辑 估值 催化剂',
    ],
    'step7_risk': [
        '"{entity}" risks regulatory litigation competition macro',
        '"{entity}" risk analysis report',
        '"{entity}" 风险 监管 诉讼 竞争',
    ],
    'step6b_valuation': [
        '"{entity}" DCF valuation target price WACC',
        '"{entity}" comparable company valuation PE PB PS EV/EBITDA',
        '"{entity}" analyst consensus target price',
        '"{entity}" 估值 目标价 可比公司',
    ],
    'step8_master': [],
}


# ═══════════════════════════════════════════════════════
# 通知（龙少微信，替代 openclaw message send）
# ═══════════════════════════════════════════════════════

def notify_wx(text: str) -> bool:
    """通过龙少微信发送通知，失败静默。"""
    try:
        sys.path.insert(0, str(ROOT / 'scripts'))
        from longshao_notify import send_message
        result = send_message(text)
        return result.get('ok', False)
    except Exception:
        return False


# ═══════════════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════════════

def load_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return default


def step_output_path(task_id: str, step: str) -> Path:
    return TASKS_DIR / f'{task_id}-{step}.md'


def step_spawn_receipt_path(task_id: str, step: str) -> Path:
    return TASKS_DIR / f'{task_id}-spawn-receipt-{step}.json'


def step_manifest_path(task_id: str, step: str) -> Path:
    """WorkBuddy Task 子代理的 manifest 文件"""
    return TASKS_DIR / f'{task_id}-manifest-{step}.json'


def pipeline_manifest_path(task_id: str) -> Path:
    """整个 pipeline 的 step manifest 汇总"""
    return TASKS_DIR / f'{task_id}-pipeline-manifest.json'


def deps_ready(task_id: str, step: str) -> tuple[bool, list[str]]:
    """检查依赖步骤的输出文件是否已存在"""
    missing = []
    for dep in STEP_DEPS.get(step, []):
        if not step_output_path(task_id, dep).exists():
            missing.append(dep)
    return len(missing) == 0, missing


def load_instruction(role_key: str) -> str:
    """加载角色指令（instruction_store）"""
    instruction_map = {
        'step1_data': '投研_主笔_数据收集',
        'step2_industry': '投研_主笔_行业分析',
        'step3_biz': '投研_主笔_商业模式',
        'step4_finance': '投研_主笔_财务分析',
        'step5_mgmt': '投研_主笔_管理层',
        'step_macro': '投研_主笔_宏观分析',
        'step6_insight': '投研_主笔_差异化洞察',
        'step6b_valuation': '投研_主笔_预测与估值',
        'step7_risk': '投研_主笔_风险催化',
        'step8_master': '投研_主笔_文档汇总',
    }
    role_file = INSTRUCTION_STORE / f'{instruction_map.get(role_key, role_key)}.md'
    if role_file.exists():
        return role_file.read_text(encoding='utf-8')
    return f'Role instructions for {role_key} not found.'


def build_step_brief(task_id: str, step: str, entity: str = '', query: str = '') -> str:
    """构建子代理任务 brief"""
    role_key = step
    instruction = load_instruction(role_key)
    
    output_path = step_output_path(task_id, step)
    
    brief_lines = [
        f'# Step Brief: {STEP_ROLE.get(step, step)} ({step})',
        f'',
        f'Task: {task_id}',
        f'Entity: {entity}',
        f'Query: {query}',
        f'',
        f'## ⚠️ CRITICAL: 输出文件路径（必须写入此路径）',
        f'',
        f'**你必须将最终分析报告写入以下文件：**',
        f'',
        f'`{output_path}`',
        f'',
        f'**禁止写入其他路径（如 search-stepX.md、brief-stepX.md 等）。**',
        f'**唯一完成条件：上述文件写入成功。**',
        f'',
        f'## Role Instruction',
        f'',
        instruction,
        f'',
        f'## ⚠️ 自主闭环规则（最高优先级）',
        f'',
        f'你在执行过程中必须自主闭环，不要返回主控等待指示：',
        f'1. **发现数据缺口** → 自己补搜（工具优先级见下方），继续推进',
        f'2. **来源不足** → 自己搜更多来源，补充到输出中',
        f'3. **数据矛盾** → 自己判断哪个更可靠，标注矛盾来源',
        f'4. **前序 step 输出有 gap** → 自己补充搜索填补',
        f'5. **唯一完成条件** → 将完整报告写入上方指定的输出文件路径',
        f'',
        f'### 补搜工具优先级',
        f'1. `NeoData 金融搜索` — A/HK 股首选（行情、财报、板块、研报，通过 search_gateway 自动调用）',
        f'2. `yfinance (Python)` — 估值指标、美股数据、交叉验证',
        f'3. `web_search` — 通用搜索（新闻、公告、行业报告、东财/雪球行情）',
        f'4. DuckDuckGo / SearXNG — 备用搜索',
        f'',
        f'### 补搜纪律',
        f'- 最多补搜 3 轮，避免无限循环',
        f'- 补搜结果必须标注来源 URL',
        f'- 仍搜不到的标注"经 X 次搜索未找到独立来源"',
        f'',
        f'## Pre-search Results（输入参考，只读）',
        f'',
    ]
    
    # Pre-search
    search_path = TASKS_DIR / f'{task_id}-search-{step}.md'
    if search_path.exists():
        brief_lines.append(search_path.read_text(encoding='utf-8'))
    else:
        brief_lines.append('_No pre-search results._')
    
    # Extraction results (phase15 产出)
    extraction_dir = TASKS_DIR / f'{task_id}_body_content'
    extraction_facts = extraction_dir / 'ir_extracted_facts.json'
    if extraction_facts.exists():
        brief_lines.append(f'')
        brief_lines.append(f'## URL Content Extraction Results')
        brief_lines.append(f'')
        brief_lines.append(f'提取事实文件: `{extraction_facts}`')
        brief_lines.append(f'提取内容目录: `{extraction_dir}`')
        brief_lines.append(f'请读取提取事实文件获取预提取的 URL 内容（年报、公告、行业报告等）。')
    
    # Company verification results (phase05 产出)
    verify_path = TASKS_DIR / f'{task_id}-ir_company_verify.json'
    if verify_path.exists():
        brief_lines.append(f'')
        brief_lines.append(f'## Company Verification Data')
        brief_lines.append(f'')
        brief_lines.append(f'文件路径: `{verify_path}`')
        brief_lines.append(f'请读取此文件获取公司验证和估值数据（PE/PB/市值等）。')
    
    # Prior steps
    for dep in STEP_DEPS.get(step, []):
        dep_path = step_output_path(task_id, dep)
        if dep_path.exists():
            brief_lines.append(f'')
            brief_lines.append(f'## Prior Step Output: {dep}')
            brief_lines.append(f'')
            brief_lines.append(dep_path.read_text(encoding='utf-8')[:5000])
            brief_lines.append(f'_（完整 {dep} 输出，截断显示前 5000 字符）_')
    
    return '\n'.join(brief_lines)


def build_step_prompt(step: str, entity: str, market: str = 'us') -> str:
    """构建给 WorkBuddy Task 子代理的系统级提示词 — v2: 按角色加入专属验证规则"""
    role_name = STEP_ROLE.get(step, step)

    # 通用基础指令
    base = (
        f"You are an expert investment research analyst specializing in {role_name}. "
        f"You are working on step '{step}' of an investment research pipeline for '{entity}' (market: {market}). "
        f"Your output must be in Markdown format, well-structured with multiple sections (## headers), "
        f"include at least 3 source citations (URLs), and contain substantive analysis (minimum 3000 characters). "
        f"Write your analysis directly — do not include meta-commentary about the task itself. "
        f"If you cannot find specific data, SUPPLEMENTARY SEARCH FIRST before writing '未找到独立外部证据'. "
        f"Use thinking=high — reason carefully before writing each section.\n\n"
        f"CRITICAL: You must autonomously close the loop. When you discover data gaps during analysis:\n"
        f"1. Search for the missing data yourself (NeoData via search_gateway → yfinance → web_search)\n"
        f"2. Integrate the found data into your analysis\n"
        f"3. Only mark as '待核实' after 3 rounds of supplementary search still yield nothing\n"
        f"Do NOT return to the coordinator for search instructions — you ARE the search agent.\n\n"
        f"DATA SOURCE PRIORITY:\n"
        f"- A/HK stocks: NeoData (via search_gateway, auto-invoked) → yfinance (cross-validation) → web_search\n"
        f"- US stocks: yfinance → web_search\n"
        f"- NeoData covers: real-time quotes, financials, sector data, analyst reports\n"
        f"- search_gateway automatically routes financial queries to NeoData Layer 0\n\n"
        f"- Required fields coverage ≥ 70%\n"
        f"- ≥ 3 independent sources\n"
        f"- ≥ 3 ## level sections\n"
        f"- Content length ≥ 3000 chars\n"
        f"If self-check fails, do more research before outputting.\n\n"
    )

    # 角色专属 ANTI-DEFECT RULES
    step_rules = {
        'step1_data': (
            'ANTI-DEFECT RULES:\n'
            '1. FINANCING/LISTING STATUS: Before citing any company (target or competitor), verify their '
            'current listing/financing status. If yfinance returns no data for a previously known ticker, '
            'search whether the company has been delisted, privatized, or acquired.\n'
            '2. PERSON VERIFICATION: Every person name cited must be verified via at least 1 independent '
            'source. NEVER fabricate person names or positions from model training data.\n'
            '3. YFINANCE ACCURACY: For key financial data (revenue, market cap, PE), cross-verify yfinance '
            'data with at least 1 web_search source (东财/雪球/公司IR页). If discrepancy >10%, investigate.\n'
            '4. COMPETITOR FINANCING VERIFICATION: For every competitor in comparison tables, search-verify '
            'their current financing/IPO status. NEVER use stale training data (e.g. "private, B轮" when '
            'company has IPO\'d). If listed, use yfinance for real-time market cap and cite ticker.\n'
        ),
        'step2_industry': (
            'ANTI-DEFECT RULES:\n'
            '1. COMPETITOR STATUS VERIFICATION: For every competitor listed, search-verify their current '
            'financing/IPO status. A competitor marked as "private, B轮" may have since IPO\'d. '
            'Update status and note date of verification.\n'
            '2. INDUSTRY REPORT CURRENCY: When citing market size data, verify you are using the LATEST '
            'edition of the report. Search "{report} {year} latest edition" before citing.\n'
            '3. REGULATORY STATUS: For regulated industries, verify current policy status before citing '
            'policy-driven market assumptions. Search "{policy} 现行 有效 最新政策".\n'
        ),
        'step3_biz': (
            'ANTI-DEFECT RULES:\n'
            '1. COMPETITOR MOAT VERIFICATION: When scoring competitor moat dimensions, each score must be '
            'based on SEARCH-VERIFIED current data, not model training data. A competitor\'s capability '
            'may have changed significantly since training cutoff.\n'
        ),
        'step4_finance': (
            'ANTI-DEFECT RULES:\n'
            '1. LATEST FILING VERIFICATION: Before citing annual report data, verify it is the LATEST filing. '
            'Search "{company} 最新年报 {year}" and check HKEX/SEC for recent filings. '
            'If a newer report exists, use the newer data.\n'
            '2. AUDIT OPINION CHECK: Note the audit opinion for each year cited. A change in audit opinion '
            '(e.g., from "unqualified" to "qualified") is a significant red flag that must be highlighted.\n'
        ),
        'step5_mgmt': (
            'ANTI-DEFECT RULES:\n'
            '1. PERSON EXISTENCE VERIFICATION (CRITICAL): EVERY person name mentioned in the management '
            'team section MUST be verified to actually exist at this company. Search "{person name} '
            '{company} 高管/董事/管理层" to confirm. If no independent source confirms this person\'s '
            'association with the company after 2 searches, write "⚠ 该人员信息未经独立来源验证". '
            'NEVER fabricate person names from model training data — this is the HIGHEST RISK area '
            'for data fabrication in this step.\n'
            '2. MANAGEMENT CURRENCY: Management team data from annual reports may be outdated (CEO changes, '
            'director resignations). Search "{company} 管理层变动 CEO变更 {year}" for recent changes.\n'
            '3. MANAGEMENT LEGAL STATUS: For key management members, search for recent legal/regulatory '
            'issues: "{person name} 处罚 调查 诉讼". Recent issues are material to governance assessment.\n'
        ),
        'step6_insight': (
            'ANTI-DEFECT RULES:\n'
            '1. COMPETITOR DATA CURRENCY: When citing competitor data from prior steps, verify it is current. '
            'If prior steps used stale competitor data, note this as a limitation.\n'
        ),
        'step6b_valuation': (
            'ANTI-DEFECT RULES:\n'
            '1. COMPARABLE COMPANY STATUS VERIFICATION (CRITICAL): For EVERY comparable company in the '
            'comps table, search-verify their CURRENT status: (a) If currently listed: use yfinance to '
            'verify ticker is active, pull latest market cap/PE/PS. (b) If currently private: search '
            'IT桔子/36氪/企查查 for latest round and date. CRITICAL: check whether they have IPO\'d '
            'SINCE the last private valuation you found. (c) If delisted/privatized: note date and last '
            'available valuation. (d) If acquired: note acquisition price — this IS a valuation data point. '
            'Status column format: "上市公司(代码) 市值X亿" or "未上市 X轮 金额(日期)" or '
            '"已IPO(代码) 市值X亿" or "已收购 价格X亿(日期)". NEVER assume private companies '
            'remain private without verification. This is the #1 cause of valuation errors.\n'
            '2. VALUATION DATA TIMELINESS: All financial data (revenue, PE, PS, etc.) must be verified '
            'as current within 6 months. Data >12 months old must be labeled with ⚠ warning.\n'
        ),
        'step7_risk': (
            'ANTI-DEFECT RULES:\n'
            '1. REGULATORY STATUS CURRENCY: Every regulatory risk cited must be search-verified for CURRENT '
            'status. A regulation described as "即将出台" in older sources may have been enacted, revised, '
            'or shelved. Search "{regulation} 最新 现行 有效 {year}" before citing.\n'
            '2. COMPETITOR COMPLIANCE EVENTS: For competition-related risks, search whether major competitors '
            'have recent regulatory penalties — this may reduce competitive pressure on the target.\n'
        ),
        'step_macro': (
            'ANTI-DEFECT RULES:\n'
            '1. MACRO DATA TIMELINESS: Every macro indicator cited (CPI, PMI, LPR, GDP, etc.) must have '
            'a publication date. Indicators older than 60 days must be marked with "⚠ 数据滞后 X 天". '
            'Search "{indicator} 最新 {year}" to verify you have the latest release.\n'
            '2. POLICY STATUS CURRENCY: When citing monetary/fiscal policy, verify it is CURRENT. '
            'Search "{policy} 现行 最新 {year}" to confirm. Policies announced but not yet implemented '
            'must be labeled as "待实施".\n'
            '3. CROSS-MARKET IMPACT: For A/HK stocks, analyze BOTH China domestic macro AND global/'
            'US macro spillover effects (Fed rates, USD/CNY). Do not analyze only one dimension.\n'
            '4. IMPACT PATHWAY: Every macro judgment must include a concrete transmission mechanism '
            'to the target company\'s sector. "利好" without an impact pathway is insufficient — '
            'explain HOW (e.g., "降息→融资成本下降→资本密集型行业受益").\n'
            '5. CONFIDENCE CALIBRATION: If a key indicator (e.g. PMI) is from a single source with no '
            'cross-verification, set confidence to "medium" max. "high" requires ≥2 independent sources.\n'
        ),
        'step8_master': (
            'ANTI-DEFECT RULES:\n'
            '1. FINANCING STATUS CONSISTENCY: Check that the same entity\'s financing/IPO status is consistent '
            'across all steps. If step1 describes a competitor as "private" but step6b uses listed-company '
            'multiples for it, this is a critical inconsistency that must be resolved by search verification.\n'
        ),
    }

    rules = step_rules.get(step, '')
    return base + rules if rules else base


# ═══════════════════════════════════════════════════════
# 核心：子代理发射（WorkBuddy 版 v3 — Task 子代理）
# ═══════════════════════════════════════════════════════

def launch_step(task_id: str, step: str, entity: str = '', query: str = '',
                timeout: int = 900, dry_run: bool = False, market: str = 'us') -> dict:
    """启动单个子代理 step — WorkBuddy 版 v3。
    
    发射器只负责：
    1. 构建 brief 并写入文件
    2. 写入 manifest（给 WorkBuddy 主 AI 读取用）
    3. 写入 spawn receipt（让 execution-loop 知道 step 已发射）
    
    实际的 LLM 推理由主 AI 通过 WorkBuddy Task 子代理完成。
    """
    output_path = step_output_path(task_id, step)
    receipt_path = step_spawn_receipt_path(task_id, step)
    manifest = step_manifest_path(task_id, step)

    # 检查依赖
    ready, missing = deps_ready(task_id, step)
    if not ready:
        return {
            'step': step,
            'status': 'blocked',
            'reason': f'Dependencies not ready: {missing}',
        }

    # 构建 brief
    brief = build_step_brief(task_id, step, entity, query)
    brief_path = TASKS_DIR / f'{task_id}-brief-{step}.md'
    brief_path.write_text(brief, encoding='utf-8')

    if dry_run:
        return {
            'step': step,
            'status': 'dry_run',
            'brief_path': str(brief_path),
            'output_path': str(output_path),
            'manifest_path': str(manifest),
        }

    # 清理旧输出
    for p in (receipt_path, manifest):
        if p.exists():
            p.unlink()

    # ─── 写入 manifest（WorkBuddy Task 子代理的任务描述）───
    role_name = STEP_ROLE.get(step, step)
    system_prompt = build_step_prompt(step, entity, market)
    
    manifest_data = {
        'task_id': task_id,
        'step': step,
        'role': role_name,
        'entity': entity,
        'query': query,
        'market': market,
        'system_prompt': system_prompt,
        'brief_path': str(brief_path),
        'output_path': str(output_path),
        'timeout': timeout,
        'thinking': 'high',
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'status': 'pending',  # pending → running → completed/failed
    }
    manifest.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding='utf-8')

    # ─── 写入 spawn receipt（兼容原格式，确保 execution-loop 无缝衔接）───
    label = f'{task_id}-{step}'
    receipt = {
        'task_id': task_id,
        'step': step,
        'hook': step,
        'label': label,
        'status': 'dispatched',  # dispatched = 已派发，等待子代理完成
        'runId': f'wb-task-{int(time.time())}',
        'childSessionKey': f'wb-{task_id}-{step}',
        'runtime': 'workbuddy-task',
        'thinking': 'high',
        'manifest_path': str(manifest),
        'output_path': str(output_path),
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"  📋 已派发 {role_name} ({step}) → manifest: {manifest.name}")

    return {
        'step': step,
        'status': 'dispatched',  # dispatched = 等待 WorkBuddy Task 子代理执行
        'label': label,
        'childSessionKey': receipt['childSessionKey'],
        'runId': receipt['runId'],
        'thinking': 'high',
        'brief_path': str(brief_path),
        'output_path': str(output_path),
        'receipt_path': str(receipt_path),
        'manifest_path': str(manifest),
    }


def wait_for_output(task_id: str, step: str, timeout: int = 900, poll_interval: int = 15) -> dict:
    """等待 step 输出文件出现。
    
    WorkBuddy Task 子代理完成分析后会写入 output_path。
    主 AI 在派发 Task 子代理后应轮询此函数来检查输出。
    """
    output_path = step_output_path(task_id, step)
    start = time.time()
    while time.time() - start < timeout:
        if output_path.exists() and output_path.stat().st_size > 100:
            return {
                'step': step,
                'status': 'completed',
                'output_path': str(output_path),
                'output_size': output_path.stat().st_size,
                'elapsed_s': int(time.time() - start),
            }
        time.sleep(poll_interval)
    return {
        'step': step,
        'status': 'timeout',
        'timeout_s': timeout,
        'elapsed_s': int(time.time() - start),
    }


# ═══════════════════════════════════════════════════════
# 质量门控 + 补搜
# ═══════════════════════════════════════════════════════

def _check_step_quality(task_id: str, step: str) -> dict:
    """单 step 质量评估 (0-5 分)"""
    output_path = step_output_path(task_id, step)
    if not output_path.exists():
        return {'score': 0, 'verdict': 'fail', 'issues': ['output file missing']}
    
    text = output_path.read_text(encoding='utf-8')
    content_len = len(text)
    urls = text.count('http')
    sections = text.count('## ')
    
    score = 0
    issues = []
    
    if content_len < 500:
        score = 0
        issues.append(f'内容过短 ({content_len} 字符)')
    elif content_len < 1000:
        score = 1
        issues.append(f'内容偏少 ({content_len} 字符)')
    elif content_len < 3000:
        score = 2
        issues.append(f'内容尚可 ({content_len} 字符)')
    elif content_len < 6000:
        score = 3
    elif content_len < 10000:
        score = 4
    else:
        score = 5
    
    if urls < 2:
        score = max(0, score - 1)
        issues.append(f'来源不足 ({urls} 个 URL)')
    
    if sections < 3:
        score = max(0, score - 1)
        issues.append(f'章节不足 ({sections} 个)')
    
    threshold = STEP_QUALITY_THRESHOLD
    
    return {
        'score': score,
        'content_length': content_len,
        'url_count': urls,
        'section_count': sections,
        'threshold': threshold,
        'verdict': 'pass' if score >= threshold else 'fail',
        'issues': issues,
    }


def _do_targeted_search(entity: str, step: str, market: str = 'us') -> str:
    """针对某个 step 做补搜，统一走 scripts.search_gateway.search。"""
    templates = _STEP_QUERY_TEMPLATES.get(step, [])
    if not templates:
        kw = _STEP_KEYWORDS.get(step, '')
        if not kw:
            return ''
        templates = [f'"{{entity}}" {kw}']

    memo_lines = []
    seen_urls: set[str] = set()

    try:
        sys.path.insert(0, str(ROOT / 'scripts'))
        from search_gateway import search as gateway_search

        collected = []
        for template in templates[:5]:
            query = template.format(entity=entity).strip()
            rows = gateway_search(query, max_results=5, timeout=20)
            for row in rows:
                url = row.get('url', '') or ''
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                collected.append((query, row))

        if collected:
            memo_lines.append(f"## SearchGateway 补搜结果 ({len(collected)} 条)\n\n")
            for i, (query, row) in enumerate(collected[:12], 1):
                title = row.get('title', '') or ''
                url = row.get('url', '') or ''
                snippet = row.get('content', '') or row.get('snippet', '') or ''
                engine = row.get('engine', '?')
                memo_lines.append(f"### {i}. [{engine}] {title}\n")
                memo_lines.append(f"Query: {query}\n")
                memo_lines.append(f"URL: {url}\n")
                memo_lines.append(f"{snippet[:300]}\n\n")
    except Exception as exc:
        print(f"    ⚠ SearchGateway 补搜异常: {exc}")

    return '\n'.join(memo_lines)


def _rewrite_step(task_id: str, step: str, entity: str, query: str,
                  quality: dict, market: str = 'us', timeout: int = 900) -> dict:
    """质量不达标 → 补搜 + 重写。"""
    step_name = STEP_ROLE.get(step, step)

    # 1. 补搜
    print(f"  🔍 补搜 ({step_name})...")
    memo = _do_targeted_search(entity, step, market)

    memo_path = TASKS_DIR / f'{task_id}-{step}-followup-research.md'
    if memo:
        memo_path.write_text(memo, encoding='utf-8')
        print(f"  📝 补搜结果已写入 {memo_path.name}")
    else:
        print(f"  ⚠ 补搜无结果，用已有内容重写")

    # 2. 重新写 brief
    brief = build_step_brief(task_id, step, entity, query)
    brief_path = TASKS_DIR / f'{task_id}-brief-{step}.md'
    
    rewrite_brief = brief
    if memo_path.exists():
        rewrite_brief += f'\n\n## 补充搜索笔记\n- 文件: `{memo_path}`\n- 必读其中内容\n'
    brief_path.write_text(rewrite_brief, encoding='utf-8')

    # 3. 清理旧输出
    output_path = step_output_path(task_id, step)
    receipt_path = step_spawn_receipt_path(task_id, step)
    for p in (output_path, receipt_path):
        if p.exists():
            p.unlink()

    # 4. Re-dispatch
    step_info = launch_step(task_id, step, entity, query, timeout=timeout, dry_run=False, market=market)
    if step_info.get('status') not in ('dispatched', 'spawned'):
        return {'status': 'rewrite_dispatch_failed', 'error': (step_info.get('error', '') or '')[:500]}

    return {
        'status': 'rewrite_dispatched',
        'manifest_path': step_info.get('manifest_path', ''),
        'output_path': str(output_path),
    }


MAX_SPAWN_RETRIES = 2


def launch_and_verify(task_id: str, step: str, entity: str = '', query: str = '',
                      timeout: int = 900, market: str = 'us', retries: int = 1) -> dict:
    """完整流程：发射 → 等待输出 → 超时补发 → 质检 → 补搜重写
    
    注意：在 WorkBuddy Task 模式下，此函数只做发射 + 写 manifest。
    等待输出和质检需要主 AI 在 Task 子代理完成后调用 check_step_quality()。
    """
    results = []

    # 发射
    launch_result = launch_step(task_id, step, entity, query, timeout, market=market)
    results.append(launch_result)

    if launch_result.get('status') in ('blocked', 'spawn_failed'):
        return {
            'step': step,
            'status': launch_result.get('status'),
            'steps': results,
            'error': launch_result.get('error') or launch_result.get('reason', ''),
        }

    # WorkBuddy Task 模式：发射即返回，主 AI 负责等待和质检
    return {
        'step': step,
        'status': 'dispatched',
        'manifest_path': launch_result.get('manifest_path', ''),
        'output_path': str(step_output_path(task_id, step)),
        'steps': results,
    }


def check_step_quality(task_id: str, step: str) -> dict:
    """检查 step 输出质量（供主 AI 在 Task 子代理完成后调用）"""
    return _check_step_quality(task_id, step)


def do_supplementary_search(entity: str, step: str, task_id: str, market: str = 'us') -> dict:
    """执行补搜（供主 AI 在质量不达标时调用）"""
    memo = _do_targeted_search(entity, step, market)
    memo_path = TASKS_DIR / f'{task_id}-{step}-followup-research.md'
    if memo:
        memo_path.write_text(memo, encoding='utf-8')
    return {
        'step': step,
        'memo_path': str(memo_path) if memo else '',
        'has_results': bool(memo),
    }


def dispatch_rewrite(task_id: str, step: str, entity: str, query: str, market: str = 'us') -> dict:
    """重新派发 step（补搜后重写，供主 AI 调用）"""
    # 清理旧输出
    output_path = step_output_path(task_id, step)
    receipt_path = step_spawn_receipt_path(task_id, step)
    for p in (output_path, receipt_path):
        if p.exists():
            p.unlink()
    return launch_step(task_id, step, entity, query, dry_run=False, market=market)


def launch_wave(task_id: str, steps: list[str], entity: str, query: str, market: str) -> dict:
    """并行发射一组无依赖关系的 step。"""
    results = []
    
    for step in steps:
        result = launch_and_verify(task_id, step, entity, query, STEP_TIMEOUTS.get(step, 600), market)
        results.append(result)

    step_map = {r['step']: r for r in results if 'step' in r}
    ordered_results = [step_map[s] for s in steps if s in step_map]
    
    return {
        'results': ordered_results,
    }


def launch_all(task_id: str, entity: str = '', query: str = '', dry_run: bool = False, market: str = 'us') -> dict:
    """按依赖拓扑并行发射所有 step — 4 波次。

    ⚠️ 仅适用于 DashScope 直调模式（同步等待每个 step 完成）。
    WorkBuddy Task 模式下请使用 launch_next_wave() 循环，因为 Task 子代理
    是异步的，launch_step() 只写 manifest 就返回，后续 wave 的依赖检查必然失败。
    """
    import warnings
    warnings.warn(
        "launch_all() 在 WorkBuddy Task 模式下无法正确推进 wave 2-4，"
        "请改用 launch_next_wave() 循环。",
        DeprecationWarning,
        stacklevel=2,
    )
    all_results = []
    all_manifests = []
    
    for wave_idx, wave_steps in enumerate(LAUNCH_WAVES):
        print(f"\n{'=' * 50}")
        print(f"🌊 Wave {wave_idx + 1}: {', '.join(wave_steps)}")
        print(f"{'=' * 50}")
        
        if dry_run:
            for step in wave_steps:
                result = launch_step(task_id, step, entity, query, STEP_TIMEOUTS.get(step, 600), dry_run=True)
                all_results.append(result)
            continue
        
        wave_result = launch_wave(task_id, wave_steps, entity, query, market)
        all_results.extend(wave_result['results'])
        
        # 收集 manifest 路径
        for r in wave_result['results']:
            if r.get('manifest_path'):
                all_manifests.append(r['manifest_path'])
    
    # 写入 pipeline manifest 汇总
    pipeline_manifest = {
        'task_id': task_id,
        'entity': entity,
        'query': query,
        'market': market,
        'mode': 'workbuddy-task',
        'runtime': 'workbuddy-task',
        'dry_run': dry_run,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'steps': all_results,
        'manifest_files': all_manifests,
        'total_steps_dispatched': sum(1 for r in all_results if r.get('status') in ('dispatched', 'spawned')),
    }
    pipeline_manifest_path(task_id).write_text(
        json.dumps(pipeline_manifest, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    
    result = {
        **pipeline_manifest,
        'pipeline_manifest_path': str(pipeline_manifest_path(task_id)),
    }
    
    # 微信通知汇总
    if not dry_run:
        notify_wx(
            f"🐲 IR Pipeline 已派发\n"
            f"任务: {task_id}\n"
            f"实体: {entity}\n"
            f"已派发: {result['total_steps_dispatched']}/{len(LAUNCH_WAVES)} waves\n"
            f"运行时: WorkBuddy Task\n"
            f"⚠ 需主 AI 逐 step 派发 Task 子代理执行"
        )
    
    return result


def get_current_wave_index(task_id: str) -> int:
    """根据已完成的 step 输出文件推算当前应该发射的 wave 索引（0-3）。"""
    for idx, wave_steps in enumerate(LAUNCH_WAVES):
        for step in wave_steps:
            out = step_output_path(task_id, step)
            if not out.exists() or out.stat().st_size < 100:
                return idx
    return len(LAUNCH_WAVES)  # 全部完成


def get_pipeline_status(task_id: str) -> dict:
    """返回整个管线当前状态快照。"""
    steps_status = {}
    for step in STEP_DEPS:
        out = step_output_path(task_id, step)
        if out.exists() and out.stat().st_size >= 100:
            steps_status[step] = 'completed'
        else:
            ready, missing = deps_ready(task_id, step)
            steps_status[step] = 'ready' if ready else f'blocked_by:{",".join(missing)}'
    wave_idx = get_current_wave_index(task_id)
    all_done = wave_idx >= len(LAUNCH_WAVES)
    return {
        'task_id': task_id,
        'steps': steps_status,
        'current_wave': wave_idx if not all_done else 'all_done',
        'total_waves': len(LAUNCH_WAVES),
        'completed_count': sum(1 for v in steps_status.values() if v == 'completed'),
        'total_steps': len(STEP_DEPS),
        'all_steps_done': all_done,
        'next_action': 'finalize' if all_done else f'launch_wave_{wave_idx}',
    }


def launch_next_wave(task_id: str, entity: str = '', query: str = '', market: str = 'us') -> dict:
    """发射当前应该执行的 wave。主 AI 每轮调用一次，直到所有 wave 完成。

    返回值包含：
    - wave_index: 发射的 wave 编号
    - steps: 本 wave 的 step 列表及 manifest 信息
    - all_done: 所有 wave 是否已完成
    - next_action: 下一步该做什么（'dispatch_tasks' / 'finalize' / 'already_done'）
    - task_tool_instructions: 给主 AI 的精确派发指令
    """
    wave_idx = get_current_wave_index(task_id)

    if wave_idx >= len(LAUNCH_WAVES):
        return {
            'wave_index': -1,
            'steps': [],
            'all_done': True,
            'next_action': 'finalize',
            'message': '所有 wave 已完成，请调用 finalize_pipeline()',
        }

    wave_steps = LAUNCH_WAVES[wave_idx]
    results = []

    for step in wave_steps:
        # 已完成的跳过
        out = step_output_path(task_id, step)
        if out.exists() and out.stat().st_size >= 100:
            results.append({'step': step, 'status': 'already_completed', 'output_path': str(out)})
            continue

        ready, missing = deps_ready(task_id, step)
        if not ready:
            results.append({'step': step, 'status': 'blocked', 'missing': missing})
            continue

        result = launch_step(task_id, step, entity, query, STEP_TIMEOUTS.get(step, 900), market=market)
        results.append(result)

    dispatched = [r for r in results if r.get('status') == 'dispatched']

    # 构建主 AI 的精确执行指令
    # step8_master 的前序 step 列表（需要读取它们的完整输出）
    _STEP8_PRIOR_STEPS = ['step1_data', 'step2_industry', 'step3_biz', 'step4_finance', 'step5_mgmt', 'step_macro', 'step6_insight', 'step6b_valuation', 'step7_risk']

    task_instructions = []
    for r in dispatched:
        step = r['step']
        role = STEP_ROLE.get(step, step)
        brief_path = r.get('brief_path', '')
        output_path = r.get('output_path', '')

        # 构建 prompt
        prompt_body = (
            f'你是投研分析师，负责 {role}（{step}）。\n\n'
            f'【输出路径 - 必须严格遵守】\n'
            f'你必须将完整 Markdown 报告写入以下文件（绝对路径）：\n'
            f'{output_path}\n'
            f'禁止写入任何其他路径（如 search-stepX.md、bref-stepX.md 等）。\n'
            f'唯一完成条件：上述文件成功写入且内容完整。\n\n'
        )

        # step8_master 特殊处理：注入前序 step 的完整输出文件路径 + 统稿硬约束
        if step == 'step8_master':
            prior_paths = []
            for ps in _STEP8_PRIOR_STEPS:
                pp = step_output_path(task_id, ps)
                prior_paths.append(f'  {ps}: {pp}')
            prompt_body += (
                f'⚠️ CRITICAL: 你是统稿 Agent，必须读取以下前序 step 的完整输出文件作为输入：\n'
                + '\n'.join(prior_paths) + '\n\n'
                f'brief 中嵌入的 "Prior Step Output" 是截断版（仅前5000字符），你必须读取上述完整文件才能做出高质量统稿。\n\n'
                f'⚠️ 统稿保留硬约束（最高优先级，违反任一条即视为统稿失败）：\n\n'
                f'【规则1】核心对比表必须原文保留：行业技术路线全景对比表、产品级竞品参数对比表、现有方案深度对比大表、核心组件拆解表——不得删除或压缩为文字叙述。如果某个step有5张竞品对比表，统稿必须保留5张，不能合并成1张。\n\n'
                f'【规则2】市占率/份额/渗透率数据必须完整保留：TAM/SAM/SOM分层推算及每层具体数字、各细分市场渗透率及驱动力、竞品市占率（具体数字和百分比，不能只写"垄断竞争"等模糊表述）、标的公司渗透率——这些是判断市场空间的核心依据。\n\n'
                f'【规则3】去重只做跨step，不做step内压缩：跨step重复内容可合并，但单个step内部的表格、数据、分析段落不得删除或压缩。\n\n'
                f'【规则4】来源合并不得丢来源：所有step的来源索引表/脚注列表都必须合并到统稿末尾"来源附录"章节；不能因格式不同（[^N]脚注/编号表格/URL直接引用/评级格式）就丢弃；非[^N]格式的来源必须转换为[^N]脚注格式纳入统一编号；目标：统稿来源总数 ≥ 各step来源去重后总数。统稿完成后必须自检：数末尾来源附录条目数，对比各step来源总数，显著减少则说明有来源丢失，必须补回。\n\n'
            )

        prompt_body += (
            f'【执行步骤】\n'
            f'1. 读取 brief 文件：{brief_path}\n'
        )

        if step == 'step8_master':
            prompt_body += (
                f'2. 逐一读取上方列出的前序 step 完整输出文件\n'
                f'3. 根据 brief 中的统稿规则，将 step1~step7 的内容汇总为一份完整研报\n'
                f'   （step_macro 宏观判断需纳入投资摘要和风险章节）\n'
                f'4. 如发现数据缺口或矛盾，用 web_search 补搜验证（最多 3 轮）\n'
                f'5. 将完整 Markdown 报告写入上方指定的输出路径\n\n'
            )
        else:
            prompt_body += (
                f'2. 根据 brief 中的角色指令和预搜索数据，执行完整分析\n'
                f'3. 如发现数据缺口，用 web_search 补搜（最多 3 轮）\n'
                f'4. 将完整 Markdown 报告写入上方指定的输出路径\n\n'
            )

        prompt_body += (
            f'【输出要求】\n'
            f'- ≥3000 字符\n'
            f'- ≥3 个来源引用（带 URL）\n'
            f'- 多个 ## 章节\n'
            f'- 关键数据加粗\n'
            f'- 禁止输出"Pre-search Results"格式的搜索备忘录——必须是正式分析报告'
        )

        task_instructions.append({
            'step': step,
            'role': role,
            'action': 'team_task',
            'tool': 'task(name=..., team_name=...)',
            'subagent_name': 'code-explorer',
            'name': step,
            'team_name': f'ir-{task_id}',
            'mode': 'bypassPermissions',
            'prompt': prompt_body,
            'brief_path': brief_path,
            'output_path': output_path,
        })

    return {
        'wave_index': wave_idx,
        'wave_label': f'Wave {wave_idx + 1}/{len(LAUNCH_WAVES)}',
        'steps': results,
        'dispatched_count': len(dispatched),
        'all_done': False,
        'next_action': 'dispatch_tasks',
        'task_tool_instructions': task_instructions,
        'after_all_tasks_complete': (
            'launch_next_wave()' if wave_idx < len(LAUNCH_WAVES) - 1 else 'finalize_pipeline()'
        ),
    }


def finalize_pipeline(task_id: str, entity: str = '', market: str = 'us') -> dict:
    """Phase 5：统稿 → DOCX → 交付。所有 step 完成后由主 AI 调用。

    自动执行：
    1. 质量门禁
    2. DOCX 生成
    3. 复制到桌面
    4. 微信通知
    """
    from pathlib import Path as _P

    # 确认所有 step 都完成
    status = get_pipeline_status(task_id)
    if not status['all_steps_done']:
        incomplete = [s for s, v in status['steps'].items() if v != 'completed']
        return {
            'status': 'not_ready',
            'incomplete_steps': incomplete,
            'message': f'尚有 {len(incomplete)} 个 step 未完成',
        }

    result = {'status': 'finalizing', 'task_id': task_id}

    # 质量门禁（内联，避免导入 run_ir_pipeline 触发重量级模块链）
    try:
        _OFFICIAL = ['sec.gov','hkexnews.hk','cninfo.com.cn','szse.cn','sse.com.cn','ir.','investor.']
        _REPUTABLE = ['reuters.com','bloomberg.com','wsj.com','ft.com','economist.com','scmp.com','caixin.com','36kr.com','cls.cn','eastmoney.com','xueqiu.com']
        _REDFLAGS = ['待补','待填','TODO','无法验证','无法获取','需要进一步']
        _STEP_ORDER = ['step1_data','step2_industry','step3_biz','step4_finance','step5_mgmt','step_macro','step6_insight','step6b_valuation','step7_risk','step8_master']
        scores, issues = {}, []
        for step in _STEP_ORDER:
            f = TASKS_DIR / f'{task_id}-{step}.md'
            if not f.exists():
                scores[step] = 0; issues.append(f"❰{step}❱ 缺失"); continue
            txt = f.read_text(encoding='utf-8')
            if len(txt) < 200:
                scores[step] = 0; issues.append(f"❰{step}❱ 内容过短"); continue
            t = txt.lower()
            oc = sum(1 for d in _OFFICIAL if d in t)
            rc = sum(1 for d in _REPUTABLE if d in t)
            uc = txt.count('http')
            if oc >= 2 and len(txt) > 2000: sc = 3
            elif (oc >= 1 or rc >= 2) and len(txt) > 1000: sc = 2
            elif uc >= 1: sc = 1
            else: sc = 0
            fl = sum(1 for x in _REDFLAGS if x in txt)
            if fl >= 3 and sc > 1: sc = max(1, sc - 1); issues.append(f"❰{step}❱ {fl} 红旗")
            scores[step] = sc
        total = sum(scores.values())
        qg = {'scores': scores, 'total': total, 'max': len(_STEP_ORDER) * 3, 'pass': total >= 16, 'issues': issues}
        result['quality_gate'] = qg
        print(f"  {'✅' if qg['pass'] else '⚠️'} 质量: {qg['total']}/{qg['max']}")
    except Exception as e:
        result['quality_gate_error'] = str(e)

    # DOCX 生成（subprocess 调用，与 ir_profile Phase 5 一致）
    docx_path = None
    build_script = ROOT / 'scripts' / 'build_ir_broker_report_docx.py'
    if build_script.exists():
        try:
            import subprocess
            r = subprocess.run(
                [sys.executable, str(build_script), task_id],
                capture_output=True, text=True, timeout=180,
                cwd=str(ROOT),
            )
            if r.returncode == 0:
                try:
                    payload = json.loads(r.stdout.strip())
                    dp = payload.get('output', '')
                    if dp and _P(dp).exists():
                        docx_path = dp
                        result['docx_path'] = dp
                        print(f"  ✅ DOCX: {dp}")
                except (json.JSONDecodeError, KeyError):
                    pass
            else:
                err_msg = r.stderr[:300] if r.stderr else r.stdout[:300]
                print(f"  ⚠ DOCX 生成失败 (exit {r.returncode}): {err_msg}")
                result['docx_error'] = f"exit {r.returncode}: {err_msg}"
        except Exception as e:
            print(f"  ⚠ DOCX 生成异常: {e}")
            result['docx_error'] = str(e)
    else:
        result['docx_error'] = f"build script not found: {build_script}"

    # 如果 DOCX 失败，用 markdown 兜底
    master_md = TASKS_DIR / f'{task_id}-step8_master.md'
    if not docx_path and master_md.exists():
        result['markdown_path'] = str(master_md)
        result['docx_fallback'] = True

    # 复制到桌面
    desktop = _P.home() / 'Desktop'
    deliver_path = None
    try:
        if docx_path and _P(docx_path).exists():
            dst = desktop / _P(docx_path).name
            import shutil
            shutil.copy2(docx_path, dst)
            deliver_path = str(dst)
            result['desktop_path'] = deliver_path
            print(f"  📄 已复制到桌面: {dst.name}")
        elif master_md.exists():
            entity_clean = entity.replace(' ', '_').replace('/', '_') or task_id
            dst = desktop / f'{entity_clean}_投资研报.md'
            import shutil
            shutil.copy2(master_md, dst)
            deliver_path = str(dst)
            result['desktop_path'] = deliver_path
            print(f"  📄 已复制到桌面: {dst.name}")
    except Exception as e:
        result['desktop_error'] = str(e)

    # 微信通知（三步发送：文本→文件→确认，确保文件真正送达）
    try:
        import subprocess
        notify_script = ROOT / 'scripts' / 'longshao_notify.py'
        file_name = _P(deliver_path).name if deliver_path else ''
        file_to_send = deliver_path  # 桌面文件路径

        if notify_script.exists():
            # 第一步：发送文本通知
            text_msg = (
                f"📊 {entity or task_id} 深度研报已生成\n\n"
                f"📄 文件: {file_name or '(未生成)'}\n"
                f"📁 桌面已放置\n\n"
                f"请查阅。（IR管线自动交付）"
            )
            text_cmd = [sys.executable, str(notify_script), text_msg]
            nr = subprocess.run(text_cmd, capture_output=True, text=True, timeout=30)
            text_ok = False
            if nr.returncode == 0:
                try:
                    text_result = json.loads(nr.stdout.strip())
                    text_ok = text_result.get('ok', False)
                except Exception:
                    text_ok = True

            # 第二步：发送文件（关键！之前的代码只发了文本没发文件）
            file_ok = False
            if file_to_send and _P(file_to_send).exists():
                file_cmd = [sys.executable, str(notify_script), '--file', file_to_send, text_msg]
                fr = subprocess.run(file_cmd, capture_output=True, text=True, timeout=60)
                if fr.returncode == 0:
                    try:
                        file_result = json.loads(fr.stdout.strip())
                        file_ok = file_result.get('ok', False)
                    except Exception:
                        file_ok = True
                else:
                    # 文件发送失败，重试一次
                    fr2 = subprocess.run(file_cmd, capture_output=True, text=True, timeout=60)
                    if fr2.returncode == 0:
                        try:
                            file_result = json.loads(fr2.stdout.strip())
                            file_ok = file_result.get('ok', False)
                        except Exception:
                            file_ok = True

            result['notified'] = text_ok
            result['file_sent'] = file_ok
            if not file_ok and file_to_send:
                result['file_send_warning'] = '文件发送可能失败，请检查微信是否收到文件'
        else:
            # fallback: 直接调用 notify_wx（仅文本）
            notify_wx(
                f"📊 {entity or task_id} 深度研报已生成\n\n"
                f"📄 文件: {file_name or '(未生成)'}\n"
                f"📁 桌面已放置\n\n"
                f"请查阅。（IR管线自动交付）"
            )
            result['notified'] = True
            result['file_sent'] = False
    except Exception as e:
        result['notify_error'] = str(e)
        result['file_sent'] = False

    result['status'] = 'delivered'
    result['message'] = f"研报已生成并复制到桌面: {deliver_path or '(markdown)'}"
    return result


def get_pending_steps(task_id: str) -> list[dict]:
    """获取所有待执行的 step manifest（供主 AI 读取后派发 Task）"""
    pending = []
    for step in STEP_DEPS:
        manifest = step_manifest_path(task_id, step)
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding='utf-8'))
            output = step_output_path(task_id, step)
            if not output.exists() and data.get('status') == 'pending':
                pending.append(data)
    return pending


def main():
    ap = argparse.ArgumentParser(description='IR Subagent Launcher — WorkBuddy 版 v3 (Task 子代理)')
    ap.add_argument('--task-id', required=True, help='Task ID')
    ap.add_argument('--step', choices=list(STEP_DEPS.keys()), help='Single step to launch')
    ap.add_argument('--all', action='store_true', help='Launch all steps (parallel waves)')
    ap.add_argument('--entity', default='', help='Entity name (e.g. 宁德时代)')
    ap.add_argument('--query', default='', help='Research query')
    ap.add_argument('--market', default='us', choices=['us', 'hk', 'cn'], help='Market')
    ap.add_argument('--dry-run', action='store_true', help='Show what would be launched')
    ap.add_argument('--retries', type=int, default=1, help='Max quality-gated retries')
    ap.add_argument('--check-quality', action='store_true', help='Check quality of completed step')
    ap.add_argument('--pending', action='store_true', help='List pending steps for Task dispatch')
    ap.add_argument('--do-search', action='store_true', help='Do supplementary search for step')
    sub = ap.add_subparsers(dest='action')
    info_sub = sub.add_parser('info', help='Show pipeline status')
    info_sub.add_argument('--task-id', required=True)
    super_main = ap.parse_args()

    # Handle --pending
    if super_main.pending:
        pending = get_pending_steps(super_main.task_id)
        print(json.dumps(pending, ensure_ascii=False, indent=2))
        return

    # Handle --check-quality
    if super_main.check_quality and super_main.step:
        quality = check_step_quality(super_main.task_id, super_main.step)
        print(json.dumps(quality, ensure_ascii=False, indent=2))
        return

    # Handle --do-search
    if super_main.do_search and super_main.step:
        result = do_supplementary_search(super_main.entity, super_main.step, super_main.task_id, super_main.market)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # Handle info
    if super_main.action == 'info':
        pm_path = pipeline_manifest_path(super_main.task_id)
        if pm_path.exists():
            print(pm_path.read_text(encoding='utf-8'))
        else:
            print(json.dumps({'error': 'No pipeline manifest found', 'task_id': super_main.task_id}))
        return

    if super_main.step:
        timeout = STEP_TIMEOUTS.get(super_main.step, 600)
        result = launch_and_verify(super_main.task_id, super_main.step, super_main.entity, super_main.query, timeout, market=super_main.market)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif super_main.all:
        result = launch_all(super_main.task_id, super_main.entity, super_main.query, super_main.dry_run, super_main.market)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        ap.print_help()


if __name__ == '__main__':
    main()
