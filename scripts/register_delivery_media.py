#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import time
import uuid
from pathlib import Path

WB_GLOBAL = Path.home() / "Library" / "Application Support" / "WorkBuddy" / "User" / "globalStorage" / "tencent-cloud.coding-copilot"
MEDIA_INDEX_DIR = WB_GLOBAL / "media-index"
MSG_QUEUE_DIR = WB_GLOBAL / "message-queue"


def _guess_content_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime == "text/markdown":
        return "document"
    if mime and mime.startswith("application/vnd.openxmlformats-officedocument"):
        return "document"
    if mime == "application/pdf":
        return "document"
    return "document"


def register_media(file_path: str, session_id: str) -> dict:
    p = Path(file_path).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"file not found: {p}")

    MEDIA_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    index_path = MEDIA_INDEX_DIR / f"{session_id}.json"

    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            data = {"version": 1, "lastUpdated": 0, "records": {}}
    else:
        data = {"version": 1, "lastUpdated": 0, "records": {}}

    now_ms = int(time.time() * 1000)
    mime, _ = mimetypes.guess_type(str(p))
    mime = mime or "application/octet-stream"
    record = {
        "uri": p.as_uri(),
        "filePath": str(p),
        "fileName": p.name,
        "mimeType": mime,
        "size": p.stat().st_size,
        "contentType": _guess_content_type(p),
        "timestamp": now_ms,
        "sessionId": session_id,
    }

    data["lastUpdated"] = now_ms
    data.setdefault("records", {})[str(p)] = record
    index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "index": str(index_path), "record": record}


def attach_message(text: str, file_path: str, session_id: str, model: str = "glm-5.1", mode: str = "craft") -> dict:
    register_media(file_path, session_id)

    MSG_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    now_ms = int(time.time() * 1000)
    msg_id = f"mq-{now_ms}-{uuid.uuid4().hex[:6]}"
    queue_path = MSG_QUEUE_DIR / f"{uuid.uuid4().hex[:16]}.json"

    file_uri = Path(file_path).expanduser().resolve().as_uri()
    preview = f"{text}\n\n📎 文档: {Path(file_path).name}"
    payload = {
        "version": 2,
        "lastUpdated": now_ms,
        "conversations": {
            session_id: {
                "version": 2,
                "conversationId": session_id,
                "updatedAt": now_ms,
                "runtime": {
                    "activated": True,
                    "paused": False,
                    "awaitingSessionIdle": False,
                    "updatedAt": now_ms,
                },
                "items": [
                    {
                        "id": msg_id,
                        "conversationId": session_id,
                        "contentBlocks": [
                            {
                                "type": "text",
                                "text": preview,
                                "_meta": {"codebuddy.ai": {"mode": mode, "model": model}},
                            }
                        ],
                        "attachments": [
                            {
                                "kind": "media-index-ref",
                                "uri": file_uri,
                                "fileName": Path(file_path).name,
                                "mimeType": mimetypes.guess_type(file_path)[0] or "application/octet-stream",
                                "contentType": _guess_content_type(Path(file_path)),
                                "sessionId": session_id,
                            }
                        ],
                        "previewText": preview[:100],
                        "status": "pending",
                        "order": 0,
                        "createdAt": now_ms,
                        "updatedAt": now_ms,
                        "modeId": mode,
                        "modelId": model,
                    }
                ],
            }
        },
    }
    queue_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "queue": str(queue_path), "msg_id": msg_id, "session_id": session_id, "uri": file_uri}


def main():
    ap = argparse.ArgumentParser(description="Register document into WorkBuddy media-index and emit queue message")
    ap.add_argument("file_path")
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--text", default="文档已送达，请查看。")
    args = ap.parse_args()
    result = attach_message(args.text, args.file_path, args.session_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
