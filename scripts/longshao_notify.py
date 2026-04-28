#!/usr/bin/env python3
"""
🐲 龙少微信推送 — 基于 wechat-ilink-bot SDK

通过微信 iLink 协议直接发送消息和文件到用户微信（龙少机器人）

流程：
1. 初始化 Bot（首次需要用户给龙少发过一条消息）
2. 发送文本消息或文件

用法：
  python3 longshao_notify.py "研报已完成：东江环保"
  python3 longshao_notify.py --file /path/to/report.docx "研报完成请查收"
  python3 longshao_notify.py --init          # 初始化：获取 context_token
  python3 longshao_notify.py --status        # 查看当前状态
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

# ─── 配置 ──────────────────────────────────────────
BOT_TOKEN = "d7d8aa0509dc@im.bot:06000099413e56ea535764208470a68f6be80c"
ACCOUNT_ID = "d7d8aa0509dc@im.bot"
USER_ID = "o9cq80xv1-tm50fGmGHn9e1LoqHo@im.wechat"

# context_token 持久化路径
IR_ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = IR_ROOT / ".credentials" / "ilink_context_token.json"

# SSL
os.environ.setdefault('SSL_CERT_FILE', '/opt/homebrew/etc/openssl@3/cert.pem')
os.environ.setdefault('REQUESTS_CA_BUNDLE', '/opt/homebrew/etc/openssl@3/cert.pem')


def _load_token() -> str:
    """加载持久化的 context_token"""
    if TOKEN_FILE.exists():
        try:
            data = json.loads(TOKEN_FILE.read_text(encoding='utf-8'))
            return data.get('context_token', '')
        except Exception:
            pass
    return ''


def _save_token(token: str):
    """持久化 context_token"""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({
        'context_token': token,
        'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'account_id': ACCOUNT_ID,
        'user_id': USER_ID,
    }, ensure_ascii=False, indent=2), encoding='utf-8')


async def _get_bot() -> "Bot":
    """初始化并返回 Bot 实例"""
    from wechat_bot import Bot
    bot = Bot(token=BOT_TOKEN)
    # 从磁盘恢复 context_token（send_file 必须有有效的 context_token）
    try:
        restored = bot._storage.restore_context_tokens(ACCOUNT_ID)
        if restored:
            print(f"  📌 Restored {restored} context token(s) from disk")
    except Exception as e:
        print(f"  ⚠ restore_context_tokens failed: {e}")
    # 如果本地有保存的 context_token，也尝试手动注入
    ct = _load_token()
    if ct:
        try:
            bot._storage.set_context_token(ACCOUNT_ID, USER_ID, ct)
        except Exception:
            pass
    return bot


async def send_message(text: str = "", file_path: str | None = None) -> dict:
    """
    通过龙少发送微信消息和/或文件

    Args:
        text: 消息文本
        file_path: 可选，文件路径（传此参数则发送文件）

    Returns:
        发送结果 dict

    策略：
    - 发文件时：先发文本通知 → 再发文件 → 最后发确认文本
    - 这样即使 send_file 静默失败，用户至少能看到通知和确认
    - 文件发送失败不会阻断流程，会标注 in result
    """
    import logging
    log_path = IR_ROOT / ".logs" / "wechat_notify.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_path), level=logging.DEBUG,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    log = logging.getLogger("longshao_notify")

    bot = None
    try:
        bot = await _get_bot()
        result = {"ok": True, "msg": ""}

        # 发送文件
        if file_path:
            if not Path(file_path).exists():
                log.error(f"文件不存在: {file_path}")
                return {"ok": False, "msg": f"文件不存在: {file_path}"}

            file_size = Path(file_path).stat().st_size
            file_name = Path(file_path).name
            log.info(f"准备发送文件: {file_name} ({file_size} bytes)")

            # Step 0: 检查 context_token 有效性
            try:
                ct = bot._storage.get_context_token(ACCOUNT_ID, USER_ID)
                if not ct:
                    log.error("context_token 为空，需要重新初始化")
                    return {"ok": False, "msg": "context_token 为空，请运行 python3 longshao_notify.py --init 重新初始化"}
            except Exception as e:
                log.warning(f"无法检查 context_token: {e}")

            # Step 1: 先发文本通知（确保通道可用）
            try:
                notice_text = text or f"📎 文件发送中: {file_name}"
                await bot.send_text(to=USER_ID, text=notice_text)
                log.info("文本通知已发送")
            except Exception as e:
                log.warning(f"文本通知发送失败: {e}")
                # 文本通知失败 → 通道可能有问题，但继续尝试发文件

            # Step 2: 发送文件
            try:
                await bot.send_file(to=USER_ID, file_path=file_path, caption="")
                log.info(f"send_file 调用完成: {file_name}")
                result["msg"] = f"文件发送成功: {file_name}"
                result["file"] = file_name
            except Exception as e:
                log.error(f"send_file 异常: {type(e).__name__}: {e}")
                result["ok"] = False
                result["msg"] = f"文件发送失败: {str(e)}"
                result["file"] = file_name

            # Step 3: 发确认文本（让用户知道文件是否成功）
            try:
                if result["ok"]:
                    confirm = f"✅ 文件已发送: {file_name}（{file_size//1024}KB）"
                else:
                    confirm = f"⚠️ 文件发送可能失败: {file_name}，请检查是否收到"
                await bot.send_text(to=USER_ID, text=confirm)
                log.info("确认文本已发送")
            except Exception as e:
                log.warning(f"确认文本发送失败: {e}")

        # 只发文本（没有文件）
        elif text:
            await bot.send_text(to=USER_ID, text=text)
            result["msg"] = "消息发送成功 ✅"
            result["text"] = text
            log.info(f"文本消息已发送: {text[:50]}...")

        else:
            return {"ok": False, "msg": "必须提供 text 或 file_path"}

        # 保存可能更新的 context_token
        try:
            latest_ct = bot._storage.get_context_token(ACCOUNT_ID, USER_ID)
            if latest_ct:
                _save_token(latest_ct)
                log.debug("context_token 已保存")
        except Exception as e:
            log.warning(f"保存 context_token 失败: {e}")

        return result

    except Exception as e:
        log.error(f"send_message 总异常: {type(e).__name__}: {e}")
        return {"ok": False, "msg": f"发送失败: {str(e)}"}
    finally:
        if bot:
            try:
                await bot.stop()
            except Exception:
                pass


def notify_ir_report(task_id: str, docx_path: str, message: str = "研报已生成") -> dict:
    """发送 IR 研报完成通知 + 文件"""
    text = f"""🐲 龙少 — 研报交付通知

📋 任务: {task_id}
💬 {message}
📄 文件: {Path(docx_path).name}

📁 Word 报告已生成，请查收。"""
    return asyncio.run(send_message(text=text, file_path=docx_path))


def notify_bp_report(task_id: str, docx_path: str, dimension_count: int = 0, total: int = 0) -> dict:
    """发送 BP 尽调报告完成通知 + 文件"""
    text = f"""📋 BP 尽调报告完成
标的: {task_id}
维度: {dimension_count}/{total} 完成
报告: {Path(docx_path).name}

请查收完整尽调报告。"""
    return asyncio.run(send_message(text=text, file_path=docx_path))


# ══════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════
def main():
    import argparse
    ap = argparse.ArgumentParser(description='🐲 龙少微信推送')
    ap.add_argument('text', nargs='?', help='消息内容（直接发送文本）')
    ap.add_argument('--file', help='发送文件（与 text 配合使用，text 作为文件说明）')
    ap.add_argument('--init', action='store_true', help='初始化 context_token（需要给龙少发一条微信消息）')
    ap.add_argument('--status', action='store_true', help='查看当前状态')
    ap.add_argument('--poll', action='store_true', help='轮询一次新消息')

    args = ap.parse_args()

    if args.init:
        print("🐲 龙少初始化：需要你给龙少发一条微信消息来刷新 context_token")
        print("   （请在微信上给龙少发任意消息，如「你好」）")
        try:
            from wechat_bot import Bot

            async def _init():
                bot = Bot(token=BOT_TOKEN)
                bot._storage.restore_context_tokens(ACCOUNT_ID)

                # 启动 poller 来接收用户消息（消息到达时 SDK 会自动更新 context_token）
                await bot.start()
                print("   ⏳ 已启动轮询，等待你发消息...（最多等 60 秒）")

                # 等待 context_token 变化
                old_ct = _load_token()
                for i in range(30):  # 30 次 × 2 秒 = 60 秒超时
                    await asyncio.sleep(2)
                    try:
                        new_ct = bot._storage.get_context_token(ACCOUNT_ID, USER_ID)
                        if new_ct and new_ct != old_ct:
                            _save_token(new_ct)
                            print(f"   ✅ context_token 已刷新！")
                            await bot.stop()
                            return
                    except Exception:
                        pass
                    if i % 5 == 4:
                        print(f"   ⏳ 还在等待...（{i*2+2}秒）")

                # 超时，但检查是否已有 token（哪怕没变化）
                try:
                    ct = bot._storage.get_context_token(ACCOUNT_ID, USER_ID)
                    if ct:
                        _save_token(ct)
                        print(f"   ⚠️ 未检测到新消息，但已保存现有 token")
                    else:
                        print(f"   ❌ 未获取到 context_token，请确认已给龙少发消息")
                except Exception as e:
                    print(f"   ❌ 获取 token 失败: {e}")

                await bot.stop()

            asyncio.run(_init())
        except Exception as e:
            print(f"   初始化失败: {e}")

    elif args.status:
        token = _load_token()
        status = f"已保存 ({TOKEN_FILE.name})" if token else "未初始化"
        print(f"Context token: {status}")
        print(f"Token 文件: {TOKEN_FILE}")
        print(f"Account: {ACCOUNT_ID}")
        print(f"User: {USER_ID}")

    elif args.poll:
        print("轮询功能请直接使用 Bot API")

    elif args.file:
        result = asyncio.run(send_message(text=args.text or "", file_path=args.file))
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.text:
        result = asyncio.run(send_message(text=args.text))
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        ap.print_help()


if __name__ == '__main__':
    main()
