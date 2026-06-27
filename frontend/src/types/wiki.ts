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
  decision: WikiReviewDecisionModel | null;
}

export interface WikiReviewListModel {
  enabled: boolean;
  items: WikiReviewItemModel[];
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
