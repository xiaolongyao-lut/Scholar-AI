"""Knowledge Workbench facade routes."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

try:  # pragma: no cover - package import path used by the running app.
    from literature_assistant.core.source_vault import (
        SourceAssetRecord,
        SourceChunkSearchResult,
        SourceVault,
    )
except ImportError:  # pragma: no cover - flat import path used by legacy tests.
    from source_vault import (
        SourceAssetRecord,
        SourceChunkSearchResult,
        SourceVault,
    )


router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Workbench"])

StorageStatus = Literal["stored", "referenced", "missing"]


class SourceVaultSourceResponse(BaseModel):
    """One Source Vault source row returned to the workbench UI."""

    source_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_hash: str = Field(min_length=64, max_length=64)
    original_filename: str = Field(min_length=1)
    stored_path: str = Field(min_length=1)
    file_size: int = Field(gt=0)
    parser_version: str = Field(min_length=1)
    chunker_version: str = Field(min_length=1)
    storage_status: StorageStatus
    first_seen_at: str = Field(min_length=1)
    last_indexed_at: str = Field(min_length=1)
    project_ids: list[str] = Field(default_factory=list)


class SourceVaultOverviewResponse(BaseModel):
    """Source Vault overview for the Knowledge Workbench source section."""

    total_sources: int = Field(ge=0)
    total_project_links: int = Field(ge=0)
    fts_enabled: bool
    storage_root: str = Field(min_length=1)
    db_path: str = Field(min_length=1)
    sources: list[SourceVaultSourceResponse] = Field(default_factory=list)


class SourceVaultSearchResultResponse(BaseModel):
    """One Source Vault chunk search hit."""

    chunk_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_hash: str = Field(min_length=64, max_length=64)
    title: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    score: float | None = None


class SourceVaultSearchResponse(BaseModel):
    """Search results for source chunks."""

    query: str = Field(min_length=1)
    project_id: str | None = None
    results: list[SourceVaultSearchResultResponse] = Field(default_factory=list)


def get_source_vault() -> SourceVault:
    """Return the default Source Vault dependency for read-only workbench routes."""

    return SourceVault()


def _source_to_response(source: SourceAssetRecord) -> SourceVaultSourceResponse:
    return SourceVaultSourceResponse(
        source_id=source.source_id,
        source_type=source.source_type,
        title=source.title,
        source_hash=source.source_hash,
        original_filename=source.original_filename,
        stored_path=str(source.stored_path),
        file_size=source.file_size,
        parser_version=source.parser_version,
        chunker_version=source.chunker_version,
        storage_status=source.storage_status,
        first_seen_at=source.first_seen_at,
        last_indexed_at=source.last_indexed_at,
        project_ids=list(source.project_ids),
    )


def _search_result_to_response(result: SourceChunkSearchResult) -> SourceVaultSearchResultResponse:
    return SourceVaultSearchResultResponse(
        chunk_id=result.chunk_id,
        source_id=result.source_id,
        source_hash=result.source_hash,
        title=result.title,
        chunk_index=result.chunk_index,
        text=result.text,
        score=result.score,
    )


@router.get("/source-vault", response_model=SourceVaultOverviewResponse)
def source_vault_overview(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    vault: SourceVault = Depends(get_source_vault),
) -> SourceVaultOverviewResponse:
    """Return Source Vault status and recent sources for the workbench UI."""

    sources = vault.list_sources()
    limited_sources = sources[:limit]
    return SourceVaultOverviewResponse(
        total_sources=len(sources),
        total_project_links=sum(len(source.project_ids) for source in sources),
        fts_enabled=vault.fts_enabled,
        storage_root=str(vault.storage_root),
        db_path=str(vault.db_path),
        sources=[_source_to_response(source) for source in limited_sources],
    )


@router.get("/source-vault/search", response_model=SourceVaultSearchResponse)
def source_vault_search(
    q: Annotated[str, Query(min_length=1, max_length=500, description="Source chunk search query.")],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    vault: SourceVault = Depends(get_source_vault),
) -> SourceVaultSearchResponse:
    """Search Source Vault chunks by title/text with optional project narrowing."""

    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="q must not be empty")
    normalized_project_id = project_id.strip() if isinstance(project_id, str) else None
    results = vault.search_chunks(query, limit=limit, project_id=normalized_project_id)
    return SourceVaultSearchResponse(
        query=query,
        project_id=normalized_project_id,
        results=[_search_result_to_response(result) for result in results],
    )
