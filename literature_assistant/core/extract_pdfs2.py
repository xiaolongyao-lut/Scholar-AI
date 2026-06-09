"""Compatibility wrapper for longer local PDF inspection output."""

from __future__ import annotations

from typing import Sequence

try:
    from literature_assistant.core.extract_pdfs import main as _extract_main
except ModuleNotFoundError:
    from extract_pdfs import main as _extract_main


def main(argv: Sequence[str] | None = None) -> int:
    """Run the PDF extractor with the legacy longer-output defaults."""

    return _extract_main(
        argv=argv,
        default_first_pages=5,
        default_max_chars=3000,
        default_ascii_safe=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
