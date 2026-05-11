#!/usr/bin/env python3
"""
投研任务记忆源检查脚本
用于在研究任务开场时总结当前应从哪些记忆源优先读取
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent

def check_memory_sources() -> dict:
    """检查所有记忆源的状态"""
    
    # 检查 memory_agent 向量库（检查 chroma.sqlite3 是否存在）
    memory_db_path = ROOT / 'memory_agent' / 'memory_db' / 'chroma.sqlite3'
    memory_agent_exists = memory_db_path.exists()
    
    sources = {
        'primary': {
            'memory_agent': memory_agent_exists,
            'instruction_store': (ROOT / 'instruction_store_ir' / 'index.json').exists(),
        },
        'daily_logs': {
            'today': (ROOT / 'memory' / f'{datetime.now().strftime("%Y-%m-%d")}.md').exists(),
            'recent_7days': sum(
                1 for i in range(7) 
                if (ROOT / 'memory' / f'{(datetime.now() - __import__("datetime").timedelta(days=i)).strftime("%Y-%m-%d")}.md').exists()
            ),
        },
        'lessons': {
            'learnings_dir': (ROOT / '.learnings').exists(),
            'count': len(list((ROOT / '.learnings').glob('*.md'))) if (ROOT / '.learnings').exists() else 0,
        },
        'reports': {
            'final_reports': len(list((ROOT / 'reports').glob('*.docx'))) if (ROOT / 'reports').exists() else 0,
        },
        'workflow': {
            'tasks': len(json.loads((ROOT / 'data' / 'tasks' / 'tasks.json').read_text()).get('tasks', [])) 
                if (ROOT / 'data' / 'tasks' / 'tasks.json').exists() else 0,
        },
    }
    
    # 生成优先级建议
    priority_order = []
    if sources['primary']['instruction_store']:
        priority_order.append('instruction_store (投研专用指令)')
    if sources['daily_logs']['today']:
        priority_order.append('daily_logs (今日记忆)')
    if sources['primary']['memory_agent']:
        priority_order.append('memory_agent (长期记忆向量库)')
    if sources['lessons']['count'] > 0:
        priority_order.append(f'.learnings ({sources["lessons"]["count"]} 条教训)')
    
    return {
        'sources': sources,
        'priority_order': priority_order,
        'recommendation': ' | '.join(priority_order[:3]) if priority_order else '无可用记忆源',
        'checked_at': datetime.now().isoformat(timespec='seconds'),
    }

def main():
    result = check_memory_sources()
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
