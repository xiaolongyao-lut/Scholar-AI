import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Filter,
  GitBranch,
  RefreshCw,
  Search,
  X,
} from 'lucide-react';

import {
  GraphViewport,
  type GraphViewportSelection,
} from '@/components/graph/GraphViewport';
import { cn } from '@/lib/utils';
import {
  getAnswerEvidenceGraph,
  getProjectEvidenceGraph,
  getWikiEvidenceGraph,
  type EvidenceGraphEdge,
  type EvidenceGraphNode,
  type EvidenceGraphPayload,
  type EvidenceGraphProvenanceRef,
  type EvidenceGraphScopeKind,
  type EvidenceGraphStatus,
} from '@/services/graphApi';

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

function formatConfidence(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${Math.round(value * 100)}%`
    : '未提供';
}

function provenanceLocator(ref: EvidenceGraphProvenanceRef): string {
  const parts = [
    ref.material_id,
    ref.source_id,
    ref.source_vault_id,
    ref.chunk_id,
    ref.source_vault_chunk_id,
    typeof ref.page === 'number' ? `第 ${ref.page} 页` : null,
  ].filter((value): value is string => typeof value === 'string' && value.trim().length > 0);
  return parts.join(' · ') || '未提供来源定位';
}

interface GraphDetailPanelProps {
  node: EvidenceGraphNode | null;
  edge: EvidenceGraphEdge | null;
  nodeLabels: ReadonlyMap<string, string>;
  onClose: () => void;
}

function GraphDetailPanel({ node, edge, nodeLabels, onClose }: GraphDetailPanelProps) {
  const entity = node ?? edge;
  if (!entity) return null;
  const refs = entity.provenance_refs;
  const title = node ? node.label : formatRelation(edge?.relation ?? 'related');

  return (
    <aside
      aria-label={node ? '节点详情' : '关系详情'}
      className="min-h-0 overflow-y-auto border-t border-outline-variant/45 bg-surface-low px-4 py-3 xl:border-l xl:border-t-0"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-foreground/40">
            {node ? '节点详情' : '关系详情'}
          </div>
          <h3 className="mt-1 break-words text-sm font-semibold text-foreground">{title}</h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭图谱详情"
          className="inline-flex size-8 shrink-0 items-center justify-center rounded-sm border border-outline-variant/55 text-foreground/50 transition-colors hover:border-primary/35 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35"
        >
          <X size={14} aria-hidden />
        </button>
      </div>

      <dl className="mt-4 grid grid-cols-[5rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-xs">
        {node ? (
          <>
            <dt className="text-foreground/45">类型</dt>
            <dd className="break-words text-foreground/75">{formatNodeType(node.type)}</dd>
          </>
        ) : (
          <>
            <dt className="text-foreground/45">起点</dt>
            <dd className="break-words text-foreground/75">{nodeLabels.get(edge?.source ?? '') ?? edge?.source}</dd>
            <dt className="text-foreground/45">终点</dt>
            <dd className="break-words text-foreground/75">{nodeLabels.get(edge?.target ?? '') ?? edge?.target}</dd>
            <dt className="text-foreground/45">方向</dt>
            <dd className="text-foreground/75">{edge?.direction === 'undirected' ? '无向' : '有向'}</dd>
          </>
        )}
        <dt className="text-foreground/45">状态</dt>
        <dd className="text-foreground/75">{formatStatus(entity.status)}</dd>
        <dt className="text-foreground/45">置信度</dt>
        <dd className="text-foreground/75">{formatConfidence(entity.confidence)}</dd>
        <dt className="text-foreground/45">证据</dt>
        <dd className="text-foreground/75">{refs.length} 条</dd>
        <dt className="text-foreground/45">标识</dt>
        <dd className="break-all font-mono text-[11px] text-foreground/60">{entity.id}</dd>
      </dl>

      {refs.length > 0 ? (
        <div className="mt-4 border-t border-outline-variant/45 pt-3">
          <h4 className="text-xs font-semibold text-foreground/65">证据定位</h4>
          <ul className="mt-2 space-y-2" aria-label="证据定位">
            {refs.map((ref, index) => (
              <li
                key={`${ref.material_id ?? ref.source_id ?? ref.chunk_id ?? 'ref'}:${index}`}
                className="rounded-sm border border-outline-variant/45 bg-surface-lowest px-2.5 py-2"
              >
                <div className="break-words text-[11px] text-foreground/50">{provenanceLocator(ref)}</div>
                {ref.quote ? (
                  <blockquote className="mt-1.5 line-clamp-4 break-words text-xs leading-5 text-foreground/72">
                    {ref.quote}
                  </blockquote>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="mt-4 border-t border-outline-variant/45 pt-3 text-xs text-foreground/45">
          当前条目没有可用的来源定位。
        </p>
      )}
    </aside>
  );
}

export function EvidenceGraphWorkbench() {
  const [searchParams] = useSearchParams();
  const sourceFilterParam = searchParams.get('source')?.trim() ?? '';
  const routeProjectId = (
    searchParams.get('project_id')
    ?? searchParams.get('project')
    ?? ''
  ).trim();
  const [payload, setPayload] = useState<EvidenceGraphPayload | null>(null);
  const [scopeKind, setScopeKind] = useState<EvidenceGraphScopeKind>('project');
  const [scopeRef, setScopeRef] = useState(routeProjectId);
  const [sessionId, setSessionId] = useState(searchParams.get('session_id')?.trim() ?? '');
  const [turnId, setTurnId] = useState(searchParams.get('turn_id')?.trim() ?? '');
  const [filters, setFilters] = useState<GraphFilters>({
    ...DEFAULT_FILTERS,
    sourceText: sourceFilterParam,
  });
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selection, setSelection] = useState<GraphViewportSelection>(null);

  const loadGraph = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    const normalizedScopeRef = scopeRef.trim();
    const normalizedSessionId = sessionId.trim();
    const normalizedTurnId = turnId.trim();
    if (scopeKind === 'project' && !normalizedScopeRef) {
      setPayload(null);
      setError('请选择项目，或在地址中提供 project_id 后再读取项目文献关联图。');
      setIsLoading(false);
      return;
    }
    if (
      (scopeKind === 'question' || scopeKind === 'smart_read_session')
      && (!normalizedSessionId || !normalizedTurnId)
    ) {
      setPayload(null);
      setError('回答图谱必须同时提供 session_id 和 turn_id；问题文字不能作为图谱键。');
      setIsLoading(false);
      return;
    }
    try {
      const next = scopeKind === 'project'
        ? await getProjectEvidenceGraph({
            project_id: normalizedScopeRef,
            top_k: 4,
            min_similarity: 0.08,
          })
        : scopeKind === 'question' || scopeKind === 'smart_read_session'
          ? await getAnswerEvidenceGraph({
              session_id: normalizedSessionId,
              turn_id: normalizedTurnId,
            })
          : await getWikiEvidenceGraph({
              scope_kind: scopeKind,
              scope_ref: normalizedScopeRef,
            });
      setPayload(next);
    } catch (err: unknown) {
      setPayload(null);
      setError(err instanceof Error ? err.message : '证据图谱读取失败。');
    } finally {
      setIsLoading(false);
    }
  }, [scopeKind, scopeRef, sessionId, turnId]);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  useEffect(() => {
    if (!routeProjectId) return;
    setScopeKind('project');
    setScopeRef(routeProjectId);
  }, [routeProjectId]);

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
  const selectedNode = useMemo(
    () => selection?.kind === 'node'
      ? filteredPayload?.nodes.find((node) => node.id === selection.id) ?? null
      : null,
    [filteredPayload, selection],
  );
  const selectedEdge = useMemo(
    () => selection?.kind === 'edge'
      ? filteredPayload?.edges.find((edge) => edge.id === selection.id) ?? null
      : null,
    [filteredPayload, selection],
  );
  const nodeLabels = useMemo(
    () => new Map((filteredPayload?.nodes ?? []).map((node) => [node.id, node.label])),
    [filteredPayload],
  );

  useEffect(() => {
    if (!selection) return;
    const stillVisible = selection.kind === 'node'
      ? Boolean(filteredPayload?.nodes.some((node) => node.id === selection.id))
      : Boolean(filteredPayload?.edges.some((edge) => edge.id === selection.id));
    if (!stillVisible) setSelection(null);
  }, [filteredPayload, selection]);

  const updateFilter = <K extends keyof GraphFilters,>(key: K, value: GraphFilters[K]) => {
    setFilters((current) => ({ ...current, [key]: value }));
  };

  const nodeCount = filteredPayload?.nodes.length ?? 0;
  const edgeCount = filteredPayload?.edges.length ?? 0;
  const filterChanged = filters.nodeType !== DEFAULT_FILTERS.nodeType
    || filters.relation !== DEFAULT_FILTERS.relation
    || filters.status !== DEFAULT_FILTERS.status
    || filters.evidence !== DEFAULT_FILTERS.evidence
    || filters.minConfidence !== DEFAULT_FILTERS.minConfidence
    || filters.sourceText !== DEFAULT_FILTERS.sourceText;

  return (
    <div className="min-h-0 space-y-2">
      <section className="min-w-0 space-y-2">
        <div className="px-1 py-1">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-sm bg-primary/10 text-primary">
                <GitBranch size={18} />
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-semibold text-foreground">证据图谱</h2>
                <p className="mt-0.5 text-xs text-foreground/50">
                  {nodeCount} 节点 · {edgeCount} 边，选择节点或关系后可查看证据与来源定位。
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => void loadGraph()}
              disabled={isLoading}
              className="inline-flex items-center gap-1.5 self-start rounded-sm border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 text-xs text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-wait disabled:opacity-60"
            >
              <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} />
              刷新
            </button>
          </div>

          <div className="mt-3 grid gap-2 lg:grid-cols-[10rem_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
            <label className="grid gap-1 text-[11px] text-foreground/55">
              <span>范围</span>
              <select
                value={scopeKind}
                onChange={(event) => setScopeKind(event.target.value as EvidenceGraphScopeKind)}
                className="h-9 rounded-sm border border-outline-variant/50 bg-surface-high px-2 text-sm text-foreground focus:border-primary/40 focus:outline-none"
              >
                {SCOPE_KIND_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-[11px] text-foreground/55">
              <span>对象</span>
              <input
                type="text"
                value={scopeRef}
                onChange={(event) => setScopeRef(event.target.value)}
                disabled={scopeKind === 'question' || scopeKind === 'smart_read_session'}
                className="h-9 rounded-sm border border-outline-variant/50 bg-surface-high px-3 text-sm text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
                placeholder={scopeKind === 'project'
                  ? '必填：project_id'
                  : scopeKind === 'question' || scopeKind === 'smart_read_session'
                    ? '由会话与 turn_id 定位'
                    : '留空查看全部'}
              />
            </label>
            <label className="grid gap-1 text-[11px] text-foreground/55">
              <span>会话</span>
              <input
                type="text"
                value={sessionId}
                onChange={(event) => setSessionId(event.target.value)}
                disabled={scopeKind !== 'question' && scopeKind !== 'smart_read_session'}
                className="h-9 rounded-sm border border-outline-variant/50 bg-surface-high px-3 text-sm text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
                placeholder="必填：session_id"
              />
            </label>
            <label className="grid gap-1 text-[11px] text-foreground/55">
              <span>回答轮次</span>
              <input
                type="text"
                value={turnId}
                onChange={(event) => setTurnId(event.target.value)}
                disabled={scopeKind !== 'question' && scopeKind !== 'smart_read_session'}
                className="h-9 rounded-sm border border-outline-variant/50 bg-surface-high px-3 text-sm text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
                placeholder="必填：turn_id"
              />
            </label>
            <button
              type="button"
              onClick={() => void loadGraph()}
              disabled={isLoading}
              className="inline-flex h-9 items-center justify-center gap-1.5 self-end rounded-sm bg-primary px-3 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-wait disabled:opacity-60"
            >
              <Search size={13} />
              查询
            </button>
          </div>
        </div>

        <div className="px-1 py-1">
          <div className="mb-2 flex items-center gap-2 text-xs font-medium text-foreground/70">
            <Filter size={14} />
            <span>过滤器</span>
            <span className="ml-auto text-[11px] text-foreground/40">{nodeCount} 节点 · {edgeCount} 边</span>
          </div>
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-6">
            <select
              aria-label="节点类型"
              value={filters.nodeType}
              onChange={(event) => updateFilter('nodeType', event.target.value)}
              className="h-9 rounded-sm border border-outline-variant/50 bg-surface-high px-2 text-xs text-foreground"
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
              className="h-9 rounded-sm border border-outline-variant/50 bg-surface-high px-2 text-xs text-foreground"
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
              className="h-9 rounded-sm border border-outline-variant/50 bg-surface-high px-2 text-xs text-foreground"
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
              className="h-9 rounded-sm border border-outline-variant/50 bg-surface-high px-2 text-xs text-foreground"
            >
              <option value="all">全部证据</option>
              <option value="with_evidence">有证据</option>
              <option value="without_evidence">无证据</option>
            </select>
            <label className="flex h-9 items-center gap-2 rounded-sm border border-outline-variant/50 bg-surface-high px-2 text-xs text-foreground/65">
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
              className="h-9 rounded-sm border border-outline-variant/50 bg-surface-high px-2 text-xs text-foreground placeholder:text-foreground/30"
            />
          </div>
        </div>

        {payload?.warnings.length ? (
          <div className="rounded-sm border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
            {payload.warnings.join(' ')}
          </div>
        ) : null}

        <div className="overflow-hidden bg-surface-lowest">
          <div className="flex items-center justify-between border-y border-outline-variant/45 px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-foreground">图谱视图</span>
              <span className="text-[10px] text-foreground/45">{nodeCount} 节点 · {edgeCount} 边</span>
            </div>
            <button
              type="button"
              onClick={() => setFilters(DEFAULT_FILTERS)}
              disabled={!filterChanged}
              className={cn(
                'rounded-sm border px-2 py-1 text-[11px] transition-colors',
                filterChanged
                  ? 'border-outline-variant/60 text-foreground/60 hover:border-primary/35 hover:text-primary'
                  : 'cursor-not-allowed border-outline-variant/40 text-foreground/35',
              )}
            >
              重置过滤
            </button>
          </div>
          <div className={cn(
            'grid min-h-[680px]',
            selectedNode || selectedEdge ? 'xl:grid-cols-[minmax(0,1fr)_19rem]' : '',
          )}>
            <div className="h-[680px] min-w-0">
              <GraphViewport
                nodes={filteredPayload?.nodes ?? []}
                edges={filteredPayload?.edges ?? []}
                presentation={scopeKind === 'question' || scopeKind === 'smart_read_session'
                  ? 'cards'
                  : 'network'}
                selection={selection}
                fit={{
                  initially: true,
                  onDataChange: true,
                  requestKey: selection ? `${selection.kind}:${selection.id}` : undefined,
                  padding: 0.16,
                }}
                loading={isLoading}
                error={error}
                ariaLabel="证据图谱只读视图"
                emptyMessage={filterChanged ? '当前筛选没有匹配的节点或关系。' : '当前范围暂无图谱数据。'}
                onNodeSelect={(node) => setSelection({ kind: 'node', id: node.id })}
                onEdgeSelect={(edge) => setSelection({ kind: 'edge', id: edge.id })}
                onSelectionClear={() => setSelection(null)}
                onRetry={() => void loadGraph()}
              />
            </div>
            <GraphDetailPanel
              node={selectedNode}
              edge={selectedEdge}
              nodeLabels={nodeLabels}
              onClose={() => setSelection(null)}
            />
          </div>
        </div>
      </section>
    </div>
  );
}
