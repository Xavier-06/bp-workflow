#!/usr/bin/env python3
"""
Delivery Guard — 确保所有生成的研报/报告都自动发送到飞书

根因分析 (2026-04-04):
  Xavier 问"东江集团研报"，我生成了 DOCX 但没有发送，等用户来催。
  之前承诺了"不会再犯"但只是口头说，没有代码级的强制机制。
  根因：产出物生成和交付发送之间没有系统级连接，全靠"记住"。
  修复：产出物生成后立即检查并自动发送。

工作流程:
  1. 在管线 Phase 5 最后自动调用此脚本
  2. 每次 session 结束前调用此脚本扫描未发送产出物
  3. 扫描 output/*.docx 和 reports/*.docx，与已发送清单对比

用法:
    # 检查并发送指定文件的产出物
    python3 scripts/delivery_guard.py send "东江集团控股" /path/to/report.docx
    
    # 扫描所有未发送产出物
    python3 scripts/delivery_guard.py scan
"""
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
DELIVERY_LOG = ROOT / "data" / "delivery_log.json"

# Feishu target (Xavier)
FEISHU_TARGET = "ou_fc4728374aeed4fb302026963720c08c"


def load_delivery_log() -> dict:
    """Load delivery log"""
    if DELIVERY_LOG.exists():
        try:
            return json.loads(DELIVERY_LOG.read_text(encoding="utf-8"))
        except Exception:
            return {"sent": []}
    return {"sent": []}


def save_delivery_log(log: dict) -> None:
    """Save delivery log"""
    DELIVERY_LOG.parent.mkdir(parents=True, exist_ok=True)
    DELIVERY_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_sent(file_path: str) -> bool:
    """Check if file was already sent"""
    log = load_delivery_log()
    abs_path = str(Path(file_path).resolve())
    for entry in log.get("sent", []):
        if entry.get("file_path") == abs_path:
            return True
    return False


def mark_sent(file_path: str, entity: str, task_id: str = "") -> None:
    """Mark file as sent"""
    log = load_delivery_log()
    abs_path = str(Path(file_path).resolve())
    log.setdefault("sent", []).append({
        "file_path": abs_path,
        "entity": entity,
        "task_id": task_id,
        "sent_at": datetime.now().isoformat(),
    })
    save_delivery_log(log)


def send_file(file_path: str, entity: str, task_id: str = "", message: str = "") -> bool:
    """Send file via Feishu and log it"""
    if is_sent(file_path):
        print(f"⚠️ Already sent: {file_path}")
        return True

    if not message:
        message = f"📊 {entity} 深度研报 — 请查阅。"

    # 2026-04-13: WorkBuddy 版 — 用龙少微信替代 openclaw message send
    print(f"📤 Sending: {file_path}")
    try:
        from longshao_notify import send_message as _send_wx
        _wx_msg = f"{message}\n\n📄 文件: {file_path}"
        _r = _send_wx(_wx_msg)
        if _r.get('ok'):
            print(f"✅ Sent via 龙少微信")
            mark_sent(file_path, entity, task_id)
            return True
        else:
            print(f"❌ Send failed: {_r.get('msg', '')[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"❌ Send timed out (60s)")
        return False
    except FileNotFoundError:
        print(f"❌ File not found: {file_path}")
        return False


def scan_for_unsent() -> list[dict]:
    """Scan output/ and reports/ for DOCX files that haven't been sent"""
    unsent = []
    for search_dir in [ROOT / "output", ROOT / "reports"]:
        if not search_dir.exists():
            continue
        for docx in sorted(search_dir.glob("*.docx")):
            if not is_sent(str(docx)):
                unsent.append({
                    "file": str(docx),
                    "size_kb": round(docx.stat().st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(docx.stat().st_mtime).isoformat(),
                })
    return unsent


def cmd_send():
    """Send a specific file"""
    if len(sys.argv) < 4:
        print("Usage: delivery_guard.py send 'Entity Name' /path/to/report.docx [optional_message]")
        sys.exit(1)

    entity = sys.argv[2]
    file_path = sys.argv[3]
    message = sys.argv[4] if len(sys.argv) > 4 else ""

    # Find entity from filename if not provided
    if not file_path or not Path(file_path).exists():
        # Try to find it in output/
        output_files = list((ROOT / "output").glob("*.docx"))
        matching = [f for f in output_files if entity.lower() in f.name.lower() or entity in f.name]
        if matching:
            file_path = str(matching[-1])
            print(f"  Found: {file_path}")
        else:
            print(f"❌ File not found: {file_path}")
            sys.exit(1)

    success = send_file(file_path, entity, message=message)
    sys.exit(0 if success else 1)


def cmd_scan():
    """Scan for unsent files"""
    unsent = scan_for_unsent()

    if not unsent:
        print("✅ All deliverables have been sent")
        return

    print(f"📋 Found {len(unsent)} unsent deliverable(s):")
    for item in unsent:
        print(f"  📄 {item['file']}")
        print(f"     Size: {item['size_kb']} KB | Modified: {item['modified']}")

    # Auto-send all unsent files
    print(f"\n📤 Auto-sending {len(unsent)} file(s)...")
    for item in unsent:
        file_path = item["file"]
        entity = Path(file_path).stem.split("-")[0]
        send_file(file_path, entity)


def cmd_auto_send_latest():
    """Auto-send the most recent DOCX in output/"""
    output_dir = ROOT / "output"
    if not output_dir.exists():
        print("No output directory")
        return

    docx_files = sorted(output_dir.glob("*.docx"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not docx_files:
        print("No DOCX files in output/")
        return

    latest = docx_files[0]
    if is_sent(str(latest)):
        print(f"✅ Latest file already sent: {latest.name}")
        return

    # Extract entity name from filename
    entity = latest.stem
    # Remove common prefixes/patterns
    for prefix in ["TASK-", "东江集团控股", "东江集团", "泡泡玛特", "优必选", "英伟达", "特斯拉"]:
        if entity.startswith(prefix):
            entity = entity.replace(prefix, "").strip("-_")

    print(f"📤 Auto-sending latest: {latest.name}")
    success = send_file(str(latest), entity)

    if success:
        print(f"✅ File sent to Xavier via Feishu")
    else:
        print(f"❌ Failed to send file")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  delivery_guard.py scan          # Scan for unsent deliverables")
        print("  delivery_guard.py send 'Entity' /path/file.docx  # Send specific file")
        print("  delivery_guard.py auto          # Auto-send latest output DOCX")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "send":
        cmd_send()
    elif cmd == "scan":
        cmd_scan()
    elif cmd == "auto":
        cmd_auto_send_latest()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
