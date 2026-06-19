import axios from 'axios';
import { useState, useEffect, useMemo, useRef, useCallback, lazy, Suspense, type PointerEvent as ReactPointerEvent } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import {
  Archive,
  BookOpen,
  FolderKanban,
  GitFork,
  Globe2,
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
} from 'lucide-react';
import { Conversation } from '@/components/chat/Conversation';
import { buildSuggestedQuestions, type SuggestedQuestion } from '@/components/chat/suggestedQuestions';
import { DiscussionPanel } from '@/components/DiscussionPanel';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { formatChatVisibleError, sanitizeChatVisibleText } from '@/components/chat/chatDisplay';
import type { ChatAttachment, ChatInputSubmitPayload } from '@/components/chat/ChatInput';
import type {
  ChatJointRecallDiagnostics,
  ChatMessageData,
  ChatMessageDiagnostics,
  ChatRetrievalDiagnostics,
} from '@/components/chat/MessageRenderer';
import type { EvidenceRefLike } from '@/components/evidence/EvidencePill';
import type { GraphNavigateTarget } from '@/components/graph/GraphPayloadViewer';
import { WikiGraphSegmentedView } from '@/components/graph/WikiGraphSegmentedView';
import type { GraphPayloadV0 } from '@/components/graph/payloadToRf';
import type { ReasoningDimension } from '@/components/graph/dimensionGraph';
import { PdfTabStrip } from '@/components/PdfViewer/PdfTabStrip';
import type { PdfSelectionAnchor } from '@/components/PdfViewer/PdfViewer';
import { getAnnotations, type Highlight, type Note as AnnotationNote } from '@/services/annotationApi';
import { smartReadDialogScope, useSmartRead } from '@/contexts/SmartReadContext';
import { usePdfTabs } from '@/contexts/PdfTabsContext';
import {
  artifactContentRecord,
  findLatestArtifact,
  runBackgroundJob,
} from '@/services/backgroundJobRunner';
import { getWritingRuntimeClient } from '@/services/runtimeClient';
import type { WritingJob } from '@/types/runtime';
import {
  listChatSessions,
  deleteChatSession,
  bulkDeleteChatSessions,
  archiveChatSession,
  restoreChatSession,
  forkChatHistoryConversation,
  resumeChatSession,
  searchChatHistory,
  type ContextTier,
  type CurrentPdfContext,
  type IntelligentChatResponse,
  type ChatSessionSummary,
  type ChatHistorySearchResult,
  type ChatResumeMessage,
  type TokenUsage,
} from '@/services/intelligentChatApi';
import { backendTierForCostTier, loadSmartReadCostTier } from '@/services/smartReadTiers';
import { useWriting } from '@/contexts/WritingContext';
import { useProjectReasoningBiasState } from '@/hooks/useProjectReasoningBiasState';
import { getWritingBackendService } from '@/services/writingBackend';
import type { ProjectChunkResource, WritingMaterialResource, WritingProject } from '@/types/resources';
import { getApiBaseUrl } from '@/services/apiBaseUrl';
import {
  encodePdfBboxParam,
  isPdfBboxUnit,
  normalizePdfUrlBbox,
  parsePdfBboxSearchParam,
  toPdfHighlightRect,
  type PdfBbox,
  type PdfBboxUnit,
} from '@/lib/pdfAnchor';
import {
  type DiscussionDefaults,
  DEFAULT_DISCUSSION_DEFAULTS,
  normalizeDiscussionDefaults,
} from '@/services/discussionDefaults';

const UNIFIED_DIALOG_MODE = 'literature_qa' as const;
const UNIFIED_INPUT_PLACEHOLDER = '围绕当前项目材料提问…';
const UNIFIED_EMPTY_HINT = '提问后会结合当前项目材料、证据和上下文生成回答。';
const DISCUSSION_SESSION_SOURCE = 'multi_agent_discussion';
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
const dialogAbortControllers = new Map<string, AbortController>();
const dialogActiveJobsByScope = new Map<string, string>();
const dialogRequestStartedAtByScope = new Map<string, number>();

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  tierUsed?: ContextTier;
  contextMetadata?: IntelligentChatResponse['context_metadata'];
  evidenceRefs?: IntelligentChatResponse['evidence_refs'];
  actualSamplingParams?: IntelligentChatResponse['actual_sampling_params'];
  tokensUsed?: TokenUsage;
  retrievalDiagnostics?: ChatRetrievalDiagnostics;
  timestamp: Date;
  insufficientContext?: boolean;
  status?: ChatMessageData['status'];
}

type ChatState = 'ready' | 'responding' | 'error' | 'unavailable';
type HistoryState = 'idle' | 'loading' | 'error';
type SearchState = 'idle' | 'loading' | 'error';
type HistoryMode = 'recent' | 'archived';
type DialogContextScope = 'paper' | 'project' | 'workspace';
type DialogWorkbenchMode = 'chat' | 'discussion';
type DialogCenterTab = 'chat' | 'discussion' | 'reader';
type DialogContextRailTab = 'chat' | 'discussion' | 'paper' | 'project' | 'graph' | 'notes';
type DiscussionEnhancementIntent = 'reading' | 'writing' | 'research';
type ProjectMaterialsState = 'idle' | 'loading' | 'error';
type AnnotationNotesState = 'idle' | 'loading' | 'error';
type SuggestedQuestionState = 'idle' | 'loading' | 'error';

interface DialogPdfSelectionState {
  materialId: string;
  page: number;
  selectedText: string;
  bbox: PdfBbox | null;
  bboxUnit: PdfBboxUnit | null;
}

interface BuildDialogCurrentPdfContextInput {
  materialId?: string | null;
  page?: number | null;
  chunkId?: string | null;
  selectedText?: string | null;
  bbox?: readonly number[] | null;
  bboxUnit?: PdfBboxUnit | null;
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

function readRecordStringArray(record: Record<string, unknown>, key: string): string[] | undefined {
  const value = record[key];
  if (!Array.isArray(value)) return undefined;
  const strings = value.filter((item): item is string => typeof item === 'string');
  return strings.length > 0 ? strings : undefined;
}

function coerceContextMetadata(value: unknown): IntelligentChatResponse['context_metadata'] | undefined {
  if (!isRecord(value) || !Array.isArray(value.chunks)) return undefined;
  const chunks = value.chunks.flatMap((chunk, index) => {
    if (!isRecord(chunk)) return [];
    const source = readRecordString(chunk, 'source') ?? '来源材料';
    const content = readRecordString(chunk, 'content') ?? '';
    return [{
      index: readRecordNumber(chunk, 'index') ?? index + 1,
      source,
      content,
      relevance_score: readRecordNumber(chunk, 'relevance_score'),
      chunk_id: readRecordStringOrNull(chunk, 'chunk_id'),
      material_id: readRecordStringOrNull(chunk, 'material_id'),
      title: readRecordStringOrNull(chunk, 'title'),
      section_title: readRecordStringOrNull(chunk, 'section_title'),
      page: readRecordPage(chunk, 'page'),
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

function coerceEvidenceRefs(value: unknown): IntelligentChatResponse['evidence_refs'] | undefined {
  if (!Array.isArray(value)) return undefined;
  const refs = value.flatMap((item): NonNullable<IntelligentChatResponse['evidence_refs']> => {
    if (!isRecord(item)) return [];
    const chunkId = readRecordString(item, 'chunk_id') ?? readRecordString(item, 'ref_id');
    if (!chunkId) return [];
    const sourceType = readRecordString(item, 'source_type');
    const sourceTitle = readRecordStringOrNull(item, 'source_title');
    const source = readRecordString(item, 'source') ?? sourceTitle ?? (sourceType === 'wiki' ? 'Wiki 记忆' : '项目证据');
    const text = readRecordString(item, 'text') ?? readRecordString(item, 'summary') ?? '';
    const quote = readRecordString(item, 'quote') ?? text;
    return [{
      chunk_id: chunkId,
      material_id: readRecordStringOrNull(item, 'material_id') ?? undefined,
      source,
      text,
      quote,
      label: readRecordString(item, 'label'),
      score: readRecordNonNegativeNumber(item, 'score') ?? readRecordNonNegativeNumber(item, 'lexical_score'),
      source_labels: readRecordStringArray(item, 'source_labels'),
      page: readRecordPage(item, 'page'),
      bbox: Array.isArray(item.bbox) ? item.bbox.filter((part): part is number => typeof part === 'number' && Number.isFinite(part)) : null,
      bbox_unit: isPdfBboxUnit(item.bbox_unit) ? item.bbox_unit : null,
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
    }];
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

function coerceRetrievalDiagnostics(value: unknown): ChatRetrievalDiagnostics | undefined {
  if (!isRecord(value)) return undefined;
  const diagnostics: ChatRetrievalDiagnostics = {
    retrieval_method: readRecordString(value, 'retrieval_method'),
    embedding_status: readRecordString(value, 'embedding_status'),
    rerank_status: readRecordString(value, 'rerank_status'),
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
  return {
    tierUsed,
    contextMetadata,
    evidenceRefs,
    actualSamplingParams,
    tokensUsed,
    retrievalDiagnostics,
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
    timestamp: new Date(),
    insufficientContext: patch.insufficientContext,
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
  const chatMessage: ChatMessage = {
    id: message.id,
    role: message.role,
    content: message.content,
    tierUsed: message.tier_used ?? undefined,
    contextMetadata: message.context_metadata ?? undefined,
    evidenceRefs: message.evidence_refs ?? undefined,
    tokensUsed: message.tokens_used ?? undefined,
    retrievalDiagnostics: coerceRetrievalDiagnostics((message as { retrieval_diagnostics?: unknown }).retrieval_diagnostics),
    timestamp: parseChatTimestamp(message.timestamp),
    insufficientContext: message.role === 'assistant' && !message.context_metadata,
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
    content: message.content,
    tierUsed: diagnostics?.tier,
    contextMetadata: diagnostics?.context
      ? {
          chunks: diagnostics.context.chunks?.map((chunk) => ({
            index: chunk.index,
            source: chunk.source,
            content: chunk.content,
            relevance_score: chunk.relevance_score,
          })) ?? [],
          truncated: false,
        }
      : undefined,
    evidenceRefs: message.evidence?.map((ref) => ({
      chunk_id: ref.chunk_id ?? ref.evidence_id ?? 'legacy-evidence',
      material_id: ref.material_id ?? undefined,
      source: ref.source ?? '证据',
      text: ref.text ?? '',
      quote: ref.text ?? '',
      page: ref.page ?? undefined,
      bbox: ref.bbox ?? null,
      bbox_unit: ref.bbox_unit ?? null,
      source_kind: ref.source_kind ?? 'local',
      source_type: ref.source_type ?? 'project',
      source_title: ref.source_title ?? null,
      source_path: ref.source_path ?? null,
      joint_score: ref.joint_score ?? null,
    })),
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
    timestamp: message.timestamp ? parseChatTimestamp(message.timestamp) : new Date(),
    insufficientContext: diagnostics?.insufficient,
    status: message.status,
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
  if (normalized === 'workspace' || normalized === 'all') return 'workspace';
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
  contextScope: DialogContextScope,
  projectId: string,
  _materialId: string,
): string {
  if (contextScope === 'workspace') return smartReadDialogScope('workspace');
  return smartReadDialogScope(projectId || 'default');
}

function buildDialogStorageScope(
  contextScope: DialogContextScope,
  projectId: string,
  _materialId: string,
): string {
  if (contextScope === 'workspace') return 'workspace';
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

type DialogGraphNode = GraphPayloadV0['nodes'][number];
type DialogGraphEdge = GraphPayloadV0['edges'][number];
type DialogGraphEvidenceRef = NonNullable<ChatMessageData['evidence']>[number];

function hashGraphText(text: string): string {
  let hash = 0;
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash * 31 + text.charCodeAt(index)) | 0;
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
}

function lastUserQuestion(messages: ChatMessageData[]): string {
  const found = [...messages].reverse().find((message) => message.role === 'user' && message.content.trim());
  return sanitizeChatVisibleText(found?.content ?? '', '当前研读问题', { maxLength: 88 });
}

function evidenceGraphId(evidence: DialogGraphEvidenceRef, index: number): string {
  const materialId = String(evidence.material_id ?? '').trim();
  const chunkId = String(evidence.chunk_id ?? '').trim();
  if (materialId && chunkId) return `evidence:${materialId}:${chunkId}`;
  if (materialId) return `evidence:${materialId}:${index}`;
  const source = String(evidence.source ?? '').trim();
  const text = String(evidence.text ?? '').trim();
  return `evidence:external:${hashGraphText(`${source}|${text}|${index}`)}`;
}

function graphEvidenceText(evidence: DialogGraphEvidenceRef): string {
  return sanitizeChatVisibleText(
    String(evidence.text ?? evidence.source ?? '').trim(),
    '证据',
    { maxLength: 96 },
  );
}

function graphEvidenceLabel(evidence: DialogGraphEvidenceRef, index: number): string {
  const source = sanitizeChatVisibleText(
    String(evidence.source ?? '').trim(),
    '',
    { maxLength: 54 },
  );
  if (source) {
    return typeof evidence.page === 'number' && evidence.page > 0
      ? `${source} · p.${evidence.page}`
      : source;
  }
  const text = graphEvidenceText(evidence);
  return text === '证据' ? `证据 ${index + 1}` : text;
}

function materialNodeLabel(evidence: DialogGraphEvidenceRef, index: number): string {
  const source = sanitizeChatVisibleText(
    String(evidence.source ?? '').trim(),
    '',
    { maxLength: 54 },
  );
  if (source) return source;
  return `文献 ${index + 1}`;
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

function graphEvidenceRef(evidence: DialogGraphEvidenceRef): DialogGraphNode['evidence_refs'] {
  const materialId = String(evidence.material_id ?? '').trim();
  if (!materialId) return null;
  return [{
    material_id: materialId,
    chunk_id: evidence.chunk_id ?? null,
    page: typeof evidence.page === 'number' && evidence.page > 0 ? evidence.page : null,
    text: graphEvidenceText(evidence),
    score: null,
  }];
}

function buildDialogEvidenceGraphPayload(messages: ChatMessageData[]): GraphPayloadV0 | null {
  const claimId = 'dialog-claim';
  const nodes = new Map<string, DialogGraphNode>();
  const edges = new Map<string, DialogGraphEdge>();
  const materialEvidenceCounts = new Map<string, number>();

  nodes.set(claimId, {
    id: claimId,
    label: lastUserQuestion(messages),
    type: 'claim',
    material_id: null,
    source_ref: null,
    evidence_refs: null,
    confidence: null,
    metadata: { surface: 'dialog', reasoning_dimension: 'question' },
  });

  let evidenceIndex = 0;
  for (const message of messages) {
    if (message.role !== 'assistant' || !message.evidence || message.evidence.length === 0) continue;
    for (const evidence of message.evidence) {
      const evidenceId = evidenceGraphId(evidence, evidenceIndex);
      const evidenceRefs = graphEvidenceRef(evidence);
      const materialId = String(evidence.material_id ?? '').trim();
      if (!nodes.has(evidenceId)) {
        nodes.set(evidenceId, {
          id: evidenceId,
          label: graphEvidenceLabel(evidence, evidenceIndex),
          type: 'evidence',
          material_id: materialId || null,
          source_ref: materialId
            ? {
                material_id: materialId,
                chunk_id: evidence.chunk_id ?? null,
                page: typeof evidence.page === 'number' && evidence.page > 0 ? evidence.page : null,
                bbox: evidence.bbox ?? null,
              }
            : null,
          evidence_refs: evidenceRefs,
          confidence: null,
          metadata: {
            source_kind: evidence.source_kind ?? 'local',
            evidence_text: graphEvidenceText(evidence),
            reasoning_dimension: 'evidence',
          },
        });
      }

      if (materialId) {
        const materialNodeId = `material:${materialId}`;
        const previousCount = materialEvidenceCounts.get(materialNodeId) ?? 0;
        materialEvidenceCounts.set(materialNodeId, previousCount + 1);
        const existingMaterial = nodes.get(materialNodeId);
        if (existingMaterial) {
          nodes.set(materialNodeId, {
            ...existingMaterial,
            label: `${existingMaterial.label.replace(/\s·\s\d+\s条证据$/, '')} · ${previousCount + 1} 条证据`,
            evidence_refs: [
              ...(existingMaterial.evidence_refs ?? []),
              ...(evidenceRefs ?? []),
            ],
          });
        } else {
          nodes.set(materialNodeId, {
            id: materialNodeId,
            label: `${materialNodeLabel(evidence, evidenceIndex)} · 1 条证据`,
            type: 'material',
            material_id: materialId,
            source_ref: {
              material_id: materialId,
              chunk_id: evidence.chunk_id ?? null,
              page: typeof evidence.page === 'number' && evidence.page > 0 ? evidence.page : null,
              bbox: evidence.bbox ?? null,
            },
            evidence_refs: evidenceRefs,
            confidence: null,
            metadata: { evidence_count: 1, reasoning_dimension: 'evidence' },
          });
        }
        const evidenceToMaterialId = `edge:${evidenceId}->${materialNodeId}`;
        if (!edges.has(evidenceToMaterialId)) {
          edges.set(evidenceToMaterialId, {
            id: evidenceToMaterialId,
            source: evidenceId,
            target: materialNodeId,
            relation: 'cites',
            material_id: materialId,
            source_ref: null,
            evidence_refs: evidenceRefs,
            confidence: null,
            metadata: null,
          });
        }
        const materialToClaimId = `edge:${materialNodeId}->${claimId}`;
        if (!edges.has(materialToClaimId)) {
          edges.set(materialToClaimId, {
            id: materialToClaimId,
            source: materialNodeId,
            target: claimId,
            relation: 'supports',
            material_id: materialId,
            source_ref: null,
            evidence_refs: null,
            confidence: null,
            metadata: null,
          });
        }
      } else {
        const evidenceToClaimId = `edge:${evidenceId}->${claimId}`;
        if (!edges.has(evidenceToClaimId)) {
          edges.set(evidenceToClaimId, {
            id: evidenceToClaimId,
            source: evidenceId,
            target: claimId,
            relation: 'related',
            material_id: null,
            source_ref: null,
            evidence_refs: null,
            confidence: null,
            metadata: null,
          });
        }
      }
      evidenceIndex += 1;
    }
  }

  if (nodes.size <= 1) return null;

  return {
    version: 'v0',
    scope: { kind: 'question', ref: lastUserQuestion(messages) },
    updated_at: new Date().toISOString(),
    nodes: Array.from(nodes.values()),
    edges: Array.from(edges.values()),
  };
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
  const page = normalizeDialogReaderPage(input.page);
  const selectedText = normalizeDialogSelectionText(input.selectedText);
  const bboxUnit = input.bboxUnit ?? 'normalized_ratio';
  const bbox = normalizePdfUrlBbox(input.bbox ?? null, bboxUnit);
  const chunkId = normalizeMaterialId(input.chunkId ?? '');
  if (!page && !selectedText && !chunkId) return undefined;
  return {
    material_id: materialId,
    ...(page ? { page } : {}),
    ...(chunkId ? { chunk_id: chunkId } : {}),
    ...(bbox ? { bbox, bbox_unit: 'normalized_ratio' } : {}),
    ...(selectedText ? { selected_text: selectedText } : {}),
    context_kind: selectedText ? 'selection' : bbox || chunkId ? 'deep_link' : 'reader_page',
    source_labels: [
      'dialog_smart_read',
      selectedText ? 'pdf_selection' : 'pdf_reader_page',
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
    content: message.content,
    evidence: message.evidenceRefs?.map((ref) => ({
      evidence_id: ref.chunk_id,
      chunk_id: ref.chunk_id,
      material_id: ref.material_id ?? undefined,
      source: ref.source,
      quote: ref.quote || ref.text,
      text: ref.text || ref.quote,
      score: ref.score ?? undefined,
      page: normalizeEvidencePage(ref.page),
      bbox: ref.bbox ?? null,
      bbox_unit: ref.bbox_unit ?? null,
      source_hint: ref.source_hint ?? undefined,
      source_labels: ref.source_labels,
      source_kind: ref.source_kind ?? 'local',
      source_type: ref.source_type ?? 'project',
      source_title: ref.source_title ?? null,
      source_path: ref.source_path ?? null,
      joint_score: ref.joint_score ?? null,
    })),
    timestamp: message.timestamp.toISOString(),
    status: message.status,
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

function EnhancementMenu({
  disabled,
  onSelect,
}: {
  disabled?: boolean;
  onSelect: (intent: DiscussionEnhancementIntent) => void;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

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

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={disabled}
        aria-haspopup="true"
        aria-expanded={open}
        className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-2.5 text-[11px] font-medium text-foreground/70 transition-colors hover:border-primary/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-45"
        title="用多智能体讨论增强当前研读"
      >
        <Sparkles className="h-3.5 w-3.5" aria-hidden />
        增强
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-60 overflow-hidden rounded-md border border-outline-variant/60 bg-surface-lowest p-1 shadow-lg">
          {ENHANCEMENT_MENU_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  setOpen(false);
                  onSelect(item.id);
                }}
                className="flex w-full items-start gap-2 rounded px-2 py-1.5 text-left transition-colors hover:bg-primary/8"
              >
                <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
                <span className="min-w-0">
                  <span className="block text-xs font-medium text-foreground/80">{item.label}</span>
                  <span className="block text-[11px] leading-snug text-foreground/50">{item.description}</span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
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
  const [embeddedReaderTarget, setEmbeddedReaderTarget] = useState<{
    page?: number;
    bbox?: number[];
    bboxUnit?: PdfBboxUnit | null;
    chunkId?: string;
    nonce: number;
  }>({ nonce: 0 });
  const [embeddedReaderPage, setEmbeddedReaderPage] = useState<number | null>(null);
  const [currentPdfSelection, setCurrentPdfSelection] = useState<DialogPdfSelectionState | null>(null);
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
  const evidenceGraphPayload = useMemo(
    () => buildDialogEvidenceGraphPayload(conversationMessages),
    [conversationMessages],
  );
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
  const urlReaderBbox = parsePdfBboxSearchParam(searchParams.get('bbox'));
  const effectiveReaderPage = embeddedReaderTarget.page
    ?? embeddedReaderPage
    ?? urlReaderPage
    ?? persistedPinnedPdfView?.page
    ?? null;
  const effectiveReaderBbox = embeddedReaderTarget.bbox ?? urlReaderBbox ?? undefined;
  const effectiveReaderBboxUnit = embeddedReaderTarget.bboxUnit ?? (urlReaderBbox ? 'normalized_ratio' : null);
  const effectiveReaderChunkId = embeddedReaderTarget.chunkId ?? urlReaderChunkId ?? undefined;
  const embeddedReaderHighlights = useMemo<Highlight[]>(() => {
    if (!effectiveReaderPage) return [];
    const rect = toPdfHighlightRect(effectiveReaderBbox, effectiveReaderBboxUnit);
    if (!rect) return [];
    return [{
      page: effectiveReaderPage,
      text: '当前跳转证据位置',
      color: '#60A5FA',
      rects: [rect],
    }];
  }, [effectiveReaderBbox, effectiveReaderBboxUnit, effectiveReaderPage]);
  const readerTabAvailable = !!pinnedMaterialId && pinnedLooksLikePdf;
  const readerInCenter = readerTabAvailable;
  const projectMaterialCount = projectMaterials.length;
  const annotationNoteCount = annotationNotes.length;
  const requestProjectId = dialogContextScope === 'workspace' ? undefined : effectiveProjectId || undefined;
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
  const activeJobIdRef = useRef<string | null>(dialogActiveJobsByScope.get(smartReadScope) ?? null);
  const isMountedRef = useRef(true);
  const restoringSessionIdRef = useRef<string | null>(null);
  const taskCenterNavigationPendingRef = useRef(false);
  const dialogShellRef = useRef<HTMLDivElement | null>(null);
  const previousPinnedMaterialIdRef = useRef('');
  const projectReasoningBias = useProjectReasoningBiasState(activeProjectId);
  const defaultProjectBiasEnabled = projectReasoningBias.isEnabledForSurface('chat_generation');
  const [projectBiasEnabled, setProjectBiasEnabled] = useState(defaultProjectBiasEnabled);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
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
    if (pinnedMaterialId && previousPinnedMaterialIdRef.current !== pinnedMaterialId) {
      setContextRailTab(
        pinnedLooksLikePdf
          ? urlCenterTab === 'discussion' ? 'discussion' : 'chat'
          : 'paper',
      );
      setEmbeddedReaderTarget({ nonce: 0 });
      setEmbeddedReaderPage(null);
      setCurrentPdfSelection(null);
    }
    previousPinnedMaterialIdRef.current = pinnedMaterialId;
  }, [pinnedLooksLikePdf, pinnedMaterialId, urlCenterTab]);

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

  const handleResumeSession = async (nextSessionId: string, sessionHint?: ChatSessionSummary) => {
    const normalizedSessionId = nextSessionId.trim();
    if (!normalizedSessionId || chatState === 'responding' || restoringSessionIdRef.current) return;
    restoringSessionIdRef.current = normalizedSessionId;
    setHistoryState('loading');
    setHistoryErrorMessage(null);
    try {
      const response = await resumeChatSession({ session_id: normalizedSessionId, limit: 100 });
      const restoredMessages = response.messages.map(toChatMessage).map(mapDialogMessageToChatData);
      const targetProjectId = normalizeProjectId(response.project_id ?? sessionHint?.project_id);
      const targetProjectForScope = targetProjectId || effectiveProjectId;
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
    const activeJobId = activeJobIdRef.current ?? dialogActiveJobsByScope.get(smartReadScope);
    if (activeJobId) {
      void getWritingRuntimeClient().cancelJob(activeJobId).catch(() => undefined);
    }
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
    conversationMessagesRef.current = nextMessages;
    setConversation(smartReadScope, nextMessages);
    setInputValue(message.content);
    setSessionId(undefined);
    setErrorMessage(null);
    setIsUnavailable(false);
    setChatState('ready');
  };

  const handleForkMessage = (message: ChatMessageData) => {
    if (chatState === 'responding') return;
    const index = conversationMessagesRef.current.findIndex((item) => item.id === message.id);
    if (index < 0) return;
    const nextMessages = conversationMessagesRef.current.slice(0, index + 1);
    conversationMessagesRef.current = nextMessages;
    setConversation(smartReadScope, nextMessages);
    setSessionId(undefined);
    setErrorMessage(null);
    setIsUnavailable(false);
    setChatState('ready');
  };

  const handleSendMessage = async (payload: ChatInputSubmitPayload) => {
    const query = payload.text.trim();
    if (!query || chatState === 'responding') return;
    const images: ChatAttachment[] = payload.attachmentsEnabled ? payload.attachments : [];
    const selectedTier = loadSmartReadCostTier('medium');

    const userMessage: ChatMessageData = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: query,
      timestamp: new Date().toISOString(),
    };
    const assistantId = `assistant-${Date.now()}`;
    const assistantMessage: ChatMessageData = {
      id: assistantId,
      role: 'assistant',
      content: 'AI 思考中…',
      timestamp: new Date().toISOString(),
      status: 'streaming',
      metadata: {
        diagnostics: {
          tier: backendTierForCostTier(selectedTier),
        },
      },
    };

    const commitMessages = (nextMessages: ChatMessageData[]) => {
      conversationMessagesRef.current = nextMessages;
      setConversation(smartReadScope, nextMessages);
    };
    const updateAssistantMessage = (patch: Partial<ChatMessageData>): ChatMessageData => {
      const existing = conversationMessagesRef.current.find((message) => message.id === assistantId) ?? assistantMessage;
      const nextMessage: ChatMessageData = {
        ...existing,
        ...patch,
        metadata: patch.metadata ?? existing.metadata,
      };
      commitMessages(
        replaceOrAppendChatData(conversationMessagesRef.current, nextMessage),
      );
      return nextMessage;
    };

    commitMessages([
      ...conversationMessagesRef.current,
      userMessage,
      assistantMessage,
    ]);
    setInputValue('');
    setChatState('responding');
    focusDialogChatPane();
    const startedAt = Date.now();
    dialogRequestStartedAtByScope.set(smartReadScope, startedAt);
    setRequestStartedAt(startedAt);
    setErrorMessage(null);
    setIsUnavailable(false);

    const cleanUpActiveJob = () => {
      if (dialogActiveJobsByScope.get(smartReadScope) === activeJobIdRef.current) {
        dialogActiveJobsByScope.delete(smartReadScope);
      }
      activeJobIdRef.current = null;
    };

    try {
      const abortController = new AbortController();
      activeAbortControllerRef.current = abortController;
      dialogAbortControllers.set(smartReadScope, abortController);
      const existingSessionId = sessionId ?? conversation.sessionId ?? undefined;
      const selectionForRequest = currentPdfSelection?.materialId === requestMaterialId
        ? currentPdfSelection
        : null;
      const currentPdfContext = buildDialogCurrentPdfContext({
        materialId: requestMaterialId,
        page: selectionForRequest?.page ?? effectiveReaderPage,
        chunkId: effectiveReaderChunkId,
        selectedText: selectionForRequest?.selectedText,
        bbox: selectionForRequest?.bbox ?? effectiveReaderBbox ?? null,
        bboxUnit: selectionForRequest?.bboxUnit ?? effectiveReaderBboxUnit ?? null,
      });
      if (selectionForRequest) {
        setCurrentPdfSelection(null);
      }
      const jobResult = await runBackgroundJob({
        sessionTitle: '智能研读',
        sessionMetadata: {
          source: 'dialog_smart_read',
          project_id: effectiveProjectId || undefined,
          material_id: pinnedMaterialId || undefined,
          current_pdf_context: currentPdfContext,
          scope: dialogContextScope,
        },
        request: {
          kind: 'smart_read',
          input_text: query,
          session_id: existingSessionId,
          metadata: {
            chat_session_id: existingSessionId,
            project_id: requestProjectId,
            material_id: requestMaterialId,
            tier: backendTierForCostTier(selectedTier),
            mode: UNIFIED_DIALOG_MODE,
            current_pdf_context: currentPdfContext,
            images: images.length > 0 ? images : undefined,
            project_reasoning_bias_enabled: defaultProjectBiasEnabled ? projectBiasEnabled : undefined,
          },
          tags: ['dialog', 'smart-read'],
        },
        timeoutMs: DIALOG_REQUEST_TIMEOUT_MS,
        signal: abortController.signal,
        onJobCreated: (job: WritingJob) => {
          activeJobIdRef.current = job.job_id;
          dialogActiveJobsByScope.set(smartReadScope, job.job_id);
          updateAssistantMessage({
            content: `AI 正在后台研读，任务已进入任务中心。\n\n任务编号：${job.job_id}`,
            status: 'streaming',
          });
        },
        // B12 (2026-06-13): show backend phase label so the user sees real
        // progress ("TOLF 检索 → Rerank → 分析链 → 生成") instead of staring at
        // a stale "AI 思考中" for 2 minutes. Only updates content when the
        // phase label is present to avoid noisy re-renders.
        onProgress: (tick) => {
          if (!isMountedRef.current) return;
          if (!tick.label) return;
          const percentSuffix = (typeof tick.percent === 'number' && Number.isFinite(tick.percent))
            ? `  ${Math.round(tick.percent)}%`
            : '';
          updateAssistantMessage({
            content: `AI 正在研读：${tick.label}${percentSuffix}`,
            status: 'streaming',
          });
        },
      });
      if (!isMountedRef.current) {
        return;
      }
      if (jobResult.status.status !== 'completed') {
        throw new Error(jobResult.status.error || '智能研读任务未完成。');
      }

      const content = artifactContentRecord(findLatestArtifact(jobResult.artifacts, 'transformed_text'));
      const response = typeof content.response === 'string'
        ? content.response
        : typeof content.text === 'string'
          ? content.text
          : '';
      const nextSessionId = resolveDialogSmartReadChatSessionId(content, existingSessionId);
      const diagnostics = coerceSmartReadResponsePatch(content, backendTierForCostTier(selectedTier));
      const finalContent = response || '回答已生成，但未找到可显示的结果。';
      const finalDiagnostics = buildSmartReadDiagnostics({
        ...diagnostics,
        content: finalContent,
      });
      const finalAssistant = updateAssistantMessage({
        content: finalContent,
        status: 'done',
        metadata: finalDiagnostics ? { diagnostics: finalDiagnostics } : undefined,
        evidence: diagnostics.evidenceRefs as EvidenceRefLike[] | undefined,
      });

      if (nextSessionId && nextSessionId !== sessionId) {
        setSessionId(nextSessionId);
      }
      setConversation(
        smartReadScope,
        replaceOrAppendChatData(conversationMessagesRef.current, finalAssistant),
        { sessionId: nextSessionId },
      );
      setIsUnavailable(false);
      setChatState('ready');
    } catch (error) {
      if (isAbortError(error)) {
        if (!isMountedRef.current) {
          return;
        }
        updateAssistantMessage({
          content: '已停止生成。',
          status: 'done',
        });
        setChatState('ready');
        return;
      }
      if (!isMountedRef.current) {
        return;
      }
      const errorMsg = getChatErrorMessage(error);
      updateAssistantMessage({
        content: `回答失败：${errorMsg}`,
        status: 'error',
      });
      if (isUnavailableError(error)) {
        setIsUnavailable(true);
        setChatState('unavailable');
      } else {
        setErrorMessage(errorMsg);
        setChatState('error');
      }
    } finally {
      cleanUpActiveJob();
      if (dialogAbortControllers.get(smartReadScope) === activeAbortControllerRef.current) {
        dialogAbortControllers.delete(smartReadScope);
      }
      dialogRequestStartedAtByScope.delete(smartReadScope);
      activeAbortControllerRef.current = null;
      if (isMountedRef.current) {
        setRequestStartedAt(null);
      }
    }
  };

  const handleUseSuggestedQuestion = (question: SuggestedQuestion) => {
    if (chatState === 'responding') return;
    focusDialogChatPane();
    setInputValue(question.question);
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
  const emptyHint = useMemo(() => {
    if (dialogContextScope === 'paper' && pinnedMaterialId) {
      return `当前对话优先围绕「${activeMaterialLabel}」检索和回答。`;
    }
    if (dialogContextScope === 'workspace') {
      return '当前对话不限定单篇文献，会按全局可用材料和工具上下文回答。';
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
    navigate(`/workbench/paper/${encodeURIComponent(pinnedMaterialId)}`);
  };
  function writeReaderSearchParams(
    materialId: string,
    options: {
      title?: string;
      page?: number | null;
      chunkId?: string | null;
      bbox?: number[] | null;
      bboxUnit?: PdfBboxUnit | null;
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
    const bboxParam = encodePdfBboxParam(options.bbox ?? null, options.bboxUnit);
    if (bboxParam) nextParams.set('bbox', bboxParam);
    else nextParams.delete('bbox');
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
  function handleOpenMaterialInReader(materialId: string): void {
    const normalizedMaterialId = normalizeMaterialId(materialId);
    if (!normalizedMaterialId) return;
    const material = projectMaterials.find((item) => normalizeMaterialId(item.material_id) === normalizedMaterialId);
    const title = material ? materialTitleLabel(material) : normalizedMaterialId;
    focusMaterialReaderPane(normalizedMaterialId, title);
    writeReaderSearchParams(normalizedMaterialId, { title });
  }
  function handlePdfTabActivate(materialId: string): void {
    const normalizedMaterialId = normalizeMaterialId(materialId);
    if (!normalizedMaterialId) return;
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
    nextParams.delete('tab');
    nextParams.set('scope', effectiveProjectId ? 'project' : 'workspace');
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
    setEmbeddedReaderPage(normalizedPage);
    if (pinnedMaterialId) {
      updatePdfView(pinnedMaterialId, { page: normalizedPage });
    }
  }

  function handleAnalyzeReaderText(text: string, page: number, anchor?: PdfSelectionAnchor): void {
    if (!pinnedMaterialId) return;
    const selectedText = normalizeDialogSelectionText(text);
    if (!selectedText) return;
    const normalizedPage = normalizeDialogReaderPage(page) ?? effectiveReaderPage ?? 1;
    const bbox = combineSelectionRects(anchor?.rects);
    setCurrentPdfSelection({
      materialId: pinnedMaterialId,
      page: normalizedPage,
      selectedText,
      bbox,
      bboxUnit: bbox ? 'normalized_ratio' : null,
    });
    setEmbeddedReaderPage(normalizedPage);
    focusDialogChatPane();
    setInputValue(`请分析当前 PDF 第 ${normalizedPage} 页选中的这段内容：\n\n${selectedText}`);
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
    setGraphExplorerOpen(false);
    setContextRailOpen(true);
    setContextRailTab('graph');
    if (targetMaterialId === pinnedMaterialId) {
      setEmbeddedReaderTarget((previous) => ({
        page: target.page ?? undefined,
        bbox: target.bbox ?? undefined,
        bboxUnit: target.bbox_unit ?? null,
        chunkId: target.chunk_id ?? undefined,
        nonce: previous.nonce + 1,
      }));
      setCenterTab('reader');
      writeReaderSearchParams(targetMaterialId, {
        title: activeMaterialLabel || pinnedMaterialTitle || targetMaterialId,
        page: target.page,
        chunkId: target.chunk_id,
        bbox: target.bbox,
        bboxUnit: target.bbox_unit,
        replace: false,
      });
      return;
    }
    const material = projectMaterials.find((item) => normalizeMaterialId(item.material_id) === targetMaterialId);
    focusMaterialReaderPane(targetMaterialId, material ? materialTitleLabel(material) : targetMaterialId);
    writeReaderSearchParams(targetMaterialId, {
      title: material ? materialTitleLabel(material) : targetMaterialId,
      page: target.page,
      chunkId: target.chunk_id,
      bbox: target.bbox,
      bboxUnit: target.bbox_unit,
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
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="inline-grid grid-cols-3 rounded-md border border-outline-variant/60 bg-surface-lowest p-1">
        {([
          { id: 'paper', label: '本文献', icon: BookOpen, disabled: !pinnedMaterialId },
          { id: 'project', label: '项目文献', icon: FolderKanban, disabled: false },
          { id: 'workspace', label: '全项目', icon: Globe2, disabled: false },
        ] as const).map((option) => {
          const Icon = option.icon;
          const selected = dialogContextScope === option.id;
          return (
            <button
              key={option.id}
              type="button"
              onClick={() => handleContextScopeChange(option.id)}
              disabled={option.disabled || isInputDisabled}
              className={`inline-flex min-h-8 items-center justify-center gap-1.5 rounded px-2.5 text-[11px] font-medium transition-colors ${
                selected
                  ? 'bg-primary text-primary-foreground'
                  : 'text-foreground/60 hover:bg-surface-high hover:text-foreground disabled:hover:bg-transparent'
              } disabled:cursor-not-allowed disabled:opacity-45`}
              aria-pressed={selected}
              title={option.disabled ? '从知识库文献进入后可用' : option.label}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden />
              {option.label}
            </button>
          );
        })}
      </div>
      <div className="flex min-w-0 flex-wrap items-center justify-end gap-2 text-[11px] text-foreground/50">
        <EnhancementMenu
          disabled={isInputDisabled}
          onSelect={(intent) => launchDiscussionEnhancement(intent)}
        />
      </div>
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
                key={`${pinnedMaterialId}:${embeddedReaderTarget.nonce}:${searchParams.get('page') ?? ''}:${searchParams.get('bbox') ?? ''}`}
                url={pinnedPdfUrl}
                materialId={pinnedMaterialId}
                initialPage={effectiveReaderPage ?? undefined}
                highlights={embeddedReaderHighlights}
                notes={annotationNotes}
                className="h-full"
                onAnalyzeText={handleAnalyzeReaderText}
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
                onClick={() => void refreshProjectMaterials({ surfaceError: false })}
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
                projectId={effectiveProjectId || null}
                onNavigateTarget={handleGraphNavigateTarget}
                variant="rail"
                onExpand={handleOpenGraphExplorer}
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

  const chatPanel = (
    <Conversation
      className="min-h-0 flex-1"
      messages={conversationMessages}
      onSubmit={(payload) => void handleSendMessage(payload)}
      projectId={effectiveProjectId}
      inputValue={inputValue}
      onInputValueChange={setInputValue}
      placeholder={inputPlaceholder}
      disabled={isInputDisabled}
      responding={isInputDisabled}
      onStop={handleStopGeneration}
      onEditMessage={handleEditMessage}
      onForkMessage={handleForkMessage}
      submitKey="enter"
      composerRows={3}
      enableAttachments
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
    <div ref={dialogShellRef} className="flex h-full min-h-0 min-w-0 overflow-hidden bg-background">
      {!historyRailCollapsed && (
        <>
      <aside
        style={{ width: paneWidths.history }}
        className="hidden h-full min-h-0 shrink-0 flex-col border-r border-outline-variant/60 bg-surface-lowest lg:flex"
      >
        <div className="border-b border-outline-variant/60 px-4 py-3">
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
            className="hidden h-full w-2 shrink-0 cursor-col-resize items-center justify-center border-r border-outline-variant/30 bg-surface-lowest text-foreground/30 transition-colors hover:bg-primary/10 hover:text-primary focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary/40 lg:flex"
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
        <div className="flex items-center justify-between gap-3 border-b border-outline-variant/60 bg-surface-low px-6 py-3">
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
            className="h-full w-full max-w-md bg-surface-lowest shadow-xl border-l border-outline-variant/60 flex flex-col"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-outline-variant/60 px-5 py-4">
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
          className="hidden h-full w-2 shrink-0 cursor-col-resize items-center justify-center border-l border-outline-variant/30 bg-surface-lowest text-foreground/30 transition-colors hover:bg-primary/10 hover:text-primary focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary/40 lg:flex"
          aria-label="调整上下文栏宽度"
          title="拖动调整上下文栏宽度"
        >
          <span className="h-10 w-px rounded bg-current" />
        </button>
        <aside
          style={{ width: paneWidths.context }}
          className="hidden h-full min-h-0 shrink-0 flex-col border-l border-outline-variant/60 bg-surface-lowest lg:flex"
        >
          <div className="flex shrink-0 items-center gap-2 border-b border-outline-variant/60 px-3 py-2">
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
