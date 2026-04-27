#!/usr/bin/env python3
"""
Notification Plugin — 通知推送插件模板

实现此文件的 send_message() 和 notify_report() 函数，
即可在 BP 管线交付时自动推送通知。

示例实现：
- 微信 iLink Bot (wechat-ilink-bot SDK)
- Slack Webhook
- 飞书 Bot
- Telegram Bot
- 邮件 SMTP

使用方式：
1. 复制此文件为 notify_plugin.py（去掉 .example 后缀）
2. 填写你的推送配置
3. 管线交付时会自动调用

如果你的平台不需要通知推送，保留此文件为空即可（ImportError 会被捕获）。
"""
from __future__ import annotations

from typing import Any


def send_message(text: str) -> dict[str, Any]:
    """发送纯文本通知。

    Args:
        text: 通知文本

    Returns:
        {"ok": True/False, "msg": "描述"}
    """
    # ── 示例：微信 iLink Bot ──
    # try:
    #     from wechat_ilink_bot import WeChatBot
    #     bot = WeChatBot(bot_key="YOUR_BOT_KEY")
    #     bot.send_text(text)
    #     return {"ok": True, "msg": "sent"}
    # except Exception as e:
    #     return {"ok": False, "msg": str(e)}

    # ── 示例：Slack Webhook ──
    # import requests
    # try:
    #     resp = requests.post("https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
    #                          json={"text": text}, timeout=10)
    #     return {"ok": resp.status_code == 200, "msg": str(resp.status_code)}
    # except Exception as e:
    #     return {"ok": False, "msg": str(e)}

    return {"ok": False, "msg": "notify_plugin not configured"}


def notify_report(
    task_id: str,
    docx_path: str,
    dimension_count: int = 0,
    total: int = 0,
) -> dict[str, Any]:
    """发送报告完成通知（含文件附件）。

    Args:
        task_id: 任务 ID
        docx_path: DOCX 报告路径
        dimension_count: 已完成维度数
        total: 总维度数

    Returns:
        {"ok": True/False, "msg": "描述"}
    """
    text = (
        f"📊 BP尽调报告完成：{task_id}\n\n"
        f"✅ {dimension_count}/{total} 维度分析已完成\n"
        f"📄 报告路径：{docx_path}\n"
    )

    result = send_message(text)
    if not result.get("ok"):
        return result

    # 如果支持文件发送，在此处实现
    # try:
    #     from wechat_ilink_bot import WeChatBot
    #     bot = WeChatBot(bot_key="YOUR_BOT_KEY")
    #     bot.send_file(docx_path, text)
    #     return {"ok": True, "msg": "file sent"}
    # except Exception as e:
    #     return {"ok": False, "msg": str(e)}

    return result
