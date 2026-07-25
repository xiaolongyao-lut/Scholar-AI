"""Official arXiv API adapter for the first acquisition vertical slice."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

from ..models import (
    AccessEvidence,
    AccessEvidenceKind,
    AccessRoute,
    CandidateManifest,
    CandidateSourceRecord,
    PdfCandidate,
    PublicationStage,
    SearchQuery,
    SourcePolicy,
)
from ..source_registry import SourceAdapterError, SourceHumanGateRequired


ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_POLICY = SourcePolicy(
    source_id="arxiv",
    capabilities=("search", "download"),
    metadata_hosts=("export.arxiv.org",),
    download_hosts=("arxiv.org",),
    evidence_kinds=(AccessEvidenceKind.OFFICIAL_REPOSITORY,),
    requires_authentication=False,
    enabled=True,
    min_interval_seconds=3.0,
    max_results_per_query=50,
    terms_url="https://info.arxiv.org/help/api/user-manual.html",
)

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
_STOP_STATUS_GATE = {
    401: "http_401",
    403: "http_403",
    407: "http_407",
    429: "http_429",
    503: "http_503",
}


class ArxivSourceAdapter:
    """Search arXiv through its documented Atom API."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        """Initialize with an optional injected client for local fixture tests."""

        self._client = client

    @property
    def policy(self) -> SourcePolicy:
        """Return the fixed official arXiv policy."""

        return ARXIV_POLICY

    async def search(self, query: SearchQuery, *, run_id: str) -> tuple[CandidateManifest, ...]:
        """Return normalized arXiv candidates for one explicit query.

        Args:
            query: Strict project-scoped search request containing ``arxiv``.
            run_id: Durable search-run id used to derive collision-safe local ids.

        Returns:
            Bounded candidates with official-repository AccessEvidence.

        Raises:
            SourceHumanGateRequired: For explicit access/rate/gate statuses.
            SourceAdapterError: For redirects, malformed XML, HTML, or transport
                failures. No alternate source is attempted inside this adapter.
        """

        if "arxiv" not in query.sources:
            raise ValueError("SearchQuery does not request arxiv")
        if not str(run_id or "").strip():
            raise ValueError("run_id must be non-empty")
        max_results = min(query.max_results, self.policy.max_results_per_query)
        params = {
            "search_query": f"all:{query.query}",
            "start": "0",
            "max_results": str(max_results),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": "ScholarAI/0.1.8.4 compliant-open-access-client"},
        )
        try:
            content = await self._request_atom(client, params)
        finally:
            if owns_client:
                await client.aclose()
        return _parse_arxiv_feed(content, query=query, run_id=run_id, max_results=max_results)

    async def _request_atom(
        self,
        client: httpx.AsyncClient,
        params: dict[str, str],
    ) -> bytes:
        try:
            async with client.stream(
                "GET",
                ARXIV_API_URL,
                params=params,
                follow_redirects=False,
            ) as response:
                if response.status_code in _STOP_STATUS_GATE:
                    raise SourceHumanGateRequired(
                        _STOP_STATUS_GATE[response.status_code],
                        ARXIV_API_URL,
                        f"arXiv returned HTTP {response.status_code}; automatic access stopped.",
                    )
                if 300 <= response.status_code < 400:
                    raise SourceAdapterError("unexpected_redirect", "arXiv API returned an unexpected redirect")
                if response.status_code != 200:
                    raise SourceAdapterError(
                        "http_error",
                        f"arXiv API returned HTTP {response.status_code}",
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type not in {"application/atom+xml", "application/xml", "text/xml"}:
                    gate_type = "html_instead_of_pdf" if content_type == "text/html" else "unexpected_content_type"
                    if gate_type == "html_instead_of_pdf":
                        raise SourceHumanGateRequired(
                            "html_instead_of_pdf",
                            ARXIV_API_URL,
                            "arXiv metadata endpoint returned HTML; automatic access stopped.",
                        )
                    raise SourceAdapterError("unexpected_content_type", "arXiv API did not return Atom XML")
                declared = response.headers.get("content-length")
                if declared and int(declared) > _MAX_RESPONSE_BYTES:
                    raise SourceAdapterError("response_too_large", "arXiv API response exceeded the metadata limit")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > _MAX_RESPONSE_BYTES:
                        raise SourceAdapterError("response_too_large", "arXiv API response exceeded the metadata limit")
                    chunks.append(chunk)
                return b"".join(chunks)
        except (SourceAdapterError, SourceHumanGateRequired):
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceAdapterError("transport_error", "arXiv API request failed") from exc


def _parse_arxiv_feed(
    raw_xml: bytes,
    *,
    query: SearchQuery,
    run_id: str,
    max_results: int,
) -> tuple[CandidateManifest, ...]:
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as exc:
        raise SourceAdapterError("invalid_xml", "arXiv API returned malformed Atom XML") from exc
    candidates: list[CandidateManifest] = []
    for entry in root.findall(f"{_ATOM}entry"):
        if len(candidates) >= max_results:
            break
        try:
            candidate = _parse_entry(entry, query=query, run_id=run_id)
        except (TypeError, ValueError):
            continue
        if query.year_from is not None and (candidate.year is None or candidate.year < query.year_from):
            continue
        if query.year_to is not None and (candidate.year is None or candidate.year > query.year_to):
            continue
        candidates.append(candidate)
    return tuple(candidates)


def _parse_entry(entry: ET.Element, *, query: SearchQuery, run_id: str) -> CandidateManifest:
    entry_id = _required_text(entry.find(f"{_ATOM}id"), "entry.id")
    match = re.search(r"arxiv\.org/abs/([^?#]+)", entry_id, flags=re.IGNORECASE)
    if match is None:
        raise ValueError("arXiv entry id is not canonical")
    versioned_id = match.group(1).strip().removesuffix(".pdf").lower()
    revision_match = re.search(r"(v\d+)$", versioned_id, flags=re.IGNORECASE)
    source_revision = revision_match.group(1).lower() if revision_match is not None else None
    arxiv_id = re.sub(r"v\d+$", "", versioned_id, flags=re.IGNORECASE)
    title = _clean_text(_required_text(entry.find(f"{_ATOM}title"), "entry.title"))
    summary = _clean_text(entry.findtext(f"{_ATOM}summary") or "") or None
    published = _required_text(entry.find(f"{_ATOM}published"), "entry.published")
    published_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
    authors = tuple(
        _clean_text(author.findtext(f"{_ATOM}name") or "")
        for author in entry.findall(f"{_ATOM}author")
        if _clean_text(author.findtext(f"{_ATOM}name") or "")
    )
    doi = _clean_text(entry.findtext(f"{_ARXIV}doi") or "") or None
    license_text = _clean_text(entry.findtext(f"{_ARXIV}license") or "") or None
    seed = f"{run_id}\0arxiv\0{versioned_id}".encode("utf-8")
    candidate_id = f"cand_{hashlib.sha256(seed).hexdigest()[:24]}"
    evidence_id = f"access_{hashlib.sha256(seed + b'\\0pdf').hexdigest()[:24]}"
    pdf_url = f"https://arxiv.org/pdf/{versioned_id}.pdf"
    evidence = AccessEvidence(
        evidence_id=evidence_id,
        candidate_id=candidate_id,
        source_platform="arxiv",
        kind=AccessEvidenceKind.OFFICIAL_REPOSITORY,
        access_route=AccessRoute.OPEN_ACCESS,
        pdf_url=pdf_url,
        statement="The official arXiv repository record exposes this paper PDF as open access.",
        license=license_text,
    )
    return CandidateManifest(
        candidate_id=candidate_id,
        run_id=run_id,
        project_id=query.project_id,
        title=title,
        authors=authors,
        year=published_dt.year,
        published_date=published_dt.date().isoformat(),
        abstract=summary,
        doi=doi,
        arxiv_id=arxiv_id,
        source_platforms=("arxiv",),
        source_records=(
            CandidateSourceRecord(
                source_platform="arxiv",
                source_record_id=arxiv_id,
                source_revision=source_revision,
                publication_stage=PublicationStage.PREPRINT,
            ),
        ),
        landing_urls=(f"https://arxiv.org/abs/{versioned_id}",),
        pdf_candidates=(
            PdfCandidate(
                pdf_url=pdf_url,
                source_platform="arxiv",
                access_evidence=evidence,
            ),
        ),
    )


def _required_text(element: ET.Element | None, field_name: str) -> str:
    value = "" if element is None or element.text is None else element.text.strip()
    if not value:
        raise ValueError(f"{field_name} is required")
    return value


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
