#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_package')
    ap.add_argument('analysis_draft')
    args = ap.parse_args()
    pkg = json.loads(Path(args.task_package).read_text(encoding='utf-8'))
    task_id = pkg['task']['task_id']

    lines = [
        f'# 风险催化表 v2 - {task_id}',
        '',
        '## 催化剂（量化草稿）',
        '| 类别 | 描述 | 观察指标 | 时间窗口 | 可能影响 | 当前置信度 |',
        '|---|---|---|---|---|---|',
        '| 政策 | AI 医疗相关监管指引继续细化 | 是否出现正式指引/医保/器审口径更新 | 3-12个月 | 提升行业落地预期，利好应用端估值修复 | medium |',
        '| 技术 | 多模态/生成式 AI 在医疗场景持续落地 | 是否出现新产品/医院落地案例/大厂合作 | 3-9个月 | 推动行业叙事从概念走向应用验证 | medium |',
        '| 产业 | 科技平台与医疗 IT / 器械公司的合作加深 | 合作公告、产品发布、订单线索 | 3-12个月 | 可能推动产业链映射与可比公司重估 | medium |',
        '',
        '## 风险（量化草稿）',
        '| 类别 | 描述 | 观察指标 | 严重性 | 当前处理建议 |',
        '|---|---|---|---|---|',
        '| 口径风险 | 市场规模与增速口径分散 | 不同报告的年份/币种/定义是否一致 | high | 统一市场定义、年份、币种与区域 |',
        '| 可比公司偏差 | 概念相关与真正可比未分层 | 公司是否直接受益于 AI 医疗商业化 | medium | 重新按平台型/应用型/医疗IT/AI制药分层 |',
        '| 监管噪音 | 政策材料中有宣传/模板站内容 | 来源是否为正式文件/高质量机构材料 | medium | 继续清洗来源并降权宣传性材料 |',
        '| 落地不确定 | 技术热度高于商业化速度 | 是否有真实付费/装机/订单案例 | medium | 优先补客户付费与落地案例 |',
        '',
        '## 使用说明',
        '- 这版风险催化表已经加入“观察指标”和“可能影响”，比首版更接近可执行跟踪表。',
    ]
    out = TASKS_DIR / f'{task_id}-risk-catalyst-v2.md'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'task_id': task_id, 'output': str(out)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
