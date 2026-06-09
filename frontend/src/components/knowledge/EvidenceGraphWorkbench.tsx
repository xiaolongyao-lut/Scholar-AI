import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Filter,
  GitBranch,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react';

import { GraphPayloadViewer } from '@/components/graph/GraphPayloadViewer';
import { cn } from '@/lib/utils';
import {
  getEvidenceGraph,
  type EvidenceGraphEdge,
  type EvidenceGraphNode,
  type EvidenceGraphPayload,
  type EvidenceGraphRelation,
  type EvidenceGraphScopeKind,
  type EvidenceGraphStatus,
} from '@/services/graphApi';
import { evidenceGraphToGraphPayload } from './evidenceGraphAdapter';

type EvidenceAvailabilityFilter = 'all' | 'with_evidence' | 'without_evidence';

interface GraphFilters {
  nodeType: string;
  relation: string;
  status: string;
  evidence: EvidenceAvailabilityFilter;
  minConfidence: number;
  sourceText: string;
}

const SCOPE_KIND_OPTIONS: Array<{ value: EvidenceGraphScopeKind; label: string }> = [
  { value: 'project', label: '项目' },
  { value: 'source', label: '来源' },
  { value: 'knowledge_item', label: '知识项' },
  { value: 'insight', label: '洞察' },
  { value: 'smart_read_session', label: '研读会话' },
  { value: 'question', label: '问题' },
];

const DEFAULT_FILTERS: GraphFilters = {
  nodeType: 'all',
  relation: 'all',
  status: 'all',
  evidence: 'all',
  minConfidence: 0,
  sourceText: '',
};

function formatNodeType(value: string): string {
  const labels: Record<string, string> = {
    source: '来源',
    chunk: '分块',
    paper: '论文',
    concept: '概念',
    claim: '断言',
    method: '方法',
    dataset: '数据集',
    metric: '指标',
    finding: '发现',
    limitation: '局限',
    insight: '洞察',
    session: '会话',
    agent: '智能体',
  };
  return labels[value] ?? value;
}

function formatRelation(value: string): string {
  const labels: Record<string, string> = {
    contains: '包含',
    derived_from: '源自',
    cites: '引用',
    supports: '支持',
    contradicts: '矛盾',
    uses_method: '使用方法',
    uses_dataset: '使用数据',
    evaluated_by: '评估于',
    mentions: '提及',
    promoted_to: '提升到',
    related: '相关',
  };
  return labels[value] ?? value;
}

function formatStatus(value: EvidenceGraphStatus): string {
  if (value === 'trusted') return '可信';
  if (value === 'candidate') return '候选';
  if (value === 'rejected') return '已拒绝';
  return '过期';
}

function confidenceValue(value: number | null | undefined): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function nodeHasEvidence(node: EvidenceGraphNode): boolean {
  return node.provenance_refs.length > 0;
}

function edgeHasEvidence(edge: EvidenceGraphEdge): boolean {
  return edge.provenance_refs.length > 0;
}

function refMatchesSourceText(node: EvidenceGraphNode, sourceText: string): boolean {
  const needle = sourceText.trim().toLowerCase();
  if (!needle) return true;
  const haystacks = [
    node.id,
    node.label,
    node.metadata.material_id,
    node.metadata.source_id,
    node.metadata.source_vault_id,
    ...node.provenance_refs.flatMap((ref) => [
      ref.source_id,
      ref.source_vault_id,
      ref.chunk_id,
      ref.source_vault_chunk_id,
      ref.material_id,
    ]),
  ]
    .filter((value): value is string => typeof value === 'string')
    .map((value) => value.toLowerCase());
  return haystacks.some((value) => value.includes(needle));
}

function nodeMatchesFilters(node: EvidenceGraphNode, filters: GraphFilters): boolean {
  if (filters.nodeType !== 'all' && node.type !== filters.nodeType) return false;
  if (filters.status !== 'all' && node.status !== filters.status) return false;
  if (filters.evidence === 'with_evidence' && !nodeHasEvidence(node)) return false;
  if (filters.evidence === 'without_evidence' && nodeHasEvidence(node)) return false;
  if (confidenceValue(node.confidence) < filters.minConfidence) return false;
  return refMatchesSourceText(node, filters.sourceText);
}

function edgeMatchesFilters(edge: EvidenceGraphEdge, filters: GraphFilters, visibleNodeIds: Set<string>): boolean {
  if (!visibleNodeIds.has(edge.source) || !visibleNodeIds.has(edge.target)) return false;
  if (filters.relation !== 'all' && edge.relation !== filters.relation) return false;
  if (filters.status !== 'all' && edge.status !== filters.status) return false;
  if (filters.evidence === 'with_evidence' && !edgeHasEvidence(edge)) return false;
  if (filters.evidence === 'without_evidence' && edgeHasEvidence(edge)) return false;
  return confidenceValue(edge.confidence) >= filters.minConfidence;
}

function filteredEvidenceGraph(payload: EvidenceGraphPayload, filters: GraphFilters): EvidenceGraphPayload {
  const nodes = payload.nodes.filter((node) => nodeMatchesFilters(node, filters));
  const visibleNodeIds = new Set(nodes.map((node) => node.id));
  const edges = payload.edges.filter((edge) => edgeMatchesFilters(edge, filters, visibleNodeIds));
  const connectedNodeIds = new Set<string>();
  edges.forEach((edge) => {
    connectedNodeIds.add(edge.source);
    connectedNodeIds.add(edge.target);
  });
  const keepIsolated = filters.relation === 'all';
  const finalNodes = keepIsolated ? nodes : nodes.filter((node) => connectedNodeIds.has(node.id));
  return {
    ...payload,
    nodes: finalNodes,
    edges,
  };
}

function uniqueSorted<T extends string>(values: T[]): T[] {
  return [...new Set(values)].sort((a, b) => a.localeCompare(b));
}

function DetailDrawer({ node }: { node: EvidenceGraphNode | null }) {
  if (!node) {
    return (
      <aside className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 text-sm text-foreground/45">
        选择节点查看可信状态、证据锚点和来源标识。
      </aside>
    );
  }

  return (
    <aside className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
          <ShieldCheck size={17} />
        </div>
        <div className="min-w-0">
          <h2 className="line-clamp-2 text-sm font-semibold text-foreground">{node.label}</h2>
          <p className="mt-1 text-xs text-foreground/45">{formatNodeType(node.type)} · {formatStatus(node.status)}</p>
        </div>
      </div>
      <dl className="mt-4 grid gap-2 text-xs">
        <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
          <dt className="text-foreground/45">节点 ID</dt>
          <dd className="mt-1 break-all font-mono text-[11px] text-foreground/75">{node.id}</dd>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
          <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
            <dt className="text-foreground/45">置信度</dt>
            <dd className="mt-1 text-foreground/75">{node.confidence === null || node.confidence === undefined ? '未标注' : node.confidence.toFixed(2)}</dd>
          </div>
          <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
            <dt className="text-foreground/45">证据锚点</dt>
            <dd className="mt-1 text-foreground/75">{node.provenance_refs.length}</dd>
          </div>
        </div>
        {node.provenance_refs.length > 0 ? (
          <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
            <dt className="text-foreground/45">来源</dt>
            <dd className="mt-2 space-y-1.5">
              {node.provenance_refs.slice(0, 4).map((ref, index) => (
                <div key={`${node.id}-ref-${index}`} className="rounded border border-outline-variant/40 bg-surface-lowest px-2 py-1.5 text-[11px] text-foreground/65">
                  <div className="truncate">{ref.material_id ?? ref.source_id ?? ref.source_vault_id ?? '未命名来源'}</div>
                  <div className="mt-0.5 truncate text-foreground/40">
                    {ref.chunk_id ?? ref.source_vault_chunk_id ?? '无 chunk'}
                    {ref.page ? ` · p.${ref.page}` : ''}
                  </div>
                </div>
              ))}
            </dd>
          </div>
        ) : null}
      </dl>
    </aside>
  );
}

export function EvidenceGraphWorkbench() {
  const [searchParams] = useSearchParams();
  const sourceFilterParam = searchParams.get('source')?.trim() ?? '';
  const [payload, setPayload] = useState<EvidenceGraphPayload | null>(null);
  const [scopeKind, setScopeKind] = useState<EvidenceGraphScopeKind>('project');
  const [scopeRef, setScopeRef] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [filters, setFilters] = useState<GraphFilters>({
    ...DEFAULT_FILTERS,
    sourceText: sourceFilterParam,
  });
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadGraph = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const next = await getEvidenceGraph({
        scope_kind: scopeKind,
        scope_ref: scopeRef.trim(),
        session_id: sessionId.trim() || undefined,
      });
      setPayload(next);
      setSelectedNodeId((current) => current && next.nodes.some((node) => node.id === current)
        ? current
        : next.nodes[0]?.id ?? null);
    } catch (err: unknown) {
      setPayload(null);
      setError(err instanceof Error ? err.message : '证据图谱读取失败。');
    } finally {
      setIsLoading(false);
    }
  }, [scopeKind, scopeRef, sessionId]);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  useEffect(() => {
    if (!sourceFilterParam) return;
    setFilters((current) => current.sourceText === sourceFilterParam
      ? current
      : { ...current, sourceText: sourceFilterParam });
  }, [sourceFilterParam]);

  const nodeTypes = useMemo(
    () => uniqueSorted((payload?.nodes ?? []).map((node) => node.type)),
    [payload],
  );
  const relations = useMemo(
    () => uniqueSorted((payload?.edges ?? []).map((edge) => edge.relation)),
    [payload],
  );
  const statuses = useMemo(
    () => uniqueSorted([
      ...(payload?.nodes ?? []).map((node) => node.status),
      ...(payload?.edges ?? []).map((edge) => edge.status),
    ]),
    [payload],
  );

  const filteredPayload = useMemo(
    () => payload ? filteredEvidenceGraph(payload, filters) : null,
    [filters, payload],
  );
  const viewerPayload = useMemo(
    () => filteredPayload ? evidenceGraphToGraphPayload(filteredPayload) : null,
    [filteredPayload],
  );
  const selectedNode = useMemo(
    () => filteredPayload?.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [filteredPayload, selectedNodeId],
  );

  const updateFilter = <K extends keyof GraphFilters,>(key: K, value: GraphFilters[K]) => {
    setFilters((current) => ({ ...current, [key]: value }));
  };

  const nodeCount = filteredPayload?.nodes.length ?? 0;
  const edgeCount = filteredPayload?.edges.length ?? 0;

  return (
    <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <section className="min-w-0 space-y-4">
        <div className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                <GitBranch size={18} />
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-semibold text-foreground">证据图谱</h2>
                <p className="mt-1 text-xs leading-5 text-foreground/55">
                  按来源、知识项、洞察、研读会话、问题或项目查看可追溯关系。
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => void loadGraph()}
              disabled={isLoading}
              className="inline-flex items-center gap-1.5 self-start rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 text-xs text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-wait disabled:opacity-60"
            >
              <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} />
              刷新
            </button>
          </div>

          <div className="mt-4 grid gap-2 lg:grid-cols-[11rem_minmax(0,1fr)_minmax(0,1fr)_auto]">
            <label className="grid gap-1 text-[11px] text-foreground/55">
              <span>Scope</span>
              <select
                value={scopeKind}
                onChange={(event) => setScopeKind(event.target.value as EvidenceGraphScopeKind)}
                className="h-9 rounded-md border border-outline-variant/50 bg-surface-high px-2 text-sm text-foreground focus:border-primary/40 focus:outline-none"
              >
                {SCOPE_KIND_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-[11px] text-foreground/55">
              <span>Ref</span>
              <input
                type="text"
                value={scopeRef}
                onChange={(event) => setScopeRef(event.target.value)}
                className="h-9 rounded-md border border-outline-variant/50 bg-surface-high px-3 text-sm text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
                placeholder="scope id / question"
              />
            </label>
            <label className="grid gap-1 text-[11px] text-foreground/55">
              <span>Session</span>
              <input
                type="text"
                value={sessionId}
                onChange={(event) => setSessionId(event.target.value)}
                className="h-9 rounded-md border border-outline-variant/50 bg-surface-high px-3 text-sm text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
                placeholder="SmartRead session"
              />
            </label>
            <button
              type="button"
              onClick={() => void loadGraph()}
              disabled={isLoading}
              className="inline-flex h-9 items-center justify-center gap-1.5 self-end rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-wait disabled:opacity-60"
            >
              <Search size={13} />
              查询
            </button>
          </div>
        </div>

        <div className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-3 shadow-sm">
          <div className="mb-3 flex items-center gap-2 text-xs font-medium text-foreground/70">
            <Filter size={14} />
            <span>过滤器</span>
            <span className="ml-auto text-[11px] text-foreground/40">{nodeCount} 节点 · {edgeCount} 边</span>
          </div>
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-6">
            <select
              aria-label="节点类型"
              value={filters.nodeType}
              onChange={(event) => updateFilter('nodeType', event.target.value)}
              className="h-9 rounded-md border border-outline-variant/50 bg-surface-high px-2 text-xs text-foreground"
            >
              <option value="all">全部节点</option>
              {nodeTypes.map((type) => (
                <option key={type} value={type}>{formatNodeType(type)}</option>
              ))}
            </select>
            <select
              aria-label="关系类型"
              value={filters.relation}
              onChange={(event) => updateFilter('relation', event.target.value)}
              className="h-9 rounded-md border border-outline-variant/50 bg-surface-high px-2 text-xs text-foreground"
            >
              <option value="all">全部关系</option>
              {relations.map((relation) => (
                <option key={relation} value={relation}>{formatRelation(relation)}</option>
              ))}
            </select>
            <select
              aria-label="可信状态"
              value={filters.status}
              onChange={(event) => updateFilter('status', event.target.value)}
              className="h-9 rounded-md border border-outline-variant/50 bg-surface-high px-2 text-xs text-foreground"
            >
              <option value="all">全部状态</option>
              {statuses.map((status) => (
                <option key={status} value={status}>{formatStatus(status)}</option>
              ))}
            </select>
            <select
              aria-label="证据可用性"
              value={filters.evidence}
              onChange={(event) => updateFilter('evidence', event.target.value as EvidenceAvailabilityFilter)}
              className="h-9 rounded-md border border-outline-variant/50 bg-surface-high px-2 text-xs text-foreground"
            >
              <option value="all">全部证据</option>
              <option value="with_evidence">有证据</option>
              <option value="without_evidence">无证据</option>
            </select>
            <label className="flex h-9 items-center gap-2 rounded-md border border-outline-variant/50 bg-surface-high px-2 text-xs text-foreground/65">
              <span className="shrink-0">≥ {filters.minConfidence.toFixed(1)}</span>
              <input
                aria-label="最小置信度"
                type="range"
                min={0}
                max={1}
                step={0.1}
                value={filters.minConfidence}
                onChange={(event) => updateFilter('minConfidence', Number(event.target.value))}
                className="min-w-0 flex-1"
              />
            </label>
            <input
              aria-label="来源或项目过滤"
              type="search"
              value={filters.sourceText}
              onChange={(event) => updateFilter('sourceText', event.target.value)}
              placeholder="来源 / 项目"
              className="h-9 rounded-md border border-outline-variant/50 bg-surface-high px-2 text-xs text-foreground placeholder:text-foreground/30"
            />
          </div>
        </div>

        {error ? (
          <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
            {error}
          </div>
        ) : null}
        {payload?.warnings.length ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
            {payload.warnings.join(' ')}
          </div>
        ) : null}

        <div className="overflow-hidden rounded-lg border border-outline-variant/60 bg-surface-lowest shadow-sm">
          <div className="flex items-center justify-between border-b border-outline-variant/60 px-4 py-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-foreground">图谱视图</span>
              <span className="text-[10px] text-foreground/45">{nodeCount} 节点 · {edgeCount} 边</span>
            </div>
            <button
              type="button"
              onClick={() => setFilters(DEFAULT_FILTERS)}
              className={cn(
                'rounded-md border px-2 py-1 text-[11px] transition-colors',
                filters === DEFAULT_FILTERS
                  ? 'border-outline-variant/40 text-foreground/35'
                  : 'border-outline-variant/60 text-foreground/60 hover:border-primary/35 hover:text-primary',
              )}
            >
              重置过滤
            </button>
          </div>
          <div className="h-[520px]">
            <GraphPayloadViewer
              payload={viewerPayload}
              loading={isLoading}
              error={error}
            />
          </div>
        </div>

        {filteredPayload?.nodes.length ? (
          <div className="grid gap-2 md:grid-cols-2 2xl:grid-cols-3">
            {filteredPayload.nodes.slice(0, 24).map((node) => (
              <button
                key={node.id}
                type="button"
                onClick={() => setSelectedNodeId(node.id)}
                className={cn(
                  'min-w-0 rounded-md border px-3 py-2 text-left transition-colors',
                  selectedNodeId === node.id
                    ? 'border-primary/45 bg-primary/10'
                    : 'border-outline-variant/55 bg-surface-lowest hover:border-primary/30 hover:bg-surface-low',
                )}
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-sm font-medium text-foreground">{node.label}</span>
                  <span className="shrink-0 rounded border border-outline-variant/45 px-1.5 py-0.5 text-[10px] text-foreground/45">
                    {formatNodeType(node.type)}
                  </span>
                </div>
                <div className="mt-1 flex items-center gap-2 text-[11px] text-foreground/45">
                  <span>{formatStatus(node.status)}</span>
                  <span>{node.provenance_refs.length} 证据</span>
                </div>
              </button>
            ))}
          </div>
        ) : null}
      </section>

      <DetailDrawer node={selectedNode} />
    </div>
  );
}
