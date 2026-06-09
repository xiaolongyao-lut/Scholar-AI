import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Send, Copy, Clock, CheckCircle2, XCircle, Plus, Trash2, Zap, Square, Layers3, Route, SlidersHorizontal, Settings2, AlertCircle, Save, Key, Archive, Download, Search, ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { discussionApi, type AgentThoughtTracePayload, type AnalysisChainPayload, type DiscussionRunConfig, type DiscussionRunResult, type DiscussionAgentConfig, type DiscussionAgentTrace, type DiscussionEvidenceMode, type DiscussionHistoryItem, type DiscussionHistoryPage, type DiscussionRunSnapshot } from '../../services/discussionApi';
import { useWriting } from '@/contexts/WritingContext';
import { useDiscussion } from '@/contexts/DiscussionContext';
import { AnalysisChainPanel } from '@/components/analysis_chain/AnalysisChainPanel';
import { cn } from '@/lib/utils';
import { discussionToGraphPayload } from '@/components/graph/discussionToGraphPayload';
import { GraphPayloadViewer } from '@/components/graph/GraphPayloadViewer';
import { McpScopePicker } from '@/components/mcp/McpScopePicker';
import { ProjectBiasSurfaceToggle } from '@/components/knowledge/ProjectBiasSurfaceToggle';
import { useProjectReasoningBiasState } from '@/hooks/useProjectReasoningBiasState';
import { sanitizeRuntimeVisibleText } from '@/components/writing/writingRuntimeDisplay';
import {
  DISCUSSION_ROLE_LABELS,
  DISCUSSION_PROFILE_STORE_CHANGED_EVENT,
  DISCUSSION_API_MODE_LABELS,
  buildAgentConfigFromProfile,
  describeApiBinding,
  isDiscussionProfileId,
  loadDiscussionProfileStore,
  type DiscussionAgentProfile,
  type DiscussionProfileId,
} from '@/services/discussionProfiles';
import {
  DISCUSSION_DEFAULT_BOUNDS,
  DISCUSSION_TURN_WARNING_THRESHOLD,
} from '@/services/discussionDefaults';
import CredentialPicker, { type CredentialPickerRequirement } from '@/components/settings/credentials/CredentialPicker';
import { EvidencePill, type EvidenceRefLike } from '@/components/evidence/EvidencePill';

interface DiscussionPanelProps {
  onInsertToEditor?: (content: string) => void;
  onHistoryChanged?: () => void | Promise<void>;
  initialQuery?: string;
  initialEvidenceMode?: DiscussionEvidenceMode;
  defaults?: {
    auto_stop?: boolean;
    min_turns?: number;
    convergence_threshold?: number;
    convergence_judge_agent_id?: string;
  };
}

const ROLE_OPTIONS: { value: DiscussionAgentConfig['role']; label: string; color: string }[] = [
  { value: 'proposer', label: '支持方', color: 'bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-700/40' },
  { value: 'critic', label: '批评方', color: 'bg-rose-50 text-rose-800 border-rose-200 dark:bg-rose-500/15 dark:text-rose-300 dark:border-rose-700/40' },
  { value: 'devil_advocate', label: '魔鬼代言人', color: 'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:border-amber-700/40' },
  { value: 'domain_expert', label: '领域专家', color: 'bg-sky-50 text-sky-800 border-sky-200 dark:bg-sky-500/15 dark:text-sky-300 dark:border-sky-700/40' },
  { value: 'synthesizer', label: '综合者', color: 'bg-indigo-50 text-indigo-800 border-indigo-200 dark:bg-indigo-500/15 dark:text-indigo-300 dark:border-indigo-700/40' },
  { value: 'custom', label: '自定义', color: 'bg-slate-50 text-slate-700 border-slate-200' },
];

const ROLE_COLOR_MAP: Record<string, string> = Object.fromEntries(
  ROLE_OPTIONS.map(r => [r.value, r.color])
);

const MAX_DISCUSSION_AGENTS = 8;
const MIN_EVIDENCE_TOP_K = 1;
const MAX_EVIDENCE_TOP_K = 50;

const SETUP_STORAGE_KEY = 'discussion-panel-setup-v1';
const HISTORY_PAGE_SIZE = 5;
const DISCUSSION_FALLBACK_ERROR = '讨论运行失败，请检查角色接口和证据配置。';
const DISCUSSION_INTERNAL_ID_PATTERN = /^(?:mat|material|chunk|source|paper|doc|run|agent|candidate|evidence)[-_][a-z0-9][a-z0-9_-]*$/i;

interface PersistedSetup {
  query?: string;
  agents?: AgentSlot[];
  maxTurns?: number;
  autoStop?: boolean;
  minTurns?: number;
  judgeAgentId?: string;
  evidenceMode?: DiscussionEvidenceMode;
  evidenceTopK?: number;
  manualChunkIds?: string;
  mcpServerIds?: string[];
  perAgentMcpServerIds?: Record<string, string[]>;
}

function loadPersistedSetup(): PersistedSetup {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(SETUP_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return typeof parsed === 'object' && parsed !== null ? (parsed as PersistedSetup) : {};
  } catch {
    return {};
  }
}

function persistSetup(value: PersistedSetup): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(SETUP_STORAGE_KEY, JSON.stringify(value));
  } catch {
    /* quota or disabled storage — drop silently */
  }
}

function getRoleLabel(role: string): string {
  return ROLE_OPTIONS.find(r => r.value === role)?.label || role;
}

export function evidenceSnippetDomId(evidenceId: string): string {
  return `evidence-snippet-${evidenceId}`;
}

export function scrollToEvidence(evidenceId: string): void {
  if (typeof document === 'undefined') return;
  const el = document.getElementById(evidenceSnippetDomId(evidenceId));
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  el.classList.add('ring-2', 'ring-primary');
  window.setTimeout(() => {
    el.classList.remove('ring-2', 'ring-primary');
  }, 1500);
}

interface AgentSlot {
  id: string;
  profileId: DiscussionProfileId;
  roleLabel: string;
  systemPrompt: string;
  runtimeCredentialId?: string;
}

function projectBiasAppliesToAgent(
  agent: AgentSlot,
  projectWide: boolean,
  discussionAgentIds: readonly string[],
): boolean {
  if (projectWide) {
    return true;
  }
  return discussionAgentIds.includes(agent.id);
}

function describeProjectBiasAgentTargets(
  agents: readonly AgentSlot[],
  projectWide: boolean,
  discussionAgentIds: readonly string[],
): string {
  if (projectWide) {
    return '全项目偏置将影响所有角色与综合。';
  }

  if (discussionAgentIds.length === 0) {
    return '当前项目未选择讨论角色。';
  }

  const labels = agents
    .filter((agent) => discussionAgentIds.includes(agent.id))
    .map((agent) => agent.roleLabel.trim() || agent.id);
  if (labels.length > 0) {
    return `将影响 ${labels.join('、')}。`;
  }

  return `已配置 ${discussionAgentIds.length} 个角色填写名，但当前角色列表未命中。`;
}

function normalizePerAgentMcpServerIds(
  raw: Record<string, string[]> | undefined,
  agents: AgentSlot[],
): Record<string, string[]> {
  if (!raw || typeof raw !== 'object') {
    return {};
  }
  const activeAgentIds = new Set(agents.map((agent) => agent.id));
  const normalized: Record<string, string[]> = {};
  for (const [agentId, serverIds] of Object.entries(raw)) {
    if (!activeAgentIds.has(agentId) || !Array.isArray(serverIds)) {
      continue;
    }
    const ids = Array.from(new Set(serverIds.map((id) => id.trim()).filter(Boolean)));
    if (ids.length > 0) {
      normalized[agentId] = ids;
    }
  }
  return normalized;
}

function makeSlot(index: number, profileId: DiscussionProfileId = 'proposer', profile?: DiscussionAgentProfile): AgentSlot {
  return {
    id: `${profileId}_${index}`,
    profileId,
    roleLabel: profile?.displayName ?? '',
    systemPrompt: profile?.systemPrompt ?? '',
  };
}

function clampNumber(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.min(max, Math.max(min, value));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readErrorDetail(error: unknown): string | null {
  if (!isRecord(error) || !isRecord(error.response)) {
    return null;
  }
  const data = error.response.data;
  if (!isRecord(data)) {
    return null;
  }
  const detail = data.detail;
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    return '讨论配置未通过校验，请检查角色、证据和自动停止设置。';
  }
  return null;
}

function buildRuntimeCredentialRequirement(agent: AgentSlot, profile?: DiscussionAgentProfile): CredentialPickerRequirement {
  const label = agent.roleLabel.trim() || profile?.displayName || '讨论角色';
  return {
    id: `discussion-agent-${agent.id}`,
    label: `${label} · 本次调用 API`,
    env: 'DISCUSSION_AGENT_API',
    kind: 'api_key',
    provider_hints: profile?.provider.trim() ? [profile.provider.trim()] : [],
    required: false,
    description: '只影响本次讨论；留空时使用该角色预设或全局默认生成配置。',
  };
}

function sanitizeDiscussionVisibleText(value: unknown, fallback: string): string {
  const visible = sanitizeRuntimeVisibleText(value, fallback);
  if (visible === fallback) return visible;
  return DISCUSSION_INTERNAL_ID_PATTERN.test(visible.trim()) ? fallback : visible;
}

export function formatDiscussionRunError(error: unknown): string {
  const raw = readErrorDetail(error) ?? (error instanceof Error ? error.message : '');
  if (!raw) {
    return DISCUSSION_FALLBACK_ERROR;
  }
  if (raw.includes('convergence_judge_agent_id')) {
    return '裁判角色必须来自当前角色列表。';
  }
  if (raw.includes('project_id is required')) {
    return '当前证据来源需要先选择项目。';
  }
  if (raw.includes('evidence_chunk_ids')) {
    return '手动证据需要填写至少一个证据编号。';
  }
  return sanitizeDiscussionVisibleText(raw, DISCUSSION_FALLBACK_ERROR);
}

export function formatDiscussionEvidenceLabel(evidenceId: string, index?: number): string {
  const trimmed = evidenceId.trim();
  const ordinal = /^E(\d+)$/i.exec(trimmed)?.[1] ?? (typeof index === 'number' ? String(index + 1) : '');
  return ordinal ? `证据 ${ordinal}` : '证据';
}

function formatDiscussionSnippetText(value: unknown, fallback: string): string {
  return sanitizeDiscussionVisibleText(value, fallback);
}

function formatDiscussionTimestamp(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return '未知时间';
  }
  return new Date(value * 1000).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function discussionHistoryStateLabel(state: DiscussionHistoryItem['state']): string {
  switch (state) {
    case 'pending':
      return '等待中';
    case 'running':
      return '运行中';
    case 'completed':
      return '已完成';
    case 'cancelled':
      return '已取消';
    case 'error':
      return '出错';
    default:
      return state;
  }
}

function downloadDiscussionExport(filename: string, content: string): void {
  if (typeof document === 'undefined') return;
  if (!filename.trim()) {
    throw new Error('filename is required');
  }
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function getSynthesisStrategyLabel(strategy: string): string {
  switch (strategy) {
    case 'vote':
      return '投票';
    case 'debate':
      return '辩论';
    case 'synthesize':
      return '综合';
    default:
      return '综合';
  }
}

function getSnapshotQuery(snapshot: DiscussionRunSnapshot): string {
  const finalResult = snapshot.final_result;
  if (finalResult?.query) {
    return sanitizeDiscussionVisibleText(finalResult.query, '问题内容已隐藏。');
  }
  const config = (snapshot as unknown as { config?: { query?: unknown } }).config;
  return typeof config?.query === 'string' && config.query.trim()
    ? sanitizeDiscussionVisibleText(config.query, '问题内容已隐藏。')
    : '未记录问题';
}

function getSnapshotSynthesisText(snapshot: DiscussionRunSnapshot): string {
  const finalText = snapshot.final_result?.synthesis?.text;
  if (typeof finalText === 'string' && finalText.trim()) {
    return sanitizeDiscussionVisibleText(finalText, '综合结论已隐藏，避免显示内部路径或系统字段。');
  }
  const liveText = snapshot.synthesis?.text;
  return typeof liveText === 'string' && liveText.trim()
    ? sanitizeDiscussionVisibleText(liveText, '综合结论已隐藏，避免显示内部路径或系统字段。')
    : '暂无综合结论。';
}

export function formatDiscussionAnswerText(value: unknown): string {
  return sanitizeDiscussionVisibleText(value, '回答内容已隐藏，避免显示内部路径或系统字段。');
}

export function formatDiscussionSynthesisText(value: unknown): string {
  return sanitizeDiscussionVisibleText(value, '综合结论已隐藏，避免显示内部路径或系统字段。');
}

function hasDiscussionAnalysisChainContent(chain: AnalysisChainPayload | null | undefined): boolean {
  if (!chain) {
    return false;
  }
  return Boolean(
    chain.observation?.trim() ||
      chain.mechanism?.trim() ||
      (Array.isArray(chain.evidence) && chain.evidence.some((item) => item.trim())) ||
      chain.boundary?.trim() ||
      (Array.isArray(chain.counter_evidence) && chain.counter_evidence.some((item) => item.trim())) ||
      chain.next_action?.trim(),
  );
}

function hasDiscussionThoughtTraceContent(trace: AgentThoughtTracePayload | null | undefined): boolean {
  if (!trace) {
    return false;
  }
  return Boolean(
    trace.agent_stance?.trim() ||
      trace.contribution_type?.trim() ||
      (Array.isArray(trace.evidence_refs) && trace.evidence_refs.some((item) => item.trim())) ||
      typeof trace.confidence === 'number' ||
      (Array.isArray(trace.trace_steps) && trace.trace_steps.some((step) => step.summary?.trim())),
  );
}

function getSnapshotTurns(snapshot: DiscussionRunSnapshot): DiscussionRunResult['turns'] {
  if (snapshot.final_result?.turns && snapshot.final_result.turns.length > 0) {
    return snapshot.final_result.turns;
  }
  if (snapshot.live_traces.length > 0) {
    return [{ turn_index: 0, agent_traces: snapshot.live_traces }];
  }
  return [];
}

function DiscussionHistoryPreviewModal({
  snapshot,
  loading,
  error,
  onClose,
  onExport,
  onRestore,
}: {
  snapshot: DiscussionRunSnapshot | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onExport: () => void;
  onRestore?: () => void;
}) {
  const turns = snapshot ? getSnapshotTurns(snapshot) : [];
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6">
      <div className="max-h-[86vh] w-full max-w-3xl overflow-hidden rounded-xl border border-outline-variant bg-surface shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-outline-variant px-4 py-3">
          <div className="min-w-0">
            <h3 className="font-headline text-sm font-semibold text-foreground">讨论结论预览</h3>
            <p className="mt-0.5 text-[10px] text-foreground/35">本机历史记录</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-xs text-foreground/55 hover:bg-surface-low hover:text-foreground"
          >
            关闭
          </button>
        </div>
        <div className="max-h-[66vh] overflow-auto p-4">
          {loading ? (
            <p className="rounded-md bg-surface-low px-3 py-2 text-xs text-foreground/55">正在加载讨论详情...</p>
          ) : error ? (
            <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</p>
          ) : snapshot ? (
            <div className="space-y-3">
              <section className="rounded-lg border border-outline-variant bg-surface-lowest p-3">
                <div className="mb-1 text-[11px] font-medium text-foreground/45">问题</div>
                <p className="text-sm leading-6 text-foreground">{getSnapshotQuery(snapshot)}</p>
              </section>
              <section className="rounded-lg border border-outline-variant bg-surface-lowest p-3">
                <div className="mb-1 text-[11px] font-medium text-foreground/45">综合结论</div>
                <p className="whitespace-pre-wrap text-sm leading-6 text-foreground/80">
                  {getSnapshotSynthesisText(snapshot)}
                </p>
              </section>
              {turns.length > 0 ? (
                <section className="space-y-2">
                  <div className="text-[11px] font-medium text-foreground/45">讨论过程</div>
                  {turns.map((turn) => (
                    <div key={turn.turn_index} className="rounded-lg border border-outline-variant bg-surface-lowest p-3">
                      <div className="mb-2 text-[11px] font-semibold text-foreground/55">
                        第 {turn.turn_index + 1} 轮
                      </div>
                      <div className="space-y-2">
                        {turn.agent_traces.map((trace) => (
                          <div key={`${turn.turn_index}-${trace.agent_id}`} className="rounded-md bg-surface-low px-2.5 py-2">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="text-xs font-semibold text-foreground/75">
                                {sanitizeDiscussionVisibleText(trace.role_label || getRoleLabel(trace.role), '讨论角色')}
                              </span>
                            </div>
                            <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-foreground/70">
                              {sanitizeDiscussionVisibleText(trace.answer, '回答内容已隐藏，避免显示内部路径或系统字段。')}
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </section>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="flex justify-end gap-2 border-t border-outline-variant px-4 py-3">
          {onRestore ? (
            <button
              type="button"
              onClick={onRestore}
              className="rounded-md bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-500/15"
            >
              恢复归档
            </button>
          ) : null}
          <button
            type="button"
            onClick={onExport}
            className="rounded-md border border-outline-variant px-3 py-1.5 text-xs font-medium text-foreground/65 hover:bg-surface-low"
          >
            导出结构化文件
          </button>
        </div>
      </div>
    </div>
  );
}

interface CitationOverlapParticipant {
  agent_id: string;
  label: string;
  evidence_ids: string[];
}

interface CitationOverlapWarningSummary {
  participants: CitationOverlapParticipant[];
  overlapping_evidence_ids: string[];
  max_pair_overlap: number;
}

function normalizeCitedEvidenceIds(value: readonly string[] | undefined): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return Array.from(new Set(value.map((id) => id.trim()).filter((id) => id.length > 0)));
}

function traceParticipant(trace: DiscussionAgentTrace): CitationOverlapParticipant | null {
  if (!trace.success) {
    return null;
  }
  const evidenceIds = normalizeCitedEvidenceIds(trace.cited_evidence_ids);
  if (evidenceIds.length === 0) {
    return null;
  }
  return {
    agent_id: trace.agent_id,
    label: trace.role_label || getRoleLabel(trace.role) || '讨论角色',
    evidence_ids: evidenceIds,
  };
}

function jaccard(left: readonly string[], right: readonly string[]): number {
  if (left.length === 0 || right.length === 0) {
    return 0;
  }
  const leftSet = new Set(left);
  const rightSet = new Set(right);
  const union = new Set([...leftSet, ...rightSet]);
  let intersection = 0;
  for (const id of leftSet) {
    if (rightSet.has(id)) {
      intersection += 1;
    }
  }
  return union.size > 0 ? intersection / union.size : 0;
}

export function buildCitationOverlapWarningSummary(
  result: DiscussionRunResult,
): CitationOverlapWarningSummary | null {
  const participants = result.turns.flatMap((turn) =>
    turn.agent_traces.flatMap((trace) => {
      const participant = traceParticipant(trace);
      return participant ? [participant] : [];
    }),
  );
  if (participants.length < 2) {
    return null;
  }

  const frequency = new Map<string, number>();
  for (const participant of participants) {
    for (const evidenceId of participant.evidence_ids) {
      frequency.set(evidenceId, (frequency.get(evidenceId) ?? 0) + 1);
    }
  }
  const overlappingEvidenceIds = Array.from(frequency.entries())
    .filter(([, count]) => count > 1)
    .map(([evidenceId]) => evidenceId)
    .sort((left, right) => left.localeCompare(right, 'en'));
  if (overlappingEvidenceIds.length === 0) {
    return null;
  }

  let maxPairOverlap = 0;
  for (let i = 0; i < participants.length; i += 1) {
    for (let j = i + 1; j < participants.length; j += 1) {
      maxPairOverlap = Math.max(
        maxPairOverlap,
        jaccard(participants[i].evidence_ids, participants[j].evidence_ids),
      );
    }
  }

  return {
    participants,
    overlapping_evidence_ids: overlappingEvidenceIds,
    max_pair_overlap: maxPairOverlap,
  };
}

export function DiscussionCitationOverlapWarning({ result }: { result: DiscussionRunResult }) {
  const summary = useMemo(() => buildCitationOverlapWarningSummary(result), [result]);
  if (!summary) {
    return null;
  }

  const visibleEvidenceIds = summary.overlapping_evidence_ids.slice(0, 6);
  const hiddenEvidenceCount = Math.max(0, summary.overlapping_evidence_ids.length - visibleEvidenceIds.length);
  const participantLabels = summary.participants.map((participant) => participant.label);

  return (
    <div
      role="alert"
      data-testid="discussion-citation-overlap-warning"
      className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 dark:border-amber-700/40 dark:bg-amber-500/10"
    >
      <div className="flex items-start gap-2">
        <AlertCircle size={14} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-300" />
        <div className="min-w-0 space-y-1">
          <p className="text-xs font-medium text-amber-900 dark:text-amber-200">
            引用重叠：{summary.overlapping_evidence_ids.length} 条证据被多个角色共同引用
          </p>
          <p className="text-[11px] leading-5 text-amber-800/80 dark:text-amber-100/75">
            最高角色间重叠 {Math.round(summary.max_pair_overlap * 100)}%。请检查是否需要补充独立证据或调整角色分工。
          </p>
          <div className="flex flex-wrap items-center gap-1.5">
            {visibleEvidenceIds.map((evidenceId, index) => (
              <span
                key={evidenceId}
                className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-900 dark:bg-amber-400/15 dark:text-amber-100"
              >
                {formatDiscussionEvidenceLabel(evidenceId, index)}
              </span>
            ))}
            {hiddenEvidenceCount > 0 && (
              <span className="text-[10px] text-amber-800/70 dark:text-amber-100/65">
                +{hiddenEvidenceCount}
              </span>
            )}
            <span className="min-w-0 truncate text-[10px] text-amber-800/60 dark:text-amber-100/55">
              {participantLabels.join(' / ')}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export const DiscussionPanel: React.FC<DiscussionPanelProps> = ({
  onInsertToEditor,
  onHistoryChanged,
  initialQuery,
  initialEvidenceMode,
  defaults,
}) => {
  const navigate = useNavigate();
  const { activeProjectId } = useWriting();
  const [profileStore, setProfileStore] = useState(loadDiscussionProfileStore);
  // User-visible inputs survive across route navigation via localStorage
  // (2026-05-24 user report: switching pages should not wipe the form).
  const [persistedSetup] = useState<PersistedSetup>(() => loadPersistedSetup());
  const [query, setQuery] = useState<string>(persistedSetup.query ?? '');
  const [agents, setAgents] = useState<AgentSlot[]>(() => {
    if (persistedSetup.agents && persistedSetup.agents.length >= 2) {
      return persistedSetup.agents;
    }
    return [
      makeSlot(1, 'proposer', profileStore.profiles.find((profile) => profile.id === 'proposer')),
      makeSlot(2, 'critic', profileStore.profiles.find((profile) => profile.id === 'critic')),
    ];
  });
  const [maxTurns, setMaxTurns] = useState<number>(persistedSetup.maxTurns ?? 3);
  const [autoStop, setAutoStop] = useState<boolean>(persistedSetup.autoStop ?? defaults?.auto_stop ?? false);
  const [minTurns, setMinTurns] = useState<number>(persistedSetup.minTurns ?? defaults?.min_turns ?? 2);
  const [judgeAgentId, setJudgeAgentId] = useState<string>(persistedSetup.judgeAgentId ?? '');
  const [evidenceMode, setEvidenceMode] = useState<DiscussionEvidenceMode>(persistedSetup.evidenceMode ?? 'none');
  const [evidenceTopK, setEvidenceTopK] = useState<number>(
    clampNumber(persistedSetup.evidenceTopK ?? 8, MIN_EVIDENCE_TOP_K, MAX_EVIDENCE_TOP_K),
  );
  const [manualChunkIds, setManualChunkIds] = useState<string>(persistedSetup.manualChunkIds ?? '');
  const [mcpServerIds, setMcpServerIds] = useState<string[]>(persistedSetup.mcpServerIds ?? []);
  const [perAgentMcpServerIds, setPerAgentMcpServerIds] = useState<Record<string, string[]>>(
    () => normalizePerAgentMcpServerIds(persistedSetup.perAgentMcpServerIds, persistedSetup.agents ?? []),
  );
  const [expandedAgentId, setExpandedAgentId] = useState<string | null>(null);
  const [expandedTraceKey, setExpandedTraceKey] = useState<string | null>(null);
  const [credentialAgentId, setCredentialAgentId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<DiscussionRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [setupSaveState, setSetupSaveState] = useState<'idle' | 'saved'>('idle');
  const [elapsedSec, setElapsedSec] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const startedAtRef = useRef<number>(0);
  const notifiedSmartReadHistoryRunIdRef = useRef<string | null>(null);
  const nextAgentIndexRef = useRef(3);
  const projectReasoningBias = useProjectReasoningBiasState(activeProjectId);
  const defaultProjectBiasEnabled = projectReasoningBias.isEnabledForSurface('discussion_agent');
  const projectBiasScopes = projectReasoningBias.payload.scopes;
  const projectBiasAgentIds = projectBiasScopes.discussion_agent_ids;
  const projectBiasProjectWide = projectBiasScopes.project_wide;
  const [projectBiasEnabled, setProjectBiasEnabled] = useState(defaultProjectBiasEnabled);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyQuery, setHistoryQuery] = useState('');
  const [historyMode, setHistoryMode] = useState<'recent' | 'archived'>('recent');
  const [history, setHistory] = useState<DiscussionHistoryPage | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [previewRunId, setPreviewRunId] = useState<string | null>(null);
  const [previewSnapshot, setPreviewSnapshot] = useState<DiscussionRunSnapshot | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const lastAppliedInitialQueryRef = useRef('');
  const normalizedInitialQuery = useMemo(() => (initialQuery ?? '').trim(), [initialQuery]);
  const projectBiasAgentSummary = useMemo(
    () => describeProjectBiasAgentTargets(agents, projectBiasProjectWide, projectBiasAgentIds),
    [agents, projectBiasAgentIds, projectBiasProjectWide],
  );

  useEffect(() => {
    if (!normalizedInitialQuery || lastAppliedInitialQueryRef.current === normalizedInitialQuery) {
      return;
    }
    lastAppliedInitialQueryRef.current = normalizedInitialQuery;
    setQuery(normalizedInitialQuery);
    if (initialEvidenceMode) {
      setEvidenceMode(initialEvidenceMode);
    }
  }, [initialEvidenceMode, normalizedInitialQuery]);

  useEffect(() => {
    setProjectBiasEnabled(defaultProjectBiasEnabled);
  }, [defaultProjectBiasEnabled, activeProjectId]);

  // Persist every setup-form change so navigating away and back keeps the
  // inputs intact. Run-time state (running/result/error) is owned by the
  // DiscussionContext and lives there.
  useEffect(() => {
    persistSetup({
      query,
      agents,
      maxTurns,
      autoStop,
      minTurns,
      judgeAgentId,
      evidenceMode,
      evidenceTopK,
      manualChunkIds,
      mcpServerIds,
      perAgentMcpServerIds,
    });
  }, [query, agents, maxTurns, autoStop, minTurns, judgeAgentId, evidenceMode, evidenceTopK, manualChunkIds, mcpServerIds, perAgentMcpServerIds]);

  // Cross-route persistent discussion session.
  const { session, startSession, cancelSession } = useDiscussion();
  const reloadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const trimmed = historyQuery.trim();
      const next = historyMode === 'archived'
        ? await discussionApi.listArchived({
            page: historyPage,
            page_size: HISTORY_PAGE_SIZE,
            q: trimmed || undefined,
          })
        : trimmed
          ? await discussionApi.searchHistory({
              q: trimmed,
              page: historyPage,
              page_size: HISTORY_PAGE_SIZE,
            })
          : await discussionApi.listHistory({
              page: historyPage,
              page_size: HISTORY_PAGE_SIZE,
            });
      setHistory(next);
    } catch {
      setHistoryError('讨论历史加载失败。');
    } finally {
      setHistoryLoading(false);
    }
  }, [historyMode, historyPage, historyQuery]);

  useEffect(() => {
    void reloadHistory();
  }, [reloadHistory, session.state]);

  useEffect(() => {
    const completedRunId = session.state === 'completed' ? session.finalResult?.run_id : null;
    if (!completedRunId || notifiedSmartReadHistoryRunIdRef.current === completedRunId) {
      return;
    }
    notifiedSmartReadHistoryRunIdRef.current = completedRunId;
    void onHistoryChanged?.();
  }, [onHistoryChanged, session.finalResult?.run_id, session.state]);

  const archiveHistoryRun = useCallback(async (runId: string) => {
    await discussionApi.archiveRun(runId);
    await reloadHistory();
  }, [reloadHistory]);

  const restoreHistoryRun = useCallback(async (runId: string) => {
    await discussionApi.restoreRun(runId);
    setHistoryMode('recent');
    setHistoryPage(1);
    await reloadHistory();
  }, [reloadHistory]);

  const openHistoryPreview = useCallback(async (runId: string) => {
    setPreviewRunId(runId);
    setPreviewSnapshot(null);
    setPreviewError(null);
    setPreviewLoading(true);
    try {
      const snapshot = await discussionApi.getDiscussionRun(runId);
      if (snapshot === null) {
        setPreviewError('找不到这条讨论记录。');
      } else {
        setPreviewSnapshot(snapshot);
      }
    } catch {
      setPreviewError('讨论详情加载失败。');
    } finally {
      setPreviewLoading(false);
    }
  }, []);

  const exportHistoryRun = useCallback(async (runId: string) => {
    const payload = await discussionApi.exportRun(runId, 'json');
    downloadDiscussionExport(payload.filename, payload.content);
  }, []);

  const deleteHistoryRun = useCallback(async (runId: string) => {
    const confirmed = window.confirm('删除这条讨论历史？此操作会移除本机记录。');
    if (!confirmed) {
      return;
    }
    await discussionApi.deleteRun(runId);
    await reloadHistory();
  }, [reloadHistory]);

  // Sync Context session state into local state so existing rendering logic
  // (which references `running` / `result` / `error`) keeps working unchanged.
  // The Context is the source of truth for running state across navigations;
  // local state mirrors it for component-internal derived rendering.
  //
  // B7+ (0.1.8.2 hotfix v3): user reported "已完成 · 2 轮 / 已收到 2 条"
  // but transcript area stays empty. Root cause: result was only filled
  // from session.finalResult (set on done event), and the existing
  // `{result && (<transcript>)}` guard hid the entire turns list during
  // the running window even though liveTraces already had agent outputs.
  // Fix: synthesize a partial result from liveTraces during running so the
  // user sees agents stream in one-by-one; replace with the authoritative
  // finalResult once the done event arrives.
  useEffect(() => {
    setRunning(session.state === 'running');
    if (session.state === 'idle') {
      setExpandedTraceKey(null);
    }
    if (session.finalResult !== null) {
      setResult(session.finalResult);
    } else if (session.liveTraces.length > 0) {
      // Synthesize a minimal DiscussionRunResult shape from liveTraces.
      // liveTraces items lack their original turn_index (the SSE event
      // carries turn_index alongside the trace; we don't fold it into the
      // trace object). Lump all live traces into one "preview turn" so
      // the user at least sees the agent answers stream in; the
      // authoritative finalResult replaces this with the proper
      // per-turn split when the done event arrives.
      const partialTurns = [
        {
          turn_index: 0,
          agent_traces: session.liveTraces,
        },
      ];
      setResult({
        run_id: session.runId ?? 'live',
        turns: partialTurns,
        synthesis: session.synthesis ?? null,
        stopped_early: false,
        convergence: null,
        evidence_pack: null,
      } as unknown as DiscussionRunResult);
    } else if (session.state === 'idle') {
      setResult(null);
    }
    if (session.state === 'cancelled') {
      setError('已停止等待，当前模型调用可能仍在收尾。');
    } else if (session.error !== null) {
      setError(session.error);
    } else if (session.state === 'running' || session.state === 'idle') {
      setError(null);
    }
    if (session.state === 'running' && session.startedAt) {
      startedAtRef.current = session.startedAt;
    }
  }, [
    session.state,
    session.finalResult,
    session.liveTraces,
    session.synthesis,
    session.runId,
    session.error,
    session.startedAt,
  ]);

  const updateAgent = useCallback((id: string, patch: Partial<AgentSlot>) => {
    setAgents((current) => current.map((agent) => (
      agent.id === id ? { ...agent, ...patch } : agent
    )));
  }, []);

  const profileForId = useCallback((profileId: DiscussionProfileId) => {
    const profile = profileStore.profiles.find((item) => item.id === profileId);
    if (profile) return profile;
    return profileStore.profiles[0];
  }, [profileStore.profiles]);

  const applyProfileDefaults = useCallback((agentId: string, profileId: DiscussionProfileId) => {
    const profile = profileForId(profileId);
    if (!profile) return;
    updateAgent(agentId, {
      profileId,
      roleLabel: profile.displayName,
      systemPrompt: profile.systemPrompt,
    });
  }, [profileForId, updateAgent]);

  useEffect(() => {
    const normalizedMinTurns = clampNumber(
      defaults?.min_turns ?? 2,
      DISCUSSION_DEFAULT_BOUNDS.min_turns.min,
      DISCUSSION_DEFAULT_BOUNDS.min_turns.max,
    );
    setAutoStop(typeof persistedSetup.autoStop === 'boolean' ? persistedSetup.autoStop : defaults?.auto_stop ?? false);
    setMinTurns(typeof persistedSetup.minTurns === 'number' ? persistedSetup.minTurns : normalizedMinTurns);
    setMaxTurns((current) => Math.max(current, normalizedMinTurns));
  }, [defaults?.auto_stop, defaults?.min_turns, persistedSetup.autoStop, persistedSetup.minTurns]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === 'scholar-ai-discussion-profiles') {
        setProfileStore(loadDiscussionProfileStore());
      }
    };
    const onStoreChanged = () => {
      setProfileStore(loadDiscussionProfileStore());
    };
    window.addEventListener('storage', onStorage);
    window.addEventListener(DISCUSSION_PROFILE_STORE_CHANGED_EVENT, onStoreChanged);
    return () => {
      window.removeEventListener('storage', onStorage);
      window.removeEventListener(DISCUSSION_PROFILE_STORE_CHANGED_EVENT, onStoreChanged);
    };
  }, []);

  useEffect(() => {
    if (!running) {
      setElapsedSec(0);
      return;
    }
    startedAtRef.current = Date.now();
    const t = setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - startedAtRef.current) / 1000));
    }, 500);
    return () => clearInterval(t);
  }, [running]);

  const fromProjectBlocked = evidenceMode === 'from_project' && !activeProjectId;
  const manualBlocked = evidenceMode === 'manual_chunk_ids' && !manualChunkIds.trim();
  const canRun = query.trim().length > 0 && agents.length >= 2 && !fromProjectBlocked && !manualBlocked;
  const historyItems = Array.isArray(history?.items) ? history.items : [];
  const historyTotal = typeof history?.total === 'number' && Number.isFinite(history.total) ? history.total : 0;
  const historyCurrentPage = typeof history?.page === 'number' && Number.isFinite(history.page) ? history.page : historyPage;
  const historyPageSize = typeof history?.page_size === 'number' && Number.isFinite(history.page_size) && history.page_size > 0
    ? history.page_size
    : HISTORY_PAGE_SIZE;
  const configuredPrompts = agents.filter((agent) => {
    const profile = profileForId(agent.profileId);
    return Boolean((agent.systemPrompt || profile?.systemPrompt || '').trim());
  }).length;
  const evidenceLabel = evidenceMode === 'none'
    ? '无证据'
    : evidenceMode === 'from_project'
      ? '当前项目'
      : '手动证据';
  const defaultJudgeAgentId = agents.find((agent) => agent.profileId === profileStore.defaultJudgeProfileId)?.id
    ?? agents.find((agent) => agent.profileId === 'synthesizer')?.id
    ?? agents[0]?.id
    ?? '';
  const persistedJudgeAgentId = defaults?.convergence_judge_agent_id?.trim() ?? '';
  const judgeProfileMissing = autoStop && !agents.some((agent) => agent.profileId === profileStore.defaultJudgeProfileId);
  const turnWarning = maxTurns > DISCUSSION_TURN_WARNING_THRESHOLD || (autoStop && minTurns > DISCUSSION_TURN_WARNING_THRESHOLD);
  const incompleteRoleApiCount = agents.filter((agent) => {
    const profile = profileForId(agent.profileId);
    return profile?.apiMode === 'inline' && !profile.credentialId.trim() && !profile.apiKey.trim();
  }).length;

  useEffect(() => {
    setJudgeAgentId((current) => {
      if (persistedJudgeAgentId && agents.some((agent) => agent.id === persistedJudgeAgentId)) {
        return persistedJudgeAgentId;
      }
      return agents.some((agent) => agent.id === current) ? current : defaultJudgeAgentId;
    });
  }, [agents, defaultJudgeAgentId, persistedJudgeAgentId]);

  const addAgent = (profileId?: DiscussionProfileId) => {
    if (agents.length >= MAX_DISCUSSION_AGENTS) return;
    const nextProfileId = profileId ?? profileStore.profiles.find((profile) => (
      !agents.some((agent) => agent.profileId === profile.id)
    ))?.id ?? profileStore.profiles[0]?.id ?? 'proposer';
    const profile = profileForId(nextProfileId);
    const nextIndex = nextAgentIndexRef.current;
    nextAgentIndexRef.current += 1;
    setAgents([
      ...agents,
      {
        ...makeSlot(nextIndex, nextProfileId),
        roleLabel: profile?.displayName ?? DISCUSSION_ROLE_LABELS.custom,
        systemPrompt: profile?.systemPrompt ?? '',
      },
    ]);
  };

  const removeAgent = (id: string) => {
    if (agents.length <= 2) return;
    setAgents(agents.filter(a => a.id !== id));
    setPerAgentMcpServerIds(({ [id]: _removed, ...rest }) => rest);
  };

  const setAgentMcpServerIds = useCallback((agentId: string, serverIds: string[]) => {
    setPerAgentMcpServerIds((current) => {
      const next = { ...current };
      if (serverIds.length === 0) {
        delete next[agentId];
      } else {
        next[agentId] = [...serverIds];
      }
      return next;
    });
  }, []);

  const handleRun = async () => {
    if (!query.trim()) return;
    if (agents.length < 2) return;

    let agentConfigs: DiscussionAgentConfig[];
    try {
      agentConfigs = agents.map((agent) => {
        const profile = profileForId(agent.profileId);
        if (!profile) {
          throw new Error('讨论角色配置缺失。');
        }
        const agentConfig = buildAgentConfigFromProfile(profile, {
          agentId: agent.id,
          roleLabel: agent.roleLabel,
          systemPrompt: agent.systemPrompt,
        });
        const runtimeCredentialId = agent.runtimeCredentialId?.trim();
        if (runtimeCredentialId) {
          agentConfig.credential_id = runtimeCredentialId;
          agentConfig.llm = null;
          agentConfig.strategy_hint = null;
          agentConfig.category = null;
          agentConfig.metadata = {
            ...(agentConfig.metadata ?? {}),
            credential_source: 'discussion_runtime_picker',
          };
        }
        return agentConfig;
      });
    } catch (err) {
      setError(formatDiscussionRunError(err));
      return;
    }

    const config: DiscussionRunConfig = {
      project_id: activeProjectId || null,
      query: query.trim(),
      agent_configs: agentConfigs,
      max_turns: maxTurns,
      evidence_mode: evidenceMode,
      evidence_top_k: clampNumber(Math.round(evidenceTopK), MIN_EVIDENCE_TOP_K, MAX_EVIDENCE_TOP_K),
      synthesis_strategy: 'synthesize',
      timeout_seconds: 120,
    };
    setExpandedTraceKey(null);
    if (evidenceMode === 'from_project' && activeProjectId) {
      config.project_id = activeProjectId;
    }
    if (activeProjectId && defaultProjectBiasEnabled) {
      config.project_reasoning_bias_enabled = projectBiasEnabled;
    }
    if (evidenceMode === 'manual_chunk_ids') {
      const ids = manualChunkIds.split(/[,\s]+/).map(s => s.trim()).filter(Boolean);
      if (ids.length > 0) {
        config.evidence_chunk_ids = ids;
      }
    }
    if (autoStop) {
      config.auto_stop = true;
      config.min_turns = Math.min(minTurns, maxTurns);
      if (judgeAgentId && agents.some((agent) => agent.id === judgeAgentId)) {
        config.convergence_judge_agent_id = judgeAgentId;
      }
    }
    const perAgentMcp = normalizePerAgentMcpServerIds(perAgentMcpServerIds, agents);
    const hasPerAgentMcp = Object.values(perAgentMcp).some((ids) => ids.length > 0);
    if (mcpServerIds.length > 0 || hasPerAgentMcp) {
      config.mcp_overrides = hasPerAgentMcp
        ? {
            scope_type: 'agent',
            server_ids: [...mcpServerIds],
            per_agent: perAgentMcp,
          }
        : {
            scope_type: 'surface',
            server_ids: [...mcpServerIds],
          };
    }

    // Delegate run lifecycle to the cross-route Context.
    // The Context owns the SSE stream + AbortController + fallback to
    // non-streaming runDiscussion; local state mirrors via useEffect above.
    await startSession(config);
  };

  const handleStop = () => {
    cancelSession();
  };

  const handleInsertSynthesis = () => {
    if (result?.synthesis?.text && onInsertToEditor) {
      onInsertToEditor(formatDiscussionSynthesisText(result.synthesis.text));
    }
  };

  const handleSaveAsKnowledgeDiscussionDefault = () => {
    persistSetup({
      query,
      agents,
      maxTurns,
      autoStop,
      minTurns,
      judgeAgentId,
      evidenceMode,
      evidenceTopK,
      manualChunkIds,
      mcpServerIds,
      perAgentMcpServerIds,
    });
    setSetupSaveState('saved');
    window.setTimeout(() => setSetupSaveState('idle'), 2400);
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="grid gap-2 [grid-template-columns:repeat(auto-fit,minmax(120px,1fr))]">
        <div className="rounded-lg border border-outline-variant bg-surface-lowest px-3 py-2">
          <div className="flex items-center gap-1.5 text-[11px] text-foreground/45">
            <Layers3 size={12} />
            智能体
          </div>
            <p className="mt-1 font-mono text-sm font-semibold text-foreground">{agents.length}/{MAX_DISCUSSION_AGENTS}</p>
        </div>
        <div className="rounded-lg border border-outline-variant bg-surface-lowest px-3 py-2">
          <div className="flex items-center gap-1.5 text-[11px] text-foreground/45">
            <Route size={12} />
            证据
          </div>
          <p className="mt-1 truncate text-sm font-semibold text-foreground">{evidenceLabel}</p>
        </div>
        <div className="rounded-lg border border-outline-variant bg-surface-lowest px-3 py-2">
          <div className="flex items-center gap-1.5 text-[11px] text-foreground/45">
            <Zap size={12} />
            终止
          </div>
          <p className="mt-1 text-sm font-semibold text-foreground">{autoStop ? `${minTurns}+ 轮` : '关闭'}</p>
        </div>
      </div>

      <div className="rounded-lg border border-outline-variant bg-surface-lowest p-3 shadow-sm">
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="font-headline text-sm font-semibold text-foreground">讨论历史</h2>
              <p className="mt-0.5 text-xs text-foreground/45">
                {historyMode === 'archived' ? '归档记录为只读查看。' : '最近运行记录支持分页、搜索和归档。'}
              </p>
            </div>
            <div className="inline-flex rounded-md border border-outline-variant/60 bg-surface-low p-0.5">
              <button
                type="button"
                onClick={() => {
                  setHistoryMode('recent');
                  setHistoryPage(1);
                }}
                className={cn(
                  'rounded px-2 py-1 text-[11px] font-medium transition-colors',
                  historyMode === 'recent' ? 'bg-primary text-primary-foreground' : 'text-foreground/55 hover:text-foreground',
                )}
              >
                最近
              </button>
              <button
                type="button"
                onClick={() => {
                  setHistoryMode('archived');
                  setHistoryPage(1);
                }}
                className={cn(
                  'rounded px-2 py-1 text-[11px] font-medium transition-colors',
                  historyMode === 'archived' ? 'bg-primary text-primary-foreground' : 'text-foreground/55 hover:text-foreground',
                )}
              >
                归档
              </button>
            </div>
          </div>
          <label className="flex min-h-9 items-center gap-2 rounded-md border border-outline-variant/60 bg-surface-low px-2">
            <Search size={13} className="text-foreground/35" />
            <input
              value={historyQuery}
              onChange={(event) => {
                setHistoryQuery(event.target.value);
                setHistoryPage(1);
              }}
              placeholder="搜索问题或综合结论"
              className="min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none placeholder:text-foreground/30"
            />
          </label>
          {historyError ? (
            <p className="rounded-md border border-rose-200 bg-rose-50 px-2 py-1.5 text-[11px] text-rose-700">
              {historyError}
            </p>
          ) : null}
          <div className="space-y-2" data-testid="discussion-history-list">
            {historyLoading ? (
              <p className="rounded-md bg-surface-low px-2 py-2 text-[11px] text-foreground/45">正在加载历史...</p>
            ) : historyItems.length > 0 ? (
              historyItems.map((item) => (
                <div key={item.run_id} className="rounded-md border border-outline-variant/50 bg-surface-low px-3 py-2">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="rounded bg-surface-lowest px-1.5 py-0.5 text-[10px] text-foreground/50">
                          {discussionHistoryStateLabel(item.state)}
                        </span>
                        {item.archived ? (
                          <span className="inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">
                            <Archive size={10} />
                            归档
                          </span>
                        ) : null}
                        <span className="text-[10px] text-foreground/35">{formatDiscussionTimestamp(item.updated_at)}</span>
                        <span className="text-[10px] text-foreground/35">{item.turn_count} 轮 · {item.agent_count} 角色</span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs font-medium text-foreground/75">
                        {item.query || '未记录问题'}
                      </p>
                      {item.synthesis_preview ? (
                        <p className="mt-1 line-clamp-2 text-[11px] leading-5 text-foreground/45">{item.synthesis_preview}</p>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={() => void openHistoryPreview(item.run_id)}
                        className="rounded-md p-1.5 text-foreground/35 transition-colors hover:bg-surface-lowest hover:text-foreground"
                        title="查看讨论结论"
                        aria-label="查看讨论结论"
                      >
                        <Search size={13} />
                      </button>
                      {!item.archived ? (
                        <button
                          type="button"
                          onClick={() => void archiveHistoryRun(item.run_id)}
                          className="rounded-md p-1.5 text-foreground/35 transition-colors hover:bg-surface-lowest hover:text-foreground"
                          title="归档"
                          aria-label="归档讨论"
                        >
                          <Archive size={13} />
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => void restoreHistoryRun(item.run_id)}
                          className="rounded-md p-1.5 text-foreground/35 transition-colors hover:bg-emerald-50 hover:text-emerald-600"
                          title="恢复到最近记录"
                          aria-label="恢复讨论"
                        >
                          <RefreshCw size={13} />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => void exportHistoryRun(item.run_id)}
                        className="rounded-md p-1.5 text-foreground/35 transition-colors hover:bg-surface-lowest hover:text-foreground"
                        title="导出结构化文件"
                        aria-label="导出讨论"
                      >
                        <Download size={13} />
                      </button>
                      <button
                        type="button"
                        onClick={() => void deleteHistoryRun(item.run_id)}
                        className="rounded-md p-1.5 text-foreground/35 transition-colors hover:bg-red-50 hover:text-red-500"
                        title="删除"
                        aria-label="删除讨论"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <p className="rounded-md bg-surface-low px-2 py-2 text-[11px] text-foreground/45">暂无讨论历史。</p>
            )}
          </div>
          {history && historyTotal > HISTORY_PAGE_SIZE ? (
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] text-foreground/40">
                第 {historyCurrentPage} 页 / 共 {Math.ceil(historyTotal / historyPageSize)} 页
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setHistoryPage((page) => Math.max(1, page - 1))}
                  disabled={historyCurrentPage <= 1}
                  className="rounded-md border border-outline-variant/60 p-1.5 text-foreground/45 disabled:opacity-35"
                  aria-label="上一页讨论历史"
                >
                  <ChevronLeft size={13} />
                </button>
                <button
                  type="button"
                  onClick={() => setHistoryPage((page) => page + 1)}
                  disabled={historyCurrentPage * historyPageSize >= historyTotal}
                  className="rounded-md border border-outline-variant/60 p-1.5 text-foreground/45 disabled:opacity-35"
                  aria-label="下一页讨论历史"
                >
                  <ChevronRight size={13} />
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {previewRunId ? (
        <DiscussionHistoryPreviewModal
          snapshot={previewSnapshot}
          loading={previewLoading}
          error={previewError}
          onClose={() => {
            setPreviewRunId(null);
            setPreviewSnapshot(null);
            setPreviewError(null);
          }}
          onExport={() => void exportHistoryRun(previewRunId)}
          onRestore={previewSnapshot?.archived ? () => void restoreHistoryRun(previewRunId) : undefined}
        />
      ) : null}

      {/* Config panel */}
      <div className="rounded-lg border border-outline-variant bg-surface-lowest p-4 shadow-sm">
        <div className="mb-4 flex flex-col gap-3">
          <div className="min-w-0">
            <h2 className="font-headline text-sm font-semibold text-foreground">讨论编排</h2>
            <p className="mt-0.5 text-xs text-foreground/45">选择角色、证据来源和结束条件</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleSaveAsKnowledgeDiscussionDefault}
              className={cn(
                'inline-flex min-h-8 items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[11px] font-medium transition-colors',
                setupSaveState === 'saved'
                  ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                  : 'border-outline-variant bg-surface-high text-foreground/65 hover:border-primary/35 hover:text-primary',
              )}
              title="以后从知识库或工作台打开多智能体讨论时复用当前角色和参数"
            >
              {setupSaveState === 'saved' ? <CheckCircle2 size={12} /> : <Save size={12} />}
              {setupSaveState === 'saved' ? '已保存默认' : '保存为知识库讨论默认'}
            </button>
            {/* Live session state pill — separate from "可运行" (which only
                reflects setup-form validity). 2026-05-24: users couldn't tell
                whether a discussion had ever started, completed, or errored. */}
            {session.state !== 'idle' && (
              <span className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-label',
                session.state === 'running' && 'bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300',
                session.state === 'completed' && 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300',
                session.state === 'cancelled' && 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
                session.state === 'error' && 'bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300',
              )}>
                <span className={cn('h-1.5 w-1.5 rounded-full',
                  session.state === 'running' && 'bg-blue-500 dark:bg-blue-400 animate-pulse',
                  session.state === 'completed' && 'bg-emerald-500 dark:bg-emerald-400',
                  session.state === 'cancelled' && 'bg-amber-500 dark:bg-amber-400',
                  session.state === 'error' && 'bg-rose-500 dark:bg-rose-400',
                )} />
                {session.state === 'running' && `运行中 · 已收到 ${session.liveTraces.length} 条`}
                {session.state === 'completed' && `已完成 · ${session.finalResult?.turns?.length ?? 0} 轮`}
                {session.state === 'cancelled' && '已取消'}
                {session.state === 'error' && '出错'}
              </span>
            )}
            {session.runtimeJobId ? (
              <>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-high px-2.5 py-1 text-[11px] font-label text-foreground/55">
                  任务：{session.runtimeJobId}
                </span>
                <button
                  type="button"
                  onClick={() => navigate('/jobs')}
                  className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-outline-variant bg-surface-high px-2.5 py-1.5 text-[11px] font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary"
                >
                  任务中心
                </button>
              </>
            ) : null}
            <span className={cn(
              'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-label',
              canRun ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' : 'bg-surface-high text-foreground/45',
            )}>
              <span className={cn('h-1.5 w-1.5 rounded-full', canRun ? 'bg-emerald-500 dark:bg-emerald-400' : 'bg-foreground/25')} />
              {canRun ? '可运行' : '待配置'}
            </span>
          </div>
        </div>

        <div className="space-y-4">
        <div>
          <label className="font-label text-xs font-medium text-foreground/70 mb-1.5 block">讨论问题</label>
          <textarea
            rows={2}
            placeholder="输入你想让多位智能体讨论的问题…"
            value={query}
            onChange={e => setQuery(e.target.value)}
            className="w-full rounded-lg border border-outline-variant/60 bg-surface-low px-3 py-2 text-sm text-foreground transition-colors placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none resize-none"
          />
        </div>

        <div>
          <div className="mb-2 flex flex-col gap-2">
            <div>
              <label className="font-label text-xs font-medium text-foreground/70">角色配置（{agents.length}/{MAX_DISCUSSION_AGENTS}）</label>
              <p className="mt-0.5 text-[11px] text-foreground/45">角色来自系统设置，新增角色和绑定 API 后会自动出现在这里。</p>
            </div>
            <div className="flex flex-wrap items-center gap-1">
              <button
                type="button"
                onClick={() => navigate('/settings?section=discussion')}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-foreground/50 transition-colors hover:bg-surface-high hover:text-foreground"
              >
                <Settings2 size={12} /> 管理角色与 API
              </button>
              <button
                type="button"
                onClick={() => addAgent()}
                disabled={agents.length >= MAX_DISCUSSION_AGENTS}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-primary transition-colors hover:bg-primary/10 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Plus size={12} /> 添加
              </button>
            </div>
          </div>
          <div className="grid gap-2 [grid-template-columns:repeat(auto-fit,minmax(260px,1fr))]">
            {agents.map((agent) => {
              const profile = profileForId(agent.profileId);
              const runtimeCredentialActive = Boolean(agent.runtimeCredentialId?.trim());
              return (
              <div key={agent.id} className="group rounded-lg border border-outline-variant/60 bg-surface-low p-2 transition-colors hover:border-primary/25">
                <div className="grid gap-2 [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
                  <label className="space-y-1">
                    <span className="text-[10px] font-label text-foreground/45">角色</span>
                    <select
                      value={agent.profileId}
                      onChange={e => {
                        const next = e.target.value;
                        if (isDiscussionProfileId(next)) {
                          applyProfileDefaults(agent.id, next);
                        }
                      }}
                      className="w-full rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1.5 text-xs font-label text-foreground focus:border-primary/40 focus:outline-none"
                    >
                      {profileStore.profiles.map((profileOption) => (
                        <option key={profileOption.id} value={profileOption.id}>{profileOption.displayName}</option>
                      ))}
                    </select>
                  </label>
                  <label className="space-y-1">
                    <span className="text-[10px] font-label text-foreground/45">本次名称</span>
                    <input
                      type="text"
                      value={agent.roleLabel}
                      onChange={e => updateAgent(agent.id, { roleLabel: e.target.value })}
                      placeholder="显示名称"
                      className="w-full rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1.5 text-xs text-foreground/70 placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
                    />
                  </label>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <span
                    className={cn(
                      'inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-label',
                      projectBiasEnabled && defaultProjectBiasEnabled && projectBiasAppliesToAgent(agent, projectBiasProjectWide, projectBiasAgentIds)
                        ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
                        : 'bg-surface-lowest text-foreground/40',
                    )}
                  >
                    <CheckCircle2 size={11} />
                    {projectBiasEnabled && defaultProjectBiasEnabled && projectBiasAppliesToAgent(agent, projectBiasProjectWide, projectBiasAgentIds)
                      ? '偏置作用中'
                      : '偏置未命中'}
                  </span>
                  <span
                    className={cn(
                      'min-w-[160px] flex-1 truncate rounded-md px-2 py-1 text-[10px]',
                      runtimeCredentialActive
                        ? 'bg-primary/10 text-primary'
                        : profile?.apiMode === 'inline' && !profile.model.trim()
                        ? 'bg-amber-50 text-amber-700'
                        : 'bg-surface-lowest text-foreground/45',
                    )}
                    title={runtimeCredentialActive
                      ? '本次讨论固定使用已保存 API 配置。'
                      : profile ? `${DISCUSSION_API_MODE_LABELS[profile.apiMode]} · ${describeApiBinding(profile)}` : DISCUSSION_API_MODE_LABELS.default}
                  >
                    {runtimeCredentialActive ? '本次 API 已选择' : profile ? describeApiBinding(profile) : DISCUSSION_API_MODE_LABELS.default}
                  </span>
                  <button
                    type="button"
                    onClick={() => setCredentialAgentId(prev => prev === agent.id ? null : agent.id)}
                    className={cn(
                      'inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-label transition-colors',
                      runtimeCredentialActive
                        ? 'bg-primary/10 text-primary hover:bg-primary/20'
                        : 'text-foreground/40 hover:bg-surface-lowest hover:text-foreground/70',
                    )}
                    title="选择本次调用 API"
                  >
                    <Key size={11} />
                    API
                  </button>
                  <button
                    type="button"
                    onClick={() => setExpandedAgentId(prev => prev === agent.id ? null : agent.id)}
                    className={cn(
                      'text-[10px] px-2 py-1 rounded-md font-label transition-colors',
                      agent.systemPrompt
                        ? 'text-primary bg-primary/10 hover:bg-primary/20'
                        : 'text-foreground/40 hover:text-foreground/70'
                    )}
                    title="自定义系统提示"
                  >
                    提示词
                  </button>
                  <button
                    type="button"
                    onClick={() => removeAgent(agent.id)}
                    disabled={agents.length <= 2}
                    className="rounded-md p-1 text-foreground/30 transition-colors hover:bg-red-50 hover:text-red-500 disabled:cursor-not-allowed disabled:opacity-30"
                    aria-label="删除角色"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
                {expandedAgentId === agent.id && (
                  <div className="mt-2">
                    <textarea
                      rows={3}
                      value={agent.systemPrompt}
                      onChange={e => updateAgent(agent.id, { systemPrompt: e.target.value })}
                      placeholder="自定义系统提示（可选，例如：扮演方法学批评者，重点关注样本偏差与统计有效性）"
                      className="w-full rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1.5 text-xs text-foreground placeholder:text-foreground/30 resize-none focus:border-primary/40 focus:outline-none"
                    />
                  </div>
                )}
                {credentialAgentId === agent.id && (
                  <div className="mt-2 rounded-md border border-outline-variant/50 bg-surface-lowest p-2">
                    <CredentialPicker
                      requirement={buildRuntimeCredentialRequirement(agent, profile)}
                      value={agent.runtimeCredentialId?.trim() || null}
                      onChange={(credentialId) => updateAgent(agent.id, { runtimeCredentialId: credentialId ?? '' })}
                      category="generation"
                      disabled={running}
                      onJumpToCreate={() => navigate('/settings?section=credentials')}
                    />
                    {agent.runtimeCredentialId?.trim() ? (
                      <button
                        type="button"
                        onClick={() => updateAgent(agent.id, { runtimeCredentialId: '' })}
                        disabled={running}
                        className="mt-2 text-[11px] text-foreground/45 transition-colors hover:text-red-500 disabled:opacity-50"
                      >
                        清除本次 API 绑定
                      </button>
                    ) : null}
                  </div>
                )}
              </div>
              );
            })}
          </div>
          {incompleteRoleApiCount > 0 && (
            <div className="mt-2 flex items-start gap-2 rounded-md border border-amber-200/70 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800">
              <AlertCircle size={13} className="mt-0.5 shrink-0" />
              <span>{incompleteRoleApiCount} 个角色还没有保存 API。可继续运行并使用聊天与生成设置，也可以先到系统设置中补齐。</span>
            </div>
          )}
          {configuredPrompts > 0 && (
            <p className="mt-2 text-[11px] text-foreground/45">{configuredPrompts} 个角色已配置提示词。</p>
          )}
        </div>

        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-outline-variant/50 bg-surface-low px-3 py-2">
            <ProjectBiasSurfaceToggle
              enabled={projectBiasEnabled && defaultProjectBiasEnabled}
              label={projectBiasEnabled && defaultProjectBiasEnabled ? '讨论偏置已启用' : '讨论偏置已关闭'}
              disabled={!defaultProjectBiasEnabled || projectReasoningBias.loading || running}
              onChange={setProjectBiasEnabled}
            />
            <span className="min-w-0 flex-1 text-[11px] leading-5 text-foreground/45">
              {defaultProjectBiasEnabled ? `${projectBiasAgentSummary} 仅影响本次讨论。` : '当前项目未启用讨论角色偏置。'}
            </span>
          </div>
          <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
            <div className="flex items-center gap-2 rounded-lg border border-outline-variant/60 bg-surface-low px-2 py-2">
              <label className="font-label text-xs text-foreground/70">轮次</label>
              <input
                type="number"
                min={DISCUSSION_DEFAULT_BOUNDS.min_turns.min}
                max={DISCUSSION_DEFAULT_BOUNDS.min_turns.max}
                value={maxTurns}
                onChange={e => setMaxTurns(clampNumber(
                  Number(e.target.value),
                  DISCUSSION_DEFAULT_BOUNDS.min_turns.min,
                  DISCUSSION_DEFAULT_BOUNDS.min_turns.max,
                ))}
                className="w-14 rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1 text-center text-xs text-foreground"
              />
            </div>
            <button
              type="button"
              onClick={running ? handleStop : handleRun}
              disabled={!running && !canRun}
              className={cn(
                'flex min-h-10 items-center justify-center gap-2 rounded-lg px-4 py-2 font-label text-sm font-medium transition-all',
                running
                  ? 'bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100'
                  : 'bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50',
              )}
            >
              {running ? <Square size={12} /> : <Send size={14} />}
              {running ? `停止等待 · ${elapsedSec}s` : '开始讨论'}
            </button>
          </div>
          {turnWarning ? (
            <p className="rounded-md border border-amber-200/70 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800">
              超过 {DISCUSSION_TURN_WARNING_THRESHOLD} 轮会明显增加耗时和模型调用成本。
            </p>
          ) : null}
        </div>

        <div className="rounded-lg border border-outline-variant/50 bg-surface-low px-3 py-2">
          <div className="grid items-center gap-2 [grid-template-columns:repeat(auto-fit,minmax(160px,1fr))]">
            <label className="flex items-center gap-1.5 whitespace-nowrap font-label text-xs text-foreground/70">
              <Route size={12} className="text-primary/70" />
              证据来源
            </label>
            <select
              value={evidenceMode}
              onChange={e => setEvidenceMode(e.target.value as DiscussionEvidenceMode)}
              className="w-full rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1.5 text-xs text-foreground"
            >
              <option value="none">无</option>
              <option value="from_project" disabled={!activeProjectId}>
                {activeProjectId ? '当前项目' : '当前项目（未选择）'}
              </option>
              <option value="manual_chunk_ids">手动证据编号</option>
            </select>
            <label className="flex items-center gap-2">
              <span className="whitespace-nowrap text-[11px] text-foreground/55">证据 Top-K</span>
              <input
                type="number"
                min={MIN_EVIDENCE_TOP_K}
                max={MAX_EVIDENCE_TOP_K}
                step={1}
                value={evidenceTopK}
                onChange={e => setEvidenceTopK(clampNumber(
                  Math.round(Number(e.target.value)),
                  MIN_EVIDENCE_TOP_K,
                  MAX_EVIDENCE_TOP_K,
                ))}
                aria-label="讨论证据 Top-K"
                className="w-16 rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1.5 text-center text-xs text-foreground"
              />
            </label>
            {evidenceMode === 'manual_chunk_ids' && (
              <input
                type="text"
                value={manualChunkIds}
                onChange={e => setManualChunkIds(e.target.value)}
                placeholder="证据编号，用逗号分隔"
                className="min-w-0 w-full rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1.5 text-xs text-foreground placeholder:text-foreground/30"
              />
            )}
            {fromProjectBlocked && (
              <span className="text-[11px] text-amber-600">需要先在写作工作台选择项目</span>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-outline-variant/50 bg-surface-low px-3 py-2 space-y-2">
          <McpScopePicker
            selected={mcpServerIds}
            onChange={setMcpServerIds}
            hideWhenEmpty
          />
          <p className="text-[10px] text-foreground/40">
            全局 MCP 是本次讨论的默认工具范围；需要隔离时，可在下方为单个角色覆盖。
          </p>
          {mcpServerIds.length > 0 || Object.keys(perAgentMcpServerIds).length > 0 ? (
            <div className="space-y-2 rounded-md border border-outline-variant/50 bg-surface-lowest px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="font-label text-[11px] font-medium text-foreground/65">按角色隔离 MCP</span>
                <span className="text-[10px] text-foreground/40">空值沿用全局范围</span>
              </div>
              <div className="space-y-2">
                {agents.map((agent) => {
                  const selectedForAgent = perAgentMcpServerIds[agent.id] ?? [];
                  const label = agent.roleLabel || profileForId(agent.profileId)?.displayName || getRoleLabel(profileForId(agent.profileId)?.role ?? 'custom');
                  return (
                    <div key={`mcp-agent-${agent.id}`} className="rounded-md border border-outline-variant/40 bg-surface-low px-2 py-2">
                      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                        <span className="truncate text-[11px] font-medium text-foreground/70">{label}</span>
                        {selectedForAgent.length > 0 ? (
                          <button
                            type="button"
                            onClick={() => setAgentMcpServerIds(agent.id, [])}
                            className="text-[10px] text-foreground/40 transition-colors hover:text-red-500"
                          >
                            清除覆盖
                          </button>
                        ) : null}
                      </div>
                      <McpScopePicker
                        selected={selectedForAgent}
                        onChange={(next) => setAgentMcpServerIds(agent.id, next)}
                        hideWhenEmpty
                        className="text-[10px]"
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}
        </div>

        <div className="rounded-lg border border-outline-variant/50 bg-surface-low px-3 py-2">
          <label className="flex cursor-pointer select-none items-center justify-between gap-3 text-xs text-foreground/70">
            <span className="flex items-center gap-1.5">
              <SlidersHorizontal size={12} className="text-primary/70" />
              自动停止
            </span>
            <span className={cn('relative inline-flex h-5 w-9 items-center rounded-full transition-colors', autoStop ? 'bg-primary' : 'bg-foreground/15')}>
              <input
                type="checkbox"
                checked={autoStop}
                onChange={e => setAutoStop(e.target.checked)}
                className="sr-only"
              />
              <span className={cn('inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform', autoStop ? 'translate-x-4' : 'translate-x-0.5')} />
            </span>
          </label>
          {autoStop && (
            <div className="mt-3 grid gap-2 [grid-template-columns:repeat(auto-fit,minmax(170px,1fr))]">
              <div className="flex items-center justify-between gap-2">
                <label className="font-label text-xs text-foreground/70">最小轮次</label>
                <input
                  type="number"
                  min={DISCUSSION_DEFAULT_BOUNDS.min_turns.min}
                  max={DISCUSSION_DEFAULT_BOUNDS.min_turns.max}
                  value={minTurns}
                  onChange={e => setMinTurns(clampNumber(
                    Number(e.target.value),
                    DISCUSSION_DEFAULT_BOUNDS.min_turns.min,
                    DISCUSSION_DEFAULT_BOUNDS.min_turns.max,
                  ))}
                  className="w-14 rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1 text-center text-xs text-foreground"
                />
              </div>
              <div className="flex flex-col items-stretch gap-1">
                <label className="font-label text-xs text-foreground/70" htmlFor="discussion-judge-agent">裁判角色</label>
                <select
                  id="discussion-judge-agent"
                  value={judgeAgentId}
                  onChange={(e) => setJudgeAgentId(e.target.value)}
                  className="min-w-0 w-full rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1 text-xs text-foreground focus:border-primary/40 focus:outline-none"
                >
                  {agents.map((a) => (
                    <option key={a.id} value={a.id}>{a.roleLabel || profileForId(a.profileId)?.displayName || getRoleLabel(profileForId(a.profileId)?.role ?? 'custom')}</option>
                  ))}
                </select>
              </div>
              {judgeProfileMissing && agents.length < MAX_DISCUSSION_AGENTS ? (
                <button
                  type="button"
                  onClick={() => addAgent(profileStore.defaultJudgeProfileId)}
                  className="w-full rounded-md border border-primary/25 bg-primary/8 px-2 py-1 text-xs text-primary transition-colors hover:bg-primary/12"
                >
                  添加裁判角色
                </button>
              ) : null}
            </div>
          )}
        </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg">
          <XCircle size={14} className="text-red-500 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-red-700">{error}</p>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-3">
          {result.stopped_early && result.convergence && (
            <div className="flex items-center gap-2 px-3 py-2 bg-emerald-50 border border-emerald-200 rounded-lg dark:bg-emerald-500/10 dark:border-emerald-700/40">
              <Zap size={12} className="text-emerald-600 dark:text-emerald-400" />
              <span className="text-xs text-emerald-800 dark:text-emerald-300">
                早停 · 收敛于第 {(result.convergence.decision_turn_index ?? 0) + 1} 轮 / 共 {result.turns.length} 轮
              </span>
              {result.convergence.judge_calls.length > 0 && (
                <span className="ml-auto text-[10px] text-emerald-700/70 font-mono">
                  相似度 {result.convergence.judge_calls.at(-1)?.similarity.toFixed(2)}
                </span>
              )}
            </div>
          )}
          {result.convergence && (result.convergence.judge_errors.length > 0) && (
            <div className="flex items-start gap-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg">
              <XCircle size={12} className="text-amber-600 mt-0.5 flex-shrink-0" />
              <span className="text-[11px] text-amber-800">
                收敛检查有 {result.convergence.judge_errors.length} 项失败（已记录但未阻断讨论）
              </span>
            </div>
          )}
          <DiscussionCitationOverlapWarning result={result} />
          {/* Evidence pack — anchor cards for cited_evidence_ids pills.
              Each card carries id={evidenceSnippetDomId(eid)} so the
              per-trace pill onClick handler can scroll the card into view. */}
          <DiscussionEvidencePackSection result={result} />
          {/* Turns */}
          {result.turns.map(turn => (
            <div key={turn.turn_index} className="space-y-2">
              <h4 className="font-label text-[10px] font-medium text-foreground/40 uppercase tracking-wider">
                第 {turn.turn_index + 1} 轮
              </h4>
              {turn.agent_traces.map((trace: DiscussionAgentTrace, traceIdx: number) => {
                // Live preview can temporarily merge traces into turn 0; include
                // the render index so expansion targets the visible row exactly.
                const traceKey = `${turn.turn_index}-${trace.agent_id}-${traceIdx}`;
                const traceDomId = traceKey.replace(/[^a-zA-Z0-9_-]/g, '_');
                const analysisChain = trace.success ? trace.analysis_chain : null;
                const thoughtTrace = trace.success ? trace.thought_trace : null;
                const hasAnalysisChain = hasDiscussionAnalysisChainContent(analysisChain);
                const hasThoughtTrace = hasDiscussionThoughtTraceContent(thoughtTrace);
                const hasTraceDetails = hasAnalysisChain || hasThoughtTrace;
                const traceExpanded = expandedTraceKey === traceKey;
                const toggleTrace = () => {
                  if (!hasTraceDetails) {
                    return;
                  }
                  setExpandedTraceKey(traceExpanded ? null : traceKey);
                };

                return (
                  <div
                    key={traceKey}
                    data-testid={`discussion-agent-trace-${traceDomId}`}
                    className={cn(
                      'rounded-lg border p-3 space-y-1.5 shadow-sm',
                      ROLE_COLOR_MAP[trace.role] || 'bg-gray-50 text-gray-700 border-gray-200',
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-label text-xs font-medium">
                          {sanitizeDiscussionVisibleText(trace.role_label || getRoleLabel(trace.role), '讨论角色')}
                        </span>
                        <span className="text-[10px] text-foreground/40">模型调用完成</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        {trace.success ? (
                          <CheckCircle2 size={10} className="text-emerald-500" />
                        ) : (
                          <XCircle size={10} className="text-red-500" />
                        )}
                        <span className="text-[10px] text-foreground/40 flex items-center gap-0.5">
                          <Clock size={9} />
                          {trace.latency_ms}ms
                        </span>
                      </div>
                    </div>
                    {trace.success && trace.answer && (
                      hasTraceDetails ? (
                        <button
                          type="button"
                          onClick={toggleTrace}
                          aria-expanded={traceExpanded}
                          aria-controls={`discussion-analysis-chain-${traceDomId}`}
                          className="block w-full rounded-md px-1 py-1 text-left text-xs leading-relaxed text-foreground/80 transition-colors hover:bg-surface/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35"
                        >
                          <span className="whitespace-pre-wrap">{formatDiscussionAnswerText(trace.answer)}</span>
                        </button>
                      ) : (
                        <p className="text-xs text-foreground/80 leading-relaxed whitespace-pre-wrap">
                          {formatDiscussionAnswerText(trace.answer)}
                        </p>
                      )
                    )}
                    {hasTraceDetails && (
                      <div className="flex justify-end">
                        <button
                          type="button"
                          onClick={toggleTrace}
                          aria-expanded={traceExpanded}
                          aria-controls={`discussion-analysis-chain-${traceDomId}`}
                          className="rounded-md border border-outline-variant/70 bg-surface/35 px-2 py-1 text-[10px] font-medium text-foreground/55 transition-colors hover:bg-surface hover:text-foreground"
                        >
                          {traceExpanded ? '收起推理过程' : '查看推理过程'}
                        </button>
                      </div>
                    )}
                    {hasTraceDetails && traceExpanded && (
                      <div id={`discussion-analysis-chain-${traceDomId}`}>
                        {hasThoughtTrace && thoughtTrace && (
                          <DiscussionThoughtTraceSummary trace={thoughtTrace} />
                        )}
                        {hasAnalysisChain && (
                          <AnalysisChainPanel
                            chain={analysisChain}
                            expanded
                            onExpandedChange={(next) => setExpandedTraceKey(next ? traceKey : null)}
                            title="推理过程（证据化摘要）"
                            className="mt-2"
                          />
                        )}
                      </div>
                    )}
                    {trace.success && trace.cited_evidence_ids && trace.cited_evidence_ids.length > 0 && (
                      <DiscussionCitedEvidencePills result={result} trace={trace} />
                    )}
                    {!trace.success && trace.error && (
                      <div className="rounded border border-rose-300/60 bg-rose-50 px-2 py-1.5 dark:bg-rose-500/15 dark:border-rose-700/40">
                        <p className="text-[11px] font-medium text-rose-700 dark:text-rose-200">
                          ⚠ 此角色调用失败
                        </p>
                        <p className="mt-0.5 text-[10px] text-rose-700/85 dark:text-rose-200/85">
                          请检查该角色绑定的模型服务后重试。
                        </p>
                        <p className="mt-0.5 text-[10px] text-rose-700/65 dark:text-rose-200/65">
                          提示：若出现上游服务错误，多为该角色绑定的模型服务异常。请到「系统设置 → 凭证」检查服务地址和访问密钥，或切换到其他服务后重试。
                        </p>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ))}

          {/* Synthesis */}
          {result.synthesis && (
            <div className="rounded-lg border border-primary/20 bg-surface-lowest p-4 shadow-sm space-y-2">
              <div className="flex items-center justify-between">
                <h4 className="font-label text-xs font-semibold text-primary">综合结论</h4>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-foreground/40">综合模型调用</span>
                  <button
                    type="button"
                    onClick={() => navigator.clipboard.writeText(formatDiscussionSynthesisText(result.synthesis.text))}
                    className="text-foreground/30 hover:text-foreground/60"
                    title="复制"
                  >
                    <Copy size={12} />
                  </button>
                  {onInsertToEditor && (
                    <button
                      type="button"
                      onClick={handleInsertSynthesis}
                      className="text-xs text-primary hover:text-primary/80 font-label"
                    >
                      插入写作区
                    </button>
                  )}
                </div>
              </div>
              <p className="text-sm text-foreground/80 leading-relaxed whitespace-pre-wrap">
                {formatDiscussionSynthesisText(result.synthesis.text)}
              </p>
              <p className="text-[10px] text-foreground/30">
                耗时 {result.elapsed_ms}ms · 策略：{getSynthesisStrategyLabel(result.synthesis.strategy)}
              </p>
            </div>
          )}

          {/* GraphPayload v0 viewer for discussion-source graphs.
              prototype. Bipartite agent ↔ evidence; "uses" relation.
              No-data case (e.g. evidence_mode="none") yields agent-only. */}
          <DiscussionGraphSection result={result} />
        </div>
      )}
    </div>
  );
};

function DiscussionGraphSection({ result }: { result: DiscussionRunResult }) {
  const payload = useMemo(() => discussionToGraphPayload(result), [result]);
  const evidenceCount = payload.nodes.filter((n) => n.type === 'evidence').length;
  return (
    <div className="rounded-lg border border-outline-variant overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-outline-variant bg-surface-low">
        <span className="text-xs font-label text-foreground/70">
          讨论图谱 <span className="text-foreground/40">· 智能体 {payload.nodes.length - evidenceCount} · 证据 {evidenceCount} · 边 {payload.edges.length}</span>
        </span>
        {evidenceCount === 0 && (
          <span className="text-[10px] text-foreground/40">
            未启用证据来源，仅显示智能体
          </span>
        )}
      </div>
      <div className="h-[360px] bg-surface-lowest">
        <GraphPayloadViewer payload={payload} projectId={result.project_id} />
      </div>
    </div>
  );
}

interface EvidenceSnippetShape {
  chunk_id?: string;
  content?: string;
  source?: string;
  score?: number;
  material_id?: string;
  section_path?: string;
  page?: number | string | null;
}

function coercePositivePage(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return Math.floor(value);
  }
  if (typeof value !== 'string') {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : null;
}

function buildEvidenceRefById(result: DiscussionRunResult): Map<string, EvidenceRefLike> {
  const refs = new Map<string, EvidenceRefLike>();
  const evidence = result.evidence;
  if (!evidence || !Array.isArray(evidence.snippets) || evidence.snippets.length === 0) {
    return refs;
  }
  const snippets = evidence.snippets as unknown as EvidenceSnippetShape[];
  const ids = evidence.evidence_ids ?? snippets.map((_, i) => `E${i + 1}`);
  snippets.forEach((snippet, index) => {
    const evidenceId = ids[index] ?? `E${index + 1}`;
    if (!evidenceId) {
      return;
    }
    const materialId = typeof snippet.material_id === 'string' ? snippet.material_id.trim() : '';
    const chunkId = typeof snippet.chunk_id === 'string' ? snippet.chunk_id.trim() : '';
    refs.set(evidenceId, {
      evidence_id: evidenceId,
      material_id: materialId || null,
      chunk_id: chunkId || null,
      page: coercePositivePage(snippet.page),
      text: typeof snippet.content === 'string' ? snippet.content : null,
      source: typeof snippet.source === 'string' ? snippet.source : null,
      source_kind: 'local',
    });
  });
  return refs;
}

const THOUGHT_CONTRIBUTION_LABELS: Record<string, string> = {
  supporting_argument: '支持论证',
  boundary_review: '边界审查',
  counter_evidence_probe: '反证探查',
  mechanism_analysis: '机制分析',
  synthesis: '综合归纳',
  role_specific_contribution: '角色贡献',
};

const THOUGHT_STEP_LABELS: Record<string, string> = {
  core_observation: '核心判断',
  mechanism: '机制',
  evidence_basis: '证据依据',
  boundary: '边界',
  counter_evidence: '反证',
  next_action: '下一步',
};

function formatThoughtContributionType(value: string | undefined): string | null {
  const key = value?.trim();
  if (!key) return null;
  return THOUGHT_CONTRIBUTION_LABELS[key] ?? sanitizeDiscussionVisibleText(key, '角色贡献');
}

function formatThoughtStepLabel(value: string): string {
  const key = value.trim();
  if (!key) return '推理摘要';
  return THOUGHT_STEP_LABELS[key] ?? sanitizeDiscussionVisibleText(key, '推理摘要');
}

function formatTraceConfidence(value: number | null | undefined): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  const clamped = Math.max(0, Math.min(1, value));
  return `${Math.round(clamped * 100)}%`;
}

function DiscussionThoughtTraceSummary({ trace }: { trace: AgentThoughtTracePayload }) {
  const stance = trace.agent_stance?.trim()
    ? sanitizeDiscussionVisibleText(trace.agent_stance, '角色立场')
    : null;
  const contribution = formatThoughtContributionType(trace.contribution_type);
  const confidence = formatTraceConfidence(trace.confidence);
  const evidenceRefs = (trace.evidence_refs ?? []).filter((item) => item.trim()).slice(0, 6);
  const steps = (trace.trace_steps ?? []).filter((step) => step.summary?.trim()).slice(0, 6);

  if (!stance && !contribution && !confidence && evidenceRefs.length === 0 && steps.length === 0) {
    return null;
  }

  return (
    <div className="mt-2 rounded-md border border-outline-variant/60 bg-surface-lowest/55 px-3 py-2 text-[11px] text-foreground/70">
      <div className="flex flex-wrap items-center gap-1.5">
        {stance && (
          <span className="rounded bg-surface-high px-1.5 py-0.5">
            立场：{stance}
          </span>
        )}
        {contribution && (
          <span className="rounded bg-surface-high px-1.5 py-0.5">
            贡献：{contribution}
          </span>
        )}
        {confidence && (
          <span className="rounded bg-surface-high px-1.5 py-0.5">
            置信度：{confidence}
          </span>
        )}
        {evidenceRefs.length > 0 && (
          <span className="rounded bg-primary/10 px-1.5 py-0.5 text-primary">
            证据：{evidenceRefs.map((eid, index) => formatDiscussionEvidenceLabel(eid, index)).join('、')}
          </span>
        )}
      </div>
      {steps.length > 0 && (
        <ol className="mt-2 space-y-1 border-l border-outline-variant/60 pl-2">
          {steps.map((step, index) => (
            <li key={`${step.label || 'step'}-${index}`} className="leading-relaxed">
              <span className="font-medium text-foreground/65">
                {formatThoughtStepLabel(step.label)}
              </span>
              <span className="ml-1">
                {sanitizeDiscussionVisibleText(step.summary, '推理摘要已隐藏。')}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function DiscussionCitedEvidencePills({
  result,
  trace,
}: {
  result: DiscussionRunResult;
  trace: DiscussionAgentTrace;
}) {
  const evidenceRefs = useMemo(() => buildEvidenceRefById(result), [result]);
  return (
    <div
      className="mt-1 flex flex-wrap gap-1"
      data-testid={`cited-evidence-pills-${trace.agent_id}`}
    >
      {(trace.cited_evidence_ids ?? []).map((eid, index) => {
        const evidenceLabel = formatDiscussionEvidenceLabel(eid, index);
        const ref = evidenceRefs.get(eid);
        if (ref?.material_id) {
          return (
            <EvidencePill
              key={eid}
              evidence={ref}
              projectId={result.project_id}
              className="font-mono text-[10px]"
              title={`打开${evidenceLabel}`}
            />
          );
        }
        return (
          <button
            type="button"
            key={eid}
            onClick={() => scrollToEvidence(eid)}
            className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary hover:bg-primary/20"
            aria-label={`定位${evidenceLabel}`}
          >
            {evidenceLabel}
          </button>
        );
      })}
    </div>
  );
}

export function DiscussionEvidencePackSection({ result }: { result: DiscussionRunResult }) {
  const evidence = result.evidence;
  if (!evidence || !evidence.snippets || evidence.snippets.length === 0) return null;
  const snippets = evidence.snippets as unknown as EvidenceSnippetShape[];
  const ids = evidence.evidence_ids ?? snippets.map((_, i) => `E${i + 1}`);
  return (
    <div
      className="rounded-lg border border-outline-variant overflow-hidden"
      data-testid="discussion-evidence-pack"
    >
      <div className="px-3 py-2 border-b border-outline-variant bg-surface-low">
        <span className="text-xs font-label text-foreground/70">
          证据池 <span className="text-foreground/40">· {snippets.length} 条</span>
        </span>
      </div>
      <div className="p-2 space-y-1.5 bg-surface-lowest">
        {snippets.map((snippet, i) => {
          const eid = ids[i] ?? `E${i + 1}`;
          const evidenceLabel = formatDiscussionEvidenceLabel(eid, i);
          const sourceLabel = formatDiscussionSnippetText(snippet.source, evidenceLabel);
          const content = formatDiscussionSnippetText(snippet.content, '证据内容已隐藏，避免显示内部路径或系统字段。');
          return (
            <div
              key={eid}
              id={evidenceSnippetDomId(eid)}
              data-testid={`evidence-snippet-${eid}`}
              className="rounded border border-outline-variant bg-white p-2 transition-shadow"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] text-primary">{evidenceLabel}</span>
                <span className="max-w-[60%] truncate text-[10px] text-foreground/40">
                  {sourceLabel}
                </span>
              </div>
              <p className="text-xs text-foreground/80 leading-relaxed line-clamp-3">
                {content}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
