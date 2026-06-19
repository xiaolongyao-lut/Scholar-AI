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
  getAgentWorkspaceStatus,
  listRuntimeJobs,
  type AgentWorkspaceArtifact,
  type AgentWorkspaceAuditRecord,
  type AgentWorkspaceStatus,
  type AgentBridgeStatus,
  type RuntimeJobsStatus,
} from '@/services/agentWorkspaceApi';
import type { WritingJob } from '@/types/runtime';

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
          {isResourceIngest ? 'runtime job · resource_ingest' : `${intent} · ${host}`}
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-1.5">
          <StatusPill tone={jobStatusTone(job)}>{job.status}</StatusPill>
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

export function AgentWorkspace() {
  const [status, setStatus] = useState<AgentWorkspaceStatus | null>(null);
  const [bridgeStatus, setBridgeStatus] = useState<AgentBridgeStatus | null>(null);
  const [runtimeJobsStatus, setRuntimeJobsStatus] = useState<RuntimeJobsStatus | null>(null);
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
      const [next, bridge, runtimeJobs] = await Promise.all([
        getAgentWorkspaceStatus(),
        getAgentBridgeStatus({ limit: 50 }).catch(() => null),
        listRuntimeJobs({ limit: 100 }).catch(() => null),
      ]);
      setStatus(next);
      setBridgeStatus(bridge);
      setRuntimeJobsStatus(runtimeJobs);
      setSelectedArtifactPath((current) => {
        if (current && next.artifacts.some((artifact) => artifact.path === current)) {
          return current;
        }
        return next.artifacts[0]?.path ?? null;
      });
      setSelectedAgentJobId((current) => {
        const visibleJobs = [
          ...(bridge?.recent ?? []),
          ...((runtimeJobs?.recent ?? []).filter((job) => job.kind === 'resource_ingest')),
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
        ...((runtimeJobsStatus?.recent ?? []).filter((job) => job.kind === 'resource_ingest')),
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
          <StatTile label="Resource Ingest" value={String((runtimeJobsStatus?.recent ?? []).filter((job) => job.kind === 'resource_ingest').length)} icon={<FolderOpen size={16} />} />
          <StatTile label="Artifacts" value={String(status?.artifact_count ?? 0)} icon={<FolderOpen size={16} />} />
        </div>

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
