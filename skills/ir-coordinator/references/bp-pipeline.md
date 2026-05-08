# BP 管线详细流程

## 管线阶段

```
phase0_document_intake     — VL OCR + Step0 结构化抽取
phase05_company_verify     — BP 专用工商验证脚本
phase1_presearch           — BP 专用预搜索脚本 + URL 内容提取
phase2_dispatch_prepare    — 写 manifest/brief，返回 needs_dispatch（前 3 维度）
│   └── 主 AI 读 manifests → 自动 Task 派发 3 个子代理
phase2_dispatch_collect    — 检查 3 维度输出是否完成
phase25_competition_prepare — 写竞争与结论 manifest，返回 needs_dispatch
│   └── 主 AI 派发竞争与结论子代理（可参考前 3 维度输出）
phase25_competition_collect — 检查竞争与结论输出
phase3_delivery            — 一致性验证 + delivery gate + DD 报告交付
```

## 提交任务

```bash
cd {IR_RUNTIME}

# BP 任务
python3 -m runtime.orchestrator.pipeline_orchestrator submit \
  --entity "公司名称" --market cn --input-file /path/to/bp.pdf
```

## BP Step 波次（分步派发，自动化）

管线在 `_prepare` 阶段返回 `needs_dispatch`，主 AI 自动读取 manifest 并用 Task 工具派发子代理。
子代理完成后，**主 AI 必须自动检查并推进下一 phase**，无需等待用户说"继续"。

| 波次 | Steps | 维度 | 触发方式 |
|------|-------|------|---------|
| Wave 1 | bp_团队与合规, bp_技术与产品, bp_行业与供应链 | 前 3 维度并行 | phase2_dispatch_prepare 自动暂停 |
| Wave 2 | bp_竞争与结论 | 竞争与结论（依赖 Wave 1 输出） | phase25_competition_prepare 自动暂停 |
| Wave 3 | bp_统稿 | 投研逻辑重组+执行摘要 | phase3_synthesis_prepare 自动暂停 |

## BP 子代理派发硬规则（team 异步模式）

- **必须用 team 异步模式**：`team_create(team_name=f"bp-{task_id}")` → `task(name=..., team_name=...)` → 轮询输出文件
- **禁止用同步 `task()`**（无 name 参数）——会返回 code=10003 挂掉
- `subagent_name` 固定为 `code-explorer`，`mode="bypassPermissions"`
- 派发后通过 `execute_command` 轮询输出文件（sleep 30 → test -s → 重复）
- 收到所有同 wave 输出文件后 → 自动调用 `execute(..., start_phase=...)` 推进下一 phase
- **绝对不要等待用户说"继续"**

## BP 9 维度 Gap 检测

- 市场规模与增长、竞争格局、商业模式、技术壁垒
- 团队背景、财务数据、融资历史、退出路径、风险因素

## Wave 3 统稿子代理

- 读取四个维度输出，按投研逻辑重组为完整研究报告（对标悦享资本/红杉/高瓴研报水准）
- 输出结构：执行摘要→技术原理（外行能懂）→技术壁垒量化评估→痛点解决→方案对比→厂商情况→市场规模→民用拓展→BP验证→风险→结论建议
- **脚注硬规则**：子代理 [^N] 标记必须保留，统稿时补全缺失脚注，正文每个关键数据点都要有 [^N]，末尾"来源与参考"展开
- **专利不堆砌**：核心≤5项，其余概括性描述
- **技术壁垒量化评估**必须独立成节（壁垒高度+实用性+赚钱能力，全部配数字和脚注）
- **⚠️ 统稿保留硬约束**（解决统稿过度压缩问题）：
  - **核心对比表必须原文保留**：行业技术路线全景对比表、产品级竞品参数对比表、现有方案深度对比大表、核心组件拆解表——不得删除或压缩为文字叙述
  - **市占率/份额/渗透率数据必须完整保留**：TAM/SAM/SOM分层推算及每层具体数字、各细分市场渗透率及驱动力、竞品市占率（具体数字和百分比，不能只写"垄断竞争"等模糊表述）、标的公司在各细分市场的渗透率
  - **去重只做跨维度，不做维度内压缩**：跨维度重复内容可合并，但单个维度内部的表格、数据、分析段落不得删除或压缩。5张产品线竞品对比表必须保留5张，不能合并成1张
  - **来源合并不得丢来源**：所有子代理的来源索引表都必须合并到统稿末尾"来源与参考"章节，不能因格式不同就丢弃；非[^N]格式的来源必须转换为[^N]脚注格式纳入统一编号；目标：统稿来源总数 ≥ 各维度来源去重后总数
- 必须用 team 异步模式派发：`task(name='bp-synthesis', team_name=..., mode='bypassPermissions')`
- manifest 路径：`{task_dir}/bp_phase3_manifest_synthesis.json`
- 输出路径：`{outputs_dir}/bp_synthesis.md`

## BP 交付

**全自动交付**（无需手动步骤）：
- `phase3_delivery` 自动调用 `register_delivery_media.py` → WorkBuddy media-index + message-queue
- 报告路径：`{job_dir}/delivery/TASK-XXXX_bp_dd_report.docx`
- 微信通知包含：任务ID、维度完成情况、报告文件名
- **注意**：BP 走 WorkBuddy 内部消息系统，IR 走微信 iLink 协议，两者交付链路不同

## Team 清理硬规则

- 交付完成后**必须清理 team**，否则 workspace 会一直挂着
- 清理顺序：先 `send_message(type="shutdown_request", recipient=每个member)` → 等 10 秒 → `team_delete()`
- 如果 `team_delete()` 因 active member 失败，再次发送 shutdown_request 并等待后重试
- 绝对不能跳过 team 清理就结束对话

## DD 报告生成与交付

- 4 维度汇总（团队/技术/行业/竞争）
- `build_bp_dd_report_docx.py` 生成 Word 报告（v2：支持表格、行内格式、来源清洗）
- **⚠️ 交付硬规则**：管线 phase3_delivery 完成后，返回值含 `deliver_to_user: true` 和 `docx_path`。
  Coordinator 必须执行以下交付动作：
  1. 在聊天窗口告知用户报告完成 + 文件路径
  2. 调用 `open_result_view` 展示报告（如适用）
  3. 微信通知已由管线自动发送，无需重复
  4. **禁止**使用 `deliver_attachments`（客户端不显示附件）
