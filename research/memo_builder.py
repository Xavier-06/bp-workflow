"""
Research Memo Builder - Post-Audit Fix
Fix 2: Finding 质量——从 full_text 提取实质内容
Fix 3: 添加 citation [N] 引用标注
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json, re
from collections import Counter

import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.runner import ResearchState
from search.models import Evidence


@dataclass
class CitedEvidence:
    id: str
    title: str
    url: str
    domain: str
    source_type: str
    source_family: str
    is_official: bool
    is_filing: bool
    document_type: str
    published_at: str | None
    snippet: str
    confidence: str
    drop_reasons: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            'id': self.id, 'title': self.title, 'url': self.url,
            'domain': self.domain, 'source_type': self.source_type,
            'source_family': self.source_family, 'is_official': self.is_official,
            'is_filing': self.is_filing, 'document_type': self.document_type,
            'published_at': self.published_at,
            'snippet': self.snippet[:200] if self.snippet else '',
            'confidence': self.confidence, 'drop_reasons': self.drop_reasons,
        }


@dataclass
class KeyFinding:
    finding: str
    evidence_ids: list[str]
    confidence: str
    subquestion: str | None = None
    is_grounded_on_official: bool = False
    extraction_method: str = 'title_only'  # title_only / content_extracted / snippet_based
    
    def to_dict(self) -> dict:
        return {
            'finding': self.finding, 'evidence_ids': self.evidence_ids,
            'confidence': self.confidence, 'subquestion': self.subquestion,
            'is_grounded_on_official': self.is_grounded_on_official,
            'extraction_method': self.extraction_method,
        }


@dataclass
class ResearchMemo:
    title: str
    objective: str
    executive_summary: str
    key_findings: list[KeyFinding]
    evidence_gaps: list[str]
    risks_or_uncertainties: list[str]
    cited_evidence: list[CitedEvidence]
    evidence_stats: dict
    task_type: str = ''
    entity: str = ''
    rounds_used: int = 0
    stop_reason: str = ''
    generated_at: str = ''
    grounded_rate: float = 0.0
    citation_map: dict = field(default_factory=dict)  # url -> {index, title, domain, url, published_at}
    
    def to_dict(self) -> dict:
        return {
            'title': self.title, 'objective': self.objective,
            'executive_summary': self.executive_summary,
            'key_findings': [f.to_dict() for f in self.key_findings],
            'evidence_gaps': self.evidence_gaps,
            'risks_or_uncertainties': self.risks_or_uncertainties,
            'cited_evidence': [e.to_dict() for e in self.cited_evidence],
            'evidence_stats': self.evidence_stats,
            'grounded_rate': self.grounded_rate,
            'metadata': {
                'task_type': self.task_type, 'entity': self.entity,
                'rounds_used': self.rounds_used, 'stop_reason': self.stop_reason,
                'generated_at': self.generated_at,
            }
        }
    
    def to_markdown(self) -> str:
        """输出 markdown 格式的研究 memo，包含 citation 引用"""
        lines = []
        
        # 标题
        lines.append(f"# {self.title}")
        lines.append("")
        
        # 执行摘要
        lines.append("## 执行摘要")
        lines.append(self.executive_summary)
        lines.append("")
        
        # 关键发现（带 citation）
        lines.append("## 关键发现")
        if not self.key_findings:
            lines.append("_暂无关键发现_")
        else:
            for i, f in enumerate(self.key_findings, 1):
                # 获取 citation index
                citation_str = self._get_citation_string(f.evidence_ids)
                lines.append(f"{i}. {f.finding} {citation_str}")
        lines.append("")
        
        # 证据缺口
        lines.append("## 证据缺口")
        if not self.evidence_gaps:
            lines.append("_暂无明显证据缺口_")
        else:
            for gap in self.evidence_gaps:
                lines.append(f"- {gap}")
        lines.append("")
        
        # 来源
        lines.append("## 来源")
        if self.citation_map:
            # 按 index 排序
            sorted_citations = sorted(self.citation_map.values(), key=lambda x: x.get('index', 0))
            for info in sorted_citations:
                idx = info.get('index', '?')
                title = info.get('title', 'Untitled')
                url = info.get('url', '')
                domain = info.get('domain', '')
                published_at = info.get('published_at', '')
                date_part = f" ({published_at})" if published_at else ""
                lines.append(f"{idx}. [{title}]({url}) — {domain}{date_part}")
        else:
            lines.append("_无来源_")
        
        return '\n'.join(lines)
    
    def _get_citation_string(self, evidence_ids: list[str]) -> str:
        """从 evidence_ids 获取 citation 字符串，如 [1][3]"""
        if not evidence_ids or not self.citation_map:
            return ""
        
        # 构建 id -> url 的映射（需要从 cited_evidence 反推）
        id_to_url = {e.id: e.url for e in self.cited_evidence}
        
        indices = set()
        for ev_id in evidence_ids:
            url = id_to_url.get(ev_id)
            if url and url in self.citation_map:
                idx = self.citation_map[url].get('index')
                if idx:
                    indices.add(idx)
        
        if not indices:
            return ""
        
        # 排序并生成 [N][M] 格式
        sorted_indices = sorted(indices)
        return ''.join(f"[{i}]" for i in sorted_indices)


class MemoBuilder:
    """Memo 构建器 - Post-Audit Fix"""
    
    def build(self, state: ResearchState) -> ResearchMemo:
        plan = state.plan
        
        evidence_to_id: dict[str, str] = {}
        id_to_evidence: dict[str, CitedEvidence] = {}
        
        for i, ev in enumerate(state.all_evidence, 1):
            ev_id = f"ev_{i:03d}"
            evidence_to_id[ev.url] = ev_id
            id_to_evidence[ev_id] = self._convert_single_evidence(ev, ev_id)
        
        cited_evidence = list(id_to_evidence.values())
        citation_map = getattr(state, 'citation_map', {}) or {}
        self.citation_map = citation_map
        
        if plan.task_type == 'company_research':
            return self._build_company_research_memo(state, evidence_to_id, id_to_evidence, cited_evidence, citation_map)
        elif plan.task_type == 'market_news':
            return self._build_market_news_memo(state, evidence_to_id, id_to_evidence, cited_evidence, citation_map)
        else:
            return self._build_generic_memo(state, evidence_to_id, id_to_evidence, cited_evidence, citation_map)
    
    def _build_company_research_memo(self, state, evidence_to_id, id_to_evidence, cited_evidence, citation_map):
        plan = state.plan
        key_findings = []
        evidence_gaps = list(state.gap_reasons)
        
        # 构建 id -> url 映射，用于 citation
        id_to_url = {ev_id: url for url, ev_id in evidence_to_id.items()}
        
        for sq in plan.subquestions:
            sq_evidence = state.evidence_by_subquestion.get(sq, [])
            
            if sq_evidence:
                official = [e for e in sq_evidence if e.is_official]
                best = (official or sq_evidence)[:3]
                ev_ids = [evidence_to_id[e.url] for e in best if e.url in evidence_to_id]
                
                if ev_ids:
                    confidences = [id_to_evidence[eid].confidence for eid in ev_ids]
                    is_official_ground = any(id_to_evidence[eid].is_official for eid in ev_ids)
                    overall_conf = 'high' if 'high' in confidences else ('medium' if 'medium' in confidences else 'low')
                    
                    # Fix 2 + Fix 3: 从 full_text 提取实质内容 + 添加 citation
                    finding_text, extraction_method = self._extract_finding_from_evidence(
                        best, sq, plan.entity, citation_map, id_to_url
                    )
                    
                    key_findings.append(KeyFinding(
                        finding=finding_text,
                        evidence_ids=ev_ids,
                        confidence=overall_conf,
                        subquestion=sq,
                        is_grounded_on_official=is_official_ground,
                        extraction_method=extraction_method,
                    ))
                else:
                    evidence_gaps.append(f"关于「{sq[:40]}...」的证据未能正确引用")
            else:
                evidence_gaps.append(f"缺少关于「{sq[:50]}...」的直接证据")
        
        stats = self._compute_stats(cited_evidence)
        stats['answered_subquestions'] = len(key_findings)
        stats['official_evidence_count'] = sum(1 for e in cited_evidence if e.is_official)
        stats['filing_evidence_count'] = sum(1 for e in cited_evidence if e.is_filing)
        
        total = len(cited_evidence)
        grounded = stats['official_evidence_count'] + stats['filing_evidence_count']
        grounded_rate = grounded / total if total > 0 else 0.0
        
        summary = f"关于 **{plan.entity}** 的研究进行了 {state.rounds_used} 轮，收集 {len(state.all_evidence)} 条证据。"
        summary += f"\n官方/披露源: {stats['official_evidence_count']} 条 | 回答了 {len(key_findings)} 个关键问题。"
        if evidence_gaps:
            summary += f"\n⚠️ {len(evidence_gaps)} 个证据缺口。"
        
        return ResearchMemo(
            title=f"{plan.entity} 公司研究", objective=plan.objective,
            executive_summary=summary, key_findings=key_findings,
            evidence_gaps=evidence_gaps, risks_or_uncertainties=[],
            cited_evidence=cited_evidence, evidence_stats=stats,
            grounded_rate=grounded_rate, task_type=plan.task_type,
            entity=plan.entity, rounds_used=state.rounds_used,
            stop_reason=state.stop_reason or '',
            generated_at=datetime.now(timezone.utc).isoformat(),
            citation_map=citation_map,
        )
    
    def _build_market_news_memo(self, state, evidence_to_id, id_to_evidence, cited_evidence, citation_map):
        plan = state.plan
        
        primary_reports = [ev for ev in cited_evidence if ev.confidence != 'low' and ev.source_family != 'aggregator']
        aggregators = [ev for ev in cited_evidence if ev.source_family == 'aggregator']
        low_confidence = [ev for ev in cited_evidence if ev.confidence == 'low']
        
        key_findings = []
        
        # 构建 id -> url 映射
        id_to_url = {ev_id: url for url, ev_id in evidence_to_id.items()}
        
        for ev in primary_reports[:5]:
            # Fix 2 + Fix 3: 从 snippet/full_text 提取内容 + 添加 citation
            finding_text = self._extract_news_finding(ev, plan.entity, citation_map, id_to_url)
            key_findings.append(KeyFinding(
                finding=finding_text,
                evidence_ids=[ev.id], confidence=ev.confidence,
                subquestion=f"{plan.entity} 新闻",
                is_grounded_on_official=ev.is_official,
                extraction_method='content_extracted' if len(ev.snippet) > 100 else 'title_only',
            ))
        
        if not primary_reports and not aggregators:
            for ev in low_confidence[:3]:
                key_findings.append(KeyFinding(
                    finding=f"[低置信] {ev.title}",
                    evidence_ids=[ev.id], confidence='low',
                    extraction_method='title_only',
                ))
        
        evidence_gaps = list(state.gap_reasons)
        risks = [f"[低置信] {ev.title[:50]}..." for ev in low_confidence[:5]]
        
        stats = self._compute_stats(cited_evidence)
        grounded_rate = len(primary_reports) / len(cited_evidence) if cited_evidence else 0.0
        
        summary = f"关于 **{plan.entity}** 的新闻研究收集 {len(state.all_evidence)} 条。"
        summary += f"\n原始报道: {len(primary_reports)} | 转载: {len(aggregators)} | 低置信: {len(low_confidence)}"
        
        return ResearchMemo(
            title=f"{plan.entity} 新闻摘要", objective=plan.objective,
            executive_summary=summary, key_findings=key_findings,
            evidence_gaps=evidence_gaps, risks_or_uncertainties=risks,
            cited_evidence=cited_evidence, evidence_stats=stats,
            grounded_rate=grounded_rate, task_type=plan.task_type,
            entity=plan.entity, rounds_used=state.rounds_used,
            stop_reason=state.stop_reason or '',
            generated_at=datetime.now(timezone.utc).isoformat(),
            citation_map=citation_map,
        )
    
    def _build_generic_memo(self, state, evidence_to_id, id_to_evidence, cited_evidence, citation_map):
        plan = state.plan
        key_findings = [KeyFinding(finding=ev.title[:80], evidence_ids=[ev.id], confidence=ev.confidence) for ev in cited_evidence[:5]]
        stats = self._compute_stats(cited_evidence)
        return ResearchMemo(
            title=f"{plan.entity} 研究", objective=plan.objective,
            executive_summary=f"收集 {len(state.all_evidence)} 条证据。",
            key_findings=key_findings, evidence_gaps=state.unanswered_subquestions,
            risks_or_uncertainties=[], cited_evidence=cited_evidence,
            evidence_stats=stats, grounded_rate=0.0, task_type=plan.task_type,
            entity=plan.entity, rounds_used=state.rounds_used,
            stop_reason=state.stop_reason or '',
            generated_at=datetime.now(timezone.utc).isoformat(),
            citation_map=citation_map,
        )
    
    # ===== Fix 2: 从 full_text 提取实质内容 =====
    # ===== Fix 3: 添加 citation [N] 引用标注 =====
    
    def _get_citation_indices(self, evidence_list: list[Evidence], id_to_url: dict) -> list[int]:
        """从 evidence 列表获取 citation index"""
        indices = []
        for ev in evidence_list:
            url = getattr(ev, 'url', None)
            if url and url in self.citation_map:
                idx = self.citation_map[url].get('index')
                if idx:
                    indices.append(idx)
        return sorted(set(indices))
    
    def _format_citation(self, indices: list[int]) -> str:
        """格式化 citation 字符串，如 [1][3]"""
        if not indices:
            return ""
        return ''.join(f"[{i}]" for i in sorted(set(indices)))
    
    def _extract_finding_from_evidence(
        self, 
        evidence_list: list[Evidence], 
        question: str, 
        entity: str,
        citation_map: dict,
        id_to_url: dict
    ) -> tuple[str, str]:
        """从 evidence 的 full_text 提取实质内容，而不是只引用标题"""
        if not evidence_list:
            return f"关于「{question[:40]}...」暂无足够证据", 'no_evidence'
        
        best = evidence_list[0]
        full_text = best.full_text or best.snippet or ''
        domain = best.domain or ''
        is_official = getattr(best, 'is_official', False)
        source_label = "[官方] " if is_official else ""
        
        # 获取 citation
        indices = self._get_citation_indices(evidence_list, id_to_url)
        citation_str = self._format_citation(indices)
        
        # 尝试从 full_text 提取有意义的句子
        if full_text and len(full_text) > 200:
            excerpt = self._extract_key_sentences(full_text, entity, question)
            if excerpt and len(excerpt) > 50:
                finding = f"{source_label}来源 {domain}：{excerpt} {citation_str}".strip()
                return finding, 'content_extracted'
        
        # 如果 snippet 有内容
        if best.snippet and len(best.snippet) > 80:
            snippet_clean = best.snippet[:200].strip()
            finding = f"{source_label}来源 {domain}：{snippet_clean} {citation_str}".strip()
            return finding, 'snippet_based'
        
        # Fallback: 标题
        finding = f"{source_label}来源 {domain}：{best.title} {citation_str}".strip()
        return finding, 'title_only'
    
    def _extract_key_sentences(self, text: str, entity: str, question: str) -> str:
        """从正文中提取与问题相关的关键句子"""
        # 清理文本
        text = re.sub(r'\s+', ' ', text).strip()
        
        # 按句子分割
        sentences = re.split(r'[。.!！？?\n]', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
        
        if not sentences:
            return ''
        
        # 提取与实体和问题相关的句子
        entity_lower = entity.lower()
        question_lower = question.lower()
        
        # 问题关键词
        q_keywords = set()
        for kw in ['业务', '产品', '服务', '收入', '利润', '风险', '争议', '事件', '动态',
                    'business', 'product', 'revenue', 'profit', 'risk', 'event']:
            if kw in question_lower:
                q_keywords.add(kw)
        
        scored = []
        for sent in sentences[:50]:  # 只看前 50 句
            sent_lower = sent.lower()
            score = 0
            
            # 包含实体名
            if entity_lower in sent_lower:
                score += 3
            
            # 包含问题关键词
            for kw in q_keywords:
                if kw in sent_lower:
                    score += 2
            
            # 包含数字（可能是关键数据）
            if re.search(r'\d+', sent):
                score += 1
            
            # 句子长度合理
            if 30 < len(sent) < 200:
                score += 1
            
            if score > 0:
                scored.append((score, sent))
        
        if not scored:
            # 没有匹配的句子，取前几句
            return '; '.join(sentences[:2])[:300]
        
        # 取得分最高的 1-2 句
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:2]
        result = '; '.join(s for _, s in top)
        
        return result[:300]
    
    def _extract_news_finding(
        self, 
        ev: CitedEvidence, 
        entity: str,
        citation_map: dict,
        id_to_url: dict
    ) -> str:
        """从新闻 evidence 提取 finding"""
        source_label = f"[{ev.source_family}]" if ev.source_family != 'other' else ''
        
        # 获取 citation
        indices = []
        if ev.url in citation_map:
            idx = citation_map[ev.url].get('index')
            if idx:
                indices.append(idx)
        citation_str = self._format_citation(indices)
        
        if ev.snippet and len(ev.snippet) > 100:
            # 从 snippet 提取前 200 字符
            excerpt = ev.snippet[:200].strip()
            finding = f"{source_label} {ev.title[:60]} — {excerpt} {citation_str}".strip()
            return finding
        
        finding = f"{source_label} {ev.title} {citation_str}".strip()
        return finding
    
    def _convert_single_evidence(self, ev: Evidence, ev_id: str) -> CitedEvidence:
        return CitedEvidence(
            id=ev_id, title=ev.title, url=ev.url,
            domain=ev.domain or '', source_type=ev.source_type or 'other',
            source_family=getattr(ev, 'source_family', 'other'),
            is_official=getattr(ev, 'is_official', False),
            is_filing=getattr(ev, 'is_filing', False),
            document_type=getattr(ev, 'document_type', ''),
            published_at=ev.published_at, snippet=ev.snippet or '',
            confidence=getattr(ev, 'confidence', 'low'),
            drop_reasons=ev.drop_reasons.copy() if ev.drop_reasons else [],
        )
    
    def _compute_stats(self, cited_evidence: list[CitedEvidence]) -> dict:
        conf_counts = Counter(e.confidence for e in cited_evidence)
        source_counts = Counter(e.source_family for e in cited_evidence)
        return {
            'total': len(cited_evidence),
            'high_confidence': conf_counts.get('high', 0),
            'medium_confidence': conf_counts.get('medium', 0),
            'low_confidence': conf_counts.get('low', 0),
            'source_types': dict(source_counts),
        }


def build_memo(state: ResearchState) -> ResearchMemo:
    return MemoBuilder().build(state)