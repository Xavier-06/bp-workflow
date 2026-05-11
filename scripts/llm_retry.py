#!/usr/bin/env python3
"""
LLM Retry Wrapper — Claude Code withRetry.ts 的 Python 移植
===========================================================

管线 LLM 调用零重试 = 一个网络抖动整条管线报废。
这个模块提供指数退避 + 529/429 检测 + 模型 fallback。

用法：

    # 方式 1：装饰器
    @retry_llm(max_retries=5, fallback_model='qwen-turbo')
    def call_llm(prompt: str) -> str:
        resp = requests.post(API_URL, json={...})
        resp.raise_for_status()
        return resp.json()

    # 方式 2：context manager
    with llm_call("phase1", "search", max_retries=5) as ctx:
        ctx.response = requests.post(URL, json=payload)
        ctx.raise_for_status()  # 自动重试

    # 方式 3：直接函数
    resp = retry_request("POST", url, json=payload, max_retries=5)

支持的环境变量：
    LLM_RETRY_DISABLED=true    — 关闭重试
    LLM_MAX_RETRIES=10         — 覆盖默认最大重试次数
"""
from __future__ import annotations
import atexit
import functools
import json
import os
import random
import time
from contextlib import contextmanager
from typing import Optional

# ═══════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════
DEFAULT_MAX_RETRIES = int(os.environ.get('LLM_MAX_RETRIES', '5'))
BASE_DELAY_MS = 500
MAX_DELAY_MS = 32_000  # 32 秒
DISABLED = os.environ.get('LLM_RETRY_DISABLED', '').lower() == 'true'

# 529 超时（Claude Code 的 overloaded_error）
_529_MARKERS = ['529', 'overloaded_error', 'Service Unavailable', 'server overloaded']

# 可重试的瞬态错误
TRANSIENT_ERRORS = {429, 500, 502, 503, 504, 529}

# ═══════════════════════════════════════════════
# 内部统计
# ═══════════════════════════════════════════════
_stats = {
    'calls': 0,
    'retries': 0,
    'fallbacks': 0,
    'failures': 0,
}

def _print_stats():
    if _stats['calls'] > 0:
        print(f"\n  📡 LLM Retry Stats: {_stats['calls']} 调用, "
              f"{_stats['retries']} 重试, {_stats['fallbacks']} 次 fallback, "
              f"{_stats['failures']} 失败")
atexit.register(_print_stats)


# ═══════════════════════════════════════════════
# 错误检测
# ═══════════════════════════════════════════════
def _is_529(response=None, error=None) -> bool:
    """检测 529 超载错误（含 Claude Code 的 overloaded_error 模式）。"""
    if response is not None:
        status = getattr(response, 'status_code', None) or (response.get('status_code') if isinstance(response, dict) else None)
        if status == 529: return True
        text = str(getattr(response, 'text', '') or str(response))
        if any(m in text for m in _529_MARKERS): return True
    if error is not None:
        msg = str(error)
        if any(m in msg for m in _529_MARKERS): return True
    return False

def _is_transient(status: int, error=None) -> bool:
    """是否是瞬态错误（可重试）。"""
    if status in TRANSIENT_ERRORS: return True
    if error:
        msg = str(error).lower()
        if any(k in msg for k in ['timeout', 'connection', 'reset', 'econnreset', 'epipe', 'overloaded']):
            return True
    return False


# ═══════════════════════════════════════════════
# 退避计算
# ═══════════════════════════════════════════════
def _get_delay(attempt: int, retry_after: Optional[int] = None) -> float:
    """指数退避 + jitter。参考 withRetry.ts 的 getRetryDelay。"""
    if retry_after and retry_after > 0:
        return min(retry_after, MAX_DELAY_MS / 1000)

    delay = min(BASE_DELAY_MS * (2 ** (attempt - 1)), MAX_DELAY_MS)
    jitter = random.uniform(0, 0.25 * delay)  # 25% jitter
    return (delay + jitter) / 1000.0  # 返回秒


# ═══════════════════════════════════════════════
# 装饰器
# ═══════════════════════════════════════════════
def retry_llm(max_retries: int = DEFAULT_MAX_RETRIES,
              fallback_model: Optional[str] = None):
    """
    装饰器：给 LLM 调用函数添加重试。

    被装饰函数应该在重试耗尽时抛出异常（任何异常）。
    RetryError 会尝试 fallback model（如果指定）。

    用法：
        @retry_llm(max_retries=5, fallback_model='qwen-turbo')
        def call_llm(prompt: str) -> str:
            resp = requests.post(url, json=body, timeout=60)
            resp.raise_for_status()
            return resp.json()
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            _stats['calls'] += 1
            last_error = None
            current_model = kwargs.pop('_model', None)

            for attempt in range(1, max_retries + 2):
                if attempt > 1:
                    _stats['retries'] += 1

                try:
                    if current_model:
                        kwargs['_model'] = current_model
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    status = getattr(e, 'status_code', 0) or getattr(e, 'response', None)
                    if hasattr(status, 'status_code'): status = status.status_code

                    # 529 超载：打印友好提示
                    if _is_529(error=e):
                        print(f"    ⚠ LLM 529 超载 (第{attempt}次)，退避 {_get_delay(attempt):.1f}s")

                    # 不可重试的 4xx（400, 401, 403 等）直接失败
                    if 400 <= status < 500 and status not in (429,):
                        raise

                    # 超过重试次数
                    if attempt >= max_retries + 1:
                        # 尝试 fallback
                        if fallback_model and current_model != fallback_model:
                            _stats['fallbacks'] += 1
                            print(f"    🔄 切换到 fallback: {fallback_model}")
                            current_model = fallback_model
                            attempt = 0  # 重置计数器
                            continue
                        _stats['failures'] += 1
                        raise

                    # 退避
                    delay = _get_delay(attempt)
                    if attempt <= 3:
                        time.sleep(delay)
                    else:
                        print(f"    ⏳ LLM 错误: {e} (第{attempt}/{max_retries+1}次，等待 {delay:.1f}s)")
                        time.sleep(delay)

            raise RetryError(f"LLM 调用失败，已重试 {max_retries} 次", last_error)
        return wrapper
    return decorator


# ═══════════════════════════════════════════════
# Context Manager
# ═══════════════════════════════════════════════
class LLMCallContext:
    def __init__(self, phase: str, step: str, max_retries: int = DEFAULT_MAX_RETRIES,
                 timeout: int = 60, model: str = 'unknown', fallback_model: str = None):
        self.phase = phase
        self.step = step
        self.max_retries = max_retries
        self.timeout = timeout
        self.model = model
        self.fallback_model = fallback_model
        self.response = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.attempt = 0
        self._t0 = None

    def raise_for_status(self):
        """检查响应状态，必要时重试。"""
        if self.response is None:
            raise RetryError("No response set")

        sc = getattr(self.response, 'status_code', None) or (self.response.get('status_code') if isinstance(self.response, dict) else 200)
        text = getattr(self.response, 'text', str(self.response))

        # 成功
        if 200 <= (sc or 200) < 300:
            return

        # 检查是否瞬态错误
        if not _is_transient(sc or 0, text) and not _is_529(response=self.response):
            if sc == 400:
                raise RetryError(f"LLM 400: {text[:300]}")
            elif sc in (401, 403):
                raise RetryError(f"LLM 认证错误 {sc}: {text[:300]}")
            else:
                raise RetryError(f"LLM 错误 {sc}: {text[:300]}")

        raise _ContextRetryError(sc, text)

    def get_json(self):
        """获取 JSON 响应。"""
        if isinstance(self.response, dict):
            return self.response
        if hasattr(self.response, 'json'):
            return self.response.json()
        return json.loads(self.response)

    def get_text(self):
        """获取文本响应。"""
        if isinstance(self.response, str):
            return self.response
        if hasattr(self.response, 'text'):
            return self.response.text
        return str(self.response)


class _ContextRetryError(Exception):
    """Context manager 内部使用的重试信号。"""
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        super().__init__(f"LLM {status_code}")

class RetryError(Exception):
    def __init__(self, message: str, original_error=None):
        super().__init__(message)
        self.original_error = original_error


@contextmanager
def llm_call(phase: str, step: str, max_retries: int = DEFAULT_MAX_RETRIES,
             timeout: int = 60, model: str = 'unknown', fallback_model: str = None):
    """
    Context manager 用法：

    with llm_call("phase1", "search", model="qwen-plus", max_retries=5, timeout=60) as ctx:
        ctx.response = requests.post(API_URL, json=body, timeout=timeout)
        ctx.raise_for_status()
        result = ctx.get_json()
    """
    if DISABLED:
        ctx = LLMCallContext(phase, step, 0, timeout, model)
        yield ctx
        return

    ctx = LLMCallContext(phase, step, max_retries, timeout, model, fallback_model)
    ctx._t0 = time.time()
    current_model = model
    last_error = None

    for attempt in range(1, max_retries + 2):
        ctx.attempt = attempt
        ctx.response = None
        try:
            ctx.model = current_model
            yield ctx

            # 成功
            dur = time.time() - ctx._t0
            from cost_tracker import add_call as _cost
            _cost(phase, step, current_model,
                  input_tokens=ctx.input_tokens, output_tokens=ctx.output_tokens,
                  duration=dur)
            return

        except _ContextRetryError as e:
            last_error = e
            if attempt >= max_retries + 1:
                if fallback_model and current_model != fallback_model:
                    _stats['fallbacks'] += 1
                    print(f"    🔄 切换到 fallback: {fallback_model}")
                    current_model = fallback_model
                    attempt = 0
                    continue
                _stats['failures'] += 1
                raise RetryError(f"LLM {e.status_code} after {max_retries} retries", e)

            delay = _get_delay(attempt)
            if _is_529(response=e.text):
                print(f"    ⚠ LLM 529 超载 (重试 {attempt}/{max_retries})，退避 {delay:.1f}s")
            else:
                print(f"    ⚠ LLM 错误 {e.status_code} (重试 {attempt}/{max_retries})，退避 {delay:.1f}s")

            _stats['retries'] += 1
            time.sleep(delay)

        except Exception as e:
            last_error = e
            if _is_transient(0, e):
                if attempt >= max_retries + 1:
                    if fallback_model and current_model != fallback_model:
                        _stats['fallbacks'] += 1
                        current_model = fallback_model
                        attempt = 0
                        continue
                    _stats['failures'] += 1
                    raise RetryError(f"LLM call failed after {max_retries} retries: {e}", e)

                delay = _get_delay(attempt)
                print(f"    ⚠ LLM 异常 (重试 {attempt}/{max_retries})，退避 {delay:.1f}s")
                _stats['retries'] += 1
                time.sleep(delay)
            else:
                _stats['failures'] += 1
                raise

    _stats['failures'] += 1
    raise RetryError(f"LLM call failed after {max_retries} retries", last_error)


# ═══════════════════════════════════════════════
# requests 快捷函数
# ═══════════════════════════════════════════════
def retry_request(method: str, url: str, max_retries: int = DEFAULT_MAX_RETRIES,
                  fallback_url: str = None, **kwargs) -> 'requests.Response':
    """
    带重试的 requests 调用。

    usage:
        resp = retry_request('POST', API_URL, json=body, max_retries=5, timeout=60)
    """
    import requests
    timeout = kwargs.pop('timeout', 60)
    kwargs.setdefault('timeout', timeout)

    current_url = url
    last_error = None

    for attempt in range(1, max_retries + 2):
        try:
            resp = requests.request(method, current_url, **kwargs)
            sc = resp.status_code

            if 200 <= sc < 300:
                return resp

            if not _is_transient(sc) and not _is_529(response=resp):
                resp.raise_for_status()

            if attempt >= max_retries + 1:
                if fallback_url and current_url != fallback_url:
                    _stats['fallbacks'] += 1
                    current_url = fallback_url
                    attempt = 0
                    continue
                resp.raise_for_status()

            delay = _get_delay(attempt)
            _stats['retries'] += 1
            if _is_529(response=resp):
                print(f"    ⚠ LLM 529 超载 (重试 {attempt}/{max_retries})，退避 {delay:.1f}s")
            time.sleep(delay)

        except Exception as e:
            last_error = e
            if _is_transient(0, e) or _is_529(error=e):
                if attempt >= max_retries + 1:
                    if fallback_url and current_url != fallback_url:
                        current_url = fallback_url
                        attempt = 0
                        continue
                    raise
                delay = _get_delay(attempt)
                _stats['retries'] += 1
                time.sleep(delay)
            else:
                raise

    raise RetryError(f"Request failed after {max_retries} retries", last_error)


# ═══════════════════════════════════════════════
# 全局统计
# ═══════════════════════════════════════════════
def get_stats() -> dict:
    return dict(_stats)
