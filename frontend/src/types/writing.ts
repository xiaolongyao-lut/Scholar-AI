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

export interface TransformResult {
  jobId: string;
  actionId: string;
  inputText: string;
  outputText: string;
  applied: boolean;
  createdAt: string;
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
  materialId?: string | null;
  token: string;
  startOffset: number;
  endOffset: number;
  ordinal: number;
}

// Alias for compatibility if needed
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

// --- Inspiration / 启发点 ---

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
