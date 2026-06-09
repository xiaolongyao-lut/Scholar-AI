"""Small CLI for inspecting selected pages from local PDF files.

This utility intentionally accepts all file locations at runtime so private
workspace paths never become part of the committed source tree.
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import fitz


@dataclass(frozen=True, slots=True)
class PaperSpec:
    """PDF input descriptor.

    Attributes:
        name: Human-readable title used only in console output.
        path: Existing local PDF file path supplied by the caller.
    """

    name: str
    path: Path


@dataclass(frozen=True, slots=True)
class ExtractOptions:
    """Page extraction options.

    Attributes:
        first_pages: Number of leading pages to inspect. Must be positive.
        include_last: Whether to also inspect the final page.
        max_chars: Maximum characters printed per page. Must be positive.
        ascii_safe: Replace non-ASCII characters for terminals that cannot
            render arbitrary PDF text.
    """

    first_pages: int
    include_last: bool
    max_chars: int
    ascii_safe: bool


def _parse_paper_arg(value: str) -> PaperSpec:
    """Parse one ``NAME=PATH`` CLI value into a validated paper descriptor."""

    if not value:
        raise argparse.ArgumentTypeError("--paper cannot be empty.")
    name, separator, raw_path = value.partition("=")
    if not separator or not name.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("--paper must use NAME=PATH format.")
    return PaperSpec(name=name.strip(), path=Path(raw_path.strip()).expanduser())


def _coerce_manifest_item(item: object, index: int) -> PaperSpec:
    """Validate one JSON manifest item.

    The manifest shape is ``[{"name": "title", "path": "file.pdf"}]``.
    """

    if not isinstance(item, Mapping):
        raise ValueError(f"Manifest item {index} must be an object.")
    raw_name = item.get("name")
    raw_path = item.get("path")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise ValueError(f"Manifest item {index} has an invalid name.")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError(f"Manifest item {index} has an invalid path.")
    return PaperSpec(name=raw_name.strip(), path=Path(raw_path.strip()).expanduser())


def load_manifest(path: Path) -> list[PaperSpec]:
    """Load a JSON manifest of PDF files.

    Args:
        path: Existing JSON file containing a list of paper descriptors.

    Returns:
        Validated paper descriptors in manifest order.
    """

    if not path:
        raise ValueError("Manifest path is required.")
    manifest_path = path.expanduser()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Manifest root must be a list.")
    return [_coerce_manifest_item(item, index) for index, item in enumerate(payload)]


def discover_pdfs(directory: Path, patterns: Sequence[str]) -> list[PaperSpec]:
    """Discover PDFs below a caller-supplied directory.

    Args:
        directory: Existing directory to scan.
        patterns: Glob patterns relative to ``directory``.

    Returns:
        Sorted PDF descriptors named by file stem.
    """

    if not patterns:
        raise ValueError("At least one discovery pattern is required.")
    root = directory.expanduser()
    if not root.is_dir():
        raise NotADirectoryError(f"PDF directory not found: {root}")

    discovered: dict[Path, PaperSpec] = {}
    for pattern in patterns:
        if not pattern.strip():
            raise ValueError("Discovery patterns cannot be empty.")
        for path in root.glob(pattern):
            if path.is_file() and path.suffix.lower() == ".pdf":
                resolved = path.resolve()
                discovered[resolved] = PaperSpec(name=path.stem, path=resolved)
    return [discovered[path] for path in sorted(discovered)]


def _page_indexes(total_pages: int, options: ExtractOptions) -> list[int]:
    if total_pages < 0:
        raise ValueError("total_pages cannot be negative.")
    leading = list(range(min(options.first_pages, total_pages)))
    if options.include_last and total_pages > options.first_pages:
        leading.append(total_pages - 1)
    return leading


def _format_text(text: str, *, ascii_safe: bool) -> str:
    if not ascii_safe:
        return text
    return text.encode("ascii", errors="replace").decode("ascii")


def process_paper(paper: PaperSpec, options: ExtractOptions) -> None:
    """Print selected PDF page text for one paper.

    Args:
        paper: PDF descriptor supplied by CLI input.
        options: Bounded extraction options.
    """

    if not paper.name:
        raise ValueError("Paper name is required.")
    if not paper.path:
        raise ValueError("Paper path is required.")
    if options.first_pages <= 0:
        raise ValueError("first_pages must be positive.")
    if options.max_chars <= 0:
        raise ValueError("max_chars must be positive.")

    print(f"\n{'=' * 60}")
    print(f"PAPER: {paper.name}")
    print("=" * 60)

    if not paper.path.is_file():
        print(f"FILE NOT FOUND: {paper.path}")
        return

    try:
        with fitz.open(paper.path) as doc:
            total_pages = len(doc)
            print(f"Total pages: {total_pages}")
            for page_index in _page_indexes(total_pages, options):
                text = doc[page_index].get_text()
                printable_text = _format_text(text, ascii_safe=options.ascii_safe)
                print(f"\n--- Page {page_index + 1} ---")
                print(printable_text[: options.max_chars])
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")


def _build_arg_parser(default_first_pages: int, default_max_chars: int) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract selected text from local PDF files.")
    parser.add_argument(
        "--paper",
        action="append",
        default=[],
        type=_parse_paper_arg,
        help="PDF to inspect in NAME=PATH format. May be repeated.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help='JSON list of {"name": "...", "path": "..."} paper descriptors.',
    )
    parser.add_argument("--directory", type=Path, help="Directory used for PDF discovery.")
    parser.add_argument(
        "--pattern",
        action="append",
        default=["*.pdf"],
        help="Glob pattern for --directory discovery. May be repeated.",
    )
    parser.add_argument("--first-pages", type=int, default=default_first_pages)
    parser.add_argument("--include-last", action="store_true")
    parser.add_argument("--max-chars", type=int, default=default_max_chars)
    parser.add_argument("--ascii-safe", action="store_true")
    parser.add_argument("--workers", type=int, default=max(1, os.cpu_count() or 1))
    return parser


def collect_papers(
    paper_args: Sequence[PaperSpec],
    manifest: Path | None,
    directory: Path | None,
    patterns: Sequence[str],
) -> list[PaperSpec]:
    """Collect explicit, manifest, and directory-discovered PDF inputs."""

    papers = list(paper_args)
    if manifest is not None:
        papers.extend(load_manifest(manifest))
    if directory is not None:
        papers.extend(discover_pdfs(directory, patterns))
    return papers


def run(papers: Iterable[PaperSpec], options: ExtractOptions, workers: int) -> None:
    """Extract all requested PDFs with bounded local parallelism."""

    paper_list = list(papers)
    if not paper_list:
        raise ValueError("No PDFs were provided. Use --paper, --manifest, or --directory.")
    if workers <= 0:
        raise ValueError("workers must be positive.")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for _ in executor.map(lambda paper: process_paper(paper, options), paper_list):
            pass


def main(
    argv: Sequence[str] | None = None,
    *,
    default_first_pages: int = 4,
    default_max_chars: int = 2000,
    default_ascii_safe: bool = False,
) -> int:
    """CLI entry point.

    Args:
        argv: Optional command-line argument sequence for tests.
        default_first_pages: Wrapper-specific default leading page count.
        default_max_chars: Wrapper-specific page text limit.
        default_ascii_safe: Wrapper-specific terminal compatibility default.

    Returns:
        Process exit code.
    """

    parser = _build_arg_parser(default_first_pages, default_max_chars)
    args = parser.parse_args(argv)
    options = ExtractOptions(
        first_pages=args.first_pages,
        include_last=args.include_last,
        max_chars=args.max_chars,
        ascii_safe=bool(args.ascii_safe or default_ascii_safe),
    )
    papers = collect_papers(
        paper_args=args.paper,
        manifest=args.manifest,
        directory=args.directory,
        patterns=args.pattern,
    )

    try:
        run(papers=papers, options=options, workers=args.workers)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
