# OpenClaw 平台适配指南

## 安装

```bash
# 克隆到 OpenClaw 工作目录
cd ~/.openclaw/workspace/
git clone https://github.com/YOUR_USERNAME/bp-workflow.git ir_runtime

# 安装依赖
cd ir_runtime
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填写配置
```

## AGENTS.md 触发规则

在 OpenClaw 的 `AGENTS.md` 中添加以下触发规则：

```markdown
| 触发信号 | 必读规则文件 |
|----------|-------------|
| 发 BP PDF + "尽调/简报/DD" | `rules/bp-pipeline.md` |
```

## Skill 安装

OpenClaw 的 Skill 存放在 `~/.openclaw/skills/`：

```bash
for skill in ir-coordinator ir-researcher ir-reporter ir-verifier; do
  cp -r skills/$skill ~/.openclaw/skills/
done
```

## Runtime 路径配置

OpenClaw 的 IR_RUNTIME 指向 `~/.openclaw/workspace/ir_runtime/`。

如果 SKILL.md 中的路径与你的安装路径不同，需要修改：

```bash
# 批量替换路径（如果需要）
sed -i 's|~/.workbuddy/ir_runtime|~/.openclaw/workspace/ir_runtime|g' \
  ~/.openclaw/skills/ir-*/SKILL.md
```

## 子代理派发

OpenClaw 的子代理派发机制与 WorkBuddy 类似，但需要确认：

1. Task tool 支持 `name` 参数（team 异步模式）
2. `mode="bypassPermissions"` 是否支持
3. 子代理是否可以通过 `send_message` 通信

如果不支持 team 异步模式，可以退化为同步模式：

```python
# 同步模式（OpenClaw 可能支持）
result = task(
    subagent_name='code-explorer',
    description='bp_团队与合规',
    prompt=instruction_prompt,
)
```

## 通知集成

OpenClaw 可能有自己的消息推送机制。编辑 `scripts/notify_plugin.py` 适配：

```python
def send_message(text: str) -> dict:
    # 使用 OpenClaw 的 CLI 或 API 推送通知
    import subprocess
    result = subprocess.run(
        ["openclaw", "notify", "--text", text],
        capture_output=True, text=True, timeout=10
    )
    return {"ok": result.returncode == 0, "msg": result.stdout}
```

## 差异对照

| 特性 | WorkBuddy | OpenClaw |
|------|-----------|----------|
| Skill 目录 | `~/.workbuddy/skills/` | `~/.openclaw/skills/` |
| Runtime 目录 | `~/.workbuddy/ir_runtime/` | `~/.openclaw/workspace/ir_runtime/` |
| 子代理模式 | team 异步（必须） | 同步/异步（视版本） |
| 通知推送 | media-index / MCP | 自定义 |
| Memory 路径 | `~/.workbuddy/memory/` | `~/.openclaw/memory/` |
