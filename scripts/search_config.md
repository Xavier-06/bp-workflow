# 搜索引擎配置记录 (2026-04-04)

## 当前状态

| 实例 | 状态 | 用途 | 路由 |
|------|------|------|------|
| SearXNG EN | ✅ 127.0.0.1:18080 | 纯英文搜索 | 路由第 2 顺位 |
| SearXNG CN | ❌ 已弃用 | — | 不再使用 |
| DDG CLI | ✅ ddgs 命令 | 中文/混合查询主路由 | 路由第 1 顺位 |

## 搜索路由规则 (scripts/search_router.py)

```
中文/混合/股票代码 → DDG CLI
纯英文 → SearXNG EN(18080) → DDG CLI(fallback)
```

## 中文搜索结果示例

- "东江集团控股 02283" → DDG 返回 4 条精准结果（新浪港股、企查查、官网、金融新闻）
- "注塑模具行业市场规模 2025" → DDG 返回 5 条行业报告
- "泡泡玛特 2025财报" → DDG 返回年报、华尔街分析、大摩点评

## 历史教训

1. CN 实例 360search/搜狗/百度 全部被反爬拦截
2. CN 实例 DuckDuckGo SSL 证书验证失败
3. CN 实例 Bing 引擎返回中文乱码
4. 代理 IP 被 Google 400 拦截

## 当前实现细节

- `search_gateway.py` 作为 BP 主入口兼容层，内部已与 `search_router.py` 对齐。
- DDG CLI 默认走 `-o json`，并支持环境变量：`DDGS_REGION`、`DDGS_BACKEND`。
- 当前默认：`DDGS_REGION=wt-wt`，`DDGS_BACKEND=auto`。
- SearXNG 本地不可用时，英文查询会自动回退到 DDG。
