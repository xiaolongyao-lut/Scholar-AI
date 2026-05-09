# -*- coding: utf-8 -*-
"""
Industrial Conversation Logic
Reference: CONVERSATION_PERSISTENCE_DESIGN.md
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

def get_workspace_root() -> Path:
    """获取工作区根目录 (优先 Git 根目录)"""
    cwd = Path.cwd()
    try:
        import subprocess
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.STDOUT
        ).decode().strip()
        return Path(git_root)
    except:
        return cwd

class ConversationManager:
    """
    工业级会话持久化层
    支持：工��区绑定 (FR-2)、追加式事件日志 (FR-1)、恢复重放 (FR-3)
    """

    def __init__(self, storage_root: str | Path = None):
        if storage_root is None:
            # 采用隐藏目录存储，实现工作区动态绑定
            self.workspace_root = get_workspace_root()
            self.modular_root = self.workspace_root / ".modular" / "sessions"
        else:
            self.workspace_root = Path.cwd()
            self.modular_root = Path(storage_root)

        self.transcripts_dir = self.modular_root / "transcripts"
        self.index_file = self.modular_root / "index.json"

        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_key = hashlib.sha256(str(self.workspace_root).encode()).hexdigest()[:12]

    def create_session(self, title: str = "New Research Session") -> str:
        """创建一个全新的工业级 Session (FR-1)"""
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        self._update_index(session_id, action="created", extra={"title": title})

        # 记录初始化事件
        self.log_event(session_id, "session_created", {"title": title})
        return session_id

    def log_event(self, session_id: str, kind: str, payload: Dict[str, Any]):
        """记录追加式结构化事件 (FR-7.2)"""
        transcript_file = self.transcripts_dir / f"{session_id}.jsonl"

        event = {
            "event_id": f"evt_{uuid.uuid4().hex[:8]}",
            "session_id": session_id,
            "event_kind": kind,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "workspace_key": self.workspace_key,
            "payload": payload
        }

        # Append-only 写入，防止覆盖损坏 (DoD 3.0.2)
        try:
            with transcript_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"严重错误: 无法写入 Transcript 事件: {e}")

        self._update_index(session_id, action="active")

    def _update_index(self, session_id: str, action: str, extra: Dict = None):
        """维护全局轻量级索引文件 (FR-7.3)"""
        index = {}
        if self.index_file.exists():
            try:
                index = json.loads(self.index_file.read_text(encoding="utf-8"))
            except:
                pass

        meta = index.setdefault(session_id, {
            "session_id": session_id,
            "workspace_root": str(self.workspace_root),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_active": "",
            "title": "Untitled Research",
            "status": "active"
        })

        if extra: meta.update(extra)
        meta["last_active"] = datetime.now(timezone.utc).isoformat()

        # 原子性重命名确保索引完整 (DoD §11.1)
        tmp_idx = self.index_file.with_suffix(".json.tmp")
        tmp_idx.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_idx, self.index_file)

    def resume_session(self, session_id: str) -> List[Dict[str, Any]]:
        """从持久化记录重构历史状态 (FR-3.5)"""
        transcript_file = self.transcripts_dir / f"{session_id}.jsonl"
        if not transcript_file.exists():
            return []

        events = []
        try:
            with transcript_file.open("r", encoding="utf-8") as f:
                for line in f:
                    events.append(json.loads(line))
        except Exception as e:
            logger.error(f"Resume 失败: 文件损��或不可读: {e}")

        return events

def get_conv_manager(**kwargs) -> ConversationManager:
    return ConversationManager(**kwargs)
