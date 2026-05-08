#!/usr/bin/env python3
"""
Check IRBP skill/instruction-store consistency.

Verifies:
  1. Every SKILL.md references/*/instruction_store file exists
  2. Every instruction_store index.json entry has a valid .md file
  3. No duplicate "golden snippets" outside their allowed locations
  4. No SKILL.md exceeds 200 lines (progressive disclosure threshold)
  5. All cross-skill references resolve

Exit 0 if clean, 1 otherwise.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"

errors: list[str] = []
warnings: list[str] = []
checked = 0


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


# --- 1. SKILL.md reference resolution ---
print("1. Checking SKILL.md reference files...")
for skill_dir in sorted(SKILLS.iterdir()):
    if not skill_dir.is_dir():
        continue
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        continue
    checked += 1
    refs_dir = skill_dir / "references"
    if not refs_dir.is_dir():
        warn(f"{rel(skill_md)}: no references/ directory (OK for simple skills)")
        continue
    # Check reference files mentioned in SKILL.md
    text = skill_md.read_text()

    # Cross-skill references first: ../other-skill/references/xxx.md
    cross_skill_refs = set()
    for m in re.finditer(r'\.\.\/([\w\-]+)\/references\/([\w\-]+\.md)', text):
        other_skill = m.group(1)
        ref_name = m.group(2)
        cross_skill_refs.add(ref_name)
        other_path = SKILLS / other_skill / "references" / ref_name
        if not other_path.is_file():
            err(f"{rel(skill_md)}: ../{other_skill}/references/{ref_name} referenced but not found")
        else:
            checked += 1

    # Same-skill references: references/xxx.md (skip ones that are part of cross-skill paths)
    for m in re.finditer(r'(?<!/)references/([\w\-]+\.md)', text):
        ref_name = m.group(1)
        # Skip if this ref name already handled as cross-skill
        if ref_name in cross_skill_refs:
            continue
        ref_path = refs_dir / ref_name
        if not ref_path.is_file():
            err(f"{rel(skill_md)}: references/{ref_name} referenced but not found")
        else:
            checked += 1


# --- 2. Instruction store index.json validation ---
print("2. Checking instruction_store index.json...")
for store_dir in sorted(ROOT.glob("instruction_store_*")):
    idx = store_dir / "index.json"
    if not idx.is_file():
        warn(f"{rel(store_dir)}: no index.json")
        continue
    checked += 1
    try:
        data = json.loads(idx.read_text())
    except json.JSONDecodeError as e:
        err(f"{rel(idx)}: JSON parse error: {e}")
        continue
    for role in data.get("roles", []):
        checked += 1
        role_file = store_dir / role.get("file", "")
        if not role_file.is_file():
            err(f"{rel(idx)}: role '{role.get('key')}' -> {role.get('file')} not found")


# --- 3. Golden snippet duplicate detection ---
print("3. Checking golden snippet duplicates...")

GOLDEN_SNIPPETS = {
    "bp_ocr_config": {
        "pattern": r"qwen3-vl-30b-a3b-instruct",
        "description": "BP OCR model config",
        "allowed_in": [
            "skills/ir-researcher/references/bp-ocr-config.md",
        ],
        "allowed_mention": [
            # SKILL.md may have a pointer like "read references/bp-ocr-config.md"
            # but should not contain the actual config values
        ],
    },
    "bp_anti_defect": {
        "pattern": r"技术路线不可强行绑定",
        "description": "BP anti-defect rules",
        "allowed_in": [
            "skills/ir-reporter/references/bp-anti-defect-rules.md",
            "instruction_store_bp/bp_技术与产品.md",
            "instruction_store_bp/bp_统稿.md",
        ],
        "allowed_mention": [],
    },
    "delivery_protocol": {
        "pattern": r"longshao_notify\.py",
        "description": "WeChat delivery protocol",
        "allowed_in": [
            "skills/ir-reporter/references/delivery-protocol.md",
            "skills/ir-coordinator/references/ir-pipeline.md",
            "skills/ir-coordinator/references/bp-pipeline.md",
        ],
        "allowed_mention": [],
    },
}

# Collect all checkable files
checkable_files: list[Path] = []
for p in sorted(ROOT.rglob("*.md")):
    # Skip .git, node_modules
    if ".git" in p.parts or "node_modules" in p.parts:
        continue
    # Only check skills/ and instruction_store_*
    rel_str = rel(p)
    if rel_str.startswith("skills/") or rel_str.startswith("instruction_store_"):
        checkable_files.append(p)

for snippet_name, snippet_def in GOLDEN_SNIPPETS.items():
    pattern = snippet_def["pattern"]
    allowed = set(snippet_def["allowed_in"])
    for f in checkable_files:
        rel_str = rel(f)
        text = f.read_text()
        if re.search(pattern, text):
            if rel_str not in allowed:
                err(
                    f"golden-snippet [{snippet_name}]: pattern found in {rel_str} "
                    f"(allowed only in: {', '.join(sorted(allowed))})"
                )


# --- 4. SKILL.md size check ---
print("4. Checking SKILL.md sizes...")
SIZE_LIMIT = 200  # lines
for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
    checked += 1
    lines = skill_md.read_text().count("\n")
    if lines > SIZE_LIMIT:
        warn(f"{rel(skill_md)}: {lines} lines (limit: {SIZE_LIMIT})")
    else:
        pass  # OK


# --- 5. Orphan reference files ---
print("5. Checking for orphan reference files...")
for refs_dir in sorted(SKILLS.glob("*/references")):
    if not refs_dir.is_dir():
        continue
    for ref_file in sorted(refs_dir.glob("*.md")):
        checked += 1
        skill_md = refs_dir.parent / "SKILL.md"
        if not skill_md.is_file():
            continue
        text = skill_md.read_text()
        if ref_file.name not in text:
            warn(f"{rel(ref_file)}: exists but not referenced in {rel(skill_md)}")


# --- Report ---
print()
if warnings:
    print(f"WARN — {len(warnings)} warning(s):", file=sys.stderr)
    for w in warnings:
        print(f"  ⚠ {w}", file=sys.stderr)
    print()

if errors:
    print(f"FAIL — {len(errors)} issue(s) across {checked} check(s):\n", file=sys.stderr)
    for e in errors:
        print(f"  ✗ {e}", file=sys.stderr)
    sys.exit(1)

print(f"OK — {checked} check(s) passed, {len(warnings)} warning(s).")
