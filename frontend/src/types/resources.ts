/**
 * Writing Resources Types
 *
 * These aliases are generated from the FastAPI OpenAPI schema so the
 * frontend resource layer stays aligned with the backend contract.
 */

import type { components } from "../generated/openapi";

export enum ProjectStatus {
  DRAFT = "draft",
  IN_PROGRESS = "in_progress",
  REVIEW = "review",
  PUBLISHED = "published",
  ARCHIVED = "archived",
}

export enum ContentType {
  ACADEMIC = "academic",
  TECHNICAL = "technical",
  CREATIVE = "creative",
  BUSINESS = "business",
  GENERAL = "general",
}

export enum DraftStatus {
  CREATED = "created",
  EDITING = "editing",
  REVIEW_READY = "review_ready",
  REVIEWED = "reviewed",
  APPROVED = "approved",
  DISCARDED = "discarded",
}

/**
 * Immutable WritingProject resource.
 * Represents a top-level writing project with multiple sections and drafts.
 */
export type WritingProject = components["schemas"]["ProjectPayload"];

/**
 * Immutable WritingSection resource.
 * Sections organize large documents into manageable parts.
 */
export type WritingSection = components["schemas"]["SectionPayload"];

/**
 * Immutable WritingMaterial resource.
 * Project-scoped material cards backing the reference drawer.
 */
export type WritingMaterialResource = components["schemas"]["MaterialPayload"];

/**
 * Immutable WritingDraft resource.
 * A versioned draft of content for a section or entire project.
 * Multiple revisions can exist for one draft.
 */
export type WritingDraft = components["schemas"]["DraftPayload"];

/**
 * Immutable WritingRevision resource.
 * Point-in-time snapshot of draft content for audit trail.
 */
export type WritingRevision = components["schemas"]["RevisionPayload"];

/**
 * Request to create a new project.
 */
export type CreateProjectRequest = components["schemas"]["CreateProjectRequest"];

/**
 * Request to create a section.
 */
export type CreateSectionRequest = components["schemas"]["CreateSectionRequest"];

/**
 * Request to create a project-scoped material.
 */
export type CreateMaterialRequest = components["schemas"]["CreateMaterialRequest"];

/**
 * Request to create a draft.
 */
export type CreateDraftRequest = components["schemas"]["CreateDraftRequest"];

/**
 * Request to save draft content.
 */
export type SaveDraftRequest = components["schemas"]["SaveDraftRequest"];

/**
 * Ranked evidence item returned by associative writing.
 */
export type WritingAssociationSignal = components["schemas"]["AssociationSignalPayload"];

/**
 * Bridgeable writing angle that links multiple signals.
 */
export type WritingAssociationAngle = components["schemas"]["AssociationAnglePayload"];

/**
 * Missing evidence detected during associative writing.
 */
export type WritingEvidenceGap = components["schemas"]["EvidenceGapPayload"];

/**
 * Request payload for associative-writing generation.
 */
export type BuildAssociationRequest = components["schemas"]["BuildAssociationRequest"];

/**
 * Full associative-writing response returned by the backend.
 */
export type WritingAssociationBundle = components["schemas"]["WritingAssociationPayload"];

/**
 * Backend action payload used by the assistant dock.
 */
export type WritingActionResource = components["schemas"]["WritingActionPayload"];


// ---------------------------------------------------------------------------
// New types for enriched API (export, statistics, batch operations)
// ---------------------------------------------------------------------------

/** Project export formats */
export type ProjectExportFormat = "markdown" | "json";

/** Project export response */
export interface ProjectExportResult {
  project_id: string;
  format: string;
  filename?: string;
  content?: string;
  project?: WritingProject;
  sections?: WritingSection[];
  drafts?: WritingDraft[];
  materials?: WritingMaterialResource[];
  document_count?: number;
}

/** Project statistics */
export interface ProjectStats {
  project_id: string;
  title: string;
  status: string;
  section_count: number;
  draft_count: number;
  material_count: number;
  document_count: number;
  total_characters: number;
  total_revisions: number;
  created_at: string;
  updated_at: string;
}

/** Global statistics overview */
export interface GlobalStats {
  project_count: number;
  draft_count: number;
  material_count: number;
  total_characters: number;
  projects_by_status: Record<string, number>;
}

/** Batch summary attached to a discovered volume bundle. */
export interface VolumeBatchSummary {
  output_root: string;
  pdf_folder: string | null;
  total_pdfs: number;
  successful_pdfs: number;
  failed_pdfs: number;
  batch_size: number;
  status: string;
  start_time: string | null;
}

/** Discovered volume bundle ready for cross-paper analysis. */
export interface VolumeSummary {
  volume_key: string;
  volume_id: string;
  label: string;
  paper_count: number;
  writing_point_count: number;
  figure_count: number;
  reference_count: number;
  created_at?: string;
  status: "indexed" | "pending";
  source_root: string;
  batch_summary: VolumeBatchSummary;
  report_paths: Record<string, string>;
}

/** Grouped claim evidence for one cross-paper parameter comparison. */
export interface VolumeClaimGroup {
  text: string;
  papers: string[];
}

/** Conflict or consensus row surfaced in the volume analysis UI. */
export interface VolumeConflictItem {
  parameter: string;
  conflict_level: string;
  unique_claims: number;
  paper_count: number;
  papers: string[];
  claim_groups: VolumeClaimGroup[];
}

/** Trend row generated from cross-paper analysis. */
export interface VolumeTrendRow {
  parameter: string;
  consensus: boolean;
  trend: string;
  papers_count: number;
  representative_claim?: string | null;
  claim_variants: number;
}

/** Detailed cross-paper analysis result for one discovered volume bundle. */
export interface VolumeAnalysisResult {
  volume: VolumeSummary;
  analysis: {
    generated_at?: string;
    tracked_parameter_count: number;
    high_conflict_count: number;
    consensus_count: number;
    top_conflicts: VolumeConflictItem[];
    top_consensus: VolumeConflictItem[];
    trend_rows: VolumeTrendRow[];
    master_index_stats: Record<string, number>;
    report_paths: Record<string, string>;
  };
}

/** Batch delete request */
export interface BatchDeleteRequest {
  material_ids: string[];
}

/** Batch delete response */
export interface BatchDeleteResult {
  deleted: string[];
  not_found: string[];
  deleted_count: number;
}

/** Update project request */
export interface UpdateProjectRequest {
  title?: string;
  description?: string;
  tags?: string[];
}

/** Update section request */
export interface UpdateSectionRequest {
  title?: string;
  description?: string;
  order?: number;
}

/** LLM model info */
export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
}

/** SSE stream event types */
export type ChatStreamEventType = "text_delta" | "thinking_start" | "thinking_delta" | "thinking_end" | "error" | "done" | "usage";

/** SSE stream event payload */
export interface ChatStreamEvent {
  event: ChatStreamEventType;
  delta?: string;
  usage?: Record<string, number>;
  error?: string;
  model?: string;
}
