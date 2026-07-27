import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  Archive,
  AlertTriangle,
  BookOpenText,
  CheckCircle2,
  ChevronDown,
  Clipboard,
  Copy,
  History,
  Loader2,
  RefreshCw,
  RotateCcw,
  XCircle,
  Unplug,
  Workflow,
} from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { Conversation } from '@/components/chat/Conversation';
import type { ChatMessageData } from '@/components/chat/MessageRenderer';
import { EvidencePill } from '@/components/evidence/EvidencePill';
import { smartReadDialogScope, useSmartRead } from '@/contexts/SmartReadContext';
import { useWriting } from '@/contexts/WritingContext';
import {
  agentSidebarEvidenceToPill,
  createAgentSidebarAnswerRequest,
  getAgentSidebarHealth,
  listAgentSidebarReceipts,
  openAgentSidebarDesktop,
  readAgentSidebarReceipt,
  revalidateAgentSidebarReceipt,
  type AgentSidebarAnswerRequestResponse,
  type AgentSidebarReceiptReadResponse,
  type AgentSidebarReceiptSummary,
  type AgentSidebarEvidenceRef,
  type AgentSidebarRevalidateResponse,
} from '@/services/agentSidebarApi';
import {
  readVisualObservationDetail,
  transitionVisualObservation,
  type VisualObservationDetail,
} from '@/services/visualObservationApi';
import { getWritingBackendService } from '@/services/writingBackend';
import type { WritingProject } from '@/types/resources';
import type {
  VisualObservationFreshnessStatus,
  VisualObservationReference,
  VisualObservationReferenceReviewStatus,
  VisualObservationReviewStatus,
} from '@/types/visualObservation';
import { cn } from '@/lib/utils';
import type { ThemeMode } from '@/hooks/useThemeMode';
import { sanitizeAssistantVisibleContent } from '@/components/chat/chatDisplay';

type ConnectionState = 'checking' | 'ready' | 'degraded' | 'offline';
type AnswerLifecycle = 'idle' | 'running' | 'stopped' | 'saving' | 'saved' | 'stale' | 'revalidating' | 'error';
type EvidenceTone = 'neutral' | 'good' | 'warning' | 'danger';
type ResolvedTheme = 'light' | 'dark';

interface RefreshReceiptOptions {
  selectLatest?: boolean;
  preserveSelection?: boolean;
}

interface EvidenceStatusProjection {
  label: string;
  detail: string;
  tone: EvidenceTone;
}

interface ContinuitySummaryItem {
  key: string;
  label: string;
  detail: string;
  tone: EvidenceTone;
}

const DIAGNOSTIC_RECEIPT_WORDS = /\b(smoke|probe|fixture|selftest|self-test|diagnostic|debug)\b/i;

function normalizeId(value: string | null | undefined): string {
  return String(value ?? '').trim();
}

function applyDocumentTheme(resolved: ResolvedTheme) {
  const root = document.documentElement;
  if (resolved === 'dark') root.classList.add('dark');
  else root.classList.remove('dark');
  root.dataset.theme = resolved;
}

function storedThemeMode(): ThemeMode {
  try {
    const raw = window.localStorage.getItem('scholar-ai.theme');
    if (raw === 'light' || raw === 'dark' || raw === 'system') return raw;
  } catch {
    /* localStorage unavailable */
  }
  return 'system';
}

function resolveStoredTheme(): ResolvedTheme {
  const mode = storedThemeMode();
  if (mode === 'dark' || mode === 'light') return mode;
  if (!window.matchMedia) return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function projectTitle(project: WritingProject): string {
  return normalizeId(project.title) || project.project_id;
}

function normalizeQuestion(value: string | null | undefined): string {
  return normalizeId(value).replace(/\s+/g, ' ');
}

function formatError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  if (/timeout of \d+ms exceeded/i.test(message) || /ECONNABORTED/i.test(message)) {
    return '读取超时。文献助手可能正在整理历史，请稍后刷新。';
  }
  if (/Network Error/i.test(message)) {
    return '文献助手后端已断开。请启动或切回文献助手后重试。';
  }
  return message.length > 240 ? `${message.slice(0, 239)}…` : message;
}

function formatVisualObservationError(error: unknown): string {
  const message = formatError(error);
  if (message.startsWith('读取超时。') || message.startsWith('文献助手后端已断开。')) {
    return message;
  }
  return '候选详情校验失败，请稍后重试。';
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return parsed.toLocaleString([], {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function lifecycleFromReceipt(read: AgentSidebarReceiptReadResponse): AnswerLifecycle {
  if (read.staleness.status === 'stale') return 'stale';
  return 'saved';
}

function compactSidebarAnswerText(value: string, placeholderOnly = false): string {
  if (placeholderOnly) return '';
  return sanitizeAssistantVisibleContent(value).replace(/\n{3,}/g, '\n\n');
}

function displayAnswerModelName(value: string | null | undefined): string | null {
  const normalized = normalizeId(value);
  if (!normalized) return null;
  if (normalized === 'external_agent' || normalized === 'host_agent') return 'Codex 智能体';
  if (normalized === 'internal_smartread') return 'SmartRead';
  if (normalized === 'scholar_ai_configured_chat') return 'Scholar AI';
  return normalized;
}

function receiptAgentName(read: AgentSidebarReceiptReadResponse): string {
  const model = displayAnswerModelName(read.receipt.answer_model);
  if (model) return model;
  const modelOrigin = displayAnswerModelName(read.receipt.answer_model_origin);
  if (modelOrigin) return modelOrigin;
  const answerOrigin = displayAnswerModelName(read.receipt.answer_origin);
  if (answerOrigin) return answerOrigin;
  return 'Scholar AI';
}

function receiptMessages(read: AgentSidebarReceiptReadResponse): ChatMessageData[] {
  const placeholderOnly = normalizeId(read.receipt.answer_model) === 'external_agent';
  return [
    {
      id: `${read.conversation_id}:answer`,
      role: 'assistant',
      content: compactSidebarAnswerText(read.answer, placeholderOnly),
      timestamp: undefined,
      status: 'done',
      evidence: read.receipt.top_evidence_refs.map(agentSidebarEvidenceToPill),
      agent: { name: receiptAgentName(read) },
    },
  ];
}

function evidenceStatusProjection(read: AgentSidebarReceiptReadResponse | null, loading = false): EvidenceStatusProjection {
  if (!read && loading) {
    return { label: '读取历史', detail: '正在同步保存记录', tone: 'neutral' };
  }
  if (!read) {
    return { label: '未选择记录', detail: '提问或从历史打开', tone: 'neutral' };
  }
  const gateStatus = normalizeId(read.receipt.evidence_gate_status?.status) || 'unknown';
  const qrelsStatus = read.receipt.qrels_status?.status ?? 'unknown';
  const semanticQualityClaimAllowed = qrelsStatus === 'canonical'
    && read.receipt.qrels_status?.semantic_quality_claim_allowed === true;
  const staleStatus = read.staleness.status || read.receipt.staleness_status || 'unchecked';
  const hasEvidenceRefs = read.receipt.top_evidence_refs.length > 0;
  if (gateStatus === 'blocked' || gateStatus === 'failed' || gateStatus === 'error') {
    return { label: '证据被阻断', detail: '需要先修复证据或重新检索', tone: 'danger' };
  }
  if (staleStatus === 'stale') {
    return { label: '证据需复核', detail: '项目或证据已变化，建议重新检查', tone: 'warning' };
  }
  if (qrelsStatus === 'missing' || (hasEvidenceRefs && qrelsStatus === 'unknown')) {
    return { label: '有引用，未评估', detail: '可回答内容，但不评价检索质量', tone: 'warning' };
  }
  if (qrelsStatus === 'candidate' || qrelsStatus === 'reviewed') {
    return { label: '已绑定证据', detail: '引用已保存，质量评估待确认', tone: 'warning' };
  }
  if (gateStatus === 'passed') {
    return {
      label: '证据可用',
      detail: semanticQualityClaimAllowed ? '回答已绑定可追溯引用' : '引用可追溯，不评价检索质量',
      tone: 'good',
    };
  }
  return { label: '证据待确认', detail: '打开证据可查看引用来源', tone: 'neutral' };
}

function lifecycleLabel(state: AnswerLifecycle): string {
  switch (state) {
    case 'running':
      return '运行中';
    case 'stopped':
      return '已停止';
    case 'saving':
      return '保存中';
    case 'saved':
      return '已保存';
    case 'stale':
      return '需复核';
    case 'revalidating':
      return '复核中';
    case 'error':
      return '错误';
    default:
      return '待提问';
  }
}

function compactStatusLabel(value: string | null | undefined): string {
  switch (normalizeId(value)) {
    case 'saved':
      return '已保存';
    case 'stale':
      return '需复核';
    case 'revalidated':
      return '已复核';
    case 'superseded':
      return '已替代';
    case 'unchecked':
      return '未检查';
    case 'missing':
      return '缺失';
    case 'unknown':
      return '未知';
    case 'started':
    case 'running':
    case 'in_progress':
      return '运行中';
    case 'completed':
      return '已完成';
    case 'failed':
    case 'error':
      return '错误';
    default:
      return normalizeId(value) || '未知';
  }
}

function toneClass(tone: EvidenceTone): string {
  switch (tone) {
    case 'good':
      return 'border-emerald-500/35 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200';
    case 'warning':
      return 'border-amber-500/35 bg-amber-500/10 text-amber-800 dark:text-amber-200';
    case 'danger':
      return 'border-red-500/35 bg-red-500/10 text-red-800 dark:text-red-200';
    default:
      return 'border-outline-variant/70 bg-surface-low text-foreground/65';
  }
}

function receiptTitle(summary: AgentSidebarReceiptSummary): string {
  return summary.receipt.question || summary.title || summary.conversation_id;
}

function isDiagnosticReceipt(summary: AgentSidebarReceiptSummary): boolean {
  const conversationId = normalizeId(summary.conversation_id);
  const title = normalizeQuestion(summary.title);
  const question = normalizeQuestion(summary.receipt.question);
  const model = normalizeId(summary.receipt.answer_model);
  const searchable = `${conversationId} ${title} ${question} ${model}`;
  if (DIAGNOSTIC_RECEIPT_WORDS.test(searchable)) return true;
  return /^s\d{2,}[_-]/i.test(conversationId);
}

function autoSelectableReceipt(summaries: AgentSidebarReceiptSummary[]): AgentSidebarReceiptSummary | null {
  return summaries.find((summary) => !isDiagnosticReceipt(summary)) ?? null;
}

function userVisibleReceipts(summaries: AgentSidebarReceiptSummary[]): AgentSidebarReceiptSummary[] {
  return summaries.filter((summary) => !isDiagnosticReceipt(summary));
}

function findSubmittedReceipt(
  summaries: AgentSidebarReceiptSummary[],
  previousUpdatedAtById: Map<string, string>,
  question: string,
  submittedAfterMs: number,
): AgentSidebarReceiptSummary | null {
  const submittedQuestion = normalizeQuestion(question);
  return summaries.find((summary) => {
    if (normalizeQuestion(summary.receipt.question || summary.title) !== submittedQuestion) return false;
    const previousUpdatedAt = previousUpdatedAtById.get(summary.conversation_id);
    if (previousUpdatedAt !== undefined) return previousUpdatedAt !== summary.updated_at;
    const updatedAtMs = Date.parse(summary.updated_at);
    return Number.isFinite(updatedAtMs) && updatedAtMs >= submittedAfterMs - 5000;
  }) ?? null;
}

function refTitle(ref: AgentSidebarEvidenceRef): string {
  return ref.source_title || ref.title || ref.source || ref.ref_id || '证据';
}

function evidenceDetailLine(read: AgentSidebarReceiptReadResponse): string {
  const refCount = read.receipt.top_evidence_refs.length;
  const stale = read.staleness.status || read.receipt.staleness_status;
  if (stale === 'stale' || read.staleness.mismatches.length > 0) return '项目内容变化后建议复核。';
  if (refCount > 0) return `${refCount} 条引用已绑定到这条回答。`;
  return '这条记录还没有可显示的引用。';
}

function graphContinuityDetail(status: string, count: number): { label: string; detail: string; tone: EvidenceTone } {
  if (status === 'failed' || status === 'error' || status === 'blocked') {
    return {
      label: '图谱候选未完成',
      detail: '候选关系没有进入最终图谱，请在文献助手审查。',
      tone: 'danger',
    };
  }
  if (status === 'metadata_only') {
    return {
      label: '图谱元数据待审',
      detail: '仅保存候选关系元数据，未写入最终图谱。',
      tone: 'warning',
    };
  }
  if (status === 'attached_to_wiki_candidate') {
    return {
      label: '图谱候选待审',
      detail: `${count > 0 ? `${count} 条` : '候选'}关系随 Wiki 草稿保存，未作为最终图谱结论。`,
      tone: 'warning',
    };
  }
  return {
    label: '图谱候选待审',
    detail: '等待治理审查，未作为最终图谱完整性结论。',
    tone: 'warning',
  };
}

function continuitySummaryItems(read: AgentSidebarReceiptReadResponse): ContinuitySummaryItem[] {
  const refs = read.receipt.knowledge_consumer_refs;
  const evidenceCount = read.receipt.top_evidence_refs.length;
  const items: ContinuitySummaryItem[] = [];

  items.push({
    key: 'citation',
    label: evidenceCount > 0 ? '引用可回读' : '引用缺失',
    detail: evidenceCount > 0
      ? `${evidenceCount} 条回答引用保留在保存记录；这只证明可追溯，不代表检索质量。`
      : '这条回答没有可回读证据，不能进入 Wiki 或图谱审查。',
    tone: evidenceCount > 0 ? 'neutral' : 'warning',
  });

  if (refs?.wiki_candidate_ref) {
    items.push({
      key: 'wiki',
      label: refs.wiki_review_item_ref ? 'Wiki 候选待审' : 'Wiki 草稿可回读',
      detail: refs.wiki_review_item_ref
        ? '回答摘要已进入审查队列，确认后才进入知识库。'
        : '候选草稿已生成，但未绑定审查项。',
      tone: refs.wiki_review_item_ref ? 'warning' : 'neutral',
    });
  }

  const graphRef = refs?.graph_candidate_ref;
  if (graphRef) {
    const graph = graphContinuityDetail(
      normalizeId(graphRef.status) || 'unknown',
      graphRef.graph_patch_ref_count ?? 0,
    );
    items.push({
      key: 'graph',
      label: graph.label,
      detail: graph.detail,
      tone: graph.tone,
    });
  }

  if (refs?.evolution_capture_ref) {
    items.push({
      key: 'governance',
      label: '治理记录已挂接',
      detail: '后续演化记录从同一接手任务回看，不另建回答历史。',
      tone: 'neutral',
    });
  }

  return items;
}

function revalidateStatusLine(result: AgentSidebarRevalidateResponse): string {
  if (result.status === 'stale') return '结果需要更新。';
  if (result.status === 'ready' || result.status === 'saved') return '当前记录可继续使用。';
  return compactStatusLabel(result.status);
}

function buildMainColumnInstruction(request: AgentSidebarAnswerRequestResponse): string {
  return [
    `请接手 Scholar AI 侧栏交接任务 ${request.request_id}。`,
    '用 literature.agent_request_read 读取任务和限定证据，基于 evidence refs 回答。',
    '完成后用 literature.agent_result 写回同一 request_id。',
  ].join('\n');
}

function visualGenerationLabel(status: VisualObservationReference['generation_status']): string {
  return status === 'succeeded' ? '生成成功' : '生成失败';
}

function visualReviewLabel(status: VisualObservationReferenceReviewStatus | VisualObservationReviewStatus): string {
  if (status === 'candidate') return '待审';
  if (status === 'accepted') return '已接受';
  if (status === 'rejected') return '已拒绝';
  if (status === 'withdrawn') return '已撤回';
  return '待审';
}

function visualFreshnessLabel(status: VisualObservationFreshnessStatus): string {
  return status === 'fresh' ? '新鲜' : '已过期';
}

function visualReferenceLifecycle(reference: VisualObservationReference): {
  reviewStatus: VisualObservationReviewStatus;
  freshnessStatus: VisualObservationFreshnessStatus;
} {
  return reference.review_status === 'stale'
    ? { reviewStatus: 'candidate', freshnessStatus: 'stale' }
    : { reviewStatus: reference.review_status, freshnessStatus: 'fresh' };
}

function visualOperationId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return `visual_review_${uuid}`;
  return `visual_review_${Date.now().toString(36)}_${Math.floor(Math.random() * 1_000_000).toString(36)}`;
}

function visualMutationError(error: unknown): string {
  const message = formatError(error);
  if (message.startsWith('读取超时。') || message.startsWith('文献助手后端已断开。')) {
    return message;
  }
  return '审查状态更新失败；候选可能已被其他窗口更新，请重新读取后重试。';
}

function visualRouteLabel(route: VisualObservationReference['route']): string {
  return route === 'direct_model' ? '直接模型' : '视觉辅助';
}

interface SidebarDisclosureProps {
  title: string;
  icon: JSX.Element;
  count?: number;
  contentClassName?: string;
  children: ReactNode;
}

function SidebarDisclosure({ title, icon, count, contentClassName, children }: SidebarDisclosureProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <section className="border-b border-outline-variant/55">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-xs font-medium text-foreground/80 transition-colors hover:bg-surface-high/65"
      >
        <span className="text-foreground/55">{icon}</span>
        <span className="flex-1">{title}</span>
        {typeof count === 'number' && (
          <span className="rounded border border-outline-variant/60 bg-surface-lowest px-1.5 py-0.5 text-[10px] text-foreground/55">
            {count}
          </span>
        )}
        <ChevronDown className={cn('h-3 w-3 text-foreground/35 transition-transform', open ? 'rotate-180' : '')} aria-hidden />
        <span className="sr-only">展开或收起</span>
      </button>
      {open ? (
        <div
          id={panelId}
          className={cn('max-h-56 overflow-auto bg-surface-lowest px-3 py-2 text-xs text-foreground/70', contentClassName)}
        >
          {children}
        </div>
      ) : null}
    </section>
  );
}

export function AgentSidebar() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryProjectId = normalizeId(searchParams.get('project_id'));
  const { activeProjectId, setActiveProjectId } = useWriting();
  const smartRead = useSmartRead();
  const initialProjectId = queryProjectId || activeProjectId;
  const [projects, setProjects] = useState<WritingProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState(initialProjectId);
  const [connectionState, setConnectionState] = useState<ConnectionState>('checking');
  const [answerLifecycle, setAnswerLifecycle] = useState<AnswerLifecycle>('idle');
  const [submissionActive, setSubmissionActive] = useState(false);
  const [receipts, setReceipts] = useState<AgentSidebarReceiptSummary[]>([]);
  const [selectedReceiptId, setSelectedReceiptId] = useState<string | null>(null);
  const [selectedReceipt, setSelectedReceipt] = useState<AgentSidebarReceiptReadResponse | null>(null);
  const [receiptLoading, setReceiptLoading] = useState(Boolean(initialProjectId));
  const [revalidateResult, setRevalidateResult] = useState<AgentSidebarRevalidateResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [handoffCopied, setHandoffCopied] = useState(false);
  const [handoffRequest, setHandoffRequest] = useState<AgentSidebarAnswerRequestResponse | null>(null);
  const [handoffCreating, setHandoffCreating] = useState(false);
  const [desktopOpening, setDesktopOpening] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [selectedVisualObservationId, setSelectedVisualObservationId] = useState<string | null>(null);
  const [visualObservationDetail, setVisualObservationDetail] = useState<VisualObservationDetail | null>(null);
  const [visualObservationLoadingId, setVisualObservationLoadingId] = useState<string | null>(null);
  const [visualObservationError, setVisualObservationError] = useState<string | null>(null);
  const [visualObservationReason, setVisualObservationReason] = useState('');
  const [visualObservationMutating, setVisualObservationMutating] = useState(false);
  const stopRequestedRef = useRef(false);
  const submitInFlightRef = useRef(false);
  const selectedProjectIdRef = useRef(normalizeId(initialProjectId));
  const selectedReceiptIdRef = useRef<string | null>(null);
  const projectLoadGenerationRef = useRef(0);
  const receiptRequestGenerationRef = useRef(0);
  const visualObservationRequestRef = useRef(0);

  useEffect(() => {
    if (!window.matchMedia) return undefined;
    const mql = window.matchMedia('(prefers-color-scheme: dark)');
    const syncFromHost = (matches: boolean) => applyDocumentTheme(matches ? 'dark' : 'light');
    const handleChange = (event: MediaQueryListEvent) => syncFromHost(event.matches);
    syncFromHost(mql.matches);
    mql.addEventListener?.('change', handleChange);
    return () => {
      mql.removeEventListener?.('change', handleChange);
      applyDocumentTheme(resolveStoredTheme());
    };
  }, []);

  const smartReadScope = useMemo(
    () => smartReadDialogScope(selectedProjectId || 'default'),
    [selectedProjectId],
  );
  const conversation = smartRead.getConversation(smartReadScope);
  const submissionBusy = submissionActive
    || conversation.pending
    || answerLifecycle === 'running'
    || answerLifecycle === 'saving';
  const visualObservationRefs = useMemo(
    () => selectedReceipt?.receipt.visual_observation_refs ?? [],
    [selectedReceipt],
  );

  useEffect(() => {
    selectedReceiptIdRef.current = selectedReceiptId;
  }, [selectedReceiptId]);

  useEffect(() => {
    visualObservationRequestRef.current += 1;
    setSelectedVisualObservationId(null);
    setVisualObservationDetail(null);
    setVisualObservationLoadingId(null);
    setVisualObservationError(null);
    setVisualObservationReason('');
    setVisualObservationMutating(false);
  }, [selectedReceipt]);

  const isCurrentReceiptRequest = useCallback((projectId: string, generation: number): boolean => (
    selectedProjectIdRef.current === projectId
    && receiptRequestGenerationRef.current === generation
  ), []);

  const isCurrentReceiptSelection = useCallback((
    projectId: string,
    conversationId: string,
    generation: number,
  ): boolean => (
    isCurrentReceiptRequest(projectId, generation)
    && selectedReceiptIdRef.current === conversationId
  ), [isCurrentReceiptRequest]);

  const advanceReceiptRequestGeneration = useCallback((): number => {
    const generation = receiptRequestGenerationRef.current + 1;
    receiptRequestGenerationRef.current = generation;
    setHandoffCreating(false);
    return generation;
  }, []);

  const resetReceiptOwnership = useCallback((projectId: string): void => {
    const normalized = normalizeId(projectId);
    selectedProjectIdRef.current = normalized;
    setSelectedProjectId(normalized);
    setReceipts([]);
    setSelectedReceipt(null);
    selectedReceiptIdRef.current = null;
    setSelectedReceiptId(null);
    setRevalidateResult(null);
    setHandoffRequest(null);
    setHandoffCopied(false);
    setHandoffCreating(false);
    setNotice(null);
    setErrorMessage(null);
    setAnswerLifecycle('idle');
    setReceiptLoading(Boolean(normalized));
  }, []);

  const loadReceipt = useCallback(async (
    conversationId: string,
    projectId = selectedProjectIdRef.current,
    requestGeneration?: number,
  ) => {
    const normalized = normalizeId(conversationId);
    const normalizedProjectId = normalizeId(projectId);
    if (!normalized || !normalizedProjectId || selectedProjectIdRef.current !== normalizedProjectId) return null;
    const generation = requestGeneration ?? advanceReceiptRequestGeneration();
    if (requestGeneration !== undefined && !isCurrentReceiptRequest(normalizedProjectId, generation)) {
      return null;
    }
    setReceiptLoading(true);
    try {
      const read = await readAgentSidebarReceipt(normalized);
      if (!isCurrentReceiptRequest(normalizedProjectId, generation)) return null;
      const responseProjectId = normalizeId(read.project_id);
      if (responseProjectId && responseProjectId !== normalizedProjectId) return null;
      setSelectedReceipt(read);
      selectedReceiptIdRef.current = read.conversation_id;
      setSelectedReceiptId(read.conversation_id);
      setAnswerLifecycle(lifecycleFromReceipt(read));
      setHandoffRequest(null);
      setHandoffCopied(false);
      setErrorMessage(null);
      return read;
    } catch (error) {
      if (!isCurrentReceiptRequest(normalizedProjectId, generation)) return null;
      setErrorMessage(formatError(error));
      setAnswerLifecycle('error');
      return null;
    } finally {
      if (isCurrentReceiptRequest(normalizedProjectId, generation)) {
        setReceiptLoading(false);
      }
    }
  }, [advanceReceiptRequestGeneration, isCurrentReceiptRequest]);

  const refreshReceipts = useCallback(async (projectId: string, options: RefreshReceiptOptions = {}) => {
    const normalized = normalizeId(projectId);
    if (!normalized) {
      advanceReceiptRequestGeneration();
      setReceipts([]);
      setSelectedReceipt(null);
      selectedReceiptIdRef.current = null;
      setSelectedReceiptId(null);
      setReceiptLoading(false);
      return [];
    }
    if (selectedProjectIdRef.current !== normalized) return [];
    const generation = advanceReceiptRequestGeneration();
    setReceiptLoading(true);
    try {
      const response = await listAgentSidebarReceipts(normalized, 20);
      if (!isCurrentReceiptRequest(normalized, generation)) return [];
      const responseProjectId = normalizeId(response.project_id);
      if (responseProjectId && responseProjectId !== normalized) return [];
      setReceipts(response.receipts);
      const currentReceiptId = options.preserveSelection === false ? null : selectedReceiptIdRef.current;
      const stillSelected = currentReceiptId && response.receipts.some((item) => item.conversation_id === currentReceiptId);
      const targetId = stillSelected
        ? currentReceiptId
        : options.selectLatest
          ? autoSelectableReceipt(response.receipts)?.conversation_id
          : null;
      if (targetId) {
        await loadReceipt(targetId, normalized, generation);
      } else if (!stillSelected) {
        setSelectedReceipt(null);
        selectedReceiptIdRef.current = null;
        setSelectedReceiptId(null);
      }
      if (!isCurrentReceiptRequest(normalized, generation)) return [];
      setConnectionState('ready');
      setErrorMessage(null);
      return response.receipts;
    } catch (error) {
      if (!isCurrentReceiptRequest(normalized, generation)) return [];
      setConnectionState('degraded');
      setErrorMessage(formatError(error));
      return [];
    } finally {
      if (isCurrentReceiptRequest(normalized, generation)) {
        setReceiptLoading(false);
      }
    }
  }, [advanceReceiptRequestGeneration, isCurrentReceiptRequest, loadReceipt]);

  const loadProjects = useCallback(async () => {
    const generation = projectLoadGenerationRef.current + 1;
    projectLoadGenerationRef.current = generation;
    advanceReceiptRequestGeneration();
    setConnectionState('checking');
    try {
      const [healthResult, projectList] = await Promise.all([
        getAgentSidebarHealth().catch(() => null),
        getWritingBackendService().listProjects(),
      ]);
      if (projectLoadGenerationRef.current !== generation) return;
      const sorted = [...projectList].sort((a, b) => projectTitle(a).localeCompare(projectTitle(b)));
      const preferred = queryProjectId || activeProjectId || sorted[0]?.project_id || '';
      setProjects(sorted);
      if (selectedProjectIdRef.current !== normalizeId(preferred)) {
        resetReceiptOwnership(preferred);
      } else {
        selectedProjectIdRef.current = normalizeId(preferred);
        setSelectedProjectId(preferred);
      }
      if (preferred && preferred !== activeProjectId) {
        setActiveProjectId(preferred);
      }
      setConnectionState(healthResult?.status === 'degraded' ? 'degraded' : 'ready');
      setErrorMessage(null);
      if (preferred) {
        void refreshReceipts(preferred, { selectLatest: true });
      } else {
        setReceiptLoading(false);
      }
    } catch (error) {
      if (projectLoadGenerationRef.current !== generation) return;
      setConnectionState('offline');
      setReceiptLoading(false);
      setErrorMessage(formatError(error));
    }
  }, [
    activeProjectId,
    advanceReceiptRequestGeneration,
    queryProjectId,
    refreshReceipts,
    resetReceiptOwnership,
    setActiveProjectId,
  ]);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  const handleProjectChange = useCallback((projectId: string) => {
    const normalized = normalizeId(projectId);
    projectLoadGenerationRef.current += 1;
    advanceReceiptRequestGeneration();
    resetReceiptOwnership(normalized);
    setActiveProjectId(normalized);
    const next = new URLSearchParams(searchParams);
    if (normalized) next.set('project_id', normalized);
    else next.delete('project_id');
    setSearchParams(next, { replace: true });
    if (normalized) {
      void refreshReceipts(normalized, { selectLatest: true });
    } else {
      setReceiptLoading(false);
    }
  }, [
    advanceReceiptRequestGeneration,
    refreshReceipts,
    resetReceiptOwnership,
    searchParams,
    setActiveProjectId,
    setSearchParams,
  ]);

  const handleSubmit = useCallback(async (payload: { text: string }) => {
    const question = payload.text.trim();
    if (!question) return;
    if (!selectedProjectId) {
      setErrorMessage('请选择 Scholar AI 项目后再提问。');
      setAnswerLifecycle('error');
      return;
    }
    if (submitInFlightRef.current || submissionBusy) return;
    const submissionProjectId = normalizeId(selectedProjectId);
    submitInFlightRef.current = true;
    setSubmissionActive(true);
    stopRequestedRef.current = false;
    setSelectedReceipt(null);
    setSelectedReceiptId(null);
    setRevalidateResult(null);
    setHandoffRequest(null);
    setHandoffCopied(false);
    setNotice(null);
    setErrorMessage(null);
    setAnswerLifecycle('running');
    const previousUpdatedAtById = new Map(
      receipts.map((summary) => [summary.conversation_id, summary.updated_at] as const),
    );
    const submittedAfterMs = Date.now();
    try {
      await smartRead.sendMessage(smartReadScope, question, {
        projectId: submissionProjectId,
        answerOrigin: 'internal_smartread',
        generatedIn: 'mcp_sidebar',
        tier: 'medium',
      });
      if (selectedProjectIdRef.current !== submissionProjectId) return;
      if (stopRequestedRef.current) {
        setAnswerLifecycle('stopped');
        setNotice('已停止后续刷新；已完成的后端步骤不会回滚。');
        return;
      }
      setAnswerLifecycle('saving');
      const updatedReceipts = await refreshReceipts(submissionProjectId, {
        selectLatest: false,
        preserveSelection: false,
      });
      if (selectedProjectIdRef.current !== submissionProjectId) return;
      const submittedReceipt = findSubmittedReceipt(updatedReceipts, previousUpdatedAtById, question, submittedAfterMs);
      if (!submittedReceipt) {
        setAnswerLifecycle('error');
        setErrorMessage('本次提问没有生成可保存的 Scholar AI receipt；历史不会自动选中旧记录。');
        return;
      }
      await loadReceipt(submittedReceipt.conversation_id, submissionProjectId);
    } catch (error) {
      if (selectedProjectIdRef.current !== submissionProjectId) return;
      setAnswerLifecycle('error');
      setErrorMessage(formatError(error));
    } finally {
      submitInFlightRef.current = false;
      setSubmissionActive(false);
    }
  }, [loadReceipt, receipts, refreshReceipts, selectedProjectId, smartRead, smartReadScope, submissionBusy]);

  const handleStop = useCallback(() => {
    stopRequestedRef.current = true;
    smartRead.stopMessage(smartReadScope);
    setAnswerLifecycle('stopped');
    setNotice('停止只影响前端流和后续步骤；已完成的工具或保存不会撤销。');
  }, [smartRead, smartReadScope]);

  const handleRevalidate = useCallback(async (apply: boolean) => {
    const requestProjectId = selectedProjectIdRef.current;
    const requestReceiptId = normalizeId(selectedReceiptId);
    const requestGeneration = receiptRequestGenerationRef.current;
    const requestIsCurrent = (): boolean => isCurrentReceiptSelection(
      requestProjectId,
      requestReceiptId,
      requestGeneration,
    );
    if (!requestProjectId || !requestReceiptId || !requestIsCurrent()) return;
    setAnswerLifecycle('revalidating');
    setRevalidateResult(null);
    setNotice(null);
    setErrorMessage(null);
    try {
      const result = await revalidateAgentSidebarReceipt(requestReceiptId, { apply, topK: 10 });
      if (!requestIsCurrent()) return;
      setRevalidateResult(result);
      setNotice(apply ? `复核：${result.status}` : `预检：${result.status}`);
      if (apply) {
        await loadReceipt(requestReceiptId, requestProjectId);
      } else {
        setAnswerLifecycle(selectedReceipt ? lifecycleFromReceipt(selectedReceipt) : 'saved');
      }
    } catch (error) {
      if (!requestIsCurrent()) return;
      setAnswerLifecycle('error');
      setErrorMessage(formatError(error));
    }
  }, [isCurrentReceiptSelection, loadReceipt, selectedReceipt, selectedReceiptId]);

  const handleCreateHandoffRequest = useCallback(async () => {
    const requestProjectId = selectedProjectIdRef.current;
    const requestReceipt = selectedReceipt;
    const requestReceiptId = normalizeId(requestReceipt?.conversation_id);
    const requestGeneration = receiptRequestGenerationRef.current;
    const requestIsCurrent = (): boolean => isCurrentReceiptSelection(
      requestProjectId,
      requestReceiptId,
      requestGeneration,
    );
    if (!requestReceipt || !requestProjectId || !requestReceiptId || !requestIsCurrent()) return;
    setHandoffCreating(true);
    setHandoffCopied(false);
    setNotice(null);
    setErrorMessage(null);
    try {
      const request = await createAgentSidebarAnswerRequest(requestReceipt, {
        projectId: requestProjectId,
        agentHost: 'codex',
      });
      if (!requestIsCurrent()) return;
      setHandoffRequest(request);
      setNotice('已创建待接手任务。');
    } catch (error) {
      if (!requestIsCurrent()) return;
      setErrorMessage(formatError(error));
    } finally {
      if (requestIsCurrent()) {
        setHandoffCreating(false);
      }
    }
  }, [isCurrentReceiptSelection, selectedReceipt]);

  const handleCopyHandoffInstruction = useCallback(async () => {
    if (!handoffRequest) return;
    setHandoffCopied(false);
    setNotice(null);
    setErrorMessage(null);
    if (!navigator.clipboard?.writeText) {
      setNotice('当前浏览器没有开放剪贴板写入。');
      return;
    }
    try {
      await navigator.clipboard.writeText(buildMainColumnInstruction(handoffRequest));
      setHandoffCopied(true);
      window.setTimeout(() => setHandoffCopied(false), 1600);
    } catch {
      setNotice('剪贴板写入失败。');
    }
  }, [handoffRequest]);

  const handleOpenDesktop = useCallback(async () => {
    setDesktopOpening(true);
    setNotice(null);
    setErrorMessage(null);
    try {
      const response = await openAgentSidebarDesktop();
      setNotice(response.message);
    } catch (error) {
      setErrorMessage(formatError(error));
    } finally {
      setDesktopOpening(false);
    }
  }, []);

  const handleReadVisualObservation = useCallback(async (reference: VisualObservationReference) => {
    const requestId = visualObservationRequestRef.current + 1;
    visualObservationRequestRef.current = requestId;
    setSelectedVisualObservationId(reference.candidate_id);
    setVisualObservationDetail(null);
    setVisualObservationError(null);
    setVisualObservationReason('');
    setVisualObservationMutating(false);
    setVisualObservationLoadingId(reference.candidate_id);
    try {
      const detail = await readVisualObservationDetail(reference);
      if (visualObservationRequestRef.current !== requestId) return;
      setVisualObservationDetail(detail);
    } catch (error) {
      if (visualObservationRequestRef.current !== requestId) return;
      setVisualObservationError(formatVisualObservationError(error));
    } finally {
      if (visualObservationRequestRef.current === requestId) {
        setVisualObservationLoadingId(null);
      }
    }
  }, []);

  const handleReviewVisualObservation = useCallback(async (
    targetReviewStatus: Exclude<VisualObservationReviewStatus, 'candidate'>,
  ) => {
    const candidate = visualObservationDetail;
    const reference = visualObservationRefs.find((item) => item.candidate_id === candidate?.candidateId);
    const reason = visualObservationReason.trim();
    if (!candidate || !reference || !reason || visualObservationMutating) return;

    const requestId = visualObservationRequestRef.current;
    setVisualObservationMutating(true);
    setVisualObservationError(null);
    setNotice(null);
    try {
      const result = await transitionVisualObservation(candidate, {
        operationId: visualOperationId(),
        expectedReviewStatus: candidate.reviewStatus,
        expectedFreshnessStatus: candidate.freshnessStatus,
        targetReviewStatus,
        reason,
        changedBy: 'agent-sidebar',
      });
      if (visualObservationRequestRef.current !== requestId) return;
      setVisualObservationDetail(result.candidate);
      setVisualObservationReason('');
      setNotice(`${visualReviewLabel(result.candidate.reviewStatus)}。已按当前候选状态保存审查结果。`);
    } catch (error) {
      if (visualObservationRequestRef.current !== requestId) return;
      setVisualObservationError(visualMutationError(error));
      try {
        const refreshed = await readVisualObservationDetail(reference);
        if (visualObservationRequestRef.current === requestId) {
          setVisualObservationDetail(refreshed);
        }
      } catch {
        // Keep the validated local snapshot when authoritative read-back is unavailable.
      }
    } finally {
      if (visualObservationRequestRef.current === requestId) {
        setVisualObservationMutating(false);
      }
    }
  }, [visualObservationDetail, visualObservationReason, visualObservationMutating, visualObservationRefs]);

  const isReceiptBootstrapping = receiptLoading
    && !selectedReceipt
    && !!selectedProjectId
    && !['running', 'saving', 'revalidating', 'error', 'stopped'].includes(answerLifecycle);
  const evidenceStatus = useMemo(
    () => evidenceStatusProjection(selectedReceipt, isReceiptBootstrapping),
    [isReceiptBootstrapping, selectedReceipt],
  );
  const displayMessages = useMemo(() => {
    if (selectedReceipt && !conversation.pending) return receiptMessages(selectedReceipt);
    if (conversation.pending || answerLifecycle === 'running' || answerLifecycle === 'saving') {
      return conversation.messages;
    }
    return [];
  }, [answerLifecycle, conversation.messages, conversation.pending, selectedReceipt]);
  const canAsk = connectionState !== 'offline' && !!selectedProjectId;
  const isResponding = !stopRequestedRef.current && (conversation.pending || answerLifecycle === 'running');
  const visibleReceipts = useMemo(() => userVisibleReceipts(receipts), [receipts]);
  const latestReceipt = visibleReceipts[0] ?? null;
  const lifecycleText = isReceiptBootstrapping ? '读取中' : lifecycleLabel(isResponding ? 'running' : answerLifecycle);
  const continuityItems = useMemo(
    () => selectedReceipt ? continuitySummaryItems(selectedReceipt) : [],
    [selectedReceipt],
  );
  return (
    <div className="min-h-screen bg-background text-foreground">
      <main className="mx-auto flex h-screen max-w-[480px] flex-col overflow-hidden border-x border-outline-variant/60 bg-surface-lowest">
        <header className="shrink-0 border-b border-outline-variant/70 bg-surface-lowest px-2 py-2">
          <div className="grid grid-cols-[1fr_auto_auto_auto] gap-2">
            <label className="sr-only" htmlFor="agent-sidebar-project">
              Scholar AI 项目
            </label>
            <select
              id="agent-sidebar-project"
              value={selectedProjectId}
              onChange={(event) => handleProjectChange(event.target.value)}
              className="min-w-0 rounded-md border border-outline-variant/70 bg-surface-lowest px-2 py-1.5 text-xs text-foreground focus:border-primary/50 focus:outline-none"
            >
              <option value="">选择项目</option>
              {projects.map((project) => (
                <option key={project.project_id} value={project.project_id}>
                  {project.project_id === selectedProjectId ? '项目' : projectTitle(project)}
                </option>
              ))}
            </select>
            <span className="inline-flex items-center rounded-md border border-outline-variant/70 bg-surface-low px-2 text-[10px] text-foreground/60">
              {lifecycleText}
            </span>
            <button
              type="button"
              onClick={() => void loadProjects()}
              aria-label="刷新连接和项目"
              title="刷新连接和项目"
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-outline-variant/65 bg-surface-low text-foreground/70 transition-colors hover:bg-surface-high"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            </button>
            <button
              type="button"
              onClick={() => setToolsOpen((open) => !open)}
              aria-expanded={toolsOpen}
              aria-controls="agent-sidebar-tools"
              aria-label={toolsOpen ? '收起侧栏工具' : '显示侧栏工具'}
              title={toolsOpen ? '收起侧栏工具' : '显示侧栏工具'}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-outline-variant/65 bg-surface-low text-foreground/70 transition-colors hover:bg-surface-high"
            >
              <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', toolsOpen ? 'rotate-180' : '')} aria-hidden />
            </button>
          </div>
        </header>

        <section
          aria-live="polite"
          aria-label={`证据状态：${evidenceStatus.label}；${evidenceStatus.detail}`}
          className={cn('shrink-0 border-b px-3 py-2 text-xs', toneClass(evidenceStatus.tone))}
        >
          <div className="flex min-w-0 items-center gap-2">
            {evidenceStatus.tone === 'good' ? (
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
            ) : evidenceStatus.tone === 'danger' ? (
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
            ) : (
              <Workflow className="h-3.5 w-3.5 shrink-0" aria-hidden />
            )}
            <span className="font-medium">{evidenceStatus.label}</span>
          </div>
        </section>

        {(errorMessage || notice) && (
          <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-3 py-2 text-xs">
            {errorMessage ? (
              <div className="flex items-start gap-2 text-red-700 dark:text-red-300">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                <span className="min-w-0 break-words">{errorMessage}</span>
              </div>
            ) : null}
            {notice ? (
              <div className="flex items-start gap-2 text-foreground/65">
                <Workflow className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                <span className="min-w-0 break-words">{notice}</span>
              </div>
            ) : null}
          </div>
        )}

        {toolsOpen ? (
        <div id="agent-sidebar-tools" className="shrink-0 border-b border-outline-variant/60">
          <SidebarDisclosure title="证据" icon={<Workflow className="h-3.5 w-3.5" />} count={selectedReceipt?.receipt.top_evidence_refs.length ?? 0}>
            {selectedReceipt ? (
              <div className="space-y-2">
                <div className="text-[11px] text-foreground/55">{evidenceDetailLine(selectedReceipt)}</div>
                <div className="flex flex-wrap gap-1.5">
                  {selectedReceipt.receipt.top_evidence_refs.map((ref, index) => (
                    <EvidencePill
                      key={`${ref.ref_id ?? ref.chunk_id ?? index}`}
                      evidence={agentSidebarEvidenceToPill(ref)}
                      projectId={selectedProjectId || null}
                      showSourceLabels
                      title={refTitle(ref)}
                    />
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-foreground/45">未选择保存记录。</div>
            )}
          </SidebarDisclosure>
          <SidebarDisclosure
            title="视觉观察审查"
            icon={<Workflow className="h-3.5 w-3.5" />}
            count={visualObservationRefs.length}
            contentClassName="max-h-[28rem]"
          >
            {!selectedReceipt ? (
              <div className="text-foreground/45">未选择保存记录。</div>
            ) : visualObservationRefs.length === 0 ? (
              <div className="text-foreground/45">当前记录没有视觉观察候选。</div>
            ) : (
              <div data-testid="visual-observation-review-surface" className="space-y-2.5">
                <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2.5 py-2 text-[11px] leading-relaxed text-amber-800 dark:text-amber-200">
                  视觉结果仅供审查，不会自动进入回答证据、Wiki 或图谱。
                </div>
                <div className="space-y-1.5">
                  {visualObservationRefs.map((reference, index) => {
                    const storedLifecycle = visualReferenceLifecycle(reference);
                    const authoritative = visualObservationDetail?.candidateId === reference.candidate_id
                      ? visualObservationDetail
                      : null;
                    const reviewStatus = authoritative?.reviewStatus ?? storedLifecycle.reviewStatus;
                    const freshnessStatus = authoritative?.freshnessStatus ?? storedLifecycle.freshnessStatus;
                    return (
                      <button
                        key={reference.candidate_id}
                        type="button"
                        aria-label={`读取视觉观察候选 ${index + 1}`}
                        onClick={() => void handleReadVisualObservation(reference)}
                        className={cn(
                          'w-full rounded-md border px-2.5 py-2 text-left transition-colors',
                          selectedVisualObservationId === reference.candidate_id
                            ? 'border-primary/45 bg-primary/10'
                            : 'border-outline-variant/55 bg-surface-low hover:bg-surface-high',
                        )}
                      >
                        <div className="flex items-center justify-between gap-2 text-[11px]">
                          <span className="font-medium text-foreground/80">候选 {index + 1}</span>
                          <span className="text-right text-foreground/55">
                            {visualGenerationLabel(reference.generation_status)} · {visualReviewLabel(reviewStatus)} · {visualFreshnessLabel(freshnessStatus)}
                          </span>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-foreground/50">
                          <span>方式：{visualRouteLabel(reference.route)}</span>
                          <span>关联选区：{reference.selection_ids.length}</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
                {selectedVisualObservationId ? (
                  <div
                    aria-live="polite"
                    className="rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-2 text-[11px] leading-relaxed"
                  >
                    {visualObservationLoadingId === selectedVisualObservationId ? (
                      <div className="flex items-center gap-2 text-foreground/50">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                        读取候选详情…
                      </div>
                    ) : (
                      <div className="space-y-2.5">
                        {visualObservationError ? (
                          <div className="rounded border border-red-500/30 bg-red-500/10 px-2 py-1.5 text-red-700 dark:text-red-300">
                            {visualObservationError}
                          </div>
                        ) : null}
                        {visualObservationDetail?.error ? (
                          <div className="space-y-1">
                            <div className="text-red-700 dark:text-red-300">{visualObservationDetail.error.message}</div>
                            <div className="text-foreground/45">
                              {visualObservationDetail.error.recoverable ? '可重试' : '不可重试'}
                            </div>
                          </div>
                        ) : visualObservationDetail?.outputText ? (
                          <div className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded border border-outline-variant/50 bg-surface-lowest px-2 py-1.5 text-foreground/70">
                            {visualObservationDetail.outputText}
                          </div>
                        ) : !visualObservationError ? (
                          <div className="text-foreground/45">候选详情为空。</div>
                        ) : null}

                        {visualObservationDetail ? (
                          <div className="space-y-2 border-t border-outline-variant/55 pt-2">
                            <div className="flex flex-wrap gap-1.5">
                              <span className="rounded border border-outline-variant/60 bg-surface-lowest px-1.5 py-0.5 text-[10px] text-foreground/60">
                                审查：{visualReviewLabel(visualObservationDetail.reviewStatus)}
                              </span>
                              <span className={cn(
                                'rounded border px-1.5 py-0.5 text-[10px]',
                                visualObservationDetail.freshnessStatus === 'fresh'
                                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200'
                                  : 'border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-200',
                              )}>
                                新鲜度：{visualFreshnessLabel(visualObservationDetail.freshnessStatus)}
                              </span>
                            </div>
                            <label className="block space-y-1" htmlFor="visual-observation-review-reason">
                              <span className="font-medium text-foreground/70">审查理由（必填）</span>
                              <textarea
                                id="visual-observation-review-reason"
                                value={visualObservationReason}
                                onChange={(event) => setVisualObservationReason(event.target.value)}
                                maxLength={2000}
                                rows={3}
                                disabled={visualObservationMutating || visualObservationDetail.reviewStatus === 'withdrawn'}
                                placeholder="说明接受、拒绝或撤回的依据"
                                className="w-full resize-y rounded-md border border-outline-variant/70 bg-surface-lowest px-2 py-1.5 text-[11px] text-foreground outline-none transition-colors placeholder:text-foreground/35 focus:border-primary/50 disabled:cursor-not-allowed disabled:opacity-55"
                              />
                            </label>
                            <div className="grid grid-cols-3 gap-1.5">
                              <button
                                type="button"
                                onClick={() => void handleReviewVisualObservation('accepted')}
                                disabled={
                                  !visualObservationReason.trim()
                                  || visualObservationMutating
                                  || visualObservationDetail.generationStatus !== 'succeeded'
                                  || visualObservationDetail.reviewStatus !== 'candidate'
                                }
                                className="inline-flex min-h-8 items-center justify-center gap-1 rounded-md border border-emerald-500/35 bg-emerald-500/10 px-2 py-1 text-[11px] font-medium text-emerald-800 transition-colors hover:bg-emerald-500/15 disabled:cursor-not-allowed disabled:opacity-45 dark:text-emerald-200"
                              >
                                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
                                接受
                              </button>
                              <button
                                type="button"
                                onClick={() => void handleReviewVisualObservation('rejected')}
                                disabled={
                                  !visualObservationReason.trim()
                                  || visualObservationMutating
                                  || !['candidate', 'accepted'].includes(visualObservationDetail.reviewStatus)
                                }
                                className="inline-flex min-h-8 items-center justify-center gap-1 rounded-md border border-red-500/35 bg-red-500/10 px-2 py-1 text-[11px] font-medium text-red-800 transition-colors hover:bg-red-500/15 disabled:cursor-not-allowed disabled:opacity-45 dark:text-red-200"
                              >
                                <XCircle className="h-3.5 w-3.5" aria-hidden />
                                拒绝
                              </button>
                              <button
                                type="button"
                                onClick={() => void handleReviewVisualObservation('withdrawn')}
                                disabled={
                                  !visualObservationReason.trim()
                                  || visualObservationMutating
                                  || visualObservationDetail.reviewStatus === 'withdrawn'
                                }
                                className="inline-flex min-h-8 items-center justify-center gap-1 rounded-md border border-outline-variant/70 bg-surface-lowest px-2 py-1 text-[11px] font-medium text-foreground/70 transition-colors hover:bg-surface-high disabled:cursor-not-allowed disabled:opacity-45"
                              >
                                <Archive className="h-3.5 w-3.5" aria-hidden />
                                撤回
                              </button>
                            </div>
                            {visualObservationMutating ? (
                              <div className="flex items-center gap-1.5 text-[10px] text-foreground/45">
                                <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                                正在保存审查结果…
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    )}
                  </div>
                ) : null}
              </div>
            )}
          </SidebarDisclosure>
          <SidebarDisclosure title="连续性" icon={<BookOpenText className="h-3.5 w-3.5" />} count={continuityItems.length}>
            {selectedReceipt ? (
              <div data-testid="agent-sidebar-continuity-summary" className="space-y-1.5">
                {continuityItems.map((item) => (
                  <div
                    key={item.key}
                    className={cn('rounded-md border px-2 py-1.5 text-[11px] leading-relaxed', toneClass(item.tone))}
                  >
                    <div className="font-medium">{item.label}</div>
                    <div className="mt-0.5 opacity-75">{item.detail}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-foreground/45">未选择保存记录。</div>
            )}
          </SidebarDisclosure>
          <SidebarDisclosure title="历史" icon={<History className="h-3.5 w-3.5" />} count={visibleReceipts.length}>
            {receiptLoading ? (
              <div className="text-foreground/45">读取历史…</div>
            ) : visibleReceipts.length === 0 ? (
              <div className="text-foreground/45">本项目暂无侧栏记录。</div>
            ) : (
              <div className="space-y-1.5">
                {visibleReceipts.map((summary) => (
                  <button
                    key={summary.conversation_id}
                    type="button"
                    onClick={() => void loadReceipt(summary.conversation_id)}
                    className={cn(
                      'w-full rounded-md border px-2 py-1.5 text-left transition-colors',
                      summary.conversation_id === selectedReceiptId
                        ? 'border-primary/45 bg-primary/10 text-foreground'
                        : 'border-outline-variant/55 bg-surface-low hover:bg-surface-high',
                    )}
                  >
                    <div className="line-clamp-2 text-[11px] font-medium">{receiptTitle(summary)}</div>
                    <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-foreground/45">
                      <span>{compactStatusLabel(summary.lifecycle_state)}</span>
                      <span>{compactStatusLabel(summary.staleness_status)}</span>
                      <span>{formatDate(summary.updated_at)}</span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </SidebarDisclosure>
          <SidebarDisclosure title="操作" icon={<RotateCcw className="h-3.5 w-3.5" />}>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void refreshReceipts(selectedProjectId, { selectLatest: false })}
                disabled={!selectedProjectId || receiptLoading}
                className="inline-flex items-center gap-1 rounded-md border border-outline-variant/65 bg-surface-low px-2 py-1.5 text-xs transition-colors hover:bg-surface-high disabled:cursor-not-allowed disabled:opacity-50"
              >
                <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                刷新
              </button>
              <button
                type="button"
                onClick={() => void handleRevalidate(false)}
                disabled={!selectedReceiptId || answerLifecycle === 'revalidating'}
                className="inline-flex items-center gap-1 rounded-md border border-outline-variant/65 bg-surface-low px-2 py-1.5 text-xs transition-colors hover:bg-surface-high disabled:cursor-not-allowed disabled:opacity-50"
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                复核
              </button>
              <button
                type="button"
                onClick={() => void handleOpenDesktop()}
                disabled={desktopOpening}
                className="inline-flex items-center gap-1 rounded-md border border-outline-variant/65 bg-surface-low px-2 py-1.5 text-xs transition-colors hover:bg-surface-high disabled:cursor-not-allowed disabled:opacity-50"
              >
                <BookOpenText className="h-3.5 w-3.5" aria-hidden />
                {desktopOpening ? '打开中…' : '打开文献助手'}
              </button>
            </div>
            {revalidateResult ? (
              <div className="mt-2 rounded-md border border-outline-variant/60 bg-surface-low px-2 py-1.5 text-[11px] text-foreground/60">
                <div>{revalidateStatusLine(revalidateResult)}</div>
              </div>
            ) : null}
          </SidebarDisclosure>
          <SidebarDisclosure title="交接" icon={<Clipboard className="h-3.5 w-3.5" />}>
            {selectedReceipt ? (
              <div className="space-y-1.5">
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void handleCreateHandoffRequest()}
                    disabled={handoffCreating || !selectedProjectId}
                    className="inline-flex items-center gap-1 rounded-md border border-outline-variant/65 bg-surface-low px-2 py-1.5 text-xs transition-colors hover:bg-surface-high disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Workflow className="h-3.5 w-3.5" aria-hidden />
                    {handoffCreating ? '创建中…' : '创建接手任务'}
                  </button>
                  {handoffRequest ? (
                    <button
                      type="button"
                      onClick={() => void handleCopyHandoffInstruction()}
                      aria-label="复制交接指令"
                      className="inline-flex items-center gap-1 rounded-md border border-outline-variant/65 bg-surface-low px-2 py-1.5 text-xs transition-colors hover:bg-surface-high"
                    >
                      <Copy className="h-3.5 w-3.5" aria-hidden />
                      复制备用
                    </button>
                  ) : null}
                </div>
                {handoffRequest ? (
                  <div
                    aria-label="待主栏接手"
                    data-testid="agent-sidebar-main-handoff-ready"
                    role="note"
                    className="select-text rounded-md border border-primary/30 bg-primary/5 px-2 py-1.5 text-[11px] leading-relaxed text-foreground/75"
                  >
                    <div className="font-medium text-foreground/80">待主栏接手</div>
                    <div className="text-foreground/60">主栏交接卡会读取此任务。</div>
                    <div className="text-foreground/50">未弹出时可备用复制。</div>
                  </div>
                ) : null}
                {handoffCopied ? <div className="text-[11px] text-foreground/50">已复制。</div> : null}
              </div>
            ) : (
              <div className="flex items-center gap-2 text-foreground/45">
                <Unplug className="h-3.5 w-3.5" aria-hidden />
                先打开一条保存记录。
              </div>
            )}
          </SidebarDisclosure>
        </div>
        ) : null}

        <div className="min-h-0 flex-1">
          <Conversation
            messages={displayMessages}
            onSubmit={(payload) => void handleSubmit(payload)}
            projectId={selectedProjectId || null}
            placeholder={selectedProjectId ? '基于 Scholar AI 证据提问…' : '先选择项目…'}
            disabled={!canAsk || submissionBusy}
            responding={isResponding}
            onStop={handleStop}
            stopLabel="停止后续步骤"
            submitKey="enter"
            composerRows={2}
            composerAriaLabel="侧栏提问"
            autoFocusComposer
            composerHint={latestReceipt ? `最新记录：${compactStatusLabel(latestReceipt.staleness_status)}` : undefined}
            emptyState={(
              <div className="flex h-full min-h-[180px] flex-col items-center justify-center gap-2 px-3 text-center text-xs text-foreground/45">
                <Workflow className="h-5 w-5" aria-hidden />
                <div>{selectedProjectId ? (isReceiptBootstrapping ? '正在读取历史…' : '输入文献问题，或从历史打开。') : '先选择 Scholar AI 项目。'}</div>
              </div>
            )}
          />
        </div>
      </main>
    </div>
  );
}

export default AgentSidebar;
