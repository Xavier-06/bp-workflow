"""
批量导入智能体指令工具
用法：python import_instructions.py

支持两种方式导入：
1. 交互式逐条添加
2. 从文件夹批量导入（每个 .txt 文件 = 一个智能体指令）

文件命名规范：行业_角色.txt
例如：医药_行业分析师.txt, 半导体_研究员.txt
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(__file__))

from instruction_store import InstructionStore
from rich.console import Console
from rich.table import Table

console = Console()


def interactive_add():
    """交互式添加单条指令"""
    store = InstructionStore()

    console.print("\n[bold cyan]添加智能体指令[/bold cyan]\n")

    industry = console.input("行业名称 (如 医药/半导体/新能源): ").strip()
    role = console.input("角色名称 (如 行业分析师/研究员): ").strip()
    name = console.input(f"智能体名称 (默认：{industry}{role}): ").strip()
    if not name:
        name = f"{industry}{role}"
    description = console.input("简要描述：").strip()

    key = f"{industry}_{role}"

    console.print("\n请输入完整指令（支持多行，输入单独一行 END 结束）:")
    lines = []
    while True:
        line = input()
        if line.strip() == "END":
            break
        lines.append(line)
    instruction = "\n".join(lines)

    keywords_input = console.input("\n关键词（逗号分隔，如 医药，创新药，CXO）: ").strip()
    keywords = [kw.strip() for kw in keywords_input.split(",") if kw.strip()]

    store.add_instruction(
        key=key,
        name=name,
        industry=industry,
        role=role,
        instruction=instruction,
        description=description,
        keywords=keywords,
    )

    console.print(f"\n[green]✓ 已添加：{key} ({len(instruction)} 字)[/green]")


def batch_import(folder_path: str):
    """
    从文件夹批量导入
    文件命名：行业_角色.txt，文件内容即为完整指令
    """
    store = InstructionStore()

    if not os.path.isdir(folder_path):
        console.print(f"[red]文件夹不存在：{folder_path}[/red]")
        return

    txt_files = [f for f in os.listdir(folder_path) if f.endswith(".txt")]

    if not txt_files:
        console.print(f"[yellow]文件夹中没有找到 .txt 文件[/yellow]")
        return

    console.print(f"\n找到 {len(txt_files)} 个指令文件:\n")

    for filename in sorted(txt_files):
        filepath = os.path.join(folder_path, filename)
        key = filename.replace(".txt", "")

        # 解析行业和角色
        parts = key.split("_", 1)
        industry = parts[0]
        role = parts[1] if len(parts) > 1 else "分析师"

        with open(filepath, "r", encoding="utf-8") as f:
            instruction = f.read()

        # 如果文件第一行是 #keywords: xxx,yyy,zzz 格式，提取关键词
        keywords = []
        lines = instruction.split("\n")
        if lines[0].startswith("#keywords:"):
            keywords = [kw.strip() for kw in lines[0].replace("#keywords:", "").split(",")]
            instruction = "\n".join(lines[1:]).strip()

        store.add_instruction(
            key=key,
            name=f"{industry}{role}",
            industry=industry,
            role=role,
            instruction=instruction,
            description=f"从文件 {filename} 导入",
            keywords=keywords,
        )

        console.print(f"  [green]✓[/green] {key} ({len(instruction)} 字)")

    console.print(f"\n[green]批量导入完成！共 {len(txt_files)} 条指令[/green]")


def show_all():
    """显示所有已配置的指令"""
    store = InstructionStore()
    agents = store.list_all()

    if not agents:
        console.print("[yellow]暂无指令[/yellow]")
        return

    table = Table(title=f"已配置指令 ({len(agents)} 个)")
    table.add_column("Key", style="cyan")
    table.add_column("行业", style="green")
    table.add_column("角色", style="white")
    table.add_column("指令长度", style="yellow", justify="right")
    table.add_column("关键词", style="dim")

    for a in agents:
        table.add_row(
            a["key"],
            a["industry"],
            a["role"],
            f"{a['instruction_length']} 字",
            ", ".join(a["keywords"][:5]),
        )
    console.print(table)


def main():
    console.print("""
[bold]智能体指令管理工具[/bold]

1. 交互式添加单条指令
2. 从文件夹批量导入 (.txt 文件)
3. 查看所有已配置指令
4. 导出为 JSON（备份）
5. 退出
""")

    while True:
        choice = console.input("\n请选择 (1-5): ").strip()

        if choice == "1":
            interactive_add()
        elif choice == "2":
            folder = console.input("请输入文件夹路径：").strip()
            batch_import(folder)
        elif choice == "3":
            show_all()
        elif choice == "4":
            store = InstructionStore()
            backup_path = os.path.join(os.path.dirname(__file__), "instructions_backup.json")
            import shutil
            shutil.copy2(store.filepath, backup_path)
            console.print(f"[green]✓ 已导出到：{backup_path}[/green]")
        elif choice == "5":
            break
        else:
            console.print("[yellow]无效选择[/yellow]")


if __name__ == "__main__":
    main()
