#!/usr/bin/env python3
"""
IR Pipeline WorkBuddy Adapter
==============================
WorkBuddy 环境下的 IR 研报管线统一入口。

职责:
1. 环境检测 — Python 依赖、API 凭证、搜索服务
2. 任务创建 — 通过 run_ir_task.py 创建投研任务
3. 管线执行 — 通过 run_ir_pipeline.py 运行 Phase 0→5
4. 结果交付 — DOCX 输出路径返回

用法:
    python3 ir_runtime.py check                    # 环境检测
    python3 ir_runtime.py create "东江环保" 专题研究类  # 创建任务
    python3 ir_runtime.py run TASK-XXXXX            # 执行管线
    python3 ir_runtime.py status TASK-XXXXX         # 查看状态
    python3 ir_runtime.py list                      # 列出所有任务

Note:
    - 本脚本位于 ir_runtime/ 根目录，自动检测运行环境
    - 凭证文件: .credentials/investment-research.env
    - 输出目录: outputs/
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# ─── 路径设置 ─────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT / 'scripts'
TASKS_DIR = ROOT / 'data' / 'tasks'
OUTPUTS_DIR = ROOT / 'outputs'
CREDENTIALS_FILE = ROOT / '.credentials' / 'investment-research.env'

# 确保关键目录存在
for d in [TASKS_DIR, OUTPUTS_DIR, ROOT / 'logs', ROOT / 'sessions']:
    d.mkdir(parents=True, exist_ok=True)

# SSL 证书（自动探测，用户可通过 SSL_CERT_PATH 环境变量覆盖）
_cert = os.getenv('SSL_CERT_PATH', '')
if not _cert:
    for _p in ['/opt/homebrew/etc/openssl@3/cert.pem', '/usr/local/etc/openssl@3/cert.pem',
               '/etc/ssl/certs/ca-certificates.crt', '/etc/pki/tls/certs/ca-bundle.crt']:
        if os.path.exists(_p):
            _cert = _p
            break
if _cert:
    os.environ.setdefault('SSL_CERT_FILE', _cert)
    os.environ.setdefault('REQUESTS_CA_BUNDLE', _cert)

# scripts/ 加入 sys.path
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _sh(cmd, **kwargs):
    """运行子进程命令，返回 CompletedProcess"""
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _py(script_name, *args):
    """用当前 Python 运行 scripts/ 下的脚本"""
    script = SCRIPTS_DIR / script_name
    if not script.exists():
        print(f"❌ 脚本不存在: {script}")
        return None
    return _sh([sys.executable, str(script)] + list(args))


def _load_env():
    """从 .credentials/investment-research.env 加载环境变量"""
    if not CREDENTIALS_FILE.exists():
        return False
    with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, val = line.partition('=')
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val:
                os.environ.setdefault(key, val)
    return True


# ═══════════════════════════════════════════════════════
# 1. 环境检测
# ═══════════════════════════════════════════════════════
def check_environment():
    """检测运行环境，返回检测结果 dict"""
    results = {
        'python': sys.version.split()[0],
        'root': str(ROOT),
        'checks': {}
    }

    # 1. 凭证文件
    has_creds = CREDENTIALS_FILE.exists()
    results['checks']['credentials'] = {
        'ok': has_creds,
        'path': str(CREDENTIALS_FILE),
        'msg': '凭证文件存在' if has_creds else '⚠️ 缺少 .credentials/investment-research.env'
    }

    # 2. 加载凭证检查 API keys
    if has_creds:
        _load_env()
    dashscope_key = os.environ.get('DASHSCOPE_API_KEY', '')
    results['checks']['dashscope'] = {
        'ok': bool(dashscope_key),
        'msg': 'DASHSCOPE_API_KEY 已设置' if dashscope_key else '⚠️ DASHSCOPE_API_KEY 未设置'
    }

    # 3. 核心依赖模块
    core_modules = {
        'task_registry': 'task_registry.py',
        'hook_dispatcher': 'hook_dispatcher.py',
        'ir_preflight_check': 'ir_preflight_check.py',
        'ir_presearch': 'ir_presearch.py',
        'ir_extract_content': 'ir_extract_content.py',
        'ir_gap_detector': 'ir_gap_detector.py',
        'ir_query_rewriter': 'ir_query_rewriter.py',
        'ir_subagent_launcher': 'ir_subagent_launcher.py',
        'ir_subagent_launcher_wb': 'ir_subagent_launcher_wb.py',
        'build_ir_evidence_table': 'build_ir_evidence_table.py',
        'build_ir_analysis_draft': 'build_ir_analysis_draft.py',
        'build_ir_final_memo': 'build_ir_final_memo.py',
        'build_ir_broker_report_docx': 'build_ir_broker_report_docx.py',
    }
    missing_scripts = []
    for name, fname in core_modules.items():
        if not (SCRIPTS_DIR / fname).exists():
            missing_scripts.append(fname)
    results['checks']['core_scripts'] = {
        'ok': len(missing_scripts) == 0,
        'msg': f'全部 {len(core_modules)} 个核心脚本就绪' if not missing_scripts else f'⚠️ 缺少: {", ".join(missing_scripts)}'
    }

    # 4. 子模块
    sub_modules = ['research', 'content', 'search', 'routing', 'sources', 'memory', 'memory_agent', 'instruction_store_bp', 'instruction_store_ir']
    missing_mods = [m for m in sub_modules if not (ROOT / m).exists()]
    results['checks']['sub_modules'] = {
        'ok': len(missing_mods) == 0,
        'msg': f'全部 {len(sub_modules)} 个子模块就绪' if not missing_mods else f'⚠️ 缺少: {", ".join(missing_mods)}'
    }

    # 5. Python 依赖 (pip_name → import_name mapping)
    _dep_map = {
        'chromadb': 'chromadb',
        'dashscope': 'dashscope',
        'openai': 'openai',
        'httpx': 'httpx',
        'beautifulsoup4': 'bs4',
    }
    opt_deps = {}
    for pip_name, import_name in _dep_map.items():
        try:
            __import__(import_name)
            opt_deps[pip_name] = True
        except ImportError:
            opt_deps[pip_name] = False
    missing_deps = [k for k, v in opt_deps.items() if not v]
    results['checks']['python_deps'] = {
        'ok': len(missing_deps) == 0,
        'available': {k: v for k, v in opt_deps.items() if v},
        'missing': missing_deps,
        'msg': '核心依赖已安装' if not missing_deps else f'⚠️ 缺少 pip 包: {", ".join(missing_deps)}'
    }

    # 6. 搜索服务 (分层检测)
    # 6a. Yahoo Finance Skill (免密钥，金融查询首选)
    yahoo_skill = Path.home() / '.workbuddy' / 'skills' / 'yahoo' / 'yahoo_search.py'
    yahoo_ok = yahoo_skill.exists()
    results['checks']['yahoo_skill'] = {
        'ok': yahoo_ok,
        'msg': f'Yahoo Skill 可用 (免密钥)' if yahoo_ok else '⚠️ Yahoo Skill 未安装，金融搜索将降级到 DDG'
    }

    # 6b. SearXNG (本地自建，自动启动)
    searxng_url = os.environ.get('SEARXNG_URL', 'http://localhost:8888')
    try:
        # 自动启动 SearXNG
        from searxng_manager import auto_start, healthcheck as searxng_hc
        auto_start()
        searxng_ok = searxng_hc()
    except Exception:
        # fallback: 直接探测端口
        try:
            import httpx
            r = httpx.get(f'{searxng_url}/healthz', timeout=2)
            searxng_ok = r.status_code == 200
        except Exception:
            searxng_ok = False
    results['checks']['searxng'] = {
        'ok': True,  # SearXNG 可选，不影响整体
        'available': searxng_ok,
        'url': searxng_url,
        'msg': f'SearXNG 可用 ({searxng_url})' if searxng_ok else f'⚠️ SearXNG 自动启动失败 (可选，降级到 DDG/Yahoo)'
    }

    # 6c. DDG (免密钥，兜底搜索)
    try:
        from ddgs import DDGS
        ddg_ok = True
    except ImportError:
        try:
            from duckduckgo_search import DDGS
            ddg_ok = True
        except ImportError:
            ddg_ok = False
    results['checks']['ddg'] = {
        'ok': ddg_ok,
        'msg': 'DDG 搜索可用 (免密钥)' if ddg_ok else '⚠️ DDG 搜索不可用，pip install ddgs'
    }

    # 搜索整体可用性
    search_available = yahoo_ok or ddg_ok or searxng_ok
    results['checks']['search_overall'] = {
        'ok': search_available,
        'msg': '搜索系统可用 (无需 API 密钥)' if search_available else '⚠️ 所有搜索服务均不可用'
    }

    # 7. 配置文件
    ir_config = ROOT / 'config' / 'ir-runtime.json'
    results['checks']['ir_config'] = {
        'ok': ir_config.exists(),
        'msg': 'ir-runtime.json 存在' if ir_config.exists() else '⚠️ 缺少 config/ir-runtime.json'
    }

    return results


def print_check_report(results):
    """打印环境检测报告"""
    print(f"\n{'═'*60}")
    print(f"  IR Pipeline 环境检测 (WorkBuddy)")
    print(f"  Python: {results['python']}")
    print(f"  Root: {results['root']}")
    print(f"{'═'*60}\n")

    # 关键检测项（必须通过）
    critical_keys = {'credentials', 'dashscope', 'core_scripts', 'sub_modules', 'python_deps', 'ir_config', 'search_overall'}
    all_ok = True
    for name, check in results['checks'].items():
        if name in critical_keys:
            status = '✅' if check['ok'] else '❌'
            if not check['ok']:
                all_ok = False
        else:
            # 可选项：可用标记✅，不可用标记⚠️
            status = '✅' if check['ok'] else '⚠️'
        print(f"  {status} {name}: {check['msg']}")

    print(f"\n{'─'*60}")
    if all_ok:
        print("  🎉 所有检测通过，IR Pipeline 可用！(无需 API 密钥搜索)")
    else:
        print("  ⚠️ 部分检测未通过，请按提示修复")
    print(f"{'─'*60}\n")
    return all_ok


# ═══════════════════════════════════════════════════════
# 2. 任务创建
# ═══════════════════════════════════════════════════════
def create_task(target: str, task_type: str = '专题研究类') -> dict:
    """创建 IR 任务"""
    _load_env()
    result = _py('run_ir_task.py', target, '--task-type', task_type)
    if result is None:
        return {'ok': False, 'msg': 'run_ir_task.py 脚本不存在'}
    if result.returncode != 0:
        return {'ok': False, 'msg': result.stderr[:500]}
    # 尝试解析输出获取 task_id
    output = result.stdout.strip()
    task_id = None
    for line in output.split('\n'):
        if 'TASK-' in line:
            import re
            m = re.search(r'(TASK-\d{8}-\d+)', line)
            if m:
                task_id = m.group(1)
                break
    return {
        'ok': True,
        'task_id': task_id,
        'output': output,
        'msg': f'任务创建成功: {task_id}' if task_id else '任务创建完成（未能解析 task_id）'
    }


# ═══════════════════════════════════════════════════════
# 3. 管线执行
# ═══════════════════════════════════════════════════════
def run_pipeline(task_id: str, phase: str = None) -> dict:
    """执行 IR 管线"""
    _load_env()
    args = ['--task-id', task_id]
    if phase:
        args.extend(['--phase', phase])
    result = _py('run_ir_pipeline.py', *args)
    if result is None:
        return {'ok': False, 'msg': 'run_ir_pipeline.py 脚本不存在'}
    return {
        'ok': result.returncode == 0,
        'stdout': result.stdout,
        'stderr': result.stderr,
        'msg': '管线执行完成' if result.returncode == 0 else f'管线执行失败: {result.stderr[:200]}'
    }


# ═══════════════════════════════════════════════════════
# 4. 任务状态
# ═══════════════════════════════════════════════════════
def get_status(task_id: str) -> dict:
    """获取任务状态"""
    task_file = TASKS_DIR / f'{task_id}.json'
    if not task_file.exists():
        return {'ok': False, 'msg': f'任务不存在: {task_id}'}
    try:
        data = json.loads(task_file.read_text(encoding='utf-8'))
        return {'ok': True, 'data': data}
    except Exception as e:
        return {'ok': False, 'msg': str(e)}


def list_tasks() -> list:
    """列出所有任务"""
    tasks = []
    if not TASKS_DIR.exists():
        return tasks
    for f in sorted(TASKS_DIR.glob('TASK-*.json')):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            tasks.append({
                'id': f.stem,
                'target': data.get('target', data.get('company', '?')),
                'type': data.get('type', '?'),
                'status': data.get('status', '?'),
                'created': data.get('created', '?'),
            })
        except Exception:
            tasks.append({'id': f.stem, 'status': 'read_error'})
    return tasks


# ═══════════════════════════════════════════════════════
# 5. 龙少微信通知
# ═══════════════════════════════════════════════════════
LONGSHAO = SCRIPTS_DIR / 'longshao_notify.py'

def notify_wechat(text: str) -> dict:
    """通过龙少发送微信通知"""
    result = _py('longshao_notify.py', text)
    if result is None:
        return {'ok': False, 'msg': 'longshao_notify.py 脚本不存在'}
    try:
        data = json.loads(result.stdout)
        return data
    except Exception:
        return {'ok': result.returncode == 0, 'stdout': result.stdout, 'stderr': result.stderr}


# ═══════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description='IR Pipeline WorkBuddy Adapter')
    sub = ap.add_subparsers(dest='cmd')

    # check
    sub.add_parser('check', help='环境检测')

    # create
    p_create = sub.add_parser('create', help='创建投研任务')
    p_create.add_argument('target', help='研究标的 (公司名/股票名)')
    p_create.add_argument('--type', default='专题研究类',
                          choices=['专题研究类', '晨报类', '快报类', '资料整理类', '回顾类'],
                          help='任务类型')

    # run
    p_run = sub.add_parser('run', help='执行管线')
    p_run.add_argument('task_id', help='任务ID (TASK-XXXXXXXX-XXX)')
    p_run.add_argument('--phase', help='指定起始 Phase (0/1/2/3/4/5)')

    # status
    p_status = sub.add_parser('status', help='查看任务状态')
    p_status.add_argument('task_id', help='任务ID')

    # list
    sub.add_parser('list', help='列出所有任务')

    # notify
    p_notify = sub.add_parser('notify', help='🐲 龙少微信通知')
    p_notify.add_argument('text', help='通知内容')

    args = ap.parse_args()

    if args.cmd == 'check':
        results = check_environment()
        ok = print_check_report(results)
        sys.exit(0 if ok else 1)

    elif args.cmd == 'create':
        result = create_task(args.target, args.type)
        print(result['msg'])
        if result.get('task_id'):
            print(f"Task ID: {result['task_id']}")
        if not result['ok']:
            sys.exit(1)

    elif args.cmd == 'run':
        result = run_pipeline(args.task_id, args.phase)
        print(result['msg'])
        if result.get('stdout'):
            print(result['stdout'][-2000:])
        if not result['ok']:
            sys.exit(1)

    elif args.cmd == 'status':
        result = get_status(args.task_id)
        if result['ok']:
            print(json.dumps(result['data'], ensure_ascii=False, indent=2))
        else:
            print(result['msg'])
            sys.exit(1)

    elif args.cmd == 'list':
        tasks = list_tasks()
        if not tasks:
            print("暂无任务")
        for t in tasks:
            print(f"  {t['id']}  {t.get('target', '?'):15s}  {t.get('type', '?'):8s}  {t.get('status', '?')}")

    elif args.cmd == 'notify':
        result = notify_wechat(args.text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get('ok'):
            sys.exit(1)

    else:
        ap.print_help()


if __name__ == '__main__':
    main()
