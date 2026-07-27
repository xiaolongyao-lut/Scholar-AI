"""Typed runtime boundary for PyMuPDF constructors with incomplete annotations."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Literal, Protocol, Self, overload, runtime_checkable


class PyMuPdfPixmap(Protocol):
    """Pixmap behavior consumed by resource preview rendering."""

    def save(self, filename: str) -> None: ...


class PyMuPdfPage(Protocol):
    """Page behavior reached directly from a validated document."""

    rect: object
    rotation_matrix: object

    @overload
    def get_text(self) -> str: ...

    @overload
    def get_text(
        self,
        option: Literal["text"],
        *,
        sort: bool = False,
        flags: int = 0,
    ) -> str: ...

    @overload
    def get_text(
        self,
        option: str,
        *,
        sort: bool = False,
        flags: int = 0,
    ) -> object: ...

    def get_drawings(self) -> list[object]: ...

    def get_pixmap(
        self,
        *,
        matrix: object,
        alpha: bool,
        clip: object | None,
    ) -> PyMuPdfPixmap: ...

    def search_for(self, text: str) -> list[object]: ...


@runtime_checkable
class _PyMuPdfDocumentContext(Protocol):
    """Context-manager behavior shared by supported document implementations."""

    def __enter__(self) -> object: ...

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> bool | None: ...


@runtime_checkable
class _PyMuPdfDocumentSequence(_PyMuPdfDocumentContext, Protocol):
    """Sequence protocol exposed by current PyMuPDF documents."""

    def __len__(self) -> int: ...

    def __getitem__(self, index: int) -> PyMuPdfPage: ...


@runtime_checkable
class _PyMuPdfDocumentIterable(_PyMuPdfDocumentContext, Protocol):
    """Explicit iterable protocol retained by compatible backends and test doubles."""

    def __iter__(self) -> Iterator[PyMuPdfPage]: ...


class PyMuPdfDocument:
    """Validated view over sequence- and iterable-style document APIs."""

    def __init__(
        self,
        document: _PyMuPdfDocumentSequence | _PyMuPdfDocumentIterable,
    ) -> None:
        self._document = document
        self._page_cache: tuple[PyMuPdfPage, ...] | None = None

    def __enter__(self) -> Self:
        self._document.__enter__()
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> bool | None:
        return self._document.__exit__(exc_type, exc_value, traceback)

    def __len__(self) -> int:
        if isinstance(self._document, _PyMuPdfDocumentSequence):
            return len(self._document)
        return len(self._cached_pages())

    def __getitem__(self, index: int) -> PyMuPdfPage:
        if isinstance(self._document, _PyMuPdfDocumentSequence):
            return self._document[index]
        return self._cached_pages()[index]

    def __iter__(self) -> Iterator[PyMuPdfPage]:
        if isinstance(self._document, _PyMuPdfDocumentSequence):
            for index in range(len(self._document)):
                yield self._document[index]
            return
        yield from self._cached_pages()

    def pages(self) -> Iterator[PyMuPdfPage]:
        return iter(self)

    def _cached_pages(self) -> tuple[PyMuPdfPage, ...]:
        if self._page_cache is None:
            if not isinstance(self._document, _PyMuPdfDocumentIterable):
                raise TypeError("PyMuPDF document is not iterable")
            self._page_cache = tuple(self._document)
        return self._page_cache


def _dynamic_constructor(module: object, name: str) -> Callable[..., object]:
    """Return a callable module attribute after a defensive runtime check."""

    constructor: object = getattr(module, name, None)
    if not callable(constructor):
        raise TypeError(f"PyMuPDF constructor is unavailable: {name}")
    return constructor


def open_pymupdf_document(
    module: object,
    *args: object,
    **kwargs: object,
) -> PyMuPdfDocument:
    """Open and validate the PyMuPDF document surface used by routers."""

    constructor = _dynamic_constructor(module, "open")
    document: object = constructor(*args, **kwargs)
    if isinstance(document, _PyMuPdfDocumentSequence):
        return PyMuPdfDocument(document)
    if isinstance(document, _PyMuPdfDocumentIterable):
        return PyMuPdfDocument(document)
    raise TypeError("PyMuPDF open() returned an incompatible document")


def new_pymupdf_rect(module: object, *args: object) -> object:
    """Construct a native rectangle through a checked dynamic constructor."""

    constructor = _dynamic_constructor(module, "Rect")
    rect: object = constructor(*args)
    return rect


def pymupdf_rect_area(rect: object) -> float:
    """Read a native rectangle area through its checked callable surface."""

    get_area: object = getattr(rect, "get_area", None)
    if not callable(get_area):
        raise TypeError("PyMuPDF rectangle does not expose get_area()")
    area: object = get_area()
    if isinstance(area, bool) or not isinstance(area, (int, float)):
        raise TypeError("PyMuPDF rectangle area must be numeric")
    return float(area)


def transform_pymupdf_rect(rect: object, matrix: object) -> object:
    """Apply a native PyMuPDF matrix without exposing an untyped call."""

    transform: object = getattr(rect, "__mul__", None)
    if not callable(transform):
        raise TypeError("PyMuPDF rectangle does not support matrix transforms")
    transformed: object = transform(matrix)
    return transformed


def include_pymupdf_rect(rect: object, other: object) -> None:
    """Expand one native rectangle to include another."""

    include: object = getattr(rect, "include_rect", None)
    if not callable(include):
        raise TypeError("PyMuPDF rectangle does not expose include_rect()")
    include(other)


def new_pymupdf_matrix(module: object, *args: object) -> object:
    """Construct an opaque matrix passed directly back to PyMuPDF."""

    constructor = _dynamic_constructor(module, "Matrix")
    matrix: object = constructor(*args)
    return matrix


__all__ = [
    "include_pymupdf_rect",
    "new_pymupdf_matrix",
    "new_pymupdf_rect",
    "open_pymupdf_document",
    "pymupdf_rect_area",
    "transform_pymupdf_rect",
]
