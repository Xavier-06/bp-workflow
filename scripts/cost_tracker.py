#!/usr/bin/env python3
"""
Cost Tracker — Claude Code cost-tracker.ts 的 Python 移植
==========================================================

管线每次 LLM 调用自动记录：phase/step、模型、token 数、成本估算、耗时。
管线退出时打印汇总报告。

用法：
    # 全局单例
    from cost_tracker import tracker, add_call, print_summary

    add_call(
        phase="phase1", step="presearch", model="qwen-plus",
        input_tokens=1200, output_tokens=400, cost=0.003, duration=2.4
    )

    # 或用 context manager 自动计时
    from cost_tracker import track_call
    with track_call("phase1", "search", model="gpt-5.2"):
        result = llm_call(prompt)  # 手动记录 token
        record_tokens(result.usage.input_tokens, result.usage.output_tokens)

    # 退出时自动打印汇总（atexit 注册）
"""
from __future__ import annotations
import atexit
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════════════
# 模型价格表（每百万 token 的 USD 成本）
# ═══════════════════════════════════════════════
MODEL_PRICES = {
    # Qwen / 通义
    'qwen-plus':        {'input': 0.0004, 'output': 0.0012},   # 约 0.4/1.2 per M
    'qwen-max':         {'input': 0.0020, 'output': 0.0060},
    'qwen-turbo':       {'input': 0.0002, 'output': 0.0006},
    'qwen-vl-max':      {'input': 0.0030, 'output': 0.0090},   # OCR 用
    'qwen3.6-plus':      {'input': 0.0005, 'output': 0.0015},
    'qwen3.6-plus:free':{'input': 0.0,      'output': 0.0},    # free tier
    'qwen3.6-plus:free': {'input': 0.0,     'output': 0.0},
    # Claude
    'claude-sonnet-4-6': {'input': 0.003, 'output': 0.015},
    'claude-sonnet-4-5': {'input': 0.003, 'output': 0.015},
    'claude-haiku-4-5':  {'input': 0.001, 'output': 0.005},
    'claude-opus-4-6':   {'input': 0.015, 'output': 0.075},
    # GPT
    'gpt-5.2':           {'input': 0.003, 'output': 0.010},
    'gpt-5':             {'input': 0.003, 'output': 0.010},
    'gpt-4o':            {'input': 0.003, 'output': 0.010},
    'gpt-4o-mini':       {'input': 0.0003, 'output': 0.001},   # ~$0.15/0.60
    # Fallback
    'unknown':           {'input': 0.003, 'output': 0.010},
}


# ═══════════════════════════════════════════════
# 调用记录
# ═══════════════════════════════════════════════
@dataclass
class LLMApiCall:
    phase: str           # "phase0", "phase1", "phase3"
    step: str            # "preflight", "presearch", "deep_drill"
    model: str           # "qwen-plus", "gpt-5.2"
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    duration: float = 0.0       # 秒
    status: str = 'ok'          # 'ok' | 'error'
    timestamp: float = 0.0
    metadata: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════
# CostTracker 单例
# ═══════════════════════════════════════════════
class CostTracker:
    """线程安全的 LLM 调用成本追踪器。"""

    def __init__(self, enabled: bool = True):
        self._enabled = enabled and os.environ.get('COST_TRACKER_DISABLED', '').lower() != 'true'
        self._calls: list[LLMApiCall] = []
        self._lock = threading.Lock()
        self._total_cost = 0.0
        self._total_input = 0
        self._total_output = 0
        self._total_duration = 0.0
        self._printed = False

    def add_call(self, phase: str, step: str, model: str,
                 input_tokens: int = 0, output_tokens: int = 0,
                 cost: Optional[float] = None,
                 duration: float = 0.0,
                 status: str = 'ok',
                 metadata: Optional[dict] = None):
        """记录一次 LLM 调用。"""
        if not self._enabled:
            return False

        if cost is None:
            cost = self._estimate_cost(model, input_tokens, output_tokens)

        call = LLMApiCall(
            phase=phase, step=step, model=model,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cost=cost, duration=duration, status=status,
            timestamp=time.time(), metadata=metadata or {},
        )

        with self._lock:
            self._calls.append(call)
            self._total_cost += cost
            self._total_input += input_tokens
            self._total_output += output_tokens
            self._total_duration += duration

        return True

    @contextmanager
    def track(self, phase: str, step: str, model: str = 'unknown',
              metadata: Optional[dict] = None):
        """
        Context manager 用法：
         with tracker.track("phase1", "presearch", model="qwen-plus") as ctx:
             result = call_api()
             ctx.record_tokens(result.input_tokens, result.output_tokens)
        """
        t0 = time.time()
        ctx = self._TrackContext()
        try:
            yield ctx
        except Exception as e:
            dur = time.time() - t0
            self.add_call(phase, step, model,
                         input_tokens=ctx.input_tokens,
                         output_tokens=ctx.output_tokens,
                         duration=dur, status='error',
                         metadata={**(metadata or {}), 'error': str(e)})
            raise
        dur = time.time() - t0
        self.add_call(phase, step, model,
                     input_tokens=ctx.input_tokens,
                     output_tokens=ctx.output_tokens,
                     cost=ctx.cost_override or None,
                     duration=dur, status='ok',
                     metadata=metadata)

    def _estimate_cost(self, model: str, inp: int, out: int) -> float:
        """根据模型价格表估算成本。"""
        prices = MODEL_PRICES.get(model, MODEL_PRICES['unknown'])
        return (prices['input'] * inp + prices['output'] * out) / 1_000_000

    # ═══════════════════════════════════════════════
    # 汇总
    # ═══════════════════════════════════════════════
    def summary(self) -> str:
        """生成汇总报告字符串。"""
        with self._lock:
            calls = list(self._calls)
            total_cost = self._total_cost
            total_input = self._total_input
            total_output = self._total_output
            total_dur = self._total_duration

        if not calls:
            return "  Cost Tracker: 无 LLM 调用记录"

        # 按 phase + step 聚合
        phases: dict[str, dict] = {}
        models: dict[str, dict] = {}
        for c in calls:
            pk = f"{c.phase}.{c.step}"
            if pk not in phases:
                phases[pk] = {'inp': 0, 'out': 0, 'cost': 0.0, 'count': 0}
            phases[pk]['inp'] += c.input_tokens
            phases[pk]['out'] += c.output_tokens
            phases[pk]['cost'] += c.cost
            phases[pk]['count'] += 1

            if c.model not in models:
                models[c.model] = {'inp': 0, 'out': 0, 'cost': 0.0}
            models[c.model]['inp'] += c.input_tokens
            models[c.model]['out'] += c.output_tokens
            models[c.model]['cost'] += c.cost

        lines = []
        lines.append(f"\n{'='*60}")
        lines.append(f"  📊 Token 费用汇总")
        lines.append(f"{'='*60}")

        # 按 Phase 详情
        lines.append(f"\n  按 Phase 细分:")
        for pk, v in sorted(phases.items()):
            lines.append(f"    {pk:<30}  {v['inp']:>8,} in → {v['out']:>8,} out  ({v['cost']:.4f}) [{v['count']} 次]")

        # 按模型聚合
        lines.append(f"\n  按模型聚合:")
        line_width = max(len(m) for m in models)
        lines.append(f"    {'模型':<{line_width}}  {'输入 Token':>12}  {'输出 Token':>12}  成本")
        lines.append(f"    {'-'*line_width}  {'-'*12}  {'-'*12}  {'-'*10}")
        for m, v in sorted(models.items(), key=lambda x: x[1]['cost'], reverse=True):
            lines.append(f"    {m:<{line_width}}  {v['inp']:>12,}  {v['out']:>12,}  ${v['cost']:.4f}")

        # 总计
        lines.append(f"\n  {'─'*52}")
        lines.append(f"  {'Total':<{line_width}}  {total_input:>12,} in → {total_output:>12,} out  (${total_cost:.4f})")
        lines.append(f"  总耗时: {total_dur:.1f}s ({len(calls)} 次调用)")
        lines.append(f"{'='*60}")

        return '\n'.join(lines)

    def print_summary(self):
        """打印汇总（只打印一次）。"""
        with self._lock:
            if self._printed or not self._calls:
                return
            self._printed = True

        print(self.summary())

    # ═══════════════════════════════════════════
    # 内部 context
    # ═══════════════════════════════════════════
    class _TrackContext:
        def __init__(self):
            self.input_tokens = 0
            self.output_tokens = 0
            self.cost_override = None

        def record_tokens(self, inp: int, out: int, cost: Optional[float] = None):
            self.input_tokens = inp
            self.output_tokens = out
            if cost is not None:
                self.cost_override = cost


# ═══════════════════════════════════════════════
# 全局单例 + Atexit
# ═══════════════════════════════════════════════
tracker = CostTracker()

def add_call(phase: str, step: str, model: str, **kwargs):
    """快捷函数：记录一次 LLM 调用。"""
    return tracker.add_call(phase, step, model, **kwargs)

@contextmanager
def track_call(phase: str, step: str, model: str = 'unknown', **kw):
    """Context manager 快捷函数。"""
    with tracker.track(phase, step, model, **kw) as ctx:
        yield ctx

def print_summary():
    tracker.print_summary()

# 进程退出时自动打印
