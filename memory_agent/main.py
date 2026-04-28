"""
投研主管 Agent - 带记忆系统的命令行界面
运行方式：python main.py

命令：
  /quit     - 退出并保存记忆
  /save     - 手动触发记忆提取
  /stats    - 查看记忆库统计
  /agents   - 查看已配置的智能体
  /context  - 查看当前活跃上下文
  /todo     - 查看待办事项
  /clear    - 清除当前对话历史（不清记忆）
  /reset    - 清空所有记忆（慎用！）
"""
import sys
import os

# 确保项目目录在 path 中
sys.path.insert(0, os.path.dirname(__file__))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich import print as rprint

from agent import Agent
import config

console = Console()


def print_banner():
    banner = """
╔══════════════════════════════════════════════════╗
║     🧠  投研主管 Agent - Memory System  🧠      ║
║                                                  ║
║  记忆系统已启用：                                 ║
║  • 向量记忆库 (ChromaDB + 百炼 Embedding)        ║
║  • 智能体指令库 (JSON)                           ║
║  • 工作日志 (Markdown)                           ║
║                                                  ║
║  输入 /help 查看可用命令                          ║
╚══════════════════════════════════════════════════╝
"""
    console.print(banner, style="bold blue")


def print_help():
    table = Table(title="可用命令")
    table.add_column("命令", style="cyan")
    table.add_column("说明", style="white")
    table.add_row("/quit", "退出并自动保存本轮记忆")
    table.add_row("/save", "手动触发本轮记忆提取（不退出）")
    table.add_row("/stats", "查看记忆库统计数据")
    table.add_row("/agents", "查看已配置的智能体指令")
    table.add_row("/context", "查看当前研究上下文")
    table.add_row("/todo", "查看待办事项")
    table.add_row("/clear", "清除本轮对话历史（不清记忆库）")
    table.add_row("/reset", "清空所有记忆（⚠️ 慎用！）")
    table.add_row("/help", "显示此帮助信息")
    console.print(table)


def show_stats(agent: Agent):
    stats = agent.get_memory_stats()
    table = Table(title="记忆库统计")
    table.add_column("类别", style="cyan")
    table.add_column("数量", style="green", justify="right")
    table.add_row("用户偏好", str(stats["user_preferences"]))
    table.add_row("历史错误", str(stats["past_errors"]))
    table.add_row("关键数据", str(stats["key_data"]))
    table.add_row("对话摘要", str(stats["conversations"]))
    table.add_row("总计", str(sum(stats.values())), style="bold")
    console.print(table)


def show_agents(agent: Agent):
    agents_list = agent.instructions.list_all()
    if not agents_list:
        console.print("[yellow]暂无配置的智能体指令。请编辑 instructions/instructions.json[/yellow]")
        return

    table = Table(title=f"已配置智能体 ({len(agents_list)} 个)")
    table.add_column("Key", style="cyan")
    table.add_column("名称", style="white")
    table.add_column("行业", style="green")
    table.add_column("指令长度", style="yellow", justify="right")
    table.add_column("关键词", style="dim")

    for a in agents_list:
        table.add_row(
            a["key"],
            a["name"],
            a["industry"],
            f"{a['instruction_length']} 字",
            ", ".join(a["keywords"][:5]),
        )
    console.print(table)


def save_memories(agent: Agent):
    console.print("[yellow]正在提取本轮对话记忆...[/yellow]")
    result = agent.extract_and_save_memories()

    if result["status"] == "success":
        console.print(
            f"[green]✓ 记忆提取完成："
            f"保存 {result['memories_saved']} 条记忆，"
            f"上下文{'已' if result['context_updated'] else '未'}更新，"
            f"新增 {result['todos_added']} 条待办[/green]"
        )
    elif result["status"] == "skipped":
        console.print(f"[dim]{result['reason']}[/dim]")
    else:
        console.print(f"[red]✗ 提取失败：{result.get('reason', '未知错误')}[/red]")


def main():
    # 检查 API Key
    if config.DASHSCOPE_API_KEY == "你的百炼 API-KEY":
        console.print(
            Panel(
                "请先在 config.py 中填入你的百炼 API Key\n"
                "或设置环境变量：export DASHSCOPE_API_KEY=你的 key",
                title="⚠️ 配置缺失",
                style="red",
            )
        )
        return

    print_banner()

    # 初始化 Agent
    console.print("[dim]正在初始化记忆系统...[/dim]")
    agent = Agent()
    stats = agent.get_memory_stats()
    total = sum(stats.values())
    console.print(f"[green]✓ 记忆系统就绪，当前共有 {total} 条历史记忆[/green]\n")

    # 主循环
    while True:
        try:
            user_input = console.input("[bold cyan]你：[/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            user_input = "/quit"

        if not user_input:
            continue

        # 命令处理
        if user_input.startswith("/"):
            cmd = user_input.lower().split()[0]

            if cmd == "/quit":
                save_memories(agent)
                console.print("[bold blue]再见！记忆已保存。[/bold blue]")
                break

            elif cmd == "/save":
                save_memories(agent)
                continue

            elif cmd == "/stats":
                show_stats(agent)
                continue

            elif cmd == "/agents":
                show_agents(agent)
                continue

            elif cmd == "/context":
                ctx = agent.work_log.get_active_context()
                if ctx:
                    console.print(Panel(Markdown(ctx), title="活跃上下文"))
                else:
                    console.print("[dim]暂无活跃上下文[/dim]")
                continue

            elif cmd == "/todo":
                todos = agent.work_log.get_todos()
                if todos:
                    console.print(Panel(Markdown(todos), title="待办事项"))
                else:
                    console.print("[dim]暂无待办事项[/dim]")
                continue

            elif cmd == "/clear":
                agent.reset_conversation()
                console.print("[green]对话历史已清除（记忆库保留）[/green]")
                continue

            elif cmd == "/reset":
                confirm = console.input("[red]确认清空所有记忆？输入 YES 确认：[/red]")
                if confirm == "YES":
                    agent.memory.clear_all()
                    console.print("[red]所有记忆已清空[/red]")
                else:
                    console.print("[dim]已取消[/dim]")
                continue

            elif cmd == "/help":
                print_help()
                continue

            else:
                console.print(f"[yellow]未知命令：{cmd}，输入 /help 查看帮助[/yellow]")
                continue

        # 正常对话
        console.print("[bold green]助手：[/bold green]", end="")
        try:
            for chunk in agent.chat(user_input, stream=True):
                console.print(chunk, end="", highlight=False)
            console.print()  # 换行
        except Exception as e:
            console.print(f"\n[red]对话出错：{e}[/red]")

        console.print()  # 空行分隔


if __name__ == "__main__":
    main()
