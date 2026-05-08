# 质量门禁与错误处理

## 质量门禁（硬规则）

1. **Step 完整性门禁** — `verify_step1_completeness.py`
   - BLOCK（<50%）→ 禁止进入后续 step
   - WARN（50-70%）→ 降级标记后可继续
   - PASS（>70%）→ 正常推进
2. **跨 Step 一致性门禁** — `verify_cross_step_consistency.py`
   - FAIL → 必须修正后再统稿
3. **子代理产出最低标准** — Step1 ≥100字含市场数据，Step2-7 ≥150行含来源
4. **完成率 <50% 熔断** — dispatch 阶段完成率不足时阻断 delivery

## 错误处理

| 错误 | 处理 |
|------|------|
| 环境检测失败 | 报告缺失项，不继续 |
| 任一 Step 空返回 | 5 分钟内重派 |
| 子代理超时（25 分钟） | 重新派发，最多 2 次 |
| 验证 FAIL | 修复后重验 1 次 |
| 全链路超时（120 分钟） | 标注超时，交付已完成部分 |
| Step1 完整性 <50% | 熔断，阻断 delivery |
| 数据不够不能往下跑 | 估值偏差 >20% 需告警 |

## BP 质量检查

BP 质量评分维度：content_length, url_count, unique_domain_count, unverified_count, section_count
通过阈值：score >= 3
