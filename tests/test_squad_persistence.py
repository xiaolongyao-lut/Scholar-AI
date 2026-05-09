# -*- coding: utf-8 -*-
"""
Squad Rigorous Persistence Test (FR-7.3)
Role: 验证在追加事件过程中，索引的原子性与数据完整性
"""

import os
import json
import pytest
from pathlib import Path
from conversation_manager import ConversationManager

@pytest.fixture
def temp_manager(tmp_path):
    return ConversationManager(storage_root=tmp_path)

def test_atomic_persistence_loop(temp_manager):
    session_id = temp_manager.create_session("Stress Test")

    # 模拟快速并发写入
    for i in range(50):
        temp_manager.log_event(session_id, "test_event", {"idx": i})

    events = temp_manager.resume_session(session_id)
    assert len(events) == 51 # 1 base + 50 loop
    assert events[0]["event_kind"] == "session_created"

    # 验证索引一致性
    with temp_manager.index_file.open("r", encoding="utf-8") as f:
        index = json.load(f)
        assert session_id in index
        assert index[session_id]["status"] == "active"

def test_resume_non_existent(temp_manager):
    res = temp_manager.resume_session("fake_id")
    assert res == []
