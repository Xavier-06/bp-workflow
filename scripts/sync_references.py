#!/usr/bin/env python3
"""
Sync and validate IRBP skill references.

Validates:
  1. All SKILL.md reference paths resolve to existing files
  2. All instruction_store index.json entries have valid .md files
  3. Cross-skill references are valid

Optional --fix mode:
  - Creates skeleton reference files for missing references

Usage:
  python3 scripts/sync_references.py          # validate only
  python3 scripts/sync_references.py --fix    # validate + create missing skeletons
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"

fix_mode = "--fix" in sys.argv

errors: list[str] = []
created: list[str] = []
checked = 0


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


print(f"Running in {'FIX' if fix_mode else 'CHECK'} mode")

# --- 1. Resolve SKILL.md references ---
print("\n1. Resolving SKILL.md references...")
for skill_dir in sorted(SKILLS.iterdir()):
    if not skill_dir.is_dir():
        continue
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        continue
    checked += 1
    text = skill_md.read_text()

    # Cross-skill references first: collect their ref names to avoid double-checking
    cross_skill_refs = set()
    for m in re.finditer(r'\.\.\/([\w\-]+)\/references\/([\w\-]+\.md)', text):
        other_skill = m.group(1)
        ref_name = m.group(2)
        cross_skill_refs.add(ref_name)
        other_path = SKILLS / other_skill / "references" / ref_name
        if not other_path.is_file():
            msg = f"{rel(skill_md)}: ../{other_skill}/references/{ref_name} not found"
            if fix_mode:
                other_path.parent.mkdir(parents=True, exist_ok=True)
                other_path.write_text(f"# {ref_name.replace('.md', '')}\n\nTODO: populate this reference file\n")
                created.append(f"Created skeleton: {rel(other_path)}")
                print(f"  + {rel(other_path)} (skeleton)")
            else:
                errors.append(msg)
                print(f"  ✗ {msg}")
        else:
            print(f"  ✓ ../{other_skill}/references/{ref_name}")

    # Same-skill references: skip ones already handled as cross-skill
    for m in re.finditer(r'(?<!/)references/([\w\-]+\.md)', text):
        ref_name = m.group(1)
        if ref_name in cross_skill_refs:
            continue
        ref_path = skill_dir / "references" / ref_name
        if not ref_path.is_file():
            msg = f"{rel(skill_md)}: references/{ref_name} not found"
            if fix_mode:
                ref_path.parent.mkdir(parents=True, exist_ok=True)
                ref_path.write_text(f"# {ref_name.replace('.md', '')}\n\nTODO: populate this reference file\n")
                created.append(f"Created skeleton: {rel(ref_path)}")
                print(f"  + {rel(ref_path)} (skeleton)")
            else:
                errors.append(msg)
                print(f"  ✗ {msg}")
        else:
            print(f"  ✓ references/{ref_name}")


# --- 2. Validate instruction_store ---
print("\n2. Validating instruction_store...")
for store_dir in sorted(ROOT.glob("instruction_store_*")):
    idx = store_dir / "index.json"
    if not idx.is_file():
        print(f"  ⚠ {rel(store_dir)}: no index.json")
        continue
    checked += 1
    data = json.loads(idx.read_text())
    for role in data.get("roles", []):
        checked += 1
        role_file = store_dir / role.get("file", "")
        if role_file.is_file():
            print(f"  ✓ {role.get('key')} → {role.get('file')}")
        else:
            errors.append(f"{rel(idx)}: role '{role.get('key')}' -> {role.get('file')} not found")
            print(f"  ✗ {role.get('key')} → {role.get('file')} NOT FOUND")


# --- Report ---
print()
if created:
    print(f"CREATED — {len(created)} skeleton file(s):")
    for c in created:
        print(f"  + {c}")

if errors:
    print(f"\nFAIL — {len(errors)} issue(s):")
    for e in errors:
        print(f"  ✗ {e}")
    if not fix_mode:
        print("\nTip: run with --fix to create skeleton files for missing references")
    sys.exit(1)

print(f"\nOK — {checked} reference(s) validated, 0 issues.")
