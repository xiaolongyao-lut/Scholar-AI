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
  source_id?: string;
  title?: string;
  content?: string;
  quote?: string;
  score?: number;
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

export interface InspirationSpark {
  id: string;
  content: string;
  spark_type: SparkType;
  source_papers: string[];
  confidence: number;
  related_point_ids: string[];
  actionable: boolean;
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
