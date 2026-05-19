export type WritingActionScope = 'selection' | 'section' | 'full_draft';
export type OutputMode = 'latex' | 'markdown' | 'plain';

export interface WritingAction {
  id: string;
  nameZh: string;
  nameEn: string;
  descriptionZh: string;
  descriptionEn: string;
  category: string;
  supportedScopes: string[];
  icon: string;
}

export interface EvidenceReference {
  chunk_id?: string;
  material_id?: string;
  source_id?: string;
  title?: string;
  content?: string;
  text?: string;
  compressed_text?: string;
  quote?: string;
  label?: string;
  score?: number;
  page?: number | string;
  source?: string;
  source_label?: string;
  source_labels?: string[];
  source_hint?: string;
  [key: string]: unknown;
}

export interface TransformResult {
  jobId: string;
  actionId: string;
  inputText: string;
  outputText: string;
  applied: boolean;
  createdAt: string;
  evidenceRefs?: EvidenceReference[];
}

export interface WritingMaterial {
  id: string;
  titleZh: string;
  titleEn: string;
  summaryZh: string;
  summaryEn: string;
  type: string;
  focusPointsZh: string[];
  focusPointsEn: string[];
}

export interface CitationAnchor {
  id: string;
  instanceId: string;
  materialId?: string | null;
  token: string;
  startOffset: number;
  endOffset: number;
  ordinal: number;
}

export interface ManuscriptSection {
  id: string;
  projectId: string;
  titleZh: string;
  titleEn: string;
  status: 'done' | 'drafting' | 'reviewing' | 'not_started' | 'blocked';
  wordCount: number;
  order: number;
  notesZh?: string;
  notesEn?: string;
}

export interface DraftContent {
  sectionId: string;
  content: string;
  wordCount: number;
  lastSavedAt: string;
  isDirty: boolean;
}

export interface Revision {
  id: string;
  sectionId: string;
  projectId: string;
  content: string;
  source: 'manual' | 'auto_save' | 'transform';
  createdAt: string;
  label: string;
}

export type SparkType = 'causal_extension' | 'conflict' | 'analogy' | 'gap' | 'synthesis' | 'memory_association';

export interface AnalysisChain {
  observation: string;
  mechanism: string;
  evidence: string[];
  boundary: string;
  counter_evidence: string[];
  next_action: string;
}

export interface SparkEvidenceRef {
  material_id: string;
  page?: number | null;
  chunk_id?: string | null;
  text?: string;
  score?: number | null;
}

export interface InspirationSpark {
  id: string;
  content: string;
  spark_type: SparkType;
  source_papers: string[];
  confidence: number;
  related_point_ids: string[];
  actionable: boolean;
  analysis_chain?: AnalysisChain | null;
  confidence_reason?: string;
  temporal_sensitivity?: number;
  /** Per-spark anchored evidence (Track B D-EVR-1..6). When the
   *  generator carries chunk metadata, the backend populates this so
   *  the frontend can render a clickable evidence pill. Empty for
   *  LLM-generated sparks (per D-EVR-4 never fabricate). */
  evidence_refs?: SparkEvidenceRef[];
}

export interface ContinuationContext {
  spark: InspirationSpark;
  evidence_texts: string[];
  causal_chain_summary: string;
  suggested_angles: string[];
  related_figures: string[];
}

export type CitationInsertRequest = {
  requestId: string;
  materialId: string | null;
};

export type CitationFocusRequest = {
  requestId: string;
  anchorId: string;
  anchorInstanceId: string;
  anchorStartOffset: number;
  materialId: string | null;
};
