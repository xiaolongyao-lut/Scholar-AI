from __future__ import annotations

import json
from pathlib import Path

from literature_assistant import __main__ as assistant_cli
from literature_assistant.core.routers import wiki_router
from literature_assistant.core.wiki import backup as wiki_backup


class _FakePayload:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def model_dump(self) -> dict[str, object]:
        return self._payload


def test_paths_command_preserves_json_contract(capsys) -> None:
    exit_code = assistant_cli.main(["paths"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert "repo_root" in payload
    assert "workspace_artifacts_root" in payload


def test_wiki_status_command_prints_router_contract(monkeypatch, capsys) -> None:
    expected = {"enabled": False, "warnings": ["wiki disabled"], "page_count": 0}
    monkeypatch.setattr(wiki_router, "wiki_status", lambda: _FakePayload(expected))

    exit_code = assistant_cli.main(["wiki", "status"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == expected


def test_wiki_doctor_command_prints_router_contract(monkeypatch, capsys) -> None:
    expected = {
        "enabled": True,
        "report": {
            "ok": True,
            "checks": [{"name": "workspace", "status": "pass"}],
        },
    }
    monkeypatch.setattr(wiki_router, "wiki_doctor", lambda: _FakePayload(expected))

    exit_code = assistant_cli.main(["wiki", "doctor"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == expected


def test_wiki_migration_dry_run_command_prints_json_report(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "evidence.jsonl"
    input_path.write_text(
        json.dumps({"chunk_id": "c1", "material_id": "m1", "text": "evidence"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    exit_code = assistant_cli.main(["wiki", "migration-dry-run", "--input", str(input_path)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["would_write"] is False
    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["source_id"] == "rag_evidence:m1"


def test_wiki_backup_command_defaults_to_dry_run(monkeypatch, tmp_path: Path, capsys) -> None:
    expected = wiki_backup.WikiBackupPlan(
        ok=True,
        would_write=False,
        archive_path=tmp_path / "wiki-backup.zip",
        manifest_path=None,
        files=(),
    )
    monkeypatch.setattr(assistant_cli, "_wiki_backup_report", lambda **kwargs: expected.to_dict())

    exit_code = assistant_cli.main(["wiki", "backup", "--archive", str(tmp_path / "wiki-backup.zip")])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["would_write"] is False
    assert payload["archive_path"].endswith("wiki-backup.zip")
