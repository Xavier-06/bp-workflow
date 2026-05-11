#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

GENERIC_QUERY_TEMPLATES = {
    '专题研究类': [
        '{topic} 市场规模 增长率',
        '{topic} 主要公司 龙头 上市公司',
        '{topic} 政策 监管 技术',
        '{topic} 行业报告 投资逻辑',
    ],
    '晨报类': [
        '{topic} 最新 新闻 公告',
        '{topic} 过去24小时 价格 事件',
    ],
}

COMPANY_REPORT_TEMPLATES = [
    '{canonical} FY2026 Q4 revenue gross margin datacenter',
    '{canonical} Blackwell Rubin shipment 2026',
    '{canonical} valuation target Goldman Sachs JPMorgan March 2026',
    '{canonical} China export restriction impact 2026',
    '{canonical} GTC 2026 inference agentic AI',
]

SOURCE_HINTS_GENERIC = [
    '行业研究综述 / 券商公开摘要',
    '公司官网 / 产品介绍 / 投资者关系页面',
    '政策文件 / 协会 / 政府公开资料',
    '主流媒体 / 专业行业媒体',
    '公告 / 财报 / 路演纪要公开摘录',
]

SOURCE_HINTS_COMPANY = [
    '公司 IR / 财报 / 业绩会纪要',
    'Reuters / AP / TechCrunch / The Next Web 等时效媒体',
    'Goldman Sachs / JPMorgan / 券商公开摘要或二手报道',
    'GTC / 产品发布会 / 公司新闻稿',
    '监管 / 出口限制 / 供应链跟踪材料',
]

TESTLIKE_PATTERNS = [
    '压测', '测试', '验证', '接线', '主链接', 'execution loop', 'instruction-guided', 'wiring', 'reviewer'
]
SECTOR_HINTS = ['赛道', '行业', '市场', '支付', '半导体', '医药', '机器人', '软件', 'saas', '消费', '银行', '新能源', '稳定币', '电子烟', '雾化', '烟草', '潮玩', '盲盒', '玩具', 'IP', '文创', '零售', '电商', '互联网']


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def normalize_topic(query: str) -> str:
    q = query.strip()
    q = re.sub(r'^(做一份|做个|写一份|帮我做一份)\s*', '', q)
    q = re.sub(r'(深度分析研报|深度分析|研究框架|研究报告|研究|框架版|框架|memo|报告)$', '', q).strip()
    q = q.replace('赛道', '').replace('行业', '').strip()
    q = re.sub(r'\s+', ' ', q)
    return q or query.strip()


def detect_company_profile(topic: str) -> dict | None:
    t = topic.lower()
    if '泡泡玛特' in topic or 'popmart' in t or '9992' in t:
        return {
            'canonical': 'PopMart 9992.HK 泡泡玛特',
            'name': '泡泡玛特',
            'ticker': '9992.HK',
            'market': 'hk',
            'sector': '潮玩/盲盒/消费品',
            'kind': '公司深度',
            'expected_sections': ['市场数据', '行业分析', '商业模式', '财务与估值', '管理层', '差异化洞察', '风险催化'],
        }
    if '英伟达' in topic or 'nvidia' in t or 'nvda' in t:
        return {
            'canonical': 'NVIDIA NVDA 英伟达',
            'name': '英伟达',
            'kind': 'company-report',
            'expected_sections': [
                '财务表现 / 分部结构',
                '产品路线图 / 供给节奏',
                '估值 / 目标价',
                '竞争 / 出口限制 / 风险催化',
                '关键来源清单',
            ],
        }
    if '思摩尔' in topic or 'smoore' in t or '6969' in t:
        return {
            'canonical': 'Smoore 6969.HK 思摩尔国际',
            'name': '思摩尔国际',
            'kind': 'company-report',
            'expected_sections': [
                '收入与毛利率驱动 / 分业务结构',
                '监管变化与产品结构迁移',
                '业绩指引与估值区间',
                '竞争格局 / 风险催化',
                '关键来源清单',
            ],
        }
    return None


def validate_research_query(query: str, topic: str, company: dict | None) -> dict:
    q = (query or '').strip().lower()
    t = (topic or '').strip().lower()
    if any(k in q for k in TESTLIKE_PATTERNS):
        return {
            'ok': False,
            'reason': 'query 是压测/接线/验证描述，不是可直接进入搜索的研究题目',
            'action': '先明确标的、研究目标、范围，再生成搜索计划',
        }
    if company:
        return {'ok': True, 'reason': '', 'action': ''}
    if len(topic.strip()) < 3:
        return {
            'ok': False,
            'reason': 'topic 过短，研究对象不明确',
            'action': '至少明确标的名或赛道名',
        }
    if not any(h in query for h in SECTOR_HINTS) and not any(h in t for h in SECTOR_HINTS):
        return {
            'ok': False,
            'reason': 'query 缺少明确行业/标的提示，容易泛搜失焦',
            'action': '补充“研究对象 + 范围 + 重点问题”',
        }
    return {'ok': True, 'reason': '', 'action': ''}


def build_sub_questions(query: str, topic: str, company: dict | None) -> list[str]:
    if company:
        return [
            f'{company["name"]} 当前收入与毛利率的核心驱动是什么？',
            f'{company["name"]} Blackwell / Rubin 路线图和供给节奏会如何影响后续增长？',
            f'市场当前如何给 {company["name"]} 估值，主要分歧点在哪里？',
            f'中国出口限制、竞争格局、客户自研对 {company["name"]} 的风险有多大？',
            f'{company["name"]} 接下来 6-12 个月最关键的催化剂是什么？',
        ]
    return [
        f'{topic} 的市场规模、增长率和主要驱动是什么？',
        f'{topic} 的关键玩家和可比公司是谁？',
        f'{topic} 当前最重要的政策、监管或技术变化是什么？',
        f'{topic} 的核心投资逻辑和主要风险分别是什么？',
    ]


def build_query_groups(topic: str, company: dict | None) -> list[dict]:
    if company:
        canonical = company['canonical']
        return [
            {
                'sub_question': f'{company["name"]} 当前收入与毛利率的核心驱动是什么？',
                'queries': [
                    f'{canonical} investor relations earnings call transcript guidance gross margin data center demand China revenue exposure',
                    f'{canonical} FY2026 Q4 revenue gross margin datacenter site:investor.nvidia.com OR site:reuters.com OR site:cnbc.com',
                ],
            },
            {
                'sub_question': f'{company["name"]} Blackwell / Rubin 路线图和供给节奏会如何影响后续增长？',
                'queries': [
                    f'{canonical} Blackwell Rubin shipment 2026 site:investor.nvidia.com OR site:reuters.com',
                    f'{canonical} roadmap Blackwell Rubin supply availability 2026 site:investor.nvidia.com OR site:ft.com OR site:bloomberg.com',
                ],
            },
            {
                'sub_question': f'市场当前如何给 {company["name"]} 估值，主要分歧点在哪里？',
                'queries': [
                    'NVIDIA consensus price target FY2027 EPS estimate forward P/E EV/EBITDA site:reuters.com OR site:bloomberg.com OR site:wsj.com',
                    'NVIDIA valuation model DCF sensitivity data center growth gross margin capex assumptions FY2027 FY2028',
                    'NVDA analyst notes target price raised lowered after earnings Blackwell Rubin supply constraints',
                ],
            },
            {
                'sub_question': f'中国出口限制、竞争格局、客户自研对 {company["name"]} 的风险有多大？',
                'queries': [
                    'NVIDIA U.S. export controls China H20 H200 BIS rule update impact revenue scenario analysis Reuters Bloomberg',
                    'NVIDIA competition from AMD MI400 MI350 Google TPU AWS Trainium custom ASIC market share data center AI',
                    'NVIDIA antitrust regulatory scrutiny bundling CUDA lock-in DOJ EU inquiry',
                ],
            },
            {
                'sub_question': f'{company["name"]} 接下来 6-12 个月最关键的催化剂是什么？',
                'queries': [
                    'NVIDIA key catalysts GTC product roadmap Blackwell ramp Rubin launch enterprise AI adoption inflection',
                    'NVIDIA cloud capex trend hyperscalers Microsoft Meta Amazon Google AI infrastructure spending guidance 2026',
                    'NVIDIA supply chain risk CoWoS HBM SK hynix Samsung Micron bottleneck timeline 2026 2027',
                ],
            },
        ]
    return [
        {
            'sub_question': f'{topic} 的市场规模、增长率和主要驱动是什么？',
            'queries': [f'{topic} 市场规模 增长率', f'{topic} 行业报告 投资逻辑'],
        },
        {
            'sub_question': f'{topic} 的关键玩家和可比公司是谁？',
            'queries': [f'{topic} 主要公司 龙头 上市公司', f'{topic} 可比公司 竞争格局'],
        },
        {
            'sub_question': f'{topic} 当前最重要的政策、监管或技术变化是什么？',
            'queries': [f'{topic} 政策 监管 技术', f'{topic} 最新 新闻 公告'],
        },
        {
            'sub_question': f'{topic} 的核心投资逻辑和主要风险分别是什么？',
            'queries': [f'{topic} 投资逻辑 风险', f'{topic} 催化剂 风险'],
        },
    ]


def build_plan(subtask: dict) -> dict:
    query = subtask.get('context', {}).get('query', '')
    task_type = subtask.get('context', {}).get('task_type', '专题研究类')
    topic = normalize_topic(query)
    company = detect_company_profile(topic)
    validation = validate_research_query(query, topic, company)

    query_groups = build_query_groups(topic, company)
    sub_questions = build_sub_questions(query, topic, company)
    search_queries = []
    for group in query_groups:
        search_queries.extend(group.get('queries', []))

    if company:
        source_hints = SOURCE_HINTS_COMPANY
        expected_sections = company['expected_sections']
        search_mode = company['kind']
        notes = '这是公司深度研报专用搜索计划，优先搜财报/IR/权威媒体/券商观点，而不是泛行业模板词。'
    else:
        source_hints = SOURCE_HINTS_GENERIC
        expected_sections = [
            '市场规模 / 增长',
            '关键玩家 / 可比公司',
            '政策 / 技术变化',
            '初步来源清单',
        ]
        search_mode = 'generic-research'
        notes = '这是给 data-collection 子任务使用的第一轮搜索计划，不代表最终结论。'

    return {
        'subtask_id': subtask.get('subtask_id'),
        'task_id': subtask.get('task_id'),
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'topic': topic,
        'original_query': query,
        'search_mode': search_mode,
        'sub_questions': sub_questions,
        'query_groups': query_groups,
        'search_queries': search_queries,
        'source_hints': source_hints,
        'expected_sections': expected_sections,
        'notes': notes,
        'validation': validation,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('subtask_id')
    args = ap.parse_args()

    subtasks_json = TASKS_DIR / f"{args.subtask_id.split('-S')[0]}-subtasks.json"
    if not subtasks_json.exists():
        raise SystemExit(f'subtasks file not found: {subtasks_json}')
    data = load_json(subtasks_json)
    subtask = next((s for s in data.get('subtasks', []) if s.get('subtask_id') == args.subtask_id), None)
    if not subtask:
        raise SystemExit(f'subtask not found: {args.subtask_id}')

    plan = build_plan(subtask)
    out_path = TASKS_DIR / f'{args.subtask_id}-search-plan.json'
    out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not plan.get('validation', {}).get('ok'):
        print(json.dumps({'subtask_id': args.subtask_id, 'search_plan': str(out_path), 'validation': plan.get('validation')}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    print(json.dumps({'subtask_id': args.subtask_id, 'search_plan': str(out_path)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
