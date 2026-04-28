# HOT Memory

- Updated: 2026-04-09 12:00
- Purpose: 当前活跃任务、最近决策、下一步动作。只保留短期必须用的信息。

## Active Tasks
1. 检查记忆系统 bug
   - 状态: 🔄 进行中
   - 更新: 2026-04-09 10:39
   - 下一步/备注: 已确认主线跑在 memory_agent。现正收口入口层：修复坏掉的 scripts/mem.py、把 scripts/memory_bridge.py 改成兼容壳、移除 memory-cmd.sh 对旧 mem0/memory_system 的误导性包装，再跑回归测试。
2. 修 BP 管线关键问题
   - 状态: ⏸️ 暂停
   - 更新: 2026-04-09 10:03
   - 下一步/备注: 已定位并绕过致命断点（根目录影子 `bp_preflight_check.py` 导致 Step0 产物路径串味）。回归任务跑到长搜索阶段后被 SIGKILL 中断，待继续收口。

## Today Decisions
（无）

## Today TODO
（无）

## HOT Rules
- 只保留未来 1-3 次对话内真的会用到的信息。
- 已完成任务不要留在 HOT。
- 不存明文密钥，只存根路径或引用。
