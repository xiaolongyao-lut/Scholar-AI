import axios from 'axios';
import {
  useState,
  useEffect,
  useMemo,
  useRef,
  useCallback,
  lazy,
  Suspense,
  useId,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type SetStateAction,
} from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import {
  Archive,
  BookOpen,
  FolderKanban,
  GitFork,
  FileText,
  Loader2,
  MessageCircle,
  Maximize2,
  Plus,
  RefreshCw,
  AlertCircle,
  History,
  X,
  Trash2,
  Search,
  RotateCcw,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRight,
  PanelRightClose,
  Sparkles,
  Users2,
  Activity,
  Check,
  ChevronDown,
} from 'lucide-react';
import { Conversation } from '@/components/chat/Conversation';
import { buildSuggestedQuestions, type SuggestedQuestion } from '@/components/chat/suggestedQuestions';
import { DiscussionPanel } from '@/components/DiscussionPanel';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import {
  formatChatVisibleError,
  sanitizeAssistantVisibleContent,
  sanitizeChatVisibleText,
} from '@/components/chat/chatDisplay';
import {
  CHAT_INPUT_VISION_LIMITS,
  chatAttachmentFingerprint,
  type ChatAttachment,
  type ChatInputHandle,
  type ChatInputSubmitPayload,
  type IdentifiedChatSelectionContext,
} from '@/components/chat/ChatInput';
import type {
  ChatRelatedFigure,
  ChatJointRecallDiagnostics,
  ChatMessageData,
  ChatMessageDiagnostics,
  ChatRetrievalDiagnostics,
  ChatRetrievalQrelsStatus,
} from '@/components/chat/MessageRenderer';
import { relatedFiguresFromEvidenceRefs } from '@/components/chat/relatedFigures';
import type { EvidenceRefLike } from '@/components/evidence/EvidencePill';
import type { GraphNavigateTarget } from '@/components/graph/GraphPayloadViewer';
import type { GraphPayloadV0 } from '@/components/graph/payloadToRf';
import { WikiGraphSegmentedView } from '@/components/graph/WikiGraphSegmentedView';
import { buildAnswerTurnGraphPayload } from '@/components/graph/answerGraphProjection';
import { evidenceGraphToGraphPayload } from '@/components/knowledge/evidenceGraphAdapter';
import type { ReasoningDimension } from '@/components/graph/dimensionGraph';
import { PdfTabStrip } from '@/components/PdfViewer/PdfTabStrip';
import type {
  PdfFormulaCandidate,
  PdfRegionCapture,
  PdfSelectedVisualRegion,
  PdfSelectionAnchor,
} from '@/components/PdfViewer/PdfViewer';
import { getAnnotations, type Highlight, type Note as AnnotationNote } from '@/services/annotationApi';
import { getAnswerEvidenceGraph } from '@/services/graphApi';
import { smartReadDialogScope, useSmartRead } from '@/contexts/SmartReadContext';
import { usePdfTabs } from '@/contexts/PdfTabsContext';
import {
  listChatSessions,
  deleteChatSession,
  bulkDeleteChatSessions,
  archiveChatSession,
  restoreChatSession,
  forkChatHistoryConversation,
  resumeChatSession,
  searchChatHistory,
  streamIntelligentChatMessage,
  type AnswerOrigin,
  type ContextTier,
  type CurrentPdfContext,
  type EvidenceRole,
  type IntelligentChatResponse,
  type IntelligentChatStreamEvent,
  type ChatSessionSummary,
  type ChatHistorySearchResult,
  type ChatResumeMessage,
  type TokenUsage,
} from '@/services/intelligentChatApi';
import { backendTierForCostTier, loadSmartReadCostTier } from '@/services/smartReadTiers';
import { useWriting } from '@/contexts/WritingContext';
import { useProjectReasoningBiasState } from '@/hooks/useProjectReasoningBiasState';
import { getWritingBackendService } from '@/services/writingBackend';
import type {
  FigureTableCandidateResource,
  FormulaCandidateResource,
  ProjectChunkResource,
  WritingMaterialResource,
  WritingProject,
} from '@/types/resources';
import {
  buildResearchSelections,
  sanitizeResearchSelections,
  type ResearchSelection,
} from '@/types/researchSelection';
import {
  sanitizeVisualObservationReferences,
  type VisualObservationReference,
} from '@/types/visualObservation';
import { getApiBaseUrl } from '@/services/apiBaseUrl';
import {
  encodePdfBboxParam,
  isPdfBboxUnit,
  normalizePdfUrlBbox,
  parsePdfBboxSearchParam,
  readPdfBbox,
  toPdfHighlightRect,
  type PdfBbox,
  type PdfBboxUnit,
  type PdfContentSelection,
} from '@/lib/pdfAnchor';
import { normalizePdfQuote } from '@/lib/pdfQuoteAnchor';
import { locateChunk, type ChunkLocator } from '@/services/resourcesApi';
import {
  type DiscussionDefaults,
  DEFAULT_DISCUSSION_DEFAULTS,
  normalizeDiscussionDefaults,
} from '@/services/discussionDefaults';
import {
  createAgentSidebarAnswerRequest,
  readAgentSidebarReceipt,
  type AgentSidebarAnswerRequestResponse,
} from '@/services/agentSidebarApi';

const UNIFIED_DIALOG_MODE = 'literature_qa' as const;
const UNIFIED_INPUT_PLACEHOLDER = '围绕当前项目材料提问…';
const UNIFIED_EMPTY_HINT = '提问后会结合当前项目材料、证据和上下文生成回答。';
const DISCUSSION_SESSION_SOURCE = 'multi_agent_discussion';
const AGENT_BRIDGE_READY_MESSAGE = '证据已准备，等待智能体回答。';
const DIALOG_REQUEST_TIMEOUT_MS = 30 * 60_000;
const DIALOG_REQUEST_TIMEOUT_SECONDS = DIALOG_REQUEST_TIMEOUT_MS / 1000;
const LEGACY_DIALOG_MODES = ['literature_qa', 'direct', 'inspiration'] as const;
const DIALOG_PANE_WIDTHS_STORAGE_KEY = 'dialog-pane-widths-v1';
const DIALOG_HISTORY_COLLAPSED_STORAGE_KEY = 'dialog-history-collapsed-v1';
const DIALOG_CONTEXT_OPEN_STORAGE_KEY = 'dialog-context-open-v1';
const DIALOG_CONTEXT_TAB_STORAGE_KEY = 'dialog-context-tab-v1';
const DIALOG_CENTER_TAB_STORAGE_KEY = 'dialog-center-tab-v1';
const DIALOG_HISTORY_DEFAULT_WIDTH = 320;
const DIALOG_HISTORY_MIN_WIDTH = 248;
const DIALOG_HISTORY_MAX_WIDTH = 440;
const DIALOG_CONTEXT_DEFAULT_WIDTH = 380;
const DIALOG_CONTEXT_MIN_WIDTH = 320;
const DIALOG_CONTEXT_MAX_WIDTH = 560;
const DIALOG_MAIN_MIN_WIDTH = 420;
const DIALOG_PDF_SELECTION_MAX_COUNT = 12;
const DIALOG_PDF_FORMULA_CANDIDATE_MAX_COUNT = 200;
const DIALOG_MIXED_SELECTION_PROMPT = '请结合选中的内容进行分析。';
const DIALOG_SELECTION_AUTO_PROMPTS = new Set([
  '请分析选中的这段内容。',
  '请分析选中的图。',
  '请分析选中的表。',
  '请解释选中的公式。',
  '请分析选中的区域。',
  DIALOG_MIXED_SELECTION_PROMPT,
]);
const dialogAbortControllers = new Map<string, AbortController>();
const dialogRequestStartedAtByScope = new Map<string, number>();
let dialogPdfSelectionSequence = 0;
let dialogTurnSequence = 0;

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  turnId?: string;
  content: string;
  researchSelections?: ResearchSelection[];
  visualObservationRefs?: VisualObservationReference[];
  tierUsed?: ContextTier;
  contextMetadata?: IntelligentChatResponse['context_metadata'];
  evidenceRefs?: IntelligentChatResponse['evidence_refs'];
  actualSamplingParams?: IntelligentChatResponse['actual_sampling_params'];
  tokensUsed?: TokenUsage;
  retrievalDiagnostics?: ChatRetrievalDiagnostics;
  answerOrigin?: AnswerOrigin;
  answerModelOrigin?: IntelligentChatResponse['answer_model_origin'];
  retrievalProvider?: IntelligentChatResponse['retrieval_provider'];
  timestamp: Date;
  insufficientContext?: boolean;
  status?: ChatMessageData['status'];
  relatedFigures?: ChatRelatedFigure[];
}

type ChatState = 'ready' | 'responding' | 'error' | 'unavailable';
type HistoryState = 'idle' | 'loading' | 'error';
type SearchState = 'idle' | 'loading' | 'error';
type HistoryMode = 'recent' | 'archived';
type DialogContextScope = 'paper' | 'project';
type DialogWorkbenchMode = 'chat' | 'discussion';
type DialogCenterTab = 'chat' | 'discussion' | 'reader';
type DialogContextRailTab = 'chat' | 'discussion' | 'paper' | 'project' | 'graph' | 'notes';
type DiscussionEnhancementIntent = 'reading' | 'writing' | 'research';
type ProjectMaterialsState = 'idle' | 'loading' | 'error';
type AnnotationNotesState = 'idle' | 'loading' | 'error';
type SuggestedQuestionState = 'idle' | 'loading' | 'error';
type AgentHandoffState = 'idle' | 'creating' | 'created' | 'error';

interface DialogPdfSelectionState {
  id: string;
  materialId: string;
  selection: PdfContentSelection;
  imageFingerprint?: string;
  restoredFromResearchSelection?: true;
}

interface DialogRequestContextRevision {
  projectId: string | null;
  materialId: string | null;
  contextScope: DialogContextScope;
  sessionId: string | null;
  revision: number;
}

interface BuildDialogCurrentPdfContextInput {
  materialId?: string | null;
  page?: number | null;
  chunkId?: string | null;
  selectedText?: string | null;
  bbox?: readonly number[] | null;
  bboxUnit?: PdfBboxUnit | null;
  selection?: PdfContentSelection | null;
  selections?: readonly PdfContentSelection[] | null;
}

interface SessionBranchGroup {
  root: ChatSessionSummary;
  forks: ChatSessionSummary[];
}

interface SessionProjectGroup {
  key: string;
  label: string;
  branchGroups: SessionBranchGroup[];
}

interface DialogPaneWidths {
  history: number;
  context: number;
}

interface DiscussionLaunchState {
  query: string;
  evidenceMode?: 'from_project' | 'none';
}

type DialogResizablePane = keyof DialogPaneWidths;

const DEFAULT_DIALOG_PANE_WIDTHS: DialogPaneWidths = {
  history: DIALOG_HISTORY_DEFAULT_WIDTH,
  context: DIALOG_CONTEXT_DEFAULT_WIDTH,
};

const DISCUSSION_LAUNCH_STATE_KEY = 'dialog-discussion-launch-v1';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function clampPaneWidth(value: unknown, min: number, max: number, fallback: number): number {
  const numeric = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.min(Math.max(Math.round(numeric), min), max);
}

function readDialogPaneWidths(): DialogPaneWidths {
  try {
    const raw = localStorage.getItem(DIALOG_PANE_WIDTHS_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_DIALOG_PANE_WIDTHS };
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) return { ...DEFAULT_DIALOG_PANE_WIDTHS };
    return {
      history: clampPaneWidth(
        parsed.history,
        DIALOG_HISTORY_MIN_WIDTH,
        DIALOG_HISTORY_MAX_WIDTH,
        DIALOG_HISTORY_DEFAULT_WIDTH,
      ),
      context: clampPaneWidth(
        parsed.context,
        DIALOG_CONTEXT_MIN_WIDTH,
        DIALOG_CONTEXT_MAX_WIDTH,
        DIALOG_CONTEXT_DEFAULT_WIDTH,
      ),
    };
  } catch {
    return { ...DEFAULT_DIALOG_PANE_WIDTHS };
  }
}

function writeDialogPaneWidths(widths: DialogPaneWidths): void {
  try {
    localStorage.setItem(DIALOG_PANE_WIDTHS_STORAGE_KEY, JSON.stringify(widths));
  } catch {
    // Browser storage can be unavailable in private or restricted contexts.
  }
}

function readDialogBoolean(key: string, fallback: boolean): boolean {
  try {
    const value = localStorage.getItem(key);
    if (value === '1') return true;
    if (value === '0') return false;
  } catch {
    return fallback;
  }
  return fallback;
}

function writeDialogBoolean(key: string, value: boolean): void {
  try {
    localStorage.setItem(key, value ? '1' : '0');
  } catch {
    // Browser storage can be unavailable in private or restricted contexts.
  }
}

function normalizeAnswerOrigin(value: string | null | undefined): AnswerOrigin | null {
  const normalized = String(value ?? '').trim();
  if (normalized === 'internal_smartread' || normalized === 'external_agent') {
    return normalized;
  }
  return null;
}

function dialogVisibleAnswerContent(content: string, answerOrigin: AnswerOrigin): string {
  const raw = content.trim();
  if (!raw) return '';
  const isExternalHandoff = answerOrigin === 'external_agent'
    || raw.includes('已切换为外部智能体回答模式')
    || raw.includes('文献助手未调用内部聊天模型');
  const directAnswer = sanitizeAssistantVisibleContent(raw);
  if (!isExternalHandoff) return directAnswer;
  if (!directAnswer) return AGENT_BRIDGE_READY_MESSAGE;
  return directAnswer.replace(/\n{3,}/g, '\n\n');
}

function normalizeDialogContextRailTab(value: string | null | undefined): DialogContextRailTab | null {
  const normalized = String(value ?? '').trim().toLowerCase();
  if (
    normalized === 'chat' ||
    normalized === 'discussion' ||
    normalized === 'paper' ||
    normalized === 'project' ||
    normalized === 'graph' ||
    normalized === 'notes'
  ) {
    return normalized;
  }
  return null;
}

function readDialogContextRailTab(fallback: DialogContextRailTab): DialogContextRailTab {
  try {
    return normalizeDialogContextRailTab(localStorage.getItem(DIALOG_CONTEXT_TAB_STORAGE_KEY)) ?? fallback;
  } catch {
    return fallback;
  }
}

function writeDialogContextRailTab(tab: DialogContextRailTab): void {
  try {
    localStorage.setItem(DIALOG_CONTEXT_TAB_STORAGE_KEY, tab);
  } catch {
    // Browser storage can be unavailable in private or restricted contexts.
  }
}

function normalizeDialogCenterTab(value: string | null | undefined): DialogCenterTab | null {
  const normalized = String(value ?? '').trim().toLowerCase();
  if (normalized === 'chat' || normalized === 'discussion' || normalized === 'reader') {
    return normalized;
  }
  return null;
}

function readDialogCenterTab(fallback: DialogCenterTab): DialogCenterTab {
  try {
    return normalizeDialogCenterTab(localStorage.getItem(DIALOG_CENTER_TAB_STORAGE_KEY)) ?? fallback;
  } catch {
    return fallback;
  }
}

function writeDialogCenterTab(tab: DialogCenterTab): void {
  try {
    localStorage.setItem(DIALOG_CENTER_TAB_STORAGE_KEY, tab);
  } catch {
    // Browser storage can be unavailable in private or restricted contexts.
  }
}

function getChatErrorMessage(error: unknown): string {
  return formatChatVisibleError(error);
}

export function readDialogErrorText(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return typeof error === 'string' ? error : String(error ?? '');
}

export function isUnavailableError(error: unknown): boolean {
  if (!axios.isAxiosError(error) || !error.response) {
    const message = readDialogErrorText(error);
    return message.toLowerCase().includes('no literature source paths configured');
  }
  if (error.response.status !== 400) return false;
  const detail = error.response.data?.detail;
  const message = typeof detail === 'string' ? detail : error.response.data?.error?.message;
  return typeof message === 'string' && message.toLowerCase().includes('no literature source paths configured');
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function readRecordNumber(record: Record<string, unknown>, key: string): number | undefined {
  const value = record[key];
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  return undefined;
}

function coerceTokenUsageRecord(value: unknown): TokenUsage | undefined {
  if (!isRecord(value)) return undefined;
  const prompt = readRecordNumber(value, 'prompt') ?? readRecordNumber(value, 'prompt_tokens') ?? 0;
  const completion = readRecordNumber(value, 'completion') ?? readRecordNumber(value, 'completion_tokens') ?? 0;
  const total = readRecordNumber(value, 'total') ?? readRecordNumber(value, 'total_tokens') ?? prompt + completion;
  return { prompt, completion, total };
}

function coerceSmartReadTier(value: unknown, fallback: ContextTier): ContextTier {
  return value === 'fast' || value === 'balanced' || value === 'thorough' ? value : fallback;
}

function readRecordString(record: Record<string, unknown>, key: string): string | undefined {
  const value = record[key];
  return typeof value === 'string' ? value : undefined;
}

function readRecordStringOrNull(record: Record<string, unknown>, key: string): string | null | undefined {
  const value = record[key];
  if (value === null) return null;
  return typeof value === 'string' ? value : undefined;
}

function readRecordPage(record: Record<string, unknown>, key: string): number | string | null | undefined {
  const value = record[key];
  if (value === null) return null;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') return value;
  return undefined;
}

function readRecordPageNumber(record: Record<string, unknown>, key: string): number | null | undefined {
  const value = readRecordPage(record, key);
  if (value === null) return null;
  if (typeof value === 'number') {
    return Number.isInteger(value) && value > 0 ? value : undefined;
  }
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const parsed = Number(value.trim());
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}

function readRecordStringArray(record: Record<string, unknown>, key: string): string[] | undefined {
  const value = record[key];
  if (!Array.isArray(value)) return undefined;
  const strings = value.filter((item): item is string => typeof item === 'string');
  return strings.length > 0 ? strings : undefined;
}

function readRecordBoolean(record: Record<string, unknown>, key: string): boolean | undefined {
  const value = record[key];
  return typeof value === 'boolean' ? value : undefined;
}

function readEvidenceRole(value: unknown): EvidenceRole {
  if (
    value === 'selected_content'
    || value === 'current_material'
    || value === 'cited_project_material'
    || value === 'project_context'
  ) {
    return value;
  }
  return 'project_context';
}

function coerceContextMetadata(value: unknown): IntelligentChatResponse['context_metadata'] | undefined {
  if (!isRecord(value) || !Array.isArray(value.chunks)) return undefined;
  const chunks = value.chunks.flatMap((chunk, index) => {
    if (!isRecord(chunk)) return [];
    const source = readRecordString(chunk, 'source') ?? '来源材料';
    const content = readRecordString(chunk, 'content') ?? '';
    const bboxUnit = isPdfBboxUnit(chunk.bbox_unit) ? chunk.bbox_unit : null;
    const bbox = bboxUnit ? readPdfBbox(chunk.bbox) : null;
    return [{
      index: readRecordNumber(chunk, 'index') ?? index + 1,
      source,
      content,
      relevance_score: readRecordNumber(chunk, 'relevance_score'),
      chunk_id: readRecordStringOrNull(chunk, 'chunk_id'),
      material_id: readRecordStringOrNull(chunk, 'material_id'),
      evidence_role: readEvidenceRole(chunk.evidence_role),
      title: readRecordStringOrNull(chunk, 'title'),
      section_title: readRecordStringOrNull(chunk, 'section_title'),
      page: readRecordPage(chunk, 'page'),
      bbox: bbox ? [...bbox] : null,
      bbox_unit: bbox ? bboxUnit : null,
      source_labels: readRecordStringArray(chunk, 'source_labels'),
      source_hint: readRecordStringOrNull(chunk, 'source_hint'),
    }];
  });
  return {
    chunks,
    truncated: value.truncated === true,
  };
}

function readRecordNonNegativeNumber(record: Record<string, unknown>, key: string): number | undefined {
  const value = readRecordNumber(record, key);
  return value !== undefined && value >= 0 ? value : undefined;
}

type DialogEvidenceRef = NonNullable<IntelligentChatResponse['evidence_refs']>[number]
  & EvidenceRefLike
  & { content?: string | null };

function coerceEvidenceRefs(value: unknown): DialogEvidenceRef[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const refs = value.flatMap((item): DialogEvidenceRef[] => {
    if (!isRecord(item)) return [];
    const chunkId = readRecordString(item, 'chunk_id') ?? readRecordString(item, 'ref_id');
    if (!chunkId) return [];
    const sourceType = readRecordString(item, 'source_type');
    const sourceTitle = readRecordStringOrNull(item, 'source_title');
    const source = readRecordString(item, 'source') ?? sourceTitle ?? (sourceType === 'wiki' ? 'Wiki 记忆' : '项目证据');
    const text = readRecordString(item, 'text') ?? '';
    const quote = readRecordString(item, 'quote') ?? '';
    const bboxUnit = isPdfBboxUnit(item.bbox_unit) ? item.bbox_unit : null;
    const bbox = bboxUnit ? readPdfBbox(item.bbox) : null;
    const ref: DialogEvidenceRef = {
      evidence_id: readRecordString(item, 'evidence_id') ?? chunkId,
      chunk_id: chunkId,
      material_id: readRecordStringOrNull(item, 'material_id') ?? undefined,
      evidence_role: readEvidenceRole(item.evidence_role),
      source,
      text,
      quote,
      label: readRecordString(item, 'label'),
      score: readRecordNonNegativeNumber(item, 'score') ?? readRecordNonNegativeNumber(item, 'lexical_score'),
      source_labels: readRecordStringArray(item, 'source_labels'),
      page: readRecordPageNumber(item, 'page'),
      bbox: bbox ? [...bbox] : null,
      bbox_unit: bbox ? bboxUnit : null,
      source_hint: readRecordStringOrNull(item, 'source_hint'),
      source_kind: item.source_kind === 'web' || item.source_kind === 'mcp' || item.source_kind === 'local'
        ? item.source_kind
        : sourceType === 'wiki'
          ? 'mcp'
          : 'local',
      source_type: sourceType === 'wiki' ? 'wiki' : 'project',
      source_title: sourceTitle,
      source_path: readRecordStringOrNull(item, 'source_path'),
      joint_score: readRecordNonNegativeNumber(item, 'joint_score') ?? null,
      figure_candidate: readRecordStringOrNull(item, 'figure_candidate'),
      figure_candidate_detail: isRecord(item.figure_candidate_detail) ? item.figure_candidate_detail : null,
      image_paths: readRecordStringArray(item, 'image_paths'),
      anchor_kind: item.anchor_kind === 'text' || item.anchor_kind === 'visual'
        ? item.anchor_kind
        : null,
      ...(readRecordString(item, 'content') ? { content: readRecordString(item, 'content') } : {}),
    };
    for (const key of ['content_hash', 'locator_hash', 'chunk_hash', 'embedding_input_hash', 'hash_version'] as const) {
      const hash = readRecordString(item, key);
      if (hash) ref[key] = hash;
    }
    return [ref];
  });
  return refs.length > 0 ? refs : undefined;
}

function coerceJointRecallDiagnostics(value: unknown): ChatJointRecallDiagnostics | undefined {
  if (!isRecord(value)) return undefined;
  const rawSummaries = Array.isArray(value.wiki_summaries) ? value.wiki_summaries : [];
  const wikiSummaries = rawSummaries.flatMap((item) => {
    if (!isRecord(item)) return [];
    return [{
      title: readRecordString(item, 'title'),
      summary: readRecordString(item, 'summary'),
      ref_id: readRecordString(item, 'ref_id'),
      read_endpoint: readRecordString(item, 'read_endpoint'),
    }];
  }).slice(0, 3);
  return {
    status: readRecordString(value, 'status'),
    fusion: readRecordString(value, 'fusion'),
    project_weight: readRecordNonNegativeNumber(value, 'project_weight'),
    wiki_weight: readRecordNonNegativeNumber(value, 'wiki_weight'),
    project_hit_count: readRecordNonNegativeNumber(value, 'project_hit_count'),
    wiki_hit_count: readRecordNonNegativeNumber(value, 'wiki_hit_count'),
    fused_count: readRecordNonNegativeNumber(value, 'fused_count'),
    wiki_share_after_fusion: readRecordNonNegativeNumber(value, 'wiki_share_after_fusion'),
    max_wiki_share_after_fusion: readRecordNonNegativeNumber(value, 'max_wiki_share_after_fusion'),
    top_doc_ids: readRecordStringArray(value, 'top_doc_ids'),
    wiki_summaries: wikiSummaries.length > 0 ? wikiSummaries : undefined,
  };
}

function coerceQrelsQualityClaim(value: unknown): ChatRetrievalQrelsStatus['quality_claim'] | undefined {
  if (typeof value !== 'string') return undefined;
  if (
    value === 'no_qrels_available'
    || value === 'candidate_qrels_review_required'
    || value === 'reviewed_qrels_promotion_required'
    || value === 'canonical_qrels_available'
  ) {
    return value;
  }
  return undefined;
}

export function coerceQrelsStatus(value: unknown): ChatRetrievalQrelsStatus | undefined {
  if (!isRecord(value)) return undefined;
  const status = readRecordString(value, 'status');
  const normalizedStatus = status === 'missing' || status === 'candidate' || status === 'reviewed' || status === 'canonical'
    ? status
    : undefined;
  const semanticQualityClaimAllowed = normalizedStatus === 'canonical' && value.semantic_quality_claim_allowed === true;
  const qrelsStatus: ChatRetrievalQrelsStatus = {
    schema_version: readRecordString(value, 'schema_version') === 'retrieval-qrels-status/v1'
      ? 'retrieval-qrels-status/v1'
      : undefined,
    status: normalizedStatus,
    candidate_qrels_count: readRecordNonNegativeNumber(value, 'candidate_qrels_count'),
    reviewed_qrels_count: readRecordNonNegativeNumber(value, 'reviewed_qrels_count'),
    canonical_qrels_count: readRecordNonNegativeNumber(value, 'canonical_qrels_count'),
    semantic_quality_claim_allowed: semanticQualityClaimAllowed,
    quality_claim: semanticQualityClaimAllowed ? coerceQrelsQualityClaim(value.quality_claim) : undefined,
    notes: readRecordStringArray(value, 'notes')?.slice(0, 8),
  };
  return Object.values(qrelsStatus).some((item) => item !== undefined) ? qrelsStatus : undefined;
}

function coerceGatewayStatusCounts(value: unknown): Record<string, number> | undefined {
  if (!isRecord(value)) return undefined;
  const entries = Object.entries(value).flatMap(([key, rawValue]) => {
    if (typeof rawValue !== 'number' || !Number.isFinite(rawValue) || rawValue < 0) return [];
    return [[key, Math.trunc(rawValue)] as const];
  });
  return entries.length > 0 ? Object.fromEntries(entries) : undefined;
}

function coerceGatewayDiagnostics(value: unknown): ChatRetrievalDiagnostics['gateway'] | undefined {
  if (!isRecord(value)) return undefined;
  const diagnostics = {
    dense_hit_count: readRecordNonNegativeNumber(value, 'dense_hit_count'),
    lexical_hit_count: readRecordNonNegativeNumber(value, 'lexical_hit_count'),
    visual_hit_count: readRecordNonNegativeNumber(value, 'visual_hit_count'),
    candidate_count: readRecordNonNegativeNumber(value, 'candidate_count'),
    dense_enabled: readRecordBoolean(value, 'dense_enabled'),
    material_balancing_enabled: readRecordBoolean(value, 'material_balancing_enabled'),
    chroma_status: readRecordString(value, 'chroma_status'),
    fts_status: readRecordString(value, 'fts_status'),
    fallback_reasons: readRecordStringArray(value, 'fallback_reasons')?.slice(0, 8),
    gate_status_counts: coerceGatewayStatusCounts(value.gate_status_counts),
  };
  return Object.values(diagnostics).some((item) => item !== undefined) ? diagnostics : undefined;
}

function coerceNullableNonNegativeNumber(record: Record<string, unknown>, key: string): number | null | undefined {
  if (record[key] === null) return null;
  return readRecordNonNegativeNumber(record, key);
}

function coerceTolfDiagnostics(value: unknown): ChatRetrievalDiagnostics['tolf'] | undefined {
  if (!isRecord(value)) return undefined;
  const diagnostics = {
    status: readRecordString(value, 'status'),
    candidate_count: readRecordNonNegativeNumber(value, 'candidate_count'),
    input_count: readRecordNonNegativeNumber(value, 'input_count'),
    graph_node_count: readRecordNonNegativeNumber(value, 'graph_node_count'),
    graph_edge_count: readRecordNonNegativeNumber(value, 'graph_edge_count'),
    gate_after_count: readRecordNonNegativeNumber(value, 'gate_after_count'),
    activation_min: coerceNullableNonNegativeNumber(value, 'activation_min'),
    activation_max: coerceNullableNonNegativeNumber(value, 'activation_max'),
    activation_mean: coerceNullableNonNegativeNumber(value, 'activation_mean'),
    top_final_rank_score: coerceNullableNonNegativeNumber(value, 'top_final_rank_score'),
    rank_contribution_keys: readRecordStringArray(value, 'rank_contribution_keys')?.slice(0, 8),
    fallback_reason: readRecordStringOrNull(value, 'fallback_reason'),
  };
  return Object.values(diagnostics).some((item) => item !== undefined) ? diagnostics : undefined;
}

function coerceRetrievalDiagnostics(value: unknown): ChatRetrievalDiagnostics | undefined {
  if (!isRecord(value)) return undefined;
  const diagnostics: ChatRetrievalDiagnostics = {
    retrieval_method: readRecordString(value, 'retrieval_method'),
    embedding_status: readRecordString(value, 'embedding_status'),
    rerank_status: readRecordString(value, 'rerank_status'),
    lexical_only: readRecordBoolean(value, 'lexical_only'),
    fallback_reasons: readRecordStringArray(value, 'fallback_reasons')?.slice(0, 8),
    gateway: coerceGatewayDiagnostics(value.gateway),
    tolf: coerceTolfDiagnostics(value.tolf),
    qrels_status: coerceQrelsStatus(value.qrels_status),
    joint_recall: coerceJointRecallDiagnostics(value.joint_recall),
  };
  return Object.values(diagnostics).some((item) => item !== undefined) ? diagnostics : undefined;
}

function coerceSmartReadResponsePatch(
  content: Record<string, unknown>,
  fallbackTier: ContextTier,
): {
  tierUsed: ContextTier;
  contextMetadata?: IntelligentChatResponse['context_metadata'];
  evidenceRefs?: IntelligentChatResponse['evidence_refs'];
  actualSamplingParams?: IntelligentChatResponse['actual_sampling_params'];
  tokensUsed?: TokenUsage;
  retrievalDiagnostics?: ChatRetrievalDiagnostics;
  answerOrigin?: AnswerOrigin;
  answerModelOrigin?: IntelligentChatResponse['answer_model_origin'];
  retrievalProvider?: IntelligentChatResponse['retrieval_provider'];
  insufficientContext?: boolean;
} {
  const contextMetadata = coerceContextMetadata(content.context_metadata);
  const evidenceRefs = coerceEvidenceRefs(content.evidence_refs);
  const actualSamplingParams = isRecord(content.actual_sampling_params)
    ? content.actual_sampling_params as IntelligentChatResponse['actual_sampling_params']
    : undefined;
  const tierUsed = coerceSmartReadTier(content.tier_used, fallbackTier);
  const tokensUsed = coerceTokenUsageRecord(content.tokens_used);
  const retrievalDiagnostics = coerceRetrievalDiagnostics(content.retrieval_diagnostics);
  const answerOrigin = normalizeAnswerOrigin(readRecordString(content, 'answer_origin'));
  const answerModelOrigin = readRecordString(content, 'answer_model_origin');
  const retrievalProvider = readRecordString(content, 'retrieval_provider');
  return {
    tierUsed,
    contextMetadata,
    evidenceRefs,
    actualSamplingParams,
    tokensUsed,
    retrievalDiagnostics,
    answerOrigin: answerOrigin ?? undefined,
    answerModelOrigin: answerModelOrigin === 'scholar_ai_configured_chat' || answerModelOrigin === 'external_agent'
      ? answerModelOrigin
      : undefined,
    retrievalProvider: retrievalProvider === 'scholar_ai' ? 'scholar_ai' : undefined,
    insufficientContext: contextMetadata ? contextMetadata.chunks.length === 0 : undefined,
  };
}

function buildSmartReadDiagnostics(
  patch: {
    tierUsed: ContextTier;
    contextMetadata?: IntelligentChatResponse['context_metadata'];
    evidenceRefs?: IntelligentChatResponse['evidence_refs'];
    actualSamplingParams?: IntelligentChatResponse['actual_sampling_params'];
    tokensUsed?: TokenUsage;
    retrievalDiagnostics?: ChatRetrievalDiagnostics;
    answerOrigin?: AnswerOrigin;
    answerModelOrigin?: IntelligentChatResponse['answer_model_origin'];
    retrievalProvider?: IntelligentChatResponse['retrieval_provider'];
    insufficientContext?: boolean;
    content: string;
  },
): ChatMessageDiagnostics | undefined {
  return buildDialogDiagnostics({
    id: 'smart-read-final',
    role: 'assistant',
    content: patch.content,
    tierUsed: patch.tierUsed,
    contextMetadata: patch.contextMetadata,
    evidenceRefs: patch.evidenceRefs,
    actualSamplingParams: patch.actualSamplingParams,
    tokensUsed: patch.tokensUsed,
    retrievalDiagnostics: patch.retrievalDiagnostics,
    answerOrigin: patch.answerOrigin,
    answerModelOrigin: patch.answerModelOrigin,
    retrievalProvider: patch.retrievalProvider,
    timestamp: new Date(),
    insufficientContext: patch.insufficientContext,
  });
}

type DialogStreamMetadata = Extract<IntelligentChatStreamEvent, { event: 'metadata' }>;
type DialogStreamUsage = Extract<IntelligentChatStreamEvent, { event: 'usage' }>;

function buildSmartReadDiagnosticsFromStream(input: {
  metadata: DialogStreamMetadata | null;
  usage: DialogStreamUsage | null;
  doneTokens?: TokenUsage;
  fallbackTier: ContextTier;
  content: string;
}): ChatMessageDiagnostics | undefined {
  const payload: Record<string, unknown> = {
    tier_used: input.metadata?.tier_used ?? input.fallbackTier,
    context_metadata: input.metadata?.context_metadata ?? undefined,
    evidence_refs: input.metadata?.evidence_refs ?? undefined,
    actual_sampling_params: input.metadata?.actual_sampling_params ?? undefined,
    tokens_used: input.doneTokens ?? input.usage?.usage ?? undefined,
    retrieval_diagnostics: input.metadata?.retrieval_diagnostics ?? undefined,
    answer_origin: input.metadata?.answer_origin ?? undefined,
    answer_model_origin: input.metadata?.answer_model_origin ?? undefined,
    retrieval_provider: input.metadata?.retrieval_provider ?? undefined,
  };
  const patch = coerceSmartReadResponsePatch(payload, input.fallbackTier);
  return buildSmartReadDiagnostics({
    ...patch,
    content: input.content,
  });
}

function evidenceRefsFromDialogStreamMetadata(metadata: DialogStreamMetadata | null): EvidenceRefLike[] | undefined {
  if (!metadata) return undefined;
  return coerceEvidenceRefs(metadata.evidence_refs);
}

function visualEvidenceRefsFromDialogStreamMetadata(metadata: DialogStreamMetadata | null): EvidenceRefLike[] | undefined {
  if (!metadata || metadata.visual_evidence_refs === undefined) return undefined;
  return coerceEvidenceRefs(metadata.visual_evidence_refs) ?? [];
}

function shouldLoadRelatedFigures(query: string): boolean {
  return /(?:外观|图片|图像|图表|焊缝|形貌|表面|截面|显微|宏观|照片|figure|fig\.|image|picture|appearance|morphology|surface|cross[-\s]?section|micrograph|macrograph|sem|om)/i.test(query);
}

function isAppearanceFigureQuery(query: string): boolean {
  return /(?:外观|宏观|照片|表面成形|焊缝成形|正面成形|背面成形|appearance|macrograph|macroscopic|photo|surface\s+appearance|weld\s+appearance)/i.test(query);
}

function isRealFigureAssetSource(source: string | null | undefined): boolean {
  const value = String(source ?? '').trim();
  return value === 'pdf_embedded_image'
    || value === 'chunk_asset'
    || value === 'chunk_image'
    || value === 'chunk_image_paths'
    || value === 'chunk_raw_image'
    || value === 'chunk_figure_asset'
    || value === 'chunk_figure_image_paths'
    || value === 'chunk_raw_embedded_image'
    || value.endsWith('_chunk_asset')
    || value.endsWith('_chunk_image')
    || value.endsWith('_chunk_image_paths')
    || value.endsWith('_chunk_raw_image')
    || value.endsWith('_chunk_figure_asset')
    || value.endsWith('_chunk_figure_image_paths')
    || value.endsWith('_chunk_raw_embedded_image');
}

function toDialogRelatedFigures(
  candidates: FigureTableCandidateResource[],
  query: string,
  materialId?: string,
): ChatRelatedFigure[] {
  const normalizedMaterialId = String(materialId ?? '').trim();
  const appearanceQuery = isAppearanceFigureQuery(query);
  const scored = candidates
    .filter((candidate) => {
      if (normalizedMaterialId && String(candidate.material_id ?? '').trim() !== normalizedMaterialId) {
        return false;
      }
      if (candidate.kind !== 'figure' && candidate.kind !== 'table') return false;
      if (!candidate.asset_path || !isRealFigureAssetSource(candidate.source)) return false;
      if (appearanceQuery && candidate.kind !== 'figure') return false;
      return true;
    })
    .map((candidate) => {
      const text = `${candidate.label ?? ''} ${candidate.caption ?? ''} ${candidate.material_title ?? ''}`.toLowerCase();
      const appearanceScore = /(?:appearance|macrograph|macroscopic|photo|surface|weld bead|weld seam|face|root|外观|宏观|照片|表面成形|焊缝成形|正面|背面|焊缝表面)/i.test(text) ? 12 : 0;
      const characterizationPenalty = appearanceQuery && /(?:microstructure|morphology|sem|ebsd|eds|ct|pore|porosity|cross[-\s]?section|显微|微观|形貌|孔|气孔|截面|断口|组织|表征)/i.test(text) ? -10 : 0;
      const score =
        (candidate.source === 'pdf_embedded_image' ? 10 : 8) +
        (candidate.kind === 'figure' ? 4 : 0) +
        (/(?:weld|seam|appearance|surface|macro|焊缝|外观|表面|宏观)/i.test(text) ? 6 : 0) +
        appearanceScore +
        characterizationPenalty;
      return { candidate, score };
    })
    .sort((a, b) => b.score - a.score);

  const seen = new Set<string>();
  const figures: ChatRelatedFigure[] = [];
  for (const { candidate } of scored) {
    const id = String(candidate.id ?? `${candidate.material_id}:${candidate.chunk_id}:${candidate.label}`).trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const bboxUnit = isPdfBboxUnit(candidate.bbox_unit) ? candidate.bbox_unit : null;
    const bbox = bboxUnit ? normalizePdfUrlBbox(candidate.bbox, bboxUnit) : null;
    figures.push({
      id,
      kind: candidate.kind === 'table' ? 'table' : 'figure',
      label: String(candidate.label ?? (candidate.kind === 'table' ? '表格候选' : '图像候选')),
      caption: String(candidate.caption ?? ''),
      material_id: String(candidate.material_id ?? ''),
      material_title: candidate.material_title ?? null,
      page: typeof candidate.page === 'number' && Number.isFinite(candidate.page) ? candidate.page : null,
      bbox: bbox ? [...bbox] : null,
      bbox_unit: bbox ? 'normalized_ratio' : null,
      chunk_id: candidate.chunk_id ?? null,
      asset_path: candidate.asset_path ?? null,
      source: candidate.source ?? null,
    });
  }
  return figures;
}

function relatedFigureQueryForAssistant(messages: ChatMessageData[], assistantIndex: number): string | null {
  for (let index = assistantIndex - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role === 'user') {
      const query = message.content.trim();
      return query && shouldLoadRelatedFigures(query) ? query : null;
    }
  }
  return null;
}

function relatedFigureMaterialHint(message: ChatMessageData): string | undefined {
  const materialId = message.evidence?.find((ref) => typeof ref.material_id === 'string' && ref.material_id.trim())
    ?.material_id;
  return materialId?.trim() || undefined;
}

function evidenceRefPageNumber(ref: EvidenceRefLike): number | null {
  if (typeof ref.page === 'number' && Number.isInteger(ref.page) && ref.page > 0) {
    return ref.page;
  }
  return null;
}

function evidenceRefBbox(ref: EvidenceRefLike): PdfBbox | null {
  return isPdfBboxUnit(ref.bbox_unit)
    ? normalizePdfUrlBbox(ref.bbox, ref.bbox_unit)
    : null;
}

async function restoreDialogRelatedFigures(
  messages: ChatMessageData[],
  projectId: string | null,
): Promise<ChatMessageData[]> {
  const normalizedProjectId = String(projectId ?? '').trim();
  if (!normalizedProjectId || messages.length === 0) return messages;

  const targetIndexes = messages.flatMap((message, index): number[] => {
    if (message.role !== 'assistant' || message.relatedFigures?.length) return [];
    return relatedFigureQueryForAssistant(messages, index) ? [index] : [];
  });
  if (targetIndexes.length === 0) return messages;

  const evidenceMappedMessages = messages.map((message, index) => {
    if (!targetIndexes.includes(index) || message.relatedFigures?.length) return message;
    const figures = relatedFiguresFromEvidenceRefs(message.evidence);
    return figures.length > 0 ? { ...message, relatedFigures: figures } : message;
  });
  const remainingTargetIndexes = targetIndexes.filter((index) => !evidenceMappedMessages[index]?.relatedFigures?.length);
  if (remainingTargetIndexes.length === 0) return evidenceMappedMessages;

  let candidates: FigureTableCandidateResource[];
  try {
    candidates = await getWritingBackendService().listFigureTableCandidates(
      normalizedProjectId,
      200,
      { pixelOnly: true, renderPdfFallback: false },
    );
  } catch {
    return messages;
  }
  if (candidates.length === 0) return evidenceMappedMessages;

  return evidenceMappedMessages.map((message, index) => {
    if (!remainingTargetIndexes.includes(index)) return message;
    const query = relatedFigureQueryForAssistant(messages, index);
    if (!query) return message;
    const figures = toDialogRelatedFigures(candidates, query, relatedFigureMaterialHint(message));
    return figures.length > 0 ? { ...message, relatedFigures: figures } : message;
  });
}

function parseChatTimestamp(value: string): Date {
  if (!value.trim()) return new Date();
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
}

function toChatMessage(message: ChatResumeMessage): ChatMessage {
  if (message.role !== 'user' && message.role !== 'assistant') {
    throw new Error('Unsupported chat message role');
  }
  const visualEvidenceRefs = coerceEvidenceRefs(message.visual_evidence_refs);
  const turnId = message.turn_id ?? undefined;
  const visualObservationRefs = message.role === 'assistant'
    ? sanitizeVisualObservationReferences(message.visual_observation_refs)
        .filter((reference) => !turnId || reference.turn_id === turnId)
    : [];
  const chatMessage: ChatMessage = {
    id: message.id,
    role: message.role,
    turnId,
    content: message.content,
    researchSelections: sanitizeResearchSelections(message.research_selections),
    ...(visualObservationRefs.length > 0 ? { visualObservationRefs } : {}),
    tierUsed: message.tier_used ?? undefined,
    contextMetadata: coerceContextMetadata(message.context_metadata),
    evidenceRefs: coerceEvidenceRefs(message.evidence_refs),
    tokensUsed: message.tokens_used ?? undefined,
    retrievalDiagnostics: coerceRetrievalDiagnostics((message as { retrieval_diagnostics?: unknown }).retrieval_diagnostics),
    answerOrigin: message.answer_origin ?? undefined,
    answerModelOrigin: message.answer_model_origin ?? undefined,
    retrievalProvider: message.retrieval_provider === 'scholar_ai'
      ? 'scholar_ai'
      : undefined,
    timestamp: parseChatTimestamp(message.timestamp),
    insufficientContext: message.role === 'assistant' && !message.context_metadata,
    relatedFigures: relatedFiguresFromEvidenceRefs(visualEvidenceRefs),
  };
  return chatMessage;
}

function mapChatDataToDialogMessage(message: ChatMessageData): ChatMessage {
  if (message.role !== 'user' && message.role !== 'assistant') {
    throw new Error('Unsupported smart-read message role');
  }
  const diagnostics = message.metadata?.diagnostics;
  return {
    id: message.id,
    role: message.role,
    turnId: message.turnId,
    content: message.content,
    researchSelections: message.researchSelections,
    visualObservationRefs: message.visualObservationRefs,
    tierUsed: diagnostics?.tier,
    contextMetadata: diagnostics?.context
      ? {
          chunks: diagnostics.context.chunks?.map((chunk) => ({
            index: chunk.index,
            source: chunk.source,
            content: chunk.content,
            relevance_score: chunk.relevance_score,
            chunk_id: chunk.chunk_id,
            material_id: chunk.material_id,
            evidence_role: readEvidenceRole(chunk.evidence_role),
            title: chunk.title,
            section_title: chunk.section_title,
            page: chunk.page,
            bbox: chunk.bbox ?? null,
            bbox_unit: chunk.bbox_unit ?? null,
            source_labels: chunk.source_labels,
            source_hint: chunk.source_hint,
          })) ?? [],
          truncated: false,
        }
      : undefined,
    evidenceRefs: coerceEvidenceRefs(message.evidence),
    actualSamplingParams: diagnostics?.sampling
      ? {
          temperature: diagnostics.sampling.temperature ?? 0,
          top_p: diagnostics.sampling.top_p ?? 0,
          top_k: diagnostics.sampling.top_k ?? 0,
          max_tokens: diagnostics.sampling.max_tokens ?? 0,
        }
      : undefined,
    tokensUsed: diagnostics?.tokens
      ? {
          prompt: diagnostics.tokens.prompt ?? 0,
          completion: diagnostics.tokens.completion ?? 0,
          total: diagnostics.tokens.total ?? 0,
      }
      : undefined,
    retrievalDiagnostics: diagnostics?.retrieval,
    answerOrigin: diagnostics?.answerOrigin,
    answerModelOrigin: diagnostics?.answerModelOrigin,
    retrievalProvider: diagnostics?.retrievalProvider,
    timestamp: message.timestamp ? parseChatTimestamp(message.timestamp) : new Date(),
    insufficientContext: diagnostics?.insufficient,
    status: message.status,
    relatedFigures: message.relatedFigures,
  };
}

function readFirstStorageValue(keys: string[]): string | null {
  for (const key of keys) {
    const value = localStorage.getItem(key);
    if (value) return value;
  }
  return null;
}

function legacyScopedKeys(projectId: string, suffix: string): string[] {
  return LEGACY_DIALOG_MODES.map((mode) => `dialog-${suffix}_${projectId}_${mode}`);
}

function sessionModeLabel(mode: ChatSessionSummary['mode']): string | null {
  if (mode === 'direct' || mode === 'inspiration') return '旧版';
  return null;
}

function isDiscussionSession(item: ChatSessionSummary): boolean {
  return item.source === DISCUSSION_SESSION_SOURCE;
}

function sessionSummaryAgentCount(item: ChatSessionSummary): number {
  const summaryCount = item.agent_count;
  if (typeof summaryCount === 'number' && Number.isFinite(summaryCount) && summaryCount >= 0) {
    return Math.floor(summaryCount);
  }
  return 0;
}

function buildSessionBranchGroups(sessions: ChatSessionSummary[]): SessionBranchGroup[] {
  const byId = new Map(sessions.map((item) => [item.session_id, item]));
  const forksBySource = new Map<string, ChatSessionSummary[]>();
  const roots: ChatSessionSummary[] = [];
  for (const item of sessions) {
    const sourceId = item.fork?.source_session_id;
    if (sourceId && byId.has(sourceId)) {
      const forks = forksBySource.get(sourceId) ?? [];
      forks.push(item);
      forksBySource.set(sourceId, forks);
    } else {
      roots.push(item);
    }
  }
  return roots.map((root) => ({
    root,
    forks: (forksBySource.get(root.session_id) ?? []).sort(
      (a, b) => String(b.updated_at ?? '').localeCompare(String(a.updated_at ?? '')),
    ),
  }));
}

function normalizeProjectId(value: string | null | undefined): string {
  return String(value ?? '').trim();
}

function normalizeMaterialId(value: string | null | undefined): string {
  return String(value ?? '').trim();
}

function normalizeChatHistorySessionId(value: unknown): string | undefined {
  const normalized = typeof value === 'string' ? value.trim() : '';
  return normalized ? normalized : undefined;
}

function normalizeDialogContextScope(
  value: string | null | undefined,
  materialId: string,
): DialogContextScope {
  const normalized = String(value ?? '').trim().toLowerCase();
  if ((normalized === 'paper' || normalized === 'material') && materialId) return 'paper';
  if (normalized === 'workspace' || normalized === 'all') return 'project';
  if (normalized === 'project') return 'project';
  return materialId ? 'paper' : 'project';
}

function normalizeDialogWorkbenchMode(value: string | null | undefined): DialogWorkbenchMode {
  const normalized = String(value ?? '').trim().toLowerCase();
  return normalized === 'discussion' || normalized === 'multi_agent' ? 'discussion' : 'chat';
}

function normalizeDiscussionLaunchState(value: unknown): DiscussionLaunchState | null {
  if (!isRecord(value)) return null;
  const query = typeof value.query === 'string' ? value.query.trim() : '';
  if (!query) return null;
  const evidenceMode = value.evidenceMode === 'from_project' ? 'from_project' : 'none';
  return { query, evidenceMode };
}

function readDiscussionLaunchState(): DiscussionLaunchState | null {
  try {
    const raw = window.sessionStorage.getItem(DISCUSSION_LAUNCH_STATE_KEY);
    if (!raw) return null;
    window.sessionStorage.removeItem(DISCUSSION_LAUNCH_STATE_KEY);
    return normalizeDiscussionLaunchState(JSON.parse(raw));
  } catch {
    return null;
  }
}

function clearDiscussionLaunchState(): void {
  try {
    window.sessionStorage.removeItem(DISCUSSION_LAUNCH_STATE_KEY);
  } catch {
    // Session storage can be unavailable in private or restricted contexts.
  }
}

function writeDiscussionLaunchState(value: DiscussionLaunchState): void {
  try {
    window.sessionStorage.setItem(DISCUSSION_LAUNCH_STATE_KEY, JSON.stringify(value));
  } catch {
    // Session storage can be unavailable in private or restricted contexts.
  }
}

function buildDialogSmartReadScope(
  _contextScope: DialogContextScope,
  projectId: string,
  _materialId: string,
): string {
  return smartReadDialogScope(projectId || 'default');
}

function buildDialogStorageScope(
  _contextScope: DialogContextScope,
  projectId: string,
  _materialId: string,
): string {
  return projectId || 'default';
}

function buildSessionProjectGroups(
  sessions: ChatSessionSummary[],
  projectNames: Record<string, string>,
): SessionProjectGroup[] {
  const grouped = new Map<string, ChatSessionSummary[]>();
  for (const session of sessions) {
    const projectId = normalizeProjectId(session.project_id);
    const key = projectId || '__unbound__';
    const items = grouped.get(key) ?? [];
    items.push(session);
    grouped.set(key, items);
  }

  return Array.from(grouped.entries()).map(([key, items]) => ({
    key,
    label: key === '__unbound__'
      ? '未绑定项目'
      : sanitizeChatVisibleText(projectNames[key], '已删除或不可见的项目', { maxLength: 48 }),
    branchGroups: buildSessionBranchGroups(items),
  }));
}

function materialTitleLabel(material: WritingMaterialResource): string {
  return sanitizeChatVisibleText(material.title, '未命名文献', { maxLength: 80 });
}

function materialSummaryLabel(material: WritingMaterialResource): string {
  return sanitizeChatVisibleText(material.summary || material.summary_en || '', '暂无摘要', { maxLength: 180 });
}

function formatMaterialDate(value: string | null | undefined): string {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return parsed.toLocaleDateString();
}

function materialFocusPoints(material: WritingMaterialResource): string[] {
  const points = material.focus_points?.length ? material.focus_points : material.focus_points_en;
  return (points ?? [])
    .map((point) => sanitizeChatVisibleText(point, '', { maxLength: 48 }))
    .filter((point) => point.length > 0)
    .slice(0, 3);
}

function buildDiscussionEnhancementQuestion(
  intent: DiscussionEnhancementIntent,
  materialLabel: string,
  draftQuestion: string,
): string {
  const target = sanitizeChatVisibleText(materialLabel, '当前材料', { maxLength: 80 });
  const draft = sanitizeChatVisibleText(draftQuestion, '', { maxLength: 220 });
  if (intent === 'reading') {
    return draft
      ? `请围绕「${target}」组织一场多角色研读讨论，先回答这个问题：${draft}。请让不同角色分别从研究对象、方法证据、创新点、局限和可追问问题提出意见，最后给出综合结论。`
      : `请围绕「${target}」组织一场多角色研读讨论。请分别从研究对象、方法证据、创新点、局限和可追问问题提出意见，最后给出综合结论。`;
  }
  if (intent === 'writing') {
    return `请围绕「${target}」组织一场写作思路讨论。请分别提出可写入论文引言、方法、结果讨论和局限性的内容框架，并指出每个写作点需要引用哪些证据。`;
  }
  return `请围绕「${target}」组织一场研究思路讨论。请提出可继续验证的研究假设、关键变量、实验或仿真方案、风险边界和最小可行的下一步实验。`;
}

function noteBodyLabel(note: AnnotationNote): string {
  return sanitizeChatVisibleText(note.body || note.anchor_text, '空笔记', { maxLength: 220 });
}

function noteAnchorLabel(note: AnnotationNote): string {
  return sanitizeChatVisibleText(note.anchor_text, '', { maxLength: 96 });
}

function noteTags(note: AnnotationNote): string[] {
  return (note.tags ?? [])
    .map((tag) => sanitizeChatVisibleText(tag, '', { maxLength: 24 }))
    .filter((tag) => tag.length > 0)
    .slice(0, 4);
}

function extractChunkRefs(content: string): string[] {
  return Array.from(content.matchAll(/\[(chunk-[a-zA-Z0-9_-]+)\]/g), (match) => match[1]);
}

function normalizeEvidencePage(page: string | number | null | undefined): number | null | undefined {
  if (typeof page === 'number') {
    return Number.isFinite(page) && page > 0 ? page : undefined;
  }
  if (typeof page !== 'string' || !page.trim()) {
    return page === null ? null : undefined;
  }
  const parsed = Number(page);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

function normalizeDialogReaderPage(page: string | number | null | undefined): number | null {
  const normalized = normalizeEvidencePage(page);
  return typeof normalized === 'number' ? Math.round(normalized) : null;
}

function normalizeDialogSelectionText(value: string | null | undefined): string | null {
  const normalized = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (!normalized) return null;
  return normalized.length > 1800 ? `${normalized.slice(0, 1799)}…` : normalized;
}

function createDialogPdfSelectionId(): string {
  dialogPdfSelectionSequence += 1;
  return `pdf-selection-${Date.now().toString(36)}-${dialogPdfSelectionSequence.toString(36)}`;
}

function createDialogTurnId(): string {
  dialogTurnSequence += 1;
  return `dialog-turn-${Date.now().toString(36)}-${dialogTurnSequence.toString(36)}`;
}

function dialogPdfSelectionsFromResearchSelections(
  value: unknown,
  turnId: string | null | undefined,
): DialogPdfSelectionState[] {
  const normalizedTurnId = String(turnId ?? '').trim();
  if (!normalizedTurnId) return [];
  return sanitizeResearchSelections(value).flatMap((researchSelection) => {
    if (researchSelection.turn_id !== normalizedTurnId) return [];
    const normalizedBbox = researchSelection.bbox_unit === 'normalized_ratio'
      ? researchSelection.bbox
      : undefined;
    if (researchSelection.kind !== 'text' && !normalizedBbox) return [];
    const selection = normalizeDialogPdfSelection({
      kind: researchSelection.kind,
      page: researchSelection.page,
      bbox: normalizedBbox,
      bbox_unit: normalizedBbox ? 'normalized_ratio' : undefined,
      text: researchSelection.text,
      label: researchSelection.label,
      chunk_id: researchSelection.chunk_id,
      candidate_id: researchSelection.candidate_id,
    });
    return selection ? [{
      id: researchSelection.selection_id,
      materialId: researchSelection.material_id,
      selection,
      restoredFromResearchSelection: true,
    }] : [];
  });
}

function dialogPdfSelectionIdentity(selectionState: DialogPdfSelectionState): string {
  const { selection } = selectionState;
  return [
    selectionState.materialId,
    selection.kind,
    selection.page,
    selection.candidate_id ?? '',
    selection.chunk_id ?? '',
    selection.bbox?.join(',') ?? '',
    selection.text ?? '',
  ].join('|');
}

function mergeDialogPdfSelections(
  primary: readonly DialogPdfSelectionState[],
  secondary: readonly DialogPdfSelectionState[] = [],
): DialogPdfSelectionState[] {
  const merged: DialogPdfSelectionState[] = [];
  const ids = new Set<string>();
  const identities = new Set<string>();
  for (const selection of [...primary, ...secondary]) {
    const id = selection.id.trim();
    const identity = dialogPdfSelectionIdentity(selection);
    if (!id || ids.has(id) || identities.has(identity)) continue;
    ids.add(id);
    identities.add(identity);
    merged.push(selection);
    if (merged.length >= DIALOG_PDF_SELECTION_MAX_COUNT) break;
  }
  return merged;
}

function selectionPrompt(
  kind: PdfContentSelection['kind'],
  selectionCount: number,
): string {
  if (selectionCount > 1) return DIALOG_MIXED_SELECTION_PROMPT;
  const promptByKind: Record<PdfContentSelection['kind'], string> = {
    text: '请分析选中的这段内容。',
    figure: '请分析选中的图。',
    table: '请分析选中的表。',
    formula: '请解释选中的公式。',
    region: '请分析选中的区域。',
  };
  return promptByKind[kind];
}

export function buildDialogFormulaCandidates(
  chunks: readonly ProjectChunkResource[],
  materialId: string,
): PdfFormulaCandidate[] {
  const normalizedMaterialId = normalizeMaterialId(materialId);
  if (!normalizedMaterialId) return [];
  const candidates: PdfFormulaCandidate[] = [];
  const candidateIds = new Set<string>();
  for (const [index, chunk] of chunks.entries()) {
    const chunkMaterialId = normalizeMaterialId(chunk.material_id ?? normalizedMaterialId);
    if (chunkMaterialId && chunkMaterialId !== normalizedMaterialId) continue;
    const chunkType = String(chunk.chunk_type ?? '').trim().toLowerCase();
    const equationLatex = normalizeDialogSelectionText(
      typeof chunk.equation_latex === 'string' ? chunk.equation_latex : null,
    );
    if (chunkType !== 'formula' && chunkType !== 'equation' && !equationLatex) continue;
    const page = normalizeDialogReaderPage(chunk.page);
    const bbox = isPdfBboxUnit(chunk.bbox_unit)
      ? normalizePdfUrlBbox(chunk.bbox ?? null, chunk.bbox_unit)
      : null;
    if (!page || !bbox) continue;
    const chunkId = normalizeMaterialId(chunk.chunk_id ?? '');
    const candidateId = chunkId || `formula-${normalizedMaterialId}-${page}-${index}`;
    if (candidateIds.has(candidateId)) continue;
    candidateIds.add(candidateId);
    const content = normalizeDialogSelectionText(
      typeof chunk.content === 'string' ? chunk.content : null,
    );
    candidates.push({
      candidateId,
      page,
      bbox,
      ...(chunkId ? { chunkId } : {}),
      ...(equationLatex || content ? { text: equationLatex ?? content ?? undefined } : {}),
    });
    if (candidates.length >= DIALOG_PDF_FORMULA_CANDIDATE_MAX_COUNT) break;
  }
  return candidates;
}

export function buildDialogFormulaCandidatesFromResources(
  resources: readonly FormulaCandidateResource[],
): PdfFormulaCandidate[] {
  const candidates: PdfFormulaCandidate[] = [];
  const candidateIds = new Set<string>();
  for (const resource of resources) {
    const candidateId = normalizeMaterialId(resource.candidate_id);
    const page = normalizeDialogReaderPage(resource.page);
    const bbox = isPdfBboxUnit(resource.bbox_unit)
      ? normalizePdfUrlBbox(resource.bbox, resource.bbox_unit)
      : null;
    if (!candidateId || !page || !bbox || candidateIds.has(candidateId)) continue;
    candidateIds.add(candidateId);
    const chunkId = normalizeMaterialId(resource.chunk_id ?? '');
    const text = normalizeDialogSelectionText(resource.text);
    candidates.push({
      candidateId,
      page,
      bbox,
      ...(chunkId ? { chunkId } : {}),
      ...(text ? { text } : {}),
    });
    if (candidates.length >= DIALOG_PDF_FORMULA_CANDIDATE_MAX_COUNT) break;
  }
  return candidates;
}

function isDialogPdfSelectionKind(value: unknown): value is PdfContentSelection['kind'] {
  return value === 'text'
    || value === 'figure'
    || value === 'table'
    || value === 'formula'
    || value === 'region';
}

function hasDurableVisualReplayLocator(selectionState: DialogPdfSelectionState): boolean {
  const { selection } = selectionState;
  if (
    selectionState.restoredFromResearchSelection !== true
    || !selectionState.materialId.trim()
    || selection.kind === 'text'
    || !Number.isSafeInteger(selection.page)
    || selection.page < 1
    || selection.bbox_unit !== 'normalized_ratio'
    || !selection.bbox
  ) {
    return false;
  }
  const [x, y, width, height] = selection.bbox;
  return [x, y, width, height].every(Number.isFinite)
    && x >= 0
    && y >= 0
    && width > 0
    && height > 0
    && x + width <= 1.0001
    && y + height <= 1.0001;
}

function selectionHasReplaySource(
  selectionState: DialogPdfSelectionState,
  attachments: ChatAttachment[],
): boolean {
  if (
    selectionState.selection.kind === 'text'
    || (
      selectionState.selection.kind === 'formula'
      && Boolean(selectionState.selection.text?.trim())
    )
  ) return true;
  if (hasDurableVisualReplayLocator(selectionState)) return true;
  return findSelectionImageIndex(selectionState, attachments) !== null;
}

function findSelectionImageIndex(
  selectionState: DialogPdfSelectionState,
  attachments: readonly ChatAttachment[],
): number | null {
  const fingerprint = selectionState.imageFingerprint?.trim() ?? '';
  if (!fingerprint) return null;
  const imageIndex = attachments.findIndex(
    (attachment) => chatAttachmentFingerprint(attachment) === fingerprint,
  );
  return imageIndex >= 0 ? imageIndex : null;
}

function selectionAttachmentFingerprints(
  selections: readonly DialogPdfSelectionState[],
): string[] {
  const fingerprints = new Set<string>();
  for (const selection of selections) {
    const fingerprint = selection.imageFingerprint?.trim() ?? '';
    if (fingerprint) fingerprints.add(fingerprint);
  }
  return [...fingerprints];
}

function withoutAttachmentFingerprints(
  attachments: readonly ChatAttachment[],
  fingerprints: readonly (string | null | undefined)[],
): ChatAttachment[] {
  const normalizedFingerprints = new Set(
    fingerprints.map((fingerprint) => fingerprint?.trim() ?? '').filter(Boolean),
  );
  if (normalizedFingerprints.size === 0) return [...attachments];
  return attachments.filter(
    (attachment) => !normalizedFingerprints.has(chatAttachmentFingerprint(attachment)),
  );
}

function mergeDialogRetryAttachments(
  current: readonly ChatAttachment[],
  retry: readonly ChatAttachment[],
  priorityFingerprints: readonly (string | null | undefined)[] = [],
): ChatAttachment[] {
  const merged: ChatAttachment[] = [];
  const seen = new Set<string>();
  const append = (attachment: ChatAttachment): void => {
    const key = `${attachment.mime}:${attachment.data_b64}`;
    if (seen.has(key) || merged.length >= CHAT_INPUT_VISION_LIMITS.maxImages) return;
    seen.add(key);
    merged.push(attachment);
  };

  current.forEach(append);
  for (const priorityFingerprint of priorityFingerprints) {
    const normalizedPriorityFingerprint = priorityFingerprint?.trim() ?? '';
    if (!normalizedPriorityFingerprint || merged.length >= CHAT_INPUT_VISION_LIMITS.maxImages) continue;
    const priorityAttachment = retry.find(
      (attachment) => chatAttachmentFingerprint(attachment) === normalizedPriorityFingerprint,
    );
    if (priorityAttachment) append(priorityAttachment);
  }
  retry.forEach(append);
  return merged;
}

function dialogSelectionContext(selectionState: DialogPdfSelectionState): IdentifiedChatSelectionContext {
  const { selection } = selectionState;
  const fallbackLabels: Record<PdfContentSelection['kind'], string> = {
    text: '文本选区',
    figure: '图',
    table: '表格',
    formula: '公式',
    region: '区域',
  };
  const fallbackLabel = fallbackLabels[selection.kind];
  return {
    id: selectionState.id,
    kind: selection.kind,
    page: selection.page,
    label: sanitizeChatVisibleText(selection.label || fallbackLabel, fallbackLabel, { maxLength: 60 }),
    ...(selection.kind === 'text' && selection.text ? { text: selection.text } : {}),
    ...(selectionState.imageFingerprint
      ? { attachmentFingerprint: selectionState.imageFingerprint }
      : {}),
  };
}

function normalizeDialogPdfSelection(
  rawSelection: PdfContentSelection | null | undefined,
): PdfContentSelection | undefined {
  if (!rawSelection) return undefined;
  const page = normalizeDialogReaderPage(rawSelection.page);
  const text = normalizeDialogSelectionText(rawSelection.text);
  const bbox = rawSelection.bbox_unit === 'normalized_ratio'
    ? normalizePdfUrlBbox(rawSelection.bbox ?? null, rawSelection.bbox_unit)
    : null;
  const kind = isDialogPdfSelectionKind(rawSelection.kind) ? rawSelection.kind : null;
  const visualSelection = kind !== null && kind !== 'text';
  const imageIndex = visualSelection
    && typeof rawSelection.image_index === 'number'
    && Number.isSafeInteger(rawSelection.image_index)
    && rawSelection.image_index >= 0
    ? rawSelection.image_index
    : null;
  if (!kind || !page || (kind === 'text' ? !text : !bbox)) return undefined;
  return {
    kind,
    page,
    ...(imageIndex !== null ? { image_index: imageIndex } : {}),
    ...(text ? { text } : { text: null }),
    ...(bbox ? { bbox, bbox_unit: 'normalized_ratio' as const } : { bbox: null }),
    ...(rawSelection.label !== undefined ? { label: rawSelection.label } : {}),
    ...(rawSelection.chunk_id !== undefined ? { chunk_id: rawSelection.chunk_id } : {}),
    ...(rawSelection.candidate_id !== undefined ? { candidate_id: rawSelection.candidate_id } : {}),
  };
}

function combineSelectionRects(rects: PdfSelectionAnchor['rects'] | undefined): PdfBbox | null {
  if (!rects || rects.length === 0) return null;
  const valid = rects.filter((rect) => (
    Number.isFinite(rect.x)
    && Number.isFinite(rect.y)
    && Number.isFinite(rect.w)
    && Number.isFinite(rect.h)
    && rect.w > 0
    && rect.h > 0
  ));
  if (valid.length === 0) return null;
  const left = Math.max(0, Math.min(...valid.map((rect) => rect.x)));
  const top = Math.max(0, Math.min(...valid.map((rect) => rect.y)));
  const right = Math.min(1, Math.max(...valid.map((rect) => rect.x + rect.w)));
  const bottom = Math.min(1, Math.max(...valid.map((rect) => rect.y + rect.h)));
  if (right <= left || bottom <= top) return null;
  return [left, top, right - left, bottom - top];
}

export function buildDialogCurrentPdfContext(input: BuildDialogCurrentPdfContextInput): CurrentPdfContext | undefined {
  const materialId = normalizeMaterialId(input.materialId ?? '');
  if (!materialId) return undefined;
  const rawSelections = input.selections && input.selections.length > 0
    ? input.selections
    : input.selection
      ? [input.selection]
      : [];
  const selections = rawSelections
    .slice(0, DIALOG_PDF_SELECTION_MAX_COUNT)
    .map(normalizeDialogPdfSelection)
    .filter((selection): selection is PdfContentSelection => selection !== undefined);
  const selection = selections[0];
  const page = selection?.page ?? normalizeDialogReaderPage(input.page);
  const selectedText = selection?.text ?? normalizeDialogSelectionText(input.selectedText);
  const bboxUnit = isPdfBboxUnit(input.bboxUnit) ? input.bboxUnit : null;
  const bbox = selection?.bbox
    ?? (bboxUnit ? normalizePdfUrlBbox(input.bbox ?? null, bboxUnit) : null);
  const chunkId = normalizeMaterialId(selection?.chunk_id ?? input.chunkId ?? '');
  if (!page && !selectedText && !chunkId) return undefined;
  return {
    material_id: materialId,
    ...(page ? { page } : {}),
    ...(chunkId ? { chunk_id: chunkId } : {}),
    ...(bbox ? { bbox, bbox_unit: 'normalized_ratio' } : {}),
    ...(selectedText ? { selected_text: selectedText } : {}),
    ...(selection ? { selection } : {}),
    ...(selections.length > 0 ? { selections } : {}),
    context_kind: selection || selectedText ? 'selection' : bbox || chunkId ? 'deep_link' : 'reader_page',
    source_labels: [
      'dialog_smart_read',
      selection || selectedText ? 'pdf_selection' : 'pdf_reader_page',
    ],
  };
}

export function resolveDialogSmartReadChatSessionId(
  artifactContent: Record<string, unknown>,
  previousSessionId?: string | null,
): string | undefined {
  return normalizeChatHistorySessionId(artifactContent.session_id)
    ?? normalizeChatHistorySessionId(previousSessionId);
}

function mapDialogMessageToChatData(message: ChatMessage): ChatMessageData {
  const diagnostics = buildDialogDiagnostics(message);
  return {
    id: message.id,
    role: message.role,
    turnId: message.turnId,
    content: message.role === 'assistant'
      ? dialogVisibleAnswerContent(message.content, message.answerOrigin ?? 'internal_smartread')
      : message.content,
    researchSelections: message.researchSelections,
    visualObservationRefs: message.visualObservationRefs,
    evidence: coerceEvidenceRefs(message.evidenceRefs),
    timestamp: message.timestamp.toISOString(),
    status: message.status,
    relatedFigures: message.relatedFigures,
    metadata: diagnostics ? { diagnostics } : undefined,
  };
}

function buildDialogDiagnostics(message: ChatMessage): ChatMessageDiagnostics | undefined {
  if (message.role !== 'assistant') return undefined;
  const chunks = message.contextMetadata?.chunks ?? [];
  const chunkRefs = extractChunkRefs(message.content);
  const diagnostics: ChatMessageDiagnostics = {};
  if (message.tierUsed) {
    diagnostics.tier = message.tierUsed;
  }
  if (message.answerOrigin) {
    diagnostics.answerOrigin = message.answerOrigin;
  }
  if (message.answerModelOrigin) {
    diagnostics.answerModelOrigin = message.answerModelOrigin;
  }
  if (message.retrievalProvider) {
    diagnostics.retrievalProvider = message.retrievalProvider;
  }
  if (message.actualSamplingParams) {
    diagnostics.sampling = message.actualSamplingParams;
  }
  if (message.tokensUsed) {
    diagnostics.tokens = message.tokensUsed;
  }
  if (message.retrievalDiagnostics) {
    diagnostics.retrieval = message.retrievalDiagnostics;
  }
  if (message.insufficientContext) {
    diagnostics.insufficient = true;
  }
  if (chunks.length > 0) {
    diagnostics.context = {
      chunkCount: chunks.length,
      sourceCount: new Set(chunks.map((chunk) => chunk.source)).size,
      chunks: chunks.map((chunk) => ({
        index: chunk.index,
        source: chunk.source,
        content: chunk.content,
        relevance_score: chunk.relevance_score,
        chunk_id: chunk.chunk_id,
        material_id: chunk.material_id,
        evidence_role: chunk.evidence_role,
        title: chunk.title,
        section_title: chunk.section_title,
        page: chunk.page,
        bbox: chunk.bbox ?? null,
        bbox_unit: chunk.bbox_unit ?? null,
        source_labels: chunk.source_labels,
        source_hint: chunk.source_hint,
      })),
    };
  }
  if (chunkRefs.length > 0) {
    diagnostics.chunkRefs = chunkRefs;
  }
  return Object.keys(diagnostics).length > 0 ? diagnostics : undefined;
}

function replaceOrAppendChatData(messages: ChatMessageData[], nextMessage: ChatMessageData): ChatMessageData[] {
  const index = messages.findIndex((message) => message.id === nextMessage.id);
  if (index < 0) return [...messages, nextMessage];
  return [
    ...messages.slice(0, index),
    nextMessage,
    ...messages.slice(index + 1),
  ];
}

function markLatestStreamingAssistantStopped(messages: ChatMessageData[]): ChatMessageData[] {
  const index = [...messages]
    .reverse()
    .findIndex((message) => message.role === 'assistant' && message.status === 'streaming');
  if (index < 0) return messages;
  const targetIndex = messages.length - 1 - index;
  return messages.map((message, currentIndex) => {
    if (currentIndex !== targetIndex) return message;
    return {
      ...message,
      content: message.content || '已停止生成。',
      status: 'done',
    };
  });
}

const PdfReaderShell = lazy(() =>
  import('@/components/PdfViewer/PdfReaderShell').then((module) => ({
    default: module.PdfReaderShell,
  })),
);

function PdfReaderFallback() {
  return (
    <div className="flex h-full w-full items-center justify-center text-foreground/40">
      <Loader2 className="h-6 w-6 animate-spin" aria-label="正在载入阅读器" />
    </div>
  );
}

const ENHANCEMENT_MENU_ITEMS: Array<{
  id: DiscussionEnhancementIntent;
  label: string;
  description: string;
  icon: typeof Users2;
}> = [
  { id: 'reading', label: '多人研读', description: '多角色围绕本文献研读讨论', icon: Users2 },
  { id: 'writing', label: '写作思路', description: '生成论文写作内容框架', icon: FileText },
  { id: 'research', label: '研究思路', description: '提出后续研究假设与实验', icon: Network },
];

function ComposerControlMenu({
  label,
  title,
  icon: Icon,
  disabled,
  align = 'left',
  width = 'default',
  children,
}: {
  label: string;
  title: string;
  icon: typeof Users2;
  disabled?: boolean;
  align?: 'left' | 'right';
  width?: 'default' | 'compact';
  children: (close: () => void) => ReactNode;
}) {
  const menuId = useId();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!disabled) return undefined;
    setOpen(false);
    return undefined;
  }, [disabled]);

  useEffect(() => {
    if (!open) return undefined;
    const handlePointerDown = (event: PointerEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener('pointerdown', handlePointerDown);
    return () => window.removeEventListener('pointerdown', handlePointerDown);
  }, [open]);

  const close = useCallback((): void => {
    setOpen(false);
    window.setTimeout(() => buttonRef.current?.focus(), 0);
  }, []);

  function handleContainerKeyDown(event: ReactKeyboardEvent<HTMLDivElement>): void {
    if (event.key !== 'Escape' || !open) return;
    event.stopPropagation();
    close();
  }

  function handleButtonKeyDown(event: ReactKeyboardEvent<HTMLButtonElement>): void {
    if (event.key !== 'ArrowDown') return;
    event.preventDefault();
    setOpen(true);
  }

  return (
    <div ref={containerRef} className="relative shrink-0" onKeyDown={handleContainerKeyDown}>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((value) => !value)}
        onKeyDown={handleButtonKeyDown}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        className="inline-flex h-8 min-w-[3.25rem] items-center justify-center gap-0.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-1 text-[11px] font-medium text-foreground/70 transition-colors hover:border-primary/40 hover:bg-primary/5 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:cursor-not-allowed disabled:opacity-45"
        title={title}
      >
        <Icon className="h-3.5 w-3.5" aria-hidden />
        {label}
        <ChevronDown className={`h-3 w-3 text-foreground/40 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden />
      </button>
      {open && (
        <div
          id={menuId}
          role="menu"
          className={`absolute z-30 mt-1 max-h-[min(18rem,calc(100vh-8rem))] max-w-[calc(100vw-2rem)] overflow-y-auto rounded-md border border-outline-variant/60 bg-surface-lowest p-1 shadow-lg ${
            width === 'compact' ? 'w-48' : 'w-56'
          } ${
            align === 'right' ? 'right-0' : 'left-0'
          }`}
        >
          {children(close)}
        </div>
      )}
    </div>
  );
}

function ComposerMenuItem({
  label,
  description,
  icon: Icon,
  role = 'menuitemradio',
  selected,
  disabled,
  title,
  onSelect,
}: {
  label: string;
  description: string;
  icon: typeof Users2;
  role?: 'menuitem' | 'menuitemradio';
  selected?: boolean;
  disabled?: boolean;
  title?: string;
  onSelect: () => void;
}) {
  const checkedProps = role === 'menuitemradio'
    ? { 'aria-checked': Boolean(selected) }
    : {};
  return (
    <button
      type="button"
      role={role}
      aria-label={label}
      {...checkedProps}
      disabled={disabled}
      onClick={onSelect}
      title={title ?? description}
      className={`flex w-full items-start gap-2 rounded px-2 py-1.5 text-left transition-colors ${
        selected ? 'bg-primary/10' : 'hover:bg-primary/8'
      } disabled:cursor-not-allowed disabled:opacity-45`}
    >
      <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${selected ? 'text-primary' : 'text-foreground/45'}`} aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block text-xs font-medium text-foreground/80">{label}</span>
        <span className="block text-[11px] leading-snug text-foreground/50">{description}</span>
      </span>
      {selected ? <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden /> : null}
    </button>
  );
}

function EnhancementMenu({
  disabled,
  onSelect,
}: {
  disabled?: boolean;
  onSelect: (intent: DiscussionEnhancementIntent) => void;
}) {
  return (
    <ComposerControlMenu
      label="增强"
      title="用多智能体讨论增强当前研读"
      icon={Sparkles}
      disabled={disabled}
      align="right"
    >
      {(close) => ENHANCEMENT_MENU_ITEMS.map((item) => (
        <ComposerMenuItem
          key={item.id}
          role="menuitem"
          label={item.label}
          description={item.description}
          icon={item.icon}
          onSelect={() => {
            close();
            onSelect(item.id);
          }}
        />
      ))}
    </ComposerControlMenu>
  );
}

function DialogDiscussionWorkbench({
  launchState,
  onHistoryChanged,
}: {
  launchState: DiscussionLaunchState | null;
  onHistoryChanged?: () => void | Promise<void>;
}) {
  const [defaults, setDefaults] = useState<DiscussionDefaults>({ ...DEFAULT_DISCUSSION_DEFAULTS });

  useEffect(() => {
    let cancelled = false;
    async function loadDefaults(): Promise<void> {
      try {
        const { data } = await axios.get<unknown>(`${getApiBaseUrl()}/api/discussion/defaults`, {
          timeout: 10_000,
        });
        if (!cancelled) {
          setDefaults(normalizeDiscussionDefaults(data));
        }
      } catch {
        if (!cancelled) {
          setDefaults({ ...DEFAULT_DISCUSSION_DEFAULTS });
        }
      }
    }

    void loadDefaults();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-background p-4">
      <div className="mx-auto max-w-6xl">
        <DiscussionPanel
          defaults={defaults}
          initialQuery={launchState?.query}
          initialEvidenceMode={launchState?.evidenceMode}
          onHistoryChanged={onHistoryChanged}
        />
      </div>
    </div>
  );
}

export function Dialog() {
  const { activeProjectId, setActiveProjectId } = useWriting();
  const { getConversation, setConversation, clearConversation } = useSmartRead();
  const {
    openTab: openPdfTab,
    getView: getPdfView,
    updateView: updatePdfView,
  } = usePdfTabs();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryProjectId = normalizeProjectId(searchParams.get('project_id'));
  const queryConversationId = normalizeChatHistorySessionId(
    searchParams.get('conversation_id') ?? searchParams.get('session_id') ?? searchParams.get('receipt'),
  );
  const pinnedMaterialId = normalizeMaterialId(searchParams.get('material_id') ?? searchParams.get('material'));
  const pinnedMaterialTitle = normalizeMaterialId(searchParams.get('material_title') ?? searchParams.get('title'));
  const effectiveProjectId = normalizeProjectId(activeProjectId || queryProjectId);
  const urlContextScope = normalizeDialogContextScope(searchParams.get('scope'), pinnedMaterialId);
  const dialogContextScope = urlContextScope;
  const legacyDialogMode = normalizeDialogWorkbenchMode(searchParams.get('mode'));
  const urlCenterTab = normalizeDialogCenterTab(searchParams.get('tab'));

  // The Dialog surface is now one smart-read conversation. Legacy per-mode
  // keys are read as a migration fallback only so existing local drafts still
  // appear after the mode switch UI is removed.
  const projectStorageScope = effectiveProjectId || 'default';
  const smartReadScope = buildDialogSmartReadScope(dialogContextScope, effectiveProjectId, pinnedMaterialId);
  const dialogStorageScope = buildDialogStorageScope(dialogContextScope, effectiveProjectId, pinnedMaterialId);
  const inputStorageKey = `dialog-input_${dialogStorageScope}`;
  const sessionStorageKey = `dialog-session_${dialogStorageScope}`;
  const conversation = getConversation(smartReadScope);
  const _messages = useMemo(
    () => conversation.messages.flatMap((message) => {
      try {
        return [mapChatDataToDialogMessage(message)];
      } catch {
        return [];
      }
    }),
    [conversation.messages],
  );
  const [inputValue, setInputValue] = useState<string>(() => {
    try {
      return readFirstStorageValue([
        inputStorageKey,
        ...legacyScopedKeys(projectStorageScope, 'input'),
      ]) ?? '';
    } catch { return ''; }
  });
  const [sessionId, setSessionId] = useState<string | undefined>(() => {
    try {
      return readFirstStorageValue([
        sessionStorageKey,
        ...legacyScopedKeys(projectStorageScope, 'session'),
      ]) ?? conversation.sessionId ?? undefined;
    } catch { return undefined; }
  });
  const [chatState, setChatState] = useState<ChatState>(() =>
    dialogAbortControllers.has(smartReadScope) ? 'responding' : 'ready',
  );
  const [historyState, setHistoryState] = useState<HistoryState>('idle');
  const [historyQuery, setHistoryQuery] = useState('');
  const [historySearchState, setHistorySearchState] = useState<SearchState>('idle');
  const [historyResults, setHistoryResults] = useState<ChatHistorySearchResult[]>([]);
  const [historyMode, setHistoryMode] = useState<HistoryMode>('recent');
  const [historyRailOpen, setHistoryRailOpen] = useState(false);
  const [historyRailCollapsed, setHistoryRailCollapsed] = useState(() =>
    readDialogBoolean(DIALOG_HISTORY_COLLAPSED_STORAGE_KEY, false),
  );
  const [contextRailOpen, setContextRailOpen] = useState(() =>
    readDialogBoolean(DIALOG_CONTEXT_OPEN_STORAGE_KEY, true),
  );
  const [contextRailTab, setContextRailTab] = useState<DialogContextRailTab>(() =>
    readDialogContextRailTab(
      pinnedMaterialId
        ? pinnedMaterialTitle.toLowerCase().endsWith('.pdf')
          ? urlCenterTab === 'discussion' ? 'discussion' : 'chat'
          : 'paper'
        : 'graph',
    ),
  );
  const [graphExplorerOpen, setGraphExplorerOpen] = useState(false);
  const [graphSelectedDimensions, setGraphSelectedDimensions] = useState<Set<ReasoningDimension>>(() => new Set());
  const [centerTab, setCenterTab] = useState<DialogCenterTab>(() => {
    if (pinnedMaterialId && pinnedMaterialTitle.toLowerCase().endsWith('.pdf')) return 'reader';
    if (urlCenterTab) return urlCenterTab;
    return readDialogCenterTab(legacyDialogMode === 'discussion' ? 'discussion' : 'chat');
  });
  const [paneWidths, setPaneWidths] = useState<DialogPaneWidths>(() => readDialogPaneWidths());
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [projectNames, setProjectNames] = useState<Record<string, string>>({});
  const [projectMaterials, setProjectMaterials] = useState<WritingMaterialResource[]>([]);
  const [projectMaterialsState, setProjectMaterialsState] = useState<ProjectMaterialsState>('idle');
  const [projectMaterialsError, setProjectMaterialsError] = useState<string | null>(null);
  const [annotationNotes, setAnnotationNotes] = useState<AnnotationNote[]>([]);
  const [annotationNotesState, setAnnotationNotesState] = useState<AnnotationNotesState>('idle');
  const [annotationNotesError, setAnnotationNotesError] = useState<string | null>(null);
  const [suggestedQuestionChunks, setSuggestedQuestionChunks] = useState<ProjectChunkResource[]>([]);
  const [suggestedQuestionState, setSuggestedQuestionState] = useState<SuggestedQuestionState>('idle');
  const [backendSuggestedQuestions, setBackendSuggestedQuestions] = useState<SuggestedQuestion[] | null>(null);
  const [readerFormulaCandidates, setReaderFormulaCandidates] = useState<PdfFormulaCandidate[]>([]);
  const [embeddedReaderTarget, setEmbeddedReaderTarget] = useState<{
    page?: number;
    bbox?: PdfBbox;
    bboxUnit?: PdfBboxUnit | null;
    chunkId?: string;
    quote?: string;
    nonce: number;
  }>({ nonce: 0 });
  const [embeddedReaderPage, setEmbeddedReaderPage] = useState<number | null>(null);
  const [draftAttachments, setDraftAttachmentsState] = useState<ChatAttachment[]>([]);
  const draftAttachmentsRef = useRef<ChatAttachment[]>(draftAttachments);
  const setDraftAttachments = useCallback((update: SetStateAction<ChatAttachment[]>): void => {
    const next = typeof update === 'function'
      ? update(draftAttachmentsRef.current)
      : update;
    draftAttachmentsRef.current = next;
    setDraftAttachmentsState(next);
  }, []);
  const [pendingAttachmentReads, setPendingAttachmentReads] = useState(0);
  const [currentPdfSelections, setCurrentPdfSelectionsState] = useState<DialogPdfSelectionState[]>([]);
  const currentPdfSelectionsRef = useRef<DialogPdfSelectionState[]>(currentPdfSelections);
  const setCurrentPdfSelections = useCallback((
    update: SetStateAction<DialogPdfSelectionState[]>,
  ): void => {
    const next = typeof update === 'function'
      ? update(currentPdfSelectionsRef.current)
      : update;
    currentPdfSelectionsRef.current = next;
    setCurrentPdfSelectionsState(next);
  }, []);
  const clearCurrentPdfSelectionsAndAttachments = useCallback((): void => {
    const fingerprints = selectionAttachmentFingerprints(currentPdfSelectionsRef.current);
    setCurrentPdfSelections([]);
    if (fingerprints.length > 0) {
      setDraftAttachments((current) => withoutAttachmentFingerprints(current, fingerprints));
    }
  }, [setCurrentPdfSelections, setDraftAttachments]);
  const [discussionLaunchState, setDiscussionLaunchState] = useState<DiscussionLaunchState | null>(() => (
    normalizeDiscussionLaunchState(location.state) ?? readDiscussionLaunchState()
  ));
  const [historyErrorMessage, setHistoryErrorMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isUnavailable, setIsUnavailable] = useState(false);
  const [requestStartedAt, setRequestStartedAt] = useState<number | null>(
    () => dialogRequestStartedAtByScope.get(smartReadScope) ?? null,
  );
  const [requestElapsedSec, setRequestElapsedSec] = useState(0);
  const conversationMessages = useMemo(
    () => conversation.messages,
    [conversation.messages],
  );
  const visibleConversationMessages = useMemo(
    () => conversationMessages.map((message) => {
      if (message.role !== 'assistant') return message;
      const answerOrigin = message.metadata?.diagnostics?.answerOrigin ?? 'internal_smartread';
      const content = dialogVisibleAnswerContent(message.content, answerOrigin);
      return content === message.content ? message : { ...message, content };
    }),
    [conversationMessages],
  );
  const localEvidenceGraphPayload = useMemo(
    () => buildAnswerTurnGraphPayload(conversationMessages, {
      sessionId: normalizeChatHistorySessionId(sessionId ?? conversation.sessionId ?? '')
        ?? `local:${smartReadScope}`,
    }),
    [conversation.sessionId, conversationMessages, sessionId, smartReadScope],
  );
  const evidenceGraphSessionId = normalizeChatHistorySessionId(sessionId ?? conversation.sessionId ?? '');
  const evidenceGraphTurnId = useMemo(() => {
    for (const node of localEvidenceGraphPayload?.nodes ?? []) {
      const value = node.metadata?.turn_id;
      if (typeof value === 'string' && value.trim()) return value.trim();
    }
    return null;
  }, [localEvidenceGraphPayload]);
  const [persistedEvidenceGraphPayload, setPersistedEvidenceGraphPayload] = useState<GraphPayloadV0 | null>(null);
  const [evidenceGraphRefreshToken, setEvidenceGraphRefreshToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setPersistedEvidenceGraphPayload(null);
    if (!evidenceGraphSessionId || !evidenceGraphTurnId) return () => {
      cancelled = true;
    };

    void getAnswerEvidenceGraph({
      session_id: evidenceGraphSessionId,
      turn_id: evidenceGraphTurnId,
    }).then((payload) => {
      if (cancelled) return;
      const adapted = evidenceGraphToGraphPayload(payload);
      if (adapted.nodes.length > 0) setPersistedEvidenceGraphPayload(adapted);
    }).catch(() => {
      if (!cancelled) setPersistedEvidenceGraphPayload(null);
    });

    return () => {
      cancelled = true;
    };
  }, [evidenceGraphRefreshToken, evidenceGraphSessionId, evidenceGraphTurnId]);

  const evidenceGraphPayload = persistedEvidenceGraphPayload ?? localEvidenceGraphPayload;
  const evidenceGraphStats = useMemo(() => ({
    evidence: evidenceGraphPayload?.nodes.filter((node) => node.type === 'evidence').length ?? 0,
    materials: evidenceGraphPayload?.nodes.filter((node) => node.type === 'material').length ?? 0,
    edges: evidenceGraphPayload?.edges.length ?? 0,
  }), [evidenceGraphPayload]);

  useEffect(() => {
    if (!evidenceGraphPayload && graphExplorerOpen) {
      setGraphExplorerOpen(false);
    }
  }, [evidenceGraphPayload, graphExplorerOpen]);

  useEffect(() => {
    if (!graphExplorerOpen) return undefined;
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        setGraphExplorerOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [graphExplorerOpen]);

  useEffect(() => {
    if (!graphExplorerOpen) return undefined;
    const shell = dialogShellRef.current;
    if (!shell) return undefined;
    const backgroundElements = Array.from(shell.children).filter((child): child is HTMLElement => {
      if (!(child instanceof HTMLElement)) return false;
      return child.getAttribute('role') !== 'dialog';
    });
    const previousState = backgroundElements.map((element) => ({
      element,
      inert: element.inert === true,
      ariaHidden: element.getAttribute('aria-hidden'),
    }));
    for (const element of backgroundElements) {
      element.inert = true;
      element.setAttribute('aria-hidden', 'true');
    }
    return () => {
      for (const { element, inert, ariaHidden } of previousState) {
        element.inert = inert;
        if (ariaHidden === null) {
          element.removeAttribute('aria-hidden');
        } else {
          element.setAttribute('aria-hidden', ariaHidden);
        }
      }
    };
  }, [graphExplorerOpen]);

  const activePinnedMaterial = useMemo(
    () => projectMaterials.find((material) => material.material_id === pinnedMaterialId) ?? null,
    [pinnedMaterialId, projectMaterials],
  );
  const suggestedQuestions = useMemo<SuggestedQuestion[]>(
    () => backendSuggestedQuestions ?? buildSuggestedQuestions(activePinnedMaterial, suggestedQuestionChunks),
    [backendSuggestedQuestions, activePinnedMaterial, suggestedQuestionChunks],
  );
  const pinnedLooksLikePdf = useMemo(() => {
    // B10 (2026-06-13): 之前只看 title.endsWith('.pdf')，但
    //   (1) title 可能来自 URL searchParam，在刚切换 material 的那一帧还没同步
    //   (2) 用户上传的 PDF 可能不带 .pdf 扩展（命名为 paper / 1 等）
    // 后端 backend 当前给 type='reference' 不区分文件格式，所以这里降级为
    // 「乐观判定」：只要有 pinnedMaterialId 就先认作可以打开 reader；真正
    // 不能渲染时 PdfViewer 会自己降级到错误态。这样避免「点研读后中间栏
    // 强制回 chat」的 race，并修复无扩展名 PDF 也能打开（用户反馈）。
    const name = String(pinnedMaterialTitle || activePinnedMaterial?.title || '').trim().toLowerCase();
    if (name.endsWith('.pdf')) return true;
    if (pinnedMaterialId) return true;  // optimistic — reader 自己会显示错误
    return false;
  }, [activePinnedMaterial, pinnedMaterialId, pinnedMaterialTitle]);
  const pinnedPdfUrl = useMemo(
    () => (pinnedMaterialId ? `${getApiBaseUrl()}/resources/document/${pinnedMaterialId}/file` : ''),
    [pinnedMaterialId],
  );
  const persistedPinnedPdfView = pinnedMaterialId ? getPdfView(pinnedMaterialId) : undefined;
  const urlReaderPage = normalizeDialogReaderPage(searchParams.get('page'));
  const urlReaderChunkId = normalizeMaterialId(searchParams.get('chunk'));
  const urlReaderBbox = urlReaderPage
    ? parsePdfBboxSearchParam(searchParams.get('bbox'))
    : null;
  const urlReaderAnchorKind = searchParams.get('anchor_kind') === 'visual' ? 'visual' : 'text';
  const urlReaderQuote = urlReaderAnchorKind === 'visual'
    ? null
    : normalizePdfQuote(searchParams.get('quote'));
  const urlReaderTargetKey = [
    pinnedMaterialId,
    searchParams.get('page') ?? '',
    searchParams.get('bbox') ?? '',
    searchParams.get('chunk') ?? '',
    searchParams.get('quote') ?? '',
    searchParams.get('anchor_kind') ?? '',
  ].join(':');
  const embeddedTargetHasPage = embeddedReaderTarget.page !== undefined;
  const embeddedPageOverridesUrlTarget = embeddedReaderPage !== null;
  const effectiveReaderPage = embeddedReaderTarget.page
    ?? embeddedReaderPage
    ?? urlReaderPage
    ?? persistedPinnedPdfView?.page
    ?? null;
  const effectiveReaderBbox = embeddedTargetHasPage
    ? embeddedReaderTarget.bboxUnit === 'normalized_ratio'
      ? embeddedReaderTarget.bbox
      : undefined
    : embeddedPageOverridesUrlTarget
      ? undefined
      : urlReaderBbox ?? undefined;
  // URL bbox values use the normalized_ratio protocol. Embedded targets must
  // declare the same unit explicitly; otherwise retain only page/chunk.
  const effectiveReaderBboxUnit: PdfBboxUnit | null = effectiveReaderBbox
    ? 'normalized_ratio'
    : null;
  const effectiveReaderChunkId = embeddedTargetHasPage
    ? embeddedReaderTarget.chunkId
    : embeddedPageOverridesUrlTarget
      ? undefined
      : embeddedReaderTarget.chunkId ?? urlReaderChunkId ?? undefined;
  const effectiveReaderQuote = embeddedTargetHasPage
    ? embeddedReaderTarget.quote
    : embeddedPageOverridesUrlTarget
      ? undefined
      : embeddedReaderTarget.quote ?? urlReaderQuote ?? undefined;
  const embeddedReaderHighlights = useMemo<Highlight[]>(() => {
    if (!effectiveReaderPage || effectiveReaderQuote) return [];
    const rect = toPdfHighlightRect(effectiveReaderBbox, effectiveReaderBboxUnit ?? null);
    if (!rect) return [];
    return [{
      page: effectiveReaderPage,
      text: '当前跳转证据位置',
      color: '#60A5FA',
      rects: [rect],
    }];
  }, [effectiveReaderBbox, effectiveReaderBboxUnit, effectiveReaderPage, effectiveReaderQuote]);
  const selectedReaderVisualRegions = useMemo<PdfSelectedVisualRegion[]>(() => (
    currentPdfSelections.flatMap((selectionState) => {
      const { selection } = selectionState;
      if (selectionState.materialId !== pinnedMaterialId || selection.kind === 'text') return [];
      const bbox = selection.bbox_unit === 'normalized_ratio'
        ? normalizePdfUrlBbox(selection.bbox ?? null, selection.bbox_unit)
        : null;
      if (!bbox) return [];
      return [{
        kind: selection.kind,
        page: selection.page,
        bbox,
        ...(selection.candidate_id ? { candidateId: selection.candidate_id } : {}),
      }];
    })
  ), [currentPdfSelections, pinnedMaterialId]);
  const readerTabAvailable = !!pinnedMaterialId && pinnedLooksLikePdf;
  const readerInCenter = readerTabAvailable;
  const projectMaterialCount = projectMaterials.length;
  const annotationNoteCount = annotationNotes.length;
  const requestProjectId = effectiveProjectId || undefined;
  const requestMaterialId = dialogContextScope === 'paper' && pinnedMaterialId ? pinnedMaterialId : undefined;
  const activeMaterialLabel = useMemo(
    () => sanitizeChatVisibleText(pinnedMaterialTitle || pinnedMaterialId, '当前文献', { maxLength: 64 }),
    [pinnedMaterialId, pinnedMaterialTitle],
  );
  const inputPlaceholder = dialogContextScope === 'paper' && pinnedMaterialId
    ? `围绕「${activeMaterialLabel}」提问…`
    : UNIFIED_INPUT_PLACEHOLDER;
  const hasStreamingAssistant = useMemo(
    () => conversationMessages.some((message) => message.role === 'assistant' && message.status === 'streaming'),
    [conversationMessages],
  );
  const isResponseActive =
    chatState === 'responding' ||
    hasStreamingAssistant ||
    dialogAbortControllers.has(smartReadScope);
  const sessionProjectGroups = useMemo(
    () => buildSessionProjectGroups(sessions, projectNames),
    [projectNames, sessions],
  );
  const conversationMessagesRef = useRef<ChatMessageData[]>(conversationMessages);
  const activeAbortControllerRef = useRef<AbortController | null>(null);
  const isMountedRef = useRef(true);
  const restoringSessionIdRef = useRef<string | null>(null);
  const evidenceActivationSequenceRef = useRef(0);
  const urlConversationRestoreRef = useRef<string | null>(null);
  const taskCenterNavigationPendingRef = useRef(false);
  const dialogShellRef = useRef<HTMLDivElement | null>(null);
  const chatInputRef = useRef<ChatInputHandle | null>(null);
  const pendingResearchSelectionRestoreRef = useRef<DialogPdfSelectionState[] | null>(null);
  const previousPinnedMaterialIdRef = useRef('');
  const previousUrlReaderTargetKeyRef = useRef<string | null>(null);
  const currentRequestContextRef = useRef<DialogRequestContextRevision>({
    projectId: requestProjectId ?? null,
    materialId: pinnedMaterialId || null,
    contextScope: dialogContextScope,
    sessionId: normalizeChatHistorySessionId(sessionId ?? conversation.sessionId) ?? null,
    revision: 0,
  });
  const previousRequestContext = currentRequestContextRef.current;
  const nextRequestContext = {
    projectId: requestProjectId ?? null,
    materialId: pinnedMaterialId || null,
    contextScope: dialogContextScope,
    sessionId: normalizeChatHistorySessionId(sessionId ?? conversation.sessionId) ?? null,
  };
  if (
    previousRequestContext.projectId !== nextRequestContext.projectId
    || previousRequestContext.materialId !== nextRequestContext.materialId
    || previousRequestContext.contextScope !== nextRequestContext.contextScope
    || previousRequestContext.sessionId !== nextRequestContext.sessionId
  ) {
    currentRequestContextRef.current = {
      ...nextRequestContext,
      revision: previousRequestContext.revision + 1,
    };
  }
  const requestContextRevision = currentRequestContextRef.current.revision;
  const clearedSelectionContextRevisionRef = useRef(requestContextRevision);
  const projectReasoningBias = useProjectReasoningBiasState(activeProjectId);
  const defaultProjectBiasEnabled = projectReasoningBias.isEnabledForSurface('chat_generation');
  const [projectBiasEnabled, setProjectBiasEnabled] = useState(defaultProjectBiasEnabled);
  const [agentHandoffState, setAgentHandoffState] = useState<AgentHandoffState>('idle');
  const [agentHandoffMessage, setAgentHandoffMessage] = useState<string | null>(null);
  const [agentHandoffRequest, setAgentHandoffRequest] = useState<AgentSidebarAnswerRequestResponse | null>(null);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (clearedSelectionContextRevisionRef.current === requestContextRevision) return;
    clearedSelectionContextRevisionRef.current = requestContextRevision;
    clearCurrentPdfSelectionsAndAttachments();
    const pendingSelections = pendingResearchSelectionRestoreRef.current;
    if (!pendingSelections || pendingSelections.length === 0) return;
    const targetMaterialId = pendingSelections[0]?.materialId ?? '';
    const activeMaterialId = currentRequestContextRef.current.materialId ?? '';
    if (targetMaterialId && activeMaterialId !== targetMaterialId) return;
    pendingResearchSelectionRestoreRef.current = null;
    setCurrentPdfSelections(pendingSelections);
  }, [clearCurrentPdfSelectionsAndAttachments, requestContextRevision, setCurrentPdfSelections]);

  const focusComposerAfterDraftWrite = useCallback((selection: 'start' | 'end' | 'all' = 'end') => {
    window.setTimeout(() => {
      chatInputRef.current?.focus({ selection });
    }, 0);
  }, []);

  const refreshProjectMaterials = useCallback(async (
    options: { surfaceError?: boolean } = {},
  ): Promise<void> => {
    if (!effectiveProjectId) {
      setProjectMaterials([]);
      setProjectMaterialsState('idle');
      setProjectMaterialsError(null);
      return;
    }
    setProjectMaterialsState('loading');
    if (options.surfaceError !== false) {
      setProjectMaterialsError(null);
    }
    try {
      const materials = await getWritingBackendService().listMaterials(effectiveProjectId);
      setProjectMaterials(materials.filter((material) => normalizeMaterialId(material.material_id)));
      setProjectMaterialsState('idle');
      setProjectMaterialsError(null);
    } catch (error) {
      setProjectMaterialsState('error');
      if (options.surfaceError !== false) {
        setProjectMaterialsError(getChatErrorMessage(error));
      }
    }
  }, [effectiveProjectId]);
  const refreshAnnotationNotes = useCallback(async (
    options: { surfaceError?: boolean } = {},
  ): Promise<void> => {
    if (!pinnedMaterialId) {
      setAnnotationNotes([]);
      setAnnotationNotesState('idle');
      setAnnotationNotesError(null);
      return;
    }
    setAnnotationNotesState('loading');
    if (options.surfaceError !== false) {
      setAnnotationNotesError(null);
    }
    try {
      const annotation = await getAnnotations(pinnedMaterialId);
      setAnnotationNotes(annotation.notes ?? []);
      setAnnotationNotesState('idle');
      setAnnotationNotesError(null);
    } catch (error) {
      setAnnotationNotesState('error');
      if (options.surfaceError !== false) {
        setAnnotationNotesError(getChatErrorMessage(error));
      }
    }
  }, [pinnedMaterialId]);

  const refreshSuggestedQuestionChunks = useCallback(async (): Promise<void> => {
    if (!effectiveProjectId || !pinnedMaterialId) {
      setSuggestedQuestionChunks([]);
      setBackendSuggestedQuestions(null);
      setSuggestedQuestionState('idle');
      return;
    }
    setSuggestedQuestionState('loading');
    // Prefer backend deterministic generation (uses the full chunk set, no model call).
    try {
      const { data } = await axios.get<{ questions?: SuggestedQuestion[] }>(
        `${getApiBaseUrl()}/resources/material/${encodeURIComponent(pinnedMaterialId)}/suggested-questions`,
        { params: { project_id: effectiveProjectId }, timeout: 15000 },
      );
      const backendQuestions = Array.isArray(data?.questions) ? data.questions : [];
      if (backendQuestions.length > 0) {
        setBackendSuggestedQuestions(backendQuestions);
        setSuggestedQuestionChunks([]);
        setSuggestedQuestionState('idle');
        return;
      }
    } catch {
      // Backend unavailable — fall back to local generation below.
    }
    setBackendSuggestedQuestions(null);
    try {
      const response = await getWritingBackendService().listMaterialChunks(
        effectiveProjectId,
        pinnedMaterialId,
      );
      setSuggestedQuestionChunks(response.chunks.slice(0, 20));
      setSuggestedQuestionState('idle');
    } catch {
      setSuggestedQuestionChunks([]);
      setSuggestedQuestionState('error');
    }
  }, [effectiveProjectId, pinnedMaterialId]);

  useEffect(() => {
    let cancelled = false;
    setReaderFormulaCandidates([]);
    if (!effectiveProjectId || !pinnedMaterialId) return undefined;
    const service = getWritingBackendService();
    void service.listFormulaCandidates(effectiveProjectId, pinnedMaterialId, DIALOG_PDF_FORMULA_CANDIDATE_MAX_COUNT)
      .then((response) => {
        if (!cancelled) {
          setReaderFormulaCandidates(buildDialogFormulaCandidatesFromResources(response.candidates));
        }
      })
      .catch(async () => {
        try {
          const response = await service.listMaterialChunks(effectiveProjectId, pinnedMaterialId);
          if (!cancelled) {
            setReaderFormulaCandidates(buildDialogFormulaCandidates(response.chunks, pinnedMaterialId));
          }
        } catch {
          if (!cancelled) setReaderFormulaCandidates([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [effectiveProjectId, pinnedMaterialId]);

  useEffect(() => {
    if (queryProjectId && queryProjectId !== activeProjectId) {
      setActiveProjectId(queryProjectId);
    }
  }, [activeProjectId, queryProjectId, setActiveProjectId]);

  useEffect(() => {
    conversationMessagesRef.current = conversationMessages;
  }, [conversationMessages]);

  useEffect(() => {
    if (!isResponseActive || requestStartedAt === null) {
      setRequestElapsedSec(0);
      return undefined;
    }
    const update = () => {
      setRequestElapsedSec(Math.max(0, Math.floor((Date.now() - requestStartedAt) / 1000)));
    };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [isResponseActive, requestStartedAt]);

  useEffect(() => {
    const activeStartedAt = dialogRequestStartedAtByScope.get(smartReadScope) ?? null;
    if (dialogAbortControllers.has(smartReadScope)) {
      setChatState('responding');
      setRequestStartedAt(activeStartedAt ?? Date.now());
      return;
    }
    if (hasStreamingAssistant) {
      setChatState('responding');
      setRequestStartedAt(activeStartedAt);
      return;
    }
    setChatState((current) => (current === 'responding' ? 'ready' : current));
    setRequestStartedAt(null);
  }, [hasStreamingAssistant, smartReadScope]);

  useEffect(() => {
    setProjectBiasEnabled(defaultProjectBiasEnabled);
  }, [defaultProjectBiasEnabled, activeProjectId]);

  useEffect(() => {
    writeDialogPaneWidths(paneWidths);
  }, [paneWidths]);

  useEffect(() => {
    writeDialogBoolean(DIALOG_HISTORY_COLLAPSED_STORAGE_KEY, historyRailCollapsed);
  }, [historyRailCollapsed]);

  useEffect(() => {
    writeDialogBoolean(DIALOG_CONTEXT_OPEN_STORAGE_KEY, contextRailOpen);
  }, [contextRailOpen]);

  useEffect(() => {
    writeDialogContextRailTab(contextRailTab);
  }, [contextRailTab]);

  useEffect(() => {
    writeDialogCenterTab(centerTab);
  }, [centerTab]);

  useEffect(() => {
    const migrated = normalizeDialogCenterTab(searchParams.get('tab'));
    if (readerTabAvailable) {
      if (migrated === 'chat' || migrated === 'discussion') {
        setContextRailTab(migrated);
      }
      if (centerTab !== 'reader') {
        setCenterTab('reader');
      }
      return;
    }
    if (migrated && migrated !== centerTab) {
      setCenterTab(migrated);
      return;
    }
    if (!migrated && searchParams.get('mode') === 'discussion' && centerTab === 'chat') {
      setCenterTab('discussion');
    }
  }, []);

  useEffect(() => {
    if (centerTab === 'reader' && !readerTabAvailable) {
      setCenterTab('chat');
    }
  }, [centerTab, readerTabAvailable]);

  useEffect(() => {
    if (!pinnedMaterialId || !pinnedLooksLikePdf) return;
    if (urlCenterTab === 'chat' || urlCenterTab === 'discussion') {
      setContextRailTab(urlCenterTab);
    }
    setCenterTab('reader');
  }, [pinnedLooksLikePdf, pinnedMaterialId, urlCenterTab]);

  useEffect(() => {
    if (previousPinnedMaterialIdRef.current === pinnedMaterialId) return;
    if (pinnedMaterialId) {
      setContextRailTab(
        pinnedLooksLikePdf
          ? urlCenterTab === 'discussion' ? 'discussion' : 'chat'
          : 'paper',
      );
      setEmbeddedReaderTarget({ nonce: 0 });
      setEmbeddedReaderPage(null);
    }
    previousPinnedMaterialIdRef.current = pinnedMaterialId;
  }, [pinnedLooksLikePdf, pinnedMaterialId, urlCenterTab]);

  useEffect(() => {
    const previousKey = previousUrlReaderTargetKeyRef.current;
    previousUrlReaderTargetKeyRef.current = urlReaderTargetKey;
    if (previousKey === null || previousKey === urlReaderTargetKey) return;
    setEmbeddedReaderPage(null);
  }, [urlReaderTargetKey]);

  useEffect(() => {
    if (!pinnedMaterialId || !pinnedLooksLikePdf) return;
    openPdfTab(
      {
        materialId: pinnedMaterialId,
        title: activeMaterialLabel || pinnedMaterialTitle || pinnedMaterialId,
      },
      { activate: true },
    );
  }, [activeMaterialLabel, openPdfTab, pinnedLooksLikePdf, pinnedMaterialId, pinnedMaterialTitle]);

  useEffect(() => {
    setContextRailTab((current) => {
      if (current === 'chat' && !readerTabAvailable) {
        return pinnedMaterialId ? 'paper' : 'graph';
      }
      if (current === 'discussion' && !readerTabAvailable) {
        return pinnedMaterialId ? 'paper' : 'graph';
      }
      if (
        current === 'project' ||
        current === 'graph' ||
        current === 'notes' ||
        current === 'paper' ||
        current === 'chat' ||
        current === 'discussion'
      ) {
        return current;
      }
      return readerTabAvailable ? 'chat' : pinnedMaterialId ? 'paper' : 'graph';
    });
  }, [pinnedMaterialId, readerTabAvailable]);

  useEffect(() => {
    if (!contextRailOpen) return;
    if (contextRailTab !== 'paper' && contextRailTab !== 'project') return;
    void refreshProjectMaterials({ surfaceError: false });
  }, [contextRailOpen, contextRailTab, refreshProjectMaterials]);

  useEffect(() => {
    if (!contextRailOpen || (contextRailTab !== 'notes' && contextRailTab !== 'paper')) return;
    void refreshAnnotationNotes({ surfaceError: false });
  }, [contextRailOpen, contextRailTab, refreshAnnotationNotes]);

  useEffect(() => {
    if (conversationMessages.length > 0) return;
    void refreshSuggestedQuestionChunks();
  }, [conversationMessages.length, refreshSuggestedQuestionChunks]);

  useEffect(() => {
    let cancelled = false;
    getWritingBackendService().listProjects()
      .then((projects: WritingProject[]) => {
        if (cancelled) return;
        const nextNames: Record<string, string> = {};
        for (const project of projects) {
          const projectId = normalizeProjectId(project.project_id);
          const title = String(project.title || '').trim();
          if (projectId) {
            nextNames[projectId] = title || '未命名项目';
          }
        }
        setProjectNames(nextNames);
      })
      .catch(() => {
        if (!cancelled) setProjectNames({});
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    try {
      if (inputValue) localStorage.setItem(inputStorageKey, inputValue);
      else localStorage.removeItem(inputStorageKey);
    } catch { /* storage quota */ }
  }, [inputValue, inputStorageKey]);

  useEffect(() => {
    try {
      setInputValue(readFirstStorageValue([
        inputStorageKey,
        ...legacyScopedKeys(projectStorageScope, 'input'),
      ]) ?? '');
    } catch { setInputValue(''); }
  }, [inputStorageKey, projectStorageScope]);

  useEffect(() => {
    try {
      if (sessionId) localStorage.setItem(sessionStorageKey, sessionId);
      else localStorage.removeItem(sessionStorageKey);
    } catch { /* storage quota */ }
  }, [sessionId, sessionStorageKey]);

  // When project storage keys change, rehydrate the backend session id. Chat
  // transcript persistence is centralized in SmartReadContext.
  useEffect(() => {
    try {
      setSessionId(readFirstStorageValue([
        sessionStorageKey,
        ...legacyScopedKeys(projectStorageScope, 'session'),
      ]) ?? conversation.sessionId ?? undefined);
    } catch { setSessionId(undefined); }

  }, [conversation.sessionId, projectStorageScope, sessionStorageKey]);

  useEffect(() => {
    void refreshSessions(historyMode, { surfaceError: false });
  }, [historyMode]);

  // 监听 localStorage 变化，自动刷新会话列表
  useEffect(() => {
    const handleStorageChange = (event: StorageEvent) => {
      if (event.key === 'smart-read-conversations-v1') {
        void refreshSessions(historyMode, { surfaceError: false });
      }
    };
    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, [historyMode]);

  const refreshSessions = async (
    mode: HistoryMode = historyMode,
    options: { surfaceError?: boolean } = {},
  ) => {
    setHistoryState('loading');
    setHistoryErrorMessage(null);
    try {
      const next = await listChatSessions(15000, { archivedOnly: mode === 'archived' });
      setSessions(next);
      setHistoryState('idle');
    } catch (error) {
      setHistoryState('error');
      if (options.surfaceError !== false) {
        setHistoryErrorMessage(getChatErrorMessage(error));
      }
    }
  };

  function focusDialogChatPane(): void {
    if (readerTabAvailable) {
      setContextRailOpen(true);
      setContextRailTab('chat');
      setCenterTab('reader');
      return;
    }
    setCenterTab('chat');
  }
  function focusRestoredSessionPane(nextRailTab: 'chat' | 'discussion'): void {
    if (readerTabAvailable) {
      setContextRailOpen(true);
      setContextRailTab(nextRailTab);
      setCenterTab('reader');
      return;
    }
    setCenterTab(nextRailTab);
  }

  const handleNewSession = () => {
    conversationMessagesRef.current = [];
    clearConversation(smartReadScope);
    clearCurrentPdfSelectionsAndAttachments();
    setDiscussionLaunchState(null);
    clearDiscussionLaunchState();
    setSessionId(undefined);
    setErrorMessage(null);
    setIsUnavailable(false);
    setChatState('ready');
    setRequestStartedAt(null);
    setHistoryErrorMessage(null);
    focusDialogChatPane();
  };

  const handleOpenHistory = async () => {
    setHistoryRailOpen(true);
    await refreshSessions();
  };

  const handleSearchHistory = async () => {
    const query = historyQuery.trim();
    if (!query) {
      setHistoryResults([]);
      setHistorySearchState('idle');
      return;
    }
    setHistorySearchState('loading');
    setHistoryErrorMessage(null);
    try {
      const results = await searchChatHistory(query, 30);
      setHistoryResults(results);
      setHistorySearchState('idle');
    } catch (error) {
      setHistorySearchState('error');
      setHistoryErrorMessage(getChatErrorMessage(error));
    }
  };

  const handleCreateAgentHandoff = useCallback(async (): Promise<void> => {
    const targetSessionId = normalizeChatHistorySessionId(sessionId ?? conversation.sessionId ?? '');
    if (!targetSessionId) {
      setAgentHandoffState('error');
      setAgentHandoffMessage('当前会话还没有可接手记录。');
      setAgentHandoffRequest(null);
      return;
    }
    if (!effectiveProjectId) {
      setAgentHandoffState('error');
      setAgentHandoffMessage('请先选择项目。');
      setAgentHandoffRequest(null);
      return;
    }
    setAgentHandoffState('creating');
    setAgentHandoffMessage(null);
    setAgentHandoffRequest(null);
    try {
      const receipt = await readAgentSidebarReceipt(targetSessionId);
      const request = await createAgentSidebarAnswerRequest(receipt, {
        projectId: effectiveProjectId,
        agentHost: 'agent',
        source: 'desktop',
        route: '/dialog',
        generatedIn: 'desktop_dialog',
      });
      setAgentHandoffRequest(request);
      setAgentHandoffState('created');
      setAgentHandoffMessage('已创建智能体接手任务。');
    } catch (error) {
      setAgentHandoffState('error');
      setAgentHandoffMessage(getChatErrorMessage(error));
      setAgentHandoffRequest(null);
    }
  }, [conversation.sessionId, effectiveProjectId, sessionId]);

  const handleResumeSession = async (nextSessionId: string, sessionHint?: ChatSessionSummary) => {
    const normalizedSessionId = nextSessionId.trim();
    if (!normalizedSessionId || chatState === 'responding' || restoringSessionIdRef.current) return;
    restoringSessionIdRef.current = normalizedSessionId;
    setHistoryState('loading');
    setHistoryErrorMessage(null);
    try {
      const response = await resumeChatSession({ session_id: normalizedSessionId, limit: 100 });
      const targetProjectId = normalizeProjectId(response.project_id ?? sessionHint?.project_id);
      const targetProjectForScope = targetProjectId || effectiveProjectId;
      const restoredMessages = await restoreDialogRelatedFigures(
        response.messages.map(toChatMessage).map(mapDialogMessageToChatData),
        targetProjectForScope,
      );
      const targetScope = smartReadDialogScope(targetProjectForScope || 'default');
      const targetRailTab = sessionHint && isDiscussionSession(sessionHint) ? 'discussion' : 'chat';
      writeDialogContextSearchParams('project', targetProjectForScope, targetRailTab);
      if (targetProjectId && targetProjectId !== activeProjectId) {
        setActiveProjectId(targetProjectId);
      }
      setSessionId(response.session_id);
      conversationMessagesRef.current = restoredMessages;
      setConversation(targetScope, restoredMessages, { sessionId: response.session_id });
      setIsUnavailable(false);
      setChatState('ready');
      focusRestoredSessionPane(targetRailTab);
      setHistoryRailOpen(false);
      setHistoryState('idle');
    } catch (error) {
      setHistoryState('error');
      setHistoryErrorMessage(getChatErrorMessage(error));
    } finally {
      restoringSessionIdRef.current = null;
    }
  };

  useEffect(() => {
    if (!queryConversationId) return;
    if (urlConversationRestoreRef.current === queryConversationId) return;
    if (restoringSessionIdRef.current === queryConversationId) return;
    const currentSessionId = normalizeChatHistorySessionId(sessionId ?? conversation.sessionId ?? '');
    if (currentSessionId === queryConversationId && conversationMessages.length > 0) {
      urlConversationRestoreRef.current = queryConversationId;
      return;
    }
    urlConversationRestoreRef.current = queryConversationId;
    void handleResumeSession(queryConversationId);
  }, [conversation.sessionId, conversationMessages.length, queryConversationId, sessionId]);

  const handleDeleteSession = async (target: ChatSessionSummary) => {
    const normalizedSessionId = target.session_id.trim();
    if (!normalizedSessionId || chatState === 'responding') return;
    const label = sanitizeChatVisibleText(target.title || target.preview, '当前会话', { maxLength: 80 });
    if (!window.confirm(`确认删除会话「${label}」？此操作只删除本机会话记录。`)) {
      return;
    }
    setHistoryState('loading');
    setHistoryErrorMessage(null);
    try {
      await deleteChatSession(normalizedSessionId);
      setSessions((prev) => prev.filter((item) => item.session_id !== normalizedSessionId));
      if (sessionId === normalizedSessionId) {
        handleNewSession();
      }
      setHistoryState('idle');
    } catch (error) {
      setHistoryState('error');
      setHistoryErrorMessage(getChatErrorMessage(error));
    }
  };

  const handleClearSessionGroup = async (group: SessionProjectGroup) => {
    if (chatState === 'responding') return;
    const ids = group.branchGroups
      .flatMap((branchGroup) => [branchGroup.root, ...branchGroup.forks])
      .map((item) => item.session_id.trim())
      .filter(Boolean);
    if (ids.length === 0) return;
    if (!window.confirm(`确认清空「${group.label}」分组下的 ${ids.length} 个会话？此操作只删除本机会话记录，不可恢复。`)) {
      return;
    }
    setHistoryState('loading');
    setHistoryErrorMessage(null);
    try {
      const result = await bulkDeleteChatSessions(ids);
      const deletedSet = new Set(result.deleted);
      setSessions((prev) => prev.filter((item) => !deletedSet.has(item.session_id)));
      if (sessionId && deletedSet.has(sessionId)) {
        handleNewSession();
      }
      setHistoryState('idle');
    } catch (error) {
      setHistoryState('error');
      setHistoryErrorMessage(getChatErrorMessage(error));
    }
  };

  const handleArchiveSession = async (target: ChatSessionSummary) => {
    const normalizedSessionId = target.session_id.trim();
    if (!normalizedSessionId || chatState === 'responding') return;
    setHistoryState('loading');
    setHistoryErrorMessage(null);
    try {
      await archiveChatSession(normalizedSessionId);
      setSessions((prev) => prev.filter((item) => item.session_id !== normalizedSessionId));
      setHistoryState('idle');
    } catch (error) {
      setHistoryState('error');
      setHistoryErrorMessage(getChatErrorMessage(error));
    }
  };

  const handleRestoreSession = async (target: ChatSessionSummary) => {
    const normalizedSessionId = target.session_id.trim();
    if (!normalizedSessionId || chatState === 'responding') return;
    setHistoryState('loading');
    setHistoryErrorMessage(null);
    try {
      await restoreChatSession(normalizedSessionId);
      setSessions((prev) => prev.filter((item) => item.session_id !== normalizedSessionId));
      setHistoryState('idle');
    } catch (error) {
      setHistoryState('error');
      setHistoryErrorMessage(getChatErrorMessage(error));
    }
  };

  const handleForkFromResult = async (result: ChatHistorySearchResult) => {
    if (chatState === 'responding') return;
    setHistoryState('loading');
    setHistoryErrorMessage(null);
    try {
      const forked = await forkChatHistoryConversation(result.conversation_id, result.node_id);
      const response = await resumeChatSession({ session_id: forked.fork_session_id, limit: 100 });
      const restoredMessages = response.messages.map(toChatMessage).map(mapDialogMessageToChatData);
      const targetProjectId = normalizeProjectId(response.project_id);
      const targetProjectForScope = targetProjectId || effectiveProjectId;
      const targetScope = smartReadDialogScope(targetProjectForScope || 'default');
      writeDialogContextSearchParams('project', targetProjectForScope, 'chat');
      if (targetProjectId && targetProjectId !== activeProjectId) {
        setActiveProjectId(targetProjectId);
      }
      setSessionId(forked.fork_session_id);
      conversationMessagesRef.current = restoredMessages;
      setConversation(targetScope, restoredMessages, { sessionId: forked.fork_session_id });
      setInputValue('从这个分叉继续：');
      focusComposerAfterDraftWrite('end');
      setIsUnavailable(false);
      setChatState('ready');
      focusRestoredSessionPane('chat');
      setHistoryRailOpen(false);
      setHistoryState('idle');
    } catch (error) {
      setHistoryState('error');
      setHistoryErrorMessage(getChatErrorMessage(error));
    }
  };

  const handleStopGeneration = () => {
    const activeController = activeAbortControllerRef.current ?? dialogAbortControllers.get(smartReadScope);
    if (activeController) {
      activeController.abort();
      return;
    }
    const stoppedMessages = markLatestStreamingAssistantStopped(conversationMessagesRef.current);
    if (stoppedMessages !== conversationMessagesRef.current) {
      conversationMessagesRef.current = stoppedMessages;
      setConversation(smartReadScope, stoppedMessages);
    }
    setChatState('ready');
    setRequestStartedAt(null);
  };

  const handleOpenTaskCenter = () => {
    if (taskCenterNavigationPendingRef.current || location.pathname === '/jobs') return;
    taskCenterNavigationPendingRef.current = true;
    navigate('/jobs');
    window.setTimeout(() => {
      taskCenterNavigationPendingRef.current = false;
    }, 750);
  };

  const handleEditMessage = (message: ChatMessageData) => {
    if (chatState === 'responding' || message.role !== 'user') return;
    const index = conversationMessagesRef.current.findIndex((item) => item.id === message.id);
    if (index < 0) return;
    const nextMessages = conversationMessagesRef.current.slice(0, index);
    const restoredSelections = dialogPdfSelectionsFromResearchSelections(
      message.researchSelections,
      message.turnId,
    );
    pendingResearchSelectionRestoreRef.current = restoredSelections.length > 0
      ? restoredSelections
      : null;
    conversationMessagesRef.current = nextMessages;
    setConversation(smartReadScope, nextMessages, { sessionId: null });
    setInputValue(message.content);
    focusComposerAfterDraftWrite('all');
    setSessionId(undefined);
    setErrorMessage(null);
    setIsUnavailable(false);
    setChatState('ready');
    const primarySelection = restoredSelections[0];
    if (primarySelection) {
      if (
        currentRequestContextRef.current.materialId === primarySelection.materialId
        && currentRequestContextRef.current.sessionId === null
      ) {
        pendingResearchSelectionRestoreRef.current = null;
        clearCurrentPdfSelectionsAndAttachments();
        setCurrentPdfSelections(restoredSelections);
      }
      const material = projectMaterials.find(
        (item) => normalizeMaterialId(item.material_id) === primarySelection.materialId,
      );
      focusMaterialReaderPane(
        primarySelection.materialId,
        material ? materialTitleLabel(material) : primarySelection.materialId,
      );
      writeReaderSearchParams(primarySelection.materialId, {
        title: material ? materialTitleLabel(material) : primarySelection.materialId,
        page: primarySelection.selection.page,
        chunkId: primarySelection.selection.chunk_id,
        bbox: primarySelection.selection.bbox
          ? [...primarySelection.selection.bbox]
          : undefined,
        bboxUnit: primarySelection.selection.bbox_unit,
      });
    } else {
      clearCurrentPdfSelectionsAndAttachments();
    }
  };

  const handleForkMessage = (message: ChatMessageData) => {
    if (chatState === 'responding') return;
    const index = conversationMessagesRef.current.findIndex((item) => item.id === message.id);
    if (index < 0) return;
    const nextMessages = conversationMessagesRef.current.slice(0, index + 1);
    conversationMessagesRef.current = nextMessages;
    setConversation(smartReadScope, nextMessages, { sessionId: null });
    setSessionId(undefined);
    setErrorMessage(null);
    setIsUnavailable(false);
    setChatState('ready');
  };

  const handleSendMessage = async (payload: ChatInputSubmitPayload) => {
    const query = payload.text.trim();
    if (!query || chatState === 'responding' || pendingAttachmentReads > 0) return;
    const images: ChatAttachment[] = payload.attachmentsEnabled ? payload.attachments : [];
    const requestScope = smartReadScope;
    const requestContextRevisionAtStart = currentRequestContextRef.current.revision;
    const requestContextIsCurrent = (): boolean => (
      currentRequestContextRef.current.revision === requestContextRevisionAtStart
    );
    const selectedTier = loadSmartReadCostTier('medium');
    const selectionCandidates = currentPdfSelectionsRef.current.filter(
      (selectionState) => selectionState.materialId === requestMaterialId,
    );
    const missingVisualSelection = selectionCandidates.find(
      (selectionState) => !selectionHasReplaySource(selectionState, images),
    );
    if (missingVisualSelection) {
      setErrorMessage('恢复的图表、公式或区域选区需要在 PDF 中重新选择后才能再次提交。');
      setChatState('error');
      focusComposerAfterDraftWrite('end');
      return;
    }
    const selectionsForRequest = selectionCandidates;
    const turnId = createDialogTurnId();
    const researchSelections = buildResearchSelections({
      turnId,
      groupId: `${turnId}-group`,
      selections: selectionsForRequest.map((selectionState) => ({
        selectionId: selectionState.id,
        materialId: selectionState.materialId,
        selection: selectionState.selection,
      })),
    });
    if (researchSelections.length !== selectionsForRequest.length) {
      setErrorMessage('当前 PDF 选区不完整，请重新选择后再提交。');
      setChatState('error');
      focusComposerAfterDraftWrite('end');
      return;
    }

    const userMessage: ChatMessageData = {
      id: `user-${turnId}`,
      role: 'user',
      turnId,
      content: query,
      timestamp: new Date().toISOString(),
      ...(researchSelections.length > 0 ? { researchSelections } : {}),
    };
    const assistantId = `assistant-${Date.now()}`;
    const assistantMessage: ChatMessageData = {
      id: assistantId,
      role: 'assistant',
      turnId,
      content: '',
      timestamp: new Date().toISOString(),
      status: 'streaming',
      metadata: {
        diagnostics: {
          tier: backendTierForCostTier(selectedTier),
        },
      },
    };

    let requestMessages = [
      ...conversationMessagesRef.current,
      userMessage,
      assistantMessage,
    ];
    const commitMessages = (nextMessages: ChatMessageData[]) => {
      requestMessages = nextMessages;
      if (requestContextIsCurrent()) {
        conversationMessagesRef.current = nextMessages;
      }
      setConversation(requestScope, nextMessages);
    };
    const updateAssistantMessage = (patch: Partial<ChatMessageData>): ChatMessageData => {
      const existing = requestMessages.find((message) => message.id === assistantId) ?? assistantMessage;
      const nextMessage: ChatMessageData = {
        ...existing,
        ...patch,
        metadata: patch.metadata ?? existing.metadata,
      };
      commitMessages(
        replaceOrAppendChatData(requestMessages, nextMessage),
      );
      return nextMessage;
    };

    commitMessages(requestMessages);
    setInputValue('');
    setChatState('responding');
    focusDialogChatPane();
    const startedAt = Date.now();
    dialogRequestStartedAtByScope.set(requestScope, startedAt);
    setRequestStartedAt(startedAt);
    setErrorMessage(null);
    setIsUnavailable(false);

    const abortController = new AbortController();
    activeAbortControllerRef.current = abortController;
    dialogAbortControllers.set(requestScope, abortController);
    const restoreRequestDraft = (): void => {
      const contextIsCurrent = requestContextIsCurrent();
      if (contextIsCurrent) {
        setInputValue(query);
      }
      const selectionFingerprints = selectionAttachmentFingerprints(selectionsForRequest);
      if (images.length === 0 && contextIsCurrent) {
        setCurrentPdfSelections((current) => mergeDialogPdfSelections(current, selectionsForRequest));
        return;
      }
      if (images.length === 0) return;
      window.setTimeout(() => {
        const delayedContextIsCurrent = requestContextIsCurrent();
        const retryImages = delayedContextIsCurrent
          ? images
          : withoutAttachmentFingerprints(images, selectionFingerprints);
        const mergedImages = mergeDialogRetryAttachments(
          draftAttachmentsRef.current,
          retryImages,
          delayedContextIsCurrent ? selectionFingerprints : [],
        );
        setDraftAttachments(mergedImages);
        if (delayedContextIsCurrent) {
          const restorableSelections = selectionsForRequest.filter(
            (selectionState) => selectionHasReplaySource(selectionState, mergedImages),
          );
          setCurrentPdfSelections((current) => mergeDialogPdfSelections(current, restorableSelections));
        }
      }, 0);
    };
    try {
      const existingSessionId = sessionId ?? conversation.sessionId ?? undefined;
      if (selectionCandidates.length > 0) {
        const candidateIds = new Set(selectionCandidates.map((selectionState) => selectionState.id));
        setCurrentPdfSelections((current) => current.filter(
          (selectionState) => !candidateIds.has(selectionState.id),
        ));
      }
      const requestSelections = selectionsForRequest.map((selectionState) => {
        const imageIndex = findSelectionImageIndex(selectionState, images);
        return {
          ...selectionState.selection,
          ...(selectionState.selection.kind !== 'text' && imageIndex !== null
            ? { image_index: imageIndex }
            : {}),
        };
      });
      const primarySelection = requestSelections[0];
      const currentPdfContext = buildDialogCurrentPdfContext({
        materialId: requestMaterialId,
        page: primarySelection?.page ?? effectiveReaderPage,
        chunkId: effectiveReaderChunkId,
        selectedText: primarySelection?.text,
        bbox: primarySelection?.bbox ?? effectiveReaderBbox ?? null,
        bboxUnit: primarySelection?.bbox_unit ?? effectiveReaderBboxUnit ?? null,
        selections: requestSelections,
      });
      let metadata: DialogStreamMetadata | null = null;
      let usage: DialogStreamUsage | null = null;
      let analysisChain: ChatMessageData['analysis_chain'] = null;
      let streamedContent = '';
      let nextSessionId = existingSessionId;
      let doneTokens: TokenUsage | undefined;
      let finalVisualEvidenceRefs: EvidenceRefLike[] | null = null;
      let finalVisualObservationRefs: VisualObservationReference[] = [];
      const fallbackTier = backendTierForCostTier(selectedTier);
      const requestAnswerOrigin: AnswerOrigin = 'internal_smartread';

      await streamIntelligentChatMessage(
        {
          query,
          turn_id: turnId,
          session_id: existingSessionId,
          project_id: requestProjectId,
          material_id: requestMaterialId,
          tier: fallbackTier,
          mode: UNIFIED_DIALOG_MODE,
          answer_origin: requestAnswerOrigin,
          current_pdf_context: currentPdfContext,
          research_selections: researchSelections.length > 0 ? researchSelections : undefined,
          images: images.length > 0 ? images : undefined,
          project_reasoning_bias_enabled: defaultProjectBiasEnabled ? projectBiasEnabled : undefined,
        },
        {
          signal: abortController.signal,
          onEvent: (event) => {
            if (!isMountedRef.current) return;
            if (event.event === 'metadata') {
              metadata = event;
              nextSessionId = event.session_id || nextSessionId;
              const nextDiagnostics = buildSmartReadDiagnosticsFromStream({
                metadata,
                usage,
                doneTokens,
                fallbackTier,
                content: streamedContent,
              });
              updateAssistantMessage({
                content: dialogVisibleAnswerContent(streamedContent, requestAnswerOrigin),
                status: 'streaming',
                evidence: coerceEvidenceRefs(event.evidence_refs),
                metadata: nextDiagnostics ? { diagnostics: nextDiagnostics } : undefined,
              });
              return;
            }
            if (event.event === 'usage') {
              usage = event;
              const nextDiagnostics = buildSmartReadDiagnosticsFromStream({
                metadata,
                usage,
                doneTokens,
                fallbackTier,
                content: streamedContent,
              });
              updateAssistantMessage({
                metadata: nextDiagnostics ? { diagnostics: nextDiagnostics } : undefined,
              });
              return;
            }
            if (event.event === 'analysis_chain_done') {
              analysisChain = event.analysis_chain;
              nextSessionId = event.session_id || nextSessionId;
              updateAssistantMessage({ analysis_chain: analysisChain });
              return;
            }
            if (event.event === 'text_delta') {
              streamedContent += event.delta;
              updateAssistantMessage({
                content: dialogVisibleAnswerContent(streamedContent, requestAnswerOrigin),
                status: 'streaming',
              });
              return;
            }
            if (event.event === 'done') {
              nextSessionId = event.session_id || nextSessionId;
              doneTokens = event.tokens_used;
              streamedContent = event.response ?? streamedContent;
              if (event.visual_evidence_refs !== undefined) {
                finalVisualEvidenceRefs = coerceEvidenceRefs(event.visual_evidence_refs) ?? [];
              }
              if (event.visual_observation_refs !== undefined) {
                finalVisualObservationRefs = sanitizeVisualObservationReferences(
                  event.visual_observation_refs,
                ).filter((reference) => reference.turn_id === turnId);
                updateAssistantMessage({ visualObservationRefs: finalVisualObservationRefs });
              }
              return;
            }
            if (event.event === 'error') {
              throw new Error(event.error);
            }
          },
        },
      );
      const finalContent = dialogVisibleAnswerContent(streamedContent, requestAnswerOrigin)
        || '回答已生成，但未找到可显示的结果。';
      const finalDiagnostics = buildSmartReadDiagnosticsFromStream({
        metadata,
        usage,
        doneTokens,
        fallbackTier,
        content: finalContent,
      });
      const finalEvidence = evidenceRefsFromDialogStreamMetadata(metadata);
      const metadataVisualEvidence = visualEvidenceRefsFromDialogStreamMetadata(metadata);
      const finalVisualEvidence = finalVisualEvidenceRefs ?? metadataVisualEvidence;
      const receivedVisualEvidenceRefs = finalVisualEvidenceRefs !== null
        || metadataVisualEvidence !== undefined;
      let relatedFigures: ChatRelatedFigure[] | undefined;
      const evidenceFigures = relatedFiguresFromEvidenceRefs(finalVisualEvidence ?? finalEvidence);
      if (evidenceFigures.length > 0) {
        relatedFigures = evidenceFigures;
      }
      if (requestProjectId && !receivedVisualEvidenceRefs && !relatedFigures && shouldLoadRelatedFigures(query)) {
        try {
          const candidates = await getWritingBackendService().listFigureTableCandidates(
            requestProjectId,
            200,
            { pixelOnly: true, renderPdfFallback: false },
          );
          const figures = toDialogRelatedFigures(candidates, query, requestMaterialId);
          relatedFigures = figures.length > 0 ? figures : undefined;
        } catch {
          relatedFigures = relatedFigures && relatedFigures.length > 0 ? relatedFigures : undefined;
        }
      }
      const finalAssistant = updateAssistantMessage({
        content: finalContent,
        status: 'done',
        metadata: finalDiagnostics ? { diagnostics: finalDiagnostics } : undefined,
        evidence: finalEvidence,
        ...(analysisChain ? { analysis_chain: analysisChain } : {}),
        ...(relatedFigures ? { relatedFigures } : {}),
        ...(finalVisualObservationRefs.length > 0
          ? { visualObservationRefs: finalVisualObservationRefs }
          : {}),
      });

      if (
        isMountedRef.current
        && requestContextIsCurrent()
        && nextSessionId
        && nextSessionId !== sessionId
      ) {
        setSessionId(nextSessionId);
      }
      setConversation(
        requestScope,
        replaceOrAppendChatData(requestMessages, finalAssistant),
        { sessionId: nextSessionId },
      );
      if (isMountedRef.current && requestContextIsCurrent()) {
        setIsUnavailable(false);
        setChatState('ready');
      }
    } catch (error) {
      if (isAbortError(error)) {
        if (!isMountedRef.current) {
          return;
        }
        updateAssistantMessage({
          content: '已停止生成。',
          status: 'done',
        });
        restoreRequestDraft();
        if (requestContextIsCurrent()) {
          setChatState('ready');
        }
        return;
      }
      const errorMsg = getChatErrorMessage(error);
      const contextIsCurrent = requestContextIsCurrent();
      restoreRequestDraft();
      updateAssistantMessage({
        content: `回答失败：${errorMsg}`,
        status: 'error',
      });
      if (isMountedRef.current && contextIsCurrent) {
        if (isUnavailableError(error)) {
          setIsUnavailable(true);
          setChatState('unavailable');
        } else {
          setErrorMessage(errorMsg);
          setChatState('error');
        }
      }
    } finally {
      if (dialogAbortControllers.get(requestScope) === abortController) {
        dialogAbortControllers.delete(requestScope);
      }
      dialogRequestStartedAtByScope.delete(requestScope);
      if (activeAbortControllerRef.current === abortController) {
        activeAbortControllerRef.current = null;
      }
      if (isMountedRef.current && requestContextIsCurrent()) {
        setRequestStartedAt(null);
      }
    }
  };

  const handleUseSuggestedQuestion = (question: SuggestedQuestion) => {
    if (chatState === 'responding') return;
    focusDialogChatPane();
    setInputValue(question.question);
    focusComposerAfterDraftWrite('end');
  };

  const launchDiscussionEnhancement = (intent: DiscussionEnhancementIntent, seedQuestion = inputValue): void => {
    if (chatState === 'responding') return;
    const effectiveSeed = seedQuestion.trim() || (suggestedQuestions[0]?.question ?? '');
    const launchState: DiscussionLaunchState = {
      query: buildDiscussionEnhancementQuestion(intent, activeMaterialLabel, effectiveSeed),
      evidenceMode: effectiveProjectId ? 'from_project' : 'none',
    };
    setDiscussionLaunchState(launchState);
    writeDiscussionLaunchState(launchState);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.delete('mode');
    nextParams.set('tab', 'discussion');
    if (effectiveProjectId) nextParams.set('project_id', effectiveProjectId);
    if (pinnedMaterialId) nextParams.set('material_id', pinnedMaterialId);
    if (pinnedMaterialTitle) nextParams.set('material_title', pinnedMaterialTitle);
    nextParams.set('scope', dialogContextScope);
    setSearchParams(nextParams, { replace: false });
    if (readerTabAvailable) {
      setContextRailOpen(true);
      setContextRailTab('discussion');
      setCenterTab('reader');
      return;
    }
    setCenterTab('discussion');
  };

  const isInputDisabled = isResponseActive;
  const activeHandoffSessionId = normalizeChatHistorySessionId(sessionId ?? conversation.sessionId ?? '');
  const latestCompletedAnswerId = useMemo(() => {
    for (let index = conversationMessages.length - 1; index >= 0; index -= 1) {
      const message = conversationMessages[index];
      if (
        (message.role === 'assistant' || message.role === 'agent') &&
        message.status !== 'streaming' &&
        message.content.trim()
      ) {
        return message.id;
      }
    }
    return null;
  }, [conversationMessages]);
  const agentHandoffDisabled =
    isInputDisabled ||
    agentHandoffState === 'creating' ||
    !activeHandoffSessionId ||
    !effectiveProjectId;
  const agentHandoffMenuDisabled = isInputDisabled || agentHandoffState === 'creating';
  const agentHandoffActionTitle = !effectiveProjectId
    ? '请先选择项目'
    : !activeHandoffSessionId
      ? '当前回答保存后可创建接手任务'
      : '为当前回答创建接手任务';
  const agentHandoffMenuTitle = agentHandoffState === 'creating'
    ? '正在创建智能体接手任务'
    : agentHandoffState === 'created'
      ? '智能体接手任务已创建'
      : '把当前回答交给智能体继续';
  const agentHandoffButtonText = agentHandoffState === 'creating' ? '创建中…' : '接手当前回答';
  const renderAgentHandoffFooter = useCallback((message: ChatMessageData) => {
    if (message.id !== latestCompletedAnswerId || (message.role !== 'assistant' && message.role !== 'agent')) {
      return null;
    }
    return (
      <div className="flex flex-wrap items-center gap-2 border-t border-outline-variant/40 pt-2 text-[11px]">
        <ComposerControlMenu
          label="给智能体"
          title={agentHandoffMenuTitle}
          icon={Users2}
          disabled={agentHandoffMenuDisabled}
          align="left"
          width="compact"
        >
          {(close) => (
            <ComposerMenuItem
              role="menuitem"
              label={agentHandoffButtonText}
              description="生成同一条 SmartRead 记录的接手任务，智能体可继续处理并写回。"
              icon={Users2}
              disabled={agentHandoffDisabled}
              title={agentHandoffActionTitle}
              onSelect={() => {
                close();
                void handleCreateAgentHandoff();
              }}
            />
          )}
        </ComposerControlMenu>
        {agentHandoffRequest ? (
          <span className="sr-only">智能体接手任务已绑定当前 SmartRead 记录。</span>
        ) : null}
      </div>
    );
  }, [
    activeHandoffSessionId,
    agentHandoffButtonText,
    agentHandoffDisabled,
    agentHandoffMenuDisabled,
    agentHandoffMenuTitle,
    agentHandoffRequest,
    agentHandoffActionTitle,
    effectiveProjectId,
    handleCreateAgentHandoff,
    isInputDisabled,
    latestCompletedAnswerId,
  ]);
  useEffect(() => {
    if (isInputDisabled) return;
    const timer = window.setTimeout(() => {
      const active = document.activeElement;
      const shouldClaimInitialFocus =
        active === null ||
        active === document.body ||
        active === document.documentElement ||
        active?.id === 'root';
      if (shouldClaimInitialFocus) {
        chatInputRef.current?.focus();
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [dialogStorageScope, isInputDisabled]);

  const emptyHint = useMemo(() => {
    if (dialogContextScope === 'paper' && pinnedMaterialId) {
      return `当前对话优先围绕「${activeMaterialLabel}」检索和回答。`;
    }
    return UNIFIED_EMPTY_HINT;
  }, [activeMaterialLabel, dialogContextScope, pinnedMaterialId]);
  const suggestedQuestionStatusLabel = useMemo(() => {
    if (suggestedQuestionState === 'loading') return '正在根据文献内容生成试问…';
    if (backendSuggestedQuestions && backendSuggestedQuestions.length > 0) return '已根据文献全文生成';
    if (suggestedQuestionState === 'error') return '片段读取失败，先给出通用试问。';
    if (suggestedQuestionChunks.length > 0) return `已参考 ${suggestedQuestionChunks.length} 个文献片段`;
    if (pinnedMaterialId) return '已参考文献信息';
    return '';
  }, [backendSuggestedQuestions, pinnedMaterialId, suggestedQuestionChunks.length, suggestedQuestionState]);
  function writeDialogContextSearchParams(
    nextScope: DialogContextScope,
    nextProjectId: string = effectiveProjectId,
    nextRailTab?: 'chat' | 'discussion',
  ): void {
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('scope', nextScope);
    if (pinnedMaterialId) nextParams.set('material_id', pinnedMaterialId);
    else nextParams.delete('material_id');
    if (pinnedMaterialTitle) nextParams.set('material_title', pinnedMaterialTitle);
    else nextParams.delete('material_title');
    if (nextProjectId) nextParams.set('project_id', nextProjectId);
    else nextParams.delete('project_id');
    if (nextRailTab) nextParams.set('tab', nextRailTab);
    setSearchParams(nextParams, { replace: true });
  }
  function handleContextScopeChange(nextScope: DialogContextScope): void {
    if (nextScope === 'paper' && !pinnedMaterialId) return;
    writeDialogContextSearchParams(nextScope);
  }
  const handleOpenPinnedMaterial = () => {
    if (!pinnedMaterialId) return;
    writeReaderSearchParams(pinnedMaterialId, {
      title: pinnedMaterialTitle,
      page: effectiveReaderPage,
      replace: false,
    });
  };
  function writeReaderSearchParams(
    materialId: string,
    options: {
      title?: string;
      page?: number | null;
      chunkId?: string | null;
      bbox?: number[] | null;
      bboxUnit?: PdfBboxUnit | null;
      quote?: string | null;
      anchorKind?: 'text' | 'visual';
      replace?: boolean;
    } = {},
  ): void {
    const normalizedMaterialId = normalizeMaterialId(materialId);
    if (!normalizedMaterialId) return;
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('scope', 'paper');
    nextParams.set('tab', 'reader');
    nextParams.set('material_id', normalizedMaterialId);
    const title = normalizeMaterialId(options.title);
    if (title) nextParams.set('material_title', title);
    else nextParams.delete('material_title');
    const nextProjectId = effectiveProjectId || queryProjectId;
    if (nextProjectId) nextParams.set('project_id', nextProjectId);
    if (options.page && Number.isFinite(options.page) && options.page > 0) {
      nextParams.set('page', String(Math.round(options.page)));
    } else {
      nextParams.delete('page');
    }
    if (options.chunkId) nextParams.set('chunk', options.chunkId);
    else nextParams.delete('chunk');
    const bboxParam = encodePdfBboxParam(options.bbox ?? null, options.bboxUnit ?? null);
    if (bboxParam) nextParams.set('bbox', bboxParam);
    else nextParams.delete('bbox');
    const quote = options.anchorKind === 'visual'
      ? null
      : normalizePdfQuote(options.quote);
    if (quote) nextParams.set('quote', quote);
    else nextParams.delete('quote');
    if (options.anchorKind) nextParams.set('anchor_kind', options.anchorKind);
    else nextParams.delete('anchor_kind');
    setSearchParams(nextParams, { replace: options.replace ?? false });
  }
  function focusMaterialReaderPane(materialId: string, title?: string): string | null {
    const normalizedMaterialId = normalizeMaterialId(materialId);
    if (!normalizedMaterialId) return null;
    openPdfTab(
      { materialId: normalizedMaterialId, title: normalizeMaterialId(title) || normalizedMaterialId },
      { activate: true },
    );
    setCenterTab('reader');
    return normalizedMaterialId;
  }
  function invalidatePendingEvidenceActivation(): void {
    evidenceActivationSequenceRef.current += 1;
  }
  function handleFocusPinnedMaterialReader(): void {
    if (!pinnedMaterialId) return;
    if (!pinnedLooksLikePdf) {
      handleOpenPinnedMaterial();
      return;
    }
    const normalizedMaterialId = focusMaterialReaderPane(
      pinnedMaterialId,
      activeMaterialLabel || pinnedMaterialTitle,
    );
    if (!normalizedMaterialId) return;
    writeReaderSearchParams(normalizedMaterialId, {
      title: activeMaterialLabel || pinnedMaterialTitle || normalizedMaterialId,
      replace: true,
    });
  }
  function handlePdfTabActivate(materialId: string): void {
    const normalizedMaterialId = normalizeMaterialId(materialId);
    if (!normalizedMaterialId) return;
    invalidatePendingEvidenceActivation();
    const material = projectMaterials.find((item) => normalizeMaterialId(item.material_id) === normalizedMaterialId);
    setCenterTab('reader');
    writeReaderSearchParams(normalizedMaterialId, {
      title: material ? materialTitleLabel(material) : normalizedMaterialId,
      replace: true,
    });
  }
  function handlePdfTabsEmpty(): void {
    const nextParams = new URLSearchParams(searchParams);
    nextParams.delete('material_id');
    nextParams.delete('material');
    nextParams.delete('material_title');
    nextParams.delete('title');
    nextParams.delete('page');
    nextParams.delete('chunk');
    nextParams.delete('bbox');
    nextParams.delete('quote');
    nextParams.delete('anchor_kind');
    nextParams.delete('tab');
    nextParams.set('scope', 'project');
    setSearchParams(nextParams, { replace: true });
    setContextRailTab('project');
    setCenterTab('chat');
  }
  function handleOpenPinnedMaterialPage(page: number): void {
    if (!pinnedMaterialId) return;
    const normalizedPage = Number.isFinite(page) && page > 0 ? Math.round(page) : 1;
    focusMaterialReaderPane(pinnedMaterialId, activeMaterialLabel || pinnedMaterialTitle);
    writeReaderSearchParams(pinnedMaterialId, {
      title: activeMaterialLabel,
      page: normalizedPage,
      replace: false,
    });
  }

  function handleEmbeddedReaderPageChange(page: number): void {
    if (!Number.isFinite(page) || page <= 0) return;
    const normalizedPage = Math.round(page);
    if (normalizedPage === effectiveReaderPage) {
      if (pinnedMaterialId) {
        updatePdfView(pinnedMaterialId, { page: normalizedPage });
      }
      return;
    }
    invalidatePendingEvidenceActivation();
    setEmbeddedReaderPage(normalizedPage);
    if (pinnedMaterialId) {
      updatePdfView(pinnedMaterialId, { page: normalizedPage });
    }
  }

  function handleAnalyzeReaderText(text: string, page: number, anchor?: PdfSelectionAnchor): void {
    if (!pinnedMaterialId || isInputDisabled) return;
    const selectedText = normalizeDialogSelectionText(text);
    if (!selectedText) return;
    const normalizedPage = normalizeDialogReaderPage(page) ?? effectiveReaderPage ?? 1;
    const bbox = combineSelectionRects(anchor?.rects);
    const selectionState: DialogPdfSelectionState = {
      id: createDialogPdfSelectionId(),
      materialId: pinnedMaterialId,
      selection: {
        kind: 'text',
        page: normalizedPage,
        text: selectedText,
        label: '选中的文本',
        ...(bbox ? { bbox, bbox_unit: 'normalized_ratio' } : {}),
      },
    };
    const nextSelections = mergeDialogPdfSelections(
      currentPdfSelectionsRef.current,
      [selectionState],
    );
    if (nextSelections.length === currentPdfSelectionsRef.current.length) return;
    setCurrentPdfSelections(nextSelections);
    setEmbeddedReaderPage(normalizedPage);
    focusDialogChatPane();
    if (!inputValue.trim() || DIALOG_SELECTION_AUTO_PROMPTS.has(inputValue.trim())) {
      setInputValue(selectionPrompt('text', nextSelections.length));
    }
    focusComposerAfterDraftWrite('end');
  }

  function handleAnalyzeReaderRegion(capture: PdfRegionCapture): void {
    if (currentRequestContextRef.current.revision !== requestContextRevision) return;
    if (!pinnedMaterialId || isInputDisabled) return;
    const normalizedPage = normalizeDialogReaderPage(capture.page) ?? effectiveReaderPage ?? 1;
    const bbox = normalizePdfUrlBbox(capture.bbox, 'normalized_ratio');
    if (!bbox) return;
    const imageFingerprint = chatAttachmentFingerprint(capture.image);
    const selectionState: DialogPdfSelectionState = {
      id: createDialogPdfSelectionId(),
      materialId: pinnedMaterialId,
      imageFingerprint,
      selection: {
        kind: capture.kind,
        page: normalizedPage,
        bbox,
        bbox_unit: 'normalized_ratio',
        label: capture.label,
        ...(capture.text ? { text: capture.text } : {}),
        ...(capture.chunkId ? { chunk_id: capture.chunkId } : {}),
        ...(capture.candidateId ? { candidate_id: capture.candidateId } : {}),
      },
    };
    const nextSelections = mergeDialogPdfSelections(
      currentPdfSelectionsRef.current,
      [selectionState],
    );
    if (nextSelections.length === currentPdfSelectionsRef.current.length) return;
    if (!chatInputRef.current?.appendAttachments([capture.image])) return;
    setCurrentPdfSelections(nextSelections);
    setEmbeddedReaderPage(normalizedPage);
    focusDialogChatPane();
    if (!inputValue.trim() || DIALOG_SELECTION_AUTO_PROMPTS.has(inputValue.trim())) {
      setInputValue(selectionPrompt(capture.kind, nextSelections.length));
    }
    focusComposerAfterDraftWrite('end');
  }

  function handleRemoveCurrentPdfSelection(selectionId: string): void {
    if (isInputDisabled) return;
    const normalizedSelectionId = selectionId.trim();
    if (!normalizedSelectionId) return;
    const target = currentPdfSelectionsRef.current.find(
      (selectionState) => selectionState.id === normalizedSelectionId,
    );
    if (!target) return;
    const nextSelections = currentPdfSelectionsRef.current.filter(
      (selectionState) => selectionState.id !== normalizedSelectionId,
    );
    setCurrentPdfSelections(nextSelections);
    if (target.imageFingerprint) {
      setDraftAttachments((current) => withoutAttachmentFingerprints(
        current,
        [target.imageFingerprint],
      ));
    }
    if (nextSelections.length === 0 && DIALOG_SELECTION_AUTO_PROMPTS.has(inputValue.trim())) {
      setInputValue('');
    }
  }

  function handleSelectContextMaterial(material: WritingMaterialResource): void {
    const materialId = normalizeMaterialId(material.material_id);
    if (!materialId) return;
    const title = materialTitleLabel(material);
    const materialProjectId = normalizeProjectId(material.project_id) || effectiveProjectId;
    if (materialProjectId && materialProjectId !== activeProjectId) {
      setActiveProjectId(materialProjectId);
    }
    focusMaterialReaderPane(materialId, title);
    setContextRailOpen(true);
    setContextRailTab('chat');
    writeReaderSearchParams(materialId, { title });
  }
  function handleGraphNavigateTarget(target: GraphNavigateTarget): void {
    const targetMaterialId = normalizeMaterialId(target.material_id);
    if (!targetMaterialId) return;
    const targetPage = typeof target.page === 'number'
      && Number.isInteger(target.page)
      && target.page > 0
      ? target.page
      : null;
    const targetBbox = targetPage && isPdfBboxUnit(target.bbox_unit)
      ? normalizePdfUrlBbox(target.bbox, target.bbox_unit)
      : null;
    const targetBboxUnit: PdfBboxUnit | null = targetBbox ? 'normalized_ratio' : null;
    const targetChunkId = normalizeMaterialId(target.chunk_id ?? '') || null;
    setGraphExplorerOpen(false);
    setContextRailOpen(true);
    setContextRailTab('graph');
    if (targetMaterialId === pinnedMaterialId) {
      setEmbeddedReaderTarget((previous) => ({
        page: targetPage ?? undefined,
        bbox: targetBbox ?? undefined,
        bboxUnit: targetBboxUnit,
        chunkId: targetChunkId ?? undefined,
        nonce: previous.nonce + 1,
      }));
      setCenterTab('reader');
      writeReaderSearchParams(targetMaterialId, {
        title: activeMaterialLabel || pinnedMaterialTitle || targetMaterialId,
        page: targetPage,
        chunkId: targetChunkId,
        bbox: targetBbox ? [...targetBbox] : null,
        bboxUnit: targetBboxUnit,
        replace: false,
      });
      return;
    }
    const material = projectMaterials.find((item) => normalizeMaterialId(item.material_id) === targetMaterialId);
    focusMaterialReaderPane(targetMaterialId, material ? materialTitleLabel(material) : targetMaterialId);
    writeReaderSearchParams(targetMaterialId, {
      title: material ? materialTitleLabel(material) : targetMaterialId,
      page: targetPage,
      chunkId: targetChunkId,
      bbox: targetBbox ? [...targetBbox] : null,
      bboxUnit: targetBboxUnit,
      replace: false,
    });
  }
  async function handleSelectEvidence(evidence: EvidenceRefLike): Promise<void> {
    const activationSequence = evidenceActivationSequenceRef.current + 1;
    evidenceActivationSequenceRef.current = activationSequence;
    const normalizedProjectId = effectiveProjectId || queryProjectId;
    const evidenceChunkId = normalizeMaterialId(evidence.chunk_id ?? '');
    let targetMaterialId = normalizeMaterialId(evidence.material_id ?? '');
    let targetPage = evidenceRefPageNumber(evidence);
    let targetBbox = targetPage ? evidenceRefBbox(evidence) : null;
    let targetBboxUnit: PdfBboxUnit | null = targetBbox ? 'normalized_ratio' : null;
    const targetAnchorKind = evidence.anchor_kind === 'visual' ? 'visual' : 'text';

    if ((!targetMaterialId || !targetPage || !targetBbox) && evidenceChunkId && normalizedProjectId) {
      let locator: ChunkLocator | null = null;
      try {
        locator = await locateChunk(evidenceChunkId, normalizedProjectId);
      } catch {
        // A locator outage must not discard an already usable material/page target.
      }
      if (activationSequence !== evidenceActivationSequenceRef.current) return;
      const locatorMaterialId = normalizeMaterialId(locator?.material_id ?? '');
      const locatorChunkId = normalizeMaterialId(locator?.chunk_id ?? '');
      const locatorMatchesTarget = locator !== null
        && locatorChunkId === evidenceChunkId
        && Boolean(locatorMaterialId)
        && (!targetMaterialId || locatorMaterialId === targetMaterialId);
      const trustedLocator = locatorMatchesTarget ? locator : null;
      const locatorPage = typeof trustedLocator?.page === 'number'
        && Number.isInteger(trustedLocator.page)
        && trustedLocator.page > 0
        ? trustedLocator.page
        : null;
      if (!targetMaterialId && locatorMaterialId && trustedLocator) {
        targetMaterialId = locatorMaterialId;
      }
      if (!targetPage && locatorPage !== null) {
        targetPage = locatorPage;
      }
      const locatorBbox = isPdfBboxUnit(trustedLocator?.bbox_unit)
        ? normalizePdfUrlBbox(trustedLocator?.bbox, trustedLocator.bbox_unit)
        : null;
      if (!targetBbox && locatorPage !== null && locatorBbox) {
        targetBbox = locatorBbox;
        targetBboxUnit = 'normalized_ratio';
        targetPage = locatorPage;
      }
    }

    if (!targetMaterialId) return;
    const targetQuote = targetAnchorKind === 'text'
      ? normalizePdfQuote(evidence.quote)
      : null;
    const material = projectMaterials.find((item) => normalizeMaterialId(item.material_id) === targetMaterialId);
    const title = material ? materialTitleLabel(material) : evidence.source_title || evidence.source || targetMaterialId;
    focusMaterialReaderPane(targetMaterialId, title);
    setContextRailOpen(true);
    setContextRailTab('chat');
    if (targetMaterialId === pinnedMaterialId) {
      setEmbeddedReaderTarget((previous) => ({
        page: targetPage ?? undefined,
        bbox: targetBbox ?? undefined,
        bboxUnit: targetBboxUnit,
        chunkId: evidenceChunkId || undefined,
        quote: targetQuote ?? undefined,
        nonce: previous.nonce + 1,
      }));
    }
    writeReaderSearchParams(targetMaterialId, {
      title,
      page: targetPage,
      chunkId: evidenceChunkId || null,
      bbox: targetBbox ? [...targetBbox] : null,
      bboxUnit: targetBboxUnit,
      quote: targetQuote,
      anchorKind: targetAnchorKind,
      replace: false,
    });
  }
  function handleOpenGraphExplorer(): void {
    if (!evidenceGraphPayload) return;
    setContextRailOpen(true);
    setContextRailTab('graph');
    setGraphExplorerOpen(true);
  }
  function constrainResizablePaneWidth(
    pane: DialogResizablePane,
    value: number,
    rootWidth: number,
    otherPaneWidth: number,
  ): number {
    const min = pane === 'history' ? DIALOG_HISTORY_MIN_WIDTH : DIALOG_CONTEXT_MIN_WIDTH;
    const max = pane === 'history' ? DIALOG_HISTORY_MAX_WIDTH : DIALOG_CONTEXT_MAX_WIDTH;
    const maxWithinShell = Math.max(min, rootWidth - otherPaneWidth - DIALOG_MAIN_MIN_WIDTH);
    return clampPaneWidth(value, min, Math.min(max, maxWithinShell), min);
  }

  function handlePaneResizeStart(
    pane: DialogResizablePane,
    event: ReactPointerEvent<HTMLButtonElement>,
  ): void {
    if (event.button !== 0) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = paneWidths[pane];
    const rootWidth = dialogShellRef.current?.getBoundingClientRect().width ?? window.innerWidth;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const handlePointerMove = (moveEvent: PointerEvent): void => {
      const delta = moveEvent.clientX - startX;
      const requestedWidth = pane === 'history' ? startWidth + delta : startWidth - delta;
      setPaneWidths((current) => {
        const otherPaneWidth = pane === 'history'
          ? (contextRailOpen ? current.context : 0)
          : (historyRailCollapsed ? 0 : current.history);
        return {
          ...current,
          [pane]: constrainResizablePaneWidth(pane, requestedWidth, rootWidth, otherPaneWidth),
        };
      });
    };

    const stopResize = (): void => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', stopResize);
      window.removeEventListener('pointercancel', stopResize);
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', stopResize);
    window.addEventListener('pointercancel', stopResize);
  }

  const composerContext = (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-[11px] text-foreground/50">
      <ComposerControlMenu
        label="范围"
        title={`检索范围：${dialogContextScope === 'paper' ? '本文献' : '项目文献'}`}
        icon={dialogContextScope === 'paper' ? BookOpen : FolderKanban}
        disabled={isInputDisabled}
      >
        {(close) => ([
          { id: 'paper' as const, label: '本文献', description: '围绕当前打开的文献检索。', icon: BookOpen, disabled: !pinnedMaterialId },
          { id: 'project' as const, label: '项目文献', description: '在当前项目材料中检索。', icon: FolderKanban, disabled: false },
        ].map((option) => (
          <ComposerMenuItem
            key={option.id}
            label={option.label}
            description={option.disabled ? '从知识库文献进入后可用。' : option.description}
            icon={option.icon}
            selected={dialogContextScope === option.id}
            disabled={option.disabled}
            title={option.disabled ? '从知识库文献进入后可用' : option.description}
            onSelect={() => {
              handleContextScopeChange(option.id);
              close();
            }}
          />
        )))}
      </ComposerControlMenu>
      <ComposerControlMenu
        label="给智能体"
        title={agentHandoffMenuTitle}
        icon={Users2}
        disabled={agentHandoffMenuDisabled}
        width="compact"
      >
        {(close) => (
          <ComposerMenuItem
            role="menuitem"
            label={agentHandoffButtonText}
            description="创建接手任务，智能体可读取同一条证据链并写回结果。"
            icon={Users2}
            disabled={agentHandoffDisabled}
            title={agentHandoffActionTitle}
            onSelect={() => {
              close();
              void handleCreateAgentHandoff();
            }}
          />
        )}
      </ComposerControlMenu>
      <EnhancementMenu
        disabled={isInputDisabled}
        onSelect={(intent) => launchDiscussionEnhancement(intent)}
      />
      {agentHandoffMessage ? (
        <span
          className={agentHandoffState === 'error'
            ? 'min-w-0 max-w-[220px] truncate text-[11px] text-destructive'
            : 'sr-only'}
          title={agentHandoffMessage}
          aria-live="polite"
        >
          {agentHandoffMessage}
        </span>
      ) : null}
    </div>
  );
  const contextRailTabs: Array<{
    id: DialogContextRailTab;
    label: string;
    icon: typeof BookOpen;
    count?: number;
  }> = [
    ...(readerTabAvailable
      ? [
          { id: 'chat' as const, label: '研读对话', icon: MessageCircle },
          { id: 'discussion' as const, label: '多人讨论', icon: Users2 },
        ]
      : []),
    { id: 'paper', label: '本文献', icon: BookOpen, count: pinnedMaterialId ? 1 : 0 },
    { id: 'project', label: '项目文献', icon: FolderKanban, count: projectMaterialCount },
    { id: 'graph', label: '图谱', icon: Network, count: evidenceGraphStats.evidence },
    { id: 'notes', label: '笔记', icon: FileText, count: annotationNoteCount },
  ];

  const renderProjectMaterialRows = (materials: WritingMaterialResource[]) => (
    <div className="space-y-2">
      {materials.map((material) => {
        const materialId = normalizeMaterialId(material.material_id);
        const title = materialTitleLabel(material);
        const summary = materialSummaryLabel(material);
        const focusPoints = materialFocusPoints(material);
        const updatedAt = formatMaterialDate(material.updated_at || material.created_at);
        const selected = materialId === pinnedMaterialId;
        return (
          <article
            key={material.material_id}
            className={`rounded-md border p-3 transition-colors ${
              selected
                ? 'border-primary/45 bg-primary/10'
                : 'border-outline-variant/60 bg-surface-low hover:border-primary/35'
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <button
                type="button"
                onClick={() => handleSelectContextMaterial(material)}
                className="min-w-0 flex-1 text-left"
              >
                <h3 className="line-clamp-2 text-xs font-semibold leading-relaxed text-foreground">
                  {title}
                </h3>
              </button>
              {updatedAt && (
                <span className="shrink-0 text-[10px] text-foreground/45">{updatedAt}</span>
              )}
            </div>
            <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-foreground/60">
              {summary}
            </p>
            {focusPoints.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {focusPoints.map((point) => (
                  <span
                    key={`${material.material_id}:${point}`}
                    className="rounded border border-outline-variant/50 bg-surface-lowest px-1.5 py-0.5 text-[10px] text-foreground/55"
                  >
                    {point}
                  </span>
                ))}
              </div>
            )}
            <div className="mt-3 flex items-center gap-2">
              {/* B9 (2026-06-13): 原本有「阅读」+「研读」两按钮，功能高度重叠
                  （都调 focusMaterialReaderPane）。删「阅读」，「研读」成为
                  唯一入口；研读 = 中间栏展开 PDF + 右栏切 chat tab + 输入框
                  围绕该文献提问。 */}
              <button
                type="button"
                onClick={() => handleSelectContextMaterial(material)}
                disabled={!materialId}
                className="inline-flex items-center gap-1 rounded-md border border-outline-variant/60 px-2 py-1 text-xs text-foreground/65 transition-colors hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              >
                <MessageCircle className="h-3.5 w-3.5" aria-hidden />
                研读
              </button>
            </div>
          </article>
        );
      })}
    </div>
  );

  const renderProjectMaterialsStatus = () => {
    if (projectMaterialsState === 'loading' && projectMaterials.length === 0) {
      return <div className="py-8 text-center text-sm text-foreground/55">正在加载文献…</div>;
    }
    if (projectMaterialsError) {
      return (
        <div role="alert" className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
          {projectMaterialsError}
        </div>
      );
    }
    if (!effectiveProjectId) {
      return <div className="py-8 text-center text-sm text-foreground/55">未选择项目</div>;
    }
    if (projectMaterials.length === 0) {
      return <div className="py-8 text-center text-sm text-foreground/55">暂无项目文献</div>;
    }
    return null;
  };

  const renderEmbeddedReader = () => {
    if (!pinnedMaterialId) return null;
    const _material = activePinnedMaterial;
    return (
      <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-md border border-outline-variant/60 bg-surface-low">
        <PdfTabStrip onActivate={handlePdfTabActivate} onEmpty={handlePdfTabsEmpty} />
        <div className="min-h-0 flex-1 overflow-hidden">
          <ErrorBoundary fallbackTitle="PDF 阅读器暂时无法显示">
            <Suspense fallback={<PdfReaderFallback />}>
              <PdfReaderShell
                key={`${pinnedMaterialId}:${embeddedReaderTarget.nonce}:${searchParams.get('page') ?? ''}:${searchParams.get('bbox') ?? ''}:${searchParams.get('chunk') ?? ''}:${searchParams.get('quote') ?? ''}`}
                url={pinnedPdfUrl}
                materialId={pinnedMaterialId}
                projectId={normalizeProjectId(_material?.project_id) || null}
                analysisDisabled={isInputDisabled}
                initialPage={effectiveReaderPage ?? undefined}
                initialBbox={effectiveReaderBbox}
                initialQuote={effectiveReaderQuote}
                highlights={embeddedReaderHighlights}
                notes={annotationNotes}
                formulaCandidates={readerFormulaCandidates}
                selectedVisualRegions={selectedReaderVisualRegions}
                className="h-full"
                onAnalyzeText={handleAnalyzeReaderText}
                onAnalyzeRegion={handleAnalyzeReaderRegion}
                onPageChange={handleEmbeddedReaderPageChange}
              />
            </Suspense>
          </ErrorBoundary>
        </div>
      </div>
    );
  };

  const renderContextRailContent = () => {
    if (contextRailTab === 'chat') {
      return chatPanel;
    }

    if (contextRailTab === 'discussion') {
      return (
        <DialogDiscussionWorkbench
          launchState={discussionLaunchState}
          onHistoryChanged={() => {
            void refreshSessions(historyMode, { surfaceError: false });
          }}
        />
      );
    }

    if (contextRailTab === 'paper') {
      const status = renderProjectMaterialsStatus();
      const material = activePinnedMaterial;
      if (!pinnedMaterialId) {
        return (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center">
            <BookOpen className="mb-3 h-10 w-10 text-foreground/20" aria-hidden />
            <p className="text-sm font-medium text-foreground/60">未选择本文献</p>
            <button
              type="button"
              onClick={() => setContextRailTab('project')}
              className="mt-3 inline-flex items-center gap-1 rounded-md border border-outline-variant/60 px-2.5 py-1.5 text-xs text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
            >
              <FolderKanban className="h-3.5 w-3.5" aria-hidden />
              项目文献
            </button>
          </div>
        );
      }
      return (
        <div className="space-y-3">
          {status}
          <section className="rounded-md border border-outline-variant/60 bg-surface-low p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <h3 className="line-clamp-2 text-sm font-semibold leading-relaxed text-foreground">
                  {material ? materialTitleLabel(material) : activeMaterialLabel}
                </h3>
                {material && (
                  <p className="mt-1 text-[11px] text-foreground/45">
                    {formatMaterialDate(material.updated_at || material.created_at)}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={handleFocusPinnedMaterialReader}
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-lowest text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
                aria-label={pinnedLooksLikePdf ? '在中间栏阅读本文献' : '打开本文献'}
                title={pinnedLooksLikePdf ? '在中间栏阅读' : '打开本文献'}
              >
                <BookOpen className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
            {material && (
              <>
                <p className="mt-3 text-xs leading-relaxed text-foreground/65">
                  {materialSummaryLabel(material)}
                </p>
                {materialFocusPoints(material).length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1">
                    {materialFocusPoints(material).map((point) => (
                      <span
                        key={`${material.material_id}:paper:${point}`}
                        className="rounded border border-outline-variant/50 bg-surface-lowest px-1.5 py-0.5 text-[10px] text-foreground/55"
                      >
                        {point}
                      </span>
                    ))}
                  </div>
                )}
              </>
            )}
          </section>
          {pinnedLooksLikePdf && (
            <button
              type="button"
              onClick={handleFocusPinnedMaterialReader}
              className="inline-flex w-full items-center justify-center gap-1.5 rounded-md border border-primary/35 bg-primary/10 px-3 py-2 text-xs font-medium text-primary transition-colors hover:border-primary/50 hover:bg-primary/15"
            >
              <BookOpen className="h-3.5 w-3.5" aria-hidden />
              在中间栏阅读
            </button>
          )}
          <button
            type="button"
            onClick={() => setContextRailTab('project')}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-low px-3 py-2 text-xs font-medium text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
          >
            <FolderKanban className="h-3.5 w-3.5" aria-hidden />
            切换项目文献
          </button>
        </div>
      );
    }

    if (contextRailTab === 'project') {
      const status = renderProjectMaterialsStatus();
      return (
        <div className="space-y-3">
          <button
            type="button"
            onClick={() => void refreshProjectMaterials()}
            disabled={projectMaterialsState === 'loading' || !effectiveProjectId}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-low px-3 py-2 text-xs font-medium text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${projectMaterialsState === 'loading' ? 'animate-spin' : ''}`} aria-hidden />
            刷新文献
          </button>
          {status ?? renderProjectMaterialRows(projectMaterials)}
        </div>
      );
    }

    if (contextRailTab === 'graph') {
      return (
        <>
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-xs font-medium text-foreground/65">当前上下文图谱</p>
              <p className="text-[11px] text-foreground/45">
                {evidenceGraphStats.evidence} 条证据 · {evidenceGraphStats.materials} 篇材料
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                onClick={() => {
                  void refreshProjectMaterials({ surfaceError: false });
                  setEvidenceGraphRefreshToken((current) => current + 1);
                }}
                className="inline-flex items-center gap-1 rounded-md border border-outline-variant/60 px-2 py-1 text-[11px] text-foreground/60 transition-colors hover:border-primary/40 hover:text-foreground"
                title="刷新当前项目材料和图谱"
              >
                <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                刷新
              </button>
              {evidenceGraphPayload ? (
                <button
                  type="button"
                  onClick={handleOpenGraphExplorer}
                  className="inline-flex items-center gap-1 rounded-md border border-primary/40 bg-primary/10 px-2 py-1 text-[11px] text-primary transition-colors hover:bg-primary/15"
                  title="展开为全宽图谱工作台"
                >
                  <Maximize2 className="h-3.5 w-3.5" aria-hidden />
                  展开
                </button>
              ) : null}
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-hidden rounded-md border border-outline-variant/60 bg-surface-low">
            {evidenceGraphPayload ? (
              <WikiGraphSegmentedView
                payload={evidenceGraphPayload}
                domain="answer"
                projectId={effectiveProjectId || null}
                onNavigateTarget={handleGraphNavigateTarget}
                variant="rail"
                selectedDimensions={graphSelectedDimensions}
                onChangeSelectedDimensions={setGraphSelectedDimensions}
              />
            ) : (
              <div className="flex h-full flex-col items-center justify-center px-6 text-center">
                <Network className="mb-3 h-10 w-10 text-foreground/20" aria-hidden />
                <p className="text-sm font-medium text-foreground/60">暂无证据图谱</p>
              </div>
            )}
          </div>
          {evidenceGraphPayload && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-foreground/45">
              <span>{evidenceGraphStats.edges} 条关系</span>
            </div>
          )}
        </>
      );
    }

    if (contextRailTab === 'notes') {
      if (!pinnedMaterialId) {
        return (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center">
            <FileText className="mb-3 h-10 w-10 text-foreground/20" aria-hidden />
            <p className="text-sm font-medium text-foreground/60">未选择本文献</p>
            <button
              type="button"
              onClick={() => setContextRailTab('project')}
              className="mt-3 inline-flex items-center gap-1 rounded-md border border-outline-variant/60 px-2.5 py-1.5 text-xs text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
            >
              <FolderKanban className="h-3.5 w-3.5" aria-hidden />
              项目文献
            </button>
          </div>
        );
      }
      if (annotationNotesState === 'loading' && annotationNotes.length === 0) {
        return <div className="py-8 text-center text-sm text-foreground/55">正在加载笔记…</div>;
      }
      if (annotationNotesError) {
        return (
          <div role="alert" className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
            {annotationNotesError}
          </div>
        );
      }
      if (annotationNotes.length === 0) {
        return (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center">
            <FileText className="mb-3 h-10 w-10 text-foreground/20" aria-hidden />
            <p className="text-sm font-medium text-foreground/60">暂无笔记</p>
            <button
              type="button"
              onClick={handleFocusPinnedMaterialReader}
              className="mt-3 inline-flex items-center gap-1 rounded-md border border-outline-variant/60 px-2.5 py-1.5 text-xs text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
            >
              <BookOpen className="h-3.5 w-3.5" aria-hidden />
              阅读
            </button>
          </div>
        );
      }
      return (
        <div className="space-y-3">
          <button
            type="button"
            onClick={() => void refreshAnnotationNotes()}
            disabled={annotationNotesState === 'loading'}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-low px-3 py-2 text-xs font-medium text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${annotationNotesState === 'loading' ? 'animate-spin' : ''}`} aria-hidden />
            刷新笔记
          </button>
          {annotationNotes.map((note) => {
            const body = noteBodyLabel(note);
            const anchor = noteAnchorLabel(note);
            const tags = noteTags(note);
            return (
              <article
                key={note.note_id}
                className="rounded-md border border-outline-variant/60 bg-surface-low p-3"
              >
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="rounded border border-outline-variant/50 bg-surface-lowest px-1.5 py-0.5 text-[10px] text-foreground/55">
                    p.{note.page}
                  </span>
                  <span className="text-[10px] text-foreground/45">
                    {formatMaterialDate(note.updated_at || note.created_at)}
                  </span>
                </div>
                {anchor && (
                  <blockquote className="mb-2 line-clamp-2 border-l-2 border-primary/35 pl-2 text-[11px] leading-relaxed text-foreground/50">
                    {anchor}
                  </blockquote>
                )}
                <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-foreground/75">
                  {body}
                </p>
                {tags.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {tags.map((tag) => (
                      <span
                        key={`${note.note_id}:${tag}`}
                        className="rounded border border-outline-variant/50 bg-surface-lowest px-1.5 py-0.5 text-[10px] text-foreground/55"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => handleOpenPinnedMaterialPage(note.page)}
                  className="mt-3 inline-flex items-center gap-1 rounded-md border border-outline-variant/60 px-2 py-1 text-xs text-foreground/65 transition-colors hover:border-primary/40 hover:text-foreground"
                >
                  <BookOpen className="h-3.5 w-3.5" aria-hidden />
                  打开第 {note.page} 页
                </button>
              </article>
            );
          })}
        </div>
      );
    }

    return null;
  };

  const renderHistoryError = () => (
    historyErrorMessage ? (
      <div
        role="alert"
        className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300"
      >
        {historyErrorMessage}
      </div>
    ) : null
  );
  const renderSessionGroups = (compact: boolean) => (
    sessionProjectGroups.map((projectGroup) => (
      <section key={projectGroup.key} className="space-y-2">
        <div className="flex items-center justify-between gap-2 px-1">
          <h3 className="min-w-0 truncate text-[11px] font-semibold text-foreground/60">
            {projectGroup.label}
          </h3>
          <div className="flex shrink-0 items-center gap-1.5">
            <span className="text-[10px] text-foreground/45">
              {projectGroup.branchGroups.reduce((count, group) => count + 1 + group.forks.length, 0)} 个会话
            </span>
            <button
              type="button"
              onClick={() => void handleClearSessionGroup(projectGroup)}
              disabled={historyState === 'loading' || chatState === 'responding'}
              title="清空本组会话（仅删除本机记录，不可恢复）"
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] text-foreground/45 transition-colors hover:bg-rose-500/10 hover:text-rose-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Trash2 className="h-3 w-3" />
              清空本组
            </button>
          </div>
        </div>
        {projectGroup.branchGroups.map((group) => (
          <div key={group.root.session_id} className="space-y-2">
            {[group.root, ...group.forks].map((item, rowIndex) => {
              const isFork = rowIndex > 0;
              const isDiscussion = isDiscussionSession(item);
              const agentCount = sessionSummaryAgentCount(item);
              const legacyModeLabel = sessionModeLabel(item.mode);
              const fallbackLabel = isFork ? '分叉会话' : isDiscussion ? '讨论会话' : '会话';
              const titleLabel = sanitizeChatVisibleText(
                item.title || item.preview,
                fallbackLabel,
                { maxLength: 80 },
              );
              const previewLabel = sanitizeChatVisibleText(
                (isDiscussion ? item.synthesis_preview || item.preview : item.preview) || item.title,
                titleLabel,
                { maxLength: 180 },
              );
              const isActiveSession = sessionId === item.session_id;
              return (
                <div
                  key={item.session_id}
                  className={`rounded-md border transition-colors ${compact ? 'p-3' : 'p-4'} ${
                    isActiveSession
                      ? 'border-primary/45 bg-primary/10'
                      : 'border-outline-variant/60 bg-surface-low hover:border-primary/40 hover:bg-primary/5'
                  } ${isFork ? (compact ? 'ml-4 border-l-2 border-l-primary/45' : 'ml-5 border-l-2 border-l-primary/45') : ''}`}
                >
                  <div className={`mb-2 flex gap-2 ${compact ? 'items-start justify-between' : 'items-center justify-between'}`}>
                    <div className="flex min-w-0 items-center gap-2">
                      {isFork && <GitFork className="h-3.5 w-3.5 shrink-0 text-primary/70" />}
                      <button
                        type="button"
                        onClick={() => handleResumeSession(item.session_id, item)}
                        disabled={historyState === 'loading' || chatState === 'responding'}
                        className={`min-w-0 truncate text-left transition-colors hover:text-primary disabled:cursor-not-allowed disabled:opacity-60 ${
                          compact ? 'text-xs font-semibold text-foreground/75' : 'text-xs font-medium text-foreground/70'
                        }`}
                      >
                        {titleLabel}
                      </button>
                      {isFork && item.fork && !compact && (
                        <span className="inline-flex max-w-[9rem] items-center rounded-md border border-primary/25 bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                          分叉
                        </span>
                      )}
                      {isDiscussion && (
                        <span
                          title="多智能体讨论会话"
                          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-primary/25 bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary"
                        >
                          <Users2 className="h-3 w-3" aria-hidden />
                          讨论
                        </span>
                      )}
                      {(legacyModeLabel || item.legacy_mode_inferred) && (
                        <span
                          title="旧会话会按统一智能研读入口继续"
                          className="inline-flex shrink-0 items-center rounded-md border border-outline-variant bg-surface-high px-1.5 py-0.5 text-[10px] text-foreground/60"
                        >
                          {legacyModeLabel ?? '旧版'}
                        </span>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {agentCount > 1 && (
                        <span className="whitespace-nowrap rounded-md border border-outline-variant/60 px-1.5 py-0.5 text-[10px] text-foreground/55">
                          {agentCount} 智能体
                        </span>
                      )}
                      <span className={`whitespace-nowrap text-foreground/55 ${compact ? 'text-[11px]' : 'text-xs'}`}>
                        {item.total_turns} 轮
                      </span>
                    </div>
                  </div>
                  {isFork && item.fork && (
                    <p className="mb-2 text-[10px] text-foreground/45">从原会话分叉</p>
                  )}
                  <button
                    type="button"
                    onClick={() => handleResumeSession(item.session_id, item)}
                    disabled={historyState === 'loading' || chatState === 'responding'}
                    className="block w-full text-left disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <p className={`line-clamp-2 ${compact ? 'text-xs leading-relaxed' : 'text-sm'} text-foreground/85`}>
                      {previewLabel}
                    </p>
                  </button>
                  {item.updated_at && (
                    <p className={`mt-2 text-foreground/55 ${compact ? 'text-[11px]' : 'text-xs'}`}>
                      {compact ? '' : '最近更新 '}
                      {parseChatTimestamp(item.updated_at).toLocaleString()}
                    </p>
                  )}
                  <div className="mt-3 flex items-center gap-2">
                    {historyMode === 'archived' || item.archived ? (
                      <button
                        type="button"
                        onClick={() => void handleRestoreSession(item)}
                        disabled={historyState === 'loading' || chatState === 'responding'}
                        className="inline-flex items-center gap-1 rounded-md border border-outline-variant/60 px-2 py-1 text-xs text-foreground/65 transition-colors hover:border-primary/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        恢复
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => void handleArchiveSession(item)}
                        disabled={historyState === 'loading' || chatState === 'responding'}
                        className="inline-flex items-center gap-1 rounded-md border border-outline-variant/60 px-2 py-1 text-xs text-foreground/65 transition-colors hover:border-primary/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Archive className="h-3.5 w-3.5" />
                        归档
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => handleDeleteSession(item)}
                      disabled={historyState === 'loading' || chatState === 'responding'}
                      className="inline-flex items-center gap-1 rounded-md border border-red-200 px-2 py-1 text-xs text-red-600 transition-colors hover:bg-red-50 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-700/40 dark:text-red-300 dark:hover:bg-red-500/15"
                      aria-label={`删除 ${titleLabel}`}
                      title="删除会话"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      删除
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </section>
    ))
  );

  const activeComposerSelections = currentPdfSelections.map(dialogSelectionContext);
  const chatPanel = (
    <Conversation
      className="min-h-0 flex-1"
      messages={visibleConversationMessages}
      onSubmit={(payload) => void handleSendMessage(payload)}
      projectId={effectiveProjectId}
      inputValue={inputValue}
      onInputValueChange={setInputValue}
      placeholder={inputPlaceholder}
      disabled={isInputDisabled}
      responding={isInputDisabled}
      onStop={handleStopGeneration}
      inputRef={chatInputRef}
      onEditMessage={handleEditMessage}
      onForkMessage={handleForkMessage}
      messageFooter={renderAgentHandoffFooter}
      onSelectEvidence={(evidence) => {
        void handleSelectEvidence(evidence);
      }}
      submitKey="enter"
      composerRows={3}
      composerAriaLabel="对话输入"
      autoFocusComposer={!isInputDisabled}
      enableAttachments
      attachments={draftAttachments}
      onAttachmentsChange={setDraftAttachments}
      pendingAttachmentReads={pendingAttachmentReads}
      onPendingAttachmentReadsChange={setPendingAttachmentReads}
      selectionContexts={activeComposerSelections}
      onRemoveSelectionContext={handleRemoveCurrentPdfSelection}
      composerHint={isInputDisabled
        ? `AI 思考中 · ${requestElapsedSec}s / ${DIALOG_REQUEST_TIMEOUT_SECONDS}s`
        : `按 Enter 发送，Shift+Enter 换行 · 单次请求最多等待 ${DIALOG_REQUEST_TIMEOUT_SECONDS}s`}
      projectReasoningBias={{
        enabled: projectBiasEnabled,
        available: defaultProjectBiasEnabled,
        loading: projectReasoningBias.loading,
        onChange: setProjectBiasEnabled,
      }}
      composerContext={composerContext}
      emptyState={(
        <div className="flex h-full flex-col items-center justify-center px-6 text-center">
          <MessageCircle className="mb-4 h-16 w-16 text-foreground/25" />
          <h2 className="mb-2 text-xl font-semibold text-foreground/75">开始一段对话</h2>
          <p className="max-w-md text-foreground/55">{emptyHint}</p>
          {suggestedQuestions.length > 0 && (
            <section
              aria-label="根据当前文献生成的试问"
              className="mt-6 w-full max-w-2xl text-left"
            >
              <div className="mb-2 flex items-center justify-between gap-3">
                <h3 className="text-xs font-semibold text-foreground/55">可以这样问</h3>
                {suggestedQuestionStatusLabel && (
                  <span className="text-[11px] text-foreground/40">
                    {suggestedQuestionStatusLabel}
                  </span>
                )}
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {suggestedQuestions.map((question) => (
                  <button
                    key={question.id}
                    type="button"
                    onClick={() => handleUseSuggestedQuestion(question)}
                    disabled={chatState === 'responding'}
                    className="group min-h-[4.75rem] rounded-md border border-outline-variant/60 bg-surface-low p-3 text-left transition-colors hover:border-primary/45 hover:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <span className="mb-1 inline-flex rounded border border-outline-variant/50 bg-surface-lowest px-1.5 py-0.5 text-[10px] font-medium text-foreground/50 group-hover:border-primary/35 group-hover:text-primary">
                      {question.label}
                    </span>
                    <span className="line-clamp-3 block text-xs leading-relaxed text-foreground/72">
                      {question.question}
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
      transcriptFooter={(
        <>
          {isUnavailable && (
            <div className="mb-4 p-4 bg-yellow-50 border-l-4 border-yellow-400 rounded-lg">
              <div className="flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" />
                <div>
                  <h3 className="text-sm font-semibold text-yellow-800 mb-1">智能研读暂不可用</h3>
                  <p className="text-sm text-yellow-700 mb-2">
                    当前知识库还没有可用于回答的文献来源。
                  </p>
                  <p className="text-xs text-yellow-600">
                    请先到<strong>知识库</strong>添加文献，再回到这里提问。
                  </p>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    />
  );

  return (
    <div ref={dialogShellRef} className="dialog-shell flex h-full min-h-0 min-w-0 overflow-hidden">
      {!historyRailCollapsed && (
        <>
      <aside
        style={{ width: paneWidths.history }}
        className="dialog-rail hidden h-full min-h-0 shrink-0 flex-col border-r lg:flex"
      >
        <div className="dialog-band px-4 py-3">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <h2 className="truncate text-sm font-semibold text-foreground">研读历史</h2>
              <p className="truncate text-[11px] text-foreground/55">按项目延续、归档或恢复会话</p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={() => void refreshSessions()}
              disabled={historyState === 'loading'}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-low text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
              aria-label="刷新会话列表"
              title="刷新"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${historyState === 'loading' ? 'animate-spin' : ''}`} />
            </button>
              <button
                type="button"
                onClick={() => setHistoryRailCollapsed(true)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-low text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
                aria-label="收起历史会话"
                title="收起历史会话"
              >
                <PanelLeftClose className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 rounded-lg border border-outline-variant/50 bg-surface-low p-1">
            {(['recent', 'archived'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setHistoryMode(mode)}
                className={`rounded-md px-2 py-1.5 text-xs font-medium transition-colors ${
                  historyMode === mode
                    ? 'bg-primary text-primary-foreground'
                    : 'text-foreground/55 hover:text-foreground'
                }`}
              >
                {mode === 'recent' ? '最近' : '归档'}
              </button>
            ))}
          </div>
          <form
            className="mt-3 flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void handleSearchHistory();
            }}
          >
            <input
              value={historyQuery}
              onChange={(event) => setHistoryQuery(event.target.value)}
              placeholder="搜索问题、回答、证据…"
              className="min-w-0 flex-1 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-2 text-xs text-foreground outline-none transition-colors focus:border-primary/60"
            />
            <button
              type="submit"
              disabled={historySearchState === 'loading'}
              className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-low text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
              aria-label="搜索历史"
              title="搜索历史"
            >
              <Search className={`h-4 w-4 ${historySearchState === 'loading' ? 'animate-pulse' : ''}`} />
            </button>
          </form>
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
          {renderHistoryError()}
          {historyResults.length > 0 && (
            <section className="space-y-2 border-b border-outline-variant/40 pb-4">
              <div className="flex items-center justify-between">
                <h3 className="text-[10px] font-semibold uppercase tracking-wide text-foreground/50">搜索结果</h3>
                <button
                  type="button"
                  onClick={() => setHistoryResults([])}
                  className="text-xs text-foreground/55 hover:text-foreground"
                >
                  清除
                </button>
              </div>
              {historyResults.map((result) => {
                const snippet = sanitizeChatVisibleText(
                  result.snippet.replace(/<\/?mark>/g, ''),
                  '搜索命中内容已隐藏，避免显示内部配置或本地路径。',
                  { maxLength: 160 },
                );
                return (
                  <div
                    key={`${result.conversation_id}:${result.node_id}`}
                    className="rounded-md border border-outline-variant/60 bg-surface-low p-3"
                  >
                    <button
                      type="button"
                      onClick={() => handleResumeSession(result.conversation_id)}
                      disabled={historyState === 'loading' || chatState === 'responding'}
                      className="block w-full text-left text-xs text-foreground/85 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <span className="mb-1 block text-[10px] text-foreground/45">搜索命中</span>
                      <span className="line-clamp-2">{snippet}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleForkFromResult(result)}
                      disabled={historyState === 'loading' || chatState === 'responding'}
                      className="mt-2 inline-flex items-center gap-1 rounded-md border border-outline-variant/60 px-2 py-1 text-xs text-foreground/65 transition-colors hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <GitFork className="h-3.5 w-3.5" />
                      分叉
                    </button>
                  </div>
                );
              })}
            </section>
          )}

          {historyState === 'loading' && sessions.length === 0 ? (
            <div className="py-8 text-center text-sm text-foreground/55">正在加载会话…</div>
          ) : sessions.length === 0 ? (
            <div className="py-8 text-center text-sm text-foreground/55">
              {historyMode === 'archived' ? '暂无归档会话' : '暂无保存的会话'}
            </div>
          ) : (
            renderSessionGroups(true)
          )}
        </div>
      </aside>
          <button
            type="button"
            onPointerDown={(event) => handlePaneResizeStart('history', event)}
            className="dialog-divider hidden h-full w-2 shrink-0 cursor-col-resize items-center justify-center border-r border-outline-variant/30 text-foreground/30 transition-colors hover:bg-primary/10 hover:text-primary focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary/40 lg:flex"
            aria-label="调整历史栏宽度"
            title="拖动调整历史栏宽度"
          >
            <span className="h-10 w-px rounded bg-current" />
          </button>
        </>
      )}

      <section
        aria-label="智能研读工作区"
        className="relative flex min-h-0 min-w-0 flex-1 flex-col"
      >
        <div className="dialog-band flex items-center justify-between gap-3 px-6 py-3">
          <div className="flex min-w-0 items-center gap-2">
            {historyRailCollapsed && (
              <button
                type="button"
                onClick={() => setHistoryRailCollapsed(false)}
                className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-lowest text-foreground/70 transition-colors hover:border-primary/40 hover:bg-surface-high hover:text-foreground lg:inline-flex"
                aria-label="展开历史会话"
                title="展开历史会话"
              >
                <PanelLeftOpen className="h-3.5 w-3.5" />
              </button>
            )}
            <button
              type="button"
              onClick={handleNewSession}
              disabled={chatState === 'responding'}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-2.5 text-xs font-medium text-foreground/75 transition-colors hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              aria-label="新建对话"
              title="新建对话"
            >
              <Plus className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">新建对话</span>
            </button>
            <button
              type="button"
              onClick={handleOpenTaskCenter}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-2.5 text-xs font-medium text-foreground/75 transition-colors hover:border-primary/40 hover:text-foreground"
              aria-label="打开任务中心"
              title="打开任务中心"
            >
              <Activity className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">任务中心</span>
            </button>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={handleOpenHistory}
              className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-2.5 py-1.5 text-xs font-medium text-foreground/75 transition-colors hover:border-primary/40 hover:text-foreground lg:hidden"
            >
              <History className="h-3.5 w-3.5" /> 历史会话
            </button>
            <button
              type="button"
              onClick={() => setContextRailOpen((open) => !open)}
              className="hidden h-8 w-8 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-lowest text-foreground/75 transition-colors hover:border-primary/40 hover:text-foreground lg:inline-flex"
              aria-pressed={contextRailOpen}
              aria-label={contextRailOpen ? '收起资料栏' : '展开资料栏'}
              title={contextRailOpen ? '收起资料栏' : '展开资料栏'}
            >
              {contextRailOpen ? <PanelRightClose className="h-3.5 w-3.5" /> : <PanelRight className="h-3.5 w-3.5" />}
            </button>
          </div>
        </div>

      {historyRailOpen && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/20 lg:hidden" onClick={() => setHistoryRailOpen(false)}>
          <aside
            className="dialog-rail flex h-full w-full max-w-md flex-col border-l shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="dialog-band flex items-center justify-between px-5 py-4">
              <div>
                <h2 className="text-lg font-semibold text-foreground">历史会话</h2>
                <p className="text-xs text-foreground/55">恢复一段此前的对话以继续讨论</p>
              </div>
              <button
                type="button"
                onClick={() => setHistoryRailOpen(false)}
                className="rounded-md p-2 text-foreground/55 transition-colors hover:bg-surface-high hover:text-foreground"
                aria-label="关闭历史"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="border-b border-outline-variant/40 px-5 py-3">
              <div className="mb-3 grid grid-cols-2 rounded-lg border border-outline-variant/50 bg-surface-low p-1">
                {(['recent', 'archived'] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setHistoryMode(mode)}
                    className={`rounded-md px-2 py-1.5 text-sm font-medium transition-colors ${
                      historyMode === mode
                        ? 'bg-primary text-primary-foreground'
                        : 'text-foreground/55 hover:text-foreground'
                    }`}
                  >
                    {mode === 'recent' ? '最近' : '归档'}
                  </button>
                ))}
              </div>
              <form
                className="mb-3 flex gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void handleSearchHistory();
                }}
              >
                <input
                  value={historyQuery}
                  onChange={(event) => setHistoryQuery(event.target.value)}
                  placeholder="搜索问题、回答、证据…"
                  className="min-w-0 flex-1 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-2 text-sm text-foreground outline-none transition-colors focus:border-primary/60"
                />
                <button
                  type="submit"
                  disabled={historySearchState === 'loading'}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-low text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
                  aria-label="搜索历史"
                  title="搜索历史"
                >
                  <Search className={`h-4 w-4 ${historySearchState === 'loading' ? 'animate-pulse' : ''}`} />
                </button>
              </form>
              {renderHistoryError()}
              <button
                type="button"
                onClick={() => void refreshSessions()}
                disabled={historyState === 'loading'}
                className="flex w-full items-center justify-center gap-2 rounded-md border border-outline-variant/60 bg-surface-low px-3 py-2 text-sm font-medium text-foreground/75 transition-colors hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
              >
                <RefreshCw className={`h-4 w-4 ${historyState === 'loading' ? 'animate-spin' : ''}`} />
                刷新会话列表
              </button>
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              {historyResults.length > 0 && (
                <section className="space-y-2 border-b border-outline-variant/40 pb-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-foreground/55">搜索结果</h3>
                    <button
                      type="button"
                      onClick={() => setHistoryResults([])}
                      className="text-xs text-foreground/55 hover:text-foreground"
                    >
                      清除
                    </button>
                  </div>
                  {historyResults.map((result) => {
                    const snippet = sanitizeChatVisibleText(
                      result.snippet.replace(/<\/?mark>/g, ''),
                      '搜索命中内容已隐藏，避免显示内部配置或本地路径。',
                      { maxLength: 180 },
                    );
                    return (
                      <div
                        key={`${result.conversation_id}:${result.node_id}`}
                        className="rounded-md border border-outline-variant/60 bg-surface-low p-3"
                      >
                        <button
                          type="button"
                          onClick={() => handleResumeSession(result.conversation_id)}
                          disabled={historyState === 'loading' || chatState === 'responding'}
                          className="block w-full text-left text-sm text-foreground/85 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <span className="mb-1 block text-[11px] text-foreground/45">搜索命中</span>
                          <span className="line-clamp-2">{snippet}</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleForkFromResult(result)}
                          disabled={historyState === 'loading' || chatState === 'responding'}
                          className="mt-2 inline-flex items-center gap-1 rounded-md border border-outline-variant/60 px-2 py-1 text-xs text-foreground/65 transition-colors hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <GitFork className="h-3.5 w-3.5" />
                          从这里分叉
                        </button>
                      </div>
                    );
                  })}
                </section>
              )}
              {historyState === 'loading' && sessions.length === 0 ? (
                <div className="py-8 text-center text-sm text-foreground/55">正在加载会话…</div>
              ) : sessions.length === 0 ? (
                <div className="py-8 text-center text-sm text-foreground/55">
                  {historyMode === 'archived' ? '暂无归档会话' : '暂无保存的会话'}
                </div>
              ) : (
                renderSessionGroups(false)
              )}
            </div>
          </aside>
        </div>
      )}

      {readerInCenter ? (
        <section aria-label="中间栏本文献阅读器" className="min-h-0 flex-1 p-3">
          {renderEmbeddedReader()}
        </section>
      ) : centerTab === 'discussion' ? (
        <DialogDiscussionWorkbench
          launchState={discussionLaunchState}
          onHistoryChanged={() => {
            void refreshSessions(historyMode, { surfaceError: false });
          }}
        />
      ) : (
        chatPanel
      )}

      {/* Error banner */}
      {errorMessage && (
        <div className="px-6 py-3 bg-red-50 border-t border-red-200">
          <div className="flex items-center justify-between">
            <p className="text-sm text-red-800">{errorMessage}</p>
            <button
              type="button"
              onClick={() => setErrorMessage(null)}
              className="text-sm text-red-600 hover:text-red-800 font-medium"
            >
              关闭
            </button>
          </div>
        </div>
      )}

      </section>
      {graphExplorerOpen && evidenceGraphPayload ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="dialog-graph-explorer-title"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setGraphExplorerOpen(false);
            }
          }}
        >
          <section className="flex h-[min(880px,calc(100vh-40px))] w-[min(1320px,calc(100vw-40px))] min-w-0 flex-col overflow-hidden rounded-lg border border-outline-variant/70 bg-surface-lowest shadow-2xl">
            <header className="flex shrink-0 items-center justify-between gap-3 border-b border-outline-variant/60 px-4 py-3">
              <div className="min-w-0">
                <h2 id="dialog-graph-explorer-title" className="truncate text-sm font-semibold text-foreground">
                  当前上下文图谱
                </h2>
                <p className="text-[11px] text-foreground/50">
                  {evidenceGraphStats.evidence} 条证据 · {evidenceGraphStats.materials} 篇材料 · {evidenceGraphStats.edges} 条关系
                </p>
              </div>
              <button
                type="button"
                onClick={() => setGraphExplorerOpen(false)}
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-low text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
                aria-label="关闭图谱工作台"
                title="关闭图谱工作台"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </header>
            <div className="min-h-0 flex-1 p-3">
              <WikiGraphSegmentedView
                payload={evidenceGraphPayload}
                domain="answer"
                projectId={effectiveProjectId || null}
                onNavigateTarget={handleGraphNavigateTarget}
                variant="explorer"
                selectedDimensions={graphSelectedDimensions}
                onChangeSelectedDimensions={setGraphSelectedDimensions}
              />
            </div>
          </section>
        </div>
      ) : null}
      {contextRailOpen && (
        <>
        <button
          type="button"
          onPointerDown={(event) => handlePaneResizeStart('context', event)}
          className="dialog-divider hidden h-full w-2 shrink-0 cursor-col-resize items-center justify-center border-l border-outline-variant/30 text-foreground/30 transition-colors hover:bg-primary/10 hover:text-primary focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary/40 lg:flex"
          aria-label="调整上下文栏宽度"
          title="拖动调整上下文栏宽度"
        >
          <span className="h-10 w-px rounded bg-current" />
        </button>
        <aside
          style={{ width: paneWidths.context }}
          className="dialog-rail hidden h-full min-h-0 shrink-0 flex-col border-l lg:flex"
        >
          <div className="dialog-band flex shrink-0 items-center gap-2 px-3 py-2">
            {/* B6 (2026-06-13): contextRailTabs 实际有 4-6 个（读阅模式多出 2 个），
                之前写死 grid-cols-3 导致第 4 个折到第二行（用户截图证据）。
                改成 inline-style grid-template-columns 按运行时实际数量等分。 */}
            <div
              className="grid min-w-0 flex-1 gap-1 rounded-md border border-outline-variant/50 bg-surface-low p-1"
              style={{ gridTemplateColumns: `repeat(${contextRailTabs.length}, minmax(0, 1fr))` }}
            >
              {contextRailTabs.map((tab) => {
                const Icon = tab.icon;
                const selected = contextRailTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setContextRailTab(tab.id)}
                    className={`inline-flex min-h-8 items-center justify-center gap-1 rounded px-1.5 text-[11px] font-medium transition-colors ${
                      selected
                        ? 'bg-primary text-primary-foreground'
                        : 'text-foreground/60 hover:bg-surface-high hover:text-foreground'
                    }`}
                    aria-pressed={selected}
                    aria-label={tab.label}
                    title={tab.label}
                  >
                    <Icon className="h-3.5 w-3.5" aria-hidden />
                    <span className="truncate">{tab.label}</span>
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              onClick={() => setContextRailOpen(false)}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-low text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
              aria-label="收起资料栏"
              title="收起资料栏"
            >
              <PanelRightClose className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className={`min-h-0 flex-1 ${
            contextRailTab === 'chat' || contextRailTab === 'discussion' || contextRailTab === 'graph'
              ? 'flex flex-col overflow-hidden p-3'
              : 'overflow-y-auto p-3'
          }`}>
            {renderContextRailContent()}
          </div>
        </aside>
        </>
      )}
    </div>
  );
}
