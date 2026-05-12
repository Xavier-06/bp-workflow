# 数据源与搜索策略

## 数据源优先级

| 优先级 | 数据源 | 使用方式 |
|-------|--------|---------|
| 1 | NeoData 金融搜索 | A/HK 股行情、财报、板块、券商研报（search_gateway Layer 0 自动调用） |
| 2 | yfinance (Python) | 估值指标、美股主力、A/HK 股交叉验证（PE/PS/市值/财报/key statistics） |
| 3 | web_search | 实时搜索（东财/雪球/同花顺 行情、公告、行业报告） |
| 4 | 企查查 MCP | 国内公司工商信息、融资轮、诉讼、知产 |
| 5 | RAG_search | 向量记忆知识库 |
| 6 | tushare / yahoo skill | 补充金融数据 |

## 搜索降级链

NeoData Layer 0（金融查询自动触发）→ DDG → SearXNG(8888) → Yahoo Finance

## 估值数据获取

使用 `valuation_enricher.py` 获取实时估值（A/HK 股优先 NeoData + yfinance 交叉验证）：
```bash
python3 {IR_RUNTIME}/tasks/valuation_enricher.py --entity "标的名称"
```

## A 股特殊处理

- 股票代码：6 位数字（60xxxx / 00xxxx / 30xxxx / 688xxx）
- 红涨绿跌
- NeoData 原生支持 A 股中文查询（如"贵州茅台股价"直接返回行情）
- valuation_enricher 自动映射：6位代码→SZ/SS/BJ 后缀
- 中文名映射：公司名→股票代码→yfinance 查询
- NeoData 估值数据含：实时价格、PE(TTM)、PB、市值、成交额、资金流向、换手率
