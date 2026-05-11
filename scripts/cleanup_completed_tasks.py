#!/usr/bin/env python3
"""
cleanup_completed_tasks.py - Clean up subagent sessions for completed tasks

1. Parses sessions.json to find sessions with TASK-XXX labels
2. Removes those whose task ID is marked as ✅ completed in tasks.md
3. Also removes orphan entries (sessionFile doesn't exist)
"""

import json
import re
from pathlib import Path

SESSIONS_JSON = Path(__file__).resolve().parent.parent / "data" / "sessions.json"
TASKS_FILE = Path(__file__).resolve().parent.parent / "data" / "tasks.md"

def get_completed_tasks():
    """Extract completed task IDs from tasks.md"""
    if not TASKS_FILE.exists():
        print(f"⚠️  Tasks file not found: {TASKS_FILE}")
        return set()
    
    content = TASKS_FILE.read_text()
    matches = re.findall(r'\[(TASK-[0-9-]+)\].*?✅', content)
    return set(matches)

def extract_task_id(label):
    """Extract base task ID from label"""
    match = re.search(r'(TASK-\d{8}-\d+)(?:-|$)', label)
    return match.group(1) if match else None

def main():
    print("🧹 Cleaning up sessions for completed tasks...")
    print()
    
    completed_tasks = get_completed_tasks()
    if not completed_tasks:
        print("⚠️  No completed TASK-XXX tasks found in tasks.md")
        print("✅ Nothing to clean up")
        return
    
    print("📋 Found completed tasks:")
    for task in sorted(completed_tasks):
        print(f"   - {task}")
    print()
    
    if not SESSIONS_JSON.exists():
        print(f"⚠️  Sessions file not found: {SESSIONS_JSON}")
        return
    
    with open(SESSIONS_JSON, 'r', encoding='utf-8') as f:
        sessions_data = json.load(f)
    
    print(f"📊 sessions.json entries before: {len(sessions_data)}")
    
    # Find sessions to delete
    keys_to_delete = set()
    
    for session_key, session_info in sessions_data.items():
        label = session_info.get('label', '')
        
        # Check if this is a completed task
        if label:
            task_id = extract_task_id(label)
            if task_id and task_id in completed_tasks:
                keys_to_delete.add(session_key)
                continue
        
        # Check if session file exists (orphan cleanup)
        session_file = session_info.get('sessionFile')
        if session_file and not Path(session_file).exists():
            keys_to_delete.add(session_key)
    
    print(f"🎯 Found {len(keys_to_delete)} entries to delete")
    print()
    
    # Delete session files
    deleted_files = 0
    for session_key in list(keys_to_delete):
        session_info = sessions_data[session_key]
        session_file = session_info.get('sessionFile')
        if session_file:
            p = Path(session_file)
            if p.exists():
                p.unlink()
                meta_file = p.with_suffix('.meta.json')
                if meta_file.exists():
                    meta_file.unlink()
                deleted_files += 1
    
    print(f"🗑️  Deleted {deleted_files} session files")
    
    # Remove entries from sessions.json
    for key in keys_to_delete:
        del sessions_data[key]
    
    # Write back
    with open(SESSIONS_JSON, 'w', encoding='utf-8') as f:
        json.dump(sessions_data, f, indent=2, ensure_ascii=False)
    
    print(f"📊 sessions.json entries after: {len(sessions_data)}")
    print()
    print("✅ Cleanup complete!")

if __name__ == "__main__":
    main()
