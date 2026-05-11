#!/usr/bin/env python3
"""
初始化投研指令库
从 notes/ 目录读取投研角色定义，写入 instruction_store
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / 'instruction_store_ir'

def init_store():
    STORE.mkdir(parents=True, exist_ok=True)
    
    # 读取投研角色文件
    roles_path = ROOT / 'notes' / 'investment-research-agent-roles.md'
    if not roles_path.exists():
        print('❌ 投研角色文件不存在')
        return
    
    content = roles_path.read_text(encoding='utf-8')
    
    # 写入索引
    index = {
        'meta': {
            'version': 1,
            'created_at': datetime.now().isoformat(timespec='seconds'),
            'source': 'notes/investment-research-agent-roles.md',
        },
        'roles': [
            {'key': '投研_主管', 'name': '投研主管 Agent', 'file': '投研_主管.md'},
            {'key': '投研_主笔_数据收集', 'name': '数据收集 Agent', 'file': '投研_主笔_数据收集.md'},
            {'key': '投研_主笔_行业分析', 'name': '行业分析 Agent', 'file': '投研_主笔_行业分析.md'},
            {'key': '投研_主笔_商业模式', 'name': '商业模式 Agent', 'file': '投研_主笔_商业模式.md'},
            {'key': '投研_主笔_财务分析', 'name': '财务分析 Agent', 'file': '投研_主笔_财务分析.md'},
            {'key': '投研_主笔_管理层', 'name': '管理层 Agent', 'file': '投研_主笔_管理层.md'},
            {'key': '投研_主笔_差异化洞察', 'name': '差异化洞察 Agent', 'file': '投研_主笔_差异化洞察.md'},
            {'key': '投研_主笔_风险催化', 'name': '风险催化 Agent', 'file': '投研_主笔_风险催化.md'},
            {'key': '投研_主笔_移交说明', 'name': '移交说明 Agent', 'file': '投研_主笔_移交说明.md'},
            {'key': '投研_主笔_文档汇总', 'name': '文档汇总 Agent', 'file': '投研_主笔_文档汇总.md'},
        ],
    }
    
    (STORE / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'✅ instruction_store 已初始化，共 {len(index["roles"])} 个角色')

if __name__ == '__main__':
    init_store()
