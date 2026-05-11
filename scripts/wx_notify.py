#!/usr/bin/env python3
"""
微信推送通知 — 通过 WorkBuddy 龙少机器人发送消息到微信

原理：
  WorkBuddy IDE 通过 weixinClawBot (websocket) 连接到微信机器人"龙少"
  本脚本将消息写入 WorkBuddy 的 message-queue，IDE 自动推送到微信

注意：
  当前 bot/message-queue 实现只会发送 text block。
  `--file` 目前仅把文件路径追加进文本消息，不会上传真实附件。
  如需真正文件交付，必须接入独立的媒体/文档投递机制，而不是依赖当前脚本。

用法：
  python3 wx_notify.py "研报已完成：东江环保"
  python3 wx_notify.py --file /path/to/report.docx "研报附件（仅发送路径，不是真附件）"
  python3 wx_notify.py --markdown "**研报完成**\n- 东江环保\n- 专题研究"
"""
from __future__ import annotations
import json
import time
import uuid
import argparse
from pathlib import Path

# WorkBuddy 消息队列路径
WB_GLOBAL = Path.home() / "Library" / "Application Support" / "WorkBuddy" / "User" / "globalStorage" / "tencent-cloud.coding-copilot"
MSG_QUEUE_DIR = WB_GLOBAL / "message-queue"

# 龙少频道配置（从 settings.json 读取）
SETTINGS_FILE = Path.home() / "Library" / "Application Support" / "WorkBuddy" / "User" / "settings.json"


def _get_wechat_channel_id() -> str | None:
    """从 WorkBuddy settings 读取龙少的 channelId"""
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        channels = settings.get('claw.channels', {})
        bot = channels.get('weixinClawBot', {})
        return bot.get('channelId')
    except Exception:
        return None


def _find_or_create_queue_file(conversation_id: str | None = None) -> Path:
    """找到或创建消息队列文件"""
    MSG_QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    if conversation_id:
        # 查找包含该 conversation_id 的文件
        for f in MSG_QUEUE_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding='utf-8'))
                if conversation_id in data.get('conversations', {}):
                    return f
            except Exception:
                continue

    # 创建新文件
    queue_id = uuid.uuid4().hex[:16]
    return MSG_QUEUE_DIR / f"{queue_id}.json"


def send_wechat_message(
    text: str,
    file_path: str | None = None,
    conversation_id: str | None = None,
    mode: str = "craft",
    model: str = "glm-5.1",
) -> dict:
    """
    通过龙少发送微信消息

    Args:
        text: 消息文本
        file_path: 附件文件路径（可选；当前仅追加到文本，不会真实上传）
        conversation_id: WorkBuddy 会话 ID（可选，不指定则创建新队列文件）
        mode: 工作模式
        model: 模型 ID

    Returns:
        发送结果 dict
    """
    now_ms = int(time.time() * 1000)
    msg_id = f"mq-{now_ms}-{uuid.uuid4().hex[:6]}"

    # 构建消息内容
    content = text
    if file_path:
        content += f"\n\n📎 文件路径: {file_path}"

    queue_file = _find_or_create_queue_file(conversation_id)

    # 读取现有数据或创建新的
    if queue_file.exists():
        try:
            data = json.loads(queue_file.read_text(encoding='utf-8'))
        except Exception:
            data = {"version": 2, "lastUpdated": now_ms, "conversations": {}}
    else:
        data = {"version": 2, "lastUpdated": now_ms, "conversations": {}}

    # 如果没有 conversation_id，生成一个
    if not conversation_id:
        conversation_id = uuid.uuid4().hex

    # 确保该 conversation 存在
    if conversation_id not in data['conversations']:
        data['conversations'][conversation_id] = {
            "version": 2,
            "conversationId": conversation_id,
            "updatedAt": now_ms,
            "runtime": {
                "activated": True,
                "paused": False,
                "awaitingSessionIdle": False,
                "updatedAt": now_ms
            },
            "items": []
        }

    conv = data['conversations'][conversation_id]

    # 添加消息
    item = {
        "id": msg_id,
        "conversationId": conversation_id,
        "contentBlocks": [
            {
                "type": "text",
                "text": content,
                "_meta": {
                    "codebuddy.ai": {
                        "mode": mode,
                        "model": model
                    }
                }
            }
        ],
        "previewText": content[:100],
        "status": "pending",
        "order": len(conv.get('items', [])),
        "createdAt": now_ms,
        "updatedAt": now_ms,
        "modeId": mode,
        "modelId": model
    }

    conv['items'].append(item)
    conv['updatedAt'] = now_ms
    data['lastUpdated'] = now_ms

    # 写入文件
    queue_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    return {
        "ok": True,
        "msg_id": msg_id,
        "queue_file": str(queue_file),
        "conversation_id": conversation_id,
        "channel": "weixinClawBot (龙少)",
        "delivery_kind": "text_only",
        "file_uploaded": False
    }


# ═══════════════════════════════════════════════════════
# 备选方案：直接通过 ilinkai websocket 发消息
# （如果 message-queue 方式不工作，可用此方案）
# ═══════════════════════════════════════════════════════
def send_via_serverchan(text: str, sendkey: str | None = None) -> dict:
    """
    备选：通过 Server酱 发送微信通知
    需要 SENDKEY 配置在环境变量 SERVERCHAN_SENDKEY 或传入
    """
    import os
    key = sendkey or os.environ.get('SERVERCHAN_SENDKEY', '')
    if not key:
        return {"ok": False, "msg": "缺少 Server酱 SENDKEY"}

    import requests
    url = f"https://sctapi.ftqq.com/{key}.send"
    r = requests.post(url, data={"title": "🐲 龙少通知", "desp": text}, timeout=10)
    return {"ok": r.status_code == 200, "response": r.json() if r.status_code == 200 else r.text}


def send_via_pushplus(text: str, token: str | None = None) -> dict:
    """
    备选：通过 PushPlus 发送微信通知
    需要 TOKEN 配置在环境变量 PUSHPLUS_TOKEN 或传入
    """
    import os
    key = token or os.environ.get('PUSHPLUS_TOKEN', '')
    if not key:
        return {"ok": False, "msg": "缺少 PushPlus TOKEN"}

    import requests
    url = "https://www.pushplus.plus/send"
    r = requests.post(url, json={"token": key, "title": "🐲 龙少通知", "content": text, "template": "markdown"}, timeout=10)
    return {"ok": r.status_code == 200, "response": r.json() if r.status_code == 200 else r.text}


def send_via_wecom_webhook(text: str, webhook_key: str | None = None) -> dict:
    """
    备选：通过企业微信 Webhook 机器人发送
    需要 WEBHOOK_KEY 配置在环境变量 WECOM_WEBHOOK_KEY 或传入
    """
    import os
    key = webhook_key or os.environ.get('WECOM_WEBHOOK_KEY', '')
    if not key:
        return {"ok": False, "msg": "缺少企业微信 Webhook Key"}

    import requests
    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
    r = requests.post(url, json={"msgtype": "markdown", "markdown": {"content": text}}, timeout=10)
    return {"ok": r.status_code == 200, "response": r.json() if r.status_code == 200 else r.text}


# ═══════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description='🐲 龙少微信推送通知')
    ap.add_argument('text', help='消息内容')
    ap.add_argument('--file', '-f', help='文件路径（当前仅写入文本提示，不是真附件上传）')
    ap.add_argument('--conversation-id', '-c', help='WorkBuddy 会话 ID')
    ap.add_argument('--method', choices=['bot', 'serverchan', 'pushplus', 'wecom'],
                    default='bot', help='推送方式 (默认: bot=龙少)')
    ap.add_argument('--markdown', '-m', action='store_true', help='内容为 Markdown 格式')

    args = ap.parse_args()

    if args.method == 'bot':
        result = send_wechat_message(args.text, args.file, args.conversation_id)
    elif args.method == 'serverchan':
        result = send_via_serverchan(args.text)
    elif args.method == 'pushplus':
        result = send_via_pushplus(args.text)
    elif args.method == 'wecom':
        result = send_via_wecom_webhook(args.text)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get('ok'):
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
