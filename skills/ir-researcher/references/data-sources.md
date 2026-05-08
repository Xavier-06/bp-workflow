# 数据源与搜索策略

## 数据源优先级

| 优先级 | 数据源 | 使用方式 |
|-------|--------|---------|
| 1 | neodata-financial-search skill | A股/港股/美股行情、财报、宏观 |
| 2 | finance-data-retrieval skill | 209 个结构化 API 精确查询 |
| 3 | web_search | 实时搜索 |
| 4 | RAG_search | 向量记忆知识库 |
| 5 | tushare / yahoo skill | 补充金融数据 |

## 搜索降级链

SearXNG(8888) → DDG → Yahoo Finance

## 估值数据获取

使用 `valuation_enricher.py` 获取实时估值：
```bash
python3 {IR_RUNTIME}/tasks/valuation_enricher.py --entity "标的名称" --market cn
```

## A 股特殊处理

- 股票代码：6 位数字（60xxxx / 00xxxx / 30xxxx / 688xxx）
- 红涨绿跌
- valuation_enricher 自动映射：6位代码→SZ/SS/BJ 后缀
- 中文名映射：公司名→股票代码→yfinance 查询
