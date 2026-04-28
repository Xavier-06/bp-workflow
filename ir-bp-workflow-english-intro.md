# IR/BP Dual-Pipeline: AI-Powered Investment Research & Due Diligence

> A production-grade, fully automated research workflow for WorkBuddy / OpenClaw platforms. From data collection to broker-grade DOCX report delivery — zero human intervention.

---

## What Problem Does This Solve?

### 1. AI Research That Actually Goes Deep
Most AI research tools (Perplexity, ChatGPT) produce "glorified Google summaries" — they stack public information without investment-grade analytical depth. A real equity research report requires 8 systematic dimensions (data, industry, business model, financials, management, insights, risks, synthesis). Single-turn chat can't do this.

### 2. Multi-Agent Coordination That Doesn't Fall Apart
Existing agent frameworks (AutoGPT, CrewAI) suffer from: agents dying with `code=10003`, context window breaks, inconsistent data formats, and manual stitching. We built a **stateful orchestrator** with unified phase tracking, manifest-based dispatch, and automatic retry — so the pipeline recovers from any interruption.

### 3. BP Due Diligence Without the Information Asymmetry
Early-stage startup DD faces two extremes: trusting the founder's narrative (biased) or hiring expensive consultants (slow, costly). This pipeline automates the full chain: **VL OCR → structured extraction → 4-dimension parallel analysis → competitive landscape → synthesis → DOCX delivery** in under 30 minutes.

### 4. The "Last Mile" Delivery Gap
Models often forget to copy the report to desktop, convert to DOCX, or send the WeChat notification. Our pipeline has a **mandatory finalize step** with adversarial verification → DOCX generation → desktop copy → WeChat push (3-step protocol). No report gets lost.

---

## Core Architecture

### PipelineOrchestrator + Profile Pattern

Two pipelines share one orchestration kernel. The difference is defined by Profile:

```
PipelineOrchestrator
├── IR Pipeline (8 phases, 4 waves)
│   ├── phase0_preflight          → Environment check + job registration
│   ├── phase05_company_verify    → yfinance valuation data
│   ├── phase1_presearch          → 8-step pre-search (SearXNG/DDG/Scrapling)
│   ├── phase15_extract           → URL content extraction (3-tier fallback)
│   ├── phase4_dispatch_prepare   → launch_next_wave() emits wave
│   │   └── Coordinator loop: team_create() → task(name=..., team_name=...) → poll outputs
│   ├── phase4_dispatch_collect   → Quality gate check
│   └── phase5_delivery           → finalize_pipeline() fully automated
│       (quality check → DOCX → desktop → WeChat notification)
│
└── BP Pipeline (8 phases, 3 waves)
    ├── phase0_document_intake     → VL OCR + structured extraction
    ├── phase05_company_verify     → Business registry / risk / founder verification
    ├── phase1_presearch           → 4-dimension pre-search
    ├── phase2_dispatch_prepare    → Wave 1: team + tech + industry (parallel)
    ├── phase25_competition_prepare → Wave 2: competition + conclusion
    └── phase3_delivery            → Synthesis + consistency check + DOCX + WeChat
```

### Long-Chain Reasoning: 8-Step Equity Research

Not a single conversation — a **4-wave progressive reasoning chain** where each step depends on prior outputs:

| Wave | Steps | Reasoning Depth |
|------|-------|-----------------|
| Wave 1 | step1_data | Foundation: valuation, financials, market data |
| Wave 2 | step2_industry + step3_biz + step4_finance + step5_mgmt | Parallel deep analysis (industry / business / financials / management) |
| Wave 3 | step6_insight + step7_risk | Advanced reasoning (differentiated insights / risk catalysts) |
| Wave 4 | step8_master | Synthesis: integrates all 7 prior steps into broker-grade report |

**Key**: step6_insight reads step1+2+3 outputs; step7_risk reads step1+3+4 outputs. This is **genuine chain-of-thought**, not parallel independent tasks.

### Multi-Agent Collaboration: 4 Roles + Team Async Mode

```
ir-coordinator (Orchestrator)
    ├── team_create(team_name="ir-{task_id}")
    │
    ├── task(name="step2_industry", team_name=..., mode="bypassPermissions")
    │   → ir-researcher (Data Collection Agent)
    │     → reads manifest → autonomously fills data gaps → writes .md output
    │
    ├── task(name="step3_biz", team_name=..., mode="bypassPermissions")
    │   → ir-researcher → same pattern
    │
    ├── ... (more steps dispatched in parallel)
    │
    ├── poll output files (sleep 30s → test -s → repeat)
    │
    ├── team_delete() (shutdown_request → wait 10s → delete)
    │
    └── finalize_pipeline()
        → ir-reporter (Synthesis + DOCX Agent)
        → ir-verifier (Adversarial Verification Agent, 6-layer)
```

**Critical Design Decisions**:
- **Team async mode**: `task(name=..., team_name=...)` instead of synchronous `task()` — prevents `code=10003` crashes
- **Autonomous closure**: Sub-agents detect data gaps and self-correct with up to 3 search rounds, never returning to coordinator
- **Quality gates**: Step 1 completeness <50% → circuit breaker; cross-step consistency FAIL → mandatory fix; adversarial L6 → human-level argumentation
- **Checkpoint resume**: Pipeline can resume from any phase after interruption — no restart from scratch

### Search Subsystem: 3-Tier Degradation Chain

```
SearXNG (localhost:8888) → DuckDuckGo → Scrapling StealthyFetcher → requests + BeautifulSoup
```

7 search adapters (SearXNG / DDG / SEC / HKEX / Yahoo / Tavily / RSS) with entity resolution, query planning, and evidence grading.

### Delivery Closure: The Full Last Mile

```
finalize_pipeline()
├── Adversarial verification (6 layers: info leak / placeholder residue / internal contradiction / numeric validation / logic flaw / counter-argumentation)
├── DOCX generation (sanitize_text scrubs all internal metadata)
├── Copy to desktop
└── WeChat notification (3-step protocol: text → file → confirmation)
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestration | Python 3.10+, PipelineOrchestrator (phase-driven) |
| Search | SearXNG + DuckDuckGo + Scrapling (TLS fingerprint simulation) + 7 adapters |
| Financial Data | yfinance + neodata-financial-search skill + westock-data skill |
| Document Processing | python-docx (DOCX generation) + VL OCR (qwen3-vl for BP documents) |
| Vector Memory | ChromaDB + qwen3-embedding-8b |
| Notification | wechat-ilink-bot SDK (WeChat iLink protocol) |
| Deployment | WorkBuddy / OpenClaw platform, 4 Skills (coordinator / researcher / reporter / verifier) |

---

## Project Stats

- **~200 Python files**, **~25,000 lines of code**
- **Completed analyses**: AVGO, Pop Mart, UBTECH, Dongjiang Environmental, Hefei Aichuangwei
- **Deliverables**: Broker-grade DOCX reports with executive summary, valuation analysis, risk matrix, and disclaimer
- **Automation rate**: Phase 0–5 fully automated, Zero Human Intervention

---

## Quick Start

```bash
# One-line install
curl -fsSL https://raw.githubusercontent.com/Xavier-06/ir-bp-workflow/main/setup.sh | bash

# Or manual
git clone https://github.com/Xavier-06/ir-bp-workflow.git ~/.workbuddy/ir_runtime
cd ~/.workbuddy/ir_runtime && bash setup.sh

# Edit .env with your API keys, restart WorkBuddy, then say:
# "Analyze BYD" or "Review this BP" — ir-coordinator handles the rest
```

---

*Built with 🐲 for the AI agent community*
