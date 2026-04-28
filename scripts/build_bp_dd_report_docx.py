#!/usr/bin/env python3
"""
BP 尽调报告 DOCX 生成 v3
从各 step 产出文件汇总生成专业尽调报告 Word 文档

v3 修复（2026-04-02）：
  - 修：保留 **加粗**、### 标题 等 Markdown 语义
  - 修：URL 收集链路打通（appendix 真正有内容）
  - 修：Markdown table → Word 原生表格（正文自动转）
  - 修：风险分级（高/中/低标签）
  - 精简：合并两个 sanitize 函数为一个
  - 精简：正则去冗，保留有效部分

用法：
  python3 build_bp_dd_report_docx.py --task-id TASK-XXX [--output /path/to/output.docx]
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

WORKSPACE = Path(os.getenv("OPENCLAW_WORKSPACE", os.path.expanduser("~/.openclaw/workspace")))
TASKS_DIR = WORKSPACE / "tasks"
REPORTS_DIR = WORKSPACE / "reports"


# ════════════════════════════════════════════════════════
# 交付清洗层：内部信息过滤
# ════════════════════════════════════════════════════════

# L1: 正则替换（必须删除的内部痕迹）
DELETE_RULES = [
    (r"/Users/\S+", ""),
    (r"file://\S+", ""),
    (r"TASK-\d{4}", ""),
    (r"任务\s*[IiDd][:：]\s*\S+", ""),
    (r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ""),
    (r"\.openclaw/\S+", ""),
    (r"scripts/[^\s,.;]+\.py", ""),
    (r"instruction_store\w*/[^\s,.;]+", ""),
    (r"bp_presearch\w*", ""),
    (r"bp_preflight\w*", ""),
    (r"thinking\s*=\s*high", ""),
    (r"roster\w*", ""),
    (r"brief\s*(文件|文档|内容)?", ""),
    (r"handoff", ""),
    (r"等待.*门禁验证", ""),
    (r"主控必须审核", ""),
    (r"下游子代理执行指引", ""),
    (r"搜索词组合", ""),
    (r"自检\s*\S*", ""),
    (r"当前约\s*\d+\s*行", ""),
    (r'信条[：:]\s*"[^"]*"', ""),
    (r"信条[：:]\s*['\u2018\u2019][^\u2018\u2019'\u201d\u201c]*['\u2018\u2019]", ""),
    (r"找到发动机.*标记油箱", ""),
    (r"简历上写的都是广告", ""),
    (r"需[a-zA-Z\u4e00-\u9fa5]*手动补充", ""),
    (r"待补充", ""),
    (r"需人工判[断定]", ""),
    (r"待主控确认", ""),
    (r"`([^`]+)`", r"\1"),           # 反引号去包围
    (r"~~(.+?)~~", r"\1"),           # 删除线去包围
]

# L2: 行级过滤（命中则整行跳过）
SKIP_LINE_KEYWORDS = [
    "搜索查询：",
    "搜索查询:",
    "搜索结果混杂",
    "全部是",
    "登录页面",
    "下游子代理",
    "上游",
    "步骤依赖",
    "等待 Step",
    "等待.*门禁验证",
]

# L3: URL 提取模式
URL_WITH_LABEL    = re.compile(r"\+\s*\[\s*来源\s*URL\s*\]\s*(https?://[^\s\)]+)", re.IGNORECASE)
URL_SQBRACKET     = re.compile(r"\[\s*来源[：:]?\s*\]\s*(https?://\S+)", re.IGNORECASE)
URL_SQBRACKET2    = re.compile(r"\[\s*来源(?:\d+)?\s*\]\s*(https?://[^\s\)]+)", re.IGNORECASE)
URL_BARE          = re.compile(r"(https?://[^\s\)\]]+)")


# ════════════════════════════════════════════════════════
# 核心清洗函数
# ════════════════════════════════════════════════════════

def sanitize(text: str, url_list: list) -> str:
    """清洗内部信息 + 提取 URL 到 url_list，保留 Markdown 语义"""
    lines = text.split("\n")
    clean_lines = []
    for line in lines:
        stripped = line.strip()

        # 空行保留（用于分段）
        if not stripped:
            clean_lines.append("")
            continue

        # L2: 行级过滤
        if any(kw in stripped for kw in SKIP_LINE_KEYWORDS):
            continue

        # L1: 正则替换
        for pattern, repl in DELETE_RULES:
            line = re.sub(pattern, repl, line, flags=re.IGNORECASE)

        # L3: URL 提取 → 脚注编号
        line = _extract_urls_to_footnotes(line, url_list)

        clean_lines.append(line)

    result = "\n".join(clean_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)  # 多行 → 双行
    return result.strip()


def _extract_urls_to_footnotes(text: str, url_list: list) -> str:
    """提取所有来源 URL，替换为 [来源N]"""

    def _register_url(url: str) -> str:
        url = url.strip()
        if url and url not in url_list and url.startswith("http"):
            url_list.append(url)
            return f"[来源{len(url_list)}]"
        elif url in url_list:
            return f"[来源{url_list.index(url) + 1}]"
        return url

    # 模式 1: + [来源URL] https://...
    def _sub_label(m):
        raw_url = m.group(1)
        return _register_url(raw_url)
    text = URL_WITH_LABEL.sub(_sub_label, text)

    # 模式 2: [来源] https://... / [来源:] https://...
    def _sub_sq(m):
        raw_url = m.group(1)
        return _register_url(raw_url)
    text = URL_SQBRACKET.sub(_sub_sq, text)
    text = URL_SQBRACKET2.sub(_sub_sq, text)

    # 模式 3: 裸 URL（不再匹配的部分，防止重复）
    def _sub_bare(m):
        raw_url = m.group(0)
        return _register_url(raw_url)
    text = URL_BARE.sub(_sub_bare, text)

    return text


# ════════════════════════════════════════════════════════
# Markdown → Word 段落
# ════════════════════════════════════════════════════════

def md_to_docx(doc, text: str, url_list: list):
    """将 Markdown 文本转为 Word 段落，保留加粗/标题/列表/表格"""
    cleaned = sanitize(text, url_list)
    lines = cleaned.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # ── 空行 ──
        if not line.strip():
            i += 1
            continue

        # ── Markdown table ──
        if line.strip().startswith("|"):
            table_lines = [line]
            while i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
                i += 1
                table_lines.append(lines[i])
            headers, rows = _parse_md_table(table_lines)
            if headers:
                _add_native_table(doc, headers, rows)
            else:
                for tl in table_lines:
                    p = doc.add_paragraph()
                    _add_formatted_text(p, tl)
            i += 1
            continue

        # ── 标题 ### ──
        m = re.match(r"^(#{1,3})\s+(.+)", line)
        if m:
            level = len(m.group(1))
            doc.add_heading(m.group(2).strip(), level=level)
            i += 1
            continue

        # ── 四级标题 #### ──
        m = re.match(r"^(#{4})\s+(.+)", line)
        if m:
            p = doc.add_paragraph()
            run = p.add_run(m.group(2).strip())
            run.bold = True
            run.font.size = doc.styles["Normal"].font.size
            i += 1
            continue

        # ── 列表项 ──
        if re.match(r"^[-*]\s+", line):
            li_text = re.sub(r"^[-*]\s+", "", line)
            p = doc.add_paragraph(style="List Bullet")
            _add_formatted_text(p, li_text)
            i += 1
            continue

        # ── 普通段落 ──
        p = doc.add_paragraph()
        _add_formatted_text(p, line)
        i += 1


def _add_formatted_text(p, text: str):
    """给 paragraph 加 **加粗** 解析"""
    parts = re.split(r"(\*\*.+?\*\*)", text)
    for part in parts:
        m = re.match(r"\*\*(.+?)\*\*", part)
        if m:
            run = p.add_run(m.group(1))
            run.bold = True
        else:
            p.add_run(part)


def _add_native_table(doc, headers: list, rows: list):
    """添加 Word 原生表格"""
    from docx.shared import Pt, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    table = doc.add_table(rows=len(rows) + 1, cols=len(headers))
    table.style = "Table Grid"

    # 表头
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = str(h)
        for para in cell.paragraphs:
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in para.runs:
                run.font.size = Pt(9)
                run.bold = True

    # 数据
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = table.rows[ri + 1].cells[ci]
            cell.text = str(val)
            for para in cell.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(9)

    doc.add_paragraph("")


def _parse_md_table(lines: list) -> tuple:
    """解析 Markdown pipe table → (headers, rows)"""
    headers = None
    rows = []

    for line in lines:
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if headers is None:
            # skip separator lines
            if all(c.startswith("-") or c.startswith(":") for c in cells):
                continue
            headers = cells
        else:
            if len(cells) == len(headers):
                rows.append(cells)
            else:
                break

    return (headers, rows) if headers else (None, [])


# ════════════════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════════════════

def _read_step(task_dir: Path, filename: str) -> str:
    fp = task_dir / filename
    return fp.read_text(encoding="utf-8") if fp.exists() else ""


def _extract_recommendation(step5_text: str) -> str:
    if not step5_text:
        return ""
    lower = step5_text.lower()
    if any(kw in lower for kw in ["不建议进入", "否决", "deal breaker"]):
        return "不建议进入下一轮尽调"
    if any(kw in lower for kw in ["有条件", "谨慎", "保留"]):
        return "有条件建议推进（需额外验证）"
    if any(kw in lower for kw in ["推荐", "建议推进", "值得"]):
        return "建议推进下一轮尽调"
    return "基于现有信息无法做出明确结论"


def _add_risks(doc, step1, step2, step3, step4, step5):
    """添加带风险分级的风险提示"""
    risk_levels = {"高": [], "中": [], "低": []}
    risk_keywords = ["风险", "隐患", "不确定性", "依赖", "挑战", "合规"]

    all_texts = [
        (step1, "商业模式"),
        (step2, "团队"),
        (step3, "技术"),
        (step4, "供应链"),
        (step5, "竞争"),
    ]

    seen = set()
    for raw, source in all_texts:
        if not raw:
            continue
        for line in raw.split("\n"):
            line = line.strip()
            if any(kw in line for kw in risk_keywords) and len(line) > 10:
                if line not in seen:
                    seen.add(line)
                    if any(kw in line for kw in ["Deal Breaker", "否决", "致命", "严重", "欺诈", "诉讼"]):
                        risk_levels["高"].append(line)
                    elif any(kw in line for kw in ["隐患", "存疑", "未验证", "谨慎"]):
                        risk_levels["中"].append(line)
                    else:
                        risk_levels["低"].append(line)

    if not any(risk_levels.values()):
        doc.add_paragraph("基于已有信息暂未发现重大风险。")
        return

    for level in ["高", "中", "低"]:
        items = risk_levels[level]
        if not items:
            continue
        p = doc.add_paragraph()
        run = p.add_run(f"【{level}风险】")
        run.bold = True
        for item in items:
            doc.add_paragraph(item, style="List Bullet")


# ════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════

def build_docx(task_id: str, output_path: str = None):
    try:
        from docx import Document
        from docx.shared import Pt, Inches
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        print("❌ python-docx 未安装，运行: pip install python-docx", file=sys.stderr)
        sys.exit(1)

    task_dir = TASKS_DIR / task_id

    # ── Step 0 profile ──
    profile = {}
    profile_path = task_dir / "bp_step0_profile.json"
    if profile_path.exists():
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)

    company    = profile.get("company_name", "目标公司")
    stage      = profile.get("stage", "")
    mfg_mode   = profile.get("manufacturing_mode", "")
    founders   = profile.get("founders", [])
    products   = profile.get("products", [])

    # ── 读取各 step（多文件名兼容） ──
    step1_raw = (
        _read_step(task_dir, "step1_moat_anchor.md")
        or _read_step(task_dir, "step1_founders_bgc.md")
    )
    step2_raw = (
        _read_step(task_dir, "step2_team_compliance.md")
        or _read_step(task_dir, "step2_tech_audit.md")
    )
    # step3: industry/competition or tech/product — try both
    step3_ind = (
        _read_step(task_dir, "step3_industry_competition.md")
        or _read_step(task_dir, "step3_tech_product.md")
    )
    step4_raw = (
        _read_step(task_dir, "step4_industry_supply.md")
        or _read_step(task_dir, "step4_supply_chain.md")
    )
    step5_raw = _read_step(task_dir, "step5_competition_conclusion.md")

    # ── URL 收集器 ──
    all_urls = []

    # ── 创建文档 ──
    doc = Document()

    # ── 标题页 ──
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title_para.add_run(company)
    run.font.size = Pt(22)
    run.bold = True

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run("商业尽职调查报告")
    run.font.size = Pt(16)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = meta.add_run(f"\n报告日期：{datetime.now().strftime('%Y年%m月%d日')}\n")
    run.font.size = Pt(10)
    if stage:
        run = meta.add_run(f"融资阶段：{stage}\n")
        run.font.size = Pt(10)
    if mfg_mode:
        run = meta.add_run(f"商业模式：{mfg_mode}\n")
        run.font.size = Pt(10)
    run = meta.add_run("\n机密文件 — 仅供内部使用")
    run.font.size = Pt(9)

    doc.add_page_break()

    # ── 一、执行摘要 ──
    doc.add_heading("一、执行摘要", level=1)
    deal_breakers  = re.findall(r"(?:Deal Breaker|交易否决项|否决项|关键风险)[：:\s]*([^\n]+)", step5_raw or "")
    recommendation = _extract_recommendation(step5_raw or "")

    p = doc.add_paragraph()
    _add_formatted_text(p, f"**{company}**")
    if stage:
        p = doc.add_paragraph(f"融资阶段：{stage} | 商业模式：{mfg_mode}")
    doc.add_paragraph("")

    if deal_breakers:
        p = doc.add_paragraph()
        _add_formatted_text(p, "关键风险：")
        for i, db in enumerate(deal_breakers[:3], 1):
            doc.add_paragraph(f"{i}. {db}", style="List Bullet")
        doc.add_paragraph("")

    p = doc.add_paragraph()
    _add_formatted_text(p, f"**建议：{recommendation}**")

    doc.add_page_break()

    # ── 二、公司概览 ──
    doc.add_heading("二、公司概览", level=1)
    if founders:
        doc.add_paragraph("创始人/核心团队：" + ", ".join(
            [f for f in founders if f not in ("未识别", "")]
        ))
    if products:
        doc.add_paragraph("主要产品：" + ", ".join(
            [p for p in products if p not in ("未识别", "")]
        ))
    if stage:
        doc.add_paragraph(f"融资阶段：{stage}")
    if mfg_mode:
        doc.add_paragraph(f"商业模式：{mfg_mode}")
    doc.add_paragraph("")
    doc.add_page_break()

    # ── 三、行业与市场环境 ──
    doc.add_heading("三、行业与市场环境", level=1)
    if step3_ind:
        md_to_docx(doc, step3_ind, all_urls)
    elif step4_raw:
        md_to_docx(doc, step4_raw, all_urls)
    else:
        doc.add_paragraph("（行业分析待补充）")
    doc.add_page_break()

    # ── 四、商业模式与护城河 ──
    doc.add_heading("四、商业模式与护城河", level=1)
    if step1_raw:
        md_to_docx(doc, step1_raw, all_urls)
    else:
        doc.add_paragraph("（商业模式分析待补充）")
    doc.add_page_break()

    # ── 五、团队评估 ──
    doc.add_heading("五、团队评估", level=1)
    if step2_raw:
        md_to_docx(doc, step2_raw, all_urls)
    else:
        doc.add_paragraph("（团队评估待补充）")
    doc.add_page_break()

    # ── 六、技术与产品 ──
    doc.add_heading("六、技术与产品", level=1)
    if step3_ind:
        md_to_docx(doc, step3_ind, all_urls)
    else:
        doc.add_paragraph("（技术与产品分析待补充）")
    doc.add_page_break()

    # ── 七、竞争格局 ──
    doc.add_heading("七、竞争格局", level=1)
    if step5_raw:
        md_to_docx(doc, step5_raw, all_urls)
    else:
        doc.add_paragraph("（竞争分析待补充）")
    doc.add_page_break()

    # ── 八、风险提示 ──
    doc.add_heading("八、风险提示", level=1)
    _add_risks(doc, step1_raw, step2_raw, step3_ind, step4_raw, step5_raw)
    doc.add_page_break()

    # ── 九、投资结论 ──
    doc.add_heading("九、投资结论", level=1)
    p = doc.add_paragraph()
    _add_formatted_text(p, f"**{recommendation}**")

    if deal_breakers:
        doc.add_paragraph("主要否决事项：")
        for db in deal_breakers:
            doc.add_paragraph(db, style="List Bullet")

    doc.add_page_break()

    # ── 免责声明 ──
    doc.add_heading("免责声明", level=1)
    doc.add_paragraph(
        "本报告仅供内部研究参考使用，不构成任何投资建议。"
        "报告中的信息来源于公开资料及 BP 原文，我们不对信息的完整性和准确性做出保证。"
        "投资决策需基于进一步的尽职调查和专业判断。"
        "本报告内容受保密义务约束，未经授权不得向第三方披露。"
    )

    # ── 附录：来源列表 ──
    if all_urls:
        doc.add_page_break()
        doc.add_heading("附录：来源列表", level=1)
        for i, url in enumerate(all_urls, 1):
            doc.add_paragraph(f"[{i}] {url}")

    # ── 保存 ──
    if not output_path:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_path = str(REPORTS_DIR / f"{company}_尽调报告_{date_str}.docx")

    doc.save(output_path)
    print(f"✅ DOCX 已生成: {output_path}")
    print(f"   来源: {len(all_urls)} 条")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="BP 尽调报告 DOCX 生成")
    parser.add_argument("--task-id", required=True, help="任务 ID")
    parser.add_argument("--output", help="输出文件路径（可选）")
    args = parser.parse_args()
    build_docx(args.task_id, args.output)


if __name__ == "__main__":
    main()
