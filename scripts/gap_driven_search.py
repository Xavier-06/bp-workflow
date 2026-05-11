#!/usr/bin/env python3
"""
BP 尽调 Gap-Driven Deep Research — 针对缺口做深钻搜索
零 API 费用：SearXNG + DDG
+ 可选 LLM 查询改写（千问，第2轮起自动触发）

升级 (2026-04-03):
  - 传入 evidence_snippets 给 LLM 改写，质量更高
  - 利用 body_content/extracted_facts.json 做结构化证据

用法：
  python3 scripts/gap_driven_search.py --task-id TASK-XXX [--max-rounds 3] [--llm-rewrite]

工作流程：
  1. 读 Gap 搜索清单
  2. 执行针对性搜索（SearXNG → DDG fallback）
  3. 追加结果到 bp_gap_driven_results.json
  4. 调用 gap_detector.py 重新评级
  5. IF LLM 改写 → 用千问分析证据盲区，生成补查查询
  6. 如果仍不足且未达轮次上限 → 再次深钻
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path
from datetime import datetime

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / 'tasks'
SCRIPTS_DIR = WORKSPACE / 'scripts'

sys.path.insert(0, str(SCRIPTS_DIR))
try:
    from search_gateway import search as do_search
except ImportError:
    # Fallback: 直接调旧脚本 (向后兼容)
    try:
        from searxng_search import search as _searx_search
        def ddgs_search(query: str, max_results: int = 8) -> list:
            import subprocess, json
            try:
                r = subprocess.run(['/opt/homebrew/bin/ddgs','text','-k',query,'-m',str(max_results)], capture_output=True, text=True, timeout=30)
                if r.returncode == 0 and r.stdout.strip():
                    return json.loads(r.stdout)
            except Exception:
                pass
            return []
        def do_search(query: str, max_results: int = 8) -> list:
            try:
                return _searx_search(query, max_results=max_results, timeout=25)
            except Exception:
                pass
            return ddgs_search(query, max_results)
    except ImportError:
        def do_search(query: str, max_results: int = 8) -> list:
            return []


def _load_body_content_snippets(task_dir: Path) -> list:
    """
    从两个来源加载已有证据摘要：
    1. body_content/extracted_facts.json（LLM 抽取的结构化事实，最优先）
    2. 搜索结果的 snippet
    """
    facts_path = task_dir / "body_content" / "extracted_facts.json"
    if facts_path.exists():
        try:
            with open(facts_path, encoding='utf-8') as f:
                facts = json.load(f)
            summaries = []
            for fact in facts:
                s = f"[{fact.get('authority','')}] {fact.get('source_domain','')} — "
                s += fact.get('summary', '')
                if fact.get('financials'):
                    for fin in fact['financials'][:3]:
                        s += f" | {fin.get('type','')}: {fin.get('value','')}"
                if fact.get('market_data'):
                    for md in fact['market_data'][:3]:
                        s += f" | {md.get('metric','')}: {md.get('value','')}"
                summaries.append(s)
            return summaries
        except Exception:
            pass
    return []


def load_gap_queries(task_dir: Path) -> list:
    """从 bp_gap_queries.md 加载缺口查询"""
    gap_md = task_dir / 'bp_gap_queries.md'
    if not gap_md.exists():
        return []

    queries = []
    with open(gap_md, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            m = re.match(r'^\d+\.\s+(.+)', line)
            if m:
                queries.append(m.group(1).strip())

    return queries


def load_existing_results(task_dir: Path) -> list:
    """加载已有搜索结果，用于增量追加"""
    results_file = task_dir / 'bp_gap_driven_results.json'
    if results_file.exists():
        with open(results_file, encoding='utf-8') as f:
            return json.load(f)
    return []


def deep_drill(task_id: str, max_rounds: int = 3, llm_rewrite: bool = True) -> dict:
    task_dir = TASKS_DIR / task_id

    # 预加载 LLM 抽取的结构化事实
    fact_snippets = _load_body_content_snippets(task_dir)
    if fact_snippets:
        print(f"  📋 已有 LLM 抽取事实: {len(fact_snippets)} 条")

    for round_num in range(1, max_rounds + 1):
        gap_queries = load_gap_queries(task_dir)

        if not gap_queries:
            print(f"  ✅ 第{round_num}轮：无 Gap 查询，停止")
            break

        total_q = len(gap_queries)
        total_r = 0
        all_results = []

        print(f"\n{'='*60}")
        print(f"🔍 Gap-Driven 第 {round_num} 轮深钻：{total_q} 个查询")
        print(f"{'='*60}")

        for i, q in enumerate(gap_queries, 1):
            print(f"  [{i}/{total_q}] {q[:60]}...", end=' ')

            results = do_search(q, max_results=8)
            print(f"→ {len(results)} 条")

            for r in results[:5]:
                url = r.get('url', r.get('href', ''))
                all_results.append({
                    'query': q,
                    'round': round_num,
                    'title': r.get('title', ''),
                    'url': url,
                    'snippet': (r.get('content', r.get('body', '')))[:300],
                    'source': r.get('source', ''),
                })

            total_r += len(results)
            time.sleep(0.3)

        # 追加到已有结果
        existing = load_existing_results(task_dir)
        existing_urls = {r.get('url', '') for r in existing}
        new_results = [r for r in all_results if r.get('url', '') not in existing_urls]
        all_results = existing + new_results

        # 保存本轮结果
        results_file = task_dir / 'bp_gap_driven_results.json'
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)

        # 写 markdown
        md = [f'# BP Gap-Driven 深钻 第{round_num}轮', '',
              f'**任务**: {task_id}', f'**时间**: {datetime.now().isoformat()}',
              f'**查询**: {total_q} | **命中**: {len(all_results)} 新 + {len(existing)} 已有', '']
        for r in new_results:
            md.append(f'### {r["title"]}')
            md.append(f'- **来源查询**: {r["query"]}')
            md.append(f'- **URL**: {r["url"]}')
            md.append(f'- **摘要**: {r["snippet"][:300]}')
            md.append('')

        md_path = task_dir / f'bp_gap_driven_round{round_num}.md'
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(md))

        print(f"\n  本轮新增：{len(new_results)} 条")

        # 重新跑 Gap Detector
        from gap_detector import detect
        gap_report = detect(task_id)

        score = gap_report.get('score', 'E')
        gap_count = gap_report.get('gap_count', '??')
        print(f"  评级：{score} | 剩余缺口：{gap_count}")

        if gap_count == 0 or score.startswith(('A', 'B')):
            print(f"  ✅ 数据已充足，停止迭代")
            break
        elif round_num >= max_rounds:
            print(f"  ⚠️ 已达最大轮次 {max_rounds}，停止")
            break

        # ── LLM 查询改写 ──
        if llm_rewrite and round_num >= 1:
            from query_expander import llm_rewrite_queries

            # 收集已有证据 URL
            evidence_urls = [r.get('url', '') for r in all_results if r.get('url')]

            # 读 profile 拿公司名
            profile = {}
            profile_path = task_dir / 'bp_step0_profile.json'
            if profile_path.exists():
                profile = json.loads(profile_path.read_text(encoding='utf-8'))
            entity = profile.get('company_name', '')

            # 拿当前 gap 清单 + 证据摘要给 LLM 改写
            base_queries = [q for q in gap_queries]
            snippets = fact_snippets + [r.get('snippet', '') for r in all_results if r.get('snippet')]
            snippets = list(dict.fromkeys(snippets))[:20]  # 去重 + 截断

            llm_extra = llm_rewrite_queries(
                base_queries,
                evidence_urls=evidence_urls,
                entity=entity,
                max_n=8,
                evidence_snippets=snippets,
            )

            if llm_extra:
                print(f"  🤖 LLM 查询改写：新增 {len(llm_extra)} 个补查")
                # 追加到 gap_queries.md
                gap_md_path = task_dir / 'bp_gap_queries.md'
                current_text = gap_md_path.read_text(encoding='utf-8') if gap_md_path.exists() else ''
                # 去掉旧的 LLM 补查段（如果有）
                current_text = re.sub(r'\n# LLM 补查.*', '', current_text, flags=re.DOTALL)
                with open(gap_md_path, 'w', encoding='utf-8') as f:
                    f.write(current_text)
                    f.write(f'\n\n# LLM 补查（第 {round_num+1} 轮）\n')
                    for i, q in enumerate(llm_extra, 1):
                        f.write(f'{i}. {q}\n')
            else:
                # LLM 不可用或没产出，用规则更新
                remaining_claims = gap_report.get('unverified', []) + gap_report.get('partial', [])
                new_gap_queries = []
                for c in remaining_claims:
                    new_gap_queries.extend(c.get('gap_queries', []))
                new_gap_queries = list(dict.fromkeys(new_gap_queries))

                gap_md_path = task_dir / 'bp_gap_queries.md'
                with open(gap_md_path, 'w', encoding='utf-8') as f:
                    f.write(f'# Gap 搜索清单（第 {round_num+1} 轮，{len(new_gap_queries)} 个查询）\n\n')
                    for i, q in enumerate(new_gap_queries, 1):
                        f.write(f'{i}. {q}\n')

        print(f"  继续下一轮...")

    return gap_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--max-rounds', type=int, default=3)
    parser.add_argument('--no-llm', action='store_true', help='禁用 LLM 查询改写')
    args = parser.parse_args()

    gap_report = deep_drill(args.task_id, max_rounds=args.max_rounds, llm_rewrite=not args.no_llm)

    print(f"\n{'='*60}")
    print("✅ Gap-Driven Deep Research 完成")
    print(f"   最终评级: {gap_report.get('score', 'N/A')}")
    print(f"   总声称: {gap_report.get('total_claims', 0)} | 已验证: {gap_report.get('verified_count', 0)}")
    print(f"   剩余缺口: {gap_report.get('gap_count', 0)}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
