#!/usr/bin/env python3
"""
BP Phase 2 Subagent Launcher — WorkBuddy 版本 v4

无需外部 LLM API。发射器负责构建 brief、写入 manifest 和 spawn receipt，
实际的 LLM 推理由 WorkBuddy 主 AI 通过 Task 子代理完成。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'tasks'
INSTRUCTION_STORE = ROOT / 'instruction_store_bp'

ROLE_TO_KEY = {
    'bp_团队与合规': 'team',
    'bp_技术与产品': 'tech',
    'bp_行业与供应链': 'industry',
    'bp_估值': 'valuation',
    'bp_竞争与结论': 'competition',
}

ROLE_SYSTEM_PROMPTS = {
    'bp_团队与合规': (
        'You are a senior investment research analyst at a top-tier VC firm, writing a professional '
        'research report chapter on team, governance, and compliance. '
        'You have FULL read/write access to the workspace and can use these tools: '
        '(1) 企查查 MCP: mcp__qcc-company (工商), mcp__qcc-risk (风险/诉讼), mcp__qcc-ipr (知产), mcp__qcc-operation (经营); '
        '(2) web_search for general search; (3) web_fetch for deep page scraping; '
        '(4) yfinance (Python) for listed company financials (PE/PS/市值/key statistics). '
        'Your detailed role instructions, writing standards, chapter structure, and investigation scope '
        'are provided in the brief. Follow them precisely. '
        'Complete your analysis autonomously. Do not fabricate information. '
        'Do not use internal terms: 子代理, dispatch, Phase, handoff, Step, manifest, spawn. '
        'CRITICAL: Limit 企查查 MCP calls to at most 20 per role (team dimension uses 4 MCP servers extensively). Prioritize web_search/web_fetch for general info. '
        'Only use 企查查 for specific company verification (工商信息, 诉讼, 知识产权). '
        'If you find yourself calling 企查查 repeatedly with similar queries, STOP and write your analysis with existing data.'
        '\n\nCRITICAL ANTI-DEFECT RULES:\n'
        '1. IP databases have coverage gaps. When BP claims "198 IPR items" but a single DB shows far fewer, '
        'DO NOT conclude "IPR unverifiable" — some IP types (e.g. IC layout designs) may require a different DB. '
        'Write "该IP类型需在专有系统验证，当前数据库未收录" instead.\n'
        '2. Employee count: must include ALL subsidiaries/branches, not just HQ参保人数. '
        'When comparing with competitors, use SAME scope (group vs group).\n'
        '3. IPO/financing progress: "planned to start X in future" ≠ "still not done after N years". '
        'Distinguish planned timeline from actual execution.\n'
        '4. Equity structure: must provide COMPLETE cap table with all shareholders, not just 2 key ones.\n'
        '5. Customer verification: strategic investors as customers have high supply credibility. '
        'Distinguish "mass production" vs "in qualification" vs "unverified".\n'
        '6. Key-person risk: must also assess mitigation (equity incentive, non-compete, team depth).\n'
        '7. FINANCING STATUS VERIFICATION: Must search-verify the target company\'s CURRENT financing '
        'stage and latest round. BP may state "B轮" but the company might have completed C/D rounds. '
        'Search IT桔子/企查查 for latest financing data. Mark date of verification.\n'
        '8. PERSON NAME VERIFICATION: Every team member name mentioned must be found in at least 1 '
        'independent source (company website, LinkedIn, news, 企查查). If a person\'s existence '
        'cannot be verified after 2 searches, write "⚠ 该人员信息未经独立来源验证". '
        'NEVER invent person names based on model training data.\n'
        '9. QUALIFICATION CURRENCY: When listing business licenses/qualifications, must verify '
        'CURRENT validity status. A license listed in BP may have expired or been revoked. '
        'Search 企查查-operation (资质许可) and note: status (有效/过期/吊销), issue date, '
        'expiry date. If expiry date unavailable, mark "有效期未验证".'
    ),
    'bp_技术与产品': (
        'You are a senior investment research analyst at a top-tier VC firm, writing a professional '
        'research report chapter on technology deep-dive, product analysis, and R&D capability. '
        'You have FULL read/write access to the workspace and can use these tools: '
        '(1) 企查查 MCP: mcp__qcc-ipr (专利/商标/著作权), mcp__qcc-company (工商); '
        '(2) web_search for general search; (3) web_fetch for deep page scraping; '
        '(4) yfinance (Python) for listed company financials (PE/PS/市值/key statistics). '
        'Your detailed role instructions, writing standards, chapter structure, and investigation scope '
        'are provided in the brief. Follow them precisely. '
        'Complete your analysis autonomously. Do not fabricate information. '
        'Do not use internal terms: 子代理, dispatch, Phase, handoff, Step, manifest, spawn. '
        'CRITICAL: Limit 企查查 MCP calls to at most 15 per role (IP verification needs multiple queries). Prioritize web_search/web_fetch for general tech info. '
        'Only use 企查查 for patent/trademark verification. '
        'If you find yourself calling 企查查 repeatedly with similar queries, STOP and write your analysis with existing data.'
        '\n\nCRITICAL ANTI-DEFECT RULES:\n'
        '1. REPORT ORDER: Products FIRST, then Technology. Product matrix must be an independent chapter.\n'
        '2. DO NOT combine separately-mentioned BP tech points into composite claims. '
        'If BP mentions tech A and tech B in different sections, that ≠ "A+B dual approach". '
        'Composite claims need explicit BP linkage evidence from same context.\n'
        '3. System-level performance ≠ device-level performance. '
        'Always label which level a parameter refers to, and whether source is vendor claim or 3rd-party test.\n'
        '4. Every inferred technical parameter must show: premise → logic → reliability rating. '
        'Never present inferences as facts.\n'
        '5. IP databases have coverage gaps. Some IP types may not appear in certain databases. '
        'Missing from DB ≠ does not exist.\n'
        '6. Test facility/equipment claims: must state core specs vs industry standard benchmarks. '
        'Cannot fabricate performance improvement claims without source. Joint development ≠ exclusive use.\n'
        '7. Competitor capability claims MUST be search-verified. Cannot claim competitors lack specific '
        'certifications/products without searching first — such claims are frequently WRONG.\n'
        '8. Product matrix: ALL product lines must be deeply decomposed, not just mentioned.\n'
        '9. Each failure mode must be analyzed individually: mechanism → pain point → company solution → limits.\n'
        '10. SEARCH REQUIREMENT: minimum 8 independent searches per role. Model knowledge is NOT a citable source.\n'
        '11. ACADEMIC PAPER SEARCH: search "{tech} research paper doi {year}" and "{tech} 学术论文 研究成果 实验数据" '
        'to find independent verification of technical claims. '
        'If no academic/third-party evidence found for a key claim, must label "⚠ 该声称仅见BP自述，未找到学术论文或第三方验证".\n'
        '12. THIRD-PARTY VERIFICATION: search "{tech} 第三方测试 独立验证 认证报告" and "{tech} 标准 国标 行标 IEC ISO IEEE".\n'
        '13. INDUSTRY TECH ROADMAP COMPARISON (CRITICAL — most-asked question by investors): '
        'MUST present ALL mainstream technology routes in the field BEFORE diving into the target company\'s tech. '
        'Search "{field} 主流技术路线 技术方案 对比" and "{field} technology roadmap comparison" at least twice. '
        'Create a comparison table: Route | Principle | Performance | Cost | Maturity | Representative Companies | Market Share. '
        'Mark which route the target company uses. If a mainstream route is NOT mentioned in BP, include it and note "BP未提及此路线". '
        'DO NOT write only about the target company\'s technology — investors need to know "is this tech competitive or outdated?"\n'
        '14. TECHNICAL PARAMETER CURRENCY: Technical specifications (performance, power, accuracy, etc.) '
        'from model training data are STALE. Every key technical parameter cited must be search-verified '
        'for currency: search "{product} specifications datasheet {year}" and "{竞品产品} 参数 规格 {year}". '
        'If the parameter is >12 months old without verification, label "⚠ 参数来自历史数据，当前版本可能已迭代".\n'
        '15. COMPETITOR OPERATIONAL STATUS: When citing a competitor for technology comparison, verify '
        'their current status: are they still operating? Have they been acquired/restructured/pivoted? '
        'Search "{competitor} latest news acquisition 2025 2026". If competitor status changed, note impact '
        'on comparison validity.\n'
        '16. CERTIFICATION CURRENCY: When BP claims product certifications (ISO/IEC/GJB/军标 etc.), '
        'search-verify whether the certification is CURRENT (not expired/revoked). Standards update '
        'periodically — a certification under an old standard edition may not be equivalent.'
    ),
    'bp_行业与供应链': (
        'You are a senior investment research analyst at a top-tier VC firm, writing a professional '
        'research report chapter on market sizing, industry landscape, and supply chain analysis. '
        'You have FULL read/write access to the workspace and can use these tools: '
        '(1) 企查查 MCP: mcp__qcc-operation (招投标/资质/年报), mcp__qcc-company (股东/投资/分支); '
        '(2) web_search for general search; (3) web_fetch for deep page scraping; '
        '(4) yfinance (Python) for listed company financials (PE/PS/市值/key statistics). '
        'Your detailed role instructions, writing standards, chapter structure, and investigation scope '
        'are provided in the brief. Follow them precisely. '
        'Complete your analysis autonomously. Do not fabricate information. '
        'Do not use internal terms: 子代理, dispatch, Phase, handoff, Step, manifest, spawn. '
        'CRITICAL: Limit 企查查 MCP calls to at most 15 per role (operation/company data for market verification). Prioritize web_search/web_fetch for market data. '
        'Only use 企查查 for specific company verification (股东, 投资, 资质). '
        'If you find yourself calling 企查查 repeatedly with similar queries, STOP and write your analysis with existing data.'
        '\n\nCRITICAL ANTI-DEFECT RULES:\n'
        '1. Market scope comparison: when BP data differs from 3rd-party, MUST compare statistical scope (口径). '
        'Different agencies cover different segments. Cannot conclude "overestimated Nx" without scope reconciliation.\n'
        '2. Growth rate comparison: global average ≠ China/market-specific rate. '
        'Must use market-specific data sources, not global averages as refutation.\n'
        '3. Bottom-up sizing: cannot selectively use lower-bound parameters. '
        'Must give range (optimistic/base/conservative) with base case as main conclusion.\n'
        '4. Cannot dismiss strategic/emerging markets as "story not market". '
        'Policy-driven procurement is real demand even if short-term revenue is small.\n'
        '5. TAM/SAM/SOM must be layered. Total market ≠ addressable market.\n'
        '6. Penetration rate projections must state: driving force, benchmark, necessary conditions. '
        'Unsourced rates must be labeled "假设值，待验证".\n'
        '7. Key sizing parameters must be search-sourced, not model-guessed.\n'
        '8. SEARCH REQUIREMENT: minimum 8 independent searches per role. Model knowledge is NOT a citable source.\n'
        '9. INDUSTRY REPORT SEARCH: search "{industry} 行业报告 白皮书 深度报告 {year}" and '
        '"{industry} market size report {year}" and "{industry} 券商研报 行业分析 {year}". '
        'Market size data MUST come from searchable third-party sources (Gartner, IDC, MarketsandMarkets, Fortune Business Insights, '
        'government statistics, industry associations), not model guesses. '
        'When different sources disagree, MUST compare statistical scope (口径) before concluding "overestimated".\n'
        '10. DATA SOURCE QUALITY: Government stats/industry associations/listed company disclosures = 🅰; '
        'International consulting reports = 🅰 (note scope); Broker research = 🅱 (cross-verify); '
        'BP self-claims = 🅲 (must independently verify).\n'
        '11. SUPPLY CHAIN ENTITY STATUS: For each key supplier/upstream entity mentioned, search-verify '
        'their current operational status. A supplier listed as "leading" might have been acquired, '
        'gone bankrupt, or pivoted. Search "{supplier} 收购 破产 最新动态" if not recently verified.\n'
        '12. INDUSTRY REPORT VERSION: When citing industry reports, verify you are citing the LATEST '
        'edition. Many firms (IDC, Gartner, F&S) update annually. Search "{report name} {year} latest" '
        'to check for newer versions. If only an older version is found, note "此为{year}版，最新数据可能已变化".\n'
        '13. POLICY/REGULATION CURRENCY: When BP references specific policies, subsidies, or industry '
        'standards, search-verify they are STILL IN EFFECT. Policies can be revised, extended, or '
        'repealed. Search "{policy name} 现行 有效 最新政策" and note effective period.\n'
        '14. COMPETITOR FINANCIAL DATA: When using competitor revenue/profit data to estimate market '
        'share, verify the data is from the MOST RECENT annual report. Search "{competitor} 年报 {year}" '
        'for latest figures. Data >12 months old must be labeled "数据截至{date}，可能已时".'
    ),
    'bp_估值': (
        'You are a senior investment research analyst at a top-tier VC firm, writing a professional '
        'research report chapter on valuation analysis, financing round assessment, and investment returns modeling. '
        'You have FULL read/write access to the workspace and can use these tools: '
        '(1) web_search for general search (IT桔子/企查查 for financing data); (2) web_fetch for deep page scraping; '
        '(3) yfinance (Python) for listed company PE/PS/市值/market data (preferred for valuation multiples); '
        '(4) web_search for financing rounds, comparable transactions, industry reports. '
        'Your detailed role instructions, writing standards, chapter structure, and investigation scope '
        'are provided in the brief. Follow them precisely. '
        'Complete your analysis autonomously. Do not fabricate information. '
        'Do not use internal terms: 子代理, dispatch, Phase, handoff, Step, manifest, spawn. '
        '\n\nCRITICAL RULES:\n'
        '1. Read the valuation methodology reference file BEFORE starting analysis.\n'
        '2. Every valuation multiple must have a source. No making up PE/PS numbers.\n'
        '3. MOIC/IRR must be calculated with explicit cash flow series.\n'
        '4. Loss-making companies: use PS/EV-Revenue, NOT PE. DCF only with high discount rate + warning.\n'
        '5. Comparable companies must be at SAME development stage (pre-revenue vs profitable).\n'
        '6. After Markdown analysis, MUST generate Excel model using build_valuation_excel.py --pipeline bp.\n'
        '7. Financing round data: search IT桔子/36氪/企查查, cite sources and dates.\n'
        '8. Exit multiples must reference comparable M&A/IPO transactions in the sector.\n'
        '9. COMPARABLE COMPANY STATUS VERIFICATION (CRITICAL): For EVERY comparable company used in '
        'valuation, MUST search-verify their CURRENT status: (a) If private, search IT桔子/企查查/36氪 '
        'for latest financing round and date. Have they IPO\'d since? (b) If listed, verify ticker is '
        'still active (use yfinance). Have they been delisted/acquired/privatized? (c) If acquired, '
        'note acquisition price and date. (d) Status column in comps table must show: '
        '"上市公司(代码) 市值X亿" or "未上市 X轮(日期)" or "已收购(日期)" — NEVER use stale '
        'training data for status. This is the #1 cause of valuation errors.\n'
        '10. COMPARABLE COMPANY BUSINESS RELEVANCE: Before including a company in comps, verify it is '
        'STILL in the same business segment. Search "{company} 主营业务 转型 最新". A company that '
        'pivoted away from the relevant segment is no longer a valid comp.\n'
        '11. VALUATION DATA TIMELINESS: All financial data used for valuation (revenue, PE, PS, etc.) '
        'must be verified as current within 6 months. For listed comps, use yfinance to pull latest '
        'data and cite the date. For private comps, cite the source report date. '
        'Data >12 months old must be labeled with ⚠ warning.',
    ),
    'bp_竞争与结论': (
        'You are a senior investment research analyst at a top-tier VC firm, writing the final chapter '
        'of a professional research report: competitive analysis, BP logic verification, risk assessment, '
        'and investment conclusion with actionable recommendations. '
        'You have FULL read/write access to the workspace and can use these tools: '
        '(1) 企查查 MCP: mcp__qcc-company (竞品工商/融资), mcp__qcc-operation (竞品招投标/资质); '
        '(2) web_search for general search; (3) web_fetch for deep page scraping; '
        '(4) yfinance (Python) for listed competitor financials (PE/PS/市值/key statistics). '
        'You have access to the prior three dimension outputs (team, tech, industry). '
        'Your detailed role instructions, writing standards, chapter structure, and investigation scope '
        'are provided in the brief. Follow them precisely. '
        'Complete your analysis autonomously. Do not fabricate information. '
        'Do not use internal terms: 子代理, dispatch, Phase, handoff, Step, manifest, spawn. '
        'CRITICAL: Limit 企查查 MCP calls to at most 15 per role (competitor verification needs multiple queries). Prioritize web_search/web_fetch for competitor info. '
        'Only use 企查查 for specific competitor verification. '
        'If you find yourself calling 企查查 repeatedly with similar queries, STOP and write your analysis with existing data.'
        '\n\nCRITICAL ANTI-DEFECT RULES:\n'
        '1. NEVER fabricate BP claims. Every "BP声称" in verification table must exist in actual BP text.\n'
        '2. Competitor list must be COMPLETE and search-verified. For each sub-segment, '
        'search "XX领域 主要厂商/竞品" to verify completeness.\n'
        '3. Competitor capability claims MUST be search-verified. Cannot claim competitors lack specific '
        'certifications/products without searching first — large international companies often have broader '
        'product lines than assumed.\n'
        '4. Financial data consistency: cannot simultaneously question data reliability AND use it for valuation. '
        'If questioning, label accordingly; if using for calc, accept the number.\n'
        '5. Comparable company selection must match business attributes. '
        'Vertical/specialized companies need vertical/specialized comps (typically higher multiples), '
        'not generic ones.\n'
        '6. Risk assessment must include mitigation factors. Supply chain risks: analyze actual tech level '
        'and domestic substitution capability, not just "supply cut = shutdown".\n'
        '7. DD priority: P0 = financial audit + customer verification + revenue split + IP validity; '
        'P1 = supply chain + agreements; P2 = toolchain backup + key-person mitigation. '
        'Each DD item must include HOW to verify, not just WHAT to check.\n'
        '8. Customer verification must be layered: strategic investors as customers '
        'have high credibility. Distinguish mass-production vs in-qualification vs unverified.\n'
        '9. SEARCH REQUIREMENT: minimum 10 independent searches per role. Model knowledge is NOT a citable source.\n'
        '10. COMPETITOR FINANCING VERIFICATION: For EVERY competitor in comparison tables, you MUST search-verify '
        'their current financing/ipo/listing status. NEVER use stale training data (e.g. "多轮融资" when company has IPO\'d). '
        'Rules: (a) If competitor is listed (A/H/US stock), use yfinance to get real-time market cap, ticker, and price. '
        'Cite ticker and data date. (b) If competitor is private, search IT桔子/36氪/企查查 for latest round. '
        'Cite source and date. (c) Financing stage column MUST show: listed→"上市公司(代码) 市值X亿"; '
        'private→"X轮 金额 来源(日期)". (d) If unable to verify after 2 searches, mark as "未验证" — never guess.\n'
        '11. VALUATION: Comparable companies must pass 3-filter (same financing stage or apply 20-30% illiquidity discount, '
        'revenue scale within 3x, same business model e.g. Fabless≠IDM). If using listed comps for private company, MUST apply illiquidity discount.\n'
        '12. VALUATION: Multiples (PS/PE etc.) MUST be anchored to specific comparable transactions or listed company data. '
        'Scarcity premium requires same-track private market deal evidence. Loss-making companies cannot be valued by PS alone.\n'
        '13. VALUATION: MUST apply 4 mandatory discounts where applicable: illiquidity (20-30% if private/unlisted), '
        'tech risk (15-25% if core specs unverified by 3rd party), key-person (10-15% if founder controls >50% voting), '
        'competition window (5-10% if differentiation moat <5yr). Report MUST show pre-discount AND post-discount valuation tables.\n'
        '14. VALUATION: MUST use at least 2 methods (PS + DCF minimum). If PS vs DCF gap >30%, explain why. '
        'PEG >2 = overvaluation signal, must flag. Discount rate for private companies should be 15%+ to reflect risk.\n'
        '15. VALUATION: Revenue split assumptions must have confidence levels (high=BP disclosed/medium=industry inferred/low=pure guess). '
        'Low-confidence splits must use ranges not point estimates. Sensitivity analysis required: if key assumption changes ±20%, how does valuation change?'
    ),
}


def _slug(role_name: str) -> str:
    return ROLE_TO_KEY.get(role_name, role_name.replace('bp_', '').replace('与', '_').replace(' ', '_'))


def notify_wx(text: str) -> bool:
    try:
        sys.path.insert(0, str(ROOT / 'scripts'))
        from longshao_notify import send_message

        result = send_message(text)
        return result.get('ok', False)
    except Exception:
        return False


def _build_brief(task_id: str, sub: dict, task_dir: Path | None = None) -> Path:
    task_dir = task_dir or TASKS_DIR / task_id
    slug = _slug(sub['role_name'])
    brief_path = task_dir / f'bp_phase2_brief_{slug}.md'

    output_rel = Path(sub['output_file'])
    try:
        output_display = str(output_rel.relative_to(ROOT))
    except Exception:
        output_display = str(output_rel)

    # 加载指令库文件（如果存在）
    instruction_content = ''
    instruction_file = INSTRUCTION_STORE / f'{sub["role_name"]}.md'
    if instruction_file.exists():
        try:
            raw = instruction_file.read_text(encoding='utf-8')
            # 去掉指令库中的内部链路描述（已过时），保留调查范围和证据分级
            cleaned_lines = []
            skip_section = False
            for line in raw.split('\n'):
                if '真实链路' in line or '当前可直接依赖的输入' in line:
                    skip_section = True
                    continue
                if skip_section and line.strip().startswith('## '):
                    skip_section = False
                if skip_section:
                    continue
                # 跳过输出文件和禁止章节（system prompt 已覆盖）
                if line.strip().startswith('## 输出文件') or line.strip().startswith('## 禁止'):
                    skip_section = True
                    continue
                cleaned_lines.append(line)
            instruction_content = '\n'.join(cleaned_lines).strip()
        except Exception:
            pass

    lines = [
        f'# BP Research Brief — {sub["role_name"]}',
        '',
        f'- Output file: `{output_display}`',
        '',
        '## 你的任务',
        '- 写一份专业的投研报告章节（对标一线 VC 研报水准）。',
        '- 先用已有输入完成初稿，再自行做 gap 检测和补充搜索。',
        '- 最终输出必须包含：分析叙事、对比表格、来源 URL。',
        '- 禁止写内部术语：子代理、dispatch、Phase、handoff、Step 0/1/2/3/4/5。',
        '- 直接把最终 Markdown 写到指定 output file。',
        '',
        '## 角色说明',
        sub.get('description', ''),
        '',
    ]

    # 注入指令库内容（调查范围、证据分级等）
    if instruction_content:
        lines += [
            '## 详细调查指引（指令库）',
            '',
            instruction_content,
            '',
        ]

    lines.append('## 关键输入文件（都在 workspace 内）')

    candidates = [
        task_dir / 'bp_ocr_text.txt',
        task_dir / 'bp_step0_profile.json',
        task_dir / 'bp_step0_profile.md',
        task_dir / 'company_verify_report.json',
        task_dir / 'bp_presearch_results.json',
    ]
    candidates += sorted(task_dir.glob('bp_presearch_step*.md'))
    candidates += sorted((task_dir / 'body_content').glob('*.json')) if (task_dir / 'body_content').exists() else []

    for p in candidates:
        if p.exists():
            lines.append(f'- `{p.relative_to(ROOT)}`')

    lines += [
        '',
        '## 子任务键值输入',
        '```json',
        json.dumps(sub.get('key_inputs', {}), ensure_ascii=False, indent=2),
        '```',
        '',
        '## ⚠️ 自主闭环规则（最高优先级）',
        '',
        '你在执行过程中必须自主闭环，不要返回主控等待指示：',
        '1. **发现数据缺口** → 自己补搜（工具优先级见下方），继续推进',
        '2. **来源不足** → 自己搜更多来源，补充到输出中',
        '3. **数据矛盾** → 自己判断哪个更可靠，标注矛盾来源',
        '4. **唯一完成条件** → 输出文件写完',
        '',
        '### 补搜工具优先级',
        '1. **企查查 MCP**（最高优先级）— 工商/风险/知产/经营结构化数据',
        '   - `mcp__qcc-company`：工商信息（股东、注册资本、法人、变更记录）',
        '   - `mcp__qcc-risk`：风险信息（诉讼、失信被执行人、行政处罚）',
        '   - `mcp__qcc-ipr`：知识产权（专利、商标、著作权）',
        '   - `mcp__qcc-operation`：经营信息（招投标、资质许可、年报）',
        '2. `web_search` — 通用搜索（DDG + SearXNG 多路合并）',
        '3. `web_fetch` — 对搜索结果做正文深度抓取',
        '4. `yfinance (Python)` — 上市公司金融数据（PE/PS/市值/财报/key statistics）',
        '',
        '### 补搜纪律',
        '- 最多补搜 3 轮，避免无限循环',
        '- 补搜结果必须标注来源 URL',
        '- 仍搜不到的标注"经 X 次搜索未找到独立来源"',
        '',
        '## 执行要求',
        '- 先读 OCR / Step0 / 工商验证 / Presearch，再补搜索。',
        '- 你的外部判断必须和来源一一对应。',
        '- 如果某点搜不到，要明确写"未找到独立外部证据"，不要编。',
        '- 直接把最终 Markdown 写到指定 output file。',
    ]

    brief_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return brief_path


def _read_brief_content(brief_path: Path) -> str:
    if not brief_path.exists():
        return ''
    text = brief_path.read_text(encoding='utf-8')
    lines = []
    for line in text.split('\n'):
        lines.append(line)
        if line.strip().startswith('- `') and line.strip().endswith('`'):
            ref = line.strip().lstrip('- `').rstrip('`')
            ref_path = ROOT / ref
            if not ref_path.exists():
                continue
            file_size = ref_path.stat().st_size
            if 'body_content' in str(ref_path):
                continue
            elif 'ocr_text' in ref_path.name:
                try:
                    content = ref_path.read_text(encoding='utf-8')[:15000]
                    lines.append(f'\n```\n{content}\n```\n')
                except Exception:
                    pass
            elif ref_path.suffix == '.json':
                try:
                    content = ref_path.read_text(encoding='utf-8')[:8000]
                    lines.append(f'\n```json\n{content}\n```\n')
                except Exception:
                    pass
            elif ref_path.suffix == '.md':
                try:
                    content = ref_path.read_text(encoding='utf-8')[:8000]
                    lines.append(f'\n```markdown\n{content}\n```\n')
                except Exception:
                    pass
            elif file_size < 5000:
                try:
                    content = ref_path.read_text(encoding='utf-8')[:3000]
                    lines.append(f'\n```\n{content}\n```\n')
                except Exception:
                    pass
    return '\n'.join(lines)[:40000]


def _spawn_one(task_id: str, sub: dict, task_dir: Path | None = None) -> dict:
    task_dir = task_dir or TASKS_DIR / task_id
    slug = _slug(sub['role_name'])
    output_path = Path(sub['output_file'])
    receipt_path = task_dir / f'bp_phase2_spawn_{slug}.json'
    manifest_path = task_dir / f'bp_phase2_manifest_{slug}.json'

    if output_path.exists() and output_path.stat().st_size > 50:
        return {'role': sub['role_name'], 'status': 'already_exists', 'output': str(output_path)}

    brief_path = _build_brief(task_id, sub, task_dir=task_dir)
    label = f'{task_id}-bp-phase2-{slug}'
    brief_content = _read_brief_content(brief_path)
    if not brief_content:
        brief_content = (
            f'Role: {sub["role_name"]}\n'
            f'Task ID: {task_id}\n'
            'Complete due diligence analysis for your assigned dimension.'
        )

    system_prompt = ROLE_SYSTEM_PROMPTS.get(sub['role_name'], ROLE_SYSTEM_PROMPTS['bp_竞争与结论'])
    manifest_data = {
        'task_id': task_id,
        'role': sub['role_name'],
        'slug': slug,
        'label': label,
        'system_prompt': system_prompt,
        'brief_path': str(brief_path),
        'brief_content_preview': brief_content[:500],
        'output_path': str(output_path),
        'timeout': 1200,
        'thinking': 'high',
        'dispatch_mode': 'team_async',
        'mode': 'bypassPermissions',
        'subagent_name': 'code-explorer',
        'team_name_template': 'bp-{task_id}',
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'status': 'pending',
    }
    manifest_path.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding='utf-8')

    receipt = {
        'task_id': task_id,
        'role': sub['role_name'],
        'label': label,
        'status': 'dispatched',
        'runId': f'wb-bp-{int(time.time())}',
        'childSessionKey': f'wb-bp-{task_id}-{slug}',
        'runtime': 'workbuddy-task',
        'thinking': 'high',
        'manifest_path': str(manifest_path),
        'output_path': str(output_path),
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'  📋 已派发 BP 子代理: {sub["role_name"]} → manifest: {manifest_path.name}')

    return {
        'role': sub['role_name'],
        'status': 'dispatched',
        'label': label,
        'runId': receipt['runId'],
        'childSessionKey': receipt['childSessionKey'],
        'output': str(output_path),
        'receipt': str(receipt_path),
        'manifest_path': str(manifest_path),
    }


def get_pending_bp_tasks(task_id: str) -> list[dict]:
    task_dir = TASKS_DIR / task_id
    pending = []
    for role_name, slug in ROLE_TO_KEY.items():
        manifest_path = task_dir / f'bp_phase2_manifest_{slug}.json'
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text(encoding='utf-8'))
            output_path = Path(data.get('output_path', ''))
            if not output_path.exists() and data.get('status') == 'pending':
                pending.append(data)
    return pending


def main():
    ap = argparse.ArgumentParser(description='BP Phase 2 Subagent Launcher — WorkBuddy 版 v4 (Task 子代理)')
    ap.add_argument('--task-id', required=True)
    ap.add_argument('--pending', action='store_true', help='List pending BP tasks for Task dispatch')
    args = ap.parse_args()

    if args.pending:
        pending = get_pending_bp_tasks(args.task_id)
        print(json.dumps(pending, ensure_ascii=False, indent=2))
        return

    task_dir = TASKS_DIR / args.task_id
    dispatch_path = task_dir / 'phase2_dispatch.json'
    if not dispatch_path.exists():
        print(json.dumps({'status': 'no_dispatch', 'task_id': args.task_id}, ensure_ascii=False))
        raise SystemExit(1)

    dispatch = json.loads(dispatch_path.read_text(encoding='utf-8'))
    subs = dispatch.get('subagents', [])
    results = []
    for sub in subs:
        results.append(_spawn_one(args.task_id, sub))
        time.sleep(1)

    dispatched = sum(1 for r in results if r.get('status') == 'dispatched')
    ok = all(r.get('status') in ('dispatched', 'already_exists') for r in results)

    if dispatched > 0:
        notify_wx(f'🐲 BP Phase2 已派发\n任务: {args.task_id}\n已派发: {dispatched}/{len(subs)} roles\n运行时: WorkBuddy Task')

    print(json.dumps({
        'task_id': args.task_id,
        'status': 'ok' if ok else 'partial',
        'results': results,
        'runtime': 'workbuddy-task',
        'pending_tasks': dispatched,
    }, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 2)




_BP_SEARCH_TEMPLATES = {
    'bp_团队与合规': [
        '"{entity}" founder background legal compliance litigation',
        '"{entity}" management governance ownership',
        '"{entity}" 创始人 合规 诉讼 管理层',
    ],
    'bp_技术与产品': [
        '"{entity}" technology product patent R&D',
        '"{entity}" product roadmap customer feedback',
        '"{entity}" 技术 产品 专利 研发',
    ],
    'bp_行业与供应链': [
        '"{entity}" industry supply chain market landscape',
        '"{entity}" upstream downstream suppliers customers',
        '"{entity}" 行业 供应链 市场 产业链',
    ],
    'bp_竞争与结论': [
        '"{entity}" competitors market share differentiation',
        '"{entity}" risk analysis investment thesis',
        '"{entity}" 竞争格局 市场份额 风险 投资逻辑',
    ],
}


def do_supplementary_search(task_id: str, role_name: str, entity: str) -> dict:
    """供主控在BP子代理质量不达标时执行补搜。"""
    templates = _BP_SEARCH_TEMPLATES.get(role_name, [])
    if not templates:
        return {'role': role_name, 'memo_path': '', 'has_results': False}

    sys.path.insert(0, str(ROOT / 'scripts'))
    from search_gateway import search as gateway_search

    memo_lines = []
    seen_urls: set[str] = set()
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
        memo_lines.append(f"## BP 补搜结果 ({len(collected)} 条)\n\n")
        for i, (query, row) in enumerate(collected[:12], 1):
            title = row.get('title', '') or ''
            url = row.get('url', '') or ''
            snippet = row.get('content', '') or row.get('snippet', '') or ''
            engine = row.get('engine', '?')
            memo_lines.append(f"### {i}. [{engine}] {title}\n")
            memo_lines.append(f"Query: {query}\n")
            memo_lines.append(f"URL: {url}\n")
            memo_lines.append(f"{snippet[:300]}\n\n")

    slug = _slug(role_name)
    memo_path = TASKS_DIR / task_id / f'bp_phase2_followup_{slug}.md'
    if memo_lines:
        memo_path.write_text(''.join(memo_lines), encoding='utf-8')
        return {'role': role_name, 'memo_path': str(memo_path), 'has_results': True}
    return {'role': role_name, 'memo_path': '', 'has_results': False}
