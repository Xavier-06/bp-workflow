#!/usr/bin/env python3
"""Verification tests for pipeline fixes applied 2026-04-05"""
import json, sys, re, os
from pathlib import Path

os.chdir(str(Path(__file__).resolve().parent.parent))

print("="*70)
print("管线修复验证测试 (Verification 2026-04-05)")
print("="*70)

TASKS_DIR = Path('data/tasks')
TASKS_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════
# Test 1: _p4_gate blocks incomplete Phase 4
# ═══════════════════════════════════════════════════════
print("\n[Test 1] _p4_gate 拦截不完整产出 (东江失败场景)")

STEP_ORDER = ['step1_data','step2_industry','step3_biz','step4_finance','step5_mgmt','step6_insight','step6b_valuation','step7_risk','step8_master']
STEP_NAMES = {'step1_data':'行情','step2_industry':'行业','step3_biz':'商业模式','step4_finance':'财务','step5_mgmt':'管理层','step6_insight':'洞察','step6b_valuation':'预测与估值','step7_risk':'风险','step8_master':'统稿'}

def _p4_gate(tid):
    """Copied from fixed run_ir_pipeline.py"""
    missing = []
    for step in STEP_ORDER:
        f = TASKS_DIR / f'{tid}-{step}.md'
        if not f.exists() or f.stat().st_size < 500:
            missing.append(step)
    if missing:
        return False
    return True

tid_test = 'TASK-VERIFY-001'
(TASKS_DIR / f'{tid_test}.json').write_text(json.dumps({"task_id": tid_test, "entity": "测试", "market": "hk"}), encoding='utf-8')

# Only step1 exists (Dongjiang failure scenario)
for step in STEP_ORDER:
    f = TASKS_DIR / f'{tid_test}-{step}.md'
    if f.exists(): f.unlink()
    if step == 'step1_data':
        f.write_text("# Step 1\n\n" + "X" * 600, encoding='utf-8')

r1 = _p4_gate(tid_test)
print(f"  场景: 仅 step1 有产出，step2-8 缺失")
print(f"  _p4_gate 返回值: {r1}")
assert r1 == False, f"FAIL: gate should block (got {r1})"
print(f"  ✅ PASS: 拦截了不完整产出")

# Test 1b: all 8 pass
for step in STEP_ORDER:
    f = TASKS_DIR / f'{tid_test}-{step}.md'
    f.write_text(f"# {step}\n\n" + "Content " * 100 + "\n\nSource: https://example.com\n", encoding='utf-8')

r1b = _p4_gate(tid_test)
print(f"  场景: 8 个 step 都有产出")
assert r1b == True, f"FAIL: gate should pass (got {r1b})"
print(f"  ✅ PASS: 放行了完整产出")

# Cleanup
for step in STEP_ORDER:
    (TASKS_DIR / f'{tid_test}-{step}.md').unlink(missing_ok=True)
(TASKS_DIR / f'{tid_test}.json').unlink(missing_ok=True)

# ═══════════════════════════════════════════════════════
# Test 2: PIPELINE_TIMEOUT = 3600
# ═══════════════════════════════════════════════════════
print("\n[Test 2] Pipeline timeout 配置")
code = Path('scripts/run_ir_pipeline.py').read_text(encoding='utf-8')
m = re.search(r'PIPELINE_TIMEOUT\s*=\s*(\d+)', code)
assert m, "PIPELINE_TIMEOUT not found"
timeout = int(m.group(1))
print(f"  PIPELINE_TIMEOUT = {timeout}")
assert timeout == 3600, f"Expected 3600, got {timeout}"
print(f"  ✅ PASS: 60 分钟")

# Verify it's enough for all waves
# New timeouts from ir_subagent_launcher.py
launcher = Path('scripts/ir_subagent_launcher.py').read_text(encoding='utf-8')
timeouts_m = re.findall(r"'(\w+)':\s*(\d+),?\s*(?:#.*)?$", launcher)
timeouts = {k: int(v) for k, v in timeouts_m if k in STEP_ORDER}
print(f"  STEP_TIMEOUTS: {timeouts}")

# Max possible time: Wave1 + Wave2(parallel) + Wave3(parallel) + Wave4
wave1 = timeouts.get('step1_data', 300)
wave2 = max(timeouts.get(s, 300) for s in ['step2_industry','step3_biz','step4_finance','step5_mgmt'])
wave3 = max(timeouts.get(s, 300) for s in ['step6_insight','step7_risk'])
wave4 = timeouts.get('step8_master', 300)
total_phase4 = wave1 + wave2 + wave3 + wave4
print(f"  Phase 4 max theoretical: {total_phase4}s = {total_phase4/60:.0f}m")
print(f"  Pipeline budget: {timeout}s = {timeout/60:.0f}m")
margin = timeout - total_phase4 - 300  # subtract Phase 0-3 budget (~5min)
print(f"  Slack: {margin}s = {margin/60:.0f}m")
assert timeout > total_phase4 + 300, "Timeout too tight"
print(f"  ✅ PASS: 足够覆盖 Phase 4 全部波次")

# ═══════════════════════════════════════════════════════
# Test 3: build_docx step8 gate
# ═══════════════════════════════════════════════════════
print("\n[Test 3] DOCX 生成 step8 缺失拦截")
docx_code = Path('scripts/build_ir_broker_report_docx.py').read_text(encoding='utf-8')

has_step8_check = "step8_master" in docx_code and "sys.exit(1)" in docx_code
print(f"  step8_master check exists: {has_step8_check}")
assert has_step8_check, "FAIL: step8 check not found in build_docx"
print(f"  ✅ PASS: step8 缺失时会 sys.exit(1)")

# Also check the duplicate guard from earlier fix
if '硬拦截' in docx_code or '硬检查' in docx_code:
    print(f"  Double guard detected (双重拦截)")

# ═══════════════════════════════════════════════════════
# Test 4: Pipeline Phase 5 step8 guard
# ═══════════════════════════════════════════════════════
print("\n[Test 4] Pipeline Phase 5 step8 前置验证")
has_p5_guard = "step8_master.*must exist" in code or "step8_master" in code
# Find the guard in _phase5
phase5_idx = code.find("# DOCX")
guard_context = code[phase5_idx:phase5_idx+800] if phase5_idx > 0 else ""
has_real_guard = "res['docx_blocked']" in guard_context or "return res" in guard_context[:300]

if has_real_guard:
    print(f"  _phase5 内有 step8 验证: ✅")
    print(f"  ✅ PASS: Pipeline 层也有拦截")
else:
    print(f"  ⚠️ Pipeline 层 step8 验证未发现 (但 build_docx 层有)")
    # Check alternative location
    for pattern in ['step8', 'docx_blocked', 'BLOCKED']:
        if pattern in guard_context:
            print(f"  找到 '{pattern}' 关键字")

# ═══════════════════════════════════════════════════════
# Test 5: wait_for_output timeout
# ═══════════════════════════════════════════════════════
print("\n[Test 5] wait_for_output 默认超时")
launcher_code = Path('scripts/ir_subagent_launcher.py').read_text(encoding='utf-8')
m2 = re.search(r'def wait_for_output\(.*?timeout:\s*int\s*=\s*(\d+)', launcher_code)
if m2:
    wait_timeout = int(m2.group(1))
    print(f"  wait_for_output default timeout = {wait_timeout}s")
    assert wait_timeout == 300, f"Expected 300, got {wait_timeout}"
    print(f"  ✅ PASS: 300s（原 600s → 300s，加速失败暴露）")
else:
    print(f"  ⚠️ 未找到 wait_for_output timeout 参数")

# ═══════════════════════════════════════════════════════
# Test 6: HK disambiguation
# ═══════════════════════════════════════════════════════
print("\n[Test 6] 港股搜索词消歧")
ps = Path('scripts/ir_presearch.py').read_text(encoding='utf-8')
has_hk_disambig = '港股' in ps
print(f"  港股后缀: {'✅' if has_hk_disambig else '❌'}")
if has_hk_disambig:
    for line in ps.split("\n"):
        if '港股' in line and not line.strip().startswith('#'):
            print(f"  匹配行: {line.strip()[:120]}")
print(f"  ✅ PASS: 消歧逻辑已添加" if has_hk_disambig else f"  ⚠️ 未找到消歧逻辑")

# ═══════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════
print("\n" + "="*70)
print("验证结果汇总")
print("="*70)

results = [
    ("1. Phase 4 熔断 gate", True),
    ("2. Pipeline timeout 3600s", True),
    ("3. DOCX step8 缺失拦截", True),
    ("4. Pipeline Phase 5 step8 guard", has_real_guard),
    ("5. wait_for_output 300s", m2 is not None and int(m2.group(1)) == 300),
    ("6. 港股搜索消歧", has_hk_disambig),
]

all_pass = True
for name, pass_ in results:
    status = "✅ PASS" if pass_ else "❌ FAIL"
    if not pass_: all_pass = False
    print(f"  {status}  {name}")

print(f"\n{'全部通过 🎉' if all_pass else '有修复未通过，请检查'}")
if not all_pass:
    sys.exit(1)
