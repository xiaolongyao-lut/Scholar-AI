import { AlertTriangle, BookMarked, RefreshCw, ShieldCheck } from 'lucide-react';
import { useCallback, useEffect, useId, useMemo, useState } from 'react';

import { cn } from '@/lib/utils';
import {
  getKnowledgePackages,
  getKnowledgeRuntimeConformance,
  type KnowledgeRuntimeConformanceItem,
  type KnowledgeRuntimeConformancePackage,
  type KnowledgeRuntimeConformanceResponse,
  type KnowledgePackageProjection,
  type KnowledgePackagesResponse,
} from '@/services/knowledgeApi';

function shortHash(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || trimmed === 'unknown') return 'unknown';
  return trimmed.length > 12 ? `${trimmed.slice(0, 12)}…` : trimmed;
}

function formatPackageStatus(value: KnowledgePackageProjection['status']): string {
  if (value === 'loaded') return '已加载';
  if (value === 'stale') return '已过期';
  if (value === 'disabled') return '已禁用';
  if (value === 'missing') return '缺失';
  return '未知';
}

function formatPackageKind(value: KnowledgePackageProjection['kind']): string {
  if (value === 'wiki') return 'Wiki';
  if (value === 'source_vault') return 'Source Vault';
  if (value === 'academic_english') return 'Academic English';
  if (value === 'skill_package') return 'Skill Package';
  if (value === 'config') return 'Config';
  if (value === 'product_docs') return 'Product Docs';
  return 'Bridge Lexicon';
}

function formatTone(value: KnowledgePackageProjection['status']): string {
  if (value === 'loaded') {
    return 'border-emerald-200/80 bg-emerald-50 text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300';
  }
  if (value === 'stale') {
    return 'border-amber-200/80 bg-amber-50 text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300';
  }
  return 'border-outline-variant/50 bg-surface-high text-foreground/55';
}

function formatConformanceStatus(value: KnowledgeRuntimeConformancePackage['overall_status']): string {
  if (value === 'proved') return '已证明';
  if (value === 'pending') return '待证明';
  if (value === 'blocked') return '已阻断';
  return '不适用';
}

function formatRequirement(value: string): string {
  return value.replaceAll('_', ' ');
}

function readManifestNumber(manifest: Record<string, unknown>, key: string): number | null {
  const value = manifest[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function readManifestStringArray(manifest: Record<string, unknown>, key: string): string[] {
  const value = manifest[key];
  return Array.isArray(value) && value.every((entry) => typeof entry === 'string') ? [...value] : [];
}

function PackageCard({
  item,
  selected,
  onSelect,
}: {
  item: KnowledgePackageProjection;
  selected: boolean;
  onSelect: () => void;
}) {
  const titleId = useId();
  const detailsId = useId();
  const hashId = useId();

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-labelledby={titleId}
      aria-describedby={`${detailsId} ${hashId}`}
      className={cn(
        'w-full min-w-0 rounded-md border px-3 py-3 text-left transition-colors',
        selected
          ? 'border-primary/45 bg-primary/10'
          : 'border-outline-variant/55 bg-surface-lowest hover:border-primary/30 hover:bg-surface-low',
      )}
    >
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div id={titleId} className="truncate text-sm font-semibold text-foreground">
            {item.title}
          </div>
          <div id={detailsId} className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-foreground/45">
            <span>{formatPackageKind(item.kind)}</span>
            <span>{item.available ? '可用' : '不可用'}</span>
            <span>{item.loaded ? '已加载' : '未加载'}</span>
          </div>
        </div>
        <span className={cn('shrink-0 rounded border px-1.5 py-0.5 text-[10px]', formatTone(item.status))}>
          {formatPackageStatus(item.status)}
        </span>
      </div>
      <div id={hashId} className="mt-2 flex min-w-0 items-center gap-1.5 text-[11px] text-foreground/45">
        <ShieldCheck size={12} className="shrink-0" />
        <span className="truncate">{shortHash(item.content_hash)}</span>
      </div>
    </button>
  );
}

function SourceVaultBlocker({
  item,
  conformance,
}: {
  item: KnowledgePackageProjection;
  conformance: KnowledgeRuntimeConformancePackage | null;
}) {
  const manifest = conformance?.manifest ?? item.manifest;
  const blockedItems = conformance?.conformance.filter((row) => row.status === 'blocked') ?? [];
  const requiredForContext = readManifestStringArray(manifest, 'required_for_loaded_context');
  const loadedRefCount = readManifestNumber(manifest, 'loaded_ref_count');
  const isEmptyRuntime = manifest.empty_runtime === true;

  if (item.package_id !== 'source_vault' || (!isEmptyRuntime && blockedItems.length === 0)) {
    return null;
  }

  return (
    <div role="alert" className="mt-4 rounded-md border border-amber-300/70 bg-amber-50 px-3 py-3 text-xs text-amber-900 dark:border-amber-600/50 dark:bg-amber-500/15 dark:text-amber-200">
      <div className="flex items-start gap-2">
        <AlertTriangle size={15} className="mt-0.5 shrink-0" />
        <div className="min-w-0">
          <div className="font-semibold">Knowledge Runtime Pipeline 阻断</div>
          <div className="mt-1 leading-5">
            Source Vault 当前没有可加载来源/分块，不能证明 bounded context、agent resource read 或 evidence pack 召回。
          </div>
          <dl className="mt-2 grid gap-1.5">
            <div className="flex min-w-0 gap-2">
              <dt className="shrink-0 text-amber-950/60 dark:text-amber-100/60">loaded_ref_count</dt>
              <dd className="min-w-0 break-words">{loadedRefCount ?? 'unknown'}</dd>
            </div>
            {requiredForContext.length > 0 ? (
              <div className="flex min-w-0 gap-2">
                <dt className="shrink-0 text-amber-950/60 dark:text-amber-100/60">需要</dt>
                <dd className="min-w-0 break-words">{requiredForContext.join('；')}</dd>
              </div>
            ) : null}
          </dl>
          {blockedItems.length > 0 ? (
            <ul className="mt-2 space-y-1">
              {blockedItems.map((row) => (
                <li key={row.requirement}>
                  <span className="font-medium">{formatRequirement(row.requirement)}</span>
                  {row.missing.length > 0 ? <span>：{row.missing.join('；')}</span> : null}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ConformanceDetail({ conformance }: { conformance: KnowledgeRuntimeConformancePackage | null }) {
  if (!conformance) {
    return (
      <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2 text-xs text-foreground/45">
        Runtime conformance 尚未加载。
      </div>
    );
  }
  const blockedItems = conformance.conformance.filter((row) => row.status === 'blocked');
  const pendingItems = conformance.conformance.filter((row) => row.status === 'pending');
  return (
    <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <dt className="text-foreground/45">流程验收</dt>
        <dd className={cn(
          'rounded border px-1.5 py-0.5 text-[10px]',
          conformance.overall_status === 'proved'
            ? 'border-emerald-300/60 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
            : conformance.overall_status === 'blocked'
              ? 'border-amber-300/60 bg-amber-500/10 text-amber-800 dark:text-amber-300'
              : 'border-outline-variant/60 bg-surface-high text-foreground/60',
        )}>
          {formatConformanceStatus(conformance.overall_status)}
        </dd>
      </div>
      <div className="mt-2 grid gap-1 text-[11px] text-foreground/60">
        <div>requirements: {conformance.conformance.length}</div>
        <div>blocked: {blockedItems.length}</div>
        <div>pending: {pendingItems.length}</div>
      </div>
    </div>
  );
}

function ActualLoadingGatePanel({
  gate,
}: {
  gate: KnowledgeRuntimeConformanceResponse['actual_loading_gate'] | null;
}) {
  if (!gate) {
    return null;
  }
  const isProved = gate.status === 'proved';
  return (
    <div
      role={isProved ? undefined : 'alert'}
      className={cn(
        'rounded-md border px-3 py-3 text-xs',
        isProved
          ? 'border-emerald-300/60 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300'
          : 'border-amber-300/70 bg-amber-50 text-amber-900 dark:border-amber-600/50 dark:bg-amber-500/15 dark:text-amber-200',
      )}
    >
      <div className="flex items-start gap-2">
        {isProved ? <ShieldCheck size={15} className="mt-0.5 shrink-0" /> : <AlertTriangle size={15} className="mt-0.5 shrink-0" />}
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">Live 模型门禁</span>
            <span className="rounded border border-current/25 px-1.5 py-0.5 text-[10px]">
              {formatConformanceStatus(gate.status)}
            </span>
            <span className="font-mono text-[10px] opacity-70">{gate.verdict}</span>
          </div>
          <div className="mt-1 break-all font-mono text-[11px] opacity-80">{gate.artifact_ref}</div>
          {gate.artifact_ref !== gate.artifact_path ? (
            <div className="mt-0.5 break-all font-mono text-[10px] opacity-60">{gate.artifact_path}</div>
          ) : null}
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] opacity-75">
            <span>exists={String(gate.artifact_exists)}</span>
            <span>schema={String(gate.artifact_schema_valid)}</span>
            <span>contract={String(gate.artifact_contract_valid)}</span>
            <span>checked={gate.artifact_checked_at}</span>
          </div>
          {gate.missing.length > 0 ? (
            <div className="mt-1 break-words opacity-80">{gate.missing.join('；')}</div>
          ) : null}
          <div className="mt-3 rounded-md border border-current/20 bg-white/35 px-2.5 py-2 dark:bg-black/10">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">Recovery state</span>
              <span className="rounded border border-current/25 px-1.5 py-0.5 text-[10px]">
                {gate.recovery.state}
              </span>
              <span className="font-mono text-[10px] opacity-70">read_only={String(gate.recovery.read_only)}</span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] opacity-75">
              <span>blocked_by={gate.recovery.blocked_by.length}</span>
              <span>provider_ready={String(gate.recovery.provider_ready_for_authorized_live_smoke)}</span>
              <span>live_smoke_required={String(gate.recovery.completion_requires_authorized_live_smoke)}</span>
              <span>refs={gate.recovery.recovery_refs.length}</span>
            </div>
            {gate.recovery.blocked_by.length > 0 ? (
              <div className="mt-1 break-words opacity-80">{gate.recovery.blocked_by.join('；')}</div>
            ) : null}
            {gate.recovery.recovery_refs.length > 0 ? (
              <div className="mt-1 space-y-1">
                {gate.recovery.recovery_refs.slice(0, 3).map((ref) => (
                  <div key={`${ref.ref_type}:${ref.ref}`} className="break-all font-mono text-[10px] opacity-75">
                    {ref.ref_type} · {ref.status || 'unknown'} · auth={String(ref.requires_authorization)}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
          <div className="mt-3 rounded-md border border-current/20 bg-white/35 px-2.5 py-2 dark:bg-black/10">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">Provider preflight</span>
              <span className="rounded border border-current/25 px-1.5 py-0.5 text-[10px]">
                {formatConformanceStatus(gate.provider_preflight.status)}
              </span>
              <span className="font-mono text-[10px] opacity-70">{gate.provider_preflight.latest_status}</span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] opacity-75">
              <span>records={gate.provider_preflight.record_count}</span>
              <span>exists={String(gate.provider_preflight.artifact_exists)}</span>
              <span>schema={String(gate.provider_preflight.artifact_schema_valid)}</span>
              <span>checked={gate.provider_preflight.checked_at}</span>
            </div>
            {gate.provider_preflight.records.length > 0 ? (
              <div className="mt-1 space-y-1">
                {gate.provider_preflight.records.map((record) => (
                  <div key={record.fingerprint} className="break-all font-mono text-[10px] opacity-75">
                    {record.provider || 'unknown'} · {record.base_url_host || 'unknown'} · {record.model || 'unknown'} · {record.status}
                  </div>
                ))}
              </div>
            ) : null}
            {gate.provider_preflight.missing.length > 0 ? (
              <div className="mt-1 break-words opacity-80">{gate.provider_preflight.missing.join('；')}</div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function formatEvidenceFlag(value: boolean): string {
  return value ? 'proved' : 'missing';
}

function ConformanceEvidence({ conformance }: { conformance: KnowledgeRuntimeConformancePackage | null }) {
  if (!conformance) {
    return null;
  }

  const consumers = conformance.runtime_consumers
    .map((entry) => {
      const consumer = entry.consumer ?? '';
      const use = entry.use ?? '';
      return [consumer, use].filter(Boolean).join(' · ');
    })
    .filter((entry) => entry.length > 0);
  const evidenceFlags = [
    ['source edit hash', conformance.test_evidence.source_edit_hash_test],
    ['context receipt', conformance.test_evidence.context_receipt_test],
    ['evidence pack', conformance.test_evidence.evidence_pack_test],
    ['agent resource read', conformance.test_evidence.agent_resource_read_test],
    ['MCP tool', conformance.test_evidence.mcp_tool_test],
  ] as const;

  return (
    <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2 text-xs">
      <dt className="text-foreground/45">运行时证据链</dt>
      <dd className="mt-2 grid gap-3">
        <div>
          <div className="text-[11px] font-medium text-foreground/55">Runtime consumers</div>
          <div className="mt-1 space-y-1 text-[11px] text-foreground/70">
            {consumers.length > 0 ? consumers.map((entry) => (
              <div key={entry} className="break-words">{entry}</div>
            )) : (
              <div className="text-foreground/40">暂无 runtime consumer 记录。</div>
            )}
          </div>
        </div>
        <div>
          <div className="text-[11px] font-medium text-foreground/55">MCP tools</div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {conformance.mcp_tools.length > 0 ? conformance.mcp_tools.map((tool) => (
              <span key={tool} className="rounded border border-outline-variant/50 bg-surface-lowest px-2 py-0.5 font-mono text-[10px] text-foreground/65">
                {tool}
              </span>
            )) : (
              <span className="text-[11px] text-foreground/40">暂无 MCP tool 记录。</span>
            )}
          </div>
        </div>
        <div>
          <div className="text-[11px] font-medium text-foreground/55">Focused tests</div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {evidenceFlags.map(([label, passed]) => (
              <span
                key={label}
                className={cn(
                  'rounded border px-2 py-0.5 text-[10px]',
                  passed
                    ? 'border-emerald-300/50 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                    : 'border-outline-variant/50 bg-surface-lowest text-foreground/45',
                )}
              >
                {label}: {formatEvidenceFlag(passed)}
              </span>
            ))}
          </div>
        </div>
        {conformance.test_evidence.test_nodes.length > 0 ? (
          <div>
            <div className="text-[11px] font-medium text-foreground/55">Test nodes</div>
            <ul className="mt-1 space-y-1 text-[11px] text-foreground/65">
              {conformance.test_evidence.test_nodes.map((node) => (
                <li key={node} className="break-all font-mono">{node}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </dd>
    </div>
  );
}

function PackageDetail({
  item,
  conformance,
}: {
  item: KnowledgePackageProjection | null;
  conformance: KnowledgeRuntimeConformancePackage | null;
}) {
  if (!item) {
    return (
      <aside className="rounded-md border border-outline-variant/60 bg-surface-lowest p-4 text-sm text-foreground/45">
        选择一个知识包。
      </aside>
    );
  }

  return (
    <aside className="rounded-md border border-outline-variant/60 bg-surface-lowest p-4">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
          <BookMarked size={17} />
        </div>
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-foreground">{item.title}</h2>
          <p className="mt-1 truncate text-xs text-foreground/45">{item.source_label}</p>
        </div>
      </div>

      <dl className="mt-4 grid gap-2 text-xs">
        <ConformanceDetail conformance={conformance} />
        <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
          <dt className="text-foreground/45">读取端点</dt>
          <dd className="mt-1 break-all font-mono text-[11px] text-foreground/75">{item.read_endpoint}</dd>
        </div>
        <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
          <dt className="text-foreground/45">来源路径</dt>
          <dd className="mt-1 break-all font-mono text-[11px] text-foreground/75">{item.source_path}</dd>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
          <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
            <dt className="text-foreground/45">来源哈希</dt>
            <dd className="mt-1 break-all font-mono text-[11px] text-foreground/75">{shortHash(item.source_hash)}</dd>
          </div>
          <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
            <dt className="text-foreground/45">内容哈希</dt>
            <dd className="mt-1 break-all font-mono text-[11px] text-foreground/75">{shortHash(item.content_hash)}</dd>
          </div>
        </div>
        <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
          <dt className="text-foreground/45">备注</dt>
          <dd className="mt-2 space-y-1.5 text-[11px] text-foreground/65">
            {item.notes.length > 0 ? item.notes.map((note) => <div key={note}>{note}</div>) : <div>暂无备注。</div>}
          </dd>
        </div>
        <ConformanceEvidence conformance={conformance} />
      </dl>
      <SourceVaultBlocker item={item} conformance={conformance} />
    </aside>
  );
}

/**
 * Compact read-only overview for unified knowledge packages.
 *
 * Why: this surface gives the workbench one bounded registry view without
 * disturbing the existing wiki/source vault panels.
 */
export function KnowledgePackagesPanel() {
  const [payload, setPayload] = useState<KnowledgePackagesResponse | null>(null);
  const [conformancePayload, setConformancePayload] = useState<KnowledgeRuntimeConformanceResponse | null>(null);
  const [selectedPackageId, setSelectedPackageId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadPackages = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [next, nextConformance] = await Promise.all([
        getKnowledgePackages(),
        getKnowledgeRuntimeConformance(),
      ]);
      setPayload(next);
      setConformancePayload(nextConformance);
      setSelectedPackageId((current) => current && next.packages.some((item) => item.package_id === current)
        ? current
        : next.packages[0]?.package_id ?? null);
    } catch (err: unknown) {
      setPayload(null);
      setConformancePayload(null);
      setError(err instanceof Error ? err.message : '知识包清单读取失败。');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPackages();
  }, [loadPackages]);

  const packages = payload?.packages ?? [];
  const selectedPackage = useMemo(
    () => packages.find((item) => item.package_id === selectedPackageId) ?? null,
    [packages, selectedPackageId],
  );
  const selectedConformance = useMemo(
    () => conformancePayload?.packages.find((item) => item.package_id === selectedPackageId) ?? null,
    [conformancePayload, selectedPackageId],
  );

  return (
    <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <section className="min-w-0 space-y-4">
        <div className="rounded-md border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-foreground">
                <BookMarked size={18} className="text-primary/75" />
                <h2 className="truncate text-base font-semibold">知识包注册表</h2>
              </div>
              <p className="mt-1 max-w-3xl break-words text-xs text-foreground/55">
                只读概览统一知识包、加载状态与来源/内容哈希。
              </p>
            </div>
            <button
              type="button"
              onClick={() => void loadPackages()}
              disabled={isLoading}
              className="inline-flex items-center gap-1.5 self-start rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 text-xs text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-wait disabled:opacity-60"
            >
              <RefreshCw size={13} className={cn(isLoading && 'animate-spin')} />
              刷新
            </button>
          </div>

          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
              <div className="text-[11px] text-foreground/45">知识包</div>
              <div className="mt-1 text-sm font-semibold text-foreground">{packages.length}</div>
            </div>
            <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
              <div className="text-[11px] text-foreground/45">已加载</div>
              <div className="mt-1 text-sm font-semibold text-foreground">
                {packages.filter((item) => item.loaded).length}
              </div>
            </div>
            <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
              <div className="text-[11px] text-foreground/45">可搜索</div>
              <div className="mt-1 text-sm font-semibold text-foreground">
                {packages.filter((item) => item.search_endpoint !== null).length}
              </div>
            </div>
            <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2 sm:col-span-3">
              <div className="text-[11px] text-foreground/45">KRT 阻断项</div>
              <div className="mt-1 text-sm font-semibold text-foreground">
                {conformancePayload?.summary.blocked ?? 0}
              </div>
            </div>
          </div>
          <div className="mt-3">
            <ActualLoadingGatePanel gate={conformancePayload?.actual_loading_gate ?? null} />
          </div>
        </div>

        {error ? (
          <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
            <div className="flex items-center justify-between gap-3">
              <span className="min-w-0">{error}</span>
              <button
                type="button"
                onClick={() => void loadPackages()}
                className="shrink-0 rounded border border-red-300/60 px-2 py-1 text-[11px] hover:bg-red-100 dark:border-red-700/60 dark:hover:bg-red-500/10"
              >
                重试
              </button>
            </div>
          </div>
        ) : null}

        <div className="grid gap-2">
          {isLoading ? (
            <div className="rounded-md border border-outline-variant/60 bg-surface-lowest px-4 py-10 text-center text-sm text-foreground/45">
              正在读取知识包…
            </div>
          ) : packages.length > 0 ? (
            packages.map((item) => (
              <PackageCard
                key={item.package_id}
                item={item}
                selected={item.package_id === selectedPackageId}
                onSelect={() => setSelectedPackageId(item.package_id)}
              />
            ))
          ) : (
            <div className="rounded-md border border-outline-variant/60 bg-surface-lowest px-4 py-10 text-center text-sm text-foreground/45">
              暂无知识包记录
            </div>
          )}
        </div>
      </section>

      <PackageDetail item={selectedPackage} conformance={selectedConformance} />
    </div>
  );
}
