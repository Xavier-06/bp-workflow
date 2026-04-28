#!/usr/bin/env python3
"""
SearXNG 本地实例自动管理器

功能：
- auto_start: 自动检测并启动 SearXNG 本地实例
- status: 检查运行状态
- stop: 停止实例
- healthcheck: 健康检查

被 SearchGateway 和 ir_runtime.py 自动调用，无需手动启动。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SEARXNG_VENV = ROOT / 'tools' / 'searxng' / '.venv' / 'bin' / 'python'
SEARXNG_SOURCE = Path(os.environ.get('SEARXNG_SOURCE_DIR', '/Users/xavier/Downloads/searxng-master'))
PID_FILE = ROOT / 'tools' / 'searxng' / 'searxng-local.pid'
LOG_FILE = ROOT / 'tools' / 'searxng' / 'searxng-local.log'
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8888
SEARXNG_SECRET = os.environ.get('SEARXNG_SECRET', 'workbuddy-ir-secret-2026')
STARTUP_TIMEOUT = 30  # 秒


def _port() -> int:
    """从 config 或环境变量读取端口"""
    return int(os.environ.get('SEARXNG_PORT', DEFAULT_PORT))


def _base_url() -> str:
    return f'http://{DEFAULT_HOST}:{_port()}'


def is_running() -> bool:
    """检查 SearXNG 进程是否存活"""
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)  # 信号 0 只检查进程存在
        return True
    except (ProcessLookupError, ValueError, PermissionError):
        return False


def healthcheck() -> bool:
    """检查 SearXNG 是否正常响应"""
    import urllib.request
    url = f'{_base_url()}/healthz'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'WorkBuddy-SearXNG-Manager/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        # 尝试首页（有些版本没有 /healthz）
        try:
            req = urllib.request.Request(_base_url(), headers={'User-Agent': 'WorkBuddy-SearXNG-Manager/1.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False


def search_test(query: str = 'OpenAI') -> bool:
    """快速搜索测试，确认搜索功能可用"""
    import urllib.request
    url = f'{_base_url()}/search?q={query}&format=json'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'WorkBuddy-SearXNG-Manager/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return len(data.get('results', [])) > 0
    except Exception:
        return False


def start(wait: bool = True) -> bool:
    """启动 SearXNG 本地实例
    
    Args:
        wait: 是否等待启动完成并通过健康检查
        
    Returns:
        True 如果启动成功或已在运行
    """
    if is_running() and healthcheck():
        logger.info('SearXNG already running on %s', _base_url())
        return True

    # 检查 venv
    if not SEARXNG_VENV.exists():
        logger.error('SearXNG venv not found at %s', SEARXNG_VENV)
        return False

    # 检查源码
    if not SEARXNG_SOURCE.exists():
        logger.error('SearXNG source not found at %s', SEARXNG_SOURCE)
        return False

    # 确保日志目录存在
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # 清理旧 PID
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            os.kill(old_pid, 0)
            os.kill(old_pid, 15)  # SIGTERM
            time.sleep(1)
        except (ProcessLookupError, ValueError, PermissionError):
            pass
        PID_FILE.unlink(missing_ok=True)

    # SSL 证书路径（macOS homebrew）
    cert_pem = '/opt/homebrew/etc/openssl@3/cert.pem'
    cert_dir = '/opt/homebrew/etc/openssl@3/certs'

    port = _port()

    # 启动命令
    env = {
        **os.environ,
        'SEARXNG_SECRET': SEARXNG_SECRET,
        'SEARXNG_BIND_ADDRESS': DEFAULT_HOST,
        'SEARXNG_PORT': str(port),
        'PYTHONPATH': str(SEARXNG_SOURCE),
    }
    if Path(cert_pem).exists():
        env.update({
            'SSL_CERT_FILE': cert_pem,
            'REQUESTS_CA_BUNDLE': cert_pem,
            'CURL_CA_BUNDLE': cert_pem,
            'SSL_CERT_DIR': cert_dir,
        })

    log_fh = open(LOG_FILE, 'w')
    try:
        proc = subprocess.Popen(
            [str(SEARXNG_VENV), '-m', 'searx.webapp'],
            env=env,
            stdout=log_fh,
            stderr=log_fh,
            stdin=subprocess.DEVNULL,
            cwd=str(SEARXNG_SOURCE),
        )
    except Exception as e:
        logger.error('Failed to start SearXNG: %s', e)
        log_fh.close()
        return False

    # 写 PID
    PID_FILE.write_text(str(proc.pid))
    logger.info('SearXNG started (pid=%d, port=%d)', proc.pid, port)

    if not wait:
        return True

    # 等待健康检查通过
    for i in range(STARTUP_TIMEOUT // 2):
        time.sleep(2)
        if healthcheck():
            logger.info('SearXNG healthcheck passed after %ds', (i + 1) * 2)
            return True
        # 检查进程是否已退出
        if proc.poll() is not None:
            logger.error('SearXNG process exited with code %d', proc.returncode)
            log_fh.close()
            return False

    logger.warning('SearXNG healthcheck timed out after %ds', STARTUP_TIMEOUT)
    log_fh.close()
    return False


def stop() -> bool:
    """停止 SearXNG 实例"""
    if not PID_FILE.exists():
        # 尝试按端口杀进程
        return _kill_by_port()

    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 15)  # SIGTERM
        time.sleep(1)
        try:
            os.kill(pid, 0)
            os.kill(pid, 9)  # SIGKILL
        except ProcessLookupError:
            pass
    except (ValueError, PermissionError):
        pass
    finally:
        PID_FILE.unlink(missing_ok=True)

    return True


def _kill_by_port() -> bool:
    """按端口杀 SearXNG 进程"""
    port = _port()
    try:
        result = subprocess.run(
            ['lsof', '-ti', f':{port}'],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split('\n')
        for pid in pids:
            pid = pid.strip()
            if pid:
                os.kill(int(pid), 15)
        return True
    except Exception:
        return False


def auto_start() -> bool:
    """自动检测并启动 — 被 SearchGateway 和 ir_runtime.py 调用
    
    如果已经运行且健康，直接返回 True。
    如果没运行，自动启动并等待健康检查。
    """
    if is_running() and healthcheck():
        return True

    logger.info('SearXNG not running or unhealthy, auto-starting...')
    return start(wait=True)


def status() -> dict:
    """返回详细状态信息"""
    port = _port()
    running = is_running()
    healthy = healthcheck() if running else False
    search_ok = search_test() if healthy else False
    
    pid = None
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
        except ValueError:
            pass

    return {
        'running': running,
        'healthy': healthy,
        'search_ok': search_ok,
        'pid': pid,
        'base_url': _base_url(),
        'port': port,
        'venv_exists': SEARXNG_VENV.exists(),
        'source_exists': SEARXNG_SOURCE.exists(),
        'log_file': str(LOG_FILE),
    }


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    
    if cmd == 'start':
        ok = start(wait=True)
        print(f'SearXNG start: {"OK" if ok else "FAILED"}')
        sys.exit(0 if ok else 1)
    elif cmd == 'stop':
        ok = stop()
        print(f'SearXNG stop: {"OK" if ok else "FAILED"}')
        sys.exit(0 if ok else 1)
    elif cmd == 'restart':
        stop()
        ok = start(wait=True)
        print(f'SearXNG restart: {"OK" if ok else "FAILED"}')
        sys.exit(0 if ok else 1)
    elif cmd == 'status':
        s = status()
        for k, v in s.items():
            print(f'  {k}: {v}')
    elif cmd == 'healthcheck':
        ok = healthcheck()
        print(f'healthcheck: {"OK" if ok else "FAIL"}')
        sys.exit(0 if ok else 1)
    else:
        print(f'Usage: {sys.argv[0]} {start|stop|restart|status|healthcheck}')
        sys.exit(1)
