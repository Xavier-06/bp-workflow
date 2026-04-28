# 搜索系统集成指南

BP 管线在 Phase 0.5（Company Verify）和 Phase 1（Presearch）阶段需要搜索能力。管线内置了 `search_gateway.py` 作为搜索抽象层，但默认实现基于 SearXNG，需要本地部署。

如果你没有 SearXNG，或者想使用更强大的搜索能力，可以按以下方式集成替代搜索系统。

## 方案一：WorkBuddy 插件搜索（推荐）

WorkBuddy 平台提供了 `neodata-financial-search` 和 `westock-data` 两个金融搜索插件，覆盖 A股/港股/美股全品类数据。

### 集成方式

在 `search_gateway.py` 中添加 WorkBuddy 插件搜索适配器：

```python
class WorkBuddySearchAdapter:
    """WorkBuddy 金融插件搜索适配器"""

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        """
        通过 neodata-financial-search skill 搜索。
        在 WorkBuddy 环境中，直接调用 use_skill("neodata-financial-search") 即可。
        """
        # 在 WorkBuddy AI agent 中使用：
        # use_skill("neodata-financial-search") → 自然语言查询金融数据
        # use_skill("westock-data") → 结构化行情/财报/资金流
        raise NotImplementedError("在 AI agent 上下文中直接调用 skill，不走 Python API")

    def search_stock(self, code: str, market: str = "cn") -> dict:
        """通过 westock-data 获取个股数据"""
        # npx --yes westock-data-skillhub@latest finance {code} {periods}
        raise NotImplementedError("在 AI agent 上下文中使用 skill")
```

### 使用优先级

遇到金融数据问题时，按以下顺序尝试：

1. **`neodata-financial-search`**：默认使用，覆盖股票行情、财报、基金净值、板块异动、宏观指标
2. **`westock-data`**：当需要技术指标、筹码成本、股东结构、ETF持仓、龙虎榜等 neodata 不覆盖的数据时
3. **`web_search`**：两个 skill 都无法满足时，回退到通用搜索

### westock-data 命令速查

```bash
# 代码格式：沪市 sh600519 / 深市 sz000001 / 港股 hk00700 / 美股 usAAPL
npx --yes westock-data-skillhub@latest search 腾讯控股    # 搜索
npx --yes westock-data-skillhub@latest kline sh600519 day 20  # K线
npx --yes westock-data-skillhub@latest finance sh600519 4  # 财务报表
npx --yes westock-data-skillhub@latest profile sh600519    # 公司简况
npx --yes westock-data-skillhub@latest asfund sh600519     # A股资金流向
npx --yes westock-data-skillhub@latest technical sh600519 macd  # 技术指标
npx --yes westock-data-skillhub@latest chip sh600519       # 筹码成本（仅A股）
npx --yes westock-data-skillhub@latest shareholder sh600519  # 股东结构
npx --yes westock-data-skillhub@latest dividend sh600519   # 分红数据
```

## 方案二：SearXNG 本地部署（默认）

`search_gateway.py` 默认使用 SearXNG 实例。部署方式：

```bash
# Docker 一键部署
docker run -d --name searxng \
  -p 8888:8080 \
  -e SEARXNG_BASE_URL=http://localhost:8888 \
  searxng/searxng

# 验证
curl "http://localhost:8888/search?q=test&format=json"
```

在 `.env` 中配置：

```env
SEARXNG_BASE_URL=http://localhost:8888
```

### 已知限制

- 需要本地 Docker 环境
- 搜索质量依赖 SearXNG 上游引擎
- 无金融结构化数据（需配合 westock-data）

## 方案三：自定义搜索适配器

实现 `SearchAdapter` 接口即可替换搜索后端：

```python
class SearchAdapter(ABC):
    @abstractmethod
    def search(self, query: str, max_results: int = 10) -> list[dict]:
        """返回 [{title, url, snippet}, ...]"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """健康检查"""
        ...
```

在 `search_gateway.py` 的 `get_search_adapter()` 中注册你的实现。

## 搜索质量评分

BP 管线对搜索结果使用证据质量评分：

| 评级 | 标准 | 来源示例 |
|------|------|---------|
| 🅰 | 一手官方信息 | 工商登记、公司年报、专利文书 |
| 🅱 | 权威媒体/行业报告 | 36kr、证券时报、Gartner |
| 🅲 | 二手/不确定来源 | 自媒体、论坛、未核实信息 |

子代理在引用数据时必须标注来源评级。
