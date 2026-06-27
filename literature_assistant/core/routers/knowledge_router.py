"""Knowledge Workbench facade routes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError, model_validator

try:  # pragma: no cover - package import path used by the running app.
    from literature_assistant.core.academic_english_resources import (
        academic_english_status,
        search_academic_english,
    )
    from literature_assistant.core.tolf_bridge_lexicon_store import (
        get_bridge_lexicon_status,
        load_bridge_lexicon_store,
        search_bridge_lexicon,
    )
    from literature_assistant.core.source_vault import (
        SourceAssetRecord,
        SourceChunkSearchResult,
        SourceVault,
        bounded_text,
        build_source_vault_search_metadata,
        build_source_vault_chunk_read_endpoint,
        build_source_vault_chunk_ref_id,
    )
    from literature_assistant.core import config_knowledge
    from literature_assistant.core import product_docs_knowledge
    from literature_assistant.core import skill_package_knowledge
    from literature_assistant.core.project_paths import output_path, runtime_state_path
    from literature_assistant.core.provider_capabilities import ProviderCapabilityRecord
    from literature_assistant.core.routers import agent_bridge_router as _agent_bridge_router
    from literature_assistant.core.routers import wiki_router as _wiki_router
except ImportError:  # pragma: no cover - flat import path used by legacy tests.
    from academic_english_resources import (
        academic_english_status,
        search_academic_english,
    )
    from tolf_bridge_lexicon_store import (
        get_bridge_lexicon_status,
        load_bridge_lexicon_store,
        search_bridge_lexicon,
    )
    from source_vault import (
        SourceAssetRecord,
        SourceChunkSearchResult,
        SourceVault,
        bounded_text,
        build_source_vault_search_metadata,
        build_source_vault_chunk_read_endpoint,
        build_source_vault_chunk_ref_id,
    )
    import config_knowledge
    import product_docs_knowledge
    import skill_package_knowledge
    from project_paths import output_path, runtime_state_path
    from provider_capabilities import ProviderCapabilityRecord
    import agent_bridge_router as _agent_bridge_router
    import wiki_router as _wiki_router


router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Workbench"])

StorageStatus = Literal["stored", "referenced", "missing"]
PackageKind = Literal[
    "wiki",
    "source_vault",
    "academic_english",
    "bridge_lexicon",
    "skill_package",
    "config",
    "product_docs",
]
PackageLoadStatus = Literal["loaded", "missing", "disabled", "stale", "unknown"]
KnowledgeRuntimeRecoveryMethod = Literal["GET", "POST", "READ", "RUN"]
KnowledgeRuntimeRecoveryAccessMode = Literal[
    "read_only",
    "local_artifact",
    "authorized_provider_preflight",
    "explicit_live_provider_smoke",
]
ConformanceStatus = Literal["proved", "pending", "blocked", "not_applicable"]
ConformanceEvidenceLevel = Literal[
    "runtime_projection",
    "contract_evidence",
    "focused_test_evidence",
    "not_applicable",
]

_LIVE_CONTEXT_RECEIPT_SMOKE_CONTRACT = "scholar-ai-live-context-receipt-smoke/v1"
_LIVE_CONTEXT_RECEIPT_SMOKE_ARTIFACT_NAME = "live_api_chat_knowledge_context_receipt_smoke.summary.json"
_LIVE_CONTEXT_RECEIPT_SMOKE_ARTIFACT_REF = (
    f"workspace_artifacts/generated/output/{_LIVE_CONTEXT_RECEIPT_SMOKE_ARTIFACT_NAME}"
)
_PROVIDER_CAPABILITIES_ARTIFACT_NAME = "provider-capabilities.json"
_PROVIDER_CAPABILITIES_ARTIFACT_REF = f"workspace_artifacts/runtime_state/{_PROVIDER_CAPABILITIES_ARTIFACT_NAME}"
_ACTUAL_LOADING_GATE_SCOPE = [
    "/api/chat",
    "literature.agent_resource_read",
    "literature.knowledge_context_receipt",
    "assembled_context_hash_backflow",
    "provider_tool_capability_preflight",
]
_PROVIDER_PREFLIGHT_SCOPE = [
    "/api/chat/tool-capability/test",
    "workspace_artifacts/runtime_state/provider-capabilities.json",
    "OpenAI-compatible forced tool_choice preflight",
]
_ACTUAL_LOADING_REQUIRED_CHECKS = [
    "artifact.schema.valid",
    "artifact.verdict.ok",
    "artifact.status_code.200",
    "artifact.required_tools.used",
    "artifact.required_tools.names",
    "artifact.receipt_hash.preview",
    "artifact.receipt_hash.final_answer",
    "artifact.receipt_hash.query_matches_direct",
    "artifact.direct_receipt.assembled_context_hash",
]
_ACTUAL_LOADING_REQUIRED_TOOLS = [
    "literature.agent_resource_read",
    "literature.knowledge_context_receipt",
]
_PROVIDER_PREFLIGHT_PENDING_ACTIONS = (
    "Run the provider tool-capability preflight with already configured credentials; do not paste or log secrets.",
    "Require provider_preflight.status=proved before any live actual-loading claim.",
)
_PROVIDER_PREFLIGHT_AUTH_BLOCKED_ACTIONS = (
    "Stop live actual-loading smoke while latest provider status is auth_required.",
    "After the user corrects provider credentials/config, rerun provider tool-capability preflight.",
)
_PROVIDER_PREFLIGHT_SCHEMA_ACTIONS = (
    "Inspect workspace_artifacts/runtime_state/provider-capabilities.json and regenerate it through the provider preflight path.",
)
_PROVIDER_PREFLIGHT_PROVED_ACTIONS = (
    "Proceed to the explicitly authorized live context-receipt smoke if actual-loading proof is still needed.",
)
_ACTUAL_LOADING_BASE_ACTIONS = (
    "Refresh /api/knowledge/runtime-conformance after each provider or artifact state change.",
    "Keep deterministic context-receipt evidence separate from live QA/model loading proof.",
)
_ACTUAL_LOADING_MISSING_ARTIFACT_ACTIONS = (
    "Require provider_preflight.status=proved before running live context-receipt smoke.",
    "Run tests/live_api_chat_knowledge_context_receipt_smoke.py only with explicit live-provider authorization.",
)
_ACTUAL_LOADING_INVALID_ARTIFACT_ACTIONS = (
    "Inspect validation_errors and regenerate the live context-receipt smoke artifact with the current harness.",
)
_ACTUAL_LOADING_PROVIDER_BLOCKED_ACTIONS = (
    "Resolve provider_preflight.status before treating an OK smoke artifact as actual-loading proof.",
)
_ACTUAL_LOADING_CONTRACT_ACTIONS = (
    "Fix the listed artifact contract checks and rerun the live context-receipt smoke.",
)


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

    ref_id: str = Field(min_length=1)
    read_endpoint: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_hash: str = Field(min_length=64, max_length=64)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    original_filename: str = Field(min_length=1)
    stored_path: str = Field(min_length=1)
    page: int | None = None
    span_start: int | None = None
    span_end: int | None = None
    section: str | None = None
    text_hash: str = Field(min_length=64, max_length=64)
    truncated: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None


class SourceVaultSearchResponse(BaseModel):
    """Search results for source chunks."""

    query: str = Field(min_length=1)
    project_id: str | None = None
    results: list[SourceVaultSearchResultResponse] = Field(default_factory=list)


class AcademicEnglishStatusResponse(BaseModel):
    """Status for the generated academic-English runtime knowledge package."""

    schema_version: str = Field(min_length=1)
    available: bool
    manifest_loaded: bool
    builder_version: str = ""
    built_at: str = ""
    counts: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    knowledge_sources: dict[str, dict[str, Any]] = Field(default_factory=dict)
    artifacts: dict[str, dict[str, Any]] = Field(default_factory=dict)


class AcademicEnglishSearchHitResponse(BaseModel):
    """One bounded academic-English knowledge hit."""

    schema_version: str = Field(min_length=1)
    ref_id: str = Field(min_length=1, max_length=240)
    kind: str = Field(min_length=1, max_length=80)
    resource_kind: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=2000)
    score: float | None = None
    rank: int = Field(ge=1)
    read_endpoint: str = Field(min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AcademicEnglishSearchResponse(BaseModel):
    """Search results for generated academic-English knowledge refs."""

    query: str = Field(min_length=1, max_length=500)
    results: list[AcademicEnglishSearchHitResponse] = Field(default_factory=list)


class BridgeLexiconStatusResponse(BaseModel):
    """Status for the CJK bridge lexicon runtime knowledge asset."""

    schema_version: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    source_hash: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    loaded: bool
    load_status: str = Field(min_length=1)
    entry_count: int = Field(ge=0)
    updated_at: str = Field(min_length=1)
    runtime_consumers: list[dict[str, str]] = Field(default_factory=list)


class BridgeLexiconReadResponse(BridgeLexiconStatusResponse):
    """Read-only bridge lexicon payload for bounded runtime context loading."""

    entries: dict[str, list[str]] = Field(default_factory=dict)


class BridgeLexiconSearchHitResponse(BaseModel):
    """One bridge-lexicon entry ref with agent-readable metadata."""

    schema_version: str = Field(min_length=1)
    ref_id: str = Field(min_length=1, max_length=300)
    kind: str = Field(min_length=1, max_length=80)
    resource_kind: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=2000)
    score: float | None = None
    rank: int = Field(ge=1)
    read_endpoint: str = Field(min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BridgeLexiconSearchResponse(BaseModel):
    """Search results for bridge-lexicon entries."""

    query: str = Field(min_length=1, max_length=500)
    package_id: str = Field(min_length=1, max_length=200)
    results: list[BridgeLexiconSearchHitResponse] = Field(default_factory=list)


class SkillPackageSourceResponse(BaseModel):
    """One source file loaded from a read-only Skill package."""

    relative_path: str = Field(min_length=1, max_length=500)
    role: str = Field(min_length=1, max_length=80)
    loaded: bool
    content_hash: str = Field(min_length=1)
    char_count: int = Field(ge=0)
    byte_count: int = Field(ge=0)
    updated_at: str = Field(min_length=1)
    warning: str | None = None


class SkillPackageChunkResponse(BaseModel):
    """One bounded Skill package knowledge ref."""

    chunk_id: str = Field(min_length=1, max_length=240)
    ref_id: str = Field(min_length=1, max_length=300)
    read_endpoint: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=500)
    source_path: str = Field(min_length=1, max_length=500)
    source_role: str = Field(min_length=1, max_length=80)
    source_hash: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=0)
    char_count: int = Field(ge=0)


class SkillPackageStatusResponse(BaseModel):
    """Read-only status for one repo-local Skill package knowledge asset."""

    schema_version: str = Field(min_length=1)
    package_id: str = Field(min_length=1, max_length=200)
    package_root: str = Field(min_length=1, max_length=500)
    source_path: str = Field(min_length=1, max_length=500)
    source_hash: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    loaded: bool
    manifest_loaded: bool
    load_status: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=2000)
    version: str = Field(min_length=1, max_length=80)
    skill_kind: str = Field(min_length=1, max_length=80)
    source_files: list[SkillPackageSourceResponse] = Field(default_factory=list)
    chunk_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    runtime_consumers: list[dict[str, str]] = Field(default_factory=list)
    chunks: list[SkillPackageChunkResponse] = Field(default_factory=list)


class SkillPackageSearchHitResponse(BaseModel):
    """One Skill package search result with a bounded agent-readable ref."""

    schema_version: str = Field(min_length=1)
    ref_id: str = Field(min_length=1, max_length=300)
    kind: str = Field(min_length=1, max_length=80)
    resource_kind: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=2000)
    score: float | None = None
    rank: int = Field(ge=1)
    read_endpoint: str = Field(min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillPackageSearchResponse(BaseModel):
    """Search results for repo-local Skill package knowledge refs."""

    query: str = Field(min_length=1, max_length=500)
    package_id: str = Field(min_length=1, max_length=200)
    results: list[SkillPackageSearchHitResponse] = Field(default_factory=list)


class ConfigSourceResponse(BaseModel):
    """One authoritative JSON config source loaded into runtime knowledge."""

    relative_path: str = Field(min_length=1, max_length=500)
    loaded: bool
    content_hash: str = Field(min_length=1)
    char_count: int = Field(ge=0)
    byte_count: int = Field(ge=0)
    updated_at: str = Field(min_length=1)
    warning: str | None = None


class ConfigSectionResponse(BaseModel):
    """One bounded JSON config section ref."""

    section_id: str = Field(min_length=1, max_length=120)
    ref_id: str = Field(min_length=1, max_length=240)
    read_endpoint: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=500)
    source_path: str = Field(min_length=1, max_length=500)
    source_hash: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=0)
    char_count: int = Field(ge=0)


class ScoringRulesStatusResponse(BaseModel):
    """Read-only status for the scoring rules JSON config knowledge asset."""

    schema_version: str = Field(min_length=1)
    package_id: str = Field(min_length=1, max_length=200)
    config_id: str = Field(min_length=1, max_length=120)
    source_path: str = Field(min_length=1, max_length=500)
    source_hash: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    loaded: bool
    manifest_loaded: bool
    load_status: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=2000)
    version: str = Field(min_length=1, max_length=80)
    last_updated: str = Field(min_length=1, max_length=80)
    source: ConfigSourceResponse
    section_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    runtime_consumers: list[dict[str, str]] = Field(default_factory=list)
    sections: list[ConfigSectionResponse] = Field(default_factory=list)


class ScoringRulesReadResponse(ScoringRulesStatusResponse):
    """Read-only scoring rules JSON sections for bounded runtime loading."""

    entries: dict[str, Any] = Field(default_factory=dict)


class ScoringRulesSearchHitResponse(BaseModel):
    """One scoring-rules search result with a bounded agent-readable ref."""

    schema_version: str = Field(min_length=1)
    ref_id: str = Field(min_length=1, max_length=240)
    kind: str = Field(min_length=1, max_length=80)
    resource_kind: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=2000)
    score: float | None = None
    rank: int = Field(ge=1)
    read_endpoint: str = Field(min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScoringRulesSearchResponse(BaseModel):
    """Search results for scoring-rules JSON config refs."""

    query: str = Field(min_length=1, max_length=500)
    package_id: str = Field(min_length=1, max_length=200)
    results: list[ScoringRulesSearchHitResponse] = Field(default_factory=list)


class ProductDocsSourceResponse(BaseModel):
    """One authoritative product-doc source loaded into runtime knowledge."""

    relative_path: str = Field(min_length=1, max_length=500)
    role: str = Field(min_length=1, max_length=80)
    loaded: bool
    content_hash: str = Field(min_length=1)
    char_count: int = Field(ge=0)
    byte_count: int = Field(ge=0)
    updated_at: str = Field(min_length=1)
    warning: str | None = None


class ProductDocsChunkResponse(BaseModel):
    """One bounded product-doc chunk ref."""

    chunk_id: str = Field(min_length=1, max_length=240)
    ref_id: str = Field(min_length=1, max_length=300)
    read_endpoint: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=500)
    source_path: str = Field(min_length=1, max_length=500)
    source_role: str = Field(min_length=1, max_length=80)
    source_hash: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=0)
    char_count: int = Field(ge=0)


class ProductDocsStatusResponse(BaseModel):
    """Read-only status for repo-local product documentation knowledge."""

    schema_version: str = Field(min_length=1)
    package_id: str = Field(min_length=1, max_length=200)
    source_path: str = Field(min_length=1, max_length=500)
    source_hash: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    loaded: bool
    manifest_loaded: bool
    load_status: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=2000)
    source_files: list[ProductDocsSourceResponse] = Field(default_factory=list)
    chunk_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    runtime_consumers: list[dict[str, str]] = Field(default_factory=list)
    chunks: list[ProductDocsChunkResponse] = Field(default_factory=list)


class ProductDocsReadResponse(ProductDocsStatusResponse):
    """Read-only product-doc chunks for bounded runtime context loading."""

    entries: dict[str, Any] = Field(default_factory=dict)


class ProductDocsSearchHitResponse(BaseModel):
    """One product-doc search result with a bounded agent-readable ref."""

    schema_version: str = Field(min_length=1)
    ref_id: str = Field(min_length=1, max_length=300)
    kind: str = Field(min_length=1, max_length=80)
    resource_kind: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=2000)
    score: float | None = None
    rank: int = Field(ge=1)
    read_endpoint: str = Field(min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductDocsSearchResponse(BaseModel):
    """Search results for repo-local product-doc refs."""

    query: str = Field(min_length=1, max_length=500)
    package_id: str = Field(min_length=1, max_length=200)
    results: list[ProductDocsSearchHitResponse] = Field(default_factory=list)


class KnowledgePackageProjectionResponse(BaseModel):
    """One normalized runtime knowledge package projection."""

    package_id: str = Field(min_length=1)
    kind: PackageKind
    title: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    status: PackageLoadStatus
    available: bool
    loaded: bool
    manifest_loaded: bool
    source_path: str = Field(min_length=1)
    source_hash: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    read_endpoint: str = Field(min_length=1)
    search_endpoint: str | None = None
    notes: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)


class KnowledgePackagesResponse(BaseModel):
    """Normalized registry of runtime knowledge packages."""

    schema_version: str = Field(min_length=1)
    packages: list[KnowledgePackageProjectionResponse] = Field(default_factory=list)


class KnowledgeRuntimeConformanceItemResponse(BaseModel):
    """One requirement-level proof row for a runtime knowledge package."""

    requirement: str = Field(min_length=1, max_length=120)
    status: ConformanceStatus
    evidence_level: ConformanceEvidenceLevel = "runtime_projection"
    evidence_scope: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class KnowledgeRuntimeTestEvidenceResponse(BaseModel):
    """Static local-test evidence known to protect one runtime knowledge package."""

    focused_test_exists: bool = False
    source_edit_hash_test: bool = False
    context_receipt_test: bool = False
    evidence_pack_test: bool = False
    agent_resource_read_test: bool = False
    mcp_tool_test: bool = False
    test_nodes: list[str] = Field(default_factory=list)


class KnowledgeRuntimeConformancePackageResponse(BaseModel):
    """Machine-readable source-to-context conformance projection for one package."""

    package_id: str = Field(min_length=1)
    kind: PackageKind
    title: str = Field(min_length=1)
    overall_status: ConformanceStatus
    loaded: bool
    source_path: str = Field(min_length=1)
    source_hash: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    read_endpoint: str = Field(min_length=1)
    search_endpoint: str | None = None
    manifest: dict[str, Any] = Field(default_factory=dict)
    runtime_consumers: list[dict[str, str]] = Field(default_factory=list)
    mcp_tools: list[str] = Field(default_factory=list)
    test_evidence: KnowledgeRuntimeTestEvidenceResponse = Field(
        default_factory=KnowledgeRuntimeTestEvidenceResponse,
    )
    conformance: list[KnowledgeRuntimeConformanceItemResponse] = Field(default_factory=list)


class KnowledgeRuntimeProviderPreflightRecordResponse(BaseModel):
    """One redacted provider tool-call preflight record."""

    fingerprint: str = Field(min_length=1, max_length=128)
    provider: str = Field(default="", max_length=120)
    base_url_host: str = Field(default="", max_length=240)
    model: str = Field(default="", max_length=240)
    status: str = Field(default="unknown", max_length=80)
    ordinary_chat_ok: bool = False
    forced_tool_choice_ok: bool = False
    last_probe_at: str = Field(default="", max_length=64)
    failure_class: str = Field(default="", max_length=120)
    masked_error: str = Field(default="", max_length=320)


class KnowledgeRuntimeProviderPreflightResponse(BaseModel):
    """Provider readiness gate for live Knowledge Runtime actual-loading proof.

    Why: a provider that has not proven forced tool calls cannot prove that the
    QA/model turn actually received bounded Knowledge Runtime resources.
    """

    status: ConformanceStatus
    evidence_level: ConformanceEvidenceLevel = "runtime_projection"
    artifact_path: str = Field(min_length=1)
    artifact_ref: str = Field(default=_PROVIDER_CAPABILITIES_ARTIFACT_REF, min_length=1)
    artifact_exists: bool
    artifact_schema_valid: bool
    checked_at: str = Field(min_length=1)
    record_count: int = Field(ge=0)
    latest_status: str = Field(default="unknown", max_length=80)
    status_counts: dict[str, int] = Field(default_factory=dict)
    auth_required_count: int = Field(default=0, ge=0)
    tool_call_ok_count: int = Field(default=0, ge=0)
    provider_ready_for_authorized_live_smoke: bool = False
    records: list[KnowledgeRuntimeProviderPreflightRecordResponse] = Field(default_factory=list)
    evidence_scope: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    next_safe_local_actions: list[str] = Field(default_factory=list, max_length=8)
    claim_boundary: str = Field(default="", max_length=1000)


class KnowledgeRuntimeRecoveryRefResponse(BaseModel):
    """One recovery reference for a blocked Knowledge Runtime loading gate."""

    ref_type: Literal[
        "conformance_endpoint",
        "provider_preflight_artifact",
        "provider_preflight_endpoint",
        "live_smoke_artifact",
        "live_smoke_harness",
    ]
    ref: str = Field(min_length=1, max_length=500)
    status: str = Field(default="", max_length=120)
    method: KnowledgeRuntimeRecoveryMethod = "GET"
    access_mode: KnowledgeRuntimeRecoveryAccessMode = "read_only"
    required_before_completion: bool = True
    requires_authorization: bool = False


class KnowledgeRuntimeActualLoadingRecoveryResponse(BaseModel):
    """Machine-readable recovery state for the live actual-loading gate."""

    schema_version: str = Field(default="scholar-ai-knowledge-runtime-recovery/v1", min_length=1)
    read_only: bool = True
    state: str = Field(min_length=1, max_length=120)
    blocked_by: list[str] = Field(default_factory=list, max_length=8)
    recovery_refs: list[KnowledgeRuntimeRecoveryRefResponse] = Field(default_factory=list, max_length=8)
    provider_ready_for_authorized_live_smoke: bool = False
    completion_requires_authorized_live_smoke: bool = True


class KnowledgeRuntimeActualLoadingGateResponse(BaseModel):
    """Top-level proof gate for live QA/model context loading.

    Why: deterministic context receipts prove bounded local prompt assembly, but
    only an explicitly authorized live smoke can prove a provider turn received
    and echoed the receipt hash.
    """

    status: ConformanceStatus
    evidence_level: ConformanceEvidenceLevel = "runtime_projection"
    artifact_path: str = Field(min_length=1)
    artifact_ref: str = Field(min_length=1)
    artifact_contract: str = Field(default=_LIVE_CONTEXT_RECEIPT_SMOKE_CONTRACT, min_length=1)
    artifact_exists: bool
    artifact_schema_valid: bool
    artifact_contract_valid: bool
    artifact_checked_at: str = Field(min_length=1)
    verdict: str = Field(min_length=1)
    evidence_scope: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=lambda: list(_ACTUAL_LOADING_REQUIRED_CHECKS))
    next_safe_local_actions: list[str] = Field(default_factory=list, max_length=8)
    claim_boundary: str = Field(default="", max_length=1000)
    provider_preflight: KnowledgeRuntimeProviderPreflightResponse
    recovery: KnowledgeRuntimeActualLoadingRecoveryResponse = Field(
        default_factory=lambda: KnowledgeRuntimeActualLoadingRecoveryResponse(state="unclassified"),
    )

    @model_validator(mode="after")
    def attach_recovery(self) -> Self:
        """Attach recovery state after all gate fields are validated."""

        self.recovery = _actual_loading_recovery_state(self)
        return self


class LiveContextReceiptSmokeDirectReceipt(BaseModel):
    """Direct deterministic receipt copied into the live-smoke summary."""

    schemaVersion: str = Field(default="", max_length=120)
    promptHash: str = Field(default="", max_length=64)
    assembledContextHash: str = Field(min_length=64, max_length=64, pattern=r"^[a-fA-F0-9]{64}$")
    assembledContextCharCount: int = Field(default=0, ge=0)
    resourceReceiptCount: int = Field(default=0, ge=0)


class LiveContextReceiptSmokeChatEvidence(BaseModel):
    """Provider-visible evidence extracted from one authorized chat turn."""

    toolNames: list[str] = Field(default_factory=list)
    receiptSchemaVisibleInToolPreview: bool = False
    receiptHashVisibleInToolPreview: bool = False
    finalAnswerIncludesReceiptHash: bool = False
    queryHashMatchesDirectReceipt: bool = False
    requiredToolSequence: list[str] = Field(default_factory=list)
    usedRequiredTools: bool = False


class LiveContextReceiptSmokeSummary(BaseModel):
    """Validated artifact contract for live Knowledge Runtime loading proof."""

    generatedAt: str = Field(default="", max_length=120)
    surface: str = Field(default="/api/chat", min_length=1, max_length=200)
    statusCode: int = Field(ge=0)
    verdict: str = Field(min_length=1, max_length=120)
    claimBoundary: str = Field(default="", max_length=1000)
    provider: str = Field(default="unknown", max_length=120)
    baseHost: str = Field(default="unknown", max_length=240)
    model: str = Field(default="unknown", max_length=200)
    directReceipt: LiveContextReceiptSmokeDirectReceipt
    chatEvidence: LiveContextReceiptSmokeChatEvidence


class KnowledgeRuntimeConformanceResponse(BaseModel):
    """Read-only audit surface for the Knowledge Runtime Pipeline contract."""

    schema_version: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    pipeline: list[str] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    actual_loading_gate: KnowledgeRuntimeActualLoadingGateResponse
    packages: list[KnowledgeRuntimeConformancePackageResponse] = Field(default_factory=list)


class KnowledgeContextReceiptRequest(BaseModel):
    """Bounded knowledge refs to assemble into a model-context receipt."""

    ref_ids: list[str] = Field(min_length=1, max_length=20)
    project_id: str | None = Field(default=None, max_length=200)
    prompt_name: str = Field(default="knowledge_runtime_context", min_length=1, max_length=120)
    max_chars_per_ref: int = Field(default=1200, ge=100, le=4000)


class KnowledgeContextResourceReceiptResponse(BaseModel):
    """One bounded resource-read proof row included in a context receipt."""

    ref_id: str = Field(min_length=1, max_length=300)
    kind: str = Field(min_length=1, max_length=80)
    title: str | None = Field(default=None, max_length=500)
    read_endpoint: str = Field(min_length=1, max_length=500)
    content_hash: str = Field(min_length=64, max_length=64)
    source_hash: str = Field(default="unknown", min_length=1)
    package_content_hash: str = Field(default="unknown", min_length=1)
    source_path: str | None = Field(default=None, max_length=500)
    span_start: int | None = Field(default=None, ge=0)
    span_end: int | None = Field(default=None, ge=0)
    returned_chars: int = Field(ge=0)
    total_chars: int = Field(ge=0)
    max_chars: int = Field(ge=100, le=4000)
    truncated: bool
    cursor: str | None = None
    next_cursor: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeContextReceiptResponse(BaseModel):
    """Hash-only proof that selected knowledge refs entered bounded context."""

    schema_version: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    prompt_name: str = Field(min_length=1, max_length=120)
    prompt_hash: str = Field(min_length=64, max_length=64)
    assembled_context_hash: str = Field(min_length=64, max_length=64)
    assembled_context_char_count: int = Field(ge=0)
    assembled_context_preview: str = Field(default="", max_length=4000)
    resource_read_receipts: list[KnowledgeContextResourceReceiptResponse] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


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
    preview, truncated = bounded_text(result.text, max_chars=320)
    ref_id = build_source_vault_chunk_ref_id(result.chunk_id)
    return SourceVaultSearchResultResponse(
        ref_id=ref_id,
        read_endpoint=build_source_vault_chunk_read_endpoint(result.chunk_id),
        chunk_id=result.chunk_id,
        source_id=result.source_id,
        source_hash=result.source_hash,
        title=result.title,
        summary=preview,
        chunk_index=result.chunk_index,
        text=preview,
        source_type=result.source_type,
        original_filename=result.original_filename,
        stored_path=result.stored_path,
        page=result.page,
        span_start=result.span_start,
        span_end=result.span_end,
        section=result.section,
        text_hash=result.text_hash,
        truncated=truncated,
        metadata=build_source_vault_search_metadata(result),
        score=result.score,
    )


def _wiki_package_projection() -> KnowledgePackageProjectionResponse:
    status = _wiki_router.wiki_status(user_id=None)
    manifest = status.model_dump()
    source_manifest_hash = str(status.source_manifest_hash or "unknown")
    indexed_source_manifest_hash = str(status.indexed_source_manifest_hash or "unknown")
    source_page_count = status.source_page_count
    indexed_page_count = status.indexed_page_count
    page_count = status.page_count
    load_status: PackageLoadStatus
    notes: list[str] = []
    if not status.enabled:
        load_status = "disabled"
        notes.append("Wiki APIs are disabled in the current runtime.")
    elif status.stale:
        load_status = "stale"
        notes.extend(status.warnings or ["Wiki manifest or index drift detected."])
    elif page_count > 0 or indexed_page_count > 0:
        load_status = "loaded"
    else:
        load_status = "missing"
    if status.manifest_drilldown.status not in {"aligned", "missing_indexed_entries"}:
        notes.append(f"wiki manifest drilldown: {status.manifest_drilldown.status}")
    available = bool(status.enabled)
    loaded = bool(status.enabled and not status.stale and (page_count > 0 or indexed_page_count > 0))
    return KnowledgePackageProjectionResponse(
        package_id="wiki",
        kind="wiki",
        title="Wiki",
        source_label="generated wiki pages",
        status=load_status,
        available=available,
        loaded=loaded,
        manifest_loaded=bool(indexed_source_manifest_hash not in {"", "unknown", "none"}),
        source_path=_wiki_package_source_path(),
        source_hash=source_manifest_hash,
        content_hash=indexed_source_manifest_hash if indexed_source_manifest_hash not in {"", "unknown", "none"} else "unknown",
        updated_at=_wiki_package_updated_at(status),
        read_endpoint="/api/wiki/status",
        search_endpoint="/api/wiki/search",
        notes=notes,
        manifest={
            "enabled": status.enabled,
            "page_count": page_count,
            "stale": status.stale,
            "integrity_status": status.integrity_status,
            "source_manifest_hash": source_manifest_hash,
            "indexed_source_manifest_hash": indexed_source_manifest_hash,
            "indexed_page_count": indexed_page_count,
            "source_page_count": source_page_count,
            "manifest_drilldown": status.manifest_drilldown.model_dump(),
            "runtime_consumers": [
                {
                    "consumer": "api.wiki.search",
                    "use": "Knowledge Runtime Pipeline searchable wiki refs",
                },
                {
                    "consumer": "literature.evidence_pack_build",
                    "use": "wiki joint-recall refs when the integrity gate is aligned",
                },
                {
                    "consumer": "literature.agent_resource_read",
                    "use": "bounded wiki resource loading",
                },
            ],
            "paths": status.paths,
        },
    )


def _source_vault_package_projection(vault: SourceVault) -> KnowledgePackageProjectionResponse:
    sources = vault.list_sources()
    manifest_summary = vault.manifest_summary()
    source_manifest_entries = [
        {
            "source_id": source.source_id,
            "source_hash": source.source_hash,
            "last_indexed_at": source.last_indexed_at,
        }
        for source in sources
    ]
    source_hash = hashlib.sha256(
        json.dumps(
            source_manifest_entries,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest() if sources else ""
    content_manifest = {
        "sources": [
            {
                "source_id": source.source_id,
                "source_hash": source.source_hash,
                "project_ids": list(source.project_ids),
                "chunker_version": source.chunker_version,
                "parser_version": source.parser_version,
            }
            for source in sources
        ],
        "chunk_count": manifest_summary.chunk_count,
        "artifact_count": manifest_summary.artifact_count,
        "chunk_artifact_hash": manifest_summary.chunk_artifact_hash,
    }
    content_hash = hashlib.sha256(
        json.dumps(
            content_manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    latest_updated_at = manifest_summary.latest_updated_at
    loaded_ref_count = manifest_summary.chunk_count if sources else 0
    notes = ["Source Vault is read-only in the knowledge registry."]
    if not sources:
        notes.append("No Source Vault sources are currently loaded.")
    runtime_consumers = [
        {
            "consumer": "literature.evidence_pack_build",
            "use": "project evidence pack retrieval",
        },
        {
            "consumer": "literature.agent_resource_read",
            "use": "bounded source-vault chunk resource loading",
        },
        {
            "consumer": "api.knowledge.source_vault.search",
            "use": "Knowledge Runtime Pipeline searchable chunk refs",
        },
    ]
    return KnowledgePackageProjectionResponse(
        package_id="source_vault",
        kind="source_vault",
        title="Source Vault",
        source_label="deduped originals and searchable chunks",
        status="loaded" if sources else "missing",
        available=True,
        loaded=bool(sources),
        manifest_loaded=True,
        source_path=str(vault.storage_root),
        source_hash=source_hash or "unknown",
        content_hash=content_hash or "unknown",
        updated_at=latest_updated_at,
        read_endpoint="/api/knowledge/source-vault",
        search_endpoint="/api/knowledge/source-vault/search",
        notes=notes,
        manifest={
            "total_sources": len(sources),
            "total_project_links": sum(len(source.project_ids) for source in sources),
            "chunk_count": manifest_summary.chunk_count,
            "artifact_count": manifest_summary.artifact_count,
            "chunk_artifact_hash": manifest_summary.chunk_artifact_hash,
            "manifest_hash": content_hash,
            "empty_runtime": not sources,
            "loaded_ref_count": loaded_ref_count,
            "required_for_loaded_context": [
                "at least one source_assets row",
                "at least one source_chunks row",
            ],
            "fts_enabled": vault.fts_enabled,
            "storage_root": str(vault.storage_root),
            "db_path": str(vault.db_path),
            "runtime_consumers": runtime_consumers,
        },
    )


def _academic_english_package_projection() -> KnowledgePackageProjectionResponse:
    status = academic_english_status()
    knowledge_sources = status.get("knowledge_sources", {}) if isinstance(status, dict) else {}
    artifacts = status.get("artifacts", {}) if isinstance(status, dict) else {}
    source_entry = knowledge_sources.get("academic_english_habits", {}) if isinstance(knowledge_sources, dict) else {}
    manifest_loaded = bool(status.get("manifest_loaded")) if isinstance(status, dict) else False
    artifact_hashes = sorted(
        str(value.get("sha256") or "")
        for value in artifacts.values()
        if isinstance(value, dict) and _has_known_hash(str(value.get("sha256") or ""))
    ) if isinstance(artifacts, dict) else []
    artifact_content_hash = (
        hashlib.sha256("\n".join(artifact_hashes).encode("utf-8")).hexdigest()
        if artifact_hashes
        else "unknown"
    )
    loaded = bool(source_entry.get("loaded")) and bool(artifact_hashes) if isinstance(source_entry, dict) else False
    load_status = str(source_entry.get("load_status") or "unknown") if isinstance(source_entry, dict) else "unknown"
    if not manifest_loaded:
        load_status = "missing"
    elif loaded and load_status not in {"loaded", "stale"}:
        load_status = "loaded"
    elif not loaded:
        load_status = "missing"
    latest_updated_at = str(status.get("built_at") or "unknown") if isinstance(status, dict) else "unknown"
    source_path = str(source_entry.get("source_ref") or source_entry.get("source_label") or "academic_english")
    source_hash = str(source_entry.get("content_hash") or "unknown")
    content_hash = artifact_content_hash if _has_known_hash(artifact_content_hash) else source_hash
    notes = []
    if not manifest_loaded:
        notes.append("Academic English manifest is missing or unreadable.")
    if not loaded:
        notes.append("Academic English policy source is not currently loaded.")
    if not artifact_hashes:
        notes.append("Academic English runtime artifacts are missing or have no content hashes.")
    runtime_consumers = [
        {
            "consumer": "api.knowledge.academic_english.search",
            "use": "Knowledge Runtime Pipeline searchable academic-English refs",
        },
        {
            "consumer": "literature.evidence_pack_build",
            "use": "academic-English shared ref retrieval",
        },
        {
            "consumer": "literature.agent_resource_read",
            "use": "bounded academic-English resource loading",
        },
    ]
    return KnowledgePackageProjectionResponse(
        package_id="academic_english",
        kind="academic_english",
        title="Academic English",
        source_label="generated discourse habits and phrase resources",
        status=load_status if load_status in {"loaded", "missing", "stale", "disabled", "unknown"} else "unknown",
        available=bool(status.get("available")) if isinstance(status, dict) else False,
        loaded=loaded,
        manifest_loaded=manifest_loaded,
        source_path=source_path,
        source_hash=source_hash,
        content_hash=content_hash,
        updated_at=latest_updated_at,
        read_endpoint="/api/knowledge/academic-english/status",
        search_endpoint="/api/knowledge/academic-english/search",
        notes=notes,
        manifest={
            "schema_version": status.get("schema_version") if isinstance(status, dict) else "",
            "builder_version": status.get("builder_version") if isinstance(status, dict) else "",
            "built_at": status.get("built_at") if isinstance(status, dict) else "",
            "counts": status.get("counts") if isinstance(status, dict) else {},
            "warnings": status.get("warnings") if isinstance(status, dict) else [],
            "errors": status.get("errors") if isinstance(status, dict) else [],
            "knowledge_sources": knowledge_sources,
            "artifacts": artifacts,
            "runtime_consumers": runtime_consumers,
            "raw_load_status": source_entry.get("load_status") if isinstance(source_entry, dict) else "",
        },
    )


def _bridge_lexicon_package_projection() -> KnowledgePackageProjectionResponse:
    status = get_bridge_lexicon_status()
    load_status = str(status.get("load_status") or "unknown") if isinstance(status, dict) else "unknown"
    loaded = bool(status.get("loaded")) if isinstance(status, dict) else False
    source_path = str(status.get("source_path") or "unknown") if isinstance(status, dict) else "unknown"
    source_hash = str(status.get("source_hash") or "unknown") if isinstance(status, dict) else "unknown"
    content_hash = str(status.get("content_hash") or "unknown") if isinstance(status, dict) else "unknown"
    updated_at = str(status.get("updated_at") or "unknown") if isinstance(status, dict) else "unknown"
    notes = []
    if load_status != "loaded":
        notes.append(f"Bridge lexicon load status is {load_status}.")
    normalized_status: PackageLoadStatus = "loaded" if load_status == "loaded" else "missing"
    return KnowledgePackageProjectionResponse(
        package_id="bridge_lexicon",
        kind="bridge_lexicon",
        title="Bridge Lexicon",
        source_label="CJK bridge expansion terms",
        status=normalized_status,
        available=True,
        loaded=loaded,
        manifest_loaded=True,
        source_path=source_path,
        source_hash=source_hash,
        content_hash=content_hash,
        updated_at=updated_at,
        read_endpoint="/api/knowledge/bridge-lexicon/read",
        search_endpoint="/api/knowledge/bridge-lexicon/search",
        notes=notes,
        manifest={
            "schema_version": status.get("schema_version") if isinstance(status, dict) else "",
            "entry_count": status.get("entry_count") if isinstance(status, dict) else 0,
            "runtime_consumers": status.get("runtime_consumers") if isinstance(status, dict) else [],
            "load_status": load_status,
            "raw_load_status": load_status,
        },
    )


def _academic_english_skill_package_projection() -> KnowledgePackageProjectionResponse:
    snapshot = skill_package_knowledge.load_skill_package_snapshot(
        skill_package_knowledge.ACADEMIC_ENGLISH_SKILL_PACKAGE_ID
    )
    notes = list(snapshot.warnings)
    if snapshot.loaded:
        notes.append("Repo-local Skill package metadata is read-only; scripts are not executed.")
    else:
        notes.append("Repo-local Skill package source is missing or not loadable.")
    normalized_status: PackageLoadStatus = "loaded" if snapshot.load_status == "loaded" else "missing"
    status_payload = snapshot.to_status_payload(include_chunks=True)
    return KnowledgePackageProjectionResponse(
        package_id=f"skill_package:{snapshot.package_id}",
        kind="skill_package",
        title=snapshot.title,
        source_label="repo-local Skill package source",
        status=normalized_status,
        available=True,
        loaded=snapshot.loaded,
        manifest_loaded=snapshot.manifest_loaded,
        source_path=snapshot.source_path,
        source_hash=snapshot.source_hash,
        content_hash=snapshot.content_hash,
        updated_at=snapshot.updated_at,
        read_endpoint=f"/api/knowledge/skill-packages/{snapshot.package_id}/status",
        search_endpoint=f"/api/knowledge/skill-packages/{snapshot.package_id}/search",
        notes=notes,
        manifest={
            "schema_version": status_payload["schema_version"],
            "package_id": snapshot.package_id,
            "version": snapshot.version,
            "skill_kind": snapshot.skill_kind,
            "display_group": snapshot.manifest.get("display_group"),
            "high_risk_flags": snapshot.manifest.get("high_risk_flags", []),
            "source_files": status_payload["source_files"],
            "chunk_count": status_payload["chunk_count"],
            "runtime_consumers": status_payload["runtime_consumers"],
            "load_status": snapshot.load_status,
        },
    )


def _scoring_rules_package_projection() -> KnowledgePackageProjectionResponse:
    snapshot = config_knowledge.load_scoring_rules_snapshot()
    notes = list(snapshot.warnings)
    if snapshot.loaded:
        notes.append("Scoring rules config is read-only; runtime scoring behavior is not changed by this registry.")
    elif not notes:
        notes.append(f"Scoring rules config load status is {snapshot.load_status}.")
    normalized_status: PackageLoadStatus
    if snapshot.load_status == "loaded":
        normalized_status = "loaded"
    elif snapshot.load_status == "missing":
        normalized_status = "missing"
    else:
        normalized_status = "unknown"
    status_payload = snapshot.to_status_payload(include_sections=True)
    return KnowledgePackageProjectionResponse(
        package_id=snapshot.package_id,
        kind="config",
        title=snapshot.title,
        source_label="repo-local JSON scoring configuration",
        status=normalized_status,
        available=True,
        loaded=snapshot.loaded,
        manifest_loaded=snapshot.manifest_loaded,
        source_path=snapshot.source_path,
        source_hash=snapshot.source_hash,
        content_hash=snapshot.content_hash,
        updated_at=snapshot.updated_at,
        read_endpoint="/api/knowledge/scoring-rules/status",
        search_endpoint="/api/knowledge/scoring-rules/search",
        notes=notes,
        manifest={
            "schema_version": status_payload["schema_version"],
            "config_id": snapshot.config_id,
            "version": snapshot.version,
            "last_updated": snapshot.last_updated,
            "section_count": status_payload["section_count"],
            "sections": status_payload["sections"],
            "runtime_consumers": status_payload["runtime_consumers"],
            "load_status": snapshot.load_status,
            "raw_load_status": snapshot.load_status,
        },
    )


def _product_docs_package_projection() -> KnowledgePackageProjectionResponse:
    snapshot = product_docs_knowledge.load_product_docs_snapshot()
    notes = list(snapshot.warnings)
    if snapshot.loaded:
        notes.append("Product documentation is read-only and loaded as bounded Markdown chunks.")
    elif not notes:
        notes.append(f"Product documentation load status is {snapshot.load_status}.")
    normalized_status: PackageLoadStatus
    if snapshot.load_status == "loaded":
        normalized_status = "loaded"
    elif snapshot.load_status == "missing":
        normalized_status = "missing"
    else:
        normalized_status = "unknown"
    status_payload = snapshot.to_status_payload(include_chunks=True)
    return KnowledgePackageProjectionResponse(
        package_id=snapshot.package_id,
        kind="product_docs",
        title=snapshot.title,
        source_label="repo-local README and product docs",
        status=normalized_status,
        available=True,
        loaded=snapshot.loaded,
        manifest_loaded=snapshot.manifest_loaded,
        source_path=snapshot.source_path,
        source_hash=snapshot.source_hash,
        content_hash=snapshot.content_hash,
        updated_at=snapshot.updated_at,
        read_endpoint="/api/knowledge/product-docs/status",
        search_endpoint="/api/knowledge/product-docs/search",
        notes=notes,
        manifest={
            "schema_version": status_payload["schema_version"],
            "source_count": snapshot.manifest.get("source_count", 0),
            "loaded_source_count": snapshot.manifest.get("loaded_source_count", 0),
            "chunk_count": status_payload["chunk_count"],
            "source_paths": snapshot.manifest.get("source_paths", []),
            "runtime_consumers": status_payload["runtime_consumers"],
            "load_status": snapshot.load_status,
            "raw_load_status": snapshot.load_status,
        },
    )


def _wiki_package_source_path() -> str:
    generated_root = _wiki_router.wiki_generated_root()
    try:
        return str(Path(generated_root).resolve())
    except OSError:
        return str(generated_root)


def _wiki_package_updated_at(status: Any) -> str:
    updated_at = ""
    try:
        paths = status.paths if hasattr(status, "paths") else {}
        candidate_paths = [
            str(paths.get("query_index") or ""),
            str(paths.get("wiki_root") or ""),
        ]
        for candidate in candidate_paths:
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists():
                return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace(
                    "+00:00", "Z"
                )
    except OSError:
        pass
    return updated_at or "unknown"


_PIPELINE_STEPS = [
    "authoritative_source",
    "builder_or_loader",
    "structured_runtime_artifact",
    "searchable_index",
    "evidence_or_resource_ref",
    "bounded_context_loading",
    "prompt_assembly_context_receipt",
    "qa_agent_actual_loading_gate",
    "manifest_audit_test_proof",
]


def _knowledge_package_projections(vault: SourceVault) -> list[KnowledgePackageProjectionResponse]:
    """Return the package registry rows shared by registry and conformance routes."""

    return [
        _wiki_package_projection(),
        _source_vault_package_projection(vault),
        _academic_english_package_projection(),
        _bridge_lexicon_package_projection(),
        _academic_english_skill_package_projection(),
        _scoring_rules_package_projection(),
        _product_docs_package_projection(),
    ]


def _sha256_text(value: str) -> str:
    """Return the stable SHA-256 hex digest for a UTF-8 text boundary."""

    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _normalize_context_ref_id(value: str) -> str:
    """Return a non-empty bounded ref id safe for agent-bridge resolution."""

    ref_id = str(value or "").strip()
    if not ref_id:
        raise HTTPException(status_code=422, detail="ref_ids must not contain empty refs")
    if len(ref_id) > 300:
        raise HTTPException(status_code=422, detail="ref_ids items must be at most 300 characters")
    if any(ord(char) < 32 for char in ref_id):
        raise HTTPException(status_code=422, detail="ref_ids must not contain control characters")
    return ref_id


def _normalize_context_ref_ids(values: list[str]) -> list[str]:
    """Return bounded unique refs while preserving caller order."""

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        ref_id = _normalize_context_ref_id(value)
        if ref_id in seen:
            continue
        seen.add(ref_id)
        normalized.append(ref_id)
    if not normalized:
        raise HTTPException(status_code=422, detail="ref_ids must contain at least one non-empty ref")
    return normalized


def _metadata_text(metadata: dict[str, Any], *keys: str) -> str | None:
    """Return the first non-empty string metadata value from a safe allowlist."""

    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _context_resource_receipt(
    *,
    ref_id: str,
    project_id: str | None,
    max_chars: int,
) -> tuple[KnowledgeContextResourceReceiptResponse, str]:
    """Resolve one ref through the agent bridge and return receipt plus text."""

    kind, raw_id = _agent_bridge_router._split_ref_id(ref_id)
    resource = _agent_bridge_router._resolve_resource(kind, raw_id, project_id=project_id)
    content = str(resource.get("content") or "")
    returned_content = content[:max_chars]
    metadata = dict(resource.get("metadata") or {})
    if metadata.get("ref_id") is None:
        metadata["ref_id"] = ref_id
    read_endpoint = f"/api/agent-bridge/resource/{ref_id}"
    returned_chars = len(returned_content)
    total_chars = len(content)
    truncated = returned_chars < total_chars
    metadata["offset"] = 0
    metadata["returned_chars"] = returned_chars
    return (
        KnowledgeContextResourceReceiptResponse(
            ref_id=ref_id,
            kind=str(resource.get("kind") or kind),
            title=resource.get("title") if isinstance(resource.get("title"), str) else None,
            read_endpoint=read_endpoint,
            content_hash=_sha256_text(returned_content),
            source_hash=_metadata_text(metadata, "source_hash", "import_source_hash") or "unknown",
            package_content_hash=_metadata_text(metadata, "package_content_hash", "content_hash") or "unknown",
            source_path=_metadata_text(metadata, "source_path", "import_source_path"),
            span_start=metadata.get("span_start") if isinstance(metadata.get("span_start"), int) else None,
            span_end=metadata.get("span_end") if isinstance(metadata.get("span_end"), int) else None,
            returned_chars=returned_chars,
            total_chars=total_chars,
            max_chars=max_chars,
            truncated=truncated,
            cursor="0",
            next_cursor=str(returned_chars) if truncated else None,
            metadata=metadata,
        ),
        returned_content,
    )


def _context_block(receipt: KnowledgeContextResourceReceiptResponse, content: str) -> str:
    """Return the canonical text block whose hash proves prompt input."""

    return "\n".join(
        [
            f"ref_id: {receipt.ref_id}",
            f"kind: {receipt.kind}",
            f"title: {receipt.title or ''}",
            f"source_path: {receipt.source_path or ''}",
            f"content_hash: {receipt.content_hash}",
            "content:",
            content,
        ]
    ).strip()


def _build_context_receipt(request: KnowledgeContextReceiptRequest) -> KnowledgeContextReceiptResponse:
    """Build a hash-only receipt for bounded knowledge entering context."""

    prompt_name = request.prompt_name.strip()
    project_id = request.project_id.strip() if isinstance(request.project_id, str) and request.project_id.strip() else None
    ref_ids = _normalize_context_ref_ids(request.ref_ids)
    receipts: list[KnowledgeContextResourceReceiptResponse] = []
    blocks: list[str] = []
    for ref_id in ref_ids:
        receipt, content = _context_resource_receipt(
            ref_id=ref_id,
            project_id=project_id,
            max_chars=request.max_chars_per_ref,
        )
        receipts.append(receipt)
        blocks.append(_context_block(receipt, content))
    assembled_context = "\n\n---\n\n".join(blocks)
    prompt_payload = json.dumps(
        {
            "prompt_name": prompt_name,
            "project_id": project_id,
            "ref_ids": ref_ids,
            "assembled_context_hash": _sha256_text(assembled_context),
            "resource_read_receipts": [receipt.model_dump(mode="json") for receipt in receipts],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return KnowledgeContextReceiptResponse(
        schema_version="scholar-ai-knowledge-context-receipt/v1",
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        prompt_name=prompt_name,
        prompt_hash=_sha256_text(prompt_payload),
        assembled_context_hash=_sha256_text(assembled_context),
        assembled_context_char_count=len(assembled_context),
        assembled_context_preview=assembled_context[:4000],
        resource_read_receipts=receipts,
        provenance={
            "context_builder": "literature_assistant.core.routers.knowledge_router._build_context_receipt",
            "resource_reader": "literature_assistant.core.routers.agent_bridge_router",
            "mcp_tool": "literature.knowledge_context_receipt",
            "project_id": project_id,
            "ref_count": len(receipts),
            "max_chars_per_ref": request.max_chars_per_ref,
            "hash_algorithm": "sha256",
        },
    )


def _manifest_runtime_consumers(package: KnowledgePackageProjectionResponse) -> list[dict[str, str]]:
    raw_consumers = package.manifest.get("runtime_consumers") if isinstance(package.manifest, dict) else []
    if not isinstance(raw_consumers, list):
        return []
    consumers: list[dict[str, str]] = []
    for item in raw_consumers:
        if not isinstance(item, dict):
            continue
        consumer = str(item.get("consumer") or "").strip()
        usage = str(item.get("use") or item.get("usage") or "").strip()
        if consumer:
            consumers.append({"consumer": consumer, "use": usage})
    return consumers


def _manifest_count(package: KnowledgePackageProjectionResponse, *keys: str) -> int:
    for key in keys:
        value = package.manifest.get(key) if isinstance(package.manifest, dict) else None
        if isinstance(value, int) and not isinstance(value, bool):
            return max(value, 0)
    counts = package.manifest.get("counts") if isinstance(package.manifest, dict) else None
    if isinstance(counts, dict):
        for key in keys:
            aliases = [key]
            if key.endswith("_count"):
                base = key.removesuffix("_count")
                aliases.extend([base, f"{base}s"])
                if base.endswith("y"):
                    aliases.append(f"{base[:-1]}ies")
            for alias in aliases:
                value = counts.get(alias)
                if isinstance(value, int) and not isinstance(value, bool):
                    return max(value, 0)
    return 0


def _has_known_hash(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return bool(normalized and normalized not in {"unknown", "none", "missing"})


def _has_authoritative_source(package: KnowledgePackageProjectionResponse) -> bool:
    """Return whether the package exposes a traceable source independent of loaded refs."""

    if not _has_known_hash(package.source_hash):
        return False
    if package.kind == "wiki":
        return _manifest_count(package, "source_page_count", "page_count") > 0
    return package.loaded and package.manifest_loaded


def _loaded_ref_count(package: KnowledgePackageProjectionResponse) -> int:
    """Return runtime refs that can be searched and then read into bounded context."""

    if not package.loaded:
        return 0
    if package.kind == "wiki":
        return _manifest_count(package, "indexed_page_count")
    if package.kind == "source_vault":
        return _manifest_count(package, "chunk_count")
    return _manifest_count(package, "chunk_count", "section_count", "entry_count")


def _missing_loaded_refs(package: KnowledgePackageProjectionResponse) -> list[str]:
    """Return a package-specific missing-ref explanation for conformance rows."""

    missing: list[str] = []
    if not package.loaded:
        missing.append("loaded runtime knowledge package")
    if package.kind == "wiki":
        missing.append("indexed wiki refs")
        return missing
    if package.kind == "source_vault":
        missing.append("source-vault chunks")
        return missing
    missing.append("chunk_count, section_count, or entry_count")
    return missing


def _has_agent_bridge_consumer(consumers: list[dict[str, str]]) -> bool:
    return any(
        "agent_bridge_router" in item["consumer"] or item["consumer"] == "literature.agent_resource_read"
        for item in consumers
    )


def _has_mcp_consumer(consumers: list[dict[str, str]], package: KnowledgePackageProjectionResponse) -> bool:
    if any("agent_mcp_server" in item["consumer"] or item["consumer"].startswith("literature.") for item in consumers):
        return True
    return bool(_mcp_tools_for_package(package))


def _has_evidence_pack_consumer(consumers: list[dict[str, str]], package: KnowledgePackageProjectionResponse) -> bool:
    if any("evidence_pack" in item["consumer"] or "evidence_pack" in item["use"] for item in consumers):
        return True
    return package.kind in {"wiki", "source_vault", "academic_english", "skill_package", "config", "product_docs"}


def _resource_kind_label(package: KnowledgePackageProjectionResponse) -> str:
    if package.kind == "config":
        return "section"
    if package.kind == "bridge_lexicon":
        return "entry"
    return "chunk"


def _searchable_index_requirement(package: KnowledgePackageProjectionResponse) -> KnowledgeRuntimeConformanceItemResponse:
    loaded_ref_count = _loaded_ref_count(package)
    if package.search_endpoint and loaded_ref_count > 0:
        return KnowledgeRuntimeConformanceItemResponse(
            requirement="searchable_index",
            status="proved",
            evidence_level="runtime_projection",
            evidence_scope=["search_endpoint", "loaded_ref_count"],
            evidence=[package.search_endpoint, f"loaded_ref_count={loaded_ref_count}"],
        )
    if package.search_endpoint:
        return KnowledgeRuntimeConformanceItemResponse(
            requirement="searchable_index",
            status="blocked",
            evidence_level="runtime_projection",
            evidence_scope=["search_endpoint"],
            evidence=[package.search_endpoint],
            missing=_missing_loaded_refs(package),
        )
    return KnowledgeRuntimeConformanceItemResponse(
        requirement="searchable_index",
        status="pending",
        missing=["search_endpoint"],
    )


def _evidence_pack_requirement(
    package: KnowledgePackageProjectionResponse,
    consumers: list[dict[str, str]],
) -> KnowledgeRuntimeConformanceItemResponse:
    if package.kind == "bridge_lexicon":
        return KnowledgeRuntimeConformanceItemResponse(
            requirement="evidence_pack_ref_protocol",
            status="not_applicable",
            evidence=["Bridge lexicon supports bounded read but is not an evidence-pack retrieval source."],
        )
    loaded_ref_count = _loaded_ref_count(package)
    if _has_evidence_pack_consumer(consumers, package) and loaded_ref_count > 0:
        return KnowledgeRuntimeConformanceItemResponse(
            requirement="evidence_pack_ref_protocol",
            status="proved",
            evidence_level="runtime_projection",
            evidence_scope=["evidence_pack_consumer", "loaded_ref_count"],
            evidence=[
                "literature.evidence_pack_build",
                "read_endpoint == /api/agent-bridge/resource/{ref_id}",
                f"loaded_ref_count={loaded_ref_count}",
            ],
        )
    if _has_evidence_pack_consumer(consumers, package):
        return KnowledgeRuntimeConformanceItemResponse(
            requirement="evidence_pack_ref_protocol",
            status="blocked",
            evidence_level="runtime_projection",
            evidence_scope=["evidence_pack_consumer"],
            evidence=["literature.evidence_pack_build"],
            missing=_missing_loaded_refs(package),
        )
    return KnowledgeRuntimeConformanceItemResponse(
        requirement="evidence_pack_ref_protocol",
        status="pending",
        missing=["evidence-pack consumer"],
    )


def _chunk_or_ref_requirement(package: KnowledgePackageProjectionResponse) -> KnowledgeRuntimeConformanceItemResponse:
    chunk_count = _loaded_ref_count(package)
    if chunk_count > 0:
        return KnowledgeRuntimeConformanceItemResponse(
            requirement="chunk_or_ref_protocol",
            status="proved",
            evidence_scope=["runtime_manifest", "resource_ref_shape"],
            evidence=[f"{_resource_kind_label(package)}_count={chunk_count}", "ref_id", "read_endpoint"],
        )
    if package.loaded:
        return KnowledgeRuntimeConformanceItemResponse(
            requirement="chunk_or_ref_protocol",
            status="pending",
            evidence_scope=["runtime_manifest"],
            evidence=["package is loaded"],
            missing=_missing_loaded_refs(package),
        )
    return KnowledgeRuntimeConformanceItemResponse(
        requirement="chunk_or_ref_protocol",
        status="blocked",
        missing=_missing_loaded_refs(package),
    )


def _prompt_context_receipt_requirement(
    package: KnowledgePackageProjectionResponse,
    test_evidence: KnowledgeRuntimeTestEvidenceResponse,
) -> KnowledgeRuntimeConformanceItemResponse:
    """Return the context-receipt contract row for one knowledge package."""

    loaded_ref_count = _loaded_ref_count(package)
    if loaded_ref_count <= 0:
        return KnowledgeRuntimeConformanceItemResponse(
            requirement="prompt_assembly_context_receipt",
            status="blocked",
            evidence_level="runtime_projection",
            evidence_scope=["bounded_resource_read", "prompt_context_hash"],
            evidence=["/api/knowledge/context-receipt"],
            missing=_missing_loaded_refs(package),
        )
    if not test_evidence.context_receipt_test:
        return KnowledgeRuntimeConformanceItemResponse(
            requirement="prompt_assembly_context_receipt",
            status="pending",
            evidence_level="contract_evidence",
            evidence_scope=["bounded_resource_read", "prompt_context_hash"],
            evidence=["/api/knowledge/context-receipt"],
            missing=["focused context receipt test"],
        )
    return KnowledgeRuntimeConformanceItemResponse(
        requirement="prompt_assembly_context_receipt",
        status="proved",
        evidence_level="focused_test_evidence",
        evidence_scope=["bounded_resource_read", "prompt_context_hash", "context_receipt_test"],
        evidence=[
            "/api/knowledge/context-receipt",
            "literature.knowledge_context_receipt",
            "resource_read_receipts",
            "assembled_context_hash",
            f"loaded_ref_count={loaded_ref_count}",
        ],
    )


def _mcp_tools_for_package(package: KnowledgePackageProjectionResponse) -> list[str]:
    mapping: dict[str, list[str]] = {
        "wiki": [
            "literature.wiki_status",
            "literature.wiki_search",
            "literature.agent_resource_read",
            "literature.knowledge_context_receipt",
        ],
        "source_vault": [
            "literature.source_vault_status",
            "literature.source_vault_search",
            "literature.source_vault_read",
            "literature.evidence_pack_build",
            "literature.agent_resource_read",
            "literature.knowledge_context_receipt",
        ],
        "academic_english": [
            "literature.academic_english_status",
            "literature.academic_english_search",
            "literature.evidence_pack_build",
            "literature.agent_resource_read",
            "literature.knowledge_context_receipt",
        ],
        "bridge_lexicon": [
            "literature.bridge_lexicon_status",
            "literature.bridge_lexicon_read",
            "literature.bridge_lexicon_search",
            "literature.agent_resource_read",
            "literature.knowledge_context_receipt",
        ],
        "skill_package": [
            "literature.skill_package_status",
            "literature.skill_package_search",
            "literature.evidence_pack_build",
            "literature.agent_resource_read",
            "literature.knowledge_context_receipt",
        ],
        "config": [
            "literature.scoring_rules_status",
            "literature.scoring_rules_read",
            "literature.scoring_rules_search",
            "literature.evidence_pack_build",
            "literature.agent_resource_read",
            "literature.knowledge_context_receipt",
        ],
        "product_docs": [
            "literature.product_docs_status",
            "literature.product_docs_read",
            "literature.product_docs_search",
            "literature.evidence_pack_build",
            "literature.agent_resource_read",
            "literature.knowledge_context_receipt",
        ],
    }
    return list(mapping.get(package.kind, []))


def _test_evidence_for_package(package: KnowledgePackageProjectionResponse) -> KnowledgeRuntimeTestEvidenceResponse:
    mapping: dict[str, KnowledgeRuntimeTestEvidenceResponse] = {
        "wiki": KnowledgeRuntimeTestEvidenceResponse(
            focused_test_exists=True,
            source_edit_hash_test=True,
            context_receipt_test=True,
            evidence_pack_test=True,
            agent_resource_read_test=True,
            mcp_tool_test=True,
            test_nodes=[
                "tests/wiki/test_wiki_router.py::test_search_returns_wiki_knowledge_ref_readable_as_agent_resource",
                "tests/wiki/test_wiki_router.py::test_wiki_source_rebuild_search_resource_and_context_receipt_chain",
                "tests/test_evidence_pack_build_contract.py::test_evidence_pack_build_reports_wiki_project_joint_recall",
                "agent_mcp_server/tests/test_runtime_tools.py::test_wiki_search_returns_refs_only",
                "agent_mcp_server/tests/test_server.py::test_server_registers_source_and_runtime_tools",
            ],
        ),
        "source_vault": KnowledgeRuntimeTestEvidenceResponse(
            focused_test_exists=True,
            source_edit_hash_test=True,
            context_receipt_test=True,
            evidence_pack_test=True,
            agent_resource_read_test=True,
            mcp_tool_test=True,
            test_nodes=[
                "tests/test_knowledge_router.py::test_source_vault_source_edit_rebuilds_hash_ref_resource_and_context_receipt",
                "tests/test_knowledge_router.py::test_source_vault_search_result_is_readable_as_agent_resource",
                "tests/test_knowledge_router.py::test_knowledge_context_receipt_covers_ref_bearing_knowledge_families",
                "tests/test_agent_bridge_router.py::test_agent_bridge_resource_reader_reads_source_vault_ref",
                "tests/test_evidence_pack_build_contract.py::test_evidence_pack_build_adds_source_vault_shared_resource_refs",
                "agent_mcp_server/tests/test_runtime_tools.py::test_source_vault_search_returns_refs_only",
            ],
        ),
        "academic_english": KnowledgeRuntimeTestEvidenceResponse(
            focused_test_exists=True,
            source_edit_hash_test=True,
            context_receipt_test=True,
            evidence_pack_test=True,
            agent_resource_read_test=True,
            mcp_tool_test=True,
            test_nodes=[
                "extension_packages/skills/academic-english-discourse/tests/test_build_discourse_db.py::test_built_artifact_is_consumed_by_runtime_search_and_read",
                "tests/test_knowledge_router.py::test_academic_english_artifact_edit_updates_search_resource_and_context_receipt",
                "tests/test_agent_bridge_router.py::test_agent_bridge_resource_reader_reads_academic_english_ref",
                "tests/test_evidence_pack_build_contract.py::test_evidence_pack_build_adds_academic_english_shared_resource_refs",
                "agent_mcp_server/tests/test_runtime_tools.py::test_academic_english_search_returns_refs_only",
            ],
        ),
        "skill_package": KnowledgeRuntimeTestEvidenceResponse(
            focused_test_exists=True,
            source_edit_hash_test=True,
            context_receipt_test=True,
            evidence_pack_test=True,
            agent_resource_read_test=True,
            mcp_tool_test=True,
            test_nodes=[
                "tests/test_knowledge_router.py::test_skill_package_source_edit_rebuilds_search_resource_and_context_receipt",
                "tests/test_agent_bridge_router.py::test_agent_bridge_resource_reader_reads_skill_package_ref",
                "tests/test_evidence_pack_build_contract.py::test_evidence_pack_build_adds_skill_package_shared_resource_refs",
                "agent_mcp_server/tests/test_runtime_tools.py::test_skill_package_search_returns_refs_only",
            ],
        ),
        "config": KnowledgeRuntimeTestEvidenceResponse(
            focused_test_exists=True,
            source_edit_hash_test=True,
            context_receipt_test=True,
            evidence_pack_test=True,
            agent_resource_read_test=True,
            mcp_tool_test=True,
            test_nodes=[
                "tests/test_knowledge_router.py::test_scoring_rules_source_edit_rebuilds_search_resource_and_context_receipt",
                "tests/test_agent_bridge_router.py::test_agent_bridge_resource_reader_reads_scoring_rules_ref",
                "tests/test_evidence_pack_build_contract.py::test_evidence_pack_build_adds_scoring_rules_shared_resource_refs",
                "agent_mcp_server/tests/test_runtime_tools.py::test_scoring_rules_search_returns_refs_only",
            ],
        ),
        "product_docs": KnowledgeRuntimeTestEvidenceResponse(
            focused_test_exists=True,
            source_edit_hash_test=True,
            context_receipt_test=True,
            evidence_pack_test=True,
            agent_resource_read_test=True,
            mcp_tool_test=True,
            test_nodes=[
                "tests/test_knowledge_router.py::test_product_docs_source_edit_rebuilds_search_resource_and_context_receipt",
                "tests/test_knowledge_router.py::test_knowledge_context_receipt_proves_product_docs_ref_enters_bounded_context",
                "tests/test_agent_bridge_router.py::test_agent_bridge_resource_reader_reads_product_docs_ref",
                "tests/test_evidence_pack_build_contract.py::test_evidence_pack_build_adds_product_docs_shared_resource_refs",
                "agent_mcp_server/tests/test_runtime_tools.py::test_product_docs_search_returns_refs_only",
            ],
        ),
        "bridge_lexicon": KnowledgeRuntimeTestEvidenceResponse(
            focused_test_exists=True,
            source_edit_hash_test=True,
            context_receipt_test=True,
            agent_resource_read_test=True,
            mcp_tool_test=True,
            test_nodes=[
                "tests/test_knowledge_router.py::test_bridge_lexicon_source_edit_rebuilds_search_resource_and_context_receipt",
                "tests/test_agent_bridge_router.py::test_agent_bridge_resource_reader_reads_bridge_lexicon_ref",
                "tests/test_knowledge_router.py::test_knowledge_runtime_conformance_marks_prompt_context_receipt_proved",
                "agent_mcp_server/tests/test_runtime_tools.py::test_bridge_lexicon_search_returns_refs_only",
                "agent_mcp_server/tests/test_runtime_tools.py::test_bridge_lexicon_read_uses_knowledge_endpoint",
            ],
        ),
    }
    return mapping.get(package.kind, KnowledgeRuntimeTestEvidenceResponse())


def _manifest_audit_test_requirement(
    package: KnowledgePackageProjectionResponse,
    test_evidence: KnowledgeRuntimeTestEvidenceResponse,
) -> KnowledgeRuntimeConformanceItemResponse:
    required_evidence = {
        "source_edit_hash_test": test_evidence.source_edit_hash_test,
        "context_receipt_test": test_evidence.context_receipt_test,
        "agent_resource_read_test": test_evidence.agent_resource_read_test,
        "mcp_tool_test": test_evidence.mcp_tool_test,
    }
    if package.kind != "bridge_lexicon":
        required_evidence["evidence_pack_test"] = test_evidence.evidence_pack_test
    missing = [key for key, enabled in required_evidence.items() if not enabled]
    if not test_evidence.focused_test_exists:
        missing.insert(0, f"focused tests for {package.package_id}")
    if not test_evidence.test_nodes:
        missing.append("pytest node ids for focused evidence")
    if not missing:
        return KnowledgeRuntimeConformanceItemResponse(
            requirement="manifest_audit_test_proof",
            status="proved",
            evidence_level="focused_test_evidence",
            evidence_scope=[
                key
                for key, enabled in {
                    **required_evidence,
                    "test_nodes": True,
                }.items()
                if enabled
            ],
            evidence=test_evidence.test_nodes,
        )
    return KnowledgeRuntimeConformanceItemResponse(
        requirement="manifest_audit_test_proof",
        status="pending",
        evidence_level="focused_test_evidence",
        evidence_scope=[key for key, enabled in required_evidence.items() if enabled],
        evidence=test_evidence.test_nodes,
        missing=missing,
    )


def _conformance_items(
    package: KnowledgePackageProjectionResponse,
    consumers: list[dict[str, str]],
    test_evidence: KnowledgeRuntimeTestEvidenceResponse,
) -> list[KnowledgeRuntimeConformanceItemResponse]:
    loaded_ref_count = _loaded_ref_count(package)
    source_status: ConformanceStatus = "proved" if _has_authoritative_source(package) else "blocked"
    artifact_status: ConformanceStatus = (
        "proved"
        if package.loaded and _has_known_hash(package.content_hash)
        else "blocked"
    )
    bounded_read_status: ConformanceStatus
    if package.read_endpoint and loaded_ref_count > 0:
        bounded_read_status = "proved"
    elif package.read_endpoint:
        bounded_read_status = "blocked"
    else:
        bounded_read_status = "blocked"
    agent_read_status: ConformanceStatus
    if _has_agent_bridge_consumer(consumers) and loaded_ref_count > 0:
        agent_read_status = "proved"
    elif _has_agent_bridge_consumer(consumers):
        agent_read_status = "blocked"
    else:
        agent_read_status = "pending"
    mcp_status: ConformanceStatus = "proved" if _has_mcp_consumer(consumers, package) else "pending"
    return [
        KnowledgeRuntimeConformanceItemResponse(
            requirement="authoritative_source",
            status=source_status,
            evidence_scope=["runtime_status", "source_hash", "manifest"],
            evidence=[package.source_path, package.source_hash] if source_status == "proved" else [],
            missing=[] if source_status == "proved" else ["loaded source_path/source_hash/manifest"],
        ),
        KnowledgeRuntimeConformanceItemResponse(
            requirement="structured_runtime_artifact",
            status=artifact_status,
            evidence_scope=["runtime_status", "content_hash"],
            evidence=[package.content_hash] if artifact_status == "proved" else [],
            missing=[] if artifact_status == "proved" else ["loaded content_hash/runtime artifact"],
        ),
        _searchable_index_requirement(package),
        _chunk_or_ref_requirement(package),
        KnowledgeRuntimeConformanceItemResponse(
            requirement="bounded_context_loading",
            status=bounded_read_status,
            evidence_level="runtime_projection",
            evidence_scope=["read_endpoint", "loaded_ref_count"],
            evidence=(
                [package.read_endpoint, f"loaded_ref_count={loaded_ref_count}"]
                if bounded_read_status == "proved"
                else ([package.read_endpoint] if package.read_endpoint else [])
            ),
            missing=[] if bounded_read_status == "proved" else _missing_loaded_refs(package),
        ),
        KnowledgeRuntimeConformanceItemResponse(
            requirement="agent_resource_read",
            status=agent_read_status,
            evidence_level="runtime_projection",
            evidence_scope=["agent_bridge_router", "bounded_resource_read", "loaded_ref_count"],
            evidence=(
                ["/api/agent-bridge/resource/{ref_id}", f"loaded_ref_count={loaded_ref_count}"]
                if agent_read_status == "proved"
                else []
            ),
            missing=(
                []
                if agent_read_status == "proved"
                else (
                    _missing_loaded_refs(package)
                    if _has_agent_bridge_consumer(consumers)
                    else ["agent_bridge_router runtime consumer"]
                )
            ),
        ),
        _evidence_pack_requirement(package, consumers),
        KnowledgeRuntimeConformanceItemResponse(
            requirement="mcp_entry",
            status=mcp_status,
            evidence_level="contract_evidence",
            evidence_scope=["mcp_tool"],
            evidence=_mcp_tools_for_package(package) if mcp_status == "proved" else [],
            missing=[] if mcp_status == "proved" else ["MCP runtime tool"],
        ),
        _prompt_context_receipt_requirement(package, test_evidence),
        _manifest_audit_test_requirement(package, test_evidence),
    ]


def _overall_conformance_status(items: list[KnowledgeRuntimeConformanceItemResponse]) -> ConformanceStatus:
    statuses = {item.status for item in items if item.status != "not_applicable"}
    if "blocked" in statuses:
        return "blocked"
    if "pending" in statuses:
        return "pending"
    return "proved"


def _live_smoke_schema_errors(exc: ValidationError) -> list[str]:
    """Return stable, machine-readable schema errors for artifact audit."""

    errors: list[str] = []
    for item in exc.errors():
        location = ".".join(str(part) for part in item.get("loc", ())) or "artifact"
        message = str(item.get("msg") or "invalid")
        errors.append(f"artifact.schema.{location}: {message}")
    return errors or ["artifact.schema.valid"]


def _live_smoke_contract_errors(summary: LiveContextReceiptSmokeSummary) -> list[str]:
    """Return unmet proof checks for the actual-loading gate."""

    errors: list[str] = []
    evidence = summary.chatEvidence
    tool_names = set(evidence.toolNames)
    required_tools = set(_ACTUAL_LOADING_REQUIRED_TOOLS)
    if summary.verdict != "ok":
        errors.append("artifact.verdict.ok")
    if summary.statusCode != 200:
        errors.append("artifact.status_code.200")
    if evidence.usedRequiredTools is not True:
        errors.append("artifact.required_tools.used")
    if not required_tools.issubset(tool_names):
        errors.append("artifact.required_tools.names")
    if evidence.receiptHashVisibleInToolPreview is not True:
        errors.append("artifact.receipt_hash.preview")
    if evidence.finalAnswerIncludesReceiptHash is not True:
        errors.append("artifact.receipt_hash.final_answer")
    if evidence.queryHashMatchesDirectReceipt is not True:
        errors.append("artifact.receipt_hash.query_matches_direct")
    if not summary.directReceipt.assembledContextHash:
        errors.append("artifact.direct_receipt.assembled_context_hash")
    return errors


def _provider_capabilities_path() -> Path:
    """Return the persisted provider capability store path."""

    return runtime_state_path(_PROVIDER_CAPABILITIES_ARTIFACT_NAME)


def _next_safe_local_actions(*action_groups: tuple[str, ...]) -> list[str]:
    """Return a bounded, duplicate-free action list for recovery surfaces."""

    actions: list[str] = []
    for group in action_groups:
        for action in group:
            if action not in actions:
                actions.append(action)
            if len(actions) >= 8:
                return actions
    return actions


def _actual_loading_next_safe_actions(
    provider_preflight: KnowledgeRuntimeProviderPreflightResponse,
    *action_groups: tuple[str, ...],
) -> list[str]:
    """Return recovery actions that keep provider blockers visible at the top gate."""

    provider_actions: tuple[str, ...] = ()
    if provider_preflight.status != "proved":
        provider_actions = tuple(provider_preflight.next_safe_local_actions)
    return _next_safe_local_actions(
        *action_groups,
        provider_actions,
        _ACTUAL_LOADING_BASE_ACTIONS,
    )


def _provider_preflight_record_response(
    record: ProviderCapabilityRecord,
) -> KnowledgeRuntimeProviderPreflightRecordResponse:
    """Return one redacted provider preflight record for API/UI use."""

    return KnowledgeRuntimeProviderPreflightRecordResponse(**record.to_dict())


def _provider_preflight_status_counts(records: list[ProviderCapabilityRecord]) -> dict[str, int]:
    """Return bounded status counts for provider recovery displays."""

    counts: dict[str, int] = {}
    for record in records:
        status = str(record.status or "unknown").strip() or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _provider_preflight_gate() -> KnowledgeRuntimeProviderPreflightResponse:
    """Return the provider tool-call preflight gate used before live loading."""

    artifact = _provider_capabilities_path()
    artifact_text = str(artifact)
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not artifact.exists():
        return KnowledgeRuntimeProviderPreflightResponse(
            status="pending",
            evidence_level="contract_evidence",
            artifact_path=artifact_text,
            artifact_exists=False,
            artifact_schema_valid=False,
            checked_at=checked_at,
            record_count=0,
            evidence_scope=list(_PROVIDER_PREFLIGHT_SCOPE),
            missing=["provider tool-call capability preflight record"],
            next_safe_local_actions=_next_safe_local_actions(_PROVIDER_PREFLIGHT_PENDING_ACTIONS),
            claim_boundary=(
                "No provider capability preflight record is present; live actual-loading "
                "must not be claimed until a configured provider proves forced tool calls."
            ),
        )
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        validation_errors = [f"provider_preflight.json.readable: {exc.__class__.__name__}"]
        return KnowledgeRuntimeProviderPreflightResponse(
            status="blocked",
            evidence_level="contract_evidence",
            artifact_path=artifact_text,
            artifact_exists=True,
            artifact_schema_valid=False,
            checked_at=checked_at,
            record_count=0,
            evidence_scope=list(_PROVIDER_PREFLIGHT_SCOPE),
            evidence=[_PROVIDER_CAPABILITIES_ARTIFACT_REF],
            missing=validation_errors,
            validation_errors=validation_errors,
            next_safe_local_actions=_next_safe_local_actions(_PROVIDER_PREFLIGHT_SCHEMA_ACTIONS),
            claim_boundary="Provider capability state exists, but cannot be parsed as JSON.",
        )
    records_payload = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records_payload, dict):
        return KnowledgeRuntimeProviderPreflightResponse(
            status="blocked",
            evidence_level="contract_evidence",
            artifact_path=artifact_text,
            artifact_exists=True,
            artifact_schema_valid=False,
            checked_at=checked_at,
            record_count=0,
            evidence_scope=list(_PROVIDER_PREFLIGHT_SCOPE),
            evidence=[_PROVIDER_CAPABILITIES_ARTIFACT_REF],
            missing=["provider_preflight.records object"],
            validation_errors=["provider_preflight.records: must be an object"],
            next_safe_local_actions=_next_safe_local_actions(_PROVIDER_PREFLIGHT_SCHEMA_ACTIONS),
            claim_boundary="Provider capability state exists, but does not match the preflight store schema.",
        )

    records: list[ProviderCapabilityRecord] = []
    validation_errors: list[str] = []
    for key, raw_record in records_payload.items():
        if not isinstance(raw_record, dict):
            validation_errors.append(f"provider_preflight.records.{key}: must be an object")
            continue
        try:
            records.append(ProviderCapabilityRecord.from_dict(raw_record))
        except ValueError as exc:
            validation_errors.append(f"provider_preflight.records.{key}: {exc}")
    if validation_errors:
        return KnowledgeRuntimeProviderPreflightResponse(
            status="blocked",
            evidence_level="contract_evidence",
            artifact_path=artifact_text,
            artifact_exists=True,
            artifact_schema_valid=False,
            checked_at=checked_at,
            record_count=len(records),
            records=[_provider_preflight_record_response(record) for record in records],
            evidence_scope=list(_PROVIDER_PREFLIGHT_SCOPE),
            evidence=[_PROVIDER_CAPABILITIES_ARTIFACT_REF],
            missing=validation_errors,
            validation_errors=validation_errors,
            next_safe_local_actions=_next_safe_local_actions(_PROVIDER_PREFLIGHT_SCHEMA_ACTIONS),
            claim_boundary="Provider capability state contains invalid records.",
        )
    if not records:
        return KnowledgeRuntimeProviderPreflightResponse(
            status="pending",
            evidence_level="contract_evidence",
            artifact_path=artifact_text,
            artifact_exists=True,
            artifact_schema_valid=True,
            checked_at=checked_at,
            record_count=0,
            evidence_scope=list(_PROVIDER_PREFLIGHT_SCOPE),
            evidence=[_PROVIDER_CAPABILITIES_ARTIFACT_REF],
            missing=["at least one provider tool-call capability record"],
            next_safe_local_actions=_next_safe_local_actions(_PROVIDER_PREFLIGHT_PENDING_ACTIONS),
            claim_boundary="Provider capability state exists, but no provider/model endpoint has been probed.",
        )

    ordered_records = sorted(records, key=lambda record: record.last_probe_at or "", reverse=True)
    latest_status = ordered_records[0].status or "unknown"
    response_records = [_provider_preflight_record_response(record) for record in ordered_records]
    status_counts = _provider_preflight_status_counts(records)
    auth_required_count = status_counts.get("auth_required", 0)
    tool_call_ok_count = sum(1 for record in records if record.tool_call_ok)
    if any(record.tool_call_ok for record in records):
        return KnowledgeRuntimeProviderPreflightResponse(
            status="proved",
            evidence_level="focused_test_evidence",
            artifact_path=artifact_text,
            artifact_exists=True,
            artifact_schema_valid=True,
            checked_at=checked_at,
            record_count=len(records),
            latest_status=latest_status,
            status_counts=status_counts,
            auth_required_count=auth_required_count,
            tool_call_ok_count=tool_call_ok_count,
            provider_ready_for_authorized_live_smoke=True,
            records=response_records,
            evidence_scope=list(_PROVIDER_PREFLIGHT_SCOPE),
            evidence=[
                _PROVIDER_CAPABILITIES_ARTIFACT_REF,
                "provider_tool_call_status=tool_call_ok",
            ],
            next_safe_local_actions=_next_safe_local_actions(_PROVIDER_PREFLIGHT_PROVED_ACTIONS),
            claim_boundary=(
                "At least one provider/model endpoint has proven forced tool calls; "
                "actual-loading still requires a separate live context-receipt smoke artifact."
            ),
        )

    auth_required = any(record.status == "auth_required" for record in records)
    missing = ["provider_tool_call_status=tool_call_ok"]
    if auth_required:
        missing.append("valid provider credentials before live actual-loading smoke")
    return KnowledgeRuntimeProviderPreflightResponse(
        status="blocked" if auth_required else "pending",
        evidence_level="contract_evidence",
        artifact_path=artifact_text,
        artifact_exists=True,
        artifact_schema_valid=True,
        checked_at=checked_at,
        record_count=len(records),
        latest_status=latest_status,
        status_counts=status_counts,
        auth_required_count=auth_required_count,
        tool_call_ok_count=tool_call_ok_count,
        provider_ready_for_authorized_live_smoke=False,
        records=response_records,
        evidence_scope=list(_PROVIDER_PREFLIGHT_SCOPE),
        evidence=[
            _PROVIDER_CAPABILITIES_ARTIFACT_REF,
            f"latest_provider_tool_call_status={latest_status}",
        ],
        missing=missing,
        next_safe_local_actions=_next_safe_local_actions(
            _PROVIDER_PREFLIGHT_AUTH_BLOCKED_ACTIONS if auth_required else _PROVIDER_PREFLIGHT_PENDING_ACTIONS,
            _PROVIDER_PREFLIGHT_PENDING_ACTIONS,
        ),
        claim_boundary=(
            "Provider preflight has not proven forced tool calls; Knowledge Runtime "
            "actual-loading remains blocked before any live model-context claim."
        ),
    )


def _provider_preflight_value(value: str) -> str:
    """Return the comparison form for redacted provider endpoint fields."""

    return str(value or "").strip().lower()


def _provider_preflight_match_requirement(summary: LiveContextReceiptSmokeSummary) -> str:
    """Return the endpoint-specific proof requirement for one live artifact."""

    provider = str(summary.provider or "unknown").strip() or "unknown"
    base_host = str(summary.baseHost or "unknown").strip() or "unknown"
    model = str(summary.model or "unknown").strip() or "unknown"
    return (
        "provider_preflight matching "
        f"provider={provider} baseHost={base_host} model={model} with tool_call_ok"
    )


def _provider_preflight_proves_live_summary(
    summary: LiveContextReceiptSmokeSummary,
    provider_preflight: KnowledgeRuntimeProviderPreflightResponse,
) -> bool:
    """Return whether preflight proves the exact provider endpoint in the artifact."""

    provider = _provider_preflight_value(summary.provider)
    base_host = _provider_preflight_value(summary.baseHost)
    model = _provider_preflight_value(summary.model)
    if not provider or not base_host or not model:
        return False
    if "unknown" in {provider, base_host, model}:
        return False
    for record in provider_preflight.records:
        if record.status != "tool_call_ok" or not record.forced_tool_choice_ok:
            continue
        if (
            _provider_preflight_value(record.provider) == provider
            and _provider_preflight_value(record.base_url_host) == base_host
            and _provider_preflight_value(record.model) == model
        ):
            return True
    return False


def _actual_loading_recovery_state(
    gate: KnowledgeRuntimeActualLoadingGateResponse,
) -> KnowledgeRuntimeActualLoadingRecoveryResponse:
    """Return typed recovery state without parsing human action text."""

    provider_ready = gate.provider_preflight.status == "proved"
    blocked_by: list[str] = []
    state = "proved_live_actual_loading"
    if gate.status != "proved":
        if not provider_ready:
            latest = gate.provider_preflight.latest_status or gate.provider_preflight.status
            blocked_by.append(f"provider_preflight:{gate.provider_preflight.status}:{latest}")
        if not gate.artifact_exists:
            blocked_by.append("live_smoke_artifact:missing")
        elif not gate.artifact_schema_valid:
            blocked_by.append("live_smoke_artifact:invalid_schema")
        elif not gate.artifact_contract_valid:
            blocked_by.append("live_smoke_artifact:contract_incomplete")
        elif provider_ready:
            blocked_by.append("provider_preflight:endpoint_mismatch")
        if not blocked_by:
            blocked_by = list(gate.missing[:8])
        if not provider_ready and not gate.artifact_exists:
            state = "blocked_provider_preflight_and_missing_live_smoke"
        elif not provider_ready and not gate.artifact_schema_valid:
            state = "blocked_provider_preflight_and_invalid_live_smoke_artifact"
        elif not provider_ready and not gate.artifact_contract_valid:
            state = "blocked_provider_preflight_and_incomplete_live_smoke_contract"
        elif not provider_ready:
            state = "blocked_provider_preflight"
        elif not gate.artifact_exists:
            state = "blocked_missing_live_smoke"
        elif not gate.artifact_schema_valid:
            state = "blocked_invalid_live_smoke_artifact"
        elif not gate.artifact_contract_valid:
            state = "blocked_incomplete_live_smoke_contract"
        elif gate.missing:
            state = "blocked_provider_endpoint_match"
        else:
            state = "blocked_unclassified"
    return KnowledgeRuntimeActualLoadingRecoveryResponse(
        state=state,
        blocked_by=list(dict.fromkeys(blocked_by))[:8],
        recovery_refs=[
            KnowledgeRuntimeRecoveryRefResponse(
                ref_type="conformance_endpoint",
                ref="/api/knowledge/runtime-conformance",
                status=gate.status,
                method="GET",
                access_mode="read_only",
                required_before_completion=True,
            ),
            KnowledgeRuntimeRecoveryRefResponse(
                ref_type="provider_preflight_artifact",
                ref=gate.provider_preflight.artifact_ref,
                status=gate.provider_preflight.status,
                method="READ",
                access_mode="local_artifact",
                required_before_completion=True,
            ),
            KnowledgeRuntimeRecoveryRefResponse(
                ref_type="live_smoke_artifact",
                ref=gate.artifact_ref,
                status=gate.verdict,
                method="READ",
                access_mode="local_artifact",
                required_before_completion=True,
            ),
            KnowledgeRuntimeRecoveryRefResponse(
                ref_type="provider_preflight_endpoint",
                ref="/api/chat/tool-capability/test",
                status="requires_configured_credentials" if not provider_ready else "already_proved",
                method="POST",
                access_mode="authorized_provider_preflight",
                required_before_completion=not provider_ready,
                requires_authorization=not provider_ready,
            ),
            KnowledgeRuntimeRecoveryRefResponse(
                ref_type="live_smoke_harness",
                ref="tests/live_api_chat_knowledge_context_receipt_smoke.py",
                status="requires_explicit_authorization" if gate.status != "proved" else "already_proved",
                method="RUN",
                access_mode="explicit_live_provider_smoke",
                required_before_completion=gate.status != "proved",
                requires_authorization=gate.status != "proved",
            ),
        ],
        provider_ready_for_authorized_live_smoke=provider_ready,
        completion_requires_authorized_live_smoke=gate.status != "proved",
    )


def _actual_loading_gate() -> KnowledgeRuntimeActualLoadingGateResponse:
    """Return the live QA/model loading proof gate for the runtime pipeline."""

    artifact = output_path(_LIVE_CONTEXT_RECEIPT_SMOKE_ARTIFACT_NAME)
    artifact_text = str(artifact)
    artifact_ref = _LIVE_CONTEXT_RECEIPT_SMOKE_ARTIFACT_REF
    artifact_checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    provider_preflight = _provider_preflight_gate()
    if not artifact.exists():
        return KnowledgeRuntimeActualLoadingGateResponse(
            status="blocked",
            evidence_level="contract_evidence",
            artifact_path=artifact_text,
            artifact_ref=artifact_ref,
            artifact_exists=False,
            artifact_schema_valid=False,
            artifact_contract_valid=False,
            artifact_checked_at=artifact_checked_at,
            verdict="missing_artifact",
            evidence_scope=list(_ACTUAL_LOADING_GATE_SCOPE),
            missing=[
                "authorized live provider smoke artifact with verdict=ok",
                "LITASSIST_RUN_LIVE_CONTEXT_RECEIPT_SMOKE or --allow-live-provider-call",
            ],
            next_safe_local_actions=_actual_loading_next_safe_actions(
                provider_preflight,
                _ACTUAL_LOADING_MISSING_ARTIFACT_ACTIONS,
            ),
            claim_boundary=(
                "Package conformance proves deterministic source-to-context receipts only; "
                "no live QA/model actual-loading artifact is present."
            ),
            provider_preflight=provider_preflight,
        )
    try:
        raw_payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        validation_errors = [f"artifact.json.readable: {exc.__class__.__name__}"]
        return KnowledgeRuntimeActualLoadingGateResponse(
            status="blocked",
            evidence_level="contract_evidence",
            artifact_path=artifact_text,
            artifact_ref=artifact_ref,
            artifact_exists=True,
            artifact_schema_valid=False,
            artifact_contract_valid=False,
            artifact_checked_at=artifact_checked_at,
            verdict="invalid_artifact",
            evidence_scope=list(_ACTUAL_LOADING_GATE_SCOPE) + ["live_smoke_artifact"],
            evidence=[artifact_ref],
            missing=validation_errors,
            validation_errors=validation_errors,
            next_safe_local_actions=_actual_loading_next_safe_actions(
                provider_preflight,
                _ACTUAL_LOADING_INVALID_ARTIFACT_ACTIONS,
            ),
            claim_boundary=(
                "A live smoke artifact exists, but it cannot be parsed as the "
                "actual-loading proof contract."
            ),
            provider_preflight=provider_preflight,
        )
    try:
        summary = LiveContextReceiptSmokeSummary.model_validate(raw_payload)
    except ValidationError as exc:
        validation_errors = _live_smoke_schema_errors(exc)
        return KnowledgeRuntimeActualLoadingGateResponse(
            status="blocked",
            evidence_level="contract_evidence",
            artifact_path=artifact_text,
            artifact_ref=artifact_ref,
            artifact_exists=True,
            artifact_schema_valid=False,
            artifact_contract_valid=False,
            artifact_checked_at=artifact_checked_at,
            verdict="invalid_artifact",
            evidence_scope=list(_ACTUAL_LOADING_GATE_SCOPE) + ["live_smoke_artifact"],
            evidence=[artifact_ref],
            missing=["valid live smoke artifact schema", *validation_errors],
            validation_errors=validation_errors,
            next_safe_local_actions=_actual_loading_next_safe_actions(
                provider_preflight,
                _ACTUAL_LOADING_INVALID_ARTIFACT_ACTIONS,
            ),
            claim_boundary=(
                "A live smoke artifact exists, but it does not match the "
                "actual-loading proof contract."
            ),
            provider_preflight=provider_preflight,
        )
    validation_errors = _live_smoke_contract_errors(summary)
    claim_boundary = summary.claimBoundary[:1000]
    if not validation_errors:
        if provider_preflight.status != "proved":
            missing = ["provider_preflight.status=proved", *provider_preflight.missing]
            return KnowledgeRuntimeActualLoadingGateResponse(
                status="blocked",
                evidence_level="contract_evidence",
                artifact_path=artifact_text,
                artifact_ref=artifact_ref,
                artifact_exists=True,
                artifact_schema_valid=True,
                artifact_contract_valid=True,
                artifact_checked_at=artifact_checked_at,
                verdict=summary.verdict,
                evidence_scope=list(_ACTUAL_LOADING_GATE_SCOPE) + ["live_smoke_artifact", "provider_preflight"],
                evidence=[
                    artifact_ref,
                    summary.surface,
                    f"provider_preflight_status={provider_preflight.status}",
                ],
                missing=list(dict.fromkeys(missing)),
                next_safe_local_actions=_actual_loading_next_safe_actions(
                    provider_preflight,
                    _ACTUAL_LOADING_PROVIDER_BLOCKED_ACTIONS,
                ),
                claim_boundary=(
                    "A live smoke artifact satisfies the context-receipt contract, but "
                    "provider forced-tool preflight is not proved; actual-loading remains blocked."
                ),
                provider_preflight=provider_preflight,
            )
        if not _provider_preflight_proves_live_summary(summary, provider_preflight):
            missing = [_provider_preflight_match_requirement(summary)]
            return KnowledgeRuntimeActualLoadingGateResponse(
                status="blocked",
                evidence_level="contract_evidence",
                artifact_path=artifact_text,
                artifact_ref=artifact_ref,
                artifact_exists=True,
                artifact_schema_valid=True,
                artifact_contract_valid=True,
                artifact_checked_at=artifact_checked_at,
                verdict=summary.verdict,
                evidence_scope=list(_ACTUAL_LOADING_GATE_SCOPE)
                + ["live_smoke_artifact", "provider_preflight", "provider_preflight_endpoint_match"],
                evidence=[
                    artifact_ref,
                    summary.surface,
                    f"provider_preflight_status={provider_preflight.status}",
                    f"provider={summary.provider or 'unknown'}",
                    f"baseHost={summary.baseHost or 'unknown'}",
                    f"model={summary.model or 'unknown'}",
                ],
                missing=missing,
                next_safe_local_actions=_actual_loading_next_safe_actions(
                    provider_preflight,
                    _ACTUAL_LOADING_PROVIDER_BLOCKED_ACTIONS,
                ),
                claim_boundary=(
                    "A live smoke artifact satisfies the context-receipt contract, but "
                    "provider forced-tool preflight is not proved for the same provider/baseHost/model endpoint."
                ),
                provider_preflight=provider_preflight,
            )
        return KnowledgeRuntimeActualLoadingGateResponse(
            status="proved",
            evidence_level="focused_test_evidence",
            artifact_path=artifact_text,
            artifact_ref=artifact_ref,
            artifact_exists=True,
            artifact_schema_valid=True,
            artifact_contract_valid=True,
            artifact_checked_at=artifact_checked_at,
            verdict=summary.verdict,
            evidence_scope=list(_ACTUAL_LOADING_GATE_SCOPE) + ["live_smoke_artifact"],
            evidence=[
                artifact_ref,
                summary.surface,
                f"provider={summary.provider or 'unknown'}",
                f"baseHost={summary.baseHost or 'unknown'}",
                f"model={summary.model or 'unknown'}",
                f"provider_preflight_match={summary.provider}/{summary.baseHost}/{summary.model}",
                f"assembledContextHash={summary.directReceipt.assembledContextHash}",
            ],
            claim_boundary=claim_boundary,
            provider_preflight=provider_preflight,
        )
    return KnowledgeRuntimeActualLoadingGateResponse(
        status="blocked",
        evidence_level="contract_evidence",
        artifact_path=artifact_text,
        artifact_ref=artifact_ref,
        artifact_exists=True,
        artifact_schema_valid=True,
        artifact_contract_valid=False,
        artifact_checked_at=artifact_checked_at,
        verdict=summary.verdict,
        evidence_scope=list(_ACTUAL_LOADING_GATE_SCOPE) + ["live_smoke_artifact"],
        evidence=[artifact_ref],
        missing=validation_errors,
        validation_errors=validation_errors,
        next_safe_local_actions=_actual_loading_next_safe_actions(
            provider_preflight,
            _ACTUAL_LOADING_CONTRACT_ACTIONS,
        ),
        claim_boundary=claim_boundary
        or (
            "A live smoke artifact exists, but it does not prove that the QA/model "
            "turn received and returned the Knowledge Runtime receipt hash."
        ),
        provider_preflight=provider_preflight,
    )


def _knowledge_runtime_conformance_from_packages(
    packages: list[KnowledgePackageProjectionResponse],
) -> KnowledgeRuntimeConformanceResponse:
    package_rows: list[KnowledgeRuntimeConformancePackageResponse] = []
    summary: dict[str, int] = {"proved": 0, "pending": 0, "blocked": 0, "not_applicable": 0}
    for package in packages:
        consumers = _manifest_runtime_consumers(package)
        test_evidence = _test_evidence_for_package(package)
        items = _conformance_items(package, consumers, test_evidence)
        for item in items:
            summary[item.status] = summary.get(item.status, 0) + 1
        package_rows.append(
            KnowledgeRuntimeConformancePackageResponse(
                package_id=package.package_id,
                kind=package.kind,
                title=package.title,
                overall_status=_overall_conformance_status(items),
                loaded=package.loaded,
                source_path=package.source_path,
                source_hash=package.source_hash,
                content_hash=package.content_hash,
                read_endpoint=package.read_endpoint,
                search_endpoint=package.search_endpoint,
                manifest=package.manifest,
                runtime_consumers=consumers,
                mcp_tools=_mcp_tools_for_package(package),
                test_evidence=test_evidence,
                conformance=items,
            )
        )
    actual_loading_gate = _actual_loading_gate()
    summary[actual_loading_gate.status] = summary.get(actual_loading_gate.status, 0) + 1
    return KnowledgeRuntimeConformanceResponse(
        schema_version="scholar-ai-knowledge-runtime-conformance/v1",
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        pipeline=list(_PIPELINE_STEPS),
        summary=summary,
        actual_loading_gate=actual_loading_gate,
        packages=package_rows,
    )


@router.get("/packages", response_model=KnowledgePackagesResponse)
def knowledge_packages(vault: SourceVault = Depends(get_source_vault)) -> KnowledgePackagesResponse:
    """Return a normalized registry of runtime knowledge packages."""

    return KnowledgePackagesResponse(
        schema_version="scholar-ai-knowledge-packages/v1",
        packages=_knowledge_package_projections(vault),
    )


@router.get("/runtime-conformance", response_model=KnowledgeRuntimeConformanceResponse)
def knowledge_runtime_conformance(
    vault: SourceVault = Depends(get_source_vault),
) -> KnowledgeRuntimeConformanceResponse:
    """Return a read-only Knowledge Runtime Pipeline conformance projection."""

    return _knowledge_runtime_conformance_from_packages(_knowledge_package_projections(vault))


@router.post("/context-receipt", response_model=KnowledgeContextReceiptResponse)
def knowledge_context_receipt(request: KnowledgeContextReceiptRequest) -> KnowledgeContextReceiptResponse:
    """Return proof that selected knowledge refs entered bounded context input."""

    return _build_context_receipt(request)


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


@router.get("/academic-english/status", response_model=AcademicEnglishStatusResponse)
def academic_english_runtime_status() -> AcademicEnglishStatusResponse:
    """Return source/artifact status for the academic-English knowledge package."""

    return AcademicEnglishStatusResponse(**academic_english_status())


@router.get("/academic-english/search", response_model=AcademicEnglishSearchResponse)
def academic_english_runtime_search(
    q: Annotated[str, Query(min_length=1, max_length=500, description="Academic-English knowledge query.")],
    top_k: Annotated[int, Query(ge=1, le=50)] = 8,
) -> AcademicEnglishSearchResponse:
    """Search academic-English knowledge and return bounded agent-readable refs."""

    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="q must not be empty")
    try:
        results = search_academic_english(query, top_k=top_k)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AcademicEnglishSearchResponse(
        query=query,
        results=[AcademicEnglishSearchHitResponse(**item) for item in results],
    )


@router.get("/bridge-lexicon/status", response_model=BridgeLexiconStatusResponse)
def bridge_lexicon_runtime_status() -> BridgeLexiconStatusResponse:
    """Return status for the CJK bridge lexicon runtime knowledge asset."""

    return BridgeLexiconStatusResponse(**get_bridge_lexicon_status())


@router.get("/bridge-lexicon/read", response_model=BridgeLexiconReadResponse)
def bridge_lexicon_runtime_read() -> BridgeLexiconReadResponse:
    """Return the normalized bridge lexicon entries for runtime context loading."""

    snapshot = load_bridge_lexicon_store().get_snapshot()
    entries = {term: list(values) for term, values in snapshot.entries.items()}
    return BridgeLexiconReadResponse(**snapshot.to_status_payload(), entries=entries)


@router.get("/bridge-lexicon/search", response_model=BridgeLexiconSearchResponse)
def bridge_lexicon_runtime_search(
    q: Annotated[str, Query(min_length=1, max_length=500, description="Bridge lexicon entry query.")],
    top_k: Annotated[int, Query(ge=1, le=50)] = 8,
) -> BridgeLexiconSearchResponse:
    """Search bridge lexicon entries and return bounded agent-readable refs."""

    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="q must not be empty")
    try:
        results = search_bridge_lexicon(query, top_k=top_k)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return BridgeLexiconSearchResponse(
        query=query,
        package_id="bridge_lexicon",
        results=[BridgeLexiconSearchHitResponse(**item) for item in results],
    )


@router.get("/skill-packages/{package_id}/status", response_model=SkillPackageStatusResponse)
def skill_package_runtime_status(package_id: str) -> SkillPackageStatusResponse:
    """Return read-only source/ref/provenance status for one Skill package."""

    try:
        payload = skill_package_knowledge.get_skill_package_status(package_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SkillPackageStatusResponse(**payload)


@router.get("/skill-packages/{package_id}/search", response_model=SkillPackageSearchResponse)
def skill_package_runtime_search(
    package_id: str,
    q: Annotated[str, Query(min_length=1, max_length=500, description="Skill package knowledge query.")],
    top_k: Annotated[int, Query(ge=1, le=50)] = 8,
) -> SkillPackageSearchResponse:
    """Search one Skill package and return bounded agent-readable refs."""

    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="q must not be empty")
    try:
        results = skill_package_knowledge.search_skill_package(package_id, query, top_k=top_k)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SkillPackageSearchResponse(
        query=query,
        package_id=package_id,
        results=[SkillPackageSearchHitResponse(**item) for item in results],
    )


@router.get("/product-docs/status", response_model=ProductDocsStatusResponse)
def product_docs_runtime_status() -> ProductDocsStatusResponse:
    """Return source/ref/provenance status for repo-local product docs."""

    return ProductDocsStatusResponse(**product_docs_knowledge.get_product_docs_status())


@router.get("/product-docs/read", response_model=ProductDocsReadResponse)
def product_docs_runtime_read() -> ProductDocsReadResponse:
    """Return bounded product-doc chunks for runtime context loading."""

    return ProductDocsReadResponse(**product_docs_knowledge.read_product_docs())


@router.get("/product-docs/search", response_model=ProductDocsSearchResponse)
def product_docs_runtime_search(
    q: Annotated[str, Query(min_length=1, max_length=500, description="Product documentation query.")],
    top_k: Annotated[int, Query(ge=1, le=50)] = 8,
) -> ProductDocsSearchResponse:
    """Search repo-local product docs and return bounded agent-readable refs."""

    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="q must not be empty")
    try:
        results = product_docs_knowledge.search_product_docs(query, top_k=top_k)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ProductDocsSearchResponse(
        query=query,
        package_id=product_docs_knowledge.PRODUCT_DOCS_PACKAGE_ID,
        results=[ProductDocsSearchHitResponse(**item) for item in results],
    )


@router.get("/scoring-rules/status", response_model=ScoringRulesStatusResponse)
def scoring_rules_runtime_status() -> ScoringRulesStatusResponse:
    """Return source/ref/provenance status for scoring_rules.json."""

    return ScoringRulesStatusResponse(**config_knowledge.get_scoring_rules_status())


@router.get("/scoring-rules/read", response_model=ScoringRulesReadResponse)
def scoring_rules_runtime_read() -> ScoringRulesReadResponse:
    """Return the normalized scoring-rules JSON sections for runtime context loading."""

    return ScoringRulesReadResponse(**config_knowledge.read_scoring_rules())


@router.get("/scoring-rules/search", response_model=ScoringRulesSearchResponse)
def scoring_rules_runtime_search(
    q: Annotated[str, Query(min_length=1, max_length=500, description="Scoring-rules config query.")],
    top_k: Annotated[int, Query(ge=1, le=50)] = 8,
) -> ScoringRulesSearchResponse:
    """Search scoring-rules config sections and return bounded agent-readable refs."""

    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="q must not be empty")
    try:
        results = config_knowledge.search_scoring_rules(query, top_k=top_k)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ScoringRulesSearchResponse(
        query=query,
        package_id=config_knowledge.SCORING_RULES_PACKAGE_ID,
        results=[ScoringRulesSearchHitResponse(**item) for item in results],
    )
