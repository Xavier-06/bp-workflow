# BP Workflow 示例配置

## 最小配置（开箱即用）

只需配置 VL OCR API，即可运行完整 BP 管线：

```bash
# .env
VL_API_BASE=https://your-vl-api.example.com/v1
VL_API_KEY=your-api-key
VL_MODEL=qwen3-vl-30b-a3b-instruct
```

## 完整配置

```bash
# .env

# VL OCR API（必须）
VL_API_BASE=https://your-vl-api.example.com/v1
VL_API_KEY=your-api-key
VL_MODEL=qwen3-vl-30b-a3b-instruct

# 微信通知（可选）
WECHAT_BOT_KEY=your-wechat-bot-key

# SearXNG 本地搜索引擎（可选，提升搜索质量）
SEARXNG_URL=http://localhost:8888

# 金融数据 API（可选，用于竞品分析中的财务数据）
NEODATA_API_KEY=your-neodata-key
```

## 自定义配置

### 修改融资阶段推断规则

编辑 `runtime/intake/bp_document_intake.py` 中的 `_infer_financing_stage()` 函数。

### 修改预搜索查询模板

编辑 `scripts/bp_presearch.py` 中的 `EARLY_STAGE_QUERIES` 和 `MATURE_STAGE_QUERIES` 字典。

### 修改 DOCX 报告模板

编辑 `scripts/build_bp_dd_report_docx.py` 中的 `build_bp_dd_report()` 函数。

### 添加新的搜索源

编辑 `scripts/search_gateway.py`，在 `search()` 函数中添加新的搜索引擎适配。
