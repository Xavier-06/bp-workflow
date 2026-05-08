# 交付协议

**唯一来源**：此文件是交付链路和微信推送规则的 single source of truth。

## 交付文件选择（硬规则）

- BP 报告：交付 `{JOB_ID}_bp_dd_report.docx`（统稿版），**不发**中文命名的 copy
- IR 研报：交付 `{JOB_ID}_broker_report.docx`

## 交付动作（必须全部执行）

1. 龙少微信通知（告知报告完成 + 文件路径）：
```bash
python3 {IR_RUNTIME}/scripts/longshao_notify.py "📊 {标的名称} 研报已完成。文件位置：{文件路径}"
```
如果返回 `ok: false`，直接重试一次（可能是瞬时错误）。

2. 在聊天窗口明确告知用户文件完整路径，方便用户自行获取。

**注意**：`deliver_attachments` 工具在用户客户端无法显示附件，**禁止使用**。

## 交付链路说明

- IR 管线使用 `longshao_notify.py` → wechat_bot SDK → 微信 iLink 协议直接发送消息
- BP 管线使用 `register_delivery_media.py` → WorkBuddy media-index + message-queue
- 两者不可混用：IR 研报走微信通知，BP 报告走 media-index 投递

## 微信推送格式

```
📊 研报完成：{标的名称}

✅ 8 步分析已完成
📄 报告路径：{workspace}/delivery/{TASK_ID}.docx
🔍 对抗验证：PASS/PARTIAL

关键发现：
- {3 条核心结论，每条 ≤30 字}
```

## 交付清洗（硬规则）

- sanitize_text() 清洗所有内部信息
- 标题页不暴露 task ID
- Markdown 表格 → Word 原生表格
- 包含免责声明页

## 产物归档

所有产物自动同步到 workspace：
- DOCX → `{IR_RUNTIME}/jobs/{JOB_ID}/delivery/`
- 验证报告 → `{IR_RUNTIME}/jobs/{JOB_ID}/verification/`
- 审计日志 → `{IR_RUNTIME}/jobs/{JOB_ID}/delivery/`
- artifacts.json 记录所有产物路径
