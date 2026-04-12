/**
 * Writing Resources Types
 * Phase 3 of harness upgrade: First-class backend resource types
 *
 * Replaces fabricated writing-mainline paths with real resource models:
 * - WritingProject: Top-level project container
 * - WritingSection: Sections within a project
 * - WritingDraft: Versioned draft content
 * - WritingRevision: Immutable snapshots of draft content
 */

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
export interface WritingProject {
  readonly project_id: string;
  readonly title: string;
  readonly description: string;
  readonly status: ProjectStatus;
  readonly content_type: ContentType;
  readonly created_at: string;
  readonly updated_at: string;
  readonly user_id?: string;
  readonly tags: readonly string[];
}

/**
 * Immutable WritingSection resource.
 * Sections organize large documents into manageable parts.
 */
export interface WritingSection {
  readonly section_id: string;
  readonly project_id: string;
  readonly title: string;
  readonly order: number;
  readonly description: string;
  readonly created_at: string;
  readonly updated_at: string;
}

/**
 * Immutable WritingDraft resource.
 * A versioned draft of content for a section or entire project.
 * Multiple revisions can exist for one draft.
 */
export interface WritingDraft {
  readonly draft_id: string;
  readonly project_id: string;
  readonly section_id?: string; // null for project-level draft
  readonly title: string;
  readonly content: string;
  readonly status: DraftStatus;
  readonly created_at: string;
  readonly updated_at: string;
  readonly last_edited_by?: string;
}

/**
 * Immutable WritingRevision resource.
 * Point-in-time snapshot of draft content for audit trail.
 */
export interface WritingRevision {
  readonly revision_id: string;
  readonly draft_id: string;
  readonly project_id: string;
  readonly content: string;
  readonly revision_number: number;
  readonly created_at: string;
  readonly created_by?: string;
  readonly message: string;
}

/**
 * Request to create a new project.
 */
export interface CreateProjectRequest {
  title: string;
  description?: string;
  content_type?: ContentType | string;
  user_id?: string;
  tags?: string[];
}

/**
 * Request to create a section.
 */
export interface CreateSectionRequest {
  project_id: string;
  title: string;
  order: number;
  description?: string;
}

/**
 * Request to create a draft.
 */
export interface CreateDraftRequest {
  project_id: string;
  section_id?: string;
  title?: string;
  content?: string;
  edited_by?: string;
}

/**
 * Request to save draft content.
 */
export interface SaveDraftRequest {
  content: string;
  edited_by?: string;
}

/**
 * Ranked evidence item returned by associative writing.
 */
export interface WritingAssociationSignal {
  readonly source_type: string;
  readonly source_id: string;
  readonly title: string;
  readonly excerpt: string;
  readonly score: number;
  readonly shared_terms: readonly string[];
  readonly rationale: string;
}

/**
 * Bridgeable writing angle that links multiple signals.
 */
export interface WritingAssociationAngle {
  readonly angle_id: string;
  readonly title: string;
  readonly prompt: string;
  readonly supporting_source_ids: readonly string[];
  readonly shared_terms: readonly string[];
  readonly confidence: number;
}

/**
 * Missing evidence detected during associative writing.
 */
export interface WritingEvidenceGap {
  readonly gap: string;
  readonly severity: string;
  readonly recommendation: string;
}

/**
 * Request payload for associative-writing generation.
 */
export interface BuildAssociationRequest {
  project_id: string;
  query: string;
  draft_id?: string;
  section_id?: string;
  use_memory?: boolean;
  memory_query?: string;
  wing?: string;
  room?: string;
  memory_limit?: number;
  signal_limit?: number;
  angle_limit?: number;
}

/**
 * Full associative-writing response returned by the backend.
 */
export interface WritingAssociationBundle {
  readonly project_id: string;
  readonly query: string;
  readonly generated_at: string;
  readonly draft_id?: string;
  readonly section_id?: string;
  readonly focus_terms: readonly string[];
  readonly memory_used: boolean;
  readonly memory_hit_count: number;
  readonly related_signals: readonly WritingAssociationSignal[];
  readonly association_angles: readonly WritingAssociationAngle[];
  readonly continuation_prompts: readonly string[];
  readonly evidence_gaps: readonly WritingEvidenceGap[];
  readonly recommended_memory_queries: readonly string[];
}
