## 搜索引擎（2026-04-04 统一网关）

**脚本导入：**
```python
from scripts.search_gateway import search, verify_engines
results = search("公司名 关键词", max_results=10)  # SearXNG 主力 → DDG 自动兜底
status = verify_engines()  # {"searxng": True/False, "ddg": True/False}
```

**CLI：**
```bash
python3 scripts/search_gateway.py '关键词' -n 10 --json
python3 scripts/search_gateway.py --verify           # 引擎状态检查
```

**统一搜索栈：**
- **SearXNG 本地（18080）**：26 引擎（Google/Brave/Bing/arXiv/Scholar/Reuters...），Clash 代理 127.0.0.1:7897
- **DDG（ddgs CLI）**：Rust HTTP 客户端，不走代理，SearXNG 不可用时全局自动兜底
- **Scrapling**：SearXNG 返回 URL → 抓正文 → LLM 提取（正文补抓）
- **Yahoo Finance**：估值补证（仅 IR 管线）
- **禁用**：Tavily（BP 管线零费用），Tavily（IR 管线已移除）

**回退链**：SearXNG 本地(18080) → SearXNG 公共实例 → DDG CLI → DDG Python 库

---

## 记忆去重

**脚本导入（函数，无类）：**
```python
from scripts.memory_dedup import add_content
add_content("内容", type="今日事项")
# decay/dedup 只能通过 CLI 调用
```

**CLI：**
```bash
python3 scripts/memory_dedup.py add "内容" --type 今日事项
python3 scripts/memory_dedup.py decay --days 30
python3 scripts/memory_dedup.py dedup --file memory/2026-04-07.md
