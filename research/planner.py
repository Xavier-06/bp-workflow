"""
Research Planner V2 - 官方披露导向版
company_research 强化官方源查询
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal
import re


@dataclass
class ResearchPlan:
    """研究计划"""
    task_type: Literal['company_research', 'market_news']
    user_query: str
    entity: str  # 研究主体
    market: str  # 市场: us, hk, cn, generic
    objective: str  # 研究目标
    subquestions: list[str]  # 子问题列表
    required_evidence_types: list[str]  # 需要的证据类型
    freshness_hours: int  # 时效窗口
    max_rounds: int  # 最大轮数
    stop_conditions: list[str]  # 停止条件
    
    # 查询模板
    query_templates: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            'task_type': self.task_type,
            'user_query': self.user_query,
            'entity': self.entity,
            'market': self.market,
            'objective': self.objective,
            'subquestions': self.subquestions,
            'required_evidence_types': self.required_evidence_types,
            'freshness_hours': self.freshness_hours,
            'max_rounds': self.max_rounds,
            'stop_conditions': self.stop_conditions,
            'query_templates': self.query_templates,
        }


class ResearchPlanner:
    """研究计划生成器 V2"""
    
    def plan(self, task_type: str, query: str, **kwargs) -> ResearchPlan:
        """生成研究计划"""
        if task_type == 'company_research':
            return self._plan_company_research(query, **kwargs)
        elif task_type == 'market_news':
            return self._plan_market_news(query, **kwargs)
        else:
            raise ValueError(f"Unknown task_type: {task_type}")
    
    def _plan_company_research(self, query: str, **kwargs) -> ResearchPlan:
        """
        公司研究计划 - 官方披露导向
        
        固定 4 个子问题：
        1. 主体是谁 / 做什么
        2. 最近 6-12 个月关键事件
        3. 风险 / 争议 / 不确定性
        4. 当前证据缺口
        
        查询模板强化官方披露导向：
        - 官网 / 公司简介
        - Investor Relations
        - Annual / Quarterly report
        - Earnings release / transcript
        - Regulator / exchange disclosure
        """
        entity = kwargs.get('entity') or self._extract_entity(query)
        market = kwargs.get('market') or self._infer_market(entity)
        
        # 固定 4 个子问题
        subquestions = [
            f"{entity} 是什么公司，主要做什么业务，业务模式和收入来源是什么",
            f"{entity} 最近 6-12 个月有哪些重要事件、业绩发布或战略调整",
            f"{entity} 当前面临哪些主要风险、争议或不确定性",
            f"关于 {entity} 还有哪些关键信息缺失，需要进一步核实",
        ]
        
        # 官方披露导向查询模板
        query_templates = self._build_official_queries(entity, market)
        
        required_evidence_types = [
            'company_overview',
            'official_disclosure',  # 官方披露
            'investor_relations',   # IR 资料
            'financial_statements', # 财务报表
            'earnings_transcript',  # 财报电话会
            'regulatory_filing',    # 监管文件
            'news_coverage',        # 新闻报道
        ]
        
        return ResearchPlan(
            task_type='company_research',
            user_query=query,
            entity=entity,
            market=market,
            objective=f"全面了解 {entity} 的基本面、官方披露、近期动态和风险点",
            subquestions=subquestions,
            required_evidence_types=required_evidence_types,
            freshness_hours=kwargs.get('freshness_hours', 720),  # 30天
            max_rounds=kwargs.get('max_rounds', 2),
            stop_conditions=[
                'all_key_questions_answered',
                'max_rounds_reached',
                'no_new_evidence',
            ],
            query_templates=query_templates,
        )
    
    def _build_official_queries(self, entity: str, market: str) -> list[str]:
        """构建官方披露导向的查询模板"""
        queries = []
        
        # 1. 官网 / 公司简介
        queries.append(f"{entity} 官网 公司简介 about")
        
        # 2. Investor Relations
        queries.append(f"{entity} investor relations IR")
        
        # 3. 年报 / 季报
        queries.append(f"{entity} annual report 10-K quarterly 10-Q")
        
        # 4. 财报发布 / 电话会
        queries.append(f"{entity} earnings release transcript call")
        
        # 5. 监管披露（按市场）
        if market == 'us':
            queries.append(f"{entity} SEC filing 8-K 10-K")
        elif market == 'hk':
            queries.append(f"{entity} HKEX announcement disclosure")
        elif market == 'cn':
            queries.append(f"{entity} 公告 披露 巨潮资讯")
        else:
            queries.append(f"{entity} announcement disclosure")
        
        # 6. 最新动态
        queries.append(f"{entity} 新闻 最新动态")
        
        # 7. 风险 / 争议
        queries.append(f"{entity} 风险 争议 litigation lawsuit")
        
        return queries
    
    def _plan_market_news(self, query: str, **kwargs) -> ResearchPlan:
        """
        市场新闻计划
        
        3 个子问题：
        1. 最近时效窗口内有哪些新闻事件
        2. 哪些是原始报道，哪些是转载
        3. 当前还缺哪类确认来源
        """
        entity = kwargs.get('entity') or self._extract_entity(query)
        market = kwargs.get('market') or self._infer_market(entity)
        
        subquestions = [
            f"{entity} 最近有哪些重要新闻或事件",
            f"{entity} 相关新闻中哪些是原始报道，哪些是转载",
            f"{entity} 的新闻来源中哪些可信度较高",
        ]
        
        query_templates = [
            f"{entity} 新闻",
            f"{entity} 最新消息 最新进展",
            f"{entity} 发布 宣布 报道",
        ]
        
        required_evidence_types = [
            'news_article',
            'official_announcement',
            'media_coverage',
        ]
        
        return ResearchPlan(
            task_type='market_news',
            user_query=query,
            entity=entity,
            market=market,
            objective=f"了解 {entity} 最近的重要新闻事件",
            subquestions=subquestions,
            required_evidence_types=required_evidence_types,
            freshness_hours=kwargs.get('freshness_hours', 72),  # 3天
            max_rounds=kwargs.get('max_rounds', 2),
            stop_conditions=[
                'all_key_questions_answered',
                'max_rounds_reached',
                'no_new_evidence',
            ],
            query_templates=query_templates,
        )
    
    def _extract_entity(self, query: str) -> str:
        """从查询中提取研究主体"""
        import re
        # 先尝试识别股票代码 e.g. (6969.HK) or 6969.HK
        ticker_match = re.search(r'([\w一-龥]+)\s*[（(]?\d{3,5}\.[A-Z]{2,}[）)]?', query)
        if ticker_match:
            return ticker_match.group(1).strip()
        
        stop_words = ['研究', '分析', '调查', '了解', '查看', '看看', '做一下',
                      '新闻', '最近', '最新', '动态', '情况', '基本面', '财报',
                      '年报', '季报', '深度研报', '研报', '深度', '报告',
                      '业务和财务状况', '财务状况', '业务状况', '最新业务',
                      '业务', '状况', '进展', '概况', '简介', '介绍',
                      'news', 'research', 'analysis', 'recent', 'latest',
                      '2024', '2025', '2026', '2023', 'Q1', 'Q2', 'Q3', 'Q4',
                      'FY2024', 'FY2025', 'FY2023']
        
        entity = query
        for word in stop_words:
            entity = entity.replace(word, '')
        
        # 如果结果含空格，取第一个词（通常是公司名）
        entity = entity.strip()
        if ' ' in entity:
            entity = entity.split()[0]
        
        return entity if entity else query
    
    def _infer_market(self, entity: str) -> str:
        """推断市场"""
        us_keywords = ['Google', 'Microsoft', 'Apple', 'Amazon', 'Meta', 'Tesla', 'Nvidia', 'NVIDIA', 'OpenAI', 'Anthropic', 'Netflix', 'Disney']
        hk_keywords = ['腾讯', '阿里巴巴', '美团', '小米', '比亚迪', '京东', '百度']
        cn_keywords = ['华为', '字节跳动', '大疆', '宁德时代']
        
        for kw in us_keywords:
            if kw.lower() in entity.lower():
                return 'us'
        
        for kw in hk_keywords:
            if kw in entity:
                return 'hk'
        
        for kw in cn_keywords:
            if kw in entity:
                return 'cn'
        
        return 'generic'


def plan_research(task_type: str, query: str, **kwargs) -> ResearchPlan:
    """便捷函数"""
    planner = ResearchPlanner()
    return planner.plan(task_type, query, **kwargs)