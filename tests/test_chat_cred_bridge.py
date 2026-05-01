import importlib.util
import os
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / ".claude_squad" / "chat_cred_bridge.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("chat_cred_bridge_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _clear_bridge_env(monkeypatch):
    for name in (
        "ARK_API_KEY",
        "ARK_BASE_URL",
        "ARK_MODEL",
        "VOLCANO_API_KEY",
        "API_KEY",
        "BASE_URL",
        "MODEL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "OPENAI_API_KEY_CHAT",
        "CHAT_MODEL",
        "CHAT_BASE_URL",
        "EMBEDDING_API_KEY",
        "EMBEDDING_BASE_URL",
        "EMBEDDING_MODEL",
        "OPENAI_API_KEY_EMBEDDING",
        "RERANK_API_KEY",
        "RERANK_BASE_URL",
        "RERANK_MODEL",
        "OPENAI_API_KEY_RERANK",
    ):
        monkeypatch.delenv(name, raising=False)


def test_apply_uses_structured_env_and_role_specific_credentials(monkeypatch, tmp_path):
    _clear_bridge_env(monkeypatch)

    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "## generation candidates",
                "OPENAI_API_KEY=chat_first_key",
                "OPENAI_BASE_URL=https://chat-one.example/v1",
                "OPENAI_MODEL=chat-model-one",
                "OPENAI_API_KEY=chat_second_key",
                "OPENAI_BASE_URL=https://chat-two.example/v1",
                "OPENAI_MODEL=chat-model-two",
                "## embedding candidates",
                "EMBEDDING_API_KEY=embed_first_key",
                "EMBEDDING_BASE_URL=https://embed.example/v1",
                "EMBEDDING_MODEL=embed-model-one",
                "## rerank candidates",
                "RERANK_API_KEY=rerank_first_key",
                "RERANK_BASE_URL=https://rerank.example/v1",
                "RERANK_MODEL=rerank-model-one",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module = _load_module()
    monkeypatch.setattr(module, "ENV_PATH", str(env_path), raising=False)

    assert module.apply() is True
    assert os.environ["OPENAI_API_KEY_CHAT"] == "chat_first_key"
    assert os.environ["CHAT_MODEL"] == "chat-model-one"
    assert os.environ["CHAT_BASE_URL"] == "https://chat-one.example/v1"
    assert os.environ["OPENAI_API_KEY_EMBEDDING"] == "embed_first_key"
    assert os.environ["EMBEDDING_BASE_URL"] == "https://embed.example/v1"
    assert os.environ["EMBEDDING_MODEL"] == "embed-model-one"
    assert os.environ["OPENAI_API_KEY_RERANK"] == "rerank_first_key"
    assert os.environ["RERANK_BASE_URL"] == "https://rerank.example/v1"
    assert os.environ["RERANK_MODEL"] == "rerank-model-one"


def test_apply_keeps_ark_priority_over_openai_style_fallback(monkeypatch, tmp_path):
    _clear_bridge_env(monkeypatch)

    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "ARK_API_KEY=ark_key",
                "ARK_BASE_URL=https://ark.example/v3",
                "ARK_MODEL=ep-ark-model",
                "OPENAI_API_KEY=chat_fallback_key",
                "OPENAI_BASE_URL=https://chat-fallback.example/v1",
                "OPENAI_MODEL=chat-fallback-model",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module = _load_module()
    monkeypatch.setattr(module, "ENV_PATH", str(env_path), raising=False)

    assert module.apply() is True
    assert os.environ["OPENAI_API_KEY_CHAT"] == "ark_key"
    assert os.environ["CHAT_BASE_URL"] == "https://ark.example/v3"
    assert os.environ["CHAT_MODEL"] == "ep-ark-model"
