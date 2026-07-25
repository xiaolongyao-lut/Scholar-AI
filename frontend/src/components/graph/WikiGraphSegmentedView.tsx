import { useMemo, useState } from 'react';
import { ExternalLink, X } from 'lucide-react';

import { cn } from '@/lib/utils';
import {
  formatWikiError,
  formatWikiPageLabel,
  sanitizeWikiVisibleText,
} from '@/components/wiki/wikiDisplay';
import {
  GraphViewport,
  type GraphViewportFilters,
  type GraphViewportSelection,
} from './GraphViewport';
import type { GraphNavigateTarget } from './GraphPayloadViewer';
import {
  payloadToGraphViewport,
  type GraphEdge,
  type GraphNode,
  type GraphPayloadV0,
} from './payloadToRf';
import { readNodeEvidenceText, readNodeLabel } from './graphEvidenceDisplay';
import {
  assignDimension,
  DIMENSION_META,
  REASONING_DIMENSIONS,
  type ReasoningDimension,
} from './dimensionGraph';
import { useGraphNavigation } from './useGraphNavigation';

export type GraphDensity = 'rail' | 'explorer';
export type GraphSurfaceDomain = 'answer' | 'project' | 'wiki';

interface GraphSegmentedBaseProps {
  payload: GraphPayloadV0 | null;
  domain: GraphSurfaceDomain;
  loading?: boolean;
  error?: string | null;
  className?: string;
  projectId?: string | null;
  onNavigateTarget?: (target: GraphNavigateTarget) => void;
  /** rail = compact context view; explorer = full graph workbench. */
  variant?: GraphDensity;
  /** Argument-dimension filters belong to the outer answer controller. */
  selectedDimensions?: Set<ReasoningDimension>;
  onChangeSelectedDimensions?: (next: Set<ReasoningDimension>) => void;
}

interface WikiGraphSegmentedViewProps extends GraphSegmentedBaseProps {
  domain: 'wiki';
  /** Reserved for the outer Wiki review controller; the viewport never calls it. */
  onReviewApplied?: () => Promise<void> | void;
}

interface ReadOnlyGraphSegmentedViewProps extends GraphSegmentedBaseProps {
  domain: 'answer' | 'project';
  onReviewApplied?: never;
}

type GraphSegmentedViewProps = WikiGraphSegmentedViewProps | ReadOnlyGraphSegmentedViewProps;

function nodeTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    claim: '断言',
    method: '方法',
    dataset: '数据集',
    metric: '指标',
    limitation: '局限',
    concept: '概念',
    material: '文献',
    agent: '智能体',
    evidence: '证据',
  };
  return labels[type] ?? '知识节点';
}

function relationLabel(relation: string): string {
  const labels: Record<string, string> = {
    supports: '支撑',
    contradicts: '反驳',
    extends: '延伸',
    uses: '使用',
    produces: '产生',
    measures: '测量',
    cites: '引用',
    related: '相关',
  };
  return labels[relation] ?? relation;
}

function pagePathFromNode(node: GraphNode): string | null {
  const value = node.metadata?.page_path;
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function DetailPanel({
  node,
  edge,
  nodesById,
  dimension,
  canOpenSource,
  onOpenSource,
  onClose,
}: {
  node: GraphNode | null;
  edge: GraphEdge | null;
  nodesById: ReadonlyMap<string, GraphNode>;
  dimension: ReasoningDimension | null;
  canOpenSource: boolean;
  onOpenSource: () => void;
  onClose: () => void;
}) {
  const pagePath = node ? pagePathFromNode(node) : null;
  const evidenceText = node ? readNodeEvidenceText(node) : null;
  const sourceLabel = edge
    ? readNodeLabel(nodesById.get(edge.source) ?? { id: edge.source, label: edge.source, type: 'concept' })
    : null;
  const targetLabel = edge
    ? readNodeLabel(nodesById.get(edge.target) ?? { id: edge.target, label: edge.target, type: 'concept' })
    : null;
  const edgeEvidence = edge?.evidence_refs?.find((ref) => ref.text)?.text?.trim() || null;

  return (
    <aside
      aria-label={node ? '节点详情' : '关系详情'}
      className="absolute inset-y-3 right-3 z-10 flex w-[min(22rem,calc(100%-1.5rem))] flex-col overflow-hidden rounded-lg border border-outline-variant/60 bg-surface-lowest/97 shadow-xl backdrop-blur-sm"
    >
      <header className="flex items-start justify-between gap-3 border-b border-outline-variant/50 px-3 py-2.5">
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-[0.14em] text-foreground/40">
            {node ? '节点详情' : '关系详情'}
          </div>
          <div className="mt-1 break-words text-sm font-semibold leading-5 text-foreground/85">
            {node ? readNodeLabel(node) : `${sourceLabel ?? ''} → ${targetLabel ?? ''}`}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭详情"
          className="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-foreground/45 transition-colors hover:bg-surface-high hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3 text-xs text-foreground/68">
        {node ? (
          <>
            <div className="flex flex-wrap gap-2">
              <span className="rounded border border-outline-variant/50 bg-surface-low px-2 py-1">
                {nodeTypeLabel(node.type)}
              </span>
              {dimension ? (
                <span className="rounded border border-outline-variant/50 bg-surface-low px-2 py-1">
                  {DIMENSION_META[dimension].label}
                </span>
              ) : null}
              {typeof node.confidence === 'number' ? (
                <span className="rounded border border-outline-variant/50 bg-surface-low px-2 py-1">
                  置信度 {node.confidence.toFixed(2)}
                </span>
              ) : null}
            </div>
            {evidenceText ? (
              <section>
                <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-foreground/38">证据</div>
                <p className="break-words leading-5 text-foreground/72">{evidenceText}</p>
              </section>
            ) : null}
            {pagePath ? (
              <a
                href={`/wiki?page=${encodeURIComponent(pagePath)}`}
                className="inline-flex items-center gap-1.5 text-primary hover:underline"
              >
                {formatWikiPageLabel(pagePath)}
                <ExternalLink className="size-3" aria-hidden />
              </a>
            ) : null}
          </>
        ) : edge ? (
          <>
            <div className="flex flex-wrap gap-2">
              <span className="rounded border border-outline-variant/50 bg-surface-low px-2 py-1">
                {relationLabel(edge.relation)}
              </span>
              <span className="rounded border border-outline-variant/50 bg-surface-low px-2 py-1">
                {edge.direction === 'undirected' ? '无向关系' : '有向关系'}
              </span>
              {typeof edge.confidence === 'number' ? (
                <span className="rounded border border-outline-variant/50 bg-surface-low px-2 py-1">
                  置信度 {edge.confidence.toFixed(2)}
                </span>
              ) : null}
            </div>
            {edgeEvidence ? (
              <section>
                <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-foreground/38">关系证据</div>
                <p className="break-words leading-5 text-foreground/72">
                  {sanitizeWikiVisibleText(edgeEvidence, '关系证据已隐藏。')}
                </p>
              </section>
            ) : null}
          </>
        ) : null}
      </div>

      {node && canOpenSource ? (
        <footer className="border-t border-outline-variant/50 p-3">
          <button
            type="button"
            onClick={onOpenSource}
            className="inline-flex min-h-8 w-full items-center justify-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35"
          >
            打开原文
            <ExternalLink className="size-3.5" aria-hidden />
          </button>
        </footer>
      ) : null}
    </aside>
  );
}

function ArgumentFilters({
  selected,
  onChange,
}: {
  selected: ReadonlySet<ReasoningDimension>;
  onChange: (next: Set<ReasoningDimension>) => void;
}) {
  return (
    <div className="flex min-h-10 flex-wrap items-center gap-1.5 border-b border-outline-variant/45 bg-surface-low px-2.5 py-2">
      <span className="mr-1 text-[10px] uppercase tracking-[0.12em] text-foreground/38">论证角色</span>
      {REASONING_DIMENSIONS.filter((dimension) => dimension !== 'background').map((dimension) => {
        const active = selected.has(dimension);
        return (
          <button
            key={dimension}
            type="button"
            aria-pressed={active}
            onClick={() => {
              const next = new Set(selected);
              if (active) next.delete(dimension);
              else next.add(dimension);
              onChange(next);
            }}
            className={cn(
              'rounded-md border px-2 py-1 text-[10px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30',
              active
                ? 'border-primary/45 bg-primary/10 text-primary'
                : 'border-outline-variant/50 bg-surface-lowest text-foreground/52 hover:border-primary/30 hover:text-foreground/72',
            )}
          >
            {DIMENSION_META[dimension].label}
          </button>
        );
      })}
      {selected.size > 0 ? (
        <button
          type="button"
          onClick={() => onChange(new Set())}
          className="ml-auto rounded-md px-2 py-1 text-[10px] text-foreground/45 hover:bg-surface-high hover:text-foreground/70"
        >
          清除筛选
        </button>
      ) : null}
    </div>
  );
}

/**
 * Domain controller around the shared read-only `GraphViewport`.
 * Answer filters, project/Wiki scope, navigation, and detail state remain here;
 * the canvas owns no Wiki API or mutation state.
 */
export function WikiGraphSegmentedView(props: GraphSegmentedViewProps) {
  const {
    payload,
    domain,
    loading = false,
    error = null,
    className,
    projectId,
    onNavigateTarget,
    variant = 'rail',
    selectedDimensions,
    onChangeSelectedDimensions,
  } = props;
  const { resolveTarget, navigateNode } = useGraphNavigation({ projectId, onNavigateTarget });
  const [internalDimensions, setInternalDimensions] = useState<Set<ReasoningDimension>>(() => new Set());
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);

  const viewportPayload = useMemo(
    () => payload ? payloadToGraphViewport(payload) : { nodes: [], edges: [] },
    [payload],
  );
  const nodesById = useMemo(
    () => new Map(viewportPayload.nodes.map((node) => [node.id, node])),
    [viewportPayload.nodes],
  );
  const edgesById = useMemo(
    () => new Map(viewportPayload.edges.map((edge) => [edge.id, edge])),
    [viewportPayload.edges],
  );
  const dimensionsByNodeId = useMemo(
    () => new Map(viewportPayload.nodes.map((node) => [
      node.id,
      assignDimension(node, viewportPayload.edges).dimension,
    ])),
    [viewportPayload.edges, viewportPayload.nodes],
  );
  const activeDimensions = selectedDimensions ?? internalDimensions;
  const dimensionNodeIds = useMemo(
    () => domain === 'answer' && activeDimensions.size > 0
      ? viewportPayload.nodes
          .filter((node) => activeDimensions.has(dimensionsByNodeId.get(node.id) ?? 'background'))
          .map((node) => node.id)
      : undefined,
    [activeDimensions, dimensionsByNodeId, domain, viewportPayload.nodes],
  );
  const filters = useMemo<GraphViewportFilters | undefined>(
    () => dimensionNodeIds ? { nodeIds: dimensionNodeIds, includeIsolatedNodes: true } : undefined,
    [dimensionNodeIds],
  );
  const selectedNode = selectedNodeId ? nodesById.get(selectedNodeId) ?? null : null;
  const selectedEdge = selectedEdgeId ? edgesById.get(selectedEdgeId) ?? null : null;
  const selection: GraphViewportSelection = selectedNode
    ? { kind: 'node', id: selectedNode.id }
    : selectedEdge
      ? { kind: 'edge', id: selectedEdge.id }
      : null;
  const selectedDimension = selectedNode
    ? dimensionsByNodeId.get(selectedNode.id) ?? null
    : null;
  const canOpenSource = selectedNode ? resolveTarget(selectedNode) !== null : false;
  const visibleError = error ? formatWikiError(error, '加载图谱失败，请稍后重试。') : null;

  const changeDimensions = (next: Set<ReasoningDimension>): void => {
    if (onChangeSelectedDimensions) onChangeSelectedDimensions(next);
    else setInternalDimensions(next);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  };
  const clearSelection = (): void => {
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  };

  return (
    <div
      className={cn('relative flex h-full min-h-0 w-full flex-col overflow-hidden bg-surface-lowest', className)}
      data-graph-domain={domain}
    >
      {domain === 'answer' && variant === 'explorer' ? (
        <ArgumentFilters selected={activeDimensions} onChange={changeDimensions} />
      ) : null}
      <div className="relative min-h-0 flex-1">
        <GraphViewport
          nodes={viewportPayload.nodes}
          edges={viewportPayload.edges}
          presentation={domain === 'answer' ? 'cards' : 'network'}
          selection={selection}
          filters={filters}
          loading={loading}
          error={visibleError}
          emptyMessage={domain === 'answer' ? '当前回答没有可显示的论证关系。' : '当前没有图谱数据。'}
          ariaLabel={domain === 'answer' ? '当前回答论证图谱' : domain === 'project' ? '项目文献关系图谱' : 'Wiki 知识图谱'}
          layoutDirection={domain === 'answer' || viewportPayload.nodes.length <= 18 ? 'horizontal' : 'vertical'}
          fit={{
            padding: variant === 'rail' ? 0.16 : 0.22,
            minZoom: variant === 'rail' ? 0.28 : 0.35,
            maxZoom: variant === 'rail' ? 1.05 : 1.2,
            requestKey: activeDimensions.size,
          }}
          onNodeSelect={(node) => {
            setSelectedNodeId(node.id);
            setSelectedEdgeId(null);
          }}
          onEdgeSelect={(edge) => {
            setSelectedNodeId(null);
            setSelectedEdgeId(edge.id);
          }}
          onSelectionClear={clearSelection}
          onResetFilters={domain === 'answer' ? () => changeDimensions(new Set()) : undefined}
        />
        {!loading && !visibleError && (selectedNode || selectedEdge) ? (
          <DetailPanel
            node={selectedNode}
            edge={selectedEdge}
            nodesById={nodesById}
            dimension={selectedDimension}
            canOpenSource={canOpenSource}
            onOpenSource={() => {
              if (selectedNode) void navigateNode(selectedNode);
            }}
            onClose={clearSelection}
          />
        ) : null}
      </div>
    </div>
  );
}

export default WikiGraphSegmentedView;
