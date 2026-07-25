import type { components } from '@/generated/openapi';

export type WikiStatus = components['schemas']['WikiStatusResponse'];
export type WikiManifestDrilldown = components['schemas']['WikiManifestDrilldownPayload'];
export type WikiManifestDrilldownItem = components['schemas']['WikiManifestDrilldownItemPayload'];
export type WikiPageSummary = components['schemas']['WikiPageSummaryPayload'];
export type WikiPageListResponse = components['schemas']['WikiPageListResponse'];
export type WikiPageRead = components['schemas']['WikiPageReadResponse'];
export type WikiDoctorResponse = components['schemas']['WikiDoctorResponse'];
export type WikiCompileApiResponse = components['schemas']['WikiCompileResponse'];
export type WikiGraphResponse = components['schemas']['WikiGraphResponse'];
export type WikiReviewItem = components['schemas']['WikiReviewItemPayload'];
export type WikiReviewListResponse = components['schemas']['WikiReviewListResponse'];

export type DoctorSeverity = 'ok' | 'warning' | 'error';

export interface WikiStatusModel extends WikiStatus {
  enabled: boolean;
  page_count: number;
  stale: boolean;
  integrity_status: string;
  index_hash: string;
  source_manifest_hash: string;
  indexed_source_manifest_hash: string;
  indexed_page_count: number;
  source_page_count: number | null;
  graph_json_exists: boolean;
  graph_db_exists: boolean;
  query_index_exists: boolean;
  review_queue_exists: boolean;
  paths: Record<string, string>;
  warnings: string[];
  manifest_drilldown: WikiManifestDrilldownModel;
}

export interface WikiRevalidationModel {
  enabled: boolean;
  stale: boolean;
  can_apply: boolean;
  applied: boolean;
  integrity_status: string;
  source_manifest_hash: string;
  indexed_source_manifest_hash: string;
  source_page_count: number | null;
  indexed_page_count: number;
  manifest_drilldown: WikiManifestDrilldownModel;
  warnings: string[];
  message: string;
}

export interface WikiManifestDrilldownItemModel extends WikiManifestDrilldownItem {
  kind: string;
  page_path: string;
  source_hash: string | null;
  indexed_hash: string | null;
  redacted: boolean;
}

export interface WikiManifestDrilldownModel extends WikiManifestDrilldown {
  schema_version: string;
  status: string;
  hash_algorithm: string;
  limit: number;
  missing_count: number;
  extra_count: number;
  mismatched_count: number;
  truncated: boolean;
  missing_pages: WikiManifestDrilldownItemModel[];
  extra_pages: WikiManifestDrilldownItemModel[];
  mismatched_pages: WikiManifestDrilldownItemModel[];
}

export interface WikiPageSummaryModel extends WikiPageSummary {
  path: string;
  title: string;
  kind: string;
  status: string;
}

export interface WikiPageListModel extends WikiPageListResponse {
  enabled: boolean;
  pages: WikiPageSummaryModel[];
}

export interface WikiPageDetailModel {
  enabled: boolean;
  path: string;
  frontmatter: Record<string, unknown>;
  body: string;
}

export interface WikiSearchEvidenceRefModel {
  page_path?: string;
  title?: string;
  score?: number;
  snippet?: string;
  source?: string;
  source_labels?: string[];
  [key: string]: unknown;
}

export interface WikiSearchModel {
  enabled: boolean;
  fallback_required: boolean;
  answer: string;
  evidence_refs: WikiSearchEvidenceRefModel[];
  warnings: string[];
}

export interface WikiDoctorActionModel {
  command: string;
  description: string;
  safe_auto_repair: boolean;
}

export interface WikiDoctorCheckModel {
  id: string;
  label: string;
  status: DoctorSeverity;
  summary: string;
  detail: string;
  metrics: Record<string, unknown>;
  actions: WikiDoctorActionModel[];
}

export interface WikiDoctorStructuredReportModel {
  ok: boolean;
  status: DoctorSeverity;
  counts: Record<string, number>;
  checks: WikiDoctorCheckModel[];
}

export interface WikiDoctorModel extends WikiDoctorResponse {
  enabled: boolean;
  report: Record<string, unknown>;
  warnings: string[];
  structuredReport: WikiDoctorStructuredReportModel | null;
}

export interface WikiReviewDecisionModel {
  status: string;
  reason: string;
  decided_at: string;
  decided_by: string;
  promotion_receipt: WikiReviewPromotionReceiptModel | null;
}

export interface WikiPageRevisionReviewTargetModel {
  schema_version: 'scholar-ai-wiki-page-revision-target/v1' | 'scholar-ai-wiki-page-revision-target/v2';
  type: 'wiki_page_revision';
  page_id: string;
  page_path: string;
  expected_content_hash: string;
  expected_status: 'draft' | 'review';
}

export interface WikiAnnotationNoteReviewTargetModel {
  schema_version: 'scholar-ai-annotation-note-review-target/v1';
  type: 'annotation_note';
  project_id: string;
  material_id: string;
  note_id: string;
  expected_updated_at: string;
  expected_content_hash: string;
  required_scope: 'wiki_review';
}

export type WikiReviewTargetModel =
  | WikiPageRevisionReviewTargetModel
  | WikiAnnotationNoteReviewTargetModel;

export interface WikiReviewPromotionReceiptModel {
  schema_version: 'scholar-ai-wiki-promotion-receipt/v1' | 'scholar-ai-wiki-promotion-receipt/v2';
  receipt_id: string;
  review_item_id: string;
  request_id: string;
  expected_item_revision: string;
  request_fingerprint: string;
  outcome: 'promoted';
  target: WikiPageRevisionReviewTargetModel;
  before_content_hash: string;
  after_content_hash: string;
  previous_status: 'draft' | 'review';
  promoted_status: 'final';
  promoted_at: string;
  promoted_by: string;
}

export interface WikiReviewPromotionIntentModel {
  schema_version: 'scholar-ai-wiki-promotion-intent/v1' | 'scholar-ai-wiki-promotion-intent/v2';
  operation_id: string;
  review_item_id: string;
  request_id: string;
  expected_item_revision: string;
  request_fingerprint: string;
  reason: string;
  target: WikiPageRevisionReviewTargetModel;
  before_content_hash: string;
  after_content_hash: string;
  previous_status: 'draft' | 'review';
  promoted_status: 'final';
  promoted_at: string;
  promoted_by: string;
}

export interface WikiReviewPromotionWithdrawalReceiptModel {
  schema_version: 'scholar-ai-wiki-promotion-withdrawal-receipt/v1';
  receipt_id: string;
  review_item_id: string;
  promotion_operation_id: string;
  promotion_request_id: string;
  promotion_request_fingerprint: string;
  expected_item_revision: string;
  resulting_item_revision: string;
  withdrawal_request_fingerprint: string;
  outcome: 'withdrawn';
  target: WikiPageRevisionReviewTargetModel;
  before_content_hash: string;
  planned_after_content_hash: string;
  reason: string;
  withdrawn_at: string;
  withdrawn_by: string;
}

export interface WikiReviewItemModel {
  item_id: string;
  kind: string;
  title: string;
  page_path: string;
  summary: string;
  status: string;
  created_at: string;
  source: string;
  metadata: Record<string, unknown>;
  schema_version: number;
  item_revision: string;
  target: WikiReviewTargetModel | null;
  promotion_intent: WikiReviewPromotionIntentModel | null;
  promotion_withdrawal_receipts?: WikiReviewPromotionWithdrawalReceiptModel[];
  allowed_actions: Array<'approve' | 'reject' | 'withdraw'>;
  decision: WikiReviewDecisionModel | null;
}

export interface WikiReviewListModel {
  enabled: boolean;
  items: WikiReviewItemModel[];
}

interface WikiReviewDecisionInputBaseModel {
  item_id: string;
  reason: string;
  decided_by?: string;
  request_id?: string;
  expected_item_revision: string;
}

export interface WikiPageReviewDecisionInputModel extends WikiReviewDecisionInputBaseModel {
  target_type: 'wiki_page_revision';
  expected_target_content_hash: string;
}

export interface WikiAnnotationReviewDecisionInputModel extends WikiReviewDecisionInputBaseModel {
  target_type: 'annotation_note';
  expected_target_content_hash: string;
}

export interface WikiUnboundReviewDecisionInputModel extends WikiReviewDecisionInputBaseModel {
  target_type: 'unbound';
  expected_target_content_hash?: never;
}

export type WikiReviewDecisionInputModel =
  | WikiPageReviewDecisionInputModel
  | WikiAnnotationReviewDecisionInputModel
  | WikiUnboundReviewDecisionInputModel;

export interface WikiReviewPromotionWithdrawalInputModel {
  item_id: string;
  reason: string;
  expected_item_revision: string;
  expected_promotion_operation_id: string;
}

export interface WikiReviewPromotionWithdrawalModel {
  item: WikiReviewItemModel;
  withdrawal_receipt: WikiReviewPromotionWithdrawalReceiptModel;
}

export interface WikiGraphNodeModel {
  node_id: string;
  page_path: string;
  kind: string;
  title: string;
  status: string;
  content_hash: string;
  frontmatter_id: string | null;
  metadata: Record<string, unknown>;
}

export interface WikiGraphEdgeModel {
  edge_id: string;
  source_id: string;
  target_id: string;
  edge_type: string;
  weight: number;
  confidence: string;
  evidence: string;
  source_path: string;
  target_path: string | null;
  metadata: Record<string, unknown>;
}

export interface WikiGraphStructuredModel {
  schema_version: number;
  updated_at: string;
  node_count: number;
  edge_count: number;
  nodes: WikiGraphNodeModel[];
  edges: WikiGraphEdgeModel[];
}

export interface WikiGraphModel extends WikiGraphResponse {
  enabled: boolean;
  graph: Record<string, unknown>;
  structuredGraph: WikiGraphStructuredModel | null;
}

export type WikiGraphReviewOperationKind =
  | 'merge_duplicate_nodes'
  | 'disambiguate_nodes'
  | 'add_node_evidence'
  | 'add_relation_evidence';

export interface WikiGraphReviewNodeInputModel {
  node_id: string;
  page_path: string;
  label?: string | null;
  disambiguation?: string | null;
}

export interface WikiGraphReviewEdgeInputModel {
  edge_id?: string;
  source: string;
  target: string;
  relation: string;
  source_path: string;
  target_path?: string | null;
  frontmatter_field?: string | null;
}

export interface WikiGraphReviewApplyInputModel {
  operation_kind: WikiGraphReviewOperationKind;
  review_item_key?: string;
  keep_node_id?: string | null;
  merge_node_ids?: string[];
  nodes: WikiGraphReviewNodeInputModel[];
  edges?: WikiGraphReviewEdgeInputModel[];
  evidence_refs?: Record<string, unknown>[];
  decided_by?: string;
}

export interface WikiGraphReviewPageSnapshotModel {
  page_path: string;
  content: string;
  content_hash: string;
  expected_current_hash: string;
}

export interface WikiGraphReviewApplyModel {
  enabled: boolean;
  operation_id: string;
  operation_kind: string;
  updated_page_paths: string[];
  snapshots: WikiGraphReviewPageSnapshotModel[];
  message: string;
  warnings: string[];
}

export interface WikiGraphReviewUndoInputModel {
  operation_id: string;
  operation_kind?: string;
  snapshots: WikiGraphReviewPageSnapshotModel[];
  decided_by?: string;
}

export interface WikiCompileDryRunInputModel {
  source_id?: string | null;
  project_id?: string | null;
  allow_write?: boolean;
}

export interface WikiCompileBudgetSummaryModel {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  input_cost_usd: number;
  output_cost_usd: number;
  estimated_cost_usd: number;
  pricing_configured: boolean;
  pricing_source: string;
  currency: string;
}

export interface WikiCompileBudgetCheckModel {
  source_id: string;
  source_chunks: number;
  total_chunk_chars: number;
  estimated_tokens: number;
  over_budget: boolean;
  reason: string;
}

export interface WikiCompileDryRunModel {
  enabled: boolean;
  dry_run: boolean;
  created: number;
  updated: number;
  skipped: number;
  planned_paths: string[];
  written_paths: string[];
  budget_summary: WikiCompileBudgetSummaryModel;
  budget_checks: WikiCompileBudgetCheckModel[];
  errors: string[];
  warnings: string[];
}

export interface WikiImportRequestModel {
  source_paths: string[];
  dry_run: boolean;
  confirm_write: boolean;
  overwrite: boolean;
  kind: WikiManualPageKind;
  status: WikiManualPageStatus;
}

export interface WikiImportItemModel {
  source_path: string;
  import_source_hash: string;
  source_hash: string;
  content_hash: string;
  ref_id: string;
  chunk_id: string;
  read_endpoint: string;
  span_start: number | null;
  span_end: number | null;
  title: string;
  kind: string;
  status: string;
  slug: string;
  path: string;
  action: string;
  review_item_id: string;
  runtime_session_id: string;
  runtime_job_id: string;
  runtime_approval_id: string;
  warnings: string[];
  error: string;
}

export interface WikiImportResponseModel {
  enabled: boolean;
  dry_run: boolean;
  confirm_write: boolean;
  imported: number;
  skipped: number;
  errored: number;
  pages: WikiImportItemModel[];
  warnings: string[];
}

export interface WikiExportModel {
  success: boolean;
  page_count: number;
  output_path: string;
  errors: string[];
}

export type WikiManualPageKind = 'synthesis' | 'exploration' | 'concept' | 'paper' | 'experiment' | 'question';

export type WikiManualPageStatus = 'draft' | 'review' | 'final';

export interface WikiManualPageInputModel {
  title: string;
  kind: WikiManualPageKind;
  body: string;
  status: WikiManualPageStatus;
}

export interface WikiPageMutationModel {
  success: boolean;
  slug: string;
  message: string;
}

export interface WikiStatusPanelDraft {
  id: 'status' | 'pages' | 'review' | 'graph' | 'doctor';
  title: string;
  description: string;
  tone: 'active' | 'pending';
}
