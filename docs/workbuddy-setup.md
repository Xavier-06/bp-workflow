# WorkBuddy 平台适配指南

## Skill 安装

WorkBuddy 通过 `~/.workbuddy/skills/` 目录加载 Skill。每个 Skill 是一个包含 `SKILL.md` 的目录。

```bash
# 安装 4 个 Skill
for skill in ir-coordinator ir-researcher ir-reporter ir-verifier; do
  cp -r skills/$skill ~/.workbuddy/skills/
done
```

## Runtime 路径

WorkBuddy 的 ir_runtime 通常通过 symlink 指向实际管线目录：

```bash
# 推荐：在 ~/.workbuddy/ 下创建 symlink
ln -s /path/to/bp-workflow ~/.workbuddy/ir_runtime
```

Skill 中的 `IR_RUNTIME` 常量默认指向 `~/.workbuddy/ir_runtime/`。

## 子代理派发

WorkBuddy 的子代理必须使用 **team 异步模式** 派发：

```python
# 创建 team
team_create(team_name="bp-TASK-XXX")

# 派发子代理
task(
    subagent_name='code-explorer',
    name='bp-team',              # team member 名称
    team_name='bp-TASK-XXX',     # 加入 team
    mode='bypassPermissions',    # 确保可写文件
    description='bp_团队与合规',
    prompt=instruction_prompt,
)
```

**⚠️ 禁止使用同步 task()（无 name 参数），会导致 code=10003 错误。**

## 通知集成

WorkBuddy 支持通过 MCP（Message Control Protocol）推送文件：

1. 编辑 `scripts/notify_plugin.py`
2. 实现 `send_message()` 和 `notify_report()` 函数
3. 如果你的平台支持 WorkBuddy media-index，可在 `notify_report()` 中调用 `register_delivery_media.py`

## 产物路径

每个 Job 的产物在 `~/.workbuddy/ir_runtime/jobs/{JOB_ID}/` 下：

```
jobs/{JOB_ID}/
├── state/           # Phase 状态 JSON + artifacts.json
├── briefs/          # Step brief 文件
├── search/          # 搜索结果
├── extraction/      # URL 提取结果
├── artifacts/       # 中间产物
├── outputs/         # Step 输出 (.md)
├── verification/    # 对抗验证结果
└── delivery/        # DOCX + 审计报告
```
