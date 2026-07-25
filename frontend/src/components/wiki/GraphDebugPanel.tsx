import { useMemo, useState } from 'react';
import { GitBranch, Info, Network, RefreshCw } from 'lucide-react';

import { cn } from '@/lib/utils';
import {
  GraphViewport,
  type GraphViewportEdge,
  type GraphViewportNode,
  type GraphViewportSelection,
} from '@/components/graph/GraphViewport';
import type { WikiGraphEdgeModel, WikiGraphModel, WikiGraphNodeModel, WikiGraphStructuredModel } from '@/types/wiki';
import { formatWikiError, formatWikiPageLabel, sanitizeWikiVisibleText } from './wikiDisplay';
import { resolveWikiGraphRelation } from './wikiGraphRelations';

interface GraphDebugPanelProps {
  graph: WikiGraphModel | null;
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
}

function wikiKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    claim: '断言',
    synthesis: '综合页',
    concept: '概念',
    source: '来源',
    note: '笔记',
  };
  return labels[kind] ?? '其他类型';
}

function wikiStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    draft: '草稿',
    review: '待复审',
    final: '已定稿',
  };
  return labels[status] ?? '未标注状态';
}

function edgeTypeLabel(edgeType: string): string {
  return resolveWikiGraphRelation(edgeType).label;
}

function confidenceLabel(confidence: string): string {
  const labels: Record<string, string> = {
    low: '低',
    medium: '中',
    high: '高',
  };
  return labels[confidence] ?? '未标注';
}

function metadataSummary(metadata: Record<string, unknown>): string {
  const count = Object.keys(metadata).length;
  if (count === 0) return '没有额外诊断信息。';
  return `已记录 ${count} 项图谱诊断信息，普通视图不展开内部字段。`;
}

function wikiPathLabel(path: string | null | undefined): string {
  return formatWikiPageLabel(path, '未命名页面');
}

function edgeEndpointLabel(nodeTitleById: Map<string, string>, nodeId: string, fallbackPath: string | null | undefined): string {
  return sanitizeWikiVisibleText(nodeTitleById.get(nodeId), wikiPathLabel(fallbackPath));
}

interface DebugGraphNode extends GraphViewportNode {
  readonly raw: WikiGraphNodeModel;
}

interface DebugGraphEdge extends GraphViewportEdge {
  readonly raw: WikiGraphEdgeModel;
}

function graphToViewport(
  snapshot: WikiGraphStructuredModel,
): { nodes: DebugGraphNode[]; edges: DebugGraphEdge[] } {
  const nodes: DebugGraphNode[] = snapshot.nodes.map((node) => ({
    id: node.node_id,
    label: sanitizeWikiVisibleText(node.title, wikiPathLabel(node.page_path)),
    type: node.kind || 'concept',
    status: wikiStatusLabel(node.status),
    raw: node,
  }));
  const nodeIds = new Set(snapshot.nodes.map((node) => node.node_id));
  const edges: DebugGraphEdge[] = snapshot.edges
    .filter((edge) => nodeIds.has(edge.source_id) && nodeIds.has(edge.target_id))
    .map((edge) => {
      const { relation, direction } = resolveWikiGraphRelation(edge.edge_type);
      let source = edge.source_id;
      let target = edge.target_id;
      if (direction === 'undirected' && target < source) [source, target] = [target, source];
      return {
        id: edge.edge_id,
        source,
        target,
        relation,
        direction,
        confidence: Number.isFinite(edge.weight) ? Math.min(1, Math.max(0, edge.weight)) : null,
        raw: edge,
      };
    });
  return { nodes, edges };
}

function WikiGraphNodeDetail({ node, onClose }: { node: WikiGraphNodeModel; onClose: () => void }) {
  return (
    <div
      className="absolute right-3 top-3 z-10 w-80 max-w-[calc(100%-1.5rem)] rounded-md border border-outline-variant/60 bg-surface-lowest p-3 shadow-xl"
      data-testid="wiki-graph-node-detail"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-foreground">
            {sanitizeWikiVisibleText(node.title, wikiPathLabel(node.page_path))}
          </div>
          <div className="mt-1 text-[11px] text-foreground/50">
            {wikiKindLabel(node.kind)} · {wikiStatusLabel(node.status)}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded border border-outline-variant/50 px-2 py-0.5 text-[11px] text-foreground/55 hover:bg-surface-high hover:text-foreground"
        >
          关闭
        </button>
      </div>
      <div className="mt-3 space-y-2 text-xs text-foreground/65">
        <div className="break-all">
          <span className="text-foreground/40">页面：</span>
          <a className="text-primary hover:underline" href={`/wiki?page=${encodeURIComponent(node.page_path)}`}>
            {wikiPathLabel(node.page_path)}
          </a>
        </div>
        {node.frontmatter_id ? (
          <div>
            <span className="text-foreground/40">页面元信息：</span>
            <span>已建立索引</span>
          </div>
        ) : null}
        <details>
          <summary className="cursor-pointer text-foreground/45 hover:text-foreground/70">高级诊断摘要</summary>
          <div className="mt-2 rounded bg-surface-low px-2 py-1.5 text-[11px] leading-5 text-foreground/60">
            {metadataSummary(node.metadata)}
          </div>
        </details>
      </div>
    </div>
  );
}

export function GraphDebugPanel({ graph, isLoading, error, onRefresh }: GraphDebugPanelProps) {
  const snapshot = graph?.structuredGraph;
  const [selectedNode, setSelectedNode] = useState<WikiGraphNodeModel | null>(null);
  const viewportGraph = useMemo(() => (snapshot ? graphToViewport(snapshot) : null), [snapshot]);
  const nodePreview = snapshot?.nodes.slice(0, 4) ?? [];
  const edgePreview = snapshot?.edges.slice(0, 4) ?? [];
  const nodeTitleById = useMemo(() => {
    const map = new Map<string, string>();
    for (const node of snapshot?.nodes ?? []) {
      map.set(node.node_id, sanitizeWikiVisibleText(node.title, wikiPathLabel(node.page_path)));
    }
    return map;
  }, [snapshot?.nodes]);
  const selection: GraphViewportSelection = selectedNode
    ? { kind: 'node', id: selectedNode.node_id }
    : null;

  return (
    <section className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="font-label text-[11px] uppercase tracking-[0.22em] text-foreground/35">知识图谱</div>
          <h2 className="mt-2 font-headline text-base font-semibold text-foreground">交互式知识图谱</h2>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="inline-flex items-center gap-2 self-start rounded-md border border-outline-variant/60 bg-surface-low px-3 py-1.5 text-xs font-label text-foreground/70 transition-colors hover:border-primary/30 hover:text-foreground disabled:cursor-wait disabled:opacity-60"
        >
          <RefreshCw size={14} className={cn(isLoading && 'animate-spin')} />
          刷新图谱
        </button>
      </div>

      {error ? (
        <div className="mt-5 rounded-xl border border-red-200/80 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
          {formatWikiError(error, '读取知识图谱失败，请稍后重试。')}
        </div>
      ) : null}

      {snapshot ? (
        <>
          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            <div className="min-w-0 rounded-md border border-outline-variant/50 bg-surface-low px-4 py-3">
              <div className="font-label text-[10px] tracking-[0.14em] text-foreground/35">更新时间</div>
              <div className="mt-2 break-words text-sm text-foreground/65">{sanitizeWikiVisibleText(snapshot.updated_at, '已更新')}</div>
            </div>
            <div className="min-w-0 rounded-md border border-outline-variant/50 bg-surface-low px-4 py-3">
              <div className="font-label text-[10px] tracking-[0.14em] text-foreground/35">节点</div>
              <div className="mt-2 font-display text-2xl font-semibold text-foreground tabular-nums">{snapshot.node_count}</div>
            </div>
            <div className="min-w-0 rounded-md border border-outline-variant/50 bg-surface-low px-4 py-3">
              <div className="font-label text-[10px] tracking-[0.14em] text-foreground/35">关系</div>
              <div className="mt-2 font-display text-2xl font-semibold text-foreground tabular-nums">{snapshot.edge_count}</div>
            </div>
          </div>

          <div className="relative mt-4 h-[420px] overflow-hidden rounded-md border border-outline-variant/60 bg-surface-low" data-testid="wiki-interactive-graph">
            {viewportGraph && viewportGraph.nodes.length > 0 ? (
              <GraphViewport
                nodes={viewportGraph.nodes}
                edges={viewportGraph.edges}
                presentation="network"
                selection={selection}
                ariaLabel="Wiki 图谱调试视图"
                fit={{ padding: 0.2, minZoom: 0.3, maxZoom: 1.2 }}
                onNodeSelect={(node) => setSelectedNode(node.raw)}
                onSelectionClear={() => setSelectedNode(null)}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-foreground/45">
                当前图谱没有可渲染节点。
              </div>
            )}
            {selectedNode ? (
              <WikiGraphNodeDetail node={selectedNode} onClose={() => setSelectedNode(null)} />
            ) : (
              <div className="absolute right-3 top-3 z-10 flex max-w-xs items-center gap-2 rounded-md border border-outline-variant/50 bg-surface-lowest/95 px-3 py-2 text-[11px] text-foreground/55 shadow-sm">
                <Info size={13} className="shrink-0 text-primary/70" />
                点击节点查看详情。
              </div>
            )}
          </div>

          <div className="mt-5 grid gap-4 xl:grid-cols-2">
            <div className="min-w-0 rounded-md border border-outline-variant/50 bg-surface-low px-4 py-4">
              <div className="flex items-center gap-2 font-label text-[11px] tracking-[0.14em] text-foreground/35">
                <Network size={13} />
                节点概览
              </div>
              <div className="mt-3 space-y-3">
                {nodePreview.length ? (
                  nodePreview.map((node) => (
                    <button
                      key={node.node_id}
                      type="button"
                      onClick={() => setSelectedNode(node)}
                      className="w-full rounded-md border border-outline-variant/40 bg-surface-lowest px-3 py-3 text-left transition-colors hover:border-primary/35 hover:bg-surface-high"
                    >
                      <div className="font-headline text-sm font-semibold text-foreground">
                        {sanitizeWikiVisibleText(node.title, wikiPathLabel(node.page_path))}
                      </div>
                      <div className="mt-1 text-xs text-foreground/55">{wikiKindLabel(node.kind)} · {wikiStatusLabel(node.status)}</div>
                      <div className="mt-2 text-[11px] leading-5 text-foreground/45">页面：{wikiPathLabel(node.page_path)}</div>
                    </button>
                  ))
                ) : (
                  <div className="rounded-md border border-outline-variant/40 bg-surface-lowest px-3 py-5 text-sm text-foreground/45">
                    暂无节点。
                  </div>
                )}
              </div>
            </div>

            <div className="min-w-0 rounded-md border border-outline-variant/50 bg-surface-low px-4 py-4">
              <div className="flex items-center gap-2 font-label text-[11px] tracking-[0.14em] text-foreground/35">
                <GitBranch size={13} />
                关系概览
              </div>
              <div className="mt-3 space-y-3">
                {edgePreview.length ? (
                  edgePreview.map((edge) => (
                    <div key={edge.edge_id} className="min-w-0 rounded-md border border-outline-variant/40 bg-surface-lowest px-3 py-3">
                      <div className="font-headline text-sm font-semibold text-foreground">{edgeTypeLabel(edge.edge_type)}</div>
                      <div className="mt-1 break-words text-xs text-foreground/55">
                        {edgeEndpointLabel(nodeTitleById, edge.source_id, edge.source_path)}
                        {resolveWikiGraphRelation(edge.edge_type).direction === 'directed' ? ' → ' : ' — '}
                        {edgeEndpointLabel(nodeTitleById, edge.target_id, edge.target_path)}
                      </div>
                      <div className="mt-1 text-xs text-foreground/45">置信度：{confidenceLabel(edge.confidence)} · 权重：{edge.weight}</div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-md border border-outline-variant/40 bg-surface-lowest px-3 py-5 text-sm text-foreground/45">
                    暂无关系。
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="mt-5 rounded-md border border-outline-variant/50 bg-surface-low px-4 py-8 text-center text-sm text-foreground/45">
          {isLoading ? '正在读取知识图谱…' : '当前图谱还没有结构化节点或关系。'}
        </div>
      )}
    </section>
  );
}
