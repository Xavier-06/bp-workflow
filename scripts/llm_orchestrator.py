#!/usr/bin/env python3
"""
LLM Orchestrator — Claude Code withRetry.ts 的 Python 精简版
=============================================================

管线 LLM 调用核心封装：
- 指数退避 + jitter（参考 withRetry.ts getRetryDelay）
- 529 overloaded → 特殊退避
- Retry-After header 尊重
- 连续 3 次 529 → fallback 备用模型
- 认证错误 (401/403) → 直接失败
- 不可重试的 4xx → 直接失败
- 自动报告 token/cost 到 Cost Tracker

用法（装饰器）：
    @llm_call(max_retries=5, fallback_model='qwen-turbo')
    def call_qwen(prompt: str) -> str:
        resp = requests.post(url, json=body)
        resp.raise_for_status()
        resp.json()

用法（直接调用）：
    result = llm_request('POST', url, json=body, phase='phase1', step='search')

用法（context manager — 手动控制）：
    with llm_call_ctx(phase='phase2', step='gap') as ctx:
        ctx.request(method='POST', url=url, json=body)
"""
from __future__ import annotations
import functools
import os
import random
import time
from typing import Optional, Callable, Any
from contextlib import contextmanager

# ═══════════════════════════════════════════════
# 配置（参考 withRetry.ts 常量）
# ═══════════════════════════════════════════════
DEFAULT_MAX_RETRIES = int(os.environ.get('LLM_MAX_RETRIES', '5'))
BASE_DELAY_MS = 500      # withRetry.ts: BASE_DELAY_MS = 500
MAX_DELAY_MS = 32_000    # withRetry.ts: maxDelayMs = 32000
MAX_529_BEFORE_FALLBACK = 3  # withRetry.ts: MAX_529_RETRIES = 3

# 禁用重试（调试用）
_DISABLED = os.environ.get('LLM_RETRY_DISABLED', '').lower() == 'true'

# 529 超载标记
_529_MARKERS = ['529', 'overloaded_error']

# 瞬态/可重试错误
_TRANSIENT_STATUSES = {429, 500, 502, 503, 504, 529}
_RETRYABLE_MSGS = ['timeout', 'connection', 'reset', 'econnreset', 'epipe', 'overloaded']

# 全局统计
_stats = {'calls': 0, 'retries': 0, 'fallbacks': 0, 'failures': 0}


# ═══════════════════════════════════════════════
# 错误检测（参考 withRetry.ts 的各种 isXxxError）
# ═══════════════════════════════════════════════
def _is_529(sc: int, body: str, error: Exception = None) -> bool:
    """是否是 529 超载错误。"""
    if sc == 529: return True
    text = body or (str(error) if error else '')
    return any(m in text for m in _529_MARKERS)

def _is_transient(sc: int, body: str, error: Exception = None) -> bool:
    """是否是瞬态错误（可安全重试）。"""
    if sc in _TRANSIENT_STATUSES: return True
    text = (body or '').lower() + (str(error) if error else '').lower()
    return any(k in text for k in _RETRYABLE_MSGS)

def _is_auth_error(sc: int) -> bool:
    """认证错误（不可重试）。"""
    return sc in (401, 403)


# ═══════════════════════════════════════════════
# 退避计算（参考 withRetry.ts getRetryDelay）
# ═══════════════════════════════════════════════
def _get_delay(attempt: int, retry_after: Optional[int] = None) -> float:
    """
    指数退避 + jitter。
    逻辑同 withRetry.ts getRetryDelay：
      delay = min(BASE_DELAY_MS * 2^(attempt-1), MAX_DELAY_MS) + jitter(0-25%)
    """
    if retry_after and retry_after > 0:
        return min(retry_after / 1000.0, MAX_DELAY_MS / 1000.0)
    delay = min(BASE_DELAY_MS * (2 ** (attempt - 1)), MAX_DELAY_MS)
    jitter = random.uniform(0, 0.25 * delay)  # 25% jitter
    return (delay + jitter) / 1000.0


# ═══════════════════════════════════════════════
# 装饰器 — 最简单用法
# ═══════════════════════════════════════════════
def llm_call(max_retries: int = DEFAULT_MAX_RETRIES,
             fallback_model: Optional[str] = None):
    """
    装饰器：给任何 LLM 调用函数添加重试。

    被装饰函数应该：
    - 成功时返回（任何值）
    - 失败时抛出异常（Requests HTTPError 或任何 Exception）

    @llm_call(max_retries=5, fallback_model='qwen-turbo')
    def my_llm_call(prompt: str) -> dict:
        resp = requests.post(url, json=body, timeout=60)
        resp.raise_for_status()
        return resp.json()
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if _DISABLED:
                return fn(*args, **kwargs)

            _stats['calls'] += 1
            last_error = None
            consecutive_529 = 0

            for attempt in range(1, max_retries + 2):
                try:
                    return fn(*args, **kwargs)

                except Exception as e:
                    last_error = e
                    sc = getattr(e, 'status_code', 0)
                    body = ''
                    resp = getattr(e, 'response', None)
                    if resp is not None:
                        sc = getattr(resp, 'status_code', sc)
                        body = getattr(resp, 'text', str(resp))

                    # 4xx（非 429/529）→ 直接失败
                    if 400 <= sc < 500 and sc not in (429,) and not _is_529(sc, body, e):
                        raise

                    if _is_529(sc, body, e):
                        consecutive_529 += 1
                        if attempt <= 3:
                            print(f"    ⚠ LLM 529 超载 (第{attempt}次)")

                        # 连续 3 次 529 → 触发 fallback
                        if consecutive_529 >= MAX_529_BEFORE_FALLBACK and fallback_model:
                            _stats['fallbacks'] += 1
                            print(f"    🔄 连续 {consecutive_529} 次 529，切换到: {fallback_model}")
                            # 注入 fallback model
                            kwargs['_fallback_model'] = fallback_model
                            kwargs['_model_override'] = fallback_model
                            consecutive_529 = 0

                    _stats['retries'] += 1

                    if attempt >= max_retries + 1:
                        _stats['failures'] += 1
                        raise

                    delay = _get_delay(attempt)
                    if _is_529(sc, body, e):
                        print(f"    ⚠ 529 超载，退避 {delay:.1f}s")
                    else:
                        print(f"    ⚠ LLM 错误 {sc}，退避 {delay:.1f}s")
                    time.sleep(delay)

            _stats['failures'] += 1
            raise LLMRetryError(f"LLM 调用失败，已重试 {max_retries} 次", last_error)
        return wrapper
    return decorator


# ═══════════════════════════════════════════════
# 直接请求函数 — requests 兼容
# ═══════════════════════════════════════════════
def llm_request(method: str, url: str,
                max_retries: int = DEFAULT_MAX_RETRIES,
                fallback_url: str = None,
                fallback_model: str = None,
                phase: str = None, step: str = None,
                model: str = None,
                **kwargs) -> 'requests.Response':
    """
    带重试的 HTTP 请求（兼容 requests 调用模式）。

    resp = llm_request('POST', API_URL, json=body, max_retries=5, phase='phase1')

    参数：
        fallback_url: 备用 API URL（如备用 dashscope endpoint）
        fallback_model: 备用模型名（用于 cost tracking 和 fallback 切换）
        phase, step, model: 用于成本统计
        **kwargs: 直接传给 requests.request()
    """
    import requests

    if _DISABLED:
        return requests.request(method, url, **kwargs)

    _stats['calls'] += 1
    current_url = url
    consecutive_529 = 0

    for attempt in range(1, max_retries + 2):
        t0 = time.time()
        try:
            resp = requests.request(method, current_url, **kwargs)
            dur = time.time() - t0
            sc = resp.status_code

            if 200 <= sc < 300:
                # 成本记录
                if phase and model:
                    from cost_tracker import add_call
                    add_call(phase, step, model, duration=dur)
                return resp

            # 529 处理
            is5 = _is_529(sc, resp.text[:500])
            if is5:
                consecutive_529 += 1
                print(f"    ⚠ LLM {sc} 超载 (第{attempt}次)")

            # 连续 529 → fallback
            if consecutive_529 >= MAX_529_BEFORE_FALLBACK and fallback_model:
                _stats['fallbacks'] += 1
                print(f"    🔄 连续 {consecutive_529} 次 529，切换模型: {fallback_model}")
                # 如果 json payload 里有 model 字段，尝试替换
                if 'json' in kwargs and isinstance(kwargs['json'], dict) and 'model' in kwargs['json']:
                    kwargs['json']['model'] = fallback_model
                consecutive_529 = 0

            # 不可重试
            if not _is_transient(sc, resp.text[:500]) and not is5:
                resp.raise_for_status()

            _stats['retries'] += 1
            if attempt >= max_retries + 1:
                if fallback_url and current_url != fallback_url:
                    print(f"    🔄 切换到备用 URL")
                    current_url = fallback_url
                    attempt = 0
                    continue
                _stats['failures'] += 1
                resp.raise_for_status()

            delay = _get_delay(attempt)
            if is5:
                print(f"    ⚠ 529 超载，退避 {delay:.1f}s")
            time.sleep(delay)

        except Exception as e:
            last_error = e
            sc = getattr(getattr(e, 'response', None), 'status_code', 0)
            body = getattr(getattr(e, 'response', None), 'text', '')

            if not _is_transient(sc, body, e) and not _is_529(sc, body, e):
                raise

            _stats['retries'] += 1
            if attempt >= max_retries + 1:
                if fallback_url and current_url != fallback_url:
                    current_url = fallback_url
                    attempt = 0
                    continue
                _stats['failures'] += 1
                if isinstance(e, requests.exceptions.RequestException):
                    raise
                raise LLMRetryError(f"LLM 请求失败", e)

            delay = _get_delay(attempt)
            print(f"    ⚠ LLM 异常 ({sc})，退避 {delay:.1f}s")
            time.sleep(delay)


# ═══════════════════════════════════════════════
# Context Manager — 最灵活
# ═══════════════════════════════════════════════
class LLMCall:
    """
    一次 LLM 调用的上下文。

    with LLMCall(phase='phase1', step='search') as call:
        call.response = requests.post(url, json=body, timeout=60)
        call.raise_for_status()
        call.record_tokens(input_tokens=2000, output_tokens=800)
        result = call.get_json()
    """
    def __init__(self, phase: str = None, step: str = None,
                 max_retries: int = DEFAULT_MAX_RETRIES,
                 model: str = None, fallback_model: str = None,
                 timeout: int = 60):
        self.phase = phase
        self.step = step
        self.max_retries = max_retries
        self.model = model or 'unknown'
        self.fallback_model = fallback_model
        self.timeout = timeout
        self.response = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost = 0
        self.attempt = 0
        self._t0 = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # atexit 会打印统计，这里不需要做额外事
        return False

    def raise_for_status(self):
        """检查响应状态码，失败时抛出（触发重试）。"""
        if self.response is None:
            raise LLMRetryError("No response set")
        sc = self.response.status_code
        if sc == 200:
            return

        # 检查是否瞬态错误
        is_transient = _is_transient(sc, self.response.text[:500])
        is_529 = _is_529(sc, self.response.text[:500])

        if is_transient or is_529:
            raise _RetrySignal(sc, is_529=is_529, body=self.response.text[:500])

        # 不可重试的错误 → 直接抛出
        self.response.raise_for_status()

    def get_json(self):
        return self.response.json()

    def get_text(self):
        return self.response.text

    def record_tokens(self, input_tokens: int, output_tokens: int, cost: float = 0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost = cost

    @property
    def ok(self) -> bool:
        return self.response is not None and self.response.status_code == 200


class _RetrySignal(Exception):
    """内部信号——触发重试。"""
    def __init__(self, status_code: int, is_529: bool = False, body: str = ''):
        self.status_code = status_code
        self.is_529 = is_529
        self.body = body
        super().__init__(f"LLM {status_code}{' (529)' if is_529 else ''}")


class LLMRetryError(Exception):
    def __init__(self, message: str, original_error=None):
        super().__init__(message)
        self.original_error = original_error


def make_llm_call(phase: str, step: str, max_retries: int = DEFAULT_MAX_RETRIES,
                  model: str = None, fallback_model: str = None,
                  timeout: int = 60, method: str = 'POST',
                  url: str = None, **request_kwargs):
    """
    最完整的用法——自动重试 + 自动记录成本。

    with make_llm_call('phase1', 'search', model='qwen-plus',
                       fallback_model='qwen-turbo',
                       url=API_URL, json=prompt, timeout=60) as call:
        call.raise_for_status()
        call.record_tokens(call.get_json()['input_tokens'],
                          call.get_json()['output_tokens'])
        result = call.get_json()
    """
    if _DISABLED:
        import requests
        ctx = LLMCall(phase, step, 0, model, fallback_model, timeout)
        ctx.response = requests.request(method, url, timeout=timeout, **request_kwargs)
        ctx.record_tokens(0, 0)
        yield ctx
        return

    call = LLMCall(phase, step, max_retries, model, fallback_model, timeout)
    t0 = time.time()
    consecutive_529 = 0
    last_error = None

    for attempt in range(1, max_retries + 2):
        call.attempt = attempt
        call.response = None
        try:
            import requests
            call.response = requests.request(method, url, **request_kwargs)
            call.raise_for_status()

            # 成功——记录成本
            dur = time.time() - t0
            from cost_tracker import add_call
            add_call(phase, step, call.model,
                    input_tokens=call.input_tokens,
                    output_tokens=call.output_tokens,
                    duration=dur)
            yield call
            return

        except _RetrySignal as e:
            last_error = e
            if e.is_529:
                consecutive_529 += 1
                if attempt <= 3:
                    print(f"    ⚠ LLM 529 超载 (第{attempt}次)")

                if consecutive_529 >= MAX_529_BEFORE_FALLBACK and fallback_model:
                    _stats['fallbacks'] += 1
                    print(f"    🔄 连续 {consecutive_529} 次 529 → {fallback_model}")
                    # 替换模型
                    if 'json' in request_kwargs and isinstance(request_kwargs['json'], dict):
                        request_kwargs['json']['model'] = fallback_model
                    call.model = fallback_model
                    consecutive_529 = 0

            _stats['retries'] += 1
            if attempt >= max_retries + 1:
                _stats['failures'] += 1
                raise LLMRetryError(f"LLM 调用失败 ({e.status_code})，已重试 {max_retries} 次", e)

            delay = _get_delay(attempt)
            if e.is_529:
                print(f"    ⚠ 529 超载，退避 {delay:.1f}s")
            else:
                print(f"    ⚠ LLM {e.status_code}，退避 {delay:.1f}s")
            time.sleep(delay)

        except Exception as e:
            last_error = e
            sc = getattr(getattr(e, 'response', None), 'status_code', 0)
            body = getattr(getattr(e, 'response', None), 'text', '')

            if not _is_transient(sc, body, e) and not _is_529(sc, body, e):
                _stats['failures'] += 1
                raise

            _stats['retries'] += 1
            if attempt >= max_retries + 1:
                _stats['failures'] += 1
                raise LLMRetryError(f"LLM 调用失败，已重试 {max_retries} 次", e)

            delay = _get_delay(attempt)
            print(f"    ⚠ LLM 异常 ({sc})，退避 {delay:.1f}s")
            time.sleep(delay)

    _stats['failures'] += 1
    raise LLMRetryError(f"LLM 调用失败，已重试 {max_retries} 次", last_error)


# ═══════════════════════════════════════════════
# 统计
# ═══════════════════════════════════════════════
def get_stats() -> dict:
    return dict(_stats)

def print_stats():
    s = _stats
    total = s['calls']
    if total > 0:
        fail_rate = s['failures'] / total * 100
        retry_rate = s['retries'] / total * 100
        print(f"\n  📡 LLM Retry Stats:")
        print(f"     调用: {total} | 重试: {s['retries']}({retry_rate:.0f}%) | "
              f"回退: {s['fallbacks']} | 失败: {s['failures']}({fail_rate:.0f}%)")

import atexit
