import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  Bot,
  CheckCircle2,
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
  getAgentWorkspaceStatus,
  getEvidenceIntegrityGate,
  getWorkflowPassport,
  getWorkflowReplayIndex,
  getWorkflowReplayLineage,
  getZoteroAttachmentHealth,
  listRuntimeJobs,
  type AgentHandoffCardProjection,
  type AgentWorkflowHealthCheck,
  type AgentWorkspaceArtifact,
  type AgentWorkspaceAuditRecord,
  type AgentWorkspaceStatus,
  type AgentBridgeStatus,
  type EvidenceIntegrityGateProjection,
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
import { getWikiReview } from '@/services/wikiApi';
import type { WritingJob } from '@/types/runtime';
import type { WikiReviewListModel } from '@/types/wiki';

type WorkspaceTab = 'agents' | 'artifacts' | 'audit';

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

function readRecordField(record: Record<string, unknown>, key: string): Record<string, unknown> {
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
  return `${card.status} · refs ${card.resource_refs.length} · probes ${card.resume_probes.length}`;
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
              {JSON.stringify(metadata, null, 2)}
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
  handoffCard,
  actionPreflight,
  workflowReplayIndex,
  workflowReplayLineage,
  behaviorEvalArtifacts,
  density = 'default',
}: {
  loading: boolean;
  passport: WorkflowPassportProjection | null;
  integrityGate: EvidenceIntegrityGateProjection | null;
  handoffCard: AgentHandoffCardProjection | null;
  actionPreflight: WorkflowActionPreflightProjection | null;
  workflowReplayIndex: WorkflowReplayIndexProjection | null;
  workflowReplayLineage: WorkflowReplayLineageProjection | null;
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
  const firstSignal = integrityGate?.signals[0] ?? null;
  const behaviorEvalLatest = behaviorEvalArtifacts[0] ?? null;
  const handoffBlocked = (handoffCard?.blockers.length ?? 0) > 0;
  const handoffUnresolved = (handoffCard?.unresolved.length ?? 0) > 0;
  const readinessClaims = workflowReadinessClaims(integrityGate, handoffCard);
  const visibleReadinessClaims = readinessClaims?.claims.slice(0, isDesktopAcceptance ? 2 : 4) ?? [];
  const preflightBlocked = actionPreflight?.status === 'blocked' || actionPreflight?.can_proceed === false;
  const preflightUnresolved = actionPreflight?.status === 'unresolved';
  const preflightRefreshRequired = actionPreflight?.refresh_required === true || actionPreflight?.freshness?.refresh_required === true;
  const replayIndexBlocked = (workflowReplayIndex?.blockers.length ?? 0) > 0;
  const replayIndexUnresolved = (workflowReplayIndex?.unresolved.length ?? 0) > 0;
  const lineageBlocked = (workflowReplayLineage?.blockers.length ?? 0) > 0;
  const lineageUnresolved = (workflowReplayLineage?.unresolved.length ?? 0) > 0;

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
          <StatusPill tone={lineageBlocked ? 'danger' : lineageUnresolved ? 'warning' : workflowReplayLineage ? 'info' : 'neutral'}>
            replay {workflowReplayLineage ? workflowReplayLineage.receipt_count : '未读取'}
          </StatusPill>
          <StatusPill tone={replayIndexBlocked ? 'danger' : replayIndexUnresolved ? 'warning' : workflowReplayIndex ? 'info' : 'neutral'}>
            replay index {workflowReplayIndex ? workflowReplayIndex.matching_job_count : '未读取'}
          </StatusPill>
        </div>
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
                    </div>
                  </article>
                );
              })}
            </div>
          )}
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
            </div>
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
              <h3 className="truncate font-label text-xs font-semibold text-foreground">Agent Handoff</h3>
              <StatusPill tone={handoffBlocked ? 'danger' : handoffUnresolved ? 'warning' : handoffCard ? 'success' : 'neutral'}>
                {handoffCard ? handoffCard.status : '未读取'}
              </StatusPill>
            </div>
            <p className="mt-2 break-words text-xs leading-5 text-foreground/60">
              {handoffCard?.blockers[0]
                || handoffCard?.unresolved[0]
                || (handoffCard ? 'Handoff card 已生成，当前状态与完整性门禁待复核。' : '')
                || 'Handoff card 暂无可显示记录。'}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <StatusPill tone="neutral">{handoffSummary(handoffCard)}</StatusPill>
              <StatusPill tone={actionPreflight?.refresh_receipt ? 'info' : 'neutral'}>
                {preflightReceiptSummary(actionPreflight)}
              </StatusPill>
              <StatusPill tone={behaviorEvalLatest ? 'success' : 'neutral'}>
                behavior eval {behaviorEvalArtifacts.length}
              </StatusPill>
              {behaviorEvalLatest ? <StatusPill tone="info">{behaviorEvalLatest.name}</StatusPill> : null}
            </div>
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

export function AgentWorkspace() {
  const [status, setStatus] = useState<AgentWorkspaceStatus | null>(null);
  const [bridgeStatus, setBridgeStatus] = useState<AgentBridgeStatus | null>(null);
  const [runtimeJobsStatus, setRuntimeJobsStatus] = useState<RuntimeJobsStatus | null>(null);
  const [healthCheck, setHealthCheck] = useState<AgentWorkflowHealthCheck | null>(null);
  const [zoteroHealth, setZoteroHealth] = useState<ZoteroAttachmentHealth | null>(null);
  const [wikiReview, setWikiReview] = useState<WikiReviewListModel | null>(null);
  const [workflowPassport, setWorkflowPassport] = useState<WorkflowPassportProjection | null>(null);
  const [integrityGate, setIntegrityGate] = useState<EvidenceIntegrityGateProjection | null>(null);
  const [handoffCard, setHandoffCard] = useState<AgentHandoffCardProjection | null>(null);
  const [workflowReplayIndex, setWorkflowReplayIndex] = useState<WorkflowReplayIndexProjection | null>(null);
  const [workflowReplayLineage, setWorkflowReplayLineage] = useState<WorkflowReplayLineageProjection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<WorkspaceTab>('agents');
  const [query, setQuery] = useState('');
  const [selectedArtifactPath, setSelectedArtifactPath] = useState<string | null>(null);
  const [selectedAuditIndex, setSelectedAuditIndex] = useState(0);
  const [selectedAgentJobId, setSelectedAgentJobId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [next, bridge, runtimeJobs, workflowHealth, zotero, review, passport, gate, replayIndex] = await Promise.all([
        getAgentWorkspaceStatus(),
        getAgentBridgeStatus({ limit: 50 }).catch(() => null),
        listRuntimeJobs({ limit: 100 }).catch(() => null),
        getAgentWorkflowHealth({ includeLive: false }).catch(() => null),
        getZoteroAttachmentHealth({ maxItems: 20, writeReports: false }).catch(() => null),
        getWikiReview().catch(() => null),
        getWorkflowPassport({ limit: 500 }).catch(() => null),
        getEvidenceIntegrityGate({ limit: 500 }).catch(() => null),
        getWorkflowReplayIndex({ limit: 25 }).catch(() => null),
      ]);
      setStatus(next);
      setBridgeStatus(bridge);
      setRuntimeJobsStatus(runtimeJobs);
      setHealthCheck(workflowHealth);
      setZoteroHealth(zotero);
      setWikiReview(review);
      setWorkflowPassport(passport);
      setIntegrityGate(gate);
      setWorkflowReplayIndex(replayIndex);
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
      setHandoffCard(null);
      setWorkflowReplayIndex(null);
      setWorkflowReplayLineage(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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

        <ResearchWorkflowSpine
          loading={loading}
          passport={workflowPassport}
          integrityGate={integrityGate}
          handoffCard={handoffCard}
          actionPreflight={selectedActionPreflight}
          workflowReplayIndex={workflowReplayIndex}
          workflowReplayLineage={workflowReplayLineage}
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
