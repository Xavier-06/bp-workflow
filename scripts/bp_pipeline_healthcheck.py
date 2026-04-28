#!/usr/bin/env python3
from __future__ import annotations
import json, os, socket, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / 'scripts'
DDGS_BIN = os.getenv('DDGS_BIN', '/opt/homebrew/bin/ddgs')


def port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def cmd_ok(cmd: list[str], timeout: int = 15) -> tuple[bool, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        ok = p.returncode == 0
        msg = (p.stdout or p.stderr or '').strip()[:300]
        return ok, msg
    except Exception as e:
        return False, repr(e)


def main() -> int:
    checks = {}
    checks['ddgs_cli'] = {
        'ok': os.path.exists(DDGS_BIN),
        'detail': DDGS_BIN,
    }
    ok, msg = cmd_ok([DDGS_BIN, 'version']) if os.path.exists(DDGS_BIN) else (False, 'binary missing')
    checks['ddgs_version'] = {'ok': ok, 'detail': msg}
    sear_18080 = port_open('127.0.0.1', 18080)
    sear_8888 = port_open('127.0.0.1', 8888)
    checks['searxng_local'] = {'ok': sear_18080 or sear_8888, 'detail': f'18080={sear_18080}, 8888={sear_8888}'}

    # qwen / dashscope env heuristic (advisory for now)
    qwen_env = any(os.getenv(k) for k in ['DASHSCOPE_API_KEY', 'QWEN_API_KEY'])
    checks['qwen_ocr_key'] = {'ok': True, 'detail': 'configured' if qwen_env else 'missing env (advisory only)'}

    dg = SCRIPTS / 'delivery_guard.py'
    checks['delivery_guard_script'] = {'ok': dg.exists(), 'detail': str(dg)}
    ok, msg = cmd_ok(['python3', str(dg)], timeout=10) if dg.exists() else (False, 'missing script')
    checks['delivery_guard_cli'] = {'ok': ('Usage:' in msg) or ok, 'detail': msg}

    launcher = SCRIPTS / 'bp_subagent_launcher.py'
    checks['phase4_launcher'] = {'ok': launcher.exists(), 'detail': str(launcher)}

    overall = all(v.get('ok') for v in checks.values() if v is not None)
    result = {'overall_ok': overall, 'checks': checks}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if overall else 2


if __name__ == '__main__':
    raise SystemExit(main())
