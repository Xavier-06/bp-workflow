#!/usr/bin/env python3
"""
记忆系统去重 + 衰减 + 类型分类（v2）

4 种记忆类型（借鉴 Claude Code memdir taxonomy）：
  - user:       用户偏好、角色、目标、工作习惯
  - feedback:   正/负反馈、教训、"不要做 X"、"保持做 Y"
  - project:    项目决策、团队事实、进行中事项、非代码可推导的上下文
  - reference:  外部系统指针（哪里找数据、谁负责什么、链接）

用法：
  python3 scripts/memory_dedup.py add "内容" --category feedback --tags 教训,管线
  python3 scripts/memory_dedup.py add "内容" --type 今日事项          # 旧版兼容
  python3 scripts/memory_dedup.py check --file memory/2026-04-01.md
  python3 scripts/memory_dedup.py decay --days 30
  python3 scripts/memory_dedup.py dedup --file memory/2026-04-01.md
  python3 scripts/memory_dedup.py frontmatter --file memory/2026-04-01.md
  python3 scripts/memory_dedup.py tag add "内容标签" --file memory/2026-04-01.md

功能：
  1. add: 写入前先查旧条目，同主题更新旧条目，不追加重复
          自动附加 YAML frontmatter（如果文件还没有）
          同步写入 memory_bridge（向量 DB）
  2. check: 检查文件重复度 + frontmatter 状态
  3. decay: N天以上日志归档到 memory/archives/
  4. dedup: 原地去重
  5. frontmatter: 给已有日志补 frontmatter
  6. tag: 标签管理
"""
import argparse
import hashlib
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
MEMORY_DIR = WORKSPACE / 'memory'

# ── 4 种记忆类型 ──────────────────────────────────────────────
VALID_CATEGORIES = ('user', 'feedback', 'project', 'reference')

CATEGORY_HELP = {
    'user':       '用户偏好、角色、目标、工作习惯',
    'feedback':   '正/负反馈、教训、"不要做 X"、"保持做 Y"',
    'project':    '项目决策、团队事实、进行中事项',
    'reference':  '外部系统指针、链接、资源位置',
}

# 旧版 --type → 新版 category 映射
TYPE_TO_CATEGORY = {
    '今日事项': 'project',
    '重要决定': 'project',
    '学到的教训': 'feedback',
    '管线升级': 'project',
    '重要文件变更': 'reference',
    '待办': 'project',
}

# 默认标签模板
CATEGORY_DEFAULT_TAGS = {
    'user': ['偏好', '工作习惯'],
    'feedback': ['教训', '纠正'],
    'project': ['决策', '进展'],
    'reference': ['外部资源', '团队'],
}

# ── frontmatter 工具 ─────────────────────────────────────────
FM_RE_PATTERN = r'^---\n(.*?)\n---\n'
import re


def _parse_frontmatter(text):
    """解析 YAML frontmatter，返回 (meta_dict, body_text)"""
    m = re.match(FM_RE_PATTERN, text, re.DOTALL)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).split('\n'):
        if ':' in line:
            k, v = line.split(':', 1)
            v = v.strip()
            if v.startswith('[') and v.endswith(']'):
                v = [x.strip() for x in v[1:-1].split(',') if x.strip()]
            elif v.lower() in ('true', 'false'):
                v = v.lower() == 'true'
            meta[k.strip()] = v
    return meta, text[m.end():]


def _build_frontmatter(name, description, category, date, tags=None):
    """构建 frontmatter 块"""
    tags_line = ''
    if tags:
        tags_line = f'\ntags: [{", ".join(tags)}]'
    return f'---\nname: {name}\ndescription: {description}\ntype: {category}\ndate: {date}{tags_line}\n---\n'


def _has_frontmatter(text):
    return bool(re.match(FM_RE_PATTERN, text))


def _separate_fm_and_body(text):
    """返回 (preamble_with_dashes, body)。无 frontmatter 时 preamble 为空。"""
    if not _has_frontmatter(text):
        return '', text
    m = re.match(FM_RE_PATTERN, text, re.DOTALL)
    return text[:m.end()], text[m.end():]


# ── 向量 DB bridge ───────────────────────────────────────────
def _try_write_bridge(content, section, category=None):
    """尝试同步到向量 DB（失败不阻断文本写入）"""
    try:
        sys.path.insert(0, str(MEMORY_DIR.parent))
        from memory.memory_bridge import add_memory
        cat_map = {
            '今日事项': 'project',
            '重要决定': 'project',
            '学到的教训': 'feedback',
            '待办': 'project',
            'user': 'user',
            'feedback': 'feedback',
            'project': 'project',
            'reference': 'reference',
        }
        cat = category or cat_map.get(section, 'conversations')
        doc_id = add_memory(content, category=cat, metadata={'source': 'memory_dedup'})
        if doc_id:
            print(f'  🧠 bridge → {cat} [{doc_id[:8]}]')
        return True
    except Exception as e:
        print(f'  ⚠️ bridge 写入跳过: {e}')
        return False


# ── 文件读写 ──────────────────────────────────────────────────
def read_today_md(date_str=None):
    """读取指定日期日志"""
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')
    fp = MEMORY_DIR / f'{date_str}.md'
    if fp.exists():
        return fp, fp.read_text(encoding='utf-8')
    return fp, ''


def extract_sections(text):
    """按 ## 标题提取段落（跳过 frontmatter）"""
    _, body = _separate_fm_and_body(text)
    sections = []
    current = {'title': '', 'content': ''}
    for line in body.split('\n'):
        if line.startswith('## '):
            if current['title']:
                sections.append(current)
            current = {'title': line.strip(), 'content': ''}
        else:
            current['content'] += line + '\n'
    if current['title']:
        sections.append(current)
    return sections


def section_hash(content):
    return hashlib.md5(content.strip().encode()).hexdigest()


def dedup_and_write(text):
    """段落级去重：同标题块合并、行级去重。
    保留原有 frontmatter，返回完整文本字符串。"""
    preamble, body = _separate_fm_and_body(text)

    if not body.strip():
        return preamble + body

    header = ''
    if body.startswith('# '):
        first_line = body.split('\n')[0]
        header = first_line
        body = body[len(first_line):].lstrip('\n')

    sections = extract_sections(text)  # 内部已跳过 FM
    seen_titles = {}
    clean = []
    for sec in sections:
        t = sec['title']
        if t in seen_titles:
            old = seen_titles[t]
            old_lines = set(l.strip() for l in old['content'].split('\n'))
            for line in sec['content'].split('\n'):
                s = line.strip()
                if s and s not in old_lines:
                    old['content'] += '\n' + line
                    old_lines.add(s)
        else:
            seen_titles[t] = sec
            clean.append(sec)

    lines = []
    if header:
        lines.append(header)
        lines.append('')
    for sec in clean:
        lines.append(sec['title'])
        lines.append('')
        c = sec['content'].strip()
        if c:
            lines.append(c)
        lines.append('')

    body_out = '\n'.join(lines)
    return preamble + body_out


# ── 核心：添加内容 ────────────────────────────────────────────
def add_content(content, section, category=None, tags=None, date_str=None, file_path=None):
    """去重写入，自动附加 frontmatter（如果文件还没有），同步到向量 DB"""
    # ── 分类推断 ──
    if not category:
        category = TYPE_TO_CATEGORY.get(section)
    if not category:
        category = section if section in VALID_CATEGORIES else None
    if not category:
        category = 'project'

    if not tags:
        tags = CATEGORY_DEFAULT_TAGS.get(category, [])

    today = date_str or datetime.now().strftime('%Y-%m-%d')
    fp = Path(file_path) if file_path else MEMORY_DIR / f'{today}.md'

    text = fp.read_text(encoding='utf-8') if fp.exists() else ''

    sections = extract_sections(text)

    # 重复检测
    new_h = section_hash(content)
    for s in sections:
        if section_hash(s['content']) == new_h:
            print(f'⚠️ 内容已存在，跳过')
            return

    # 找到或创建目标 section
    target = next((s for s in sections if s['title'] == f'## {section}'), None)
    if target is None:
        sections.append({'title': f'## {section}', 'content': content})
    else:
        existing = target['content'].strip()
        target['content'] = (existing + '\n\n' + content) if existing else content

    # ── 确保文件有 frontmatter ──
    preamble, _ = _separate_fm_and_body(text)
    if not preamble:
        preamble = _build_frontmatter(
            name=f'{today} 记忆',
            description=f'{today} 投研记忆日志',
            category='project',
            date=today,
        )

    # ── 拼正文 ──
    header = ''
    body_after_fm = text[len(preamble):] if preamble else text
    if body_after_fm.startswith('# '):
        header = body_after_fm.split('\n')[0]
    else:
        # 从 sections 重建标题行
        pass  # header 已空，下面从零构建

    lines = []
    if header:
        lines.append(header)
        lines.append('')
    for s in sections:
        lines.append(s['title'])
        lines.append('')
        c = s['content'].strip()
        if c:
            lines.append(c)
        lines.append('')

    body_out = '\n'.join(lines)
    full = preamble + ('\n' if not preamble.endswith('\n\n') and header else '') + body_out
    full = dedup_and_write(full)

    fp.write_text(full, encoding='utf-8')
    print(f'✅ 写入 {fp} [section={section}, category={category}]')
    _try_write_bridge(content, section, category)


# ── 检查重复度 ────────────────────────────────────────────────
def check_file(file_path):
    """检查重复度 + frontmatter 状态"""
    fp = Path(file_path)
    if not fp.exists():
        print(f'❌ 不存在: {file_path}')
        return
    text = fp.read_text(encoding='utf-8')
    meta, body = _parse_frontmatter(text)

    fm_status = f'✅ {list(meta.keys())}' if meta else '⚠️ 无 frontmatter'
    print(f'📄 {file_path}')
    print(f'   Frontmatter: {fm_status}')

    sections = extract_sections(text)
    titles = [s['title'] for s in sections]
    dupes = len(titles) - len(set(titles))
    icon = '✅' if dupes == 0 else '🔴'
    print(f'   {icon} {len(sections)} sections, {dupes} dup title(s), {len(text)} chars')


# ── 衰减归档 ──────────────────────────────────────────────────
def decay(days=30):
    """N天以上日志归档到 memory/archives/"""
    archives = MEMORY_DIR / 'archives'
    archives.mkdir(parents=True, exist_ok=True)

    cutoff = datetime.now() - timedelta(days=days)
    archived = 0
    kept = 0

    for f in sorted(MEMORY_DIR.glob('????-??-??.md')):
        try:
            fd = datetime.strptime(f.stem, '%Y-%m-%d')
            if fd < cutoff:
                dest = archives / f.name
                if not dest.exists():
                    shutil.move(str(f), str(dest))
                    archived += 1
                else:
                    f.unlink()
                    archived += 1
            else:
                kept += 1
        except ValueError:
            kept += 1

    print(f'📦 归档 {archived} 个文件 (> {days}天) → {archives}')
    print(f'📂 保留 {kept} 个文件 (<= {days}天)')


# ── 原地去重 ──────────────────────────────────────────────────
def dedup_file(file_path):
    """原地去重"""
    fp = Path(file_path)
    if not fp.exists():
        print(f'❌ 不存在: {file_path}')
        return
    text = fp.read_text(encoding='utf-8')
    old = len(text)
    clean = dedup_and_write(text)
    fp.write_text(clean, encoding='utf-8')
    new = len(clean)
    print(f'🧹 {file_path}: {old} → {new} chars ({old - new} removed)')
    print(f'   {len(extract_sections(clean))} sections remaining')


# ── Frontmatter 补写 ──────────────────────────────────────────
def add_frontmatter(file_path):
    """给已有日志文件补 frontmatter（如果还没有）"""
    fp = Path(file_path)
    if not fp.exists():
        print(f'❌ 不存在: {file_path}')
        return
    text = fp.read_text(encoding='utf-8')

    if _has_frontmatter(text):
        meta, _ = _parse_frontmatter(text)
        print(f'✅ 已有 frontmatter:')
        for k, v in meta.items():
            print(f'   {k}: {v}')
        return

    date_str = fp.stem
    sections = extract_sections(text)
    type_counts = {}
    for s in sections:
        for old_type, new_cat in TYPE_TO_CATEGORY.items():
            if old_type in s['title']:
                type_counts[new_cat] = type_counts.get(new_cat, 0) + 1
    dominant = max(type_counts, key=type_counts.get) if type_counts else 'project'

    fm_block = _build_frontmatter(
        name=f'{date_str} 记忆',
        description=f'{date_str} 投研记忆日志',
        category=dominant,
        date=date_str,
    )
    fp.write_text(fm_block + text, encoding='utf-8')
    print(f'✅ 已添加 frontmatter→ {fp} [type={dominant}]')


# ── 标签管理 ──────────────────────────────────────────────────
def tag_operation(file_path, operation, tag_name=None):
    """标签添加/删除/列出"""
    fp = Path(file_path)
    if not fp.exists():
        print(f'❌ 不存在: {file_path}')
        return
    text = fp.read_text(encoding='utf-8')

    if not _has_frontmatter(text):
        print(f'⚠️ 无 frontmatter，先运行 frontmatter 命令')
        return

    meta, body = _parse_frontmatter(text)
    tags = meta.get('tags', [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(',') if t.strip()]

    if operation == 'add' and tag_name:
        if tag_name not in tags:
            tags.append(tag_name)
            print(f'✅ 添加标签: {tag_name}')
        else:
            print(f'⚠️ 标签已存在')
    elif operation == 'remove' and tag_name:
        if tag_name in tags:
            tags.remove(tag_name)
            print(f'✅ 移除标签: {tag_name}')
        else:
            print(f'⚠️ 标签不存在')
    elif operation == 'list':
        print(f'🏷️  当前标签: {", ".join(tags) if tags else "(无)"}')
        return

    fm_block = _build_frontmatter(
        meta.get('name', '记忆'),
        meta.get('description', ''),
        meta.get('type', 'project'),
        meta.get('date', ''),
        tags,
    )
    fp.write_text(fm_block + body, encoding='utf-8')


# ── CLI ──────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description='记忆系统去重 + 衰减 + 类型分类')
    sub = p.add_subparsers(dest='cmd')

    a = sub.add_parser('add', help='添加记忆内容')
    a.add_argument('content', help='记忆内容')
    a.add_argument('--type', default=None, help='旧版 section 名称（兼容）')
    a.add_argument('--category', choices=VALID_CATEGORIES, default=None,
                   help='记忆类型：user/feedback/project/reference')
    a.add_argument('--tags', default=None, help='标签，逗号分隔')
    a.add_argument('--file', help='指定文件路径')
    a.add_argument('--date', help='日期 YYYY-MM-DD')

    b = sub.add_parser('check', help='检查文件重复度 + frontmatter')
    b.add_argument('--file', required=True)

    c = sub.add_parser('decay', help='过期日志归档')
    c.add_argument('--days', type=int, default=30)

    d = sub.add_parser('dedup', help='原地去重')
    d.add_argument('--file', required=True)

    e = sub.add_parser('frontmatter', help='补写 frontmatter')
    e.add_argument('--file', required=True)

    f = sub.add_parser('tag', help='标签管理')
    f.add_argument('operation', choices=['add', 'remove', 'list'])
    f.add_argument('tag', nargs='?', default=None)
    f.add_argument('--file', required=True)

    args = p.parse_args()

    if args.cmd == 'add':
        tags = [t.strip() for t in args.tags.split(',')] if args.tags else None
        fp = args.file
        if not fp and args.date:
            fp = str(MEMORY_DIR / f'{args.date}.md')
        add_content(
            args.content,
            section=args.type or '今日事项',
            category=args.category,
            tags=tags,
            date_str=args.date,
            file_path=fp,
        )
    elif args.cmd == 'check':
        check_file(args.file)
    elif args.cmd == 'decay':
        decay(args.days)
    elif args.cmd == 'dedup':
        dedup_file(args.file)
    elif args.cmd == 'frontmatter':
        add_frontmatter(args.file)
    elif args.cmd == 'tag':
        tag_operation(args.file, args.operation, args.tag)
    else:
        p.print_help()


if __name__ == '__main__':
    main()

# ── 记忆年龄感知 ──────────────────────────────────────────────
def add_memory_age_note(content: str, topic_file: str = None, date_str: str = None) -> str:
    """
    自动在内容前注入新鲜度信息。
    topic_file 存在 → 用文件 mtime 算年龄
    否则 → 用 date_str（YYYY-MM-DD）算天数
    """
    sys.path.insert(0, str(MEMORY_DIR.parent / 'memory'))
    from memoryAge import memory_age_days, memory_age_str, freshness_warning
    
    age_text = ""
    warn_text = ""
    
    if topic_file and Path(topic_file).exists():
        mtime_ms = int(Path(topic_file).stat().st_mtime * 1000)
        age_text = f'📅 最后更新：{memory_age_str(mtime_ms)}'
        warn_text = freshness_warning(mtime_ms) or ''
    elif date_str:
        try:
            from datetime import datetime
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            age_ms = int(dt.timestamp() * 1000)
            age_text = f'📅 记录于：{memory_age_str(age_ms)}'
            warn_text = freshness_warning(age_ms) or ''
        except:
            pass
    
    if not age_text:
        return content
    
    result = f'{age_text}\n'
    if warn_text:
        result += warn_text + '\n'
    result += content
    return result

# ── Dream 互斥 + 门控 ─────────────────────────────────────────
# ── 3-1: mtime + PID 死锁自愈锁（对标 free-code consolidationLock.ts）──
import fcntl
import os

LOCK_FILE = MEMORY_DIR / '.dream_lock'
HOLDER_STALE_SECONDS = 3600  # 1 小时 stale（对标 free-code 的 HOLDER_STALE_MS）

_dream_lock_fds = []

def _read_lock_info():
    """读取锁文件信息，返回 (mtime_seconds_ago, holder_pid) 或 (None, None)"""
    try:
        mtime = LOCK_FILE.stat().st_mtime
        mtime_ago = int(__import__('time').time() - mtime)
        pid_text = LOCK_FILE.read_text().strip()
        holder_pid = int(pid_text) if pid_text.isdigit() else None
        return mtime_ago, holder_pid
    except (FileNotFoundError, ValueError):
        return None, None


def try_acquire_dream_lock() -> bool:
    """
    对标 free-code 的 tryAcquireConsolidationLock()：
    
    1. 检查锁文件 mtime，超过 1 小时 → stale
    2. 如果 stale，检查 PID 是否还活着
    3. PID 死了 → 自动 reclaim
    4. 抢锁成功 → 写 PID
    
    优势：
    - 进程 crash 不会永久锁死（死锁自愈）
    - 多重抢占时最后赢者正确
    """
    try:
        mtime_ago, holder_pid = _read_lock_info()
        
        # 锁存在且未 stale → 检查 PID
        if mtime_ago is not None and mtime_ago < HOLDER_STALE_SECONDS:
            if holder_pid is not None:
                try:
                    os.kill(holder_pid, 0)  # 检查进程是否存活
                    # PID 还活着 → 锁被占用
                    return False
                except OSError:
                    # PID 已死 → reclaim
                    pass
        
        # 没有锁 / stale / PID 死了 → 写新锁
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.write_text(str(os.getpid()))
        
        # 双重验证（防竞争）
        verify = LOCK_FILE.read_text().strip()
        if verify != str(os.getpid()):
            # 被别人抢先了
            return False
        
        return True
        
    except Exception:
        return False


def release_dream_lock():
    """释放 dream 锁"""
    while _dream_lock_fds:
        fd = _dream_lock_fds.pop()
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
        except:
            pass
    try:
        LOCK_FILE.unlink()
    except:
        pass

def check_dream_gates(min_hours: int = 24, min_sessions: int = 5) -> bool:
    """
    Dream 自动门控检查（对标 Claude Code autoDream.ts）
    
    需要同时满足：
    1. 时间门控：距离上次 dream ≥ min_hours
    2. 数量门控：≥ min_sessions 个新的 daily notes
    3. 锁保护：没有其他 dream 进程在运行
    """
    last_dream_file = MEMORY_DIR / '.last_dream'
    
    gate_order = []
    
    if not try_acquire_dream_lock():
        gate_order.append("❌ 门控 3/3: 锁已被占用（有其他 dream 进程在运行）")
        return False
    
    # 1. 时间门控
    if last_dream_file.exists():
        last_ts = datetime.fromisoformat(last_dream_file.read_text().strip())
        hours_since = (datetime.now() - last_ts).total_seconds() / 3600
        if hours_since < min_hours:
            release_dream_lock()
            gate_order.append(f"❌ 门控 1/3: 时间不足（{hours_since:.1f}h < {min_hours}h）")
            gate_order.append("   → Dream 跳过（门控未全开）")
            print('\n'.join(gate_order))
            return False
        gate_order.append(f"✅ 门控 1/3: 时间合格（{hours_since:.1f}h ≥ {min_hours}h）")
    else:
        gate_order.append("✅ 门控 1/3: 首次运行（无上次记录）")
    
    # 2. 数量门控
    daily_count = len(list(MEMORY_DIR.glob('????-??-??.md')))
    cutoff_date = datetime.now() - timedelta(days=min_hours / 24 + 1)
    recent_files = [f for f in MEMORY_DIR.glob('????-??-??.md')
                    if datetime.strptime(f.stem, '%Y-%m-%d') >= cutoff_date]
    
    if len(recent_files) < min_sessions:
        release_dream_lock()
        gate_order.append(f"❌ 门控 2/3: 新 session 不足（{len(recent_files)} < {min_sessions}）")
        gate_order.append("   → Dream 跳过（门控未全开）")
        print('\n'.join(gate_order))
        return False
    gate_order.append(f"✅ 门控 2/3: 新 session 合格（{len(recent_files)} ≥ {min_sessions}）")
    
    # 全部门控通过
    gate_order.append("✅ 门控 3/3: 锁已获取")
    gate_order.append("   → Dream 门控全开，可以运行")
    print('\n'.join(gate_order))
    return True

def record_dream_run():
    """记录本次 dream 执行时间"""
    (MEMORY_DIR / '.last_dream').write_text(datetime.now().isoformat())
    release_dream_lock()

# ── Compact 结构（借鉴 Claude Code compact/prompt.ts）──────────
def format_compact_summary(raw_summary: str) -> str:
    """
    格式化 compact 摘要：
    1. 剥离 <analysis> 草稿盘
    2. 提取 <summary> 内容并加标题
    3. 清理多余空白
    """
    import re
    
    # 剥离 analysis 草稿
    result = re.sub(r'<analysis>[\s\S]*?</analysis>', '', raw_summary)
    
    # 提取 summary 区块
    summary_match = re.search(r'<summary>([\s\S]*?)</summary>', result)
    if summary_match:
        content = summary_match.group(1).strip()
        result = f"## 压缩摘要\n\n{content}"
    else:
        result = f"## 压缩摘要\n\n{raw_summary.strip()}"
    
    # 清理多余换行
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()

def create_compact_instruction(section_type: str = 'full') -> str:
    """
    生成 compact 提示模板（对标 Claude Code 的 compact prompt）
    
    section_type:
      - 'full': 全量压缩
      - 'partial': 局部压缩（只压缩最近消息）
      - 'checkpoint': 断点续传前压缩
    """
    base = """在提供最终摘要之前，先用 <analysis> 标签包裹你的思考过程来组织思路。

思考流程：
1. 按时间顺序分析每条消息和段落
2. 识别：用户的明确请求、采用的方法、关键决策、技术概念
3. 注意具体细节：文件名、代码片段、函数签名、文件编辑
4. 记录遇到的错误及修复方法
5. 特别关注用户反馈，尤其是要求用不同方式处理的情况

然后提供 <summary> 区块，包含：
"""
    
    templates = {
        'full': """
1. 主要请求和意图：所有用户的显式请求
2. 关键技术概念：讨论的技术栈、框架、模式
3. 文件和代码段：检查/修改/创建的文件，附关键代码
4. 错误和修复：遇到的错误及解决方法
5. 问题解决：已解决的问题和正在排查的问题
6. 所有用户消息：非工具结果的用户消息
7. 待办任务：明确被要求处理的任务
8. 当前工作：请求前正在做什么（精确描述）
9. 下一步建议：与最近工作直接相关的下一步（附原文引用）

输出格式：
<analysis>
[你的思考过程]
</analysis>

<summary>
1. 主要请求和意图：...
2. 关键技术概念：...
3. 文件和代码段：...
4. 错误和修复：...
5. 问题解决：...
6. 所有用户消息：...
7. 待办任务：...
8. 当前工作：...
9. 下一步建议：...
</summary>
""",
        'partial': """（仅关注最近的消息。之前的上下文保持不变）
1. 最近的主要请求
2. 最近的错误和修复
3. 最近的用户消息
4. 当前工作
5. 下一步建议
""",
        'checkpoint': """（这份摘要将作为断点恢复的上下文）
1. 完成的步骤
2. 失败的步骤及原因
3. 待恢复的状态
4. 下一步操作
"""
    }
    
    return base + templates.get(section_type, templates['full'])

# ── Async Hook 生命周期管理 ───────────────────────────────────
import threading
import time

class AsyncHookRegistry:
    """
    异步 Hook 注册表（对标 Claude Code AsyncHookRegistry.ts）
    替代 fire-and-forget，提供完整的生命周期管理。
    """
    
    def __init__(self):
        self._hooks = {}
        self._locks = {}
        self._progress_intervals = {}
    
    def register(self, hook_id: str, hook_name: str, hook_event: str, 
                 timeout_ms: int = 15000, process_id: str = None,
                 command: str = None) -> bool:
        """
        注册异步 Hook，返回 True 如果注册成功。
        如果 hook_id 已存在且在运行中，返回 False（防重注册）。
        """
        if hook_id in self._hooks:
            existing = self._hooks[hook_id]
            if existing.get('status') == 'running':
                print(f'⚠️ Hook {hook_id} ({hook_name}) 已在运行中，跳过重复注册')
                return False
        
        self._hooks[hook_id] = {
            'hook_id': hook_id,
            'process_id': process_id or hook_id,
            'hook_name': hook_name,
            'hook_event': hook_event,
            'command': command or '',
            'timeout_ms': timeout_ms,
            'status': 'running',
            'start_time': time.time(),
            'response_sent': False,
            'retries': 0,
            'max_retries': 3,
        }
        
        # 启动进度计时器
        self._start_progress_interval(hook_id)
        print(f'▶️ Hook 注册: {hook_name} [{hook_event}] (超时 {timeout_ms}ms)')
        return True
    
    def _start_progress_interval(self, hook_id: str):
        """启动 hook 进度检查计时器"""
        def check_progress():
            hook = self._hooks.get(hook_id)
            if not hook or hook['status'] != 'running':
                return
            elapsed_ms = int((time.time() - hook['start_time']) * 1000)
            pct = min(100, int(elapsed_ms / hook['timeout_ms'] * 100))
            hook['progress_pct'] = pct
            remaining_ms = hook['timeout_ms'] - elapsed_ms
            if remaining_ms < 3000:
                print(f'⏳ Hook {hook["hook_name"]} 即将超时: {remaining_ms}ms 剩余')
        
        timer = threading.Timer(5.0, check_progress)
        timer.daemon = True
        timer.start()
        self._progress_intervals[hook_id] = timer
    
    def complete(self, hook_id: str, result: dict = None) -> bool:
        """标记 Hook 完成"""
        hook = self._hooks.get(hook_id)
        if not hook:
            print(f'⚠️ Hook {hook_id} 不存在')
            return False
        
        hook['status'] = 'completed'
        hook['end_time'] = time.time()
        hook['result'] = result
        duration_ms = int((hook['end_time'] - hook['start_time']) * 1000)
        
        self._stop_progress_interval(hook_id)
        print(f'✅ Hook 完成: {hook["hook_name"]} ({duration_ms}ms)')
        return True
    
    def fail(self, hook_id: str, error: str = None, auto_retry: bool = True) -> bool:
        """标记 Hook 失败，支持自动重试"""
        hook = self._hooks.get(hook_id)
        if not hook:
            print(f'⚠️ Hook {hook_id} 不存在')
            return False
        
        hook['retries'] += 1
        
        if auto_retry and hook['retries'] < hook['max_retries']:
            print(f'🔄 Hook {hook["hook_name"]} 失败，自动重试 {hook["retries"]}/{hook["max_retries"]}')
            hook['status'] = 'running'
            hook['start_time'] = time.time()
            return True
        
        hook['status'] = 'failed'
        hook['error'] = error
        hook['end_time'] = time.time()
        self._stop_progress_interval(hook_id)
        print(f'❌ Hook 失败: {hook["hook_name"]} ({error})')
        return False
    
    def _stop_progress_interval(self, hook_id: str):
        """停止 Hook 进度计时器"""
        timer = self._progress_intervals.pop(hook_id, None)
        if timer:
            timer.cancel()
    
    def get_status(self, hook_id: str) -> dict:
        """获取 Hook 状态"""
        hook = self._hooks.get(hook_id, {})
        if not hook:
            return {'status': 'not_found'}
        return {
            'status': hook.get('status'),
            'progress_pct': hook.get('progress_pct', 0),
            'elapsed_ms': int((time.time() - hook['start_time']) * 1000) if 'start_time' in hook else 0,
            'retries': hook.get('retries', 0),
            'result': hook.get('result'),
            'error': hook.get('error'),
        }
    
    def list_running(self) -> list:
        """列出所有运行中 Hook"""
        return [
            {'hook_id': hid, 'name': h['hook_name'], 'event': h['hook_event'],
             'status': h['status'], 'elapsed_ms': int((time.time() - h['start_time']) * 1000)}
            for hid, h in self._hooks.items()
            if h['status'] == 'running'
        ]

# 全局默认 registry
default_hook_registry = AsyncHookRegistry()

# ──────────────────────────────────────────────────────────────
# #1 两步骤写入：topic 文件 → MEMORY.md 索引更新
# ──────────────────────────────────────────────────────────────
import unicodedata
import re

MEMORY_INDEX = WORKSPACE / 'MEMORY.md'
MEMORY_INDEX_MAX_LINES = 200
MEMORY_INDEX_MAX_BYTES = 25_000

def slugify(text: str) -> str:
    """将中文标题转为安全文件名"""
    # 中文直接保留，空格/特殊字符替换为 -
    s = text.strip()
    s = re.sub(r'[^\w\u4e00-\u9fff\u3400-\u4dbf -]', '', s)
    s = re.sub(r'[\s/]+', '-', s)
    return s[:60]

def infer_memory_type(content: str) -> str:
    """
    根据内容推断四分类之一。
    规则引擎（关键词匹配）， fallback 到 project。
    """
    text = content.lower()
    
    # feedback 信号最强（教训/纠正/错误/教训类）
    feedback_signals = ['不要', '禁止', '教训', '纠正', '错误', '踩坑', '注意',
                        '别', '避免', '已修复', 'bug', '问题', '失败']
    if any(kw in text for kw in feedback_signals):
        return 'feedback'
    
    # user 类（偏好/习惯）
    user_signals = ['偏好', '喜欢', '习惯', '风格', ' Xavier', '用户', '工作方式',
                    '沟通', '讨厌', '偏好']
    if any(kw in text for kw in user_signals):
        return 'user'
    
    # reference 类（外部资源/链接/数据源）
    reference_signals = ['链接', 'url', 'http', '数据源', 'api key', '第三方',
                         '@', 'www', '://']
    if any(kw in text for kw in reference_signals):
        return 'reference'
    
    # default → project
    return 'project'

def map_topic_type(title: str) -> tuple[str, str]:
    """
    标题 → (topic_slug, memory_type)
    """
    mem_type = infer_memory_type(title)
    slug = slugify(title)
    # 如果 slug 太短或纯符号，用日期兜底
    if len(slug) < 2:
        slug = slugify(title[:30]) if len(title) > 3 else 'untitled'
    return f'{slug}.md', mem_type

def check_size_limits(index_path=None) -> bool:
    """
    检查 MEMORY.md 是否超限。
    返回 True 如果 OK，False 如果超限（会自动截断）
    """
    path = index_path or MEMORY_INDEX
    if not path.exists():
        return True
    
    text = path.read_text(encoding='utf-8')
    lines = text.split('\n')
    byte_count = len(text.encode('utf-8'))
    
    truncated = False
    reason = ""
    
    if len(lines) > MEMORY_INDEX_MAX_LINES:
        # 在最后一个完整 section 边界处截断
        cutoff = _find_section_cutoff(lines, MEMORY_INDEX_MAX_LINES)
        lines = lines[:cutoff]
        lines.append('')
        lines.append(f'> ⚠️ 索引文件被截断（{len(lines)} 行超过 {MEMORY_INDEX_MAX_LINES} 行限制）。')
        lines.append('> 请将详细内容移至 memory/topics/ 主题文件。')
        truncated = True
        reason = f'行数 {len(lines)} > {MEMORY_INDEX_MAX_LINES}'
    
    out_text = '\n'.join(lines)
    if len(out_text.encode('utf-8')) > MEMORY_INDEX_MAX_BYTES:
        # 按最后一个换行符截断
        out_text = out_text[:MEMORY_INDEX_MAX_BYTES]
        cut_at = out_text.rfind('\n')
        if cut_at > 0:
            out_text = out_text[:cut_at]
        out_text += '\n\n> ⚠️ 索引文件被截断（超过 25KB 限制）。请将详细内容移至主题文件。'
        truncated = True
        reason = f'大小 {byte_count}B > {MEMORY_INDEX_MAX_BYTES}B'
    
    if truncated:
        path.write_text(out_text, encoding='utf-8')
        print(f'⚠️ MEMORY.md 已截断（{reason}）')
        return False
    
    return True

def _find_section_cutoff(lines, max_lines):
    """在最后一个 section 标题（## 开头）处截断"""
    cutoff = max_lines
    for i in range(max_lines - 1, max(len(lines) // 2, 10), -1):
        if lines[i].startswith('## '):
            cutoff = i
            break
    return cutoff

def update_memory_index(topic_slug: str, title: str, category: str, memory_index=None):
    """
    两步骤写入的第二步：更新 MEMORY.md 索引。
    1. 找到对应 category 的 section
    2. 检查指针是否已存在（去重）
    3. 如果不存在，添加新指针行
    4. 检查大小限制
    """
    path = memory_index or MEMORY_INDEX
    if not path.exists():
        return
    
    text = path.read_text(encoding='utf-8')
    link_pattern = f'({topic_slug})'
    
    # 已存在 → 跳过（去重）
    if link_pattern in text:
        return
    
    # 找到目标 section（category 区块）
    section_markers = {
        'user': '## User',
        'feedback': '## Feedback',
        'project': '## Project',
        'reference': '## Reference',
    }
    marker = section_markers.get(category, '## Project')
    
    lines = text.split('\n')
    insert_idx = None
    for i, line in enumerate(lines):
        if marker in line:
            # 找到该 section 的最后一个表格行（以 | 开头）或空行
            for j in range(i + 1, len(lines)):
                if lines[j].startswith('|') or lines[j].startswith('|-'):
                    insert_idx = j + 1
                elif lines[j].startswith('## ') or lines[j].startswith('---'):
                    break
            
            if insert_idx is None:
                # 没找到表格，在 section marker 后面插入
                insert_idx = i + 1
            break
    
    if insert_idx is None:
        # 没找到任何 section，在文件末尾插入
        insert_idx = len(lines) - 1
    
    # 构建新指针行
    new_line = f'- [{title}](memory/topics/{topic_slug})   {category}'
    lines.insert(insert_idx, new_line)
    
    path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'📌 索引更新: [{title}] → memory/topics/{topic_slug}')
    
    # 检查大小限制
    check_size_limits(path)

def add_topic(content: str, section: str, category=None, tags=None, date_str=None):
    """
    两步骤写入入口函数。
    
    步骤 1: 内容写入 memory/topics/{slug}.md
    步骤 2: 自动更新 MEMORY.md 索引
    
    用法：
        add_topic("Claude Code 升级：TaskRegistry + Hook 系统集成完成", 
                  "Claude Code 升级", 
                  category="project")
    """
    if not category:
        category = infer_memory_type(content)
        category = category or TYPE_TO_CATEGORY.get(section, 'project')
    
    topic_slug, _ = map_topic_type(section or content[:20])
    topic_path = TOPICS_DIR / topic_slug
    
    title = section or content[:30]
    
    if not tags:
        tags = CATEGORY_DEFAULT_TAGS.get(category, [])
    
    # ── Step 1: 写入/更新 topic 文件 ──────────────────────
    now = datetime.now().strftime('%Y-%m-%d')
    
    if topic_path.exists():
        text = topic_path.read_text(encoding='utf-8')
        meta, body = _parse_frontmatter(text)
        
        # 更新 frontmatter 的 last_updated
        meta['last_updated'] = now
        
        # 去重：同内容不追加
        if content.strip() in body:
            print(f'⚠️ 内容已在 {topic_slug} 中，跳过')
            _try_write_bridge(content, section, category)
            return
        
        # 在 body 前添加新内容
        sections_before = extract_sections('## ' + section + '\n' + body)
        target = next((s for s in sections_before if s['title'] == f'## {section}'), None)
        if target:
            existing = target['content'].strip()
            target['content'] = f'*{now}*\n\n- {content}\n\n{existing}'
        else:
            sections_before.insert(0, {'title': f'## {section}', 'content': f'*{now}*\n\n- {content}'})
        
        new_body_lines = []
        for s in sections_before:
            new_body_lines.append(s['title'])
            new_body_lines.append('')
            new_body_lines.append(s['content'].strip())
            new_body_lines.append('')
        
        new_body = '\n'.join(new_body_lines)
        preamble = _build_frontmatter(
            meta.get('name', title),
            meta.get('description', ''),
            meta.get('type', category),
            now,
            tags,
        )
        full = preamble + '\n' + new_body
        
    else:
        # 新建 topic 文件
        preamble = _build_frontmatter(
            name=title,
            description=f'{category} 记忆 — {title}',
            category=category,
            date=now,
            tags=tags,
        )
        full = preamble + '\n'
        full += f'# {title} — 主题记忆\n\n'
        full += f'## 最新进展\n\n*{now}*\n\n'
        full += f'- {content}\n\n'
        full += '## 详细记录\n\n*暂无*\n'
    
    topic_path.parent.mkdir(parents=True, exist_ok=True)
    topic_path.write_text(full, encoding='utf-8')
    print(f'✅ 主题写入: memory/topics/{topic_slug} [category={category}]')
    
    # ── Step 2: 更新 MEMORY.md 索引 ──────────────────────
    update_memory_index(topic_slug, title, category)
    
    # ── Sync: 向量 DB ────────────────────────────────────
    _try_write_bridge(content, section, category)


# 全局常量
TOPICS_DIR = MEMORY_DIR / 'topics'
