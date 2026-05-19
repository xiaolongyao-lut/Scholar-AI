import { GitBranch, Network, RefreshCw } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { WikiGraphModel } from '@/types/wiki';

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
  return labels[kind] ?? kind;
}

function wikiStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    draft: '草稿',
    review: '待复审',
    final: '已定稿',
  };
  return labels[status] ?? status;
}

function edgeTypeLabel(edgeType: string): string {
  const labels: Record<string, string> = {
    related_to: '相关',
    supports: '支持',
    contradicts: '冲突',
    derives_from: '派生',
    cites: '引用',
    wikilink: '页面链接',
  };
  return labels[edgeType] ?? edgeType;
}

function confidenceLabel(confidence: string): string {
  const labels: Record<string, string> = {
    low: '低',
    medium: '中',
    high: '高',
  };
  return labels[confidence] ?? confidence;
}

export function GraphDebugPanel({ graph, isLoading, error, onRefresh }: GraphDebugPanelProps) {
  const snapshot = graph?.structuredGraph;
  const nodePreview = snapshot?.nodes.slice(0, 4) ?? [];
  const edgePreview = snapshot?.edges.slice(0, 4) ?? [];

  return (
    <section className="glass-card rounded-2xl border border-outline-variant/40 p-5 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="font-label text-[11px] uppercase tracking-[0.22em] text-foreground/35">图谱</div>
          <h2 className="mt-2 font-display text-2xl font-semibold text-foreground">图谱调试视图</h2>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="inline-flex items-center gap-2 self-start rounded-xl border border-outline-variant/40 bg-surface-high px-3 py-2 text-xs font-label text-foreground/70 transition-colors hover:border-primary/30 hover:text-foreground disabled:cursor-wait disabled:opacity-60"
        >
          <RefreshCw size={14} className={cn(isLoading && 'animate-spin')} />
          刷新图谱
        </button>
      </div>

      {error ? (
        <div className="mt-5 rounded-xl border border-red-200/80 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
          {error}
        </div>
      ) : null}

      {snapshot ? (
        <>
          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 px-4 py-4">
              <div className="font-label text-[10px] tracking-[0.14em] text-foreground/35">更新时间</div>
              <div className="mt-2 text-sm text-foreground/65">{snapshot.updated_at}</div>
            </div>
            <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 px-4 py-4">
              <div className="font-label text-[10px] tracking-[0.14em] text-foreground/35">节点</div>
              <div className="mt-2 font-display text-2xl font-semibold text-foreground tabular-nums">{snapshot.node_count}</div>
            </div>
            <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 px-4 py-4">
              <div className="font-label text-[10px] tracking-[0.14em] text-foreground/35">关系</div>
              <div className="mt-2 font-display text-2xl font-semibold text-foreground tabular-nums">{snapshot.edge_count}</div>
            </div>
          </div>

          <div className="mt-5 grid gap-4 xl:grid-cols-2">
            <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/80 px-4 py-4">
              <div className="flex items-center gap-2 font-label text-[11px] tracking-[0.14em] text-foreground/35">
                <Network size={13} />
                节点概览
              </div>
              <div className="mt-3 space-y-3">
                {nodePreview.length ? (
                  nodePreview.map((node) => (
                    <div key={node.node_id} className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-3">
                      <div className="font-headline text-sm font-semibold text-foreground">{node.title}</div>
                      <div className="mt-1 text-xs text-foreground/55">{wikiKindLabel(node.kind)} · {wikiStatusLabel(node.status)}</div>
                      <div className="mt-2 break-all font-mono text-[11px] leading-5 text-foreground/45">{node.page_path}</div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-5 text-sm text-foreground/45">
                    暂无节点。
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/80 px-4 py-4">
              <div className="flex items-center gap-2 font-label text-[11px] tracking-[0.14em] text-foreground/35">
                <GitBranch size={13} />
                关系概览
              </div>
              <div className="mt-3 space-y-3">
                {edgePreview.length ? (
                  edgePreview.map((edge) => (
                    <div key={edge.edge_id} className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-3">
                      <div className="font-headline text-sm font-semibold text-foreground">{edgeTypeLabel(edge.edge_type)}</div>
                      <div className="mt-1 text-xs text-foreground/55">{edge.source_id} → {edge.target_id}</div>
                      <div className="mt-1 text-xs text-foreground/45">置信度：{confidenceLabel(edge.confidence)} · 权重：{edge.weight}</div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-5 text-sm text-foreground/45">
                    暂无关系。
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="mt-5 rounded-2xl border border-outline-variant/30 bg-surface-high/60 px-4 py-8 text-center text-sm text-foreground/45">
          {isLoading ? '正在读取 Wiki 图谱…' : '当前图谱还没有结构化节点或关系。'}
        </div>
      )}
    </section>
  );
}
