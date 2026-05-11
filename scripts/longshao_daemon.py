#!/usr/bin/env python3
"""
🐲 龙少微信常驻服务 — 保持 iLink Poller 在线

功能：
- 启动 Bot Poller 长轮询
- 收到用户消息时自动刷新 context_token 并持久化
- context_token 过期时通过日志告警
- 作为 launchd 守护进程运行，崩溃自动重启

用法：
  python3 longshao_daemon.py          # 前台运行
  python3 longshao_daemon.py --once   # 只刷新一次 token 就退出
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path

# 配置
BOT_TOKEN = "d7d8aa0509dc@im.bot:06000099413e56ea535764208470a68f6be80c"
ACCOUNT_ID = "d7d8aa0509dc@im.bot"
USER_ID = "o9cq80xv1-tm50fGmGHn9e1LoqHo@im.wechat"

IR_ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = IR_ROOT / ".credentials" / "ilink_context_token.json"
LOG_DIR = IR_ROOT / ".logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

os.environ.setdefault('SSL_CERT_FILE', '/opt/homebrew/etc/openssl@3/cert.pem')
os.environ.setdefault('REQUESTS_CA_BUNDLE', '/opt/homebrew/etc/openssl@3/cert.pem')


def save_token(token: str):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({
        'context_token': token,
        'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'account_id': ACCOUNT_ID,
        'user_id': USER_ID,
    }, ensure_ascii=False, indent=2), encoding='utf-8')


async def run_daemon(once: bool = False):
    """启动 bot poller 守护"""
    from wechat_bot import Bot
    import logging

    # 简洁日志
    logging.basicConfig(
        filename=str(LOG_DIR / "longshao_daemon.log"),
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    log = logging.getLogger("longshao_daemon")

    bot = Bot(token=BOT_TOKEN)
    bot._storage.restore_context_tokens(ACCOUNT_ID)

    # 注册消息处理：收到消息 → 刷新 token
    @bot.on_message
    async def handle_message(msg):
        log.info(f"收到消息: type={msg.message_type}, from={msg.from_user_id}")
        # 收到消息后 SDK 会自动更新 context_token
        # 我们额外持久化一份到 IR 目录
        try:
            ct = bot._storage.get_context_token(ACCOUNT_ID, USER_ID)
            if ct:
                save_token(ct)
                log.info("context_token 已刷新并保存")
        except Exception as e:
            log.warning(f"保存 token 失败: {e}")

    log.info("启动龙少常驻服务...")
    print(f"🐲 龙少常驻服务启动中... (PID: {os.getpid()})")
    print(f"   日志: {LOG_DIR / 'longshao_daemon.log'}")

    if once:
        # 只刷新一次模式：启动 poller，等 30 秒看有没有消息
        await bot.start()
        print("   ⏳ 等待微信消息以刷新 token（最多30秒）...")
        old_ct = ""
        try:
            old_ct = bot._storage.get_context_token(ACCOUNT_ID, USER_ID) or ""
        except Exception:
            pass

        for i in range(15):
            await asyncio.sleep(2)
            try:
                new_ct = bot._storage.get_context_token(ACCOUNT_ID, USER_ID)
                if new_ct and new_ct != old_ct:
                    save_token(new_ct)
                    print(f"   ✅ context_token 已刷新！")
                    await bot.stop()
                    return True
            except Exception:
                pass

        # 没收到新消息，但保存现有 token
        try:
            ct = bot._storage.get_context_token(ACCOUNT_ID, USER_ID)
            if ct:
                save_token(ct)
                print(f"   ⚠️ 未收到新消息，已保存现有 token")
        except Exception:
            pass

        await bot.stop()
        return False
    else:
        # 常驻模式
        try:
            await bot.start()
            print("   ✅ 龙少已上线，Poller 运行中")
            print("   按 Ctrl+C 停止")

            # 定期保存 token（每 5 分钟）
            while True:
                await asyncio.sleep(300)
                try:
                    ct = bot._storage.get_context_token(ACCOUNT_ID, USER_ID)
                    if ct:
                        save_token(ct)
                except Exception:
                    pass
        except KeyboardInterrupt:
            print("\n   🛑 收到停止信号")
        except Exception as e:
            log.error(f"Poller 异常: {e}")
            print(f"   ❌ 异常: {e}")
        finally:
            await bot.stop()
            log.info("龙少服务已停止")


def main():
    once = "--once" in sys.argv
    try:
        asyncio.run(run_daemon(once=once))
    except KeyboardInterrupt:
        print("\n🐲 龙少服务已停止")


if __name__ == "__main__":
    main()
