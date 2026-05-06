#!/usr/bin/env python3
"""BP 管线启动脚本

用法：
    python3 run_bp.py --input /path/to/bp.pptx
    python3 run_bp.py --input /path/to/bp.pdf --entity "某某科技"
    python3 run_bp.py --input /path/to/bp.pptx --job-id my-custom-id

必须在 ir_runtime 目录下运行，或者用绝对路径调用本脚本。
"""
import sys
import os
from pathlib import Path

# 确保 ir_runtime 在 sys.path 中
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

os.chdir(str(SCRIPT_DIR))

import argparse
import json
import time


def main():
    ap = argparse.ArgumentParser(description="BP 管线启动入口")
    ap.add_argument("--input", required=True, help="BP 文件路径（PDF/PPTX/DOCX/图片）")
    ap.add_argument("--entity", default="", help="公司名称（可选，OCR 后会自动提取）")
    ap.add_argument("--job-id", default="", help="任务 ID（可选，默认自动生成）")
    ap.add_argument("--session-id", default="", help="会话 ID（交付通知用）")
    ap.add_argument("--market", default="cn", choices=["cn", "us", "hk"])
    ap.add_argument("--dry-run", action="store_true", help="只检查依赖，不实际运行")
    args = ap.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"❌ 文件不存在: {input_path}")
        sys.exit(1)

    if args.dry_run:
        print("=== 依赖检查 ===")
        _check_deps()
        print(f"\n✅ 输入文件: {input_path} ({input_path.stat().st_size / 1024 / 1024:.1f} MB)")
        print("✅ dry-run 完成，管线可以启动。")
        return

    job_id = args.job_id or f"bp-{time.strftime('%Y%m%d-%H%M%S')}"

    print(f"🚀 启动 BP 管线", flush=True)
    print(f"   Job ID:  {job_id}", flush=True)
    print(f"   输入:    {input_path}", flush=True)
    print(f"   实体:    {args.entity or '(OCR 后自动提取)'}", flush=True)
    print(f"   市场:    {args.market}", flush=True)
    print(flush=True)

    from runtime.entrypoints.run_bp_pipeline_entry import run_bp_job

    result = run_bp_job(
        job_id=job_id,
        entity=args.entity,
        query=f"{args.entity} BP 尽调" if args.entity else "BP 尽调",
        market=args.market,
        input_file=str(input_path),
        session_id=args.session_id,
    )

    print("\n" + "=" * 60)
    if result.get("ok"):
        print("✅ 管线运行完成")
    else:
        failed = result.get("failed_phase", "unknown")
        print(f"❌ 管线在 {failed} 阶段失败")

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def _check_deps():
    checks = []

    # python-pptx
    try:
        import pptx
        checks.append(("python-pptx", "✅"))
    except ImportError:
        checks.append(("python-pptx", "❌ pip install python-pptx"))

    # python-docx
    try:
        import docx
        checks.append(("python-docx", "✅"))
    except ImportError:
        checks.append(("python-docx", "❌ pip install python-docx"))

    # requests
    try:
        import requests
        checks.append(("requests", "✅"))
    except ImportError:
        checks.append(("requests", "❌ pip install requests"))

    # LibreOffice
    import shutil
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        mac_path = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        if mac_path.exists():
            soffice = str(mac_path)
    checks.append(("LibreOffice", f"✅ {soffice}" if soffice else "⚠️ 未安装（PPTX 会降级到纯文字提取）"))

    # pdftoppm
    pdftoppm = shutil.which("pdftoppm")
    checks.append(("pdftoppm", f"✅ {pdftoppm}" if pdftoppm else "⚠️ 未安装（PDF→PNG 会降级）"))

    # VL API
    vl_key = os.environ.get("VL_API_KEY", "")
    checks.append(("VL_API_KEY", "✅ 已配置" if vl_key else "❌ 未配置"))

    # search gateway
    try:
        from scripts.search_gateway import verify_engines
        engines = verify_engines()
        searxng_ok = engines.get("searxng", False)
        ddg_ok = engines.get("ddg", False)
        checks.append(("SearXNG", f"✅" if searxng_ok else "⚠️ 未运行"))
        checks.append(("DDG", f"✅" if ddg_ok else "⚠️ ddgs 未安装"))
    except Exception as e:
        checks.append(("search_gateway", f"❌ {e}"))

    for name, status in checks:
        print(f"  {name}: {status}")


if __name__ == "__main__":
    main()
