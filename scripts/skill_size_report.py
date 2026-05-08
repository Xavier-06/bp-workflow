#!/usr/bin/env python3
"""
IRBP skill size report — context usage estimation.

Reports:
  1. File sizes for all SKILL.md and references/
  2. Simulated context load per execution path
  3. Files exceeding the 500-line threshold

Usage: python3 scripts/skill_size_report.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"

SIZE_LIMIT_LINES = 200  # Progressive disclosure target for SKILL.md
REFERENCE_LIMIT_LINES = 500  # Anthropic's threshold for reference files


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT / "skills"))
    except ValueError:
        return str(p.relative_to(ROOT))


def file_stats(p: Path) -> tuple[int, int]:
    """Return (lines, bytes) for a file."""
    text = p.read_text()
    return text.count("\n") + 1, len(text.encode("utf-8"))


print("=" * 70)
print("IRBP SKILL SIZE REPORT")
print("=" * 70)

# --- 1. Per-file stats ---
print("\n📦 File sizes:")
print(f"{'File':<50} {'Lines':>6} {'Bytes':>8} {'Status':>8}")
print("-" * 74)

total_lines = 0
total_bytes = 0
skill_lines = 0
skill_bytes = 0
ref_lines = 0
ref_bytes = 0

for skill_dir in sorted(SKILLS.iterdir()):
    if not skill_dir.is_dir():
        continue
    skill_md = skill_dir / "SKILL.md"
    if skill_md.is_file():
        lines, bts = file_stats(skill_md)
        total_lines += lines
        total_bytes += bts
        skill_lines += lines
        skill_bytes += bts
        status = "✓" if lines <= SIZE_LIMIT_LINES else f"⚠ >{SIZE_LIMIT_LINES}"
        print(f"  {rel(skill_md):<48} {lines:>6} {bts:>8} {status:>8}")

    refs_dir = skill_dir / "references"
    if refs_dir.is_dir():
        for ref_file in sorted(refs_dir.glob("*.md")):
            lines, bts = file_stats(ref_file)
            total_lines += lines
            total_bytes += bts
            ref_lines += lines
            ref_bytes += bts
            status = "✓" if lines <= REFERENCE_LIMIT_LINES else f"⚠ >{REFERENCE_LIMIT_LINES}"
            print(f"    {rel(ref_file):<46} {lines:>6} {bts:>8} {status:>8}")

print("-" * 74)
print(f"  {'TOTAL':<50} {total_lines:>6} {total_bytes:>8}")
print(f"  {'SKILL.md only':<50} {skill_lines:>6} {skill_bytes:>8}")
print(f"  {'references/ only':<50} {ref_lines:>6} {ref_bytes:>8}")

# --- 2. Simulated context per execution path ---
print("\n📊 Simulated context per execution path:")
print("-" * 74)

# Define execution paths and what they load
paths = {
    "IR: coordinator triggers": [
        "ir-coordinator/SKILL.md",
        "ir-coordinator/references/ir-pipeline.md",
        "ir-coordinator/references/quality-gates.md",
    ],
    "BP: coordinator triggers": [
        "ir-coordinator/SKILL.md",
        "ir-coordinator/references/bp-pipeline.md",
        "ir-coordinator/references/quality-gates.md",
    ],
    "IR: researcher executes step": [
        "ir-researcher/SKILL.md",
        "ir-researcher/references/data-sources.md",
    ],
    "BP: researcher executes dimension": [
        "ir-researcher/SKILL.md",
        "ir-researcher/references/data-sources.md",
        "ir-researcher/references/bp-ocr-config.md",
        "ir-researcher/references/bp-gap-detection.md",
    ],
    "IR: reporter writes report": [
        "ir-reporter/SKILL.md",
        "ir-reporter/references/ir-writing-standards.md",
        "ir-reporter/references/delivery-protocol.md",
    ],
    "BP: reporter writes report": [
        "ir-reporter/SKILL.md",
        "ir-reporter/references/bp-anti-defect-rules.md",
        "ir-reporter/references/delivery-protocol.md",
    ],
    "IR: verifier validates": [
        "ir-verifier/SKILL.md",
        "ir-verifier/references/ir-adversarial-strategies.md",
    ],
    "BP: verifier validates": [
        "ir-verifier/SKILL.md",
        "ir-verifier/references/bp-adversarial-strategies.md",
    ],
}

for path_name, files in paths.items():
    path_lines = 0
    path_bytes = 0
    for f in files:
        full_path = SKILLS / f
        if full_path.is_file():
            l, b = file_stats(full_path)
            path_lines += l
            path_bytes += b
    kb = path_bytes / 1024
    print(f"  {path_name:<40} {path_lines:>5} lines  {kb:>6.1f} KB")

# --- 3. Comparison with old structure ---
print("\n📈 Before vs After (SKILL.md only, always-loaded context):")
print("-" * 74)

# Old sizes (from analysis)
old_sizes = {
    "ir-coordinator/SKILL.md": (418, 22281),
    "ir-researcher/SKILL.md": (159, 6230),
    "ir-reporter/SKILL.md": (168, 7213),
    "ir-verifier/SKILL.md": (108, 4406),
}

print(f"  {'File':<40} {'Old Lines':>10} {'New Lines':>10} {'Saved':>8}")
print("-" * 74)
for skill_dir in sorted(SKILLS.iterdir()):
    if not skill_dir.is_dir():
        continue
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        continue
    new_lines, new_bytes = file_stats(skill_md)
    name = f"{skill_dir.name}/SKILL.md"
    old_lines, old_bytes = old_sizes.get(name, (0, 0))
    if old_lines > 0:
        saved = f"{(1 - new_lines/old_lines)*100:.0f}%"
        print(f"  {name:<40} {old_lines:>10} {new_lines:>10} {saved:>8}")

print()
print("💡 Key insight: SKILL.md (always-loaded) shrinks significantly.")
print("   Reference files are loaded only when needed, saving context")
print("   when running a single pipeline (IR or BP, not both).")
