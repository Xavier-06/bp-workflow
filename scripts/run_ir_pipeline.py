#!/usr/bin/env python3
"""
IR 研报管线主控 — Phase 0→5 全链路自动化 (v6, Perplexity Deep Research 标准)

Phase 0:    Preflight 校验
Phase 0.5:  上市公司官方数据验证
Phase 1:    预搜索（ir_presearch.py 多 step 并行）
Phase 1.5:  LLM 正文信息抽取
Phase 2:    Gap 检测 + 评分
Phase 3:    迭代深钻（最多 3 轮）
Phase 4:    子代理发射（8 step + 质量门禁）
Phase 5:    统稿交付（交叉验证 + 证据表 + DOCX）
"""
from __future__ import annotations
import argparse, json, sys, time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import os
os.environ.setdefault('SSL_CERT_FILE', '/opt/homebrew/etc/openssl@3/cert.pem')
os.environ.setdefault('REQUESTS_CA_BUNDLE', '/opt/homebrew/etc/openssl@3/cert.pem')

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from runtime.entrypoints.run_ir_pipeline_entry import run_ir_job as run_ir_job_v2
from task_registry import TaskRegistry, TaskStatus
from hook_dispatcher import HookDispatcher
from cleanup_registry import PipelineCleanup

PIPELINE_TIMEOUT = 3600  # 60 min (was 30, Dongjiang timeout 2026-04-05)

STEP_ORDER = ['step1_data','step2_industry','step3_biz','step4_finance','step5_mgmt','step6_insight','step6b_valuation','step7_risk','step8_master']
STEP_NAMES = {'step1_data':'行情与基础数据','step2_industry':'行业与市场格局','step3_biz':'业务模式','step4_finance':'财务分析','step5_mgmt':'管理与治理','step6_insight':'投资洞察','step6b_valuation':'预测与估值','step7_risk':'风险提示','step8_master':'统稿'}

def _log(phase, msg):
    print(f"\n{'='*60}\n  {phase}: {msg}\n{'='*60}")

def _fmt(s):
    return f"{s:.0f}s" if s < 60 else f"{s//60:.0f}m{int(s%60):02d}s"

def _load_pkg(tid):
    p = TASKS_DIR / f'{tid}.json'
    if p.exists(): return json.loads(p.read_text(encoding='utf-8'))
    return None

# ═══════════════════════════════════════════════
# Task/Hook 基础设施
# ═══════════════════════════════════════════════
_cache = {}

def _reg(tid):
    if tid not in _cache:
        r = TaskRegistry(); r.clear_pipeline(f"ir_{tid}")
        _cache[tid] = _make_tasks(tid, r)
    return _cache[tid]

def _hooks(tid):
    k = f"h_{tid}"
    if k not in _cache: _cache[k] = HookDispatcher()
    return _cache[k]

def _done(tid, ph, i):
    r = _cache.get(tid); h = _cache.get(f"h_{tid}")
    if r and i: r.update(i, status=TaskStatus.COMPLETED)
    if h: h.emit('PhaseCompleted', pipeline=f"ir_{tid}", phase=ph, task_id=i)
    _st(tid)

def _fail(tid, ph, i, err=""):
    r = _cache.get(tid); h = _cache.get(f"h_{tid}")
    if r and i: r.update(i, status=TaskStatus.FAILED, error=err)
    if h: h.emit('PhaseFailed', pipeline=f"ir_{tid}", phase=ph, task_id=i, error_msg=err or "Unknown")
    _st(tid)

def _prog(tid, ph, i):
    r = _cache.get(tid); h = _cache.get(f"h_{tid}")
    if r and i: r.update(i, status=TaskStatus.IN_PROGRESS)
    if h: h.emit('PhaseStarted', pipeline=f"ir_{tid}", phase=ph, task_id=i)
    _st(tid)

def _st(tid):
    r = _cache.get(tid)
    if r:
        s = r.pipeline_status(f"ir_{tid}")
        if not s.get('total'): return
        e = {"completed":"✅","failed":"❌","in_progress":"🔄"}.get(s['state'],"⏳")
        print(f"  {e} {s['completed']}/{s['total']} | {s.get('failed',0)} 失败")

def _chk_to(t0, tid):
    if time.time()-t0 > PIPELINE_TIMEOUT:
        print(f"\n  ❌ 超时 {_fmt(time.time()-t0)}")
        _fail(tid, "timeout", 1, f"Timeout ({_fmt(time.time()-t0)})")
        return True
    return False

def _make_tasks(tid, reg):
    p = f"ir_{tid}"
    t1 = reg.create(subject="Preflight",active_form="正在 Preflight",phase="phase0",pipeline=p)
    t2 = reg.create(subject="数据验证",active_form="正在验证数据",phase="phase05",pipeline=p,blocked_by=[t1.id],subagent_key="verify")
    t3 = reg.create(subject="预搜索",active_form="正在预搜索",phase="phase1",pipeline=p,blocked_by=[t1.id])
    t4 = reg.create(subject="信息抽取",active_form="正在抽取",phase="phase15",pipeline=p,blocked_by=[t3.id])
    t5 = reg.create(subject="Gap 检测",active_form="Gap 检测",phase="phase2",pipeline=p,blocked_by=[t4.id])
    t6 = reg.create(subject="迭代深钻",active_form="深钻中",phase="phase3",pipeline=p,blocked_by=[t5.id])
    pt = []
    for sn, snn in STEP_NAMES.items():
        t = reg.create(subject=snn,active_form=f"正在 {snn}",phase="phase4",pipeline=p,blocked_by=[t6.id],subagent_key=sn,parent_id=t6.id)
        pt.append(t)
    reg.create(subject="统稿交付",active_form="正在统稿",phase="phase5",pipeline=p,blocked_by=[t.id for t in pt])
    return reg

# ═══════════════════════════════════════════════
# Quality Gate
# ═══════════════════════════════════════════════
_OFFICIAL = ['sec.gov','hkexnews.hk','cninfo.com.cn','szse.cn','sse.com.cn','ir.','investor.']
_REPUTABLE = ['reuters.com','bloomberg.com','wsj.com','ft.com','economist.com','scmp.com','caixin.com','36kr.com','cls.cn','eastmoney.com','xueqiu.com']
_REDFLAGS = ['待补','待填','TODO','无法验证','无法获取','需要进一步']

def _qgate(tid, min_score=16):
    scores, issues = {}, []
    for step in STEP_ORDER:
        f = TASKS_DIR / f'{tid}-{step}.md'
        if not f.exists():
            scores[step]=0; issues.append(f"❰{step}❱ 缺失"); continue
        txt = f.read_text(encoding='utf-8')
        if len(txt)<200:
            scores[step]=0; issues.append(f"❰{step}❱ 内容过短"); continue
        t = txt.lower()
        oc = sum(1 for d in _OFFICIAL if d in t)
        rc = sum(1 for d in _REPUTABLE if d in t)
        uc = txt.count('http')
        if oc>=2 and len(txt)>2000: sc=3
        elif (oc>=1 or rc>=2) and len(txt)>1000: sc=2
        elif uc>=1: sc=1
        else: sc=0
        fl = sum(1 for x in _REDFLAGS if x in txt)
        if fl>=3 and sc>1: sc=max(1,sc-1); issues.append(f"❰{step}❱ {fl} 红旗")
        scores[step] = sc
        if sc<2: issues.append(f"❰{STEP_NAMES.get(step,step)}❱ {sc}/3 (官方{oc} 权威{rc} URL{uc})")
    total = sum(scores.values())
    return {'scores':scores,'total':total,'max':len(STEP_ORDER)*3,'pass':total>=min_score,'issues':issues,'threshold':min_score}

# ═══════════════════════════════════════════════
# Self-Review Loop
# ═══════════════════════════════════════════════
def _self_review(tid, entity='', rounds=2):
    log = []
    for i in range(1, rounds+1):
        q = _qgate(tid)
        if q['pass']:
            log.append({'iter':i,'action':'pass','score':q['total']}); print(f"  ✅ 第{i}轮: {q['total']}/{q['max']}")
            return {'pass':True,'log':log}
        weak = [s for s,sc in q['scores'].items() if sc<2 and s!='step8_master']
        if not weak:
            log.append({'iter':i,'action':'no_weak','score':q['total']}); break
        print(f"  🔍 第{i}轮: 薄弱 {', '.join(STEP_NAMES.get(s,s) for s in weak[:3])}")
        kw = {'step1_data':'股价 市值 市盈率 EPS 分析师评级','step2_industry':'行业规模 市场份额 竞争格局','step3_biz':'商业模式 产品线 客户 收入结构','step4_finance':'财报 营收 毛利率 现金流 ROE','step5_mgmt':'管理层 董事会 股权结构 治理','step6_insight':'催化剂 估值 目标价 投资','step6b_valuation':'DCF 估值 目标价 WACC 可比公司 PE PB PS','step7_risk':'风险 监管 诉讼 竞争'}
        for ws in weak[:3]:
            q_ = kw.get(ws,''); q_ = f"{entity} {q_}".strip()
            if not q_: continue
            print(f"    📝 补搜: {q_}")
            try:
                from search_gateway import search
                rr = search(q_, max_results=8)
                if rr:
                    ap = TASKS_DIR / f'{tid}-{ws}-followup.md'
                    with open(ap,'a') as f:
                        f.write(f"\n## 补充搜索 #{i}\n\n")
                        for j,r in enumerate(rr[:5],1): f.write(f"### {j}. {r.get('title','')}\nURL: {r.get('url','')}\n{r.get('snippet','')}\n\n")
            except Exception as e:
                print(f"    ⚠ 补搜异常: {e}")
        log.append({'iter':i,'action':'search','score':q['total']})
    return {'pass':False,'log':log,'final_score':log[-1]['score'] if log else 0}

# ═══════════════════════════════════════════════
# Evidence Chain (Phase 5)
# ═══════════════════════════════════════════════
def _evidence_chain(tid):
    ev = {'claims':None,'table':None,'audit':None,'cv':None,'cd':None,'pass':True,'issues':[]}
    # Claim cards
    try:
        evj = TASKS_DIR / f'{tid}-evidence.json'
        if evj.exists():
            from scripts.build_ir_claim_cards import main as cm
            import sys as _s2
            _s2.argv = ['','str(evj)']
            cm(); ev['claims']=str(TASKS_DIR/f'{tid}-claim-cards.md')
    except Exception as e: ev['issues'].append(f'claims: {e}')
    # Evidence table
    try:
        from scripts.build_ir_evidence_table import parse_packet, render_md
        files = list(TASKS_DIR.glob(f'{tid}-search-*.md'))
        if files:
            rows = []
            for ef in files:
                try: rows.extend(parse_packet(ef))
                except: pass
            if rows:
                TASKS_DIR/f'{tid}-evidence-table.json'.write_text(json.dumps({'task_id':tid,'rows':rows},ensure_ascii=False,indent=2))
                TASKS_DIR/f'{tid}-evidence-table.md'.write_text(render_md(rows,tid))
                ev['table']={'count':len(rows)}
    except Exception as e: ev['issues'].append(f'table: {e}')
    # Source audit
    try:
        if (TASKS_DIR/f'{tid}-evidence.json').exists():
            from scripts.build_ir_source_audit import main as am
            import sys as _s3; _s3.argv=['','tid']
            am(); ev['audit']=str(TASKS_DIR/f'{tid}-source-audit.md')
    except Exception as e: ev['issues'].append(f'audit: {e}')
    # Cross-validation
    try:
        from scripts.ir_cross_validation import run_cross_validation
        cv = run_cross_validation(tid)
        ev['cv']=cv
        if not cv.get('overall_pass',True): ev['pass']=False
    except Exception as e: ev['issues'].append(f'cv: {e}')
    # Contradiction detection
    try:
        from scripts.ir_contradiction_checker import run_contradiction_check
        cd = run_contradiction_check(tid)
        ev['cd']=cd
        if cd.get('summary',{}).get('high',0)>0: ev['pass']=False
    except Exception as e: ev['issues'].append(f'cd: {e}')
    return ev

# ═══════════════════════════════════════════════
# Phase helpers
# ═══════════════════════════════════════════════
def _p4_done(tid):
    miss, sz = [], {}
    for step in STEP_ORDER:
        f = TASKS_DIR/f'{tid}-{step}.md'
        if not f.exists(): miss.append(step)
        elif f.stat().st_size<200: miss.append(f'{step}(<200B)')
        else: sz[step]=f.stat().st_size
    return {'ready':not miss,'missing':miss,'sizes':sz}

def _p4_poll(tid, timeout=1200, interval=15):
    t0 = time.time(); last = 0
    while time.time()-t0<timeout:
        c = _p4_done(tid)
        if c['ready']:
            print(f"  ✅ Phase 4 完成 (等了 {int(time.time()-t0)}s)")
            r = _cache.get(tid)
            if r: r.get_ready_tasks(f"ir_{tid}")
            return True
        if time.time()-last>30:
            print(f"  ⏳ Phase 4... 缺: {', '.join(c['missing'][:4])}"); last=time.time()
        time.sleep(interval)
    print(f"  ⚠ Phase 4 超时 ({timeout}s)"); return False

def _preflight(tid, ent, q, mkt):
    _log("PHASE 0","Preflight"); t0=time.time()
    try:
        from ir_preflight_check import run_preflight
        r = run_preflight(tid,entity=ent,query=q,market=mkt)
        print(f"  {'✅' if r.get('passed') else '❌'} Preflight")

        return r
    except Exception as e:
        print(f"  ❌ {e}"); return {'passed':False,'error':str(e)}

def _verify(tid, ent, mkt):
    _log("PHASE 0.5",ent)
    try:
        from ir_company_verify import run as v; r=v(tid,entity=ent,market=mkt)
        if not r.get('error'): print(f"  ✅ 验证 {r.get('total_results',0)} 条")
        return r
    except Exception as e: print(f"  ⚠ {e}"); return {'error':str(e)}

def _presearch(tid, ent, mkt, tk='', en=''):
    _log("PHASE 1",ent)
    try:
        from ir_presearch import run_presearch
        _t=tk; _e=en
        r=run_presearch(tid,ent,mkt,steps=STEP_ORDER[:7],ticker=_t,english_name=_e)
        ok=sum(1 for v in r.get('steps',{}).values() if v.get('status')=='ok')
        # Estimate: 7 steps × avg 800 in + 300 out each

        print(f"  ✅ {ok}/7"); return r
    except Exception as e: print(f"  ❌ {e}"); return {'error':str(e)}

def _extract(tid, ent):
    _log("PHASE 1.5","抽取")
    try:
        from ir_extract_content import extract_from_presearch
        r=extract_from_presearch(tid,ent,15)
        print(f"  ✅ {r.get('ok_count',0)}/{r.get('total_urls',0)}"); return r
    except Exception as e: print(f"  ⚠ {e}"); return {'error':str(e)}

def _gap(tid, ent, mkt):
    _log("PHASE 2","Gap")
    try:
        from ir_gap_detector import detect
        r=detect(tid,entity=ent,market=mkt,use_facts=True)
        print(f"  ✅ {r.get('overall_grade','?')}"); return r
    except Exception as e: print(f"  ❌ {e}"); return {'error':str(e),'overall_grade':'E'}

def _drill(tid, ent, mkt, rounds=3):
    _log("PHASE 3","深钻")
    try:
        from ir_query_rewriter import rewrite
        from ir_gap_detector import detect
        dl=[]; gr='E'
        for rn in range(1,rounds+1):
            g=detect(tid,entity=ent,market=mkt,use_facts=True); gr=g.get('overall_grade','E')
            if gr in ('A','B'): dl.append({'r':rn,'g':gr,'a':'stop'}); print(f"  第{rn}轮: {gr} ✅"); break
            if not g.get('missing_count',0): dl.append({'r':rn,'g':gr,'a':'stop'}); break
            rw=rewrite(tid,entity=ent,market=mkt,max_new=15); qs=rw.get('new_queries',[])
            if not qs: dl.append({'r':rn,'g':gr,'a':'noq'}); break
            print(f"  第{rn}轮: {len(qs)} 条")
            try:
                from research.research_api import run_research
                rr=run_research(query=' '.join(qs),entity=ent,market=mkt,max_rounds=1)
                print(f"  ✅ {rr.get('accepted_count',0)} accepted")
                dl.append({'r':rn,'g':gr,'q':len(qs),'a':rr.get('accepted_count',0)})

            except Exception as e: print(f"  ❌ {e}"); dl.append({'r':rn,'g':gr,'a':'fail'})
            time.sleep(1)
        return {'rounds':len(dl),'grade':dl[-1]['g'] if dl else gr,'log':dl}
    except Exception as e: print(f"  ⚠ {e}"); return {'error':str(e)}

def _dispatch(tid, ent, q, mkt):
    _log("PHASE 4","子代理")
    try:
        # 2026-04-23: 改用 launch_next_wave 替代 launch_all，支持 wave 间等待
        from ir_subagent_launcher_wb import launch_next_wave, get_pipeline_status
        r=launch_next_wave(tid,entity=ent,query=q,market=mkt)
        dispatched=r.get('dispatched_count',0)
        print(f"  ✅ Wave {r.get('wave_index',0)+1} 发射{dispatched}")
        return r
    except Exception as e: print(f"  ❌ {e}"); return {'error':str(e)}

def _phase5(tid, ent, mkt, timing={}, hooks=None):
    _log("PHASE 5","统稿")
    res={'status':'phase5_failed'}
    # Quality gate
    print("\n  🔍 质量评估...")
    qg=_qgate(tid)
    print(f"  {'✅' if qg['pass'] else '⚠️'} {qg['total']}/{qg['max']}")
    for i in qg['issues'][:5]: print(f"    {i}")
    res['quality_gate']=qg
    # Self-review
    if not qg['pass']:
        print("\n  🔄 自审查...")
        rv=_self_review(tid,entity=ent)
        res['review']=rv; print(f"  {'✅' if rv['pass'] else '⚠️'}")
    # Evidence chain
    print("\n  🔗 证据链...")
    te=time.time()
    ev=_evidence_chain(tid); timing['evidence_chain']=time.time()-te
    res['evidence']=ev; print(f"  {'✅' if ev['pass'] else '⚠️'}")
    # Realtime data
    try:
        from ir_realtime_refresh import refresh_realtime_data
        tk=''; pk=TASKS_DIR/f'{tid}.json'
        if pk.exists():
            pk2=json.loads(pk.read_text()); tk=pk2.get('ticker',pk2.get('symbol',''))
        if tk:
            rt=refresh_realtime_data(tid,ticker=tk,entity=ent,market=mkt)
            res['realtime']=rt.get('md_snippet','')
            print(f"  📈 {tk} ${rt.get('price','?')}")
    except: pass
    # Adversarial Verification（对标 free-code VerificationAgent）
    vr=None
    try:
        from adversarial_verification import run_ir_verification, format_verification_report
        vr=run_ir_verification(tid,TASKS_DIR)
        print(f"  🔍 对抗式验证: {vr['verdict']} (P:{vr.get('pass',0)} F:{vr.get('fail',0)} W:{vr.get('warn',0)})")
        if vr.get('recommendations'):
            for r in vr['recommendations'][:5]:
                print(f"    {r[:80]}")
        adv_path=TASKS_DIR/tid if '/' in str(TASKS_DIR/tid) else TASKS_DIR
        adv_path=TASKS_DIR
        rp=adv_path/f'{tid}-adversarial-verification.md'
        rp.write_text(format_verification_report(vr,'ir'),encoding='utf-8')
        res['adversarial']=vr
        print(f"  📄 验证报告: {rp}")
    except Exception as e: print(f"  ⚠️ 对抗式验证跳过（不阻断管线）: {e}")

        # Hard gate: step8_master must exist
    master = TASKS_DIR / f'{tid}-step8_master.md'
    if not master.exists():
        print("\\n  BLOCKED: step8_master missing, no half-baked DOCX")
        res['docx_blocked'] = True
        res['reason'] = 'step8_master_missing'
        return res
    elif master.stat().st_size < 1000:
        print(f"\\n  BLOCKED: step8_master too small ({master.stat().st_size}B)")
        res['docx_blocked'] = True
        res['reason'] = 'step8_master_too_small'
        return res
    else:
        print(f"  step8_master verified: {master.stat().st_size:,}B")

# DOCX
    t5=time.time()
    try:
        from build_ir_broker_report_docx import build_docx
        dp=build_docx(tid)
        if dp and Path(dp).exists():
            res={'status':'phase5_done','docx_path':dp}; print(f"  ✅ DOCX: {dp}")
            if hooks: hooks.emit('PipelineCompleted',pipeline=f"ir_{tid}")
        else: res['docx_path']=dp
    except ImportError as e:
        print(f"  ⚠ {e}")
        try:
            from deliver_ir_report import deliver
            r=deliver(tid); res={'status':'phase5_done','output_path':r}
            if hooks: hooks.emit('PipelineCompleted',pipeline=f"ir_{tid}")
        except Exception as e2: print(f"  ❌ {e2}")
    except Exception as e: print(f"  ❌ {e}"); res['error']=str(e)
    timing['phase5']=time.time()-t5

    return res

# ═══════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════
def run_pipeline(tid, ent='', q='', mkt='us', rounds=3, p5only=False, auto=False, epages=15, ticker='', english_name=''):
    if os.environ.get('IR_USE_SHARED_KERNEL_SKELETON') == '1':
        return run_ir_job_v2(
            job_id=tid,
            entity=ent,
            query=q,
            market=mkt,
            ticker=ticker,
            english_name=english_name,
            max_extract_pages=epages,
            rounds=rounds,
            migrate_phases=['preflight', 'company_verify', 'presearch', 'extract', 'gap', 'deep_dive'],
            legacy_fallback=True,
        )
    _cache.clear()
    print(f"\n{'#'*60}\n#  IR v6 {tid}\n#  {ent} | {mkt}\n{'#'*60}")
    tim={}; t0=time.time()
    reg=_reg(tid); h=_hooks(tid); pc=PipelineCleanup(tid, TASKS_DIR)
    h.emit('PipelineStarted',pipeline=f"ir_{tid}",task_id=1); _st(tid)

    if auto:
        c=_p4_done(tid)
        if c['ready']: return _phase5(tid,ent,mkt,tim,hooks=h)
        if c['missing']: print(f"  Phase 4 缺: {', '.join(c['missing'][:3])}")
    if p5only: return _phase5(tid,ent,mkt,tim,hooks=h)

    # Load entity from task package if not specified
    if not ent and not q:
        pkg=_load_pkg(tid)
        if pkg: ent=pkg.get('entity',pkg.get('query','')); q=pkg.get('query',''); mkt=pkg.get('market',mkt)

    log={'task_id':tid,'entity':ent,'market':mkt,'started_at':datetime.now().isoformat(),'phases':[],'status':'running'}

    # Phase 0
    _prog(tid,"phase0",1)
    ps=time.time()
    try:
        p0=_preflight(tid,ent,q,mkt)
    except Exception as e:
        print(f"\n  ❌ {e}"); _fail(tid,"phase0",1,str(e)); log['status']='error'; log['error']=str(e); return log
    tim['phase0']=time.time()-ps; log['phases'].append({'name':'phase0','passed':p0.get('passed')})
    if not p0.get('passed'):
        print("\n  ❌ Preflight 未通过"); _fail(tid,"phase0",1,"Preflight 未通过")
        log['status']='blocked_at_phase0'; return log
    _done(tid,"phase0",1)
    if _chk_to(ps,tid): return log

    # Phase 0.5 + 1 Parallel
    print(f"\n  ⚡ 并行: 0.5+1"); pp=time.time(); _prog(tid,"phase05",2); _prog(tid,"phase1",3)
    res={'v':None,'p':None}
    def _rv():
        try: t=time.time(); r=_verify(tid,ent,mkt); return {'ok':True,'r':r,'d':time.time()-t}
        except Exception as e: return {'ok':False,'e':str(e)}
    def _ps():
        try: t=time.time(); r=_presearch(tid,ent,mkt,tk=ticker,en=english_name); return {'ok':True,'r':r,'d':time.time()-t}
        except Exception as e: return {'ok':False,'e':str(e)}
    with ThreadPoolExecutor(max_workers=2) as ex:
        fl={ex.submit(_rv):'v',ex.submit(_ps):'p'}
        for f in as_completed(fl):
            lb=fl[f]; r=f.result()
            if r['ok']: res[lb]=r['r']; tim[f"p{lb}"]=r['d']; print(f"  ✅ {lb}: {_fmt(r['d'])}")
            else: tim[f"p{lb}"]=0; _fail(tid,'phase05' if lb=='v' else 'phase1', 2 if lb=='v' else 3, r.get('e','')); print(f"  ⚠ {lb}: {r.get('e','')}")
    tim['parallel']=time.time()-pp
    if res['v']: _done(tid,"phase05",2)
    if res['p']: _done(tid,"phase1",3)

    # Phase 1.5
    t15=time.time(); _extract(tid,ent); tim['p15']=time.time()-t15

    # Phase 2
    _prog(tid,"phase2",4)
    t2=time.time()
    try: g2=_gap(tid,ent,mkt)
    except Exception as e: tim['p2']=0; _fail(tid,"phase2",4,str(e)); print(f"  ❌ {e}"); return log
    tim['p2']=time.time()-t2; grade=g2.get('overall_grade','E'); _done(tid,"phase2",4)

    if _chk_to(t2,tid): return log

    # Phase 3
    if grade not in ('A',):
        _prog(tid,"phase3",5)
        t3=time.time(); _drill(tid,ent,mkt,rounds); tim['p3']=time.time()-t3; _done(tid,"phase3",5)
    else: print(f"\n  ⏭ 评级 A，跳过深钻")

    # Phase 4
    _prog(tid,"phase4",6)
    t4=time.time(); r4=_dispatch(tid,ent,q,mkt); tim['p4']=time.time()-t4
    c=r4.get('total_steps_completed',0); tot=len(STEP_ORDER)
    if 0<c<tot: print(f"\n  ⏳ {c}/{tot}..."); _p4_poll(tid)
    elif c==0 and tim.get('p4',0)>0: print("\n  ⏳ 等待子代理..."); _p4_poll(tid)
    _done(tid,"phase4",6)
    if _chk_to(t4,tid): return log

    # 🔒 Phase 4 熔断：完成率 < 50% 禁止进入 Phase 5
    c4 = _p4_done(tid)
    completed_4 = len(STEP_ORDER) - len(c4.get('missing', []))
    pct_4 = completed_4 / len(STEP_ORDER) if STEP_ORDER else 0
    if pct_4 < 0.5:
        print(f"\n  ❌ Phase 4 完成率仅 {pct_4:.0%} ({completed_4}/{len(STEP_ORDER)})，硬熔断")
        print(f"  缺失: {', '.join(c4['missing'][:4])}")
        _fail(tid, "phase4", 6, f"Only {completed_4}/{len(STEP_ORDER)} steps completed")
        log['status'] = 'blocked_at_phase4'
        log['completed_at'] = datetime.now().isoformat()
        (TASKS_DIR/f'{tid}-pipeline_log.json').write_text(json.dumps(log,ensure_ascii=False,indent=2))
        return log

    # Phase 5
    r5=_phase5(tid,ent,mkt,tim,hooks=h)
    pc.release_all()
    log['status']='completed' if r5.get('status')=='phase5_done' else r5.get('status','failed')
    log['completed_at']=datetime.now().isoformat()
    docx_path=r5.get('docx_path',r5.get('output_path',''))
    log['docx_path']=docx_path
    log['quality_gate']=r5.get('quality_gate')
    log['feishu_sent']=False

    # 🚨 Delivery Guard: auto-send DOCX to Xavier via 龙少微信
    # Root cause fix (2026-04-04): Xavier asked for report, I generated DOCX but
    # didn't send it. The fix is NOT "remember to send" — it's code that enforces it.
    # 2026-04-13: WorkBuddy 版 — 用龙少微信替代 `openclaw message send --channel feishu`
    if docx_path and r5.get('status') == 'phase5_done':
        try:
            from pathlib import Path as _P
            _dp = _P(docx_path)
            if _dp.exists():
                _entity = ent or tid
                import sys as _sys
                _sys.path.insert(0, str(Path(__file__).resolve().parent))
                try:
                    from longshao_notify import send_message as _send_wx
                    _wx_text = f"📊 {_entity} 深度研报已生成\n\n📄 文件: {_dp.name}\n📁 路径: {_dp}\n\n请查阅。（自动发送）"
                    _r = _send_wx(_wx_text)
                    if _r.get('ok'):
                        log['wx_sent'] = True
                        print(f"  ✅ DOCX 通知已通过龙少微信发送")
                    else:
                        print(f"  ⚠️ 龙少微信发送失败: {_r.get('msg', '')[:200]}")
                except ImportError:
                    print(f"  ⚠️ longshao_notify 未找到，跳过微信通知")
        except Exception as e:
            print(f"  ⚠️ Delivery guard error: {e}")

    (TASKS_DIR/f'{tid}-pipeline_log.json').write_text(json.dumps(log,ensure_ascii=False,indent=2))
    tim['total']=time.time()-t0
    print(f"\n{'─'*40}\n📊 耗时:")
    for n,d in tim.items(): print(f"   {n}: {_fmt(d)}")
    print(f"{'─'*40}")
    print(f"\n{'#'*60}\n#  完成: {tid}\n#  {log['status']}\n#  DOCX: {log.get('docx_path','N/A')}\n{'#'*60}")
    return log

# ═══════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--task-id',required=True)
    ap.add_argument('--entity',default='')
    ap.add_argument('--query',default='')
    ap.add_argument('--market',default='us',choices=['us','hk','cn'])
    ap.add_argument('--ticker',default='',help='Stock ticker for search disambiguation')
    ap.add_argument('--english-name',default='',help='Company English name')
    ap.add_argument('--max-rounds',type=int,default=3)
    ap.add_argument('--phase5-only',action='store_true')
    ap.add_argument('--auto',action='store_true')
    ap.add_argument('--extract-pages',type=int,default=15)
    a=ap.parse_args()
    run_pipeline(a.task_id,a.entity,a.query,a.market,a.max_rounds,a.phase5_only,a.auto,a.extract_pages,a.ticker,a.english_name)

if __name__=='__main__': main()


def _p4_gate(tid):
    """Phase 4 gate: all 8 steps must exist and be >500 bytes"""
    missing = []
    for step in STEP_ORDER:
        f = TASKS_DIR / f'{tid}-{step}.md'
        if not f.exists() or f.stat().st_size < 500:
            missing.append(step)
    if missing:
        print(f"\\n  Phase 4 gate FAILED: {len(missing)}/{len(STEP_ORDER)} steps missing/sub-500B")
        for s in missing[:5]:
            print(f"    missing: {STEP_NAMES.get(s,s)} ({s})")
        return False
    print(f"\\n  Phase 4 gate PASSED: 8/8 steps have output")
    return True
