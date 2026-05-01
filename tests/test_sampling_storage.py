from __future__ import annotations

import json
from pathlib import Path

import sampling_storage


def test_load_user_sampling_returns_empty_when_file_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert sampling_storage.load_user_sampling() == {}


def test_load_user_sampling_returns_empty_when_json_is_corrupt(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    sampling_file = tmp_path / ".literature-lab" / "sampling.json"
    sampling_file.parent.mkdir(parents=True, exist_ok=True)
    sampling_file.write_text("{not-json", encoding="utf-8")

    assert sampling_storage.load_user_sampling() == {}


def test_save_user_sampling_rejects_invalid_payload_without_overwriting_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    sampling_file = tmp_path / ".literature-lab" / "sampling.json"
    sampling_storage.save_user_sampling({"chat": {"temperature": 0.4}})
    before = sampling_file.read_text(encoding="utf-8")

    try:
        sampling_storage.save_user_sampling({"chat": {"temperature": 9}})
        assert False, "expected ValueError for invalid sampling payload"
    except ValueError as exc:
        assert "temperature" in str(exc)

    assert sampling_file.read_text(encoding="utf-8") == before


def test_save_user_sampling_round_trips_valid_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    sampling_storage.save_user_sampling(
        {
            "chat": {"temperature": 0.4, "top_p": 0.8},
            "inspiration": {"top_k": 75, "max_tokens": 900},
        }
    )

    assert sampling_storage.load_user_sampling() == {
        "chat": {"temperature": 0.4, "top_p": 0.8},
        "inspiration": {"top_k": 75, "max_tokens": 900},
    }

    raw = json.loads((tmp_path / ".literature-lab" / "sampling.json").read_text(encoding="utf-8"))
    assert raw["chat"]["temperature"] == 0.4
