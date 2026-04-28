"""
Source Gate - Phase 2A.1
任务级可信源门槛检查
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@dataclass
class GateResult:
    """门禁检查结果"""
    passed: bool
    official_source_missing: bool = False
    secondary_only: bool = False
    gaps: list[str] = None
    warnings: list[str] = None
    
    def __post_init__(self):
        if self.gaps is None:
            self.gaps = []
        if self.warnings is None:
            self.warnings = []


class SourceGate:
    """
    源门禁检查
    
    职责：
    1. 检查是否满足最低可信源门槛
    2. 标记 missing sources
    3. 强制暴露不确定性
    """
    
    # company_research 最低可信源类型
    COMPANY_MIN_TRUSTED_SOURCES = {'official', 'ir', 'filing', 'newsroom'}
    
    # market_news 最低可信源类型
    NEWS_MIN_TRUSTED_SOURCES = {'primary_wire', 'trusted_news', 'official_newsroom', 'newsroom'}
    
    def check_company_research(self, evidence_list: list, findings: list) -> GateResult:
        """检查 company_research 门禁"""
        gaps = []
        warnings = []
        
        # 统计源类型
        source_families = set()
        official_count = 0
        ir_count = 0
        filing_count = 0
        newsroom_count = 0
        aggregator_count = 0
        
        for ev in evidence_list:
            family = getattr(ev, 'source_family', 'other')
            source_families.add(family)
            
            if getattr(ev, 'is_official', False):
                official_count += 1
            if family == 'ir':
                ir_count += 1
            if family == 'filing' or getattr(ev, 'is_filing', False):
                filing_count += 1
            if family == 'newsroom':
                newsroom_count += 1
            if family == 'aggregator':
                aggregator_count += 1
        
        # 检查是否有可信源
        has_trusted = (
            official_count > 0 or
            ir_count > 0 or
            filing_count > 0 or
            newsroom_count > 0
        )
        
        official_source_missing = not has_trusted
        
        # 如果没有可信源
        if official_source_missing:
            gaps.append("缺少官方来源（IR/官网/披露）支撑，核心 findings 可能不可靠")
            warnings.append("当前证据仅来自非官方来源，不应作为投资决策依据")
        
        # 如果主要是聚合站
        if aggregator_count > 0 and aggregator_count >= len(evidence_list) * 0.8:
            gaps.append("主要证据来自聚合平台，缺少原始来源确认")
            warnings.append("聚合平台内容可能存在偏差或过时")
        
        # 检查 findings 是否有可信源支撑
        for finding in findings:
            if not getattr(finding, 'is_grounded_on_official', False):
                if "未挂载官方证据" not in str(gaps):
                    gaps.append("部分 key findings 未挂载官方证据")
                    break
        
        passed = has_trusted
        
        return GateResult(
            passed=passed,
            official_source_missing=official_source_missing,
            secondary_only=not has_trusted and len(evidence_list) > 0,
            gaps=gaps,
            warnings=warnings,
        )
    
    def check_market_news(self, evidence_list: list, findings: list) -> GateResult:
        """检查 market_news 门禁"""
        gaps = []
        warnings = []
        
        # 统计源类型
        primary_count = 0
        official_count = 0
        aggregator_count = 0
        missing_time_count = 0
        
        for ev in evidence_list:
            if getattr(ev, 'is_primary', False) or getattr(ev, 'is_official', False):
                primary_count += 1
            if getattr(ev, 'is_official', False):
                official_count += 1
            if getattr(ev, 'source_family', '') == 'aggregator':
                aggregator_count += 1
            if not getattr(ev, 'published_at', None):
                missing_time_count += 1
        
        # 检查是否有原始报道
        has_primary = primary_count > 0 or official_count > 0
        
        secondary_only = not has_primary and len(evidence_list) > 0
        
        if secondary_only:
            gaps.append("缺少原始报道或官方公告，仅有转载/聚合来源")
            warnings.append("当前新闻未找到原始出处，可信度有限")
        
        if missing_time_count > 0:
            warnings.append(f"{missing_time_count} 条新闻缺失发布时间，时效性不确定")
        
        # 如果主要是聚合站
        if aggregator_count >= len(evidence_list) * 0.6:
            gaps.append("主要来源为聚合平台，建议查找原始报道")
        
        passed = has_primary
        
        return GateResult(
            passed=passed,
            official_source_missing=not official_count,
            secondary_only=secondary_only,
            gaps=gaps,
            warnings=warnings,
        )
    
    def check(self, task_type: str, evidence_list: list, findings: list) -> GateResult:
        """执行门禁检查"""
        if task_type == 'company_research':
            return self.check_company_research(evidence_list, findings)
        elif task_type == 'market_news':
            return self.check_market_news(evidence_list, findings)
        else:
            return GateResult(passed=True)


# 全局实例
_gate: SourceGate | None = None

def get_gate() -> SourceGate:
    global _gate
    if _gate is None:
        _gate = SourceGate()
    return _gate