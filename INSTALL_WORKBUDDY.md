# Workbuddy 安装说明（IR 研报管线）

## 这包里有什么
- `scripts/`：IR 主控、搜索、Gap 检测、子代理、交付脚本
- `research/` / `content/`：研究与抓取模块
- `instruction_store/`：研报角色指令库
- `memory_agent/`：向量记忆系统代码（不含 venv / logs / 现有数据库）
- `memory/`：桥接层 + 主题记忆 + HOT/WARM snapshot

## 安装建议
1. 解压到：`~/.openclaw/workspace/`
2. 运行路径修补：
   ```bash
   python3 tools/patch_paths.py --root "$HOME/.openclaw/workspace"
   ```
3. 配置密钥：把 `.credentials/investment-research.env.example` 复制成 `.credentials/investment-research.env` 并填值
4. 安装记忆系统依赖：
   ```bash
   cd ~/.openclaw/workspace/memory_agent
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
5. 确保 `data/tasks/` 目录存在（本包已预建）

## 最小验证
```bash
cd ~/.openclaw/workspace
python3 scripts/check_ir_memory_sources.py
python3 scripts/ir_preflight_check.py --help
python3 scripts/run_ir_pipeline.py --help
```

## 注意
- 这包**不含**你的密钥、venv、logs、历史运行垃圾
- 若要继承历史记忆，再解压配套的 `workbuddy_memory_snapshot_*.zip`
