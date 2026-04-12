export type WritingActionScope = 'selection' | 'section' | 'full_draft';
export type OutputMode = 'latex' | 'markdown' | 'plain';

export interface WritingAction {
  id: string;
  nameZh: string;
  nameEn: string;
  descriptionZh: string;
  descriptionEn: string;
  category: 'translate' | 'rewrite' | 'check' | 'generate';
  supportedScopes: WritingActionScope[];
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
