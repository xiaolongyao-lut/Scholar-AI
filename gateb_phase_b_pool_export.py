from __future__ import annotations

from literature_assistant.core import gateb_phase_b_pool_export as _impl


def __getattr__(name: str) -> object:
    return getattr(_impl, name)


def main() -> None:
    """Forward CLI execution to the active core implementation."""

    _impl.main()


if __name__ == "__main__":
    main()
