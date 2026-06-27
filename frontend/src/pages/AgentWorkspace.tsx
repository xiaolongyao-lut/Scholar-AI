import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  Bot,
  CheckCircle2,
  ChevronRight,
  Clock,
  FileJson2,
  FileText,
  FolderOpen,
  Loader2,
  RefreshCw,
  Search,
  TerminalSquare,
  XCircle,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { EmptyState } from '@/components/common/EmptyState';
import { PageHeader } from '@/components/common/PageHeader';
import { StatusPill, type StatusTone } from '@/components/common/StatusPill';
import {
  getAgentBridgeStatus,
  getAgentHandoffCard,
  getAgentWorkflowHealth,
  getAgentWorkspaceRequirement,
  getAgentWorkspaceStatus,
  getBehaviorEvalPack,
  getEvidenceIntegrityGate,
  getResearchActionLifecycle,
  getWorkflowPassport,
  getWorkflowReplayIndex,
  getWorkflowReplayLineage,
  getZoteroAttachmentHealth,
  listRuntimeJobs,
  type AgentHandoffCardProjection,
  type AgentWorkflowHealthCheck,
  type AgentWorkspaceArtifact,
  type AgentWorkspaceAuditRecord,
  type AgentWorkspaceGoalRequirementDrilldown,
  type AgentWorkspaceRecoveryProbe,
  type AgentWorkspaceStatus,
  type AgentBridgeStatus,
  type BehaviorEvalPackProjection,
  type BlockingActionBoundaryProjection,
  type BlockingActionBoundaryProbe,
  type BlockingActionBoundaryRecoveryDrilldown,
  type BlockingActionBoundarySignalRef,
  type EvidenceIntegrityGateProjection,
  type EvidenceIntegritySignal,
  type ResearchActionLifecycleItemProjection,
  type ResearchActionLifecycleProjection,
  type WorkflowActionPreflightProjection,
  type RuntimeJobsStatus,
  type WorkflowReadinessClaimsProjection,
  type WorkflowReadinessClaim,
  type WorkflowReplayIndexProjection,
  type WorkflowReplayLineageProjection,
  type WorkflowPassportProjection,
  type WorkflowPassportStage,
  type ZoteroAttachmentHealth,
} from '@/services/agentWorkspaceApi';
import {
  getKnowledgeRuntimeConformance,
  type KnowledgeRuntimeActualLoadingGate,
  type KnowledgeRuntimeConformancePackage,
  type KnowledgeRuntimeConformanceResponse,
} from '@/services/knowledgeApi';
import { getWikiReview } from '@/services/wikiApi';
import type { WritingJob } from '@/types/runtime';
import type { WikiReviewItemModel, WikiReviewListModel } from '@/types/wiki';

type WorkspaceTab = 'agents' | 'artifacts' | 'audit';

type AgentWorkspaceOpenRequirement = NonNullable<AgentWorkspaceStatus['workspace_state']['goal_state']['open_requirements']>[number];
type AgentWorkspaceOcrEngine = AgentWorkspaceStatus['workspace_state']['ocr_runtime']['engines'][number];

const KIND_LABELS: Record<string, string> = {
  markdown: 'Markdown',
  json: 'JSON',
  jsonl: 'JSONL',
  text: 'Text',
  file: 'File',
};

const KIND_ICONS: Record<string, React.ElementType> = {
  markdown: FileText,
  json: FileJson2,
  jsonl: FileJson2,
  text: FileText,
  file: FileText,
};

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) {
    return '0 B';
  }
  if (value < 1024) {
    return `${Math.round(value)} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function stringifyArgs(value: Record<string, unknown>): string {
  const entries = Object.entries(value);
  if (entries.length === 0) {
    return '—';
  }
  return entries
    .slice(0, 5)
    .map(([key, item]) => `${key}: ${String(item)}`)
    .join(' · ');
}

function statusTone(record: AgentWorkspaceAuditRecord): StatusTone {
  if (record.error_code) {
    return 'danger';
  }
  if (record.allow_block_reason.includes('block')) {
    return 'warning';
  }
  return 'success';
}

function filterText(value: string): string {
  return value.trim().toLowerCase();
}

function matchesQuery(
  query: string,
  artifact: AgentWorkspaceArtifact | null,
  record: AgentWorkspaceAuditRecord | null,
  job: WritingJob | null = null,
): boolean {
  const needle = filterText(query);
  if (!needle) {
    return true;
  }
  const haystack = job
    ? `${job.kind} ${job.input_text} ${JSON.stringify(job.metadata ?? {})}`.toLowerCase()
    : artifact
    ? `${artifact.path} ${artifact.kind} ${artifact.preview}`.toLowerCase()
    : `${record?.tool_name ?? ''} ${record?.allow_block_reason ?? ''} ${record?.error_code ?? ''} ${record?.result_preview ?? ''}`.toLowerCase();
  return haystack.includes(needle);
}

function matchesOpenRequirementQuery(query: string, item: AgentWorkspaceOpenRequirement): boolean {
  const needle = filterText(query);
  if (!needle) {
    return true;
  }
  const haystack = [
    item.id,
    item.status,
    item.requirement ?? '',
    item.residual_risk ?? '',
  ].join(' ').toLowerCase();
  return haystack.includes(needle);
}

function StatTile({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="flex min-h-[72px] min-w-0 items-center gap-3 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
        {icon}
      </div>
      <div className="min-w-0">
        <div className="truncate text-[11px] text-foreground/45">{label}</div>
        <div className="mt-1 truncate font-display text-lg font-semibold text-foreground">{value}</div>
      </div>
    </div>
  );
}

function ArtifactRow({
  artifact,
  selected,
  onSelect,
}: {
  artifact: AgentWorkspaceArtifact;
  selected: boolean;
  onSelect: () => void;
}) {
  const Icon = KIND_ICONS[artifact.kind] ?? FileText;
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'flex w-full min-w-0 items-start gap-3 px-3 py-2.5 text-left transition-colors',
        selected ? 'bg-primary/10' : 'hover:bg-surface-default/45',
      )}
    >
      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-surface-high text-primary/75">
        <Icon size={15} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-label text-sm font-medium text-foreground">{artifact.name}</span>
        <span className="mt-0.5 block truncate text-[11px] text-foreground/45">{artifact.path}</span>
        <span className="mt-1 flex flex-wrap items-center gap-1.5">
          <StatusPill tone="neutral">{KIND_LABELS[artifact.kind] ?? artifact.kind}</StatusPill>
          <StatusPill tone="info">{formatBytes(artifact.size_bytes)}</StatusPill>
        </span>
      </span>
    </button>
  );
}

function AuditRow({
  record,
  selected,
  onSelect,
}: {
  record: AgentWorkspaceAuditRecord;
  selected: boolean;
  onSelect: () => void;
}) {
  const tone = statusTone(record);
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'flex w-full min-w-0 items-start gap-3 px-3 py-2.5 text-left transition-colors',
        selected ? 'bg-primary/10' : 'hover:bg-surface-default/45',
      )}
    >
      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-surface-high text-primary/75">
        {record.error_code ? <XCircle size={15} /> : <CheckCircle2 size={15} />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-label text-sm font-medium text-foreground">{record.tool_name}</span>
        <span className="mt-0.5 block truncate text-[11px] text-foreground/45">{formatDateTime(record.timestamp)}</span>
        <span className="mt-1 flex flex-wrap items-center gap-1.5">
          <StatusPill tone={tone}>{record.error_code ? 'error' : 'ok'}</StatusPill>
          <StatusPill tone="neutral">{record.duration_ms} ms</StatusPill>
        </span>
      </span>
    </button>
  );
}

function jobStatusTone(job: WritingJob): StatusTone {
  if (job.status === 'failed') return 'danger';
  if (job.status === 'completed') return 'success';
  if (job.status === 'cancelled') return 'neutral';
  if (job.status === 'paused' || job.status === 'started' || job.status === 'in_progress') return 'warning';
  return 'neutral';
}

function jobKindLabel(job: WritingJob): string {
  if (job.kind === 'resource_ingest') return '文献入库';
  if (job.kind === 'agent_request') return '智能体任务';
  return String(job.kind || '任务');
}

function jobMetadataText(job: WritingJob, key: string): string {
  const value = job.metadata?.[key];
  return typeof value === 'string' ? value : '';
}

function workflowSummaryText(job: WritingJob, key: string): string {
  const summary = job.writing_workflow_state_summary;
  if (!summary || typeof summary !== 'object') {
    return '';
  }
  const value = summary[key];
  return typeof value === 'string' ? value : '';
}

function isVisibleRuntimeJob(job: WritingJob): boolean {
  if (job.kind === 'resource_ingest' || job.kind === 'artifact_export') {
    return true;
  }
  const summary = job.writing_workflow_state_summary;
  return Boolean(summary && typeof summary === 'object' && Object.keys(summary).length > 0);
}

function isBehaviorEvalArtifact(artifact: AgentWorkspaceArtifact): boolean {
  const text = `${artifact.path} ${artifact.name}`.toLowerCase();
  return text.includes('behavior_eval') || text.includes('behavior-eval');
}

const ACTIVE_JOB_STATUSES = new Set(['queued', 'started', 'in_progress', 'paused', 'approval_pending']);

interface ToolNextActionLike {
  kind?: string | null;
  message?: string | null;
}

interface ToolOutcomeLike {
  reason?: string | null;
  next_action?: ToolNextActionLike | null;
}

interface ReadinessCard {
  id: string;
  label: string;
  statusLabel: string;
  tone: StatusTone;
  icon: React.ReactNode;
  summary: string;
  nextAction: string;
  metrics: string[];
}

interface WikiImportRecoveryItem {
  itemId: string;
  title: string;
  status: string;
  pagePath: string;
  requestedStatus: string;
  runtimeSessionId: string;
  runtimeJobId: string;
  runtimeApprovalId: string;
  gateStatus: string;
  hasRuntimeRefs: boolean;
  hasHandoffCard: boolean;
  hasReviewQueueProbe: boolean;
  forbiddenActions: string[];
}

type ReadinessPanelDensity = 'default' | 'desktop-acceptance';

type WorkflowSpineDensity = 'default' | 'desktop-acceptance';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNumberField(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function readTextField(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === 'string' ? value.trim() : '';
}

function readBooleanField(record: Record<string, unknown>, key: string): boolean {
  return record[key] === true;
}

function readOptionalBooleanField(record: Record<string, unknown>, key: string): boolean | null {
  const value = record[key];
  return typeof value === 'boolean' ? value : null;
}

function sanitizeInspectorText(value: string): string {
  return value
    .replace(/[A-Za-z]:\\(?:Users|Documents and Settings)\\(?:[^\\,;'"`<>)]*\\)*[^\\,;'"`<>)]*\.[A-Za-z0-9]{1,12}(?=$|[\s,;'"`<>)]|$)/g, '[redacted-local-path]')
    .replace(/\/(?:Users|home)\/(?:[^/,;'"`<>)]*\/)*[^/,;'"`<>)]*\.[A-Za-z0-9]{1,12}(?=$|[\s,;'"`<>)]|$)/g, '[redacted-local-path]')
    .replace(/[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\s,;'"`<>)]*/g, '[redacted-local-path]')
    .replace(/\/(?:Users|home)\/[^\s,;'"`<>)]*/g, '[redacted-local-path]')
    .replace(/workspace_artifacts[\\/]private[^\s,;'"`<>)]*/g, '[redacted-workspace-path]')
    .replace(/\/runtime\/[^\s,;'"`<>)]*/g, '[redacted-runtime-route]');
}

function displayUnknownValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '—';
  }
  if (typeof value === 'string') {
    return sanitizeInspectorText(value.trim() || '—');
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  try {
    return sanitizeInspectorText(JSON.stringify(value));
  } catch {
    return 'unreadable';
  }
}

function displayInspectorJson(value: unknown): string {
  try {
    return sanitizeInspectorText(JSON.stringify(value, null, 2));
  } catch {
    return 'unreadable';
  }
}

function hasTextField(record: Record<string, unknown>, key: string): boolean {
  return readTextField(record, key).length > 0;
}

function readTextArrayField(record: Record<string, unknown>, key: string): string[] {
  const value = record[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    .map((item) => sanitizeInspectorText(item.trim()));
}

function isWikiImportReviewItem(item: WikiReviewItemModel): boolean {
  const metadata = isRecord(item.metadata) ? item.metadata : {};
  const source = readTextField(metadata, 'source') || item.source;
  const entrySource = readTextField(metadata, 'entry_source');
  return item.source === 'local_markdown_import'
    || source === 'local_markdown_import'
    || entrySource === 'local_markdown_import'
    || readBooleanField(metadata, 'manual_wiki_import')
    || (
      readTextField(metadata, 'runtime_action_family') === 'wiki_candidate'
      && readTextField(metadata, 'approval_surface') === 'wiki_review_queue'
    );
}

function buildWikiImportRecoveryItems(wikiReview: WikiReviewListModel | null): WikiImportRecoveryItem[] {
  return (wikiReview?.items ?? [])
    .filter(isWikiImportReviewItem)
    .map((item) => {
      const metadata = isRecord(item.metadata) ? item.metadata : {};
      const runtimeRecovery = readRecordField(metadata, 'runtime_recovery');
      const handoffRecovery = readRecordField(metadata, 'agent_handoff_recovery');
      const gate = readRecordField(metadata, 'evidence_integrity_gate');
      const runtimeSessionId = sanitizeInspectorText(readTextField(metadata, 'runtime_session_id'));
      const runtimeJobId = sanitizeInspectorText(readTextField(metadata, 'runtime_job_id'));
      const runtimeApprovalId = sanitizeInspectorText(readTextField(metadata, 'runtime_approval_id'));
      return {
        itemId: sanitizeInspectorText(item.item_id),
        title: sanitizeInspectorText(item.title || 'Untitled import'),
        status: sanitizeInspectorText(item.status || 'unknown'),
        pagePath: sanitizeInspectorText(item.page_path || readTextField(metadata, 'wiki_page_path') || 'page pending'),
        requestedStatus: sanitizeInspectorText(readTextField(metadata, 'requested_status') || 'draft'),
        runtimeSessionId,
        runtimeJobId,
        runtimeApprovalId,
        gateStatus: sanitizeInspectorText(readTextField(gate, 'status') || 'unresolved'),
        hasRuntimeRefs: Boolean(runtimeSessionId || runtimeJobId || runtimeApprovalId),
        hasHandoffCard: hasTextField(runtimeRecovery, 'agent_handoff_card'),
        hasReviewQueueProbe: hasTextField(handoffRecovery, 'review_queue_probe'),
        forbiddenActions: readTextArrayField(handoffRecovery, 'forbidden_actions').slice(0, 3),
      } satisfies WikiImportRecoveryItem;
    });
}

function actionMessage(action: ToolNextActionLike | null | undefined): string {
  const message = action?.message?.trim();
  if (message) {
    return message;
  }
  const kind = action?.kind?.trim();
  return kind && kind !== 'none' ? kind : '';
}

function outcomeReason(outcome: ToolOutcomeLike | null | undefined, fallback: string): string {
  const reason = outcome?.reason?.trim();
  return reason || fallback;
}

function healthTone(status: string | null | undefined): StatusTone {
  if (status === 'ok' || status === 'success') {
    return 'success';
  }
  if (status === 'blocked' || status === 'failed' || status === 'auth_required' || status === 'config_needed') {
    return 'danger';
  }
  if (status === 'degraded' || status === 'partial') {
    return 'warning';
  }
  return 'neutral';
}

function healthStatusLabel(status: string | null | undefined): string {
  if (status === 'ok' || status === 'success') {
    return '已就绪';
  }
  if (status === 'blocked') {
    return '阻塞';
  }
  if (status === 'degraded' || status === 'partial') {
    return '需处理';
  }
  if (status === 'failed') {
    return '失败';
  }
  if (status === 'config_needed') {
    return '需配置';
  }
  return '未读取';
}

function gateTone(status: string | null | undefined, severity?: string | null): StatusTone {
  if (status === 'block' || severity === 'block') {
    return 'danger';
  }
  if (status === 'warn' || status === 'unresolved' || severity === 'warn') {
    return 'warning';
  }
  if (status === 'pass' || status === 'complete') {
    return 'success';
  }
  if (status === 'in_progress') {
    return 'info';
  }
  return 'neutral';
}

function gateStatusLabel(status: string | null | undefined): string {
  if (status === 'pass' || status === 'complete') {
    return '通过';
  }
  if (status === 'block' || status === 'blocked') {
    return '阻断';
  }
  if (status === 'warn') {
    return '警告';
  }
  if (status === 'unresolved') {
    return '未决';
  }
  if (status === 'in_progress') {
    return '进行中';
  }
  if (status === 'not_started') {
    return '未开始';
  }
  if (status === 'not_applicable') {
    return '暂不适用';
  }
  return '未读取';
}

function knowledgeRuntimeTone(status: string | null | undefined): StatusTone {
  if (status === 'blocked') {
    return 'danger';
  }
  if (status === 'pending') {
    return 'warning';
  }
  if (status === 'proved') {
    return 'success';
  }
  return 'neutral';
}

function shortHashLabel(value: string): string {
  const sanitized = sanitizeInspectorText(value.trim());
  if (!sanitized || sanitized === 'none' || sanitized === 'missing') {
    return sanitized || 'missing';
  }
  return sanitized.length > 18 ? `${sanitized.slice(0, 18)}...` : sanitized;
}

function actualLoadingGateSummary(gate: KnowledgeRuntimeActualLoadingGate): string {
  return `${sanitizeInspectorText(gate.verdict)} · evidence ${gate.evidence.length} · missing ${gate.missing.length} · errors ${gate.validation_errors.length} · checks ${gate.required_checks.length}`;
}

function actualLoadingRecoveryTone(gate: KnowledgeRuntimeActualLoadingGate): StatusTone {
  if (gate.recovery.blocked_by.length > 0) {
    return 'danger';
  }
  if (gate.recovery.completion_requires_authorized_live_smoke) {
    return 'warning';
  }
  return gate.recovery.provider_ready_for_authorized_live_smoke ? 'success' : 'neutral';
}

function actualLoadingRecoveryRefLabel(ref: KnowledgeRuntimeActualLoadingGate['recovery']['recovery_refs'][number]): string {
  const status = sanitizeInspectorText(ref.status || 'unknown');
  const method = sanitizeInspectorText(ref.method || 'GET');
  const accessMode = sanitizeInspectorText(ref.access_mode || 'read_only');
  const auth = ref.requires_authorization ? ' · auth' : '';
  return `${sanitizeInspectorText(ref.ref_type)} ${method} · ${accessMode} · ${status}${auth}`;
}

function packageEvidenceSummary(pkg: KnowledgeRuntimeConformancePackage): string {
  const flags = [
    pkg.test_evidence.focused_test_exists ? 'focused-test' : '',
    pkg.test_evidence.context_receipt_test ? 'context-receipt' : '',
    pkg.test_evidence.agent_resource_read_test ? 'agent-resource' : '',
    pkg.test_evidence.mcp_tool_test ? 'mcp-tool' : '',
  ].filter(Boolean);
  return flags.length > 0 ? flags.join(' · ') : 'test proof pending';
}

function claimTone(status: string | null | undefined): StatusTone {
  if (status === 'blocked') {
    return 'danger';
  }
  if (status === 'warning' || status === 'unresolved' || status === 'stale') {
    return 'warning';
  }
  if (status === 'ready') {
    return 'success';
  }
  return 'neutral';
}

function claimStatusLabel(status: string | null | undefined): string {
  if (status === 'ready') {
    return 'ready';
  }
  if (status === 'blocked') {
    return 'blocked';
  }
  if (status === 'stale') {
    return 'stale';
  }
  if (status === 'warning') {
    return 'warning';
  }
  if (status === 'unresolved') {
    return 'unresolved';
  }
  return 'unknown';
}

function preflightStatusLabel(status: string | null | undefined): string {
  if (status === 'ready') {
    return 'ready';
  }
  if (status === 'blocked') {
    return 'blocked';
  }
  if (status === 'stale') {
    return 'stale';
  }
  if (status === 'unresolved') {
    return 'unresolved';
  }
  return '未读取';
}

function preflightFreshnessLabel(preflight: WorkflowActionPreflightProjection | null): string {
  const freshness = preflight?.freshness;
  if (!freshness) {
    return 'freshness unknown';
  }
  if (freshness.status === 'fresh' && freshness.age_seconds !== null) {
    return `fresh ${freshness.age_seconds}s`;
  }
  if (freshness.status === 'stale' && freshness.age_seconds !== null) {
    return `stale ${freshness.age_seconds}s`;
  }
  return `freshness ${freshness.status}`;
}

function readRecordField(record: Record<string, unknown> | null | undefined, key: string): Record<string, unknown> {
  if (!isRecord(record)) {
    return {};
  }
  const value = record[key];
  return isRecord(value) ? value : {};
}

function firstNonEmptyText(values: Array<string | null | undefined>, fallback: string): string {
  const found = values.find((value) => typeof value === 'string' && value.trim().length > 0);
  return found?.trim() || fallback;
}

function compactStageLabel(stage: WorkflowPassportStage): string {
  const label = stage.label.trim();
  return label || stage.stage_id;
}

function buildStageReason(stage: WorkflowPassportStage): string {
  return firstNonEmptyText(
    [
      stage.gate.blockers[0],
      stage.gate.unresolved[0],
      stage.gate.reason,
      stage.next_actions[0],
    ],
    '等待更多本地流程证据。',
  );
}

function findCurrentStage(passport: WorkflowPassportProjection | null): WorkflowPassportStage | null {
  const stages = passport?.stages ?? [];
  if (stages.length === 0) {
    return null;
  }
  return stages.find((stage) => stage.stage_id === passport?.current_stage_id) ?? stages[0] ?? null;
}

function summarizeGateCounts(value: Record<string, unknown>): string {
  const statusCounts = readRecordField(value, 'status_counts');
  const gateCounts = readRecordField(value, 'gate_counts');
  const source = Object.keys(statusCounts).length > 0 ? statusCounts : gateCounts;
  const summary = summarizeStatusCounts(source);
  return summary || 'no signals';
}

function integritySignalDrilldownSummary(signal: EvidenceIntegritySignal | null): {
  source: string;
  factCount: number;
  evidenceCount: number;
  replayCount: number;
  requiresHumanReview: boolean;
  blocksClaims: boolean;
} | null {
  if (!signal) {
    return null;
  }
  const drilldown = isRecord(signal.drilldown) ? signal.drilldown : {};
  const sourceRef = readRecordField(drilldown, 'source_ref');
  const checkedFacts = readRecordField(drilldown, 'checked_facts');
  const evidenceRefs = drilldown.evidence_refs;
  const replayRefs = drilldown.replay_refs;
  const sourceKind = readTextField(sourceRef, 'source_kind');
  const sourceDigest = readTextField(sourceRef, 'source_digest');
  return {
    source: sourceKind || sourceDigest || 'source pending',
    factCount: Object.keys(checkedFacts).length,
    evidenceCount: Array.isArray(evidenceRefs) ? evidenceRefs.length : 0,
    replayCount: Array.isArray(replayRefs) ? replayRefs.length : 0,
    requiresHumanReview: drilldown.requires_human_review === true,
    blocksClaims: drilldown.blocks_claims === true,
  };
}

interface IntegrityRefSummary {
  refType: string;
  refId: string;
}

interface IntegrityFactSummary {
  key: string;
  value: string;
}

interface IntegrityDrilldownDetails {
  source: string;
  sourceId: string;
  sourceDigest: string;
  rawPathExposed: boolean;
  linkedStageId: string;
  factItems: IntegrityFactSummary[];
  evidenceRefs: IntegrityRefSummary[];
  replayRefs: IntegrityRefSummary[];
  requiresHumanReview: boolean;
  blocksClaims: boolean;
}

interface LocatorQualitySignalSummary {
  signalId: string;
  message: string;
  status: string;
  severity: string;
  coverageState: string;
  riskLevel: string;
  invalidBBoxCount: number;
  bboxLocatorCount: number;
  sampleInvalidBBoxRefIds: string[];
  nextAction: string;
}

function readRefSummaries(value: unknown, maxItems: number): IntegrityRefSummary[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.slice(0, maxItems).map((item, index) => {
    const record = isRecord(item) ? item : {};
    const fallback = `ref:${index + 1}`;
    return {
      refType: sanitizeInspectorText(readTextField(record, 'ref_type') || readTextField(record, 'type') || 'ref'),
      refId: sanitizeInspectorText(readTextField(record, 'ref_id') || readTextField(record, 'id') || fallback),
    };
  });
}

function isPrivateOrRawLocatorFactKey(key: string): boolean {
  const normalized = key.trim().toLowerCase();
  if (normalized === 'bbox' || normalized === 'bounding_box' || normalized === 'coordinates' || normalized === 'rect') {
    return true;
  }
  return normalized.endsWith('_path') || normalized.endsWith('_filepath') || normalized.includes('source_path');
}

function integritySignalStageId(signal: EvidenceIntegritySignal): string {
  const drilldown = isRecord(signal.drilldown) ? signal.drilldown : {};
  const checkedFacts = readRecordField(drilldown, 'checked_facts');
  const factStageId = readTextField(checkedFacts, 'stage_id');
  if (factStageId) {
    return factStageId;
  }
  if (signal.signal_id.startsWith('workflow_stage:')) {
    return signal.signal_id.slice('workflow_stage:'.length);
  }
  return '';
}

function integritySignalsForStage(
  stage: WorkflowPassportStage,
  signals: EvidenceIntegritySignal[],
): EvidenceIntegritySignal[] {
  return signals.filter((signal) => integritySignalStageId(signal) === stage.stage_id);
}

function buildLocatorQualitySignalSummary(signal: EvidenceIntegritySignal): LocatorQualitySignalSummary | null {
  const metadata = isRecord(signal.metadata) ? signal.metadata : {};
  const drilldown = isRecord(signal.drilldown) ? signal.drilldown : {};
  const checkedFacts = readRecordField(drilldown, 'checked_facts');
  const invalidBBoxCount = Math.max(
    0,
    readNumberField(metadata, 'invalid_bbox_count'),
    readNumberField(checkedFacts, 'invalid_bbox_count'),
  );
  const signalId = signal.signal_id.toLowerCase();
  const category = signal.category.toLowerCase();
  const hasLocatorQualityContext = (
    invalidBBoxCount > 0
    || category === 'locator'
    || signalId.includes('invalid-bbox')
    || signalId.includes('locator')
  );
  if (!hasLocatorQualityContext) {
    return null;
  }
  const bboxLocatorCount = Math.max(
    0,
    readNumberField(metadata, 'bbox_locator_count'),
    readNumberField(checkedFacts, 'bbox_locator_count'),
  );
  const sampleInvalidBBoxRefIds = [
    ...readTextArray(metadata.sample_invalid_bbox_ref_ids, 4),
    ...readTextArray(checkedFacts.sample_invalid_bbox_ref_ids, 4),
  ].filter((item, index, items) => items.indexOf(item) === index).slice(0, 4);
  return {
    signalId: sanitizeInspectorText(signal.signal_id),
    message: sanitizeInspectorText(signal.message),
    status: signal.status,
    severity: signal.severity,
    coverageState: sanitizeInspectorText(
      readTextField(metadata, 'coverage_state')
        || readTextField(checkedFacts, 'coverage_state')
        || 'unknown',
    ),
    riskLevel: sanitizeInspectorText(
      readTextField(metadata, 'risk_level')
        || readTextField(checkedFacts, 'risk_level')
        || signal.severity
        || signal.status
        || 'unknown',
    ),
    invalidBBoxCount,
    bboxLocatorCount,
    sampleInvalidBBoxRefIds,
    nextAction: sanitizeInspectorText(signal.next_actions[0] ?? 'Repair locator quality before relying on layout-specific evidence claims.'),
  };
}

function buildLocatorQualitySignalSummaries(
  signals: EvidenceIntegritySignal[],
  maxItems: number,
): LocatorQualitySignalSummary[] {
  return signals
    .map(buildLocatorQualitySignalSummary)
    .filter((summary): summary is LocatorQualitySignalSummary => summary !== null)
    .slice(0, maxItems);
}

function buildIntegrityDrilldownDetails(signal: EvidenceIntegritySignal): IntegrityDrilldownDetails {
  const drilldown = isRecord(signal.drilldown) ? signal.drilldown : {};
  const sourceRef = readRecordField(drilldown, 'source_ref');
  const checkedFacts = readRecordField(drilldown, 'checked_facts');
  const factItems = Object.entries(checkedFacts)
    .filter(([key]) => !isPrivateOrRawLocatorFactKey(key))
    .slice(0, 8)
    .map(([key, value]) => ({
      key: sanitizeInspectorText(key),
      value: displayUnknownValue(value),
    }));
  const sourceKind = readTextField(sourceRef, 'source_kind');
  const sourceDigest = readTextField(sourceRef, 'source_digest');
  return {
    source: sanitizeInspectorText(sourceKind || sourceDigest || 'source pending'),
    sourceId: sanitizeInspectorText(readTextField(sourceRef, 'source_id') || 'source id pending'),
    sourceDigest: sanitizeInspectorText(sourceDigest || 'digest pending'),
    rawPathExposed: sourceRef.raw_path_exposed === true,
    linkedStageId: sanitizeInspectorText(integritySignalStageId(signal)),
    factItems,
    evidenceRefs: readRefSummaries(drilldown.evidence_refs, 4),
    replayRefs: readRefSummaries(drilldown.replay_refs, 4),
    requiresHumanReview: drilldown.requires_human_review === true,
    blocksClaims: drilldown.blocks_claims === true,
  };
}

function linkedStageLabel(stageId: string, stages: WorkflowPassportStage[]): string {
  if (!stageId) {
    return 'stage pending';
  }
  const stage = stages.find((item) => item.stage_id === stageId);
  return stage ? compactStageLabel(stage) : stageId;
}

function signalCollectionTone(signals: EvidenceIntegritySignal[]): StatusTone {
  if (signals.some((signal) => signal.status === 'block' || signal.severity === 'block')) {
    return 'danger';
  }
  if (signals.some((signal) => signal.status === 'unresolved' || signal.status === 'warn' || signal.severity === 'warn')) {
    return 'warning';
  }
  return signals.length > 0 ? 'info' : 'neutral';
}

function isBehaviorEvalSignal(value: { category?: string | null; signal_id?: string | null }): boolean {
  const category = value.category?.trim().toLowerCase() ?? '';
  const signalId = value.signal_id?.trim().toLowerCase() ?? '';
  return category === 'behavior_eval' || signalId.startsWith('behavior_eval:');
}

function integritySignalPrimaryEvidenceType(signal: EvidenceIntegritySignal): string {
  const firstEvidence = signal.evidence.find(isRecord);
  if (!firstEvidence) {
    return '';
  }
  return sanitizeInspectorText(
    readTextField(firstEvidence, 'ref_type')
      || readTextField(firstEvidence, 'type')
      || readTextField(firstEvidence, 'source_kind')
      || readTextField(firstEvidence, 'kind'),
  );
}

interface MaterialCacheDecisionSummary {
  stageId: string;
  stageLabel: string;
  refId: string;
  decision: string;
  policy: string;
  replayable: boolean | null;
  reason: string;
  artifactFamilyDigest: string;
  hasAllRequestedOutputs: boolean | null;
}

function materialCacheDecisionRefsForStage(stage: WorkflowPassportStage): MaterialCacheDecisionSummary[] {
  const refs = stage.reproducibility.cache_decision_refs;
  if (!Array.isArray(refs)) {
    return [];
  }
  return refs.slice(0, 6).map((item, index) => {
    const record = isRecord(item) ? item : {};
    const refId = readTextField(record, 'ref_id') || readTextField(record, 'decision_id') || `cache-decision:${index + 1}`;
    return {
      stageId: stage.stage_id,
      stageLabel: compactStageLabel(stage),
      refId: sanitizeInspectorText(refId),
      decision: sanitizeInspectorText(readTextField(record, 'decision') || 'unknown'),
      policy: sanitizeInspectorText(readTextField(record, 'policy') || 'unknown'),
      replayable: readOptionalBooleanField(record, 'replayable'),
      reason: sanitizeInspectorText(readTextField(record, 'reason') || 'reason pending'),
      artifactFamilyDigest: sanitizeInspectorText(readTextField(record, 'artifact_family_digest') || 'artifact digest pending'),
      hasAllRequestedOutputs: readOptionalBooleanField(record, 'has_all_requested_outputs'),
    };
  });
}

function materialCacheDecisionRefs(stages: WorkflowPassportStage[]): MaterialCacheDecisionSummary[] {
  return stages.flatMap(materialCacheDecisionRefsForStage);
}

function cacheDecisionTone(decision: MaterialCacheDecisionSummary): StatusTone {
  if (decision.decision === 'invalidated') {
    return 'danger';
  }
  if (decision.decision === 'pending' || decision.replayable === false || decision.hasAllRequestedOutputs === false) {
    return 'warning';
  }
  if (decision.decision === 'hit') {
    return 'success';
  }
  if (decision.decision === 'miss' || decision.decision === 'refresh' || decision.decision === 'bypass') {
    return 'info';
  }
  return 'neutral';
}

function cacheDecisionSummary(decision: MaterialCacheDecisionSummary): string {
  const replayable = decision.replayable === null ? 'unknown' : String(decision.replayable);
  const outputs = decision.hasAllRequestedOutputs === null ? 'unknown' : String(decision.hasAllRequestedOutputs);
  return `${decision.decision} · ${decision.policy} · replayable ${replayable} · outputs ${outputs}`;
}

function workflowGateSummary(passport: WorkflowPassportProjection | null): string {
  if (!passport) {
    return 'passport 未读取';
  }
  const gateSummary = passport.gate_summary;
  const gateCounts = readRecordField(gateSummary, 'gate_counts');
  const blocking = readNumberField(gateCounts, 'block');
  const unresolved = readNumberField(gateCounts, 'unresolved');
  const pass = readNumberField(gateCounts, 'pass');
  return `pass ${pass} · unresolved ${unresolved} · block ${blocking}`;
}

function handoffSummary(card: AgentHandoffCardProjection | null): string {
  if (!card) {
    return 'handoff card 未读取';
  }
  const recovery = card.replay_recovery;
  const index = isRecord(recovery?.index) ? recovery.index : {};
  const matchingJobs = readNumberField(index, 'matching_job_count');
  return `${card.status} · refs ${card.resource_refs.length} · probes ${card.resume_probes.length} · replay ${matchingJobs}`;
}

function lifecycleTone(status: string | null | undefined): StatusTone {
  if (status === 'blocked' || status === 'failed' || status === 'rejected') {
    return 'danger';
  }
  if (status === 'pending_approval' || status === 'unresolved') {
    return 'warning';
  }
  if (status === 'approved' || status === 'completed') {
    return 'success';
  }
  if (status === 'proposed') {
    return 'info';
  }
  return 'neutral';
}

function lifecycleSummary(lifecycle: ResearchActionLifecycleProjection | null): string {
  if (!lifecycle) {
    return 'lifecycle 未读取';
  }
  const statusCounts = readRecordField(lifecycle.summary, 'status_counts');
  const blocked = readNumberField(statusCounts, 'blocked');
  const pending = readNumberField(statusCounts, 'pending_approval');
  const unresolved = readNumberField(statusCounts, 'unresolved');
  const completed = readNumberField(statusCounts, 'completed');
  return `${lifecycle.actions.length} actions · pending ${pending} · block ${blocked} · unresolved ${unresolved} · completed ${completed}`;
}

function lifecyclePrimaryMessage(lifecycle: ResearchActionLifecycleProjection | null): string {
  if (!lifecycle) {
    return 'Research Action Lifecycle 暂未读取；执行、批准或写入前仍需刷新只读投影。';
  }
  return sanitizeInspectorText(firstNonEmptyText(
    [
      lifecycle.blockers[0],
      lifecycle.unresolved[0],
      lifecycle.actions[0]?.recovery && isRecord(lifecycle.actions[0].recovery)
        ? readTextArray(lifecycle.actions[0].recovery.next_safe_local_actions)[0]
        : null,
      'Research Action Lifecycle 已读取，当前仅展示只读动作、审批、效果和恢复探针。',
    ],
    'Research Action Lifecycle 已读取。',
  ));
}

function lifecycleActionLabel(action: ResearchActionLifecycleItemProjection): string {
  return sanitizeInspectorText(action.action_id || action.action_uid || action.action_type);
}

function lifecycleActionEffectLabel(action: ResearchActionLifecycleItemProjection): string {
  const summary = isRecord(action.effect_summary) ? action.effect_summary : {};
  const externalMutation = readOptionalBooleanField(summary, 'external_mutation');
  const sourceMutation = readOptionalBooleanField(summary, 'source_material_mutation');
  const proposed = readNumberField(summary, 'proposed_effect_count');
  const actual = readNumberField(summary, 'actual_effect_count');
  const parts = [
    externalMutation === null ? null : `external mutation ${String(externalMutation)}`,
    sourceMutation === null ? null : `source mutation ${String(sourceMutation)}`,
    proposed > 0 ? `proposed ${proposed}` : null,
    actual > 0 ? `actual ${actual}` : null,
  ].filter((value): value is string => value !== null);
  return parts.length > 0 ? parts.join(' · ') : 'effect boundary read-only';
}

function lifecycleActionPreflightLabel(action: ResearchActionLifecycleItemProjection): string {
  const preflight = isRecord(action.preflight) ? action.preflight : {};
  const status = sanitizeInspectorText(readTextField(preflight, 'status') || 'missing');
  const canProceed = readOptionalBooleanField(preflight, 'can_proceed');
  const refreshRequired = readOptionalBooleanField(preflight, 'refresh_required');
  const receiptRefs = Array.isArray(preflight.receipt_refs) ? preflight.receipt_refs.length : 0;
  return `${status} · can proceed ${canProceed === null ? 'unknown' : String(canProceed)} · refresh ${refreshRequired === null ? 'unknown' : String(refreshRequired)} · receipts ${receiptRefs}`;
}

function lifecycleActionApprovalLabel(action: ResearchActionLifecycleItemProjection): string {
  const approval = isRecord(action.approval) ? action.approval : {};
  const requires = readOptionalBooleanField(approval, 'requires_user_confirmation');
  const statusCounts = readRecordField(approval, 'status_counts');
  const pending = readNumberField(statusCounts, 'pending');
  const approved = readNumberField(statusCounts, 'approved');
  const rejected = readNumberField(statusCounts, 'rejected');
  return `confirmation ${requires === null ? 'unknown' : String(requires)} · pending ${pending} · approved ${approved} · rejected ${rejected}`;
}

function readTextArray(value: unknown, maxItems = 6): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .slice(0, maxItems)
    .map((item) => sanitizeInspectorText(String(item ?? '').trim()))
    .filter((item) => item.length > 0);
}

function lifecycleProbeLabel(value: unknown, index: number): string {
  const record = isRecord(value) ? value : {};
  const label = sanitizeInspectorText(
    readTextField(record, 'label')
      || readTextField(record, 'name')
      || readTextField(record, 'endpoint')
      || `probe ${index + 1}`,
  );
  const readOnly = record.read_only === true ? 'true' : 'unknown';
  return `${label} · read-only ${readOnly}`;
}

function lifecycleRefLabel(value: unknown, index: number): string {
  const record = isRecord(value) ? value : {};
  const type = sanitizeInspectorText(
    readTextField(record, 'ref_type')
      || readTextField(record, 'object_type')
      || readTextField(record, 'kind')
      || 'ref',
  );
  const id = sanitizeInspectorText(
    readTextField(record, 'ref_id')
      || readTextField(record, 'id')
      || readTextField(record, 'artifact_id')
      || `ref:${index + 1}`,
  );
  return id.startsWith(`${type}:`) ? id : `${type}:${id}`;
}

interface ResearchActionCrosslinkSummary {
  passportRefs: string[];
  gateRefs: string[];
  handoffRefs: string[];
  boundaryProbeLabels: string[];
  provenanceRefs: string[];
  handoffMetrics: string[];
  handoffForbidden: string[];
  readOnly: boolean;
}

function researchActionRefLabel(value: unknown, index: number): string {
  const record = isRecord(value) ? value : {};
  const actionType = sanitizeInspectorText(readTextField(record, 'action_type') || 'action');
  const status = sanitizeInspectorText(readTextField(record, 'status') || 'unknown');
  const stageId = sanitizeInspectorText(readTextField(record, 'stage_id') || 'stage unknown');
  const refId = sanitizeInspectorText(
    readTextField(record, 'ref_id')
      || readTextField(record, 'action_id')
      || readTextField(record, 'job_id')
      || `research-action:${index + 1}`,
  );
  const readOnly = readOptionalBooleanField(record, 'read_only');
  return `${refId} · ${actionType} · ${status} · ${stageId} · read-only ${readOnly === null ? 'unknown' : String(readOnly)}`;
}

function researchActionRefsFromStage(stage: WorkflowPassportStage): unknown[] {
  const refs = stage.reproducibility.research_action_refs;
  return Array.isArray(refs) ? refs : [];
}

function researchActionRefsFromGate(gate: EvidenceIntegrityGateProjection | null): unknown[] {
  const refs = gate ? gate.summary.research_action_refs : null;
  return Array.isArray(refs) ? refs : [];
}

function lifecycleProbeFromBoundary(probe: BlockingActionBoundaryProbe): boolean {
  const label = [
    probe.label,
    probe.name,
    probe.url,
    readTextField(probe, 'endpoint'),
  ].map((item) => String(item ?? '')).join(' ').toLowerCase();
  return label.includes('research action lifecycle') || label.includes('/runtime/research-action-lifecycle');
}

function provenanceRefLabels(value: Record<string, unknown> | null | undefined): string[] {
  if (!value || !Array.isArray(value.derived_from)) {
    return [];
  }
  return value.derived_from
    .filter((item): item is string => typeof item === 'string' && item.includes('research_action_lifecycle'))
    .slice(0, 3)
    .map(sanitizeInspectorText);
}

function buildResearchActionCrosslinkSummary({
  stages,
  integrityGate,
  blockingBoundary,
  handoffCard,
}: {
  stages: WorkflowPassportStage[];
  integrityGate: EvidenceIntegrityGateProjection | null;
  blockingBoundary: BlockingActionBoundaryProjection | null | undefined;
  handoffCard: AgentHandoffCardProjection | null;
}): ResearchActionCrosslinkSummary {
  const passportRefs = stages
    .flatMap(researchActionRefsFromStage)
    .slice(0, 6)
    .map(researchActionRefLabel);
  const gateRefs = researchActionRefsFromGate(integrityGate)
    .slice(0, 6)
    .map(researchActionRefLabel);
  const actionRecovery = handoffCard?.action_lifecycle_recovery;
  const handoffRefs = (actionRecovery?.action_refs ?? [])
    .slice(0, 6)
    .map(researchActionRefLabel);
  const boundaryProbeLabels = (blockingBoundary?.local_read_only_probes ?? [])
    .filter(lifecycleProbeFromBoundary)
    .slice(0, 3)
    .map((probe, index) => lifecycleProbeLabel(probe, index));
  const provenanceRefs = [
    ...provenanceRefLabels(integrityGate?.provenance),
    ...provenanceRefLabels(actionRecovery?.provenance),
  ].slice(0, 4);
  const handoffMetrics = actionRecovery
    ? [
      `handoff action refs ${actionRecovery.action_ref_count}`,
      `scoped action refs ${actionRecovery.scoped_action_ref_count}`,
      `blocked actions ${actionRecovery.blocked_action_count}`,
      `pending confirmations ${actionRecovery.pending_confirmation_count}`,
      `missing preflight ${actionRecovery.missing_preflight_count}`,
    ]
    : [];
  const handoffForbidden = (actionRecovery?.forbidden_actions ?? [])
    .slice(0, 3)
    .map(sanitizeInspectorText);
  return {
    passportRefs,
    gateRefs,
    handoffRefs,
    boundaryProbeLabels,
    provenanceRefs,
    handoffMetrics,
    handoffForbidden,
    readOnly: (
      passportRefs.length > 0
      || gateRefs.length > 0
      || handoffRefs.length > 0
      || boundaryProbeLabels.length > 0
      || provenanceRefs.length > 0
    ) && actionRecovery?.read_only !== false,
  };
}

function handoffReplayRecoverySummary(card: AgentHandoffCardProjection | null): string {
  const recovery = card?.replay_recovery;
  if (!recovery) {
    return 'handoff replay recovery 未读取';
  }
  const currentReceipt = isRecord(recovery.current_receipt) ? recovery.current_receipt : {};
  const highest = isRecord(recovery.highest_priority_attempt) ? recovery.highest_priority_attempt : {};
  const index = isRecord(recovery.index) ? recovery.index : {};
  const receiptId = readTextField(currentReceipt, 'receipt_id') || 'receipt unknown';
  const jobId = readTextField(highest, 'job_id') || 'job unknown';
  const latestStatus = readTextField(highest, 'latest_status') || readTextField(currentReceipt, 'status') || 'unknown';
  const matchingJobs = readNumberField(index, 'matching_job_count');
  return `${receiptId} · ${jobId} ${latestStatus} · index ${matchingJobs} · read-only ${recovery.read_only ? 'true' : 'false'}`;
}

interface HandoffRecoveryBundle {
  stageLabel: string;
  primaryIssue: string;
  attemptLabel: string;
  receiptLabel: string;
  attemptMetrics: string[];
  resourceRefs: string[];
  replayProbeLabels: string[];
  safeProbeLabels: string[];
  forbiddenActions: string[];
  mutationBoundary: string;
  recoveryRequired: boolean;
  readOnly: boolean;
}

function handoffRefLabel(value: unknown, index: number): string {
  const record = isRecord(value) ? value : {};
  const kind = sanitizeInspectorText(readTextField(record, 'kind') || readTextField(record, 'ref_type') || 'ref');
  const rawId = sanitizeInspectorText(
    readTextField(record, 'ref_id')
      || readTextField(record, 'id')
      || readTextField(record, 'material_id')
      || `ref:${index + 1}`,
  );
  return rawId.startsWith(`${kind}:`) ? rawId : `${kind}:${rawId}`;
}

function handoffProbeLabel(value: unknown, index: number): string {
  const record = isRecord(value) ? value : {};
  return sanitizeInspectorText(readTextField(record, 'label') || readTextField(record, 'name') || `probe ${index + 1}`);
}

function handoffStageLabel(
  card: AgentHandoffCardProjection,
  stages: WorkflowPassportStage[],
): string {
  const stageId = card.current_stage_id?.trim() || '';
  const stage = stages.find((item) => item.stage_id === stageId);
  if (stage) {
    return compactStageLabel(stage);
  }
  return stageId || 'stage pending';
}

function buildHandoffRecoveryBundle(
  card: AgentHandoffCardProjection | null,
  stages: WorkflowPassportStage[],
): HandoffRecoveryBundle | null {
  if (!card) {
    return null;
  }
  const recovery = card.replay_recovery;
  const highest = isRecord(recovery?.highest_priority_attempt) ? recovery.highest_priority_attempt : {};
  const currentReceipt = isRecord(recovery?.current_receipt) ? recovery.current_receipt : {};
  const jobId = readTextField(highest, 'job_id') || card.job_id;
  const latestStatus = readTextField(highest, 'latest_status') || readTextField(currentReceipt, 'status') || card.status;
  const claimId = readTextField(highest, 'latest_required_claim_id') || card.action_preflight?.required_claim_id || 'claim pending';
  const receiptId = readTextField(highest, 'latest_receipt_id') || readTextField(currentReceipt, 'receipt_id') || card.action_preflight?.refresh_receipt_id || 'receipt pending';
  const recoveryPriority = readNumberField(highest, 'recovery_priority');
  const primaryIssue = firstNonEmptyText(
    [
      card.blockers[0],
      card.unresolved[0],
      card.action_preflight?.blockers[0],
      card.action_preflight?.unresolved[0],
    ],
    'No blocker recorded; rerun read-only probes before any mutating action.',
  );
  const replayProbeLabels = (recovery?.resume_probes ?? [])
    .slice(0, 3)
    .map(handoffProbeLabel);
  const safeProbeLabels = card.resume_probes
    .slice(0, 4)
    .map(handoffProbeLabel);
  const resourceRefs = card.resource_refs
    .slice(0, 5)
    .map(handoffRefLabel);
  const sourceMutation = recovery?.source_material_mutation === true;
  const externalMutation = recovery?.external_mutation === true;
  return {
    stageLabel: handoffStageLabel(card, stages),
    primaryIssue: sanitizeInspectorText(primaryIssue),
    attemptLabel: `${sanitizeInspectorText(jobId)} · ${sanitizeInspectorText(latestStatus)}`,
    receiptLabel: `receipt ${sanitizeInspectorText(receiptId)}`,
    attemptMetrics: [
      `claim ${sanitizeInspectorText(claimId)}`,
      `priority ${recoveryPriority}`,
      `read-only ${readBooleanField(highest, 'read_only') || recovery?.read_only === true ? 'true' : 'unknown'}`,
    ],
    resourceRefs,
    replayProbeLabels,
    safeProbeLabels,
    forbiddenActions: card.forbidden_actions.slice(0, 4).map(sanitizeInspectorText),
    mutationBoundary: `source mutation ${sourceMutation ? 'true' : 'false'} · external mutation ${externalMutation ? 'true' : 'false'}`,
    recoveryRequired: recovery?.recovery_required === true,
    readOnly: recovery?.read_only === true,
  };
}

function isWorkflowReadinessClaimsProjection(value: unknown): value is WorkflowReadinessClaimsProjection {
  if (!isRecord(value)) {
    return false;
  }
  return value.schema_version === 'scholar_ai_workflow_enforcement_v1' && Array.isArray(value.claims);
}

function isWorkflowActionPreflightProjection(value: unknown): value is WorkflowActionPreflightProjection {
  if (!isRecord(value)) {
    return false;
  }
  return (
    value.schema_version === 'scholar_ai_action_preflight_v1'
    && typeof value.action_id === 'string'
    && typeof value.required_claim_id === 'string'
    && typeof value.status === 'string'
    && typeof value.can_proceed === 'boolean'
  );
}

function preflightReceiptSummary(preflight: WorkflowActionPreflightProjection | null): string {
  const receipt = preflight?.refresh_receipt;
  if (!receipt) {
    return 'refresh receipt 未记录';
  }
  const validation = isRecord(receipt.validation) ? receipt.validation : {};
  const digests = isRecord(receipt.projection_digests) ? receipt.projection_digests : {};
  const blockerCount = readNumberField(validation, 'blocker_count');
  const unresolvedCount = readNumberField(validation, 'unresolved_count');
  return `${receipt.receipt_id} · digests ${Object.keys(digests).length} · block ${blockerCount} · unresolved ${unresolvedCount}`;
}

function preflightReceiptStatus(preflight: WorkflowActionPreflightProjection | null): string {
  const receipt = preflight?.refresh_receipt;
  if (!receipt) {
    return 'receipt missing';
  }
  const validation = isRecord(receipt.validation) ? receipt.validation : {};
  const gateStatus = readTextField(validation, 'gate_status');
  const claimStatus = readTextField(validation, 'claim_status');
  return `receipt ${receipt.status}${gateStatus || claimStatus ? ` · gate ${gateStatus || 'unknown'} · claim ${claimStatus || 'unknown'}` : ''}`;
}

function workflowReplayLineageSummary(lineage: WorkflowReplayLineageProjection | null): string {
  if (!lineage) {
    return 'lineage 未读取';
  }
  if (lineage.receipt_count === 0) {
    return 'lineage 0 receipts';
  }
  const latest = isRecord(lineage.latest) ? lineage.latest : {};
  const status = readTextField(latest, 'status') || 'unknown';
  const blockers = readNumberField(latest, 'blocker_count');
  const unresolved = readNumberField(latest, 'unresolved_count');
  return `${lineage.receipt_count} receipts · latest ${status} · block ${blockers} · unresolved ${unresolved}`;
}

function workflowReplayLineageDelta(lineage: WorkflowReplayLineageProjection | null): string {
  if (!lineage) {
    return 'Replay lineage 暂未读取。';
  }
  if (lineage.receipt_count === 0) {
    return '当前 job 还没有持久化 refresh receipt。';
  }
  const comparison = isRecord(lineage.comparison) ? lineage.comparison : {};
  const changed = Array.isArray(comparison.changed_digest_keys)
    ? comparison.changed_digest_keys.filter((item): item is string => typeof item === 'string')
    : [];
  const blockerDelta = readNumberField(comparison, 'blocker_count_delta');
  const unresolvedDelta = readNumberField(comparison, 'unresolved_count_delta');
  if (changed.length > 0) {
    return `Digest changed: ${changed.slice(0, 3).join(', ')} · block Δ ${blockerDelta} · unresolved Δ ${unresolvedDelta}`;
  }
  const latest = isRecord(lineage.latest) ? lineage.latest : {};
  const latestId = readTextField(latest, 'receipt_id') || lineage.latest_receipt_id || 'unknown';
  return `Latest receipt ${latestId} · block Δ ${blockerDelta} · unresolved Δ ${unresolvedDelta}`;
}

function workflowReplayIndexSummary(index: WorkflowReplayIndexProjection | null): string {
  if (!index) {
    return 'index 未读取';
  }
  if (index.matching_job_count === 0) {
    return 'index 0 jobs';
  }
  const summary = isRecord(index.summary) ? index.summary : {};
  const blocked = readNumberField(summary, 'blocked_job_count');
  const unresolved = readNumberField(summary, 'unresolved_job_count');
  const stale = readNumberField(summary, 'stale_job_count');
  return `${index.matching_job_count} jobs · block ${blocked} · unresolved ${unresolved} · stale ${stale}`;
}

function workflowReplayIndexRecovery(index: WorkflowReplayIndexProjection | null): string {
  if (!index) {
    return 'Replay index 暂未读取。';
  }
  if (index.blockers.length > 0) {
    return index.blockers[0];
  }
  if (index.unresolved.length > 0) {
    return index.unresolved[0];
  }
  const first = index.items[0];
  if (!first) {
    return '没有跨 job refresh receipt，可从 selected job lineage 继续。';
  }
  return `${first.job_id} · ${first.latest_status} · block ${first.latest_blocker_count} · unresolved ${first.latest_unresolved_count}`;
}

function behaviorEvalTone(pack: BehaviorEvalPackProjection | null): StatusTone {
  if (!pack) {
    return 'neutral';
  }
  if (pack.mode === 'canary') {
    return pack.summary.structural_status === 'fail' ? 'danger' : 'success';
  }
  if (pack.summary.structural_status === 'fail' || pack.summary.behavior_status === 'block') {
    return 'danger';
  }
  if (pack.summary.behavior_status === 'warn' || pack.summary.behavior_status === 'unresolved') {
    return 'warning';
  }
  return 'success';
}

function behaviorEvalStatusLabel(pack: BehaviorEvalPackProjection | null): string {
  if (!pack) {
    return '未读取';
  }
  if (pack.mode === 'canary') {
    return pack.summary.structural_status === 'pass' ? 'canary ok' : `canary ${pack.summary.structural_status}`;
  }
  return gateStatusLabel(pack.summary.behavior_status);
}

function behaviorEvalSummary(pack: BehaviorEvalPackProjection | null): string {
  if (!pack) {
    return 'behavior eval pack 未读取';
  }
  return `${pack.mode} · cases ${pack.summary.case_count} · flags ${pack.summary.red_flag_count} · block ${pack.summary.block_count} · warn ${pack.summary.warn_count}`;
}

function behaviorEvalPrimaryMessage(pack: BehaviorEvalPackProjection | null): string {
  if (!pack) {
    return 'Behavior Eval Pack 暂未读取；仅保留本地产物启发式作为上下文。';
  }
  if (pack.mode === 'canary' && pack.summary.structural_status === 'pass') {
    return pack.summary.structural_note || 'Canary mode verified the evaluator catches seeded unsafe outputs; it is not a project workflow blocker.';
  }
  return firstNonEmptyText(
    [
      pack.blockers[0],
      pack.warnings[0],
      pack.next_actions[0],
      pack.summary.structural_note,
    ],
    'Behavior Eval Pack 已读取，未返回阻断或警告。'
  );
}

function behaviorEvalReadOnlyLabel(pack: BehaviorEvalPackProjection | null): string {
  if (!pack) {
    return 'read-only unknown';
  }
  const recordWritten = pack.provenance.record_written === true;
  const readOnly = pack.provenance.read_only === true;
  return `read-only ${readOnly ? 'true' : 'unknown'} · record ${recordWritten ? 'written' : 'not written'}`;
}

function workflowReadinessClaims(
  integrityGate: EvidenceIntegrityGateProjection | null,
  handoffCard: AgentHandoffCardProjection | null,
): WorkflowReadinessClaimsProjection | null {
  if (isWorkflowReadinessClaimsProjection(integrityGate?.enforcement)) {
    return integrityGate.enforcement;
  }
  if (isWorkflowReadinessClaimsProjection(handoffCard?.readiness_claims)) {
    return handoffCard.readiness_claims;
  }
  return null;
}

function actionPreflightFromJob(job: WritingJob | null): WorkflowActionPreflightProjection | null {
  if (!job) {
    return null;
  }
  const metadataPreflight = job.metadata?.action_preflight;
  if (isWorkflowActionPreflightProjection(metadataPreflight)) {
    return metadataPreflight;
  }
  const summaryPreflight = job.writing_workflow_state_summary?.action_preflight;
  if (isWorkflowActionPreflightProjection(summaryPreflight)) {
    return summaryPreflight;
  }
  return null;
}

function workflowActionPreflight(
  selectedJob: WritingJob | null,
  jobs: WritingJob[],
  handoffCard: AgentHandoffCardProjection | null,
): WorkflowActionPreflightProjection | null {
  const selectedPreflight = actionPreflightFromJob(selectedJob);
  if (selectedPreflight) {
    return selectedPreflight;
  }
  const jobPreflight = jobs.map(actionPreflightFromJob).find((item): item is WorkflowActionPreflightProjection => item !== null);
  if (jobPreflight) {
    return jobPreflight;
  }
  return isWorkflowActionPreflightProjection(handoffCard?.action_preflight) ? handoffCard.action_preflight : null;
}

function workflowBlockingActionBoundary(
  integrityGate: EvidenceIntegrityGateProjection | null,
  readinessClaims: WorkflowReadinessClaimsProjection | null,
  actionPreflight: WorkflowActionPreflightProjection | null,
): BlockingActionBoundaryProjection | null {
  return actionPreflight?.blocking_action_boundary
    ?? integrityGate?.blocking_action_boundary
    ?? readinessClaims?.blocking_action_boundary
    ?? null;
}

function actionPreflightSummary(preflight: WorkflowActionPreflightProjection | null): string {
  if (!preflight) {
    return '尚未读取到 action preflight；命令执行前仍需当前 Workflow Passport 与 Evidence Integrity Gate。';
  }
  return firstNonEmptyText(
    [
      preflight.refresh_required ? preflight.freshness?.reasons[0] : null,
      preflight.blockers[0],
      preflight.unresolved[0],
      `Action ${preflight.action_id} requires ${preflight.required_claim_id}: ${preflight.status}.`,
    ],
    'Action preflight 已读取，但仍需复核当前门禁。'
  );
}

function blockingBoundarySummary(boundary: BlockingActionBoundaryProjection | null): string {
  if (!boundary) {
    return 'Blocking boundary 暂未读取；执行前仍需从 gate、readiness claim 与 action preflight 复核。';
  }
  return sanitizeInspectorText(firstNonEmptyText(
    [
      boundary.refresh_required
        ? 'Boundary requires fresh Workflow Passport and Evidence Integrity Gate before mutation.'
        : null,
      boundary.blockers[0],
      boundary.unresolved[0],
      boundary.next_safe_local_actions[0],
      `Action ${boundary.action_id} requires ${boundary.required_claim_id}: ${boundary.status}.`,
    ],
    'Boundary 已读取，未返回阻断消息。',
  ));
}

function blockingProbeLabel(probe: BlockingActionBoundaryProbe, index: number): string {
  const label = sanitizeInspectorText(
    probe.label?.trim()
      || probe.name?.trim()
      || `probe ${index + 1}`,
  );
  return `${label} · read-only ${probe.read_only === true ? 'true' : 'unknown'}`;
}

function blockingSignalLabel(signal: BlockingActionBoundarySignalRef): string {
  const signalId = sanitizeInspectorText(signal.signal_id || 'signal pending');
  const status = sanitizeInspectorText(signal.status || 'unknown');
  return `${signalId} · ${status}`;
}

interface BlockingRecoveryDrilldownSummary {
  signalId: string;
  stageLabel: string;
  status: string;
  source: string;
  factCount: number;
  evidenceCount: number;
  replayCount: number;
  recoveryRefCount: number;
  probeCount: number;
  primaryAction: string;
  requiresHumanReview: boolean;
  blocksClaims: boolean;
  readOnly: boolean;
  rawPathExposed: boolean;
}

function blockingRecoveryDrilldownSummary(
  drilldown: BlockingActionBoundaryRecoveryDrilldown,
  stages: WorkflowPassportStage[],
): BlockingRecoveryDrilldownSummary {
  const sourceRef = isRecord(drilldown.source_ref) ? drilldown.source_ref : {};
  const source = readTextField(sourceRef, 'source_kind') || readTextField(sourceRef, 'source_digest') || 'source pending';
  const stageId = drilldown.linked_stage_id?.trim() || '';
  const stageLabel = stageId ? linkedStageLabel(stageId, stages) : 'stage pending';
  return {
    signalId: sanitizeInspectorText(drilldown.signal_id || 'signal pending'),
    stageLabel: sanitizeInspectorText(stageLabel),
    status: sanitizeInspectorText(drilldown.status || 'unknown'),
    source: sanitizeInspectorText(source),
    factCount: Object.keys(isRecord(drilldown.checked_facts) ? drilldown.checked_facts : {}).length,
    evidenceCount: Array.isArray(drilldown.evidence_refs) ? drilldown.evidence_refs.length : 0,
    replayCount: Array.isArray(drilldown.replay_refs) ? drilldown.replay_refs.length : 0,
    recoveryRefCount: Array.isArray(drilldown.recovery_refs) ? drilldown.recovery_refs.length : 0,
    probeCount: Array.isArray(drilldown.local_read_only_probes) ? drilldown.local_read_only_probes.length : 0,
    primaryAction: sanitizeInspectorText(drilldown.next_safe_local_actions?.[0] || 'Refresh this signal before retrying the blocked action.'),
    requiresHumanReview: drilldown.requires_human_review === true,
    blocksClaims: drilldown.blocks_claims === true,
    readOnly: drilldown.read_only === true,
    rawPathExposed: drilldown.raw_path_exposed === true,
  };
}

function behaviorEvalSignalBoundarySummary(
  signalCount: number,
  blockedCount: number,
  unresolvedCount: number,
  boundaryDrilldownCount: number,
): string {
  if (signalCount === 0) {
    return 'No observation-mode behavior_eval integrity signal is currently blocking workflow claims.';
  }
  return `${signalCount} behavior_eval signals · block ${blockedCount} · unresolved ${unresolvedCount} · recovery ${boundaryDrilldownCount}`;
}

function readinessClaimSummary(claim: WorkflowReadinessClaim): string {
  return firstNonEmptyText(
    [
      claim.blockers[0],
      claim.unresolved[0],
      claim.reason,
    ],
    '等待完整性门禁证明该 readiness claim。',
  );
}

function isActiveJob(job: WritingJob): boolean {
  return ACTIVE_JOB_STATUSES.has(String(job.status));
}

function isSinglePaperJob(job: WritingJob): boolean {
  const intent = jobMetadataText(job, 'intent').toLowerCase();
  const taskGoal = jobMetadataText(job, 'task_goal').toLowerCase();
  const input = String(job.input_text || '').toLowerCase();
  return [intent, taskGoal, input].some((text) => (
    text.includes('single_paper')
    || text.includes('single-paper')
    || text.includes('deep_read')
    || text.includes('单篇')
    || text.includes('精读')
  ));
}

function summarizeStatusCounts(value: unknown): string {
  if (!isRecord(value)) {
    return '';
  }
  const entries = Object.entries(value)
    .filter((entry): entry is [string, number] => typeof entry[1] === 'number' && entry[1] > 0)
    .slice(0, 4);
  return entries.map(([status, count]) => `${status} ${count}`).join(' · ');
}

function workspaceGitSummary(workspaceStatus: AgentWorkspaceStatus | null): string {
  const git = workspaceStatus?.workspace_state.git;
  if (!git?.available) {
    return git?.error ? `git unavailable · ${sanitizeInspectorText(git.error)}` : 'git unavailable';
  }
  const branch = git.branch?.trim() || 'detached';
  return `${branch} · changed ${git.changed_count} · staged ${git.staged_count} · unstaged ${git.unstaged_count} · untracked ${git.untracked_count}`;
}

function workspaceStateTone(workspaceStatus: AgentWorkspaceStatus | null): StatusTone {
  const state = workspaceStatus?.workspace_state;
  if (!state) {
    return 'neutral';
  }
  if (!state.workspace_ready || state.git.conflicted_count > 0) {
    return 'danger';
  }
  if (state.git.changed_count > 0 || state.git.behind > 0) {
    return 'warning';
  }
  return 'success';
}

function workspaceDirectorySummary(
  label: string,
  exists: boolean,
  fileCount: number,
  totalBytes: number,
  truncated: boolean,
): string {
  const suffix = truncated ? ' · truncated' : '';
  return `${label} ${exists ? 'ready' : 'missing'} · files ${fileCount} · ${formatBytes(totalBytes)}${suffix}`;
}

function workspaceProbeLabel(value: AgentWorkspaceRecoveryProbe, index: number): string {
  const label = sanitizeInspectorText(value.label.trim() || `probe ${index + 1}`);
  const readOnly = value.read_only ? 'true' : 'unknown';
  const identifier = value.requires_identifier && value.identifier_hint ? ` · needs ${value.identifier_hint}` : '';
  const mcpTool = value.mcp_tool ? ` · ${sanitizeInspectorText(value.mcp_tool)}` : '';
  return `${label} · read-only ${readOnly}${identifier}${mcpTool}`;
}

function workspaceGoalStateSummary(state: AgentWorkspaceStatus['workspace_state']): string {
  const goal = state.goal_state;
  if (!goal.available) {
    return `goal-state unavailable${goal.error ? ` · ${sanitizeInspectorText(goal.error)}` : ''}`;
  }
  const status = goal.requirement_status;
  const total = status?.total ?? goal.requirement_count;
  const proved = status?.proved ?? goal.proved_count;
  const incomplete = status?.incomplete ?? goal.incomplete_count;
  const outOfScope = status?.out_of_scope ?? goal.out_of_scope_count;
  const latestId = status?.latest_id ?? goal.latest_requirement_id;
  const latest = latestId ? ` · latest ${sanitizeInspectorText(latestId)}` : '';
  const lifecycle = goal.lifecycle_rollup?.status
    ? ` · lifecycle ${sanitizeInspectorText(goal.lifecycle_rollup.status)}`
    : '';
  return `goal-state ${total} rows · proved ${proved} · incomplete ${incomplete} · out-of-scope ${outOfScope}${latest}${lifecycle}`;
}

function workspaceGoalCompletionClaimSummary(goal: AgentWorkspaceStatus['workspace_state']['goal_state']): {
  thisSlice: string | null;
  fullGoal: string | null;
} {
  const claim = goal.completion_claim;
  return {
    thisSlice: claim?.this_slice ? sanitizeInspectorText(claim.this_slice) : null,
    fullGoal: claim?.full_goal ? sanitizeInspectorText(claim.full_goal) : null,
  };
}

function workspaceGoalOpenRequirementLabel(
  item: AgentWorkspaceOpenRequirement,
): string {
  const id = sanitizeInspectorText(item.id);
  const status = sanitizeInspectorText(item.status);
  const requirement = item.requirement ? ` · ${sanitizeInspectorText(item.requirement)}` : '';
  const residualRisk = item.residual_risk ? ` · risk ${sanitizeInspectorText(item.residual_risk)}` : '';
  return `${id} · ${status}${requirement}${residualRisk}`;
}

function workspaceDesktopSmokeSummary(state: AgentWorkspaceStatus['workspace_state']): string {
  const smoke = state.desktop_smoke;
  if (!smoke.available) {
    return `desktop smoke unavailable${smoke.error ? ` · ${sanitizeInspectorText(smoke.error)}` : ''}`;
  }
  const status = smoke.status ? sanitizeInspectorText(smoke.status) : 'unknown';
  const runId = smoke.run_id ? sanitizeInspectorText(smoke.run_id) : 'run pending';
  const screenshot = smoke.screenshot_nonblank ? 'screenshot nonblank' : 'screenshot unresolved';
  const tree = smoke.accessibility_tree_available ? 'a11y tree yes' : 'a11y tree no';
  const filter = `candidates ${smoke.candidate_count} · ignored ${smoke.ignored_count}`;
  return `${runId} · ${status} · ${screenshot} · ${tree} · ${filter}`;
}

function workspaceOcrRuntimeTone(state: AgentWorkspaceStatus['workspace_state']): StatusTone {
  const ocr = state.ocr_runtime;
  if (!ocr.available || ocr.error) {
    return 'danger';
  }
  if (ocr.selected_engine) {
    return 'success';
  }
  return ocr.warning || ocr.readiness_blockers.length > 0 ? 'warning' : 'neutral';
}

function workspaceOcrRuntimeSummary(state: AgentWorkspaceStatus['workspace_state']): string {
  const ocr = state.ocr_runtime;
  if (!ocr.available) {
    return `ocr runtime unavailable${ocr.error ? ` · ${sanitizeInspectorText(ocr.error)}` : ''}`;
  }
  const policy = ocr.policy ? sanitizeInspectorText(ocr.policy) : 'unknown';
  const selected = ocr.selected_engine ? sanitizeInspectorText(ocr.selected_engine) : 'none';
  const language = ocr.language ? sanitizeInspectorText(ocr.language) : 'unknown';
  const source = ocr.source ? sanitizeInspectorText(ocr.source) : 'unknown';
  return `ocr ${policy} · selected ${selected} · ready ${ocr.ready_engine_count}/${ocr.engine_count} · lang ${language} · source ${source}`;
}

function workspaceOcrEngineLabel(engine: AgentWorkspaceOcrEngine): string {
  const displayName = sanitizeInspectorText(engine.display_name || engine.name);
  const readiness = sanitizeInspectorText(engine.readiness_status || (engine.available ? 'ready' : 'unavailable'));
  const network = engine.requires_network ? ' · network' : '';
  return `${displayName} · ${readiness} · ${engine.available ? 'available' : 'unavailable'} · ${sanitizeInspectorText(engine.engine_type)}${network}`;
}

function firstRecommendationMessage(healthCheck: AgentWorkflowHealthCheck | null): string {
  const recommendation = healthCheck?.recommendations?.find((item) => actionMessage(item));
  return actionMessage(recommendation)
    || actionMessage(healthCheck?.outcome.next_action)
    || '继续当前本地流程。';
}

function buildReadinessCards({
  workspaceStatus,
  bridgeStatus,
  runtimeJobsStatus,
  healthCheck,
  zoteroHealth,
  wikiReview,
  agentJobs,
  auditRecords,
}: {
  workspaceStatus: AgentWorkspaceStatus | null;
  bridgeStatus: AgentBridgeStatus | null;
  runtimeJobsStatus: RuntimeJobsStatus | null;
  healthCheck: AgentWorkflowHealthCheck | null;
  zoteroHealth: ZoteroAttachmentHealth | null;
  wikiReview: WikiReviewListModel | null;
  agentJobs: WritingJob[];
  auditRecords: AgentWorkspaceAuditRecord[];
}): ReadinessCard[] {
  const visibleRuntimeJobs = (runtimeJobsStatus?.recent ?? []).filter(isVisibleRuntimeJob);
  const runtimeBlocked = bridgeStatus?.enabled === false;
  const runtimeRead = bridgeStatus !== null || runtimeJobsStatus !== null;
  const exportJobs = visibleRuntimeJobs.filter((job) => job.kind === 'artifact_export');
  const exportFailed = exportJobs.filter((job) => job.status === 'failed').length;
  const exportActive = exportJobs.filter(isActiveJob).length;
  const exportCompleted = exportJobs.filter((job) => job.status === 'completed').length;
  const singlePaperJobs = agentJobs.filter(isSinglePaperJob);
  const singlePaperFailed = singlePaperJobs.filter((job) => job.status === 'failed').length;
  const singlePaperActive = singlePaperJobs.filter(isActiveJob).length;
  const auditErrors = auditRecords.filter((record) => record.error_code).length;
  const blockedAudit = auditRecords.filter((record) => record.allow_block_reason.toLowerCase().includes('block')).length;
  const reviewItems = wikiReview?.items ?? [];
  const pendingReviewCount = reviewItems.filter((item) => item.status === 'pending').length;
  const zoteroSummary = isRecord(zoteroHealth?.summary) ? zoteroHealth.summary : {};
  const zoteroStatusCounts = summarizeStatusCounts(zoteroSummary.status_counts);
  const inspectedItems = readNumberField(zoteroSummary, 'inspected_item_count');

  return [
    {
      id: 'runtime',
      label: '本地运行时',
      statusLabel: runtimeBlocked ? '阻塞' : runtimeRead ? '已就绪' : '未读取',
      tone: runtimeBlocked ? 'danger' : runtimeRead ? 'success' : 'neutral',
      icon: <CheckCircle2 size={15} />,
      summary: runtimeBlocked
        ? 'Agent bridge 当前不可用。'
        : `${bridgeStatus?.running_count ?? 0} 个运行中 · ${bridgeStatus?.pending_count ?? 0} 个等待 · ${visibleRuntimeJobs.length} 个本地任务`,
      nextAction: runtimeBlocked ? '刷新或重启本地后端后再创建任务。' : '继续跟踪智能体和运行时任务。',
      metrics: [
        `agent ${bridgeStatus?.enabled === false ? 'disabled' : 'enabled'}`,
        `jobs ${visibleRuntimeJobs.length}`,
      ],
    },
    {
      id: 'workflow-health',
      label: '工作流检查',
      statusLabel: healthStatusLabel(healthCheck?.status),
      tone: healthTone(healthCheck?.status),
      icon: <Activity size={15} />,
      summary: outcomeReason(healthCheck?.outcome, '被动健康检查暂未返回。'),
      nextAction: firstRecommendationMessage(healthCheck),
      metrics: [
        `checks ${healthCheck?.checks?.length ?? 0}`,
        `actions ${healthCheck?.recommendations?.length ?? 0}`,
      ],
    },
    {
      id: 'zotero',
      label: 'Zotero 附件',
      statusLabel: healthStatusLabel(zoteroHealth?.status),
      tone: healthTone(zoteroHealth?.status),
      icon: <FileText size={15} />,
      summary: zoteroHealth
        ? inspectedItems > 0
          ? `${inspectedItems} 条文献 · ${zoteroStatusCounts || zoteroHealth.status}`
          : outcomeReason(zoteroHealth.outcome, 'Zotero 数据目录尚未配置或不可读。')
        : 'Zotero 附件健康暂未读取。',
      nextAction: actionMessage(zoteroHealth?.outcome.next_action) || '在设置中提供 Zotero data directory 后重新检查。',
      metrics: [
        `snapshot ${zoteroHealth?.snapshot_used ? 'yes' : 'no'}`,
        `returned ${readNumberField(zoteroSummary, 'returned_item_count')}`,
      ],
    },
    {
      id: 'single-paper',
      label: '单篇精读',
      statusLabel: singlePaperFailed > 0 ? '失败' : singlePaperActive > 0 ? '进行中' : singlePaperJobs.length > 0 ? '已就绪' : '待创建',
      tone: singlePaperFailed > 0 ? 'danger' : singlePaperActive > 0 ? 'warning' : singlePaperJobs.length > 0 ? 'success' : 'neutral',
      icon: <Bot size={15} />,
      summary: singlePaperJobs.length > 0
        ? `${singlePaperJobs.length} 个精读任务 · ${singlePaperActive} 个进行中 · ${singlePaperFailed} 个失败`
        : '还没有可见的单篇精读任务。',
      nextAction: singlePaperJobs.length > 0 ? '打开任务详情检查待补充哨兵和 evidence refs。' : '从材料记录创建单篇精读任务。',
      metrics: [
        `active ${singlePaperActive}`,
        `failed ${singlePaperFailed}`,
      ],
    },
    {
      id: 'workspace-state',
      label: '工作区状态',
      statusLabel: workspaceStatus?.workspace_state.workspace_ready ? '可恢复' : workspaceStatus ? '需检查' : '未读取',
      tone: workspaceStateTone(workspaceStatus),
      icon: <TerminalSquare size={15} />,
      summary: workspaceGitSummary(workspaceStatus),
      nextAction: workspaceStatus?.workspace_state.next_safe_local_actions[0]
        || '读取本地工作区状态后再恢复或交接任务。',
      metrics: [
        `runtime ${workspaceStatus?.workspace_state.runtime_state_root.exists ? 'yes' : 'no'}`,
        `output ${workspaceStatus?.workspace_state.output_root.file_count ?? 0}`,
      ],
    },
    {
      id: 'review',
      label: 'Review Queue',
      statusLabel: pendingReviewCount > 0 ? '待处理' : wikiReview ? '已清空' : '未读取',
      tone: pendingReviewCount > 0 ? 'warning' : wikiReview ? 'success' : 'neutral',
      icon: <TerminalSquare size={15} />,
      summary: wikiReview
        ? `${pendingReviewCount} 个待审 · ${reviewItems.length} 个总项`
        : 'Wiki ReviewQueue 暂未读取。',
      nextAction: pendingReviewCount > 0 ? '进入 Wiki 工作台复核待审页面。' : '继续让 wiki 候选进入人工复核队列。',
      metrics: [
        `pending ${pendingReviewCount}`,
        `items ${reviewItems.length}`,
      ],
    },
    {
      id: 'export-audit',
      label: '导出与审计',
      statusLabel: auditErrors > 0 || exportFailed > 0 ? '需处理' : exportActive > 0 ? '进行中' : exportCompleted > 0 ? '已就绪' : '待生成',
      tone: auditErrors > 0 || exportFailed > 0 ? 'danger' : exportActive > 0 ? 'warning' : exportCompleted > 0 ? 'success' : 'neutral',
      icon: <FolderOpen size={15} />,
      summary: `${exportCompleted} 个导出完成 · ${exportActive} 个进行中 · ${auditErrors + blockedAudit} 条审计需看`,
      nextAction: auditErrors > 0 || exportFailed > 0
        ? '先处理失败导出或审计错误，再生成交付产物。'
        : workspaceStatus?.artifact_count
        ? '检查本地产物预览和写作导出清单。'
        : '完成写作导出后在这里检查 artifact readiness。',
      metrics: [
        `artifacts ${workspaceStatus?.artifact_count ?? 0}`,
        `audit ${auditRecords.length}`,
      ],
    },
  ];
}

function AgentJobRow({
  job,
  selected,
  onSelect,
}: {
  job: WritingJob;
  selected: boolean;
  onSelect: () => void;
}) {
  const intent = jobMetadataText(job, 'intent') || jobKindLabel(job);
  const host = jobMetadataText(job, 'agent_host') || 'agent';
  const label = job.input_text?.trim() || intent;
  const isResourceIngest = job.kind === 'resource_ingest';
  const isWritingExport = job.kind === 'artifact_export';
  const workflowPhase = workflowSummaryText(job, 'phase');
  const exportFilename = workflowSummaryText(job, 'export_filename');
  const exportFormat = workflowSummaryText(job, 'export_format');
  const actionPreflight = actionPreflightFromJob(job);
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'flex w-full min-w-0 items-start gap-3 px-3 py-2.5 text-left transition-colors',
        selected ? 'bg-primary/10' : 'hover:bg-surface-default/45',
      )}
    >
      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-surface-high text-primary/75">
        {isResourceIngest ? <FolderOpen size={15} /> : <Bot size={15} />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-label text-sm font-medium text-foreground">{label}</span>
        <span className="mt-0.5 block truncate text-[11px] text-foreground/45">
          {isResourceIngest ? 'runtime job · resource_ingest' : isWritingExport ? 'runtime job · artifact_export' : `${intent} · ${host}`}
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-1.5">
          <StatusPill tone={jobStatusTone(job)}>{job.status}</StatusPill>
          {isWritingExport ? <StatusPill tone="info">写作导出</StatusPill> : null}
          {workflowPhase ? <StatusPill tone="neutral">{workflowPhase}</StatusPill> : null}
          {actionPreflight ? (
            <StatusPill tone={claimTone(actionPreflight.status)}>
              preflight {preflightStatusLabel(actionPreflight.status)}
            </StatusPill>
          ) : null}
          {actionPreflight?.refresh_required ? <StatusPill tone="warning">refresh required</StatusPill> : null}
          {exportFormat ? <StatusPill tone="neutral">{exportFormat}</StatusPill> : null}
          {exportFilename ? <StatusPill tone="info">{exportFilename}</StatusPill> : null}
          {jobMetadataText(job, 'progress_message') ? (
            <StatusPill tone="info">{jobMetadataText(job, 'progress_message')}</StatusPill>
          ) : null}
        </span>
      </span>
    </button>
  );
}

function DetailPanel({
  tab,
  artifact,
  record,
  job,
}: {
  tab: WorkspaceTab;
  artifact: AgentWorkspaceArtifact | null;
  record: AgentWorkspaceAuditRecord | null;
  job: WritingJob | null;
}) {
  if (tab === 'agents') {
    if (job === null) {
      return <EmptyState title="没有选中任务" icon={<Bot size={36} />} className="h-full" />;
    }
    const metadata = job.metadata ?? {};
    const actionPreflight = actionPreflightFromJob(job);
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="shrink-0 border-b border-outline-variant/50 px-4 py-3">
          <div className="flex min-w-0 items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="truncate font-display text-base font-semibold text-foreground">
                {job.input_text?.trim() || jobMetadataText(job, 'intent') || '智能体任务'}
              </h2>
              <p className="mt-0.5 truncate text-[11px] text-foreground/45">{job.job_id}</p>
            </div>
            <StatusPill tone={jobStatusTone(job)}>{job.status}</StatusPill>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <StatusPill tone="neutral">{jobMetadataText(job, 'agent_host') || 'agent'}</StatusPill>
            <StatusPill tone="neutral">{jobMetadataText(job, 'intent') || jobKindLabel(job)}</StatusPill>
            {jobMetadataText(job, 'project_id') ? <StatusPill tone="info">{jobMetadataText(job, 'project_id')}</StatusPill> : null}
          </div>
        </div>
        <div className="custom-scrollbar min-h-0 flex-1 overflow-auto px-4 py-3">
          {actionPreflight ? (
            <section className="mb-4">
              <h3 className="mb-1.5 font-label text-[11px] font-semibold uppercase text-foreground/40">Action Preflight</h3>
              <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <StatusPill tone={claimTone(actionPreflight.status)}>{preflightStatusLabel(actionPreflight.status)}</StatusPill>
                  <StatusPill tone={actionPreflight.can_proceed ? 'success' : 'danger'}>can proceed {String(actionPreflight.can_proceed)}</StatusPill>
                  <StatusPill tone={actionPreflight.require_ready ? 'warning' : 'neutral'}>require ready {String(actionPreflight.require_ready)}</StatusPill>
                  <StatusPill tone={actionPreflight.refresh_required ? 'warning' : actionPreflight.freshness?.status === 'fresh' ? 'success' : 'neutral'}>
                    {preflightFreshnessLabel(actionPreflight)}
                  </StatusPill>
                  {actionPreflight.refresh_required ? <StatusPill tone="warning">refresh required</StatusPill> : null}
                </div>
                <p className="mt-2 break-words text-xs leading-5 text-foreground/70">
                  {actionPreflightSummary(actionPreflight)}
                </p>
              </div>
            </section>
          ) : null}
          <section className="mb-4">
            <h3 className="mb-1.5 font-label text-[11px] font-semibold uppercase text-foreground/40">Progress</h3>
            <p className="break-words rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2 text-xs leading-5 text-foreground/70">
              {jobMetadataText(job, 'progress_message') || '—'}
            </p>
          </section>
          <section>
            <h3 className="mb-1.5 font-label text-[11px] font-semibold uppercase text-foreground/40">Metadata</h3>
            <pre className="whitespace-pre-wrap break-words rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2 font-mono text-xs leading-5 text-foreground/70">
              {displayInspectorJson(metadata)}
            </pre>
          </section>
        </div>
      </div>
    );
  }

  if (tab === 'artifacts') {
    if (artifact === null) {
      return <EmptyState title="没有选中文件" icon={<FileText size={36} />} className="h-full" />;
    }
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="shrink-0 border-b border-outline-variant/50 px-4 py-3">
          <div className="flex min-w-0 items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="truncate font-display text-base font-semibold text-foreground">{artifact.name}</h2>
              <p className="mt-0.5 truncate text-[11px] text-foreground/45">{artifact.path}</p>
            </div>
            <StatusPill tone="info">{formatBytes(artifact.size_bytes)}</StatusPill>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <StatusPill tone="neutral">{KIND_LABELS[artifact.kind] ?? artifact.kind}</StatusPill>
            <StatusPill tone={artifact.truncated ? 'warning' : 'success'}>
              {artifact.truncated ? 'preview' : 'full preview'}
            </StatusPill>
            <StatusPill tone="neutral">{formatDateTime(artifact.modified_at)}</StatusPill>
          </div>
        </div>
        <pre className="custom-scrollbar min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words px-4 py-3 font-mono text-xs leading-5 text-foreground/70">
          {artifact.preview || '无文本预览'}
        </pre>
      </div>
    );
  }

  if (record === null) {
    return <EmptyState title="没有选中记录" icon={<TerminalSquare size={36} />} className="h-full" />;
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-outline-variant/50 px-4 py-3">
        <div className="flex min-w-0 items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate font-display text-base font-semibold text-foreground">{record.tool_name}</h2>
            <p className="mt-0.5 truncate text-[11px] text-foreground/45">{formatDateTime(record.timestamp)}</p>
          </div>
          <StatusPill tone={statusTone(record)}>{record.error_code ?? 'ok'}</StatusPill>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <StatusPill tone="neutral">{record.allow_block_reason || '—'}</StatusPill>
          <StatusPill tone="info">{record.duration_ms} ms</StatusPill>
        </div>
      </div>
      <div className="custom-scrollbar min-h-0 flex-1 overflow-auto px-4 py-3">
        <section className="mb-4">
          <h3 className="mb-1.5 font-label text-[11px] font-semibold uppercase text-foreground/40">Args</h3>
          <p className="break-words rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2 font-mono text-xs leading-5 text-foreground/65">
            {stringifyArgs(record.args_summary)}
          </p>
        </section>
        <section>
          <h3 className="mb-1.5 font-label text-[11px] font-semibold uppercase text-foreground/40">Preview</h3>
          <pre className="whitespace-pre-wrap break-words rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2 font-mono text-xs leading-5 text-foreground/70">
            {record.result_preview || '—'}
          </pre>
        </section>
      </div>
    </div>
  );
}

export function ResearchWorkflowSpine({
  loading,
  passport,
  integrityGate,
  actionLifecycle,
  handoffCard,
  actionPreflight,
  workflowReplayIndex,
  workflowReplayLineage,
  behaviorEvalPack,
  behaviorEvalArtifacts,
  density = 'default',
}: {
  loading: boolean;
  passport: WorkflowPassportProjection | null;
  integrityGate: EvidenceIntegrityGateProjection | null;
  actionLifecycle: ResearchActionLifecycleProjection | null;
  handoffCard: AgentHandoffCardProjection | null;
  actionPreflight: WorkflowActionPreflightProjection | null;
  workflowReplayIndex: WorkflowReplayIndexProjection | null;
  workflowReplayLineage: WorkflowReplayLineageProjection | null;
  behaviorEvalPack: BehaviorEvalPackProjection | null;
  behaviorEvalArtifacts: AgentWorkspaceArtifact[];
  density?: WorkflowSpineDensity;
}) {
  const isDesktopAcceptance = density === 'desktop-acceptance';
  const stages = passport?.stages ?? [];
  const visibleStages = isDesktopAcceptance ? stages.slice(0, 4) : stages;
  const currentStage = findCurrentStage(passport);
  const statusCounts = integrityGate ? readRecordField(integrityGate.summary, 'status_counts') : {};
  const unresolvedCount = integrityGate?.unresolved.length ?? readNumberField(statusCounts, 'unresolved');
  const blockerCount = integrityGate?.blockers.length ?? readNumberField(statusCounts, 'block');
  const integritySignals = integrityGate?.signals ?? [];
  const firstSignal = integrityGate?.signals[0] ?? null;
  const firstSignalDrilldown = integritySignalDrilldownSummary(firstSignal);
  const [activeSignalId, setActiveSignalId] = useState<string | null>(null);
  const activeSignal = integritySignals.find((signal) => signal.signal_id === activeSignalId) ?? firstSignal;
  const activeSignalDetails = activeSignal ? buildIntegrityDrilldownDetails(activeSignal) : null;
  const visibleSignals = integritySignals.slice(0, isDesktopAcceptance ? 2 : 4);
  const locatorQualitySignals = buildLocatorQualitySignalSummaries(integritySignals, isDesktopAcceptance ? 2 : 4);
  const behaviorEvalSignals = integritySignals.filter(isBehaviorEvalSignal);
  const behaviorEvalBlockingSignals = behaviorEvalSignals.filter((signal) => signal.status === 'block' || signal.severity === 'block');
  const behaviorEvalUnresolvedSignals = behaviorEvalSignals.filter((signal) => signal.status === 'unresolved');
  const handoffBlocked = (handoffCard?.blockers.length ?? 0) > 0;
  const handoffUnresolved = (handoffCard?.unresolved.length ?? 0) > 0;
  const lifecycleActions = actionLifecycle?.actions ?? [];
  const visibleLifecycleActions = lifecycleActions.slice(0, isDesktopAcceptance ? 2 : 4);
  const lifecycleStatusCounts = actionLifecycle ? readRecordField(actionLifecycle.summary, 'status_counts') : {};
  const lifecycleBlockedCount = readNumberField(lifecycleStatusCounts, 'blocked') + readNumberField(lifecycleStatusCounts, 'failed');
  const lifecyclePendingCount = readNumberField(lifecycleStatusCounts, 'pending_approval');
  const lifecycleUnresolvedCount = readNumberField(lifecycleStatusCounts, 'unresolved');
  const lifecycleNeedsConfirmation = actionLifecycle?.summary.requires_user_confirmation === true;
  const readinessClaims = workflowReadinessClaims(integrityGate, handoffCard);
  const visibleReadinessClaims = readinessClaims?.claims.slice(0, isDesktopAcceptance ? 2 : 4) ?? [];
  const blockingBoundary = workflowBlockingActionBoundary(integrityGate, readinessClaims, actionPreflight);
  const boundaryBlocked = blockingBoundary?.status === 'blocked' || blockingBoundary?.can_proceed === false;
  const boundaryUnresolved = blockingBoundary?.status === 'unresolved';
  const visibleBoundaryClaims = blockingBoundary?.blocked_claims.slice(0, isDesktopAcceptance ? 1 : 3) ?? [];
  const visibleBlockedBoundarySignals = blockingBoundary?.blocked_signal_refs.slice(0, isDesktopAcceptance ? 2 : 4) ?? [];
  const visibleUnresolvedBoundarySignals = blockingBoundary?.unresolved_signal_refs.slice(0, isDesktopAcceptance ? 2 : 4) ?? [];
  const visibleBoundaryRecoveryDrilldowns = (blockingBoundary?.recovery_drilldowns ?? [])
    .slice(0, isDesktopAcceptance ? 2 : 4)
    .map((drilldown) => blockingRecoveryDrilldownSummary(drilldown, stages));
  const behaviorEvalBoundaryDrilldowns = (blockingBoundary?.recovery_drilldowns ?? [])
    .filter(isBehaviorEvalSignal)
    .slice(0, isDesktopAcceptance ? 2 : 4)
    .map((drilldown) => blockingRecoveryDrilldownSummary(drilldown, stages));
  const visibleBoundaryProbes = blockingBoundary?.local_read_only_probes.slice(0, isDesktopAcceptance ? 3 : 5) ?? [];
  const visibleBoundaryForbidden = blockingBoundary?.forbidden_actions.slice(0, isDesktopAcceptance ? 2 : 4) ?? [];
  const preflightBlocked = actionPreflight?.status === 'blocked' || actionPreflight?.can_proceed === false;
  const preflightUnresolved = actionPreflight?.status === 'unresolved';
  const preflightRefreshRequired = actionPreflight?.refresh_required === true || actionPreflight?.freshness?.refresh_required === true;
  const replayIndexBlocked = (workflowReplayIndex?.blockers.length ?? 0) > 0;
  const replayIndexUnresolved = (workflowReplayIndex?.unresolved.length ?? 0) > 0;
  const lineageBlocked = (workflowReplayLineage?.blockers.length ?? 0) > 0;
  const lineageUnresolved = (workflowReplayLineage?.unresolved.length ?? 0) > 0;
  const handoffRecoveryBundle = buildHandoffRecoveryBundle(handoffCard, stages);
  const cacheDecisionRefs = materialCacheDecisionRefs(stages);
  const visibleCacheDecisionRefs = cacheDecisionRefs.slice(0, isDesktopAcceptance ? 2 : 4);
  const researchActionCrosslinks = buildResearchActionCrosslinkSummary({
    stages,
    integrityGate,
    blockingBoundary,
    handoffCard,
  });
  const crosslinkCount = (
    researchActionCrosslinks.passportRefs.length
    + researchActionCrosslinks.gateRefs.length
    + researchActionCrosslinks.handoffRefs.length
    + researchActionCrosslinks.boundaryProbeLabels.length
  );

  return (
    <section
      aria-label="研究流程主干"
      className={cn(
        'min-w-0 max-w-full overflow-hidden rounded-md border border-outline-variant/60 bg-surface-lowest',
        isDesktopAcceptance ? 'mb-0 px-3 py-2' : 'mb-4 px-4 py-3',
      )}
      data-density={density}
    >
      <div className={cn(
        'flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between',
        isDesktopAcceptance ? 'mb-2' : 'mb-3',
      )}>
        <div className="min-w-0">
          <h2 className="font-display text-sm font-semibold text-foreground">研究流程</h2>
          <p className={cn(
            'mt-0.5 break-words text-foreground/50',
            isDesktopAcceptance ? 'text-[11px] leading-4' : 'text-xs leading-5',
          )}>
            {currentStage
              ? `当前阶段：${compactStageLabel(currentStage)} · ${buildStageReason(currentStage)}`
              : loading
              ? '正在读取 workflow passport 和 integrity gate。'
              : '尚未读取到 workflow passport。'}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-1.5">
          <StatusPill tone={gateTone(currentStage?.gate.status, currentStage?.gate.severity)}>
            {gateStatusLabel(currentStage?.gate.status)}
          </StatusPill>
          <StatusPill tone={integrityGate ? gateTone(integrityGate.status) : 'neutral'}>
            integrity {integrityGate ? gateStatusLabel(integrityGate.status) : '未读取'}
          </StatusPill>
          <StatusPill tone={handoffBlocked ? 'danger' : handoffUnresolved ? 'warning' : handoffCard ? 'success' : 'neutral'}>
            handoff {handoffCard ? gateStatusLabel(handoffBlocked ? 'block' : handoffUnresolved ? 'unresolved' : 'pass') : '未读取'}
          </StatusPill>
          <StatusPill tone={actionPreflight ? claimTone(actionPreflight.status) : 'neutral'}>
            preflight {preflightStatusLabel(actionPreflight?.status)}
          </StatusPill>
          <StatusPill tone={blockingBoundary ? claimTone(blockingBoundary.status) : 'neutral'}>
            boundary {claimStatusLabel(blockingBoundary?.status)}
          </StatusPill>
          <StatusPill tone={lineageBlocked ? 'danger' : lineageUnresolved ? 'warning' : workflowReplayLineage ? 'info' : 'neutral'}>
            replay {workflowReplayLineage ? workflowReplayLineage.receipt_count : '未读取'}
          </StatusPill>
          <StatusPill tone={replayIndexBlocked ? 'danger' : replayIndexUnresolved ? 'warning' : workflowReplayIndex ? 'info' : 'neutral'}>
            replay index {workflowReplayIndex ? workflowReplayIndex.matching_job_count : '未读取'}
          </StatusPill>
          <StatusPill tone={behaviorEvalTone(behaviorEvalPack)}>
            behavior eval {behaviorEvalStatusLabel(behaviorEvalPack)}
          </StatusPill>
          <StatusPill tone={behaviorEvalBlockingSignals.length > 0 ? 'danger' : behaviorEvalSignals.length > 0 ? 'warning' : 'neutral'}>
            behavior gate {behaviorEvalSignals.length}
          </StatusPill>
          <StatusPill tone={lifecycleBlockedCount > 0 ? 'danger' : lifecyclePendingCount > 0 || lifecycleUnresolvedCount > 0 ? 'warning' : actionLifecycle ? 'info' : 'neutral'}>
            lifecycle {actionLifecycle ? actionLifecycle.actions.length : '未读取'}
          </StatusPill>
          {lifecycleNeedsConfirmation ? (
            <StatusPill tone="warning">confirmation required</StatusPill>
          ) : null}
        </div>
      </div>

      <div
        className={cn(
          'mb-2 min-w-0 rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2.5',
          isDesktopAcceptance ? 'px-2 py-2' : '',
        )}
        role="region"
        aria-label="Research action crosslinks"
      >
        <div className="flex min-w-0 items-center justify-between gap-2">
          <h3 className="truncate font-label text-xs font-semibold text-foreground">Research Action Crosslinks</h3>
          <StatusPill tone={crosslinkCount > 0 ? 'info' : 'neutral'}>crosslinks {crosslinkCount}</StatusPill>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <StatusPill tone={researchActionCrosslinks.readOnly ? 'success' : 'neutral'}>
            lifecycle read-only {researchActionCrosslinks.readOnly ? 'true' : 'unknown'}
          </StatusPill>
          <StatusPill tone="neutral">passport refs {researchActionCrosslinks.passportRefs.length}</StatusPill>
          <StatusPill tone="neutral">gate refs {researchActionCrosslinks.gateRefs.length}</StatusPill>
          <StatusPill tone="neutral">handoff refs {researchActionCrosslinks.handoffRefs.length}</StatusPill>
          <StatusPill tone={researchActionCrosslinks.boundaryProbeLabels.length > 0 ? 'info' : 'neutral'}>
            boundary probes {researchActionCrosslinks.boundaryProbeLabels.length}
          </StatusPill>
          {researchActionCrosslinks.provenanceRefs.map((ref, index) => (
            <StatusPill key={`lifecycle-provenance:${index}:${ref}`} tone="info">{ref}</StatusPill>
          ))}
        </div>
        {crosslinkCount > 0 ? (
          <div className="mt-2 grid gap-2 lg:grid-cols-3">
            <div className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-lowest px-2 py-2">
              <h4 className="font-label text-[11px] font-semibold text-foreground/45">Passport</h4>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {researchActionCrosslinks.passportRefs.length === 0 ? (
                  <StatusPill tone="neutral">refs pending</StatusPill>
                ) : researchActionCrosslinks.passportRefs.map((ref, index) => (
                  <StatusPill key={`passport-action-ref:${index}:${ref}`} tone="info">{ref}</StatusPill>
                ))}
              </div>
            </div>
            <div className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-lowest px-2 py-2">
              <h4 className="font-label text-[11px] font-semibold text-foreground/45">Integrity Gate / Boundary</h4>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {[...researchActionCrosslinks.gateRefs, ...researchActionCrosslinks.boundaryProbeLabels].length === 0 ? (
                  <StatusPill tone="neutral">refs pending</StatusPill>
                ) : [...researchActionCrosslinks.gateRefs, ...researchActionCrosslinks.boundaryProbeLabels].map((ref, index) => (
                  <StatusPill key={`gate-action-ref:${index}:${ref}`} tone="neutral">{ref}</StatusPill>
                ))}
              </div>
            </div>
            <div className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-lowest px-2 py-2">
              <h4 className="font-label text-[11px] font-semibold text-foreground/45">Agent Handoff</h4>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {[...researchActionCrosslinks.handoffMetrics, ...researchActionCrosslinks.handoffRefs].length === 0 ? (
                  <StatusPill tone="neutral">refs pending</StatusPill>
                ) : [...researchActionCrosslinks.handoffMetrics, ...researchActionCrosslinks.handoffRefs].map((ref, index) => (
                  <StatusPill key={`handoff-action-ref:${index}:${ref}`} tone="info">{ref}</StatusPill>
                ))}
                {researchActionCrosslinks.handoffForbidden.map((item, index) => (
                  <StatusPill key={`handoff-action-forbidden:${index}:${item}`} tone="warning">{item}</StatusPill>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </div>

      <div className={cn(
        'grid gap-2',
        isDesktopAcceptance ? 'grid-cols-2' : 'xl:grid-cols-[minmax(0,1.45fr)_minmax(260px,0.8fr)]',
      )}>
        <div className="min-w-0 rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3">
          <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
            <h3 className="truncate font-label text-xs font-semibold text-foreground">Workflow Passport</h3>
            <StatusPill tone="neutral">{workflowGateSummary(passport)}</StatusPill>
          </div>
          {visibleStages.length === 0 ? (
            <p className="break-words text-xs leading-5 text-foreground/55">
              {loading ? '正在读取阶段账本。' : '还没有阶段账本。'}
            </p>
          ) : (
            <div className="grid gap-2 md:grid-cols-2">
              {visibleStages.map((stage) => {
                const isCurrent = stage.stage_id === currentStage?.stage_id;
                const stageSignals = integritySignalsForStage(stage, integritySignals);
                const stageCacheDecisions = materialCacheDecisionRefsForStage(stage);
                return (
                  <article
                    key={stage.stage_id}
                    className={cn(
                      'min-w-0 rounded-md border px-2.5 py-2',
                      isCurrent ? 'border-primary/35 bg-primary/5' : 'border-outline-variant/35 bg-surface-lowest',
                    )}
                  >
                    <div className="flex min-w-0 items-center justify-between gap-2">
                      <h4 className="truncate font-label text-xs font-medium text-foreground">{compactStageLabel(stage)}</h4>
                      <StatusPill tone={gateTone(stage.gate.status, stage.gate.severity)}>
                        {gateStatusLabel(stage.gate.status)}
                      </StatusPill>
                    </div>
                    <p className="mt-1 min-h-[32px] break-words text-[11px] leading-4 text-foreground/55">
                      {buildStageReason(stage)}
                    </p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      <StatusPill tone="neutral">artifacts {stage.present_artifacts.length}</StatusPill>
                      <StatusPill tone="neutral">events {stage.event_types.length}</StatusPill>
                      <StatusPill tone={signalCollectionTone(stageSignals)}>integrity links {stageSignals.length}</StatusPill>
                      {stageCacheDecisions.length > 0 ? (
                        <StatusPill tone={stageCacheDecisions.some((decision) => decision.replayable) ? 'info' : 'warning'}>
                          cache decisions {stageCacheDecisions.length}
                        </StatusPill>
                      ) : null}
                      {stageSignals[0] ? (
                        <StatusPill tone={gateTone(stageSignals[0].status, stageSignals[0].severity)}>
                          {stageSignals[0].signal_id}
                        </StatusPill>
                      ) : null}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
          {cacheDecisionRefs.length > 0 ? (
            <div
              className="mt-3 rounded-md border border-outline-variant/35 bg-surface-lowest px-2.5 py-2"
              role="region"
              aria-label="Material cache decision records"
            >
              <div className="flex min-w-0 items-center justify-between gap-2">
                <h4 className="truncate font-label text-[11px] font-semibold text-foreground">
                  Material Cache Decisions
                </h4>
                <StatusPill tone="info">records {cacheDecisionRefs.length}</StatusPill>
              </div>
              <div className="mt-2 grid gap-2">
                {visibleCacheDecisionRefs.map((decision) => (
                  <div
                    key={`${decision.stageId}:${decision.refId}`}
                    className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-low px-2 py-2"
                  >
                    <div className="flex min-w-0 items-center justify-between gap-2">
                      <span className="truncate font-label text-[11px] font-medium text-foreground">
                        {decision.stageLabel}
                      </span>
                      <StatusPill tone={cacheDecisionTone(decision)}>
                        {decision.decision}
                      </StatusPill>
                    </div>
                    <p className="mt-1 break-words font-mono text-[11px] leading-4 text-foreground/65">
                      {decision.refId}
                    </p>
                    <p className="mt-1 break-words text-[11px] leading-4 text-foreground/55">
                      {decision.reason}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <StatusPill tone="neutral">{cacheDecisionSummary(decision)}</StatusPill>
                      <StatusPill tone="neutral">{decision.artifactFamilyDigest}</StatusPill>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <div className="grid min-w-0 gap-2">
          <article className="min-w-0 rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3">
            <div className="flex min-w-0 items-center justify-between gap-2">
              <h3 className="truncate font-label text-xs font-semibold text-foreground">Evidence Integrity Gate</h3>
              <StatusPill tone={integrityGate ? gateTone(integrityGate.status) : 'neutral'}>
                {integrityGate ? gateStatusLabel(integrityGate.status) : '未读取'}
              </StatusPill>
            </div>
            <p className="mt-2 break-words text-xs leading-5 text-foreground/60">
              {firstSignal?.message
                || integrityGate?.unresolved[0]
                || integrityGate?.blockers[0]
                || (integrityGate ? '当前未返回阻断信号。' : 'integrity gate 暂未读取。')}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <StatusPill tone={blockerCount > 0 ? 'danger' : 'neutral'}>block {blockerCount}</StatusPill>
              <StatusPill tone={unresolvedCount > 0 ? 'warning' : 'neutral'}>unresolved {unresolvedCount}</StatusPill>
              <StatusPill tone="neutral">{integrityGate ? summarizeGateCounts(integrityGate.summary) : 'no signals'}</StatusPill>
              {firstSignalDrilldown ? <StatusPill tone="info">{firstSignalDrilldown.source}</StatusPill> : null}
              {firstSignalDrilldown ? <StatusPill tone="neutral">facts {firstSignalDrilldown.factCount}</StatusPill> : null}
              {firstSignalDrilldown ? <StatusPill tone="neutral">refs {firstSignalDrilldown.evidenceCount}</StatusPill> : null}
              {firstSignalDrilldown && firstSignalDrilldown.replayCount > 0 ? <StatusPill tone="info">replay {firstSignalDrilldown.replayCount}</StatusPill> : null}
              {firstSignalDrilldown?.requiresHumanReview ? <StatusPill tone="warning">human review</StatusPill> : null}
              {firstSignalDrilldown?.blocksClaims ? <StatusPill tone="danger">blocks claims</StatusPill> : null}
            </div>
            {activeSignal && activeSignalDetails ? (
              <details open className="mt-3 rounded-md border border-outline-variant/35 bg-surface-lowest px-2.5 py-2">
                <summary className="flex min-w-0 cursor-pointer list-none items-start justify-between gap-2 marker:hidden">
                  <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <ChevronRight size={14} className="shrink-0 text-foreground/35" aria-hidden="true" />
                      <h4 className="truncate font-label text-[11px] font-semibold text-foreground">
                        Integrity Drilldown Inspector
                      </h4>
                    </div>
                    <p className="mt-1 break-words text-[11px] leading-4 text-foreground/55">
                      {activeSignal.message}
                    </p>
                  </div>
                  <StatusPill tone={gateTone(activeSignal.status, activeSignal.severity)}>
                    {gateStatusLabel(activeSignal.status)}
                  </StatusPill>
                </summary>

                {visibleSignals.length > 1 ? (
                  <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Integrity signal selector">
                    {visibleSignals.map((signal) => (
                      <button
                        key={signal.signal_id}
                        type="button"
                        onClick={() => setActiveSignalId(signal.signal_id)}
                        className={cn(
                          'max-w-full truncate rounded-md border px-2 py-1 text-left font-label text-[11px] leading-4 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/45',
                          signal.signal_id === activeSignal.signal_id
                            ? 'border-primary/45 bg-primary/10 text-foreground'
                            : 'border-outline-variant/40 bg-surface-low text-foreground/65 hover:bg-surface',
                        )}
                      >
                        {signal.signal_id}
                      </button>
                    ))}
                  </div>
                ) : null}

                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  <div className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-low px-2 py-2">
                    <div className="flex flex-wrap gap-1.5">
                      <StatusPill tone="info">linked stage {linkedStageLabel(activeSignalDetails.linkedStageId, stages)}</StatusPill>
                      <StatusPill tone="neutral">{activeSignalDetails.source}</StatusPill>
                      <StatusPill tone={activeSignalDetails.rawPathExposed ? 'danger' : 'success'}>
                        raw path {activeSignalDetails.rawPathExposed ? 'exposed' : 'redacted'}
                      </StatusPill>
                      {activeSignalDetails.blocksClaims ? <StatusPill tone="danger">claim blocker</StatusPill> : null}
                      {activeSignalDetails.requiresHumanReview ? <StatusPill tone="warning">review required</StatusPill> : null}
                    </div>
                    <p className="mt-2 break-words font-mono text-[11px] leading-4 text-foreground/55">
                      {activeSignalDetails.sourceId} · {activeSignalDetails.sourceDigest}
                    </p>
                  </div>

                  <div className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-low px-2 py-2">
                    <div className="flex flex-wrap gap-1.5">
                      <StatusPill tone="neutral">facts {activeSignalDetails.factItems.length}</StatusPill>
                      <StatusPill tone="neutral">evidence refs {activeSignalDetails.evidenceRefs.length}</StatusPill>
                      <StatusPill tone={activeSignalDetails.replayRefs.length > 0 ? 'info' : 'neutral'}>
                        replay refs {activeSignalDetails.replayRefs.length}
                      </StatusPill>
                    </div>
                    <dl className="mt-2 grid gap-1">
                      {activeSignalDetails.factItems.length === 0 ? (
                        <div className="text-[11px] leading-4 text-foreground/45">checked facts pending</div>
                      ) : activeSignalDetails.factItems.map((fact) => (
                        <div key={fact.key} className="grid min-w-0 grid-cols-[minmax(82px,0.45fr)_minmax(0,1fr)] gap-2 text-[11px] leading-4">
                          <dt className="truncate font-label text-foreground/45">{fact.key}</dt>
                          <dd className="break-words font-mono text-foreground/65">{fact.value}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                </div>

                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  <div className="min-w-0">
                    <h5 className="font-label text-[11px] font-semibold text-foreground/45">Evidence refs</h5>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {activeSignalDetails.evidenceRefs.length === 0 ? (
                        <StatusPill tone="neutral">none</StatusPill>
                      ) : activeSignalDetails.evidenceRefs.map((ref) => (
                        <StatusPill key={`${ref.refType}:${ref.refId}`} tone="neutral">
                          {ref.refType}:{ref.refId}
                        </StatusPill>
                      ))}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <h5 className="font-label text-[11px] font-semibold text-foreground/45">Replay refs</h5>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {activeSignalDetails.replayRefs.length === 0 ? (
                        <StatusPill tone="neutral">none</StatusPill>
                      ) : activeSignalDetails.replayRefs.map((ref) => (
                        <StatusPill key={`${ref.refType}:${ref.refId}`} tone="info">
                          {ref.refType}:{ref.refId}
                        </StatusPill>
                      ))}
                    </div>
                  </div>
                </div>

                {activeSignal.next_actions.length > 0 ? (
                  <div className="mt-2 rounded-md border border-outline-variant/25 bg-surface-low px-2 py-2">
                    <h5 className="font-label text-[11px] font-semibold text-foreground/45">Next local actions</h5>
                    <ul className="mt-1 grid gap-1 text-[11px] leading-4 text-foreground/60">
                      {activeSignal.next_actions.slice(0, 3).map((action) => (
                        <li key={action} className="break-words">{action}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </details>
            ) : null}
          </article>

          <article className="min-w-0 rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3">
            <div className="flex min-w-0 items-center justify-between gap-2">
              <h3 className="truncate font-label text-xs font-semibold text-foreground">Readiness Claims</h3>
              <StatusPill tone={claimTone(readinessClaims?.status)}>
                {readinessClaims ? claimStatusLabel(readinessClaims.status) : '未读取'}
              </StatusPill>
            </div>
            {visibleReadinessClaims.length === 0 ? (
              <p className="mt-2 break-words text-xs leading-5 text-foreground/60">
                Readiness claim 投影暂未读取。
              </p>
            ) : (
              <div className="mt-2 grid gap-2">
                {visibleReadinessClaims.map((claim) => (
                  <div
                    key={claim.claim_id}
                    className="min-w-0 rounded-md border border-outline-variant/35 bg-surface-lowest px-2.5 py-2"
                  >
                    <div className="flex min-w-0 items-center justify-between gap-2">
                      <span className="truncate font-label text-[11px] font-medium text-foreground">
                        {claim.label || claim.claim_id}
                      </span>
                      <StatusPill tone={claimTone(claim.status)}>
                        {claimStatusLabel(claim.status)}
                      </StatusPill>
                    </div>
                    <p className="mt-1 break-words text-[11px] leading-4 text-foreground/55">
                      {readinessClaimSummary(claim)}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </article>

          <article className="min-w-0 rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3">
            <div className="flex min-w-0 items-center justify-between gap-2">
              <h3 className="truncate font-label text-xs font-semibold text-foreground">Command Preflight</h3>
              <StatusPill tone={actionPreflight ? claimTone(actionPreflight.status) : 'neutral'}>
                {preflightStatusLabel(actionPreflight?.status)}
              </StatusPill>
            </div>
            <p className="mt-2 break-words text-xs leading-5 text-foreground/60">
              {actionPreflightSummary(actionPreflight)}
            </p>
            <p className="mt-1 break-words text-[11px] leading-4 text-foreground/50">
              {preflightReceiptStatus(actionPreflight)}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <StatusPill tone={preflightBlocked ? 'danger' : actionPreflight ? 'success' : 'neutral'}>
                can proceed {actionPreflight ? String(actionPreflight.can_proceed) : 'unknown'}
              </StatusPill>
              <StatusPill tone={actionPreflight?.require_ready ? 'warning' : 'neutral'}>
                require ready {actionPreflight ? String(actionPreflight.require_ready) : 'unknown'}
              </StatusPill>
              <StatusPill tone={preflightRefreshRequired ? 'warning' : actionPreflight?.freshness?.status === 'fresh' ? 'success' : 'neutral'}>
                {preflightFreshnessLabel(actionPreflight)}
              </StatusPill>
              {preflightRefreshRequired ? <StatusPill tone="warning">refresh required</StatusPill> : null}
              {actionPreflight ? <StatusPill tone="neutral">{actionPreflight.action_id}</StatusPill> : null}
              {actionPreflight ? <StatusPill tone={claimTone(actionPreflight.claim_status)}>{actionPreflight.required_claim_id}</StatusPill> : null}
              {actionPreflight?.refresh_receipt_id ? <StatusPill tone="info">receipt {actionPreflight.refresh_receipt_id}</StatusPill> : null}
              {actionPreflight && preflightUnresolved ? <StatusPill tone="warning">needs gate proof</StatusPill> : null}
            </div>
          </article>

          {locatorQualitySignals.length > 0 ? (
            <article
              className="min-w-0 rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3"
              role="region"
              aria-label="Locator quality repair signals"
            >
              <div className="flex min-w-0 items-center justify-between gap-2">
                <h3 className="truncate font-label text-xs font-semibold text-foreground">Locator Quality Repair</h3>
                <StatusPill tone={locatorQualitySignals.some((signal) => signal.invalidBBoxCount > 0) ? 'warning' : 'neutral'}>
                  locator risks {locatorQualitySignals.length}
                </StatusPill>
              </div>
              <p className="mt-2 break-words text-xs leading-5 text-foreground/60">
                Invalid locator geometry is surfaced as bounded repair metadata before layout-specific evidence claims are trusted.
              </p>
              <div className="mt-2 grid gap-2">
                {locatorQualitySignals.map((signal) => (
                  <div
                    key={signal.signalId}
                    className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-lowest px-2.5 py-2"
                  >
                    <div className="flex min-w-0 items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="break-words font-label text-[11px] font-medium text-foreground">
                          signal {signal.signalId}
                        </p>
                        <p className="mt-1 break-words text-[11px] leading-4 text-foreground/55">
                          {signal.message}
                        </p>
                      </div>
                      <StatusPill tone={gateTone(signal.status, signal.severity)}>
                        {gateStatusLabel(signal.status)}
                      </StatusPill>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <StatusPill tone={signal.invalidBBoxCount > 0 ? 'warning' : 'neutral'}>
                        invalid bbox {signal.invalidBBoxCount}
                      </StatusPill>
                      <StatusPill tone="neutral">bbox locators {signal.bboxLocatorCount}</StatusPill>
                      <StatusPill tone="neutral">coverage {signal.coverageState}</StatusPill>
                      <StatusPill tone={signal.riskLevel === 'block' ? 'danger' : signal.riskLevel === 'warn' ? 'warning' : 'neutral'}>
                        risk {signal.riskLevel}
                      </StatusPill>
                    </div>
                    {signal.sampleInvalidBBoxRefIds.length > 0 ? (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {signal.sampleInvalidBBoxRefIds.map((refId) => (
                          <StatusPill key={`${signal.signalId}:${refId}`} tone="info">{refId}</StatusPill>
                        ))}
                      </div>
                    ) : null}
                    <p className="mt-2 break-words text-[11px] leading-4 text-foreground/55">
                      {signal.nextAction}
                    </p>
                    <button
                      type="button"
                      aria-label={`Inspect locator signal ${signal.signalId}`}
                      onClick={() => setActiveSignalId(signal.signalId)}
                      className="mt-2 inline-flex max-w-full items-center gap-1.5 rounded-md border border-outline-variant/45 bg-surface-low px-2 py-1 font-label text-[11px] leading-4 text-foreground/70 transition-colors hover:bg-surface focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/45"
                    >
                      <Search size={13} className="shrink-0" aria-hidden="true" />
                      <span className="truncate">Inspect signal</span>
                    </button>
                  </div>
                ))}
              </div>
            </article>
          ) : null}

          <article
            className="min-w-0 rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3"
            role="region"
            aria-label="Research action lifecycle"
          >
            <div className="flex min-w-0 items-center justify-between gap-2">
              <h3 className="truncate font-label text-xs font-semibold text-foreground">Research Action Lifecycle</h3>
              <StatusPill tone={lifecycleBlockedCount > 0 ? 'danger' : lifecyclePendingCount > 0 || lifecycleUnresolvedCount > 0 ? 'warning' : actionLifecycle ? 'info' : 'neutral'}>
                {actionLifecycle ? `${actionLifecycle.actions.length} actions` : '未读取'}
              </StatusPill>
            </div>
            <p className="mt-2 break-words text-xs leading-5 text-foreground/60">
              {lifecyclePrimaryMessage(actionLifecycle)}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <StatusPill tone="neutral">{lifecycleSummary(actionLifecycle)}</StatusPill>
              <StatusPill tone={lifecyclePendingCount > 0 ? 'warning' : 'neutral'}>pending approval {lifecyclePendingCount}</StatusPill>
              <StatusPill tone={lifecycleBlockedCount > 0 ? 'danger' : 'neutral'}>blocked actions {lifecycleBlockedCount}</StatusPill>
              <StatusPill tone={lifecycleUnresolvedCount > 0 ? 'warning' : 'neutral'}>unresolved actions {lifecycleUnresolvedCount}</StatusPill>
              <StatusPill tone={lifecycleNeedsConfirmation ? 'warning' : actionLifecycle ? 'success' : 'neutral'}>
                confirmation {actionLifecycle ? String(lifecycleNeedsConfirmation) : 'unknown'}
              </StatusPill>
              <StatusPill tone={actionLifecycle?.summary.read_only === true ? 'success' : 'neutral'}>
                read-only {actionLifecycle?.summary.read_only === true ? 'true' : 'unknown'}
              </StatusPill>
            </div>

            {visibleLifecycleActions.length === 0 ? (
              <p className="mt-3 break-words rounded-md border border-outline-variant/25 bg-surface-lowest px-2.5 py-2 text-[11px] leading-4 text-foreground/50">
                {loading ? '正在读取 action lifecycle。' : '尚未发现可审计 action lifecycle。'}
              </p>
            ) : (
              <div className="mt-3 grid gap-2">
                {visibleLifecycleActions.map((action) => {
                  const recovery = isRecord(action.recovery) ? action.recovery : {};
                  const nextActions = readTextArray(recovery.next_safe_local_actions, 3);
                  const recoveryProbes = Array.isArray(recovery.resume_probes) ? recovery.resume_probes.slice(0, 4) : [];
                  const objectRefs = action.object_refs.slice(0, 4).map(lifecycleRefLabel);
                  const effectRefs = action.effect_refs.slice(0, 4).map(lifecycleRefLabel);
                  return (
                    <div
                      key={action.action_uid}
                      className="min-w-0 rounded-md border border-outline-variant/35 bg-surface-lowest px-2.5 py-2"
                    >
                      <div className="flex min-w-0 items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate font-label text-[11px] font-medium text-foreground">
                            {lifecycleActionLabel(action)}
                          </p>
                          <p className="mt-0.5 break-words font-mono text-[11px] leading-4 text-foreground/50">
                            {sanitizeInspectorText(action.action_uid)}
                          </p>
                        </div>
                        <StatusPill tone={lifecycleTone(action.status)}>
                          {action.status}
                        </StatusPill>
                      </div>

                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <StatusPill tone="neutral">{action.action_type}</StatusPill>
                        <StatusPill tone={lifecycleTone(action.status)}>{lifecycleActionApprovalLabel(action)}</StatusPill>
                        <StatusPill tone={lifecycleTone(readTextField(action.preflight, 'status'))}>
                          {lifecycleActionPreflightLabel(action)}
                        </StatusPill>
                        <StatusPill tone={lifecycleActionEffectLabel(action).includes('true') ? 'warning' : 'success'}>
                          {lifecycleActionEffectLabel(action)}
                        </StatusPill>
                        <StatusPill tone={recovery.read_only === true ? 'success' : 'neutral'}>
                          recovery read-only {recovery.read_only === true ? 'true' : 'unknown'}
                        </StatusPill>
                        <StatusPill tone={action.forbidden_actions.length > 0 ? 'warning' : 'neutral'}>
                          forbidden {action.forbidden_actions.length}
                        </StatusPill>
                      </div>

                      <div className="mt-2 grid gap-2 md:grid-cols-2">
                        <div className="min-w-0">
                          <h4 className="font-label text-[11px] font-semibold text-foreground/45">Object / Effect refs</h4>
                          <div className="mt-1 flex flex-wrap gap-1.5">
                            {objectRefs.length === 0 && effectRefs.length === 0 ? (
                              <StatusPill tone="neutral">refs pending</StatusPill>
                            ) : [...objectRefs, ...effectRefs].map((ref) => (
                              <StatusPill key={ref} tone="info">{ref}</StatusPill>
                            ))}
                          </div>
                        </div>
                        <div className="min-w-0">
                          <h4 className="font-label text-[11px] font-semibold text-foreground/45">Recovery probes</h4>
                          <div className="mt-1 flex flex-wrap gap-1.5">
                            {recoveryProbes.length === 0 ? (
                              <StatusPill tone="neutral">probe list pending</StatusPill>
                            ) : recoveryProbes.map((probe, index) => (
                              <StatusPill key={`${action.action_uid}:probe:${index}`} tone="neutral">
                                {lifecycleProbeLabel(probe, index)}
                              </StatusPill>
                            ))}
                          </div>
                        </div>
                      </div>

                      {nextActions.length > 0 ? (
                        <p className="mt-2 break-words text-[11px] leading-4 text-foreground/55">
                          {nextActions[0]}
                        </p>
                      ) : null}
                      {action.forbidden_actions.length > 0 ? (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {action.forbidden_actions.slice(0, isDesktopAcceptance ? 1 : 3).map((item) => (
                            <StatusPill key={item} tone="warning">{sanitizeInspectorText(item)}</StatusPill>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}
          </article>

          <article
            className="min-w-0 rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3"
            role="region"
            aria-label="Blocking action boundary"
          >
            <div className="flex min-w-0 items-center justify-between gap-2">
              <h3 className="truncate font-label text-xs font-semibold text-foreground">Blocking Action Boundary</h3>
              <StatusPill tone={blockingBoundary ? claimTone(blockingBoundary.status) : 'neutral'}>
                {claimStatusLabel(blockingBoundary?.status)}
              </StatusPill>
            </div>
            <p className="mt-2 break-words text-xs leading-5 text-foreground/60">
              {blockingBoundarySummary(blockingBoundary)}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <StatusPill tone={boundaryBlocked ? 'danger' : blockingBoundary ? 'success' : 'neutral'}>
                boundary can proceed {blockingBoundary ? String(blockingBoundary.can_proceed) : 'unknown'}
              </StatusPill>
              <StatusPill tone={blockingBoundary?.require_ready ? 'warning' : 'neutral'}>
                boundary require ready {blockingBoundary ? String(blockingBoundary.require_ready) : 'unknown'}
              </StatusPill>
              <StatusPill tone={blockingBoundary?.refresh_required ? 'warning' : 'neutral'}>
                boundary refresh {blockingBoundary ? String(blockingBoundary.refresh_required) : 'unknown'}
              </StatusPill>
              {blockingBoundary ? <StatusPill tone="neutral">{blockingBoundary.action_id}</StatusPill> : null}
              {blockingBoundary ? <StatusPill tone={claimTone(blockingBoundary.status)}>{blockingBoundary.required_claim_id}</StatusPill> : null}
              <StatusPill tone={visibleBlockedBoundarySignals.length > 0 ? 'danger' : 'neutral'}>
                blocked signals {visibleBlockedBoundarySignals.length}
              </StatusPill>
              <StatusPill tone={visibleUnresolvedBoundarySignals.length > 0 ? 'warning' : 'neutral'}>
                unresolved signals {visibleUnresolvedBoundarySignals.length}
              </StatusPill>
              <StatusPill tone={visibleBoundaryRecoveryDrilldowns.length > 0 ? 'info' : 'neutral'}>
                recovery drilldowns {visibleBoundaryRecoveryDrilldowns.length}
              </StatusPill>
              {blockingBoundary && boundaryUnresolved ? <StatusPill tone="warning">boundary needs review</StatusPill> : null}
            </div>

            {blockingBoundary ? (
              <div className="mt-3 grid gap-2">
                {visibleBoundaryClaims.length > 0 ? (
                  <div className="grid gap-2 md:grid-cols-2">
                    {visibleBoundaryClaims.map((claim, index) => (
                      <div
                        key={`${claim.claim_id}:${index}`}
                        className="min-w-0 rounded-md border border-outline-variant/35 bg-surface-lowest px-2.5 py-2"
                      >
                        <div className="flex min-w-0 items-center justify-between gap-2">
                          <span className="truncate font-label text-[11px] font-medium text-foreground">
                            {sanitizeInspectorText(claim.label || claim.claim_id)}
                          </span>
                          <StatusPill tone={claimTone(claim.status)}>
                            {claimStatusLabel(claim.status)}
                          </StatusPill>
                        </div>
                        <p className="mt-1 break-words text-[11px] leading-4 text-foreground/55">
                          {sanitizeInspectorText(claim.reason || 'Boundary did not include a claim reason.')}
                        </p>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          <StatusPill tone="neutral">claim {sanitizeInspectorText(claim.claim_id)}</StatusPill>
                          <StatusPill tone={(claim.blocker_count ?? 0) > 0 ? 'danger' : 'neutral'}>block {claim.blocker_count ?? 0}</StatusPill>
                          <StatusPill tone={(claim.unresolved_count ?? 0) > 0 ? 'warning' : 'neutral'}>unresolved {claim.unresolved_count ?? 0}</StatusPill>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}

                <div className="grid gap-2 md:grid-cols-2">
                  <div className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-lowest px-2.5 py-2">
                    <h4 className="font-label text-[11px] font-semibold text-foreground/45">Blocking Signals</h4>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {visibleBlockedBoundarySignals.length === 0 ? (
                        <StatusPill tone="neutral">none</StatusPill>
                      ) : visibleBlockedBoundarySignals.map((signal) => (
                        <StatusPill key={signal.signal_id} tone="danger">
                          {blockingSignalLabel(signal)}
                        </StatusPill>
                      ))}
                    </div>
                  </div>
                  <div className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-lowest px-2.5 py-2">
                    <h4 className="font-label text-[11px] font-semibold text-foreground/45">Unresolved Signals</h4>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {visibleUnresolvedBoundarySignals.length === 0 ? (
                        <StatusPill tone="neutral">none</StatusPill>
                      ) : visibleUnresolvedBoundarySignals.map((signal) => (
                        <StatusPill key={signal.signal_id} tone="warning">
                          {blockingSignalLabel(signal)}
                        </StatusPill>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-lowest px-2.5 py-2">
                  <div className="flex min-w-0 items-center justify-between gap-2">
                    <h4 className="font-label text-[11px] font-semibold text-foreground/45">Recovery Drilldowns</h4>
                    <StatusPill tone={visibleBoundaryRecoveryDrilldowns.length > 0 ? 'info' : 'neutral'}>
                      {visibleBoundaryRecoveryDrilldowns.length}
                    </StatusPill>
                  </div>
                  <div className="mt-2 grid gap-2">
                    {visibleBoundaryRecoveryDrilldowns.length === 0 ? (
                      <p className="break-words text-[11px] leading-4 text-foreground/50">
                        recovery drilldown pending
                      </p>
                    ) : visibleBoundaryRecoveryDrilldowns.map((item) => (
                      <div
                        key={item.signalId}
                        className="min-w-0 rounded-md border border-outline-variant/20 bg-surface-low px-2 py-1.5"
                      >
                        <div className="flex min-w-0 items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate font-label text-[11px] font-medium text-foreground">
                              {item.signalId}
                            </p>
                            <p className="mt-0.5 break-words text-[11px] leading-4 text-foreground/55">
                              {item.stageLabel} · {item.source}
                            </p>
                          </div>
                          <StatusPill tone={claimTone(item.status)}>
                            {claimStatusLabel(item.status)}
                          </StatusPill>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          <StatusPill tone="neutral">facts {item.factCount}</StatusPill>
                          <StatusPill tone="neutral">evidence {item.evidenceCount}</StatusPill>
                          <StatusPill tone={item.replayCount > 0 ? 'info' : 'neutral'}>replay {item.replayCount}</StatusPill>
                          <StatusPill tone="neutral">refs {item.recoveryRefCount}</StatusPill>
                          <StatusPill tone={item.probeCount > 0 ? 'info' : 'neutral'}>safe probes {item.probeCount}</StatusPill>
                          <StatusPill tone={item.blocksClaims ? 'danger' : 'neutral'}>blocks claims {String(item.blocksClaims)}</StatusPill>
                          <StatusPill tone={item.requiresHumanReview ? 'warning' : 'neutral'}>human review {String(item.requiresHumanReview)}</StatusPill>
                          <StatusPill tone={item.readOnly ? 'success' : 'warning'}>read-only {String(item.readOnly)}</StatusPill>
                          {item.rawPathExposed ? <StatusPill tone="danger">raw path exposed</StatusPill> : null}
                        </div>
                        <p className="mt-1.5 break-words text-[11px] leading-4 text-foreground/50">
                          {item.primaryAction}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="grid gap-2 md:grid-cols-2">
                  <div className="min-w-0">
                    <h4 className="font-label text-[11px] font-semibold text-foreground/45">Local Read-only Probes</h4>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {visibleBoundaryProbes.length === 0 ? (
                        <StatusPill tone="neutral">probe list pending</StatusPill>
                      ) : visibleBoundaryProbes.map((probe, index) => (
                        <StatusPill key={`${probe.label ?? probe.url ?? 'probe'}:${index}`} tone={probe.read_only === true ? 'info' : 'warning'}>
                          {blockingProbeLabel(probe, index)}
                        </StatusPill>
                      ))}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <h4 className="font-label text-[11px] font-semibold text-foreground/45">Forbidden Actions</h4>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {visibleBoundaryForbidden.length === 0 ? (
                        <StatusPill tone="neutral">forbidden actions pending</StatusPill>
                      ) : visibleBoundaryForbidden.map((action, index) => (
                        <StatusPill key={`${action}:${index}`} tone="warning">
                          {sanitizeInspectorText(action)}
                        </StatusPill>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            ) : null}
          </article>

          <article
            className="min-w-0 rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3"
            role="region"
            aria-label="Behavior eval gate signals"
          >
            <div className="flex min-w-0 items-center justify-between gap-2">
              <h3 className="truncate font-label text-xs font-semibold text-foreground">Behavior Gate Signals</h3>
              <StatusPill tone={behaviorEvalBlockingSignals.length > 0 ? 'danger' : behaviorEvalSignals.length > 0 ? 'warning' : 'neutral'}>
                {behaviorEvalBlockingSignals.length > 0 ? 'blocking' : behaviorEvalSignals.length > 0 ? 'observed' : 'none'}
              </StatusPill>
            </div>
            <p className="mt-2 break-words text-xs leading-5 text-foreground/60">
              {behaviorEvalSignalBoundarySummary(
                behaviorEvalSignals.length,
                behaviorEvalBlockingSignals.length,
                behaviorEvalUnresolvedSignals.length,
                behaviorEvalBoundaryDrilldowns.length,
              )}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <StatusPill tone={behaviorEvalBlockingSignals.length > 0 ? 'danger' : 'neutral'}>
                behavior block {behaviorEvalBlockingSignals.length}
              </StatusPill>
              <StatusPill tone={behaviorEvalUnresolvedSignals.length > 0 ? 'warning' : 'neutral'}>
                behavior unresolved {behaviorEvalUnresolvedSignals.length}
              </StatusPill>
              <StatusPill tone={behaviorEvalBoundaryDrilldowns.length > 0 ? 'info' : 'neutral'}>
                behavior recovery {behaviorEvalBoundaryDrilldowns.length}
              </StatusPill>
              <StatusPill tone={behaviorEvalSignals.length > 0 ? 'info' : 'neutral'}>
                observation-mode gate
              </StatusPill>
              <StatusPill tone={behaviorEvalPack?.mode === 'canary' ? 'success' : behaviorEvalPack ? 'warning' : 'neutral'}>
                pack mode {behaviorEvalPack?.mode ?? 'unknown'}
              </StatusPill>
            </div>
            <div className="mt-2 grid gap-2">
              {behaviorEvalSignals.slice(0, isDesktopAcceptance ? 2 : 4).map((signal) => {
                const primaryEvidenceType = integritySignalPrimaryEvidenceType(signal);
                return (
                  <div
                    key={signal.signal_id}
                    className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-lowest px-2.5 py-2"
                  >
                    <div className="flex min-w-0 items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate font-label text-[11px] font-medium text-foreground">
                          {sanitizeInspectorText(signal.signal_id)}
                        </p>
                        <p className="mt-0.5 break-words text-[11px] leading-4 text-foreground/55">
                          {sanitizeInspectorText(signal.message)}
                        </p>
                      </div>
                      <StatusPill tone={gateTone(signal.status, signal.severity)}>
                        {gateStatusLabel(signal.status)}
                      </StatusPill>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <StatusPill tone="neutral">{sanitizeInspectorText(signal.category)}</StatusPill>
                      <StatusPill tone={signal.severity === 'block' ? 'danger' : signal.severity === 'warn' ? 'warning' : 'neutral'}>
                        severity {sanitizeInspectorText(signal.severity)}
                      </StatusPill>
                      <StatusPill tone="neutral">evidence {signal.evidence.length}</StatusPill>
                      {primaryEvidenceType ? (
                        <StatusPill tone="neutral">evidence type {primaryEvidenceType}</StatusPill>
                      ) : null}
                      <StatusPill tone={signal.next_actions.length > 0 ? 'info' : 'neutral'}>
                        next actions {signal.next_actions.length}
                      </StatusPill>
                    </div>
                    {signal.next_actions[0] ? (
                      <p className="mt-1.5 break-words text-[11px] leading-4 text-foreground/50">
                        {sanitizeInspectorText(signal.next_actions[0])}
                      </p>
                    ) : null}
                  </div>
                );
              })}
              {behaviorEvalSignals.length === 0 ? (
                <p className="break-words text-[11px] leading-4 text-foreground/50">
                  Behavior Eval Pack canary results remain evaluator-health context; project blocking appears here only after persisted observation-mode findings reach the Evidence Integrity Gate.
                </p>
              ) : null}
              {behaviorEvalBoundaryDrilldowns.length > 0 ? (
                <div className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-lowest px-2.5 py-2">
                  <h4 className="font-label text-[11px] font-semibold text-foreground/45">Behavior Recovery Drilldowns</h4>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {behaviorEvalBoundaryDrilldowns.map((item) => (
                      <StatusPill key={item.signalId} tone={item.blocksClaims ? 'danger' : 'warning'}>
                        {item.signalId} · {item.stageLabel} · safe probes {item.probeCount}
                      </StatusPill>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </article>

          <article className="min-w-0 rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3">
            <div className="flex min-w-0 items-center justify-between gap-2">
              <h3 className="truncate font-label text-xs font-semibold text-foreground">Replay Lineage</h3>
              <StatusPill tone={lineageBlocked ? 'danger' : lineageUnresolved ? 'warning' : workflowReplayLineage ? 'info' : 'neutral'}>
                {workflowReplayLineage ? `${workflowReplayLineage.receipt_count} receipts` : '未读取'}
              </StatusPill>
            </div>
            <p className="mt-2 break-words text-xs leading-5 text-foreground/60">
              {workflowReplayLineage?.blockers[0]
                || workflowReplayLineage?.unresolved[0]
                || workflowReplayLineageDelta(workflowReplayLineage)}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <StatusPill tone="neutral">{workflowReplayLineageSummary(workflowReplayLineage)}</StatusPill>
              <StatusPill tone="neutral">{workflowReplayLineage ? `returned ${workflowReplayLineage.returned_count}` : 'returned unknown'}</StatusPill>
              {workflowReplayLineage?.latest_receipt_id ? (
                <StatusPill tone="info">{workflowReplayLineage.latest_receipt_id}</StatusPill>
              ) : null}
            </div>
          </article>

          <article className="min-w-0 rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3">
            <div className="flex min-w-0 items-center justify-between gap-2">
              <h3 className="truncate font-label text-xs font-semibold text-foreground">Replay Index</h3>
              <StatusPill tone={replayIndexBlocked ? 'danger' : replayIndexUnresolved ? 'warning' : workflowReplayIndex ? 'info' : 'neutral'}>
                {workflowReplayIndex ? `${workflowReplayIndex.matching_job_count} jobs` : '未读取'}
              </StatusPill>
            </div>
            <p className="mt-2 break-words text-xs leading-5 text-foreground/60">
              {workflowReplayIndexRecovery(workflowReplayIndex)}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <StatusPill tone="neutral">{workflowReplayIndexSummary(workflowReplayIndex)}</StatusPill>
              <StatusPill tone="neutral">{workflowReplayIndex ? `receipts ${workflowReplayIndex.total_receipts_seen}` : 'receipts unknown'}</StatusPill>
              <StatusPill tone="neutral">{workflowReplayIndex ? `returned ${workflowReplayIndex.returned_count}` : 'returned unknown'}</StatusPill>
              {workflowReplayIndex?.items[0]?.job_id ? <StatusPill tone="info">{workflowReplayIndex.items[0].job_id}</StatusPill> : null}
            </div>
          </article>

          <article className="min-w-0 rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3">
            <div className="flex min-w-0 items-center justify-between gap-2">
              <h3 className="truncate font-label text-xs font-semibold text-foreground">Behavior Eval Pack</h3>
              <StatusPill tone={behaviorEvalTone(behaviorEvalPack)}>
                {behaviorEvalStatusLabel(behaviorEvalPack)}
              </StatusPill>
            </div>
            <p className="mt-2 break-words text-xs leading-5 text-foreground/60">
              {behaviorEvalPrimaryMessage(behaviorEvalPack)}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <StatusPill tone="neutral">{behaviorEvalSummary(behaviorEvalPack)}</StatusPill>
              <StatusPill tone={behaviorEvalPack?.summary.structural_status === 'pass' ? 'success' : behaviorEvalPack ? 'danger' : 'neutral'}>
                structural {behaviorEvalPack?.summary.structural_status ?? 'unknown'}
              </StatusPill>
              <StatusPill tone={behaviorEvalPack?.provenance.read_only === true ? 'info' : 'neutral'}>
                {behaviorEvalReadOnlyLabel(behaviorEvalPack)}
              </StatusPill>
              <StatusPill tone={behaviorEvalArtifacts.length > 0 ? 'info' : 'neutral'}>
                artifacts {behaviorEvalArtifacts.length}
              </StatusPill>
              {behaviorEvalArtifacts[0]?.name ? <StatusPill tone="info">{behaviorEvalArtifacts[0].name}</StatusPill> : null}
            </div>
          </article>

          <article className="min-w-0 rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3">
            <div className="flex min-w-0 items-center justify-between gap-2">
              <h3 className="truncate font-label text-xs font-semibold text-foreground">Agent Handoff</h3>
              <StatusPill tone={handoffBlocked ? 'danger' : handoffUnresolved ? 'warning' : handoffCard ? 'success' : 'neutral'}>
                {handoffCard ? handoffCard.status : '未读取'}
              </StatusPill>
            </div>
            <p className="mt-2 break-words text-xs leading-5 text-foreground/60">
              {handoffCard?.blockers[0]
                || handoffCard?.unresolved[0]
                || (handoffCard?.replay_recovery ? handoffReplayRecoverySummary(handoffCard) : '')
                || (handoffCard ? 'Handoff card 已生成，当前状态与完整性门禁待复核。' : '')
                || 'Handoff card 暂无可显示记录。'}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <StatusPill tone="neutral">{handoffSummary(handoffCard)}</StatusPill>
              <StatusPill tone={handoffCard?.replay_recovery?.recovery_required ? 'warning' : handoffCard?.replay_recovery ? 'info' : 'neutral'}>
                {handoffReplayRecoverySummary(handoffCard)}
              </StatusPill>
              <StatusPill tone={actionPreflight?.refresh_receipt ? 'info' : 'neutral'}>
                {preflightReceiptSummary(actionPreflight)}
              </StatusPill>
            </div>
            {handoffRecoveryBundle ? (
              <div
                className="mt-3 rounded-md border border-outline-variant/35 bg-surface-lowest px-2.5 py-2"
                role="region"
                aria-label="Agent handoff recovery bundle"
              >
                <div className="flex min-w-0 flex-col gap-2 md:flex-row md:items-start md:justify-between">
                  <div className="min-w-0">
                    <h4 className="font-label text-[11px] font-semibold text-foreground">
                      Agent Handoff Recovery Bundle
                    </h4>
                    <p className="mt-1 break-words text-[11px] leading-4 text-foreground/60">
                      {handoffRecoveryBundle.primaryIssue}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-1.5">
                    <StatusPill tone={handoffRecoveryBundle.recoveryRequired ? 'warning' : 'info'}>
                      recovery {handoffRecoveryBundle.recoveryRequired ? 'required' : 'optional'}
                    </StatusPill>
                    <StatusPill tone={handoffRecoveryBundle.readOnly ? 'success' : 'warning'}>
                      read-only {handoffRecoveryBundle.readOnly ? 'true' : 'unknown'}
                    </StatusPill>
                  </div>
                </div>

                <div className="mt-2 grid gap-2 md:grid-cols-3">
                  <div className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-low px-2 py-2">
                    <h5 className="font-label text-[11px] font-semibold text-foreground/45">Current Stage</h5>
                    <p className="mt-1 break-words font-label text-[11px] leading-4 text-foreground">
                      {handoffRecoveryBundle.stageLabel}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <StatusPill tone="neutral">{handoffRecoveryBundle.receiptLabel}</StatusPill>
                      {handoffRecoveryBundle.attemptMetrics.map((metric) => (
                        <StatusPill key={metric} tone="neutral">{metric}</StatusPill>
                      ))}
                    </div>
                  </div>

                  <div className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-low px-2 py-2">
                    <h5 className="font-label text-[11px] font-semibold text-foreground/45">Highest Priority Attempt</h5>
                    <p className="mt-1 break-words font-mono text-[11px] leading-4 text-foreground/65">
                      {handoffRecoveryBundle.attemptLabel}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {handoffRecoveryBundle.resourceRefs.length === 0 ? (
                        <StatusPill tone="neutral">resource refs none</StatusPill>
                      ) : handoffRecoveryBundle.resourceRefs.map((ref) => (
                        <StatusPill key={ref} tone="info">{ref}</StatusPill>
                      ))}
                    </div>
                  </div>

                  <div className="min-w-0 rounded-md border border-outline-variant/25 bg-surface-low px-2 py-2">
                    <h5 className="font-label text-[11px] font-semibold text-foreground/45">Recovery Boundary</h5>
                    <p className="mt-1 break-words font-mono text-[11px] leading-4 text-foreground/65">
                      {handoffRecoveryBundle.mutationBoundary}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <StatusPill tone="neutral">safe probes {handoffRecoveryBundle.safeProbeLabels.length}</StatusPill>
                      <StatusPill tone="neutral">replay probes {handoffRecoveryBundle.replayProbeLabels.length}</StatusPill>
                    </div>
                  </div>
                </div>

                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  <div className="min-w-0">
                    <h5 className="font-label text-[11px] font-semibold text-foreground/45">Next Safe Local Probes</h5>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {[...handoffRecoveryBundle.safeProbeLabels, ...handoffRecoveryBundle.replayProbeLabels].length === 0 ? (
                        <StatusPill tone="neutral">probe list pending</StatusPill>
                      ) : [...handoffRecoveryBundle.safeProbeLabels, ...handoffRecoveryBundle.replayProbeLabels]
                        .slice(0, 6)
                        .map((probe) => (
                          <StatusPill key={probe} tone="neutral">{probe}</StatusPill>
                        ))}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <h5 className="font-label text-[11px] font-semibold text-foreground/45">Do Not Do</h5>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {handoffRecoveryBundle.forbiddenActions.length === 0 ? (
                        <StatusPill tone="neutral">forbidden actions pending</StatusPill>
                      ) : handoffRecoveryBundle.forbiddenActions.map((action) => (
                        <StatusPill key={action} tone="warning">{action}</StatusPill>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            ) : null}
          </article>
        </div>
      </div>
    </section>
  );
}

export function ReadinessPanel({
  loading,
  error,
  workspaceStatus,
  bridgeStatus,
  runtimeJobsStatus,
  healthCheck,
  zoteroHealth,
  wikiReview,
  agentJobs,
  auditRecords,
  density = 'default',
}: {
  loading: boolean;
  error: string | null;
  workspaceStatus: AgentWorkspaceStatus | null;
  bridgeStatus: AgentBridgeStatus | null;
  runtimeJobsStatus: RuntimeJobsStatus | null;
  healthCheck: AgentWorkflowHealthCheck | null;
  zoteroHealth: ZoteroAttachmentHealth | null;
  wikiReview: WikiReviewListModel | null;
  agentJobs: WritingJob[];
  auditRecords: AgentWorkspaceAuditRecord[];
  density?: ReadinessPanelDensity;
}) {
  const cards = buildReadinessCards({
    workspaceStatus,
    bridgeStatus,
    runtimeJobsStatus,
    healthCheck,
    zoteroHealth,
    wikiReview,
    agentJobs,
    auditRecords,
  });
  const isDesktopAcceptance = density === 'desktop-acceptance';

  return (
    <section
      aria-label="本地就绪面板"
      className={cn(
        'min-w-0 max-w-full overflow-hidden rounded-md border border-outline-variant/60 bg-surface-lowest',
        isDesktopAcceptance ? 'mb-0 px-3 py-2' : 'mb-4 px-4 py-3',
      )}
      data-density={density}
    >
      <div className={cn(
        'flex flex-col sm:flex-row sm:items-start sm:justify-between',
        isDesktopAcceptance ? 'mb-2 gap-1.5' : 'mb-3 gap-2',
      )}>
        <div className="min-w-0">
          <h2 className="font-display text-sm font-semibold text-foreground">本地就绪</h2>
          <p className={cn(
            'mt-0.5 text-foreground/50',
            isDesktopAcceptance ? 'text-[11px] leading-4' : 'text-xs leading-5',
          )}>
            {error ? '主状态加载失败，保留最近一次可读诊断。' : '把任务、健康检查、Zotero、ReviewQueue、导出和审计汇成下一步。'}
          </p>
        </div>
        <div role="status" className="flex shrink-0 items-center gap-1.5 text-xs text-foreground/45">
          {loading ? (
            <>
              <Loader2 size={13} className="animate-spin" />
              正在刷新本地诊断
            </>
          ) : error ? (
            <>
              <XCircle size={13} />
              诊断需重试
            </>
          ) : (
            <>
              <CheckCircle2 size={13} />
              已读取
            </>
          )}
        </div>
      </div>
      <div className={cn(
        'grid w-full max-w-full gap-2',
        isDesktopAcceptance ? 'grid-cols-2' : 'md:grid-cols-2 xl:grid-cols-3',
      )}>
        {cards.map((card) => (
          <article
            key={card.id}
            className={cn(
              'min-w-0 overflow-hidden rounded-md border border-outline-variant/45 bg-surface-low',
              isDesktopAcceptance ? 'px-2.5 py-2' : 'px-3 py-3',
            )}
          >
            <div className={cn(
              'flex min-w-0 items-center justify-between gap-2',
              isDesktopAcceptance ? 'mb-1.5' : 'mb-2',
            )}>
              <div className="flex min-w-0 items-center gap-2">
                <span className={cn(
                  'flex shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary',
                  isDesktopAcceptance ? 'h-6 w-6' : 'h-7 w-7',
                )}>
                  {card.icon}
                </span>
                <h3 className="truncate font-label text-xs font-semibold text-foreground">{card.label}</h3>
              </div>
              <StatusPill tone={card.tone}>{card.statusLabel}</StatusPill>
            </div>
            <p className={cn(
              'break-words text-foreground/65',
              isDesktopAcceptance ? 'min-h-[30px] text-[11px] leading-4' : 'min-h-[40px] text-xs leading-5',
            )}>{card.summary}</p>
            <p className={cn(
              'break-words rounded-md border border-outline-variant/35 bg-surface-lowest px-2 text-foreground/55',
              isDesktopAcceptance ? 'mt-1.5 py-1 text-[10px] leading-3' : 'mt-2 py-1.5 text-[11px] leading-4',
            )}>
              {card.nextAction}
            </p>
            <div className={cn('flex flex-wrap gap-1.5', isDesktopAcceptance ? 'mt-1.5' : 'mt-2')}>
              {card.metrics.map((metric) => (
                <StatusPill key={metric} tone="neutral">{metric}</StatusPill>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export function WikiImportRecoveryPanel({
  wikiReview,
}: {
  wikiReview: WikiReviewListModel | null;
}) {
  const importItems = buildWikiImportRecoveryItems(wikiReview);
  if (importItems.length === 0) {
    return null;
  }

  const pendingItems = importItems.filter((item) => item.status === 'pending');
  const runtimeRefCount = importItems.filter((item) => item.hasRuntimeRefs).length;
  const blockedGateCount = importItems.filter((item) => item.gateStatus === 'block').length;

  return (
    <section
      aria-label="Wiki import recovery"
      className="mb-4 min-w-0 max-w-full overflow-hidden rounded-md border border-outline-variant/60 bg-surface-lowest px-4 py-3"
    >
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="font-display text-sm font-semibold text-foreground">Wiki Import Recovery</h2>
          <p className="mt-0.5 text-xs leading-5 text-foreground/50">
            Local Markdown imports stay in the private review queue until runtime recovery and approval gates are inspected.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <StatusPill tone={pendingItems.length > 0 ? 'warning' : 'success'}>pending {pendingItems.length}</StatusPill>
          <StatusPill tone="info">runtime refs {runtimeRefCount}</StatusPill>
          <StatusPill tone={blockedGateCount > 0 ? 'danger' : 'neutral'}>gate block {blockedGateCount}</StatusPill>
          <StatusPill tone="neutral">read-only true</StatusPill>
        </div>
      </div>

      <div className="grid gap-2 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
        <article className="min-w-0 overflow-hidden rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3">
          <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
            <h3 className="truncate font-label text-xs font-semibold text-foreground">Review Queue Imports</h3>
            <StatusPill tone="neutral">items {importItems.length}</StatusPill>
          </div>
          <div className="flex flex-col gap-2">
            {importItems.slice(0, 4).map((item) => (
              <div
                key={item.itemId}
                className="min-w-0 rounded-md border border-outline-variant/35 bg-surface-lowest px-2.5 py-2"
              >
                <div className="mb-1.5 flex min-w-0 items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h4 className="truncate font-label text-xs font-semibold text-foreground">{item.title}</h4>
                    <p className="mt-0.5 break-words text-[11px] leading-4 text-foreground/55">
                      {item.itemId}
                    </p>
                  </div>
                  <StatusPill tone={item.status === 'pending' ? 'warning' : 'neutral'}>{item.status}</StatusPill>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <StatusPill tone="neutral">{item.pagePath}</StatusPill>
                  <StatusPill tone="neutral">requested {item.requestedStatus}</StatusPill>
                  <StatusPill tone={item.gateStatus === 'block' ? 'danger' : 'neutral'}>gate {item.gateStatus}</StatusPill>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="min-w-0 overflow-hidden rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3">
          <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
            <h3 className="truncate font-label text-xs font-semibold text-foreground">Runtime Recovery</h3>
            <StatusPill tone="neutral">review queue only</StatusPill>
          </div>
          <div className="flex flex-col gap-2">
            {importItems.slice(0, 4).map((item) => (
              <div
                key={`${item.itemId}:runtime`}
                className="min-w-0 rounded-md border border-outline-variant/35 bg-surface-lowest px-2.5 py-2"
              >
                <div className="flex flex-wrap gap-1.5">
                  {item.runtimeJobId ? <StatusPill tone="info">{item.runtimeJobId}</StatusPill> : <StatusPill tone="warning">job pending</StatusPill>}
                  {item.runtimeSessionId ? <StatusPill tone="neutral">{item.runtimeSessionId}</StatusPill> : null}
                  {item.runtimeApprovalId ? <StatusPill tone="warning">{item.runtimeApprovalId}</StatusPill> : <StatusPill tone="warning">approval pending</StatusPill>}
                  <StatusPill tone={item.hasHandoffCard ? 'success' : 'neutral'}>
                    handoff card {item.hasHandoffCard ? 'available' : 'pending'}
                  </StatusPill>
                  <StatusPill tone={item.hasReviewQueueProbe ? 'success' : 'neutral'}>
                    review probe {item.hasReviewQueueProbe ? 'available' : 'pending'}
                  </StatusPill>
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {item.forbiddenActions.length > 0
                    ? item.forbiddenActions.map((action) => (
                      <StatusPill key={`${item.itemId}:${action}`} tone="warning">{action}</StatusPill>
                    ))
                    : <StatusPill tone="warning">no auto approval</StatusPill>}
                </div>
              </div>
            ))}
          </div>
          <p className="mt-2 break-words rounded-md border border-outline-variant/35 bg-surface-lowest px-2 py-1.5 text-[11px] leading-4 text-foreground/60">
            No auto approval, external upload, Zotero DB mutation, or published knowledge write is exposed from Agent Workspace.
          </p>
        </article>
      </div>
    </section>
  );
}

export function WorkspaceStatePanel({
  workspaceStatus,
  knowledgeRuntime,
  requirementDrilldown,
  selectedRequirementId,
  requirementQuery,
  onRequirementQueryChange,
  onSelectRequirement,
}: {
  workspaceStatus: AgentWorkspaceStatus | null;
  knowledgeRuntime: KnowledgeRuntimeConformanceResponse | null;
  requirementDrilldown: AgentWorkspaceGoalRequirementDrilldown | null;
  selectedRequirementId: string | null;
  requirementQuery: string;
  onRequirementQueryChange: (query: string) => void;
  onSelectRequirement: (requirementId: string) => void;
}) {
  const state = workspaceStatus?.workspace_state ?? null;
  if (state === null) {
    return null;
  }
  const git = state.git;
  const dirtyPaths = git.dirty_paths.slice(0, 6);
  const probes = state.recovery_probes.slice(0, 8);
  const boundaries = state.boundaries.slice(0, 3).map(sanitizeInspectorText);
  const nextActions = state.next_safe_local_actions.slice(0, 3).map(sanitizeInspectorText);
  const goalCompletionClaim = workspaceGoalCompletionClaimSummary(state.goal_state);
  const goalLifecycle = state.goal_state.lifecycle_rollup ?? null;
  const desktopSmoke = state.desktop_smoke;
  const ocrRuntime = state.ocr_runtime;
  const visibleOcrEngines = ocrRuntime.engines.slice(0, 4);
  const ocrConfigEntries = Object.entries(ocrRuntime.engine_config).slice(0, 4);
  const allOpenRequirements = state.goal_state.open_requirements ?? [];
  const matchingOpenRequirements = allOpenRequirements.filter((item) => matchesOpenRequirementQuery(requirementQuery, item));
  const openRequirements = matchingOpenRequirements.slice(0, 5);
  const openRequirementResultLabel = requirementQuery.trim()
    ? `requirement matches ${matchingOpenRequirements.length} / total ${allOpenRequirements.length}`
    : `requirements shown ${openRequirements.length} / total ${allOpenRequirements.length}`;
  const knowledgePackages = knowledgeRuntime?.packages.slice(0, 4) ?? [];
  const knowledgeSummary = knowledgeRuntime?.summary ?? { proved: 0, pending: 0, blocked: 0, not_applicable: 0 };
  const actualLoadingGate = knowledgeRuntime?.actual_loading_gate ?? null;
  return (
    <section
      aria-label="Workspace state visibility"
      className="mb-4 min-w-0 max-w-full overflow-hidden rounded-md border border-outline-variant/60 bg-surface-lowest px-4 py-3"
    >
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="font-display text-sm font-semibold text-foreground">Workspace State</h2>
          <p className="mt-0.5 text-xs leading-5 text-foreground/50">
            Local artifacts, runtime roots, git state, recovery probes, and mutation boundaries are summarized read-only.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <StatusPill tone={workspaceStateTone(workspaceStatus)}>
            {state.workspace_ready ? 'workspace ready' : 'workspace needs check'}
          </StatusPill>
          <StatusPill tone="neutral">read-only {String(state.read_only)}</StatusPill>
          <StatusPill tone={git.available ? 'info' : 'warning'}>{git.available ? 'git visible' : 'git unavailable'}</StatusPill>
        </div>
      </div>
      <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <article className="min-w-0 overflow-hidden rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3">
          <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
            <h3 className="truncate font-label text-xs font-semibold text-foreground">Local Recovery State</h3>
            <StatusPill tone={git.conflicted_count > 0 ? 'danger' : git.changed_count > 0 ? 'warning' : 'success'}>
              changed {git.changed_count}
            </StatusPill>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <StatusPill tone="neutral">{workspaceGitSummary(workspaceStatus)}</StatusPill>
            <StatusPill tone="neutral">ahead {git.ahead}</StatusPill>
            <StatusPill tone={git.behind > 0 ? 'warning' : 'neutral'}>behind {git.behind}</StatusPill>
            <StatusPill tone={git.conflicted_count > 0 ? 'danger' : 'neutral'}>conflicts {git.conflicted_count}</StatusPill>
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-3">
            {[
              workspaceDirectorySummary(
                'artifacts',
                state.artifact_root.exists,
                state.artifact_root.file_count,
                state.artifact_root.total_bytes,
                state.artifact_root.truncated,
              ),
              workspaceDirectorySummary(
                'runtime',
                state.runtime_state_root.exists,
                state.runtime_state_root.file_count,
                state.runtime_state_root.total_bytes,
                state.runtime_state_root.truncated,
              ),
              workspaceDirectorySummary(
                'output',
                state.output_root.exists,
                state.output_root.file_count,
                state.output_root.total_bytes,
                state.output_root.truncated,
              ),
            ].map((item) => (
              <p key={item} className="min-w-0 break-words rounded-md border border-outline-variant/35 bg-surface-lowest px-2 py-1.5 text-[11px] leading-4 text-foreground/60">
                {item}
              </p>
            ))}
          </div>
          <div className="mt-3 min-w-0 rounded-md border border-outline-variant/35 bg-surface-lowest px-2 py-1.5">
            <p className="break-words text-[11px] leading-4 text-foreground/60">
              {workspaceGoalStateSummary(state)}
            </p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              <StatusPill tone={state.goal_state.available ? 'success' : 'warning'}>
                goal-state {state.goal_state.available ? 'visible' : 'missing'}
              </StatusPill>
              {state.goal_state.requirement_status ? (
                <StatusPill tone={state.goal_state.requirement_status.incomplete > 0 ? 'warning' : 'success'}>
                  requirement status visible
                </StatusPill>
              ) : null}
              {allOpenRequirements.length > 0 ? (
                <StatusPill tone="warning">open requirements {allOpenRequirements.length}</StatusPill>
              ) : null}
              {goalCompletionClaim.fullGoal ? (
                <StatusPill tone={goalCompletionClaim.fullGoal.toLowerCase().includes('not complete') ? 'warning' : 'info'}>
                  full goal status visible
                </StatusPill>
              ) : null}
              {goalLifecycle?.status ? (
                <StatusPill tone={goalLifecycle.is_goal_complete ? 'success' : 'warning'}>
                  lifecycle {sanitizeInspectorText(goalLifecycle.status)}
                </StatusPill>
              ) : null}
              {state.goal_state.checkpoint_id ? (
                <StatusPill tone="neutral">checkpoint {sanitizeInspectorText(state.goal_state.checkpoint_id)}</StatusPill>
              ) : null}
              {state.goal_state.path ? (
                <StatusPill tone="neutral">{sanitizeInspectorText(state.goal_state.path)}</StatusPill>
              ) : null}
            </div>
            {goalCompletionClaim.thisSlice || goalCompletionClaim.fullGoal || goalLifecycle?.completion_blockers?.length ? (
              <div className="mt-2 grid gap-1.5">
                {goalCompletionClaim.thisSlice ? (
                  <p className="break-words rounded-md border border-outline-variant/35 bg-surface px-2 py-1.5 text-[11px] leading-4 text-foreground/60">
                    slice completion {goalCompletionClaim.thisSlice}
                  </p>
                ) : null}
                {goalCompletionClaim.fullGoal ? (
                  <p className="break-words rounded-md border border-outline-variant/35 bg-surface px-2 py-1.5 text-[11px] leading-4 text-foreground/60">
                    full goal {goalCompletionClaim.fullGoal}
                  </p>
                ) : null}
                {goalLifecycle?.completion_blockers?.length ? (
                  <p className="break-words rounded-md border border-outline-variant/35 bg-surface px-2 py-1.5 text-[11px] leading-4 text-foreground/60">
                    lifecycle blockers {goalLifecycle.completion_blockers.length} · can complete {String(goalLifecycle.can_mark_goal_complete)}
                  </p>
                ) : null}
              </div>
            ) : null}
            {allOpenRequirements.length > 0 ? (
              <div className="mt-2 grid gap-1.5">
                <div className="flex min-w-0 flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between">
                  <h4 id="agent-workspace-open-requirements-heading" className="font-label text-[11px] font-semibold text-foreground/45">
                    Open Requirements
                  </h4>
                  <StatusPill tone={openRequirements.length > 0 ? 'info' : 'warning'}>{openRequirementResultLabel}</StatusPill>
                </div>
                <label className="relative block">
                  <Search size={12} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-foreground/35" />
                  <input
                    type="search"
                    value={requirementQuery}
                    onChange={(event) => onRequirementQueryChange(event.target.value)}
                    aria-label="Filter open requirements"
                    aria-controls="agent-workspace-open-requirements-list"
                    className="h-8 w-full rounded-md border border-outline-variant/45 bg-surface-lowest pl-8 pr-2 text-[11px] text-foreground outline-none transition-colors placeholder:text-foreground/35 focus:border-primary/45"
                    placeholder="Filter by requirement id, status, evidence risk"
                  />
                </label>
                {openRequirements.length > 0 ? (
                  <div
                    id="agent-workspace-open-requirements-list"
                    role="list"
                    aria-labelledby="agent-workspace-open-requirements-heading"
                    className="grid gap-1"
                  >
                    {openRequirements.map((item) => {
                      const label = workspaceGoalOpenRequirementLabel(item);
                      const selected = selectedRequirementId === item.id;
                      return (
                        <div
                          key={`${item.id}-${item.status}`}
                          role="listitem"
                        >
                          <button
                            type="button"
                            aria-current={selected ? 'true' : undefined}
                            onClick={() => onSelectRequirement(item.id)}
                            className={cn(
                              'w-full break-words rounded-md border px-2 py-1.5 text-left text-[11px] leading-4 transition-colors',
                              selected
                                ? 'border-primary/35 bg-primary/10 text-foreground'
                                : 'border-outline-variant/35 bg-surface text-foreground/60 hover:border-primary/25 hover:text-foreground/75',
                            )}
                          >
                            {label}
                          </button>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="break-words rounded-md border border-outline-variant/35 bg-surface px-2 py-1.5 text-[11px] leading-4 text-foreground/55">
                    No open requirements match the current filter.
                  </p>
                )}
              </div>
            ) : null}
            {requirementDrilldown ? (
              <div
                role="region"
                aria-label="Requirement evidence drilldown"
                className="mt-2 grid gap-1.5 rounded-md border border-outline-variant/35 bg-surface px-2 py-1.5"
              >
                <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                  <h4 className="mr-auto font-label text-[11px] font-semibold text-foreground/45">
                    Requirement Evidence
                  </h4>
                  <StatusPill tone={requirementDrilldown.available ? 'info' : 'warning'}>
                    drilldown {requirementDrilldown.available ? 'visible' : 'missing'}
                  </StatusPill>
                  <StatusPill tone="neutral">read-only {String(requirementDrilldown.read_only)}</StatusPill>
                  <StatusPill tone={requirementDrilldown.truncated ? 'warning' : 'neutral'}>
                    evidence {requirementDrilldown.evidence_count}
                  </StatusPill>
                </div>
                <p className="break-words text-[11px] leading-4 text-foreground/60">
                  {requirementDrilldown.id ? sanitizeInspectorText(requirementDrilldown.id) : 'requirement id pending'}
                  {requirementDrilldown.status ? ` · ${sanitizeInspectorText(requirementDrilldown.status)}` : ''}
                  {requirementDrilldown.error ? ` · ${sanitizeInspectorText(requirementDrilldown.error)}` : ''}
                </p>
                {requirementDrilldown.requirement ? (
                  <p className="break-words rounded-md border border-outline-variant/25 bg-surface-lowest px-2 py-1 text-[11px] leading-4 text-foreground/60">
                    requirement {sanitizeInspectorText(requirementDrilldown.requirement)}
                  </p>
                ) : null}
                {requirementDrilldown.residual_risk ? (
                  <p className="break-words rounded-md border border-outline-variant/25 bg-surface-lowest px-2 py-1 text-[11px] leading-4 text-foreground/60">
                    risk {sanitizeInspectorText(requirementDrilldown.residual_risk)}
                  </p>
                ) : null}
                {requirementDrilldown.evidence.length > 0 ? (
                  <div className="grid gap-1">
                    {requirementDrilldown.evidence.slice(0, 4).map((item) => (
                      <p key={`${item.label}-${item.text}`} className="break-words rounded-md border border-outline-variant/25 bg-surface-lowest px-2 py-1 text-[11px] leading-4 text-foreground/60">
                        {sanitizeInspectorText(item.label)} · {sanitizeInspectorText(item.text)}
                      </p>
                    ))}
                  </div>
                ) : null}
                {requirementDrilldown.next_safe_local_actions.length > 0 ? (
                  <p className="break-words text-[11px] leading-4 text-foreground/55">
                    next {sanitizeInspectorText(requirementDrilldown.next_safe_local_actions[0])}
                  </p>
                ) : null}
                {requirementDrilldown.stop_boundaries.length > 0 ? (
                  <p className="break-words text-[11px] leading-4 text-foreground/55">
                    boundary {sanitizeInspectorText(requirementDrilldown.stop_boundaries[0])}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {dirtyPaths.length === 0 ? (
              <StatusPill tone="success">no dirty paths reported</StatusPill>
            ) : dirtyPaths.map((path) => (
              <StatusPill key={path} tone="warning">{sanitizeInspectorText(path)}</StatusPill>
            ))}
          </div>
        </article>
        <article className="min-w-0 overflow-hidden rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3">
          <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
            <h3 className="truncate font-label text-xs font-semibold text-foreground">Recovery Guardrails</h3>
            <StatusPill tone="info">probes {probes.length}</StatusPill>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {probes.map((probe, index) => (
              <StatusPill key={workspaceProbeLabel(probe, index)} tone="info">{workspaceProbeLabel(probe, index)}</StatusPill>
            ))}
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            <div
              role="region"
              aria-label="Desktop smoke evidence"
              className="min-w-0 rounded-md border border-outline-variant/35 bg-surface-lowest px-2 py-2 md:col-span-2"
            >
              <div className="mb-1.5 flex min-w-0 flex-wrap items-center gap-1.5">
                <h4 className="mr-auto font-label text-[11px] font-semibold text-foreground/45">Desktop Smoke Evidence</h4>
                <StatusPill tone={desktopSmoke.available ? 'success' : 'warning'}>
                  desktop smoke {desktopSmoke.available ? 'visible' : 'missing'}
                </StatusPill>
                <StatusPill tone="neutral">read-only {String(desktopSmoke.read_only)}</StatusPill>
                {desktopSmoke.status ? (
                  <StatusPill tone={desktopSmoke.status === 'passed' ? 'success' : 'warning'}>
                    status {sanitizeInspectorText(desktopSmoke.status)}
                  </StatusPill>
                ) : null}
              </div>
              <p className="break-words text-[11px] leading-4 text-foreground/60">
                {workspaceDesktopSmokeSummary(state)}
              </p>
              {desktopSmoke.available ? (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {desktopSmoke.initial_path ? <StatusPill tone="neutral">{sanitizeInspectorText(desktopSmoke.initial_path)}</StatusPill> : null}
                  <StatusPill tone="neutral">expected {sanitizeInspectorText(desktopSmoke.expected_initial_path)}</StatusPill>
                  <StatusPill tone={desktopSmoke.ignored_count > 0 ? 'warning' : 'neutral'}>ignored {desktopSmoke.ignored_count}</StatusPill>
                  {desktopSmoke.accessibility_tree_root_name ? <StatusPill tone="info">root {sanitizeInspectorText(desktopSmoke.accessibility_tree_root_name)}</StatusPill> : null}
                  {desktopSmoke.accessibility_tree_root_control_type ? <StatusPill tone="info">control {sanitizeInspectorText(desktopSmoke.accessibility_tree_root_control_type)}</StatusPill> : null}
                  {desktopSmoke.accessibility_tree_node_count !== null ? <StatusPill tone="neutral">nodes {desktopSmoke.accessibility_tree_node_count}</StatusPill> : null}
                  {desktopSmoke.accessibility_tree_named_node_count !== null ? <StatusPill tone="neutral">named {desktopSmoke.accessibility_tree_named_node_count}</StatusPill> : null}
                  {desktopSmoke.screenshot_path ? <StatusPill tone="neutral">{sanitizeInspectorText(desktopSmoke.screenshot_path)}</StatusPill> : null}
                  {desktopSmoke.accessibility_tree_path ? <StatusPill tone="neutral">{sanitizeInspectorText(desktopSmoke.accessibility_tree_path)}</StatusPill> : null}
                </div>
              ) : null}
              {desktopSmoke.warnings.length > 0 || desktopSmoke.errors.length > 0 ? (
                <div className="mt-1.5 grid gap-1">
                  {desktopSmoke.warnings.slice(0, 2).map((warning) => (
                    <p key={`desktop-smoke-warning:${warning}`} className="break-words rounded-md border border-outline-variant/25 bg-surface px-2 py-1 text-[11px] leading-4 text-foreground/60">
                      warning {sanitizeInspectorText(warning)}
                    </p>
                  ))}
                  {desktopSmoke.errors.slice(0, 2).map((error) => (
                    <p key={`desktop-smoke-error:${error}`} className="break-words rounded-md border border-danger/20 bg-danger/5 px-2 py-1 text-[11px] leading-4 text-danger">
                      error {sanitizeInspectorText(error)}
                    </p>
                  ))}
                </div>
              ) : null}
            </div>
            <div
              role="region"
              aria-label="OCR runtime recovery"
              className="min-w-0 rounded-md border border-outline-variant/35 bg-surface-lowest px-2 py-2 md:col-span-2"
            >
              <div className="mb-1.5 flex min-w-0 flex-wrap items-center gap-1.5">
                <h4 className="mr-auto font-label text-[11px] font-semibold text-foreground/45">OCR Runtime</h4>
                <StatusPill tone={workspaceOcrRuntimeTone(state)}>
                  ocr runtime {ocrRuntime.available ? 'visible' : 'unavailable'}
                </StatusPill>
                <StatusPill tone="neutral">read-only {String(ocrRuntime.read_only)}</StatusPill>
                <StatusPill tone={ocrRuntime.selected_engine ? 'success' : 'warning'}>
                  selected {ocrRuntime.selected_engine ? sanitizeInspectorText(ocrRuntime.selected_engine) : 'none'}
                </StatusPill>
              </div>
              <p className="break-words text-[11px] leading-4 text-foreground/60">
                {workspaceOcrRuntimeSummary(state)}
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {ocrRuntime.configured_engine ? <StatusPill tone="neutral">configured {sanitizeInspectorText(ocrRuntime.configured_engine)}</StatusPill> : null}
                {ocrRuntime.language ? <StatusPill tone="neutral">lang {sanitizeInspectorText(ocrRuntime.language)}</StatusPill> : null}
                {ocrRuntime.source ? <StatusPill tone="neutral">source {sanitizeInspectorText(ocrRuntime.source)}</StatusPill> : null}
                <StatusPill tone={ocrRuntime.ready_engine_count > 0 ? 'success' : 'warning'}>ready engines {ocrRuntime.ready_engine_count}</StatusPill>
                <StatusPill tone="neutral">engine inventory {ocrRuntime.engine_count}</StatusPill>
              </div>
              {ocrConfigEntries.length > 0 ? (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {ocrConfigEntries.map(([key, value]) => (
                    <StatusPill key={key} tone="neutral">
                      {sanitizeInspectorText(key)} {displayUnknownValue(value)}
                    </StatusPill>
                  ))}
                </div>
              ) : null}
              {ocrRuntime.warning || ocrRuntime.error || ocrRuntime.readiness_blockers.length > 0 ? (
                <div className="mt-1.5 grid gap-1">
                  {ocrRuntime.warning ? (
                    <p className="break-words rounded-md border border-outline-variant/25 bg-surface px-2 py-1 text-[11px] leading-4 text-foreground/60">
                      warning {sanitizeInspectorText(ocrRuntime.warning)}
                    </p>
                  ) : null}
                  {ocrRuntime.error ? (
                    <p className="break-words rounded-md border border-danger/20 bg-danger/5 px-2 py-1 text-[11px] leading-4 text-danger">
                      error {sanitizeInspectorText(ocrRuntime.error)}
                    </p>
                  ) : null}
                  {ocrRuntime.readiness_blockers.slice(0, 3).map((blocker) => (
                    <p key={`ocr-blocker:${blocker}`} className="break-words rounded-md border border-outline-variant/25 bg-surface px-2 py-1 text-[11px] leading-4 text-foreground/60">
                      blocker {sanitizeInspectorText(blocker)}
                    </p>
                  ))}
                </div>
              ) : null}
              {visibleOcrEngines.length > 0 ? (
                <div className="mt-1.5 grid gap-1 md:grid-cols-2">
                  {visibleOcrEngines.map((engine) => (
                    <p key={engine.name} className="break-words rounded-md border border-outline-variant/25 bg-surface px-2 py-1 text-[11px] leading-4 text-foreground/60">
                      {workspaceOcrEngineLabel(engine)}
                      {engine.readiness_blockers.length > 0 ? ` · blocker ${sanitizeInspectorText(engine.readiness_blockers[0])}` : ''}
                    </p>
                  ))}
                </div>
              ) : null}
              {ocrRuntime.next_safe_local_actions.length > 0 ? (
                <p className="mt-1.5 break-words text-[11px] leading-4 text-foreground/55">
                  next {sanitizeInspectorText(ocrRuntime.next_safe_local_actions[0])}
                </p>
              ) : null}
            </div>
            <div
              role="region"
              aria-label="Knowledge runtime conformance"
              className="min-w-0 rounded-md border border-outline-variant/35 bg-surface-lowest px-2 py-2 md:col-span-2"
            >
              <div className="mb-1.5 flex min-w-0 flex-wrap items-center gap-1.5">
                <h4 className="mr-auto font-label text-[11px] font-semibold text-foreground/45">Knowledge Runtime</h4>
                <StatusPill tone={knowledgeRuntime ? 'success' : 'warning'}>
                  conformance {knowledgeRuntime ? 'visible' : 'missing'}
                </StatusPill>
                <StatusPill tone="neutral">read-only true</StatusPill>
                <StatusPill tone="info">packages {knowledgeRuntime?.packages.length ?? 0}</StatusPill>
                <StatusPill tone={knowledgeSummary.blocked > 0 ? 'danger' : 'neutral'}>blocked {knowledgeSummary.blocked}</StatusPill>
                <StatusPill tone={knowledgeSummary.pending > 0 ? 'warning' : 'neutral'}>pending {knowledgeSummary.pending}</StatusPill>
                <StatusPill tone="success">proved {knowledgeSummary.proved}</StatusPill>
                {actualLoadingGate ? (
                  <StatusPill tone={knowledgeRuntimeTone(actualLoadingGate.status)}>
                    live gate {sanitizeInspectorText(actualLoadingGate.status)}
                  </StatusPill>
                ) : null}
              </div>
              {knowledgeRuntime ? (
                <>
                  <p className="break-words text-[11px] leading-4 text-foreground/60">
                    {knowledgeRuntime.pipeline.map(sanitizeInspectorText).join(' -> ')}
                  </p>
                  {actualLoadingGate ? (
                    <div className="mt-1.5 min-w-0 rounded-md border border-outline-variant/25 bg-surface px-2 py-1.5">
                      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                        <span className="mr-auto min-w-0 truncate font-label text-[11px] font-semibold text-foreground/70">
                          Actual loading gate
                        </span>
                        <StatusPill tone={knowledgeRuntimeTone(actualLoadingGate.status)}>
                          {sanitizeInspectorText(actualLoadingGate.status)}
                        </StatusPill>
                        <StatusPill tone="neutral">{actualLoadingGateSummary(actualLoadingGate)}</StatusPill>
                        <StatusPill tone="neutral">
                          contract {sanitizeInspectorText(actualLoadingGate.artifact_contract)}
                        </StatusPill>
                        <StatusPill tone={actualLoadingGate.validation_errors.length > 0 ? 'danger' : 'success'}>
                          validation errors {actualLoadingGate.validation_errors.length}
                        </StatusPill>
                        <StatusPill tone={actualLoadingGate.required_checks.length > 0 ? 'info' : 'warning'}>
                          required checks {actualLoadingGate.required_checks.length}
                        </StatusPill>
                        <StatusPill tone={actualLoadingRecoveryTone(actualLoadingGate)}>
                          recovery {sanitizeInspectorText(actualLoadingGate.recovery.state)}
                        </StatusPill>
                        <StatusPill tone={actualLoadingGate.recovery.read_only ? 'info' : 'warning'}>
                          recovery read-only {String(actualLoadingGate.recovery.read_only)}
                        </StatusPill>
                        <StatusPill tone={actualLoadingGate.recovery.blocked_by.length > 0 ? 'danger' : 'success'}>
                          blocked by {actualLoadingGate.recovery.blocked_by.length}
                        </StatusPill>
                        <StatusPill tone={actualLoadingGate.recovery.provider_ready_for_authorized_live_smoke ? 'success' : 'warning'}>
                          provider ready {String(actualLoadingGate.recovery.provider_ready_for_authorized_live_smoke)}
                        </StatusPill>
                        <StatusPill tone={actualLoadingGate.provider_preflight.auth_required_count > 0 ? 'danger' : 'neutral'}>
                          auth required {actualLoadingGate.provider_preflight.auth_required_count}
                        </StatusPill>
                        <StatusPill tone={actualLoadingGate.provider_preflight.tool_call_ok_count > 0 ? 'success' : 'warning'}>
                          tool-call ok {actualLoadingGate.provider_preflight.tool_call_ok_count}
                        </StatusPill>
                        <StatusPill tone={actualLoadingGate.provider_preflight.provider_ready_for_authorized_live_smoke ? 'success' : 'warning'}>
                          preflight ready {String(actualLoadingGate.provider_preflight.provider_ready_for_authorized_live_smoke)}
                        </StatusPill>
                        <StatusPill tone="neutral">
                          preflight records {actualLoadingGate.provider_preflight.record_count}
                        </StatusPill>
                        <StatusPill tone={actualLoadingGate.recovery.completion_requires_authorized_live_smoke ? 'warning' : 'success'}>
                          live smoke {actualLoadingGate.recovery.completion_requires_authorized_live_smoke ? 'required' : 'proved'}
                        </StatusPill>
                      </div>
                      <p className="mt-1 break-words text-[11px] leading-4 text-foreground/55">
                        {sanitizeInspectorText(actualLoadingGate.claim_boundary || 'Live QA/model loading requires an authorized smoke artifact.')}
                      </p>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        <StatusPill tone="neutral">{sanitizeInspectorText(actualLoadingGate.artifact_path)}</StatusPill>
                        {actualLoadingGate.missing.slice(0, 2).map((item) => (
                          <StatusPill key={`actual-loading-missing:${item}`} tone="warning">
                            missing {sanitizeInspectorText(item)}
                          </StatusPill>
                        ))}
                        {actualLoadingGate.evidence.slice(0, 2).map((item) => (
                          <StatusPill key={`actual-loading-evidence:${item}`} tone="info">
                            proof {sanitizeInspectorText(item)}
                          </StatusPill>
                        ))}
                        {actualLoadingGate.validation_errors.slice(0, 2).map((item) => (
                          <StatusPill key={`actual-loading-validation:${item}`} tone="danger">
                            validation {sanitizeInspectorText(item)}
                          </StatusPill>
                        ))}
                        {actualLoadingGate.required_checks.slice(0, 3).map((item) => (
                          <StatusPill key={`actual-loading-required:${item}`} tone="neutral">
                            check {sanitizeInspectorText(item)}
                          </StatusPill>
                        ))}
                        {actualLoadingGate.recovery.blocked_by.slice(0, 3).map((item) => (
                          <StatusPill key={`actual-loading-recovery-blocker:${item}`} tone="danger">
                            recovery blocker {sanitizeInspectorText(item)}
                          </StatusPill>
                        ))}
                        {actualLoadingGate.recovery.recovery_refs.slice(0, 3).map((item) => (
                          <StatusPill key={`actual-loading-recovery-ref:${item.ref_type}:${item.ref}`} tone={item.requires_authorization ? 'warning' : 'info'}>
                            recovery ref {actualLoadingRecoveryRefLabel(item)}
                          </StatusPill>
                        ))}
                        {Object.entries(actualLoadingGate.provider_preflight.status_counts ?? {}).slice(0, 3).map(([status, count]) => (
                          <StatusPill key={`actual-loading-provider-status:${status}`} tone="neutral">
                            provider status {sanitizeInspectorText(status)} {count}
                          </StatusPill>
                        ))}
                        {actualLoadingGate.provider_preflight.missing.slice(0, 2).map((item) => (
                          <StatusPill key={`actual-loading-provider-missing:${item}`} tone="warning">
                            provider missing {sanitizeInspectorText(item)}
                          </StatusPill>
                        ))}
                        {(actualLoadingGate.provider_preflight.next_safe_local_actions ?? []).slice(0, 2).map((item) => (
                          <StatusPill key={`actual-loading-provider-action:${item}`} tone="warning">
                            provider next {sanitizeInspectorText(item)}
                          </StatusPill>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  <div className="mt-1.5 grid gap-1.5">
                    {knowledgePackages.map((pkg) => (
                      <div
                        key={pkg.package_id}
                        className="min-w-0 rounded-md border border-outline-variant/25 bg-surface px-2 py-1.5"
                      >
                        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                          <span className="mr-auto min-w-0 truncate font-label text-[11px] font-semibold text-foreground/70">
                            {sanitizeInspectorText(pkg.title)}
                          </span>
                          <StatusPill tone={knowledgeRuntimeTone(pkg.overall_status)}>{pkg.overall_status}</StatusPill>
                          <StatusPill tone={pkg.loaded ? 'success' : 'warning'}>loaded {String(pkg.loaded)}</StatusPill>
                          <StatusPill tone="neutral">{sanitizeInspectorText(pkg.kind)}</StatusPill>
                        </div>
                        <p className="mt-1 break-words text-[11px] leading-4 text-foreground/55">
                          {sanitizeInspectorText(pkg.package_id)} · source {shortHashLabel(pkg.source_hash)} · content {shortHashLabel(pkg.content_hash)}
                        </p>
                        <div className="mt-1 flex flex-wrap gap-1.5">
                          <StatusPill tone={pkg.runtime_consumers.length > 0 ? 'info' : 'warning'}>
                            consumers {pkg.runtime_consumers.length}
                          </StatusPill>
                          <StatusPill tone={pkg.mcp_tools.length > 0 ? 'info' : 'warning'}>
                            mcp {pkg.mcp_tools.length}
                          </StatusPill>
                          <StatusPill tone={pkg.test_evidence.context_receipt_test ? 'success' : 'warning'}>
                            {packageEvidenceSummary(pkg)}
                          </StatusPill>
                          {pkg.conformance.some((item) => item.status === 'blocked') ? (
                            <StatusPill tone="danger">
                              blocked rows {pkg.conformance.filter((item) => item.status === 'blocked').length}
                            </StatusPill>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <p className="break-words text-[11px] leading-4 text-foreground/60">
                  Knowledge Runtime conformance was not loaded in this recovery pass.
                </p>
              )}
            </div>
            <div className="min-w-0">
              <h4 className="font-label text-[11px] font-semibold text-foreground/45">Next Safe Local Actions</h4>
              <div className="mt-1 flex flex-col gap-1.5">
                {nextActions.map((action) => (
                  <p key={action} className="break-words rounded-md border border-outline-variant/35 bg-surface-lowest px-2 py-1.5 text-[11px] leading-4 text-foreground/60">
                    {action}
                  </p>
                ))}
              </div>
            </div>
            <div className="min-w-0">
              <h4 className="font-label text-[11px] font-semibold text-foreground/45">Boundaries</h4>
              <div className="mt-1 flex flex-col gap-1.5">
                {boundaries.map((boundary) => (
                  <p key={boundary} className="break-words rounded-md border border-outline-variant/35 bg-surface-lowest px-2 py-1.5 text-[11px] leading-4 text-foreground/60">
                    {boundary}
                  </p>
                ))}
              </div>
            </div>
          </div>
        </article>
      </div>
    </section>
  );
}

export function AgentWorkspace() {
  const [status, setStatus] = useState<AgentWorkspaceStatus | null>(null);
  const [bridgeStatus, setBridgeStatus] = useState<AgentBridgeStatus | null>(null);
  const [runtimeJobsStatus, setRuntimeJobsStatus] = useState<RuntimeJobsStatus | null>(null);
  const [healthCheck, setHealthCheck] = useState<AgentWorkflowHealthCheck | null>(null);
  const [zoteroHealth, setZoteroHealth] = useState<ZoteroAttachmentHealth | null>(null);
  const [wikiReview, setWikiReview] = useState<WikiReviewListModel | null>(null);
  const [workflowPassport, setWorkflowPassport] = useState<WorkflowPassportProjection | null>(null);
  const [integrityGate, setIntegrityGate] = useState<EvidenceIntegrityGateProjection | null>(null);
  const [actionLifecycle, setActionLifecycle] = useState<ResearchActionLifecycleProjection | null>(null);
  const [handoffCard, setHandoffCard] = useState<AgentHandoffCardProjection | null>(null);
  const [workflowReplayIndex, setWorkflowReplayIndex] = useState<WorkflowReplayIndexProjection | null>(null);
  const [workflowReplayLineage, setWorkflowReplayLineage] = useState<WorkflowReplayLineageProjection | null>(null);
  const [behaviorEvalPack, setBehaviorEvalPack] = useState<BehaviorEvalPackProjection | null>(null);
  const [knowledgeRuntime, setKnowledgeRuntime] = useState<KnowledgeRuntimeConformanceResponse | null>(null);
  const [requirementDrilldown, setRequirementDrilldown] = useState<AgentWorkspaceGoalRequirementDrilldown | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<WorkspaceTab>('agents');
  const [query, setQuery] = useState('');
  const [requirementQuery, setRequirementQuery] = useState('');
  const [selectedArtifactPath, setSelectedArtifactPath] = useState<string | null>(null);
  const [selectedAuditIndex, setSelectedAuditIndex] = useState(0);
  const [selectedAgentJobId, setSelectedAgentJobId] = useState<string | null>(null);
  const [selectedRequirementId, setSelectedRequirementId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [next, bridge, runtimeJobs, workflowHealth, zotero, review, passport, gate, lifecycle, replayIndex, behaviorEval, knowledge] = await Promise.all([
        getAgentWorkspaceStatus(),
        getAgentBridgeStatus({ limit: 50 }).catch(() => null),
        listRuntimeJobs({ limit: 100 }).catch(() => null),
        getAgentWorkflowHealth({ includeLive: false }).catch(() => null),
        getZoteroAttachmentHealth({ maxItems: 20, writeReports: false }).catch(() => null),
        getWikiReview().catch(() => null),
        getWorkflowPassport({ limit: 500 }).catch(() => null),
        getEvidenceIntegrityGate({ limit: 500 }).catch(() => null),
        getResearchActionLifecycle({ limit: 50 }).catch(() => null),
        getWorkflowReplayIndex({ limit: 25 }).catch(() => null),
        getBehaviorEvalPack({ includeCases: true }).catch(() => null),
        getKnowledgeRuntimeConformance().catch(() => null),
      ]);
      setStatus(next);
      setBridgeStatus(bridge);
      setRuntimeJobsStatus(runtimeJobs);
      setHealthCheck(workflowHealth);
      setZoteroHealth(zotero);
      setWikiReview(review);
      setWorkflowPassport(passport);
      setIntegrityGate(gate);
      setActionLifecycle(lifecycle);
      setWorkflowReplayIndex(replayIndex);
      setBehaviorEvalPack(behaviorEval);
      setKnowledgeRuntime(knowledge);
      setSelectedArtifactPath((current) => {
        if (current && next.artifacts.some((artifact) => artifact.path === current)) {
          return current;
        }
        return next.artifacts[0]?.path ?? null;
      });
      setSelectedAgentJobId((current) => {
        const visibleJobs = [
          ...(bridge?.recent ?? []),
          ...((runtimeJobs?.recent ?? []).filter(isVisibleRuntimeJob)),
        ];
        if (current && visibleJobs.some((job) => job.job_id === current)) {
          return current;
        }
        return visibleJobs[0]?.job_id ?? null;
      });
      setSelectedAuditIndex((current) => (
        current >= 0 && current < next.audit_records.length ? current : 0
      ));
      setSelectedRequirementId((current) => {
        const openRequirements = next.workspace_state.goal_state.open_requirements ?? [];
        if (current && openRequirements.some((item) => item.id === current)) {
          return current;
        }
        return openRequirements[0]?.id ?? null;
      });
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : 'Agent Workspace 加载失败';
      setError(message);
      setStatus(null);
      setBridgeStatus(null);
      setRuntimeJobsStatus(null);
      setHealthCheck(null);
      setZoteroHealth(null);
      setWikiReview(null);
      setWorkflowPassport(null);
      setIntegrityGate(null);
      setActionLifecycle(null);
      setHandoffCard(null);
      setWorkflowReplayIndex(null);
      setWorkflowReplayLineage(null);
      setBehaviorEvalPack(null);
      setKnowledgeRuntime(null);
      setRequirementDrilldown(null);
      setSelectedRequirementId(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedRequirementId) {
      setRequirementDrilldown(null);
      return () => {
        cancelled = true;
      };
    }
    getAgentWorkspaceRequirement(selectedRequirementId)
      .then((drilldown) => {
        if (!cancelled) {
          setRequirementDrilldown(drilldown);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRequirementDrilldown(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedRequirementId]);

  const artifacts = useMemo(
    () => (status?.artifacts ?? []).filter((artifact) => matchesQuery(query, artifact, null)),
    [query, status],
  );
  const auditRecords = useMemo(
    () => (status?.audit_records ?? []).filter((record) => matchesQuery(query, null, record)),
    [query, status],
  );
  const agentJobs = useMemo(
    () => {
      const seen = new Set<string>();
      const merged = [
        ...((runtimeJobsStatus?.recent ?? []).filter(isVisibleRuntimeJob)),
        ...(bridgeStatus?.recent ?? []),
      ].filter((job) => {
        if (seen.has(job.job_id)) return false;
        seen.add(job.job_id);
        return true;
      });
      return merged.filter((job) => matchesQuery(query, null, null, job));
    },
    [bridgeStatus, query, runtimeJobsStatus],
  );
  const selectedArtifact = artifacts.find((artifact) => artifact.path === selectedArtifactPath) ?? artifacts[0] ?? null;
  const selectedRecord = auditRecords[selectedAuditIndex] ?? auditRecords[0] ?? null;
  const selectedAgentJob = agentJobs.find((job) => job.job_id === selectedAgentJobId) ?? agentJobs[0] ?? null;
  const selectedActionPreflight = workflowActionPreflight(selectedAgentJob, agentJobs, handoffCard);
  const behaviorEvalArtifacts = useMemo(
    () => (status?.artifacts ?? []).filter(isBehaviorEvalArtifact),
    [status],
  );

  useEffect(() => {
    let cancelled = false;
    if (!selectedAgentJob) {
      setWorkflowReplayLineage(null);
      return () => {
        cancelled = true;
      };
    }
    getWorkflowReplayLineage(selectedAgentJob.job_id, { limit: 12 })
      .then((lineage) => {
        if (!cancelled) {
          setWorkflowReplayLineage(lineage);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setWorkflowReplayLineage(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedAgentJob]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedAgentJob || selectedAgentJob.kind !== 'agent_request') {
      setHandoffCard(null);
      return () => {
        cancelled = true;
      };
    }
    getAgentHandoffCard(selectedAgentJob.job_id)
      .then((card) => {
        if (!cancelled) {
          setHandoffCard(card);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setHandoffCard(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedAgentJob]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-6 py-4">
        <PageHeader
          icon={<TerminalSquare size={18} />}
          title="Agent Workspace"
          subtitle={`任务 ${agentJobs.length} 个 · 产物 ${status?.artifact_count ?? 0} 个 · 审计 ${status?.audit_count ?? 0} 条`}
          className="mb-0"
          actions={
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-1.5 font-label text-xs font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:opacity-60"
            >
              {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              刷新
            </button>
          }
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-6 py-4">
        <div className="mb-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <StatTile label="Agent Running" value={String(bridgeStatus?.running_count ?? 0)} icon={<Bot size={16} />} />
          <StatTile label="Agent Pending" value={String(bridgeStatus?.pending_count ?? 0)} icon={<Clock size={16} />} />
          <StatTile label="Runtime Jobs" value={String((runtimeJobsStatus?.recent ?? []).filter(isVisibleRuntimeJob).length)} icon={<FolderOpen size={16} />} />
          <StatTile label="Artifacts" value={String(status?.artifact_count ?? 0)} icon={<FolderOpen size={16} />} />
        </div>

        <ReadinessPanel
          loading={loading}
          error={error}
          workspaceStatus={status}
          bridgeStatus={bridgeStatus}
          runtimeJobsStatus={runtimeJobsStatus}
          healthCheck={healthCheck}
          zoteroHealth={zoteroHealth}
          wikiReview={wikiReview}
          agentJobs={agentJobs}
          auditRecords={status?.audit_records ?? []}
        />

        <WikiImportRecoveryPanel wikiReview={wikiReview} />

        <WorkspaceStatePanel
          workspaceStatus={status}
          knowledgeRuntime={knowledgeRuntime}
          requirementDrilldown={requirementDrilldown}
          selectedRequirementId={selectedRequirementId}
          requirementQuery={requirementQuery}
          onRequirementQueryChange={setRequirementQuery}
          onSelectRequirement={setSelectedRequirementId}
        />

        <ResearchWorkflowSpine
          loading={loading}
          passport={workflowPassport}
          integrityGate={integrityGate}
          actionLifecycle={actionLifecycle}
          handoffCard={handoffCard}
          actionPreflight={selectedActionPreflight}
          workflowReplayIndex={workflowReplayIndex}
          workflowReplayLineage={workflowReplayLineage}
          behaviorEvalPack={behaviorEvalPack}
          behaviorEvalArtifacts={behaviorEvalArtifacts}
        />

        <div className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <div className="inline-flex w-fit rounded-md border border-outline-variant/60 bg-surface-lowest p-1">
            {[
              ['agents', '智能体'] as const,
              ['artifacts', '产物'] as const,
              ['audit', '审计'] as const,
            ].map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                className={cn(
                  'min-w-[72px] rounded px-3 py-1.5 font-label text-xs transition-colors',
                  tab === key ? 'bg-primary text-primary-foreground' : 'text-foreground/55 hover:text-foreground',
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="relative block w-full max-w-sm">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-foreground/35" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-9 w-full rounded-md border border-outline-variant/60 bg-surface-lowest pl-9 pr-3 text-sm text-foreground outline-none transition-colors placeholder:text-foreground/35 focus:border-primary/45"
              placeholder="筛选"
            />
          </label>
        </div>

        <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(280px,420px)_minmax(0,1fr)]">
          <section className="min-h-[260px] overflow-hidden rounded-md border border-outline-variant/60 bg-surface-lowest">
            {loading ? (
              <div className="flex h-full items-center justify-center gap-2 text-sm text-foreground/45">
                <Loader2 size={16} className="animate-spin" />
                正在加载
              </div>
            ) : error ? (
              <EmptyState
                title="加载失败"
                description={error}
                icon={<XCircle size={36} />}
                action={
                  <button
                    type="button"
                    onClick={() => void load()}
                    className="inline-flex items-center gap-2 rounded-md border border-outline-variant/60 bg-surface-low px-3 py-2 text-sm text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary"
                  >
                    <RefreshCw size={14} />
                    重试
                  </button>
                }
              />
            ) : tab === 'agents' && agentJobs.length === 0 ? (
              <EmptyState title="没有智能体任务" icon={<Bot size={36} />} className="h-full" />
            ) : tab === 'artifacts' && artifacts.length === 0 ? (
              <EmptyState title="没有产物" icon={<FolderOpen size={36} />} className="h-full" />
            ) : tab === 'audit' && auditRecords.length === 0 ? (
              <EmptyState title="没有审计记录" icon={<Activity size={36} />} className="h-full" />
            ) : (
              <div className="custom-scrollbar h-full overflow-auto">
                {tab === 'artifacts'
                  ? artifacts.map((artifact) => (
                      <ArtifactRow
                        key={artifact.path}
                        artifact={artifact}
                        selected={selectedArtifact?.path === artifact.path}
                        onSelect={() => setSelectedArtifactPath(artifact.path)}
                      />
                    ))
                  : tab === 'audit'
                  ? auditRecords.map((record, index) => (
                      <AuditRow
                        key={`${record.timestamp}-${record.tool_name}-${index}`}
                        record={record}
                        selected={selectedRecord === record}
                        onSelect={() => setSelectedAuditIndex(index)}
                      />
                    ))
                  : agentJobs.map((job) => (
                      <AgentJobRow
                        key={job.job_id}
                        job={job}
                        selected={selectedAgentJob?.job_id === job.job_id}
                        onSelect={() => setSelectedAgentJobId(job.job_id)}
                      />
                    ))}
              </div>
            )}
          </section>

          <section className="min-h-[320px] overflow-hidden rounded-md border border-outline-variant/60 bg-surface-lowest">
            <DetailPanel tab={tab} artifact={selectedArtifact} record={selectedRecord} job={selectedAgentJob} />
          </section>
        </div>
      </div>
    </div>
  );
}
