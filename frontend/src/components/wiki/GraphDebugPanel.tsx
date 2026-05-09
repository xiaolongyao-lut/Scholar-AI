import { GitBranch, Network, RefreshCw } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { WikiGraphModel } from '@/types/wiki';

interface GraphDebugPanelProps {
  graph: WikiGraphModel | null;
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
}

export function GraphDebugPanel({ graph, isLoading, error, onRefresh }: GraphDebugPanelProps) {
  const snapshot = graph?.structuredGraph;
  const nodePreview = snapshot?.nodes.slice(0, 4) ?? [];
  const edgePreview = snapshot?.edges.slice(0, 4) ?? [];

  return (
    <section className="glass-card rounded-2xl border border-outline-variant/40 p-5 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="font-label text-[11px] uppercase tracking-[0.22em] text-foreground/35">Graph</div>
          <h2 className="mt-2 font-display text-2xl font-semibold text-foreground">Graph debug 视图</h2>
          <p className="mt-2 max-w-2xl font-body text-sm leading-6 text-foreground/55">
            当前先把 `node_count / edge_count / nodes / edges` 以调试视图露出来；后续真要做图可视化，再看 blast radius 与关系筛选怎样挂进去。
          </p>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="inline-flex items-center gap-2 self-start rounded-xl border border-outline-variant/40 bg-surface-high px-3 py-2 text-xs font-label text-foreground/70 transition-colors hover:border-primary/30 hover:text-foreground disabled:cursor-wait disabled:opacity-60"
        >
          <RefreshCw size={14} className={cn(isLoading && 'animate-spin')} />
          刷新 graph
        </button>
      </div>

      {error ? (
        <div className="mt-5 rounded-xl border border-red-200/80 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      {snapshot ? (
        <>
          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 px-4 py-4">
              <div className="font-label text-[10px] uppercase tracking-[0.18em] text-foreground/35">updated</div>
              <div className="mt-2 text-sm text-foreground/65">{snapshot.updated_at}</div>
            </div>
            <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 px-4 py-4">
              <div className="font-label text-[10px] uppercase tracking-[0.18em] text-foreground/35">nodes</div>
              <div className="mt-2 font-display text-2xl font-semibold text-foreground tabular-nums">{snapshot.node_count}</div>
            </div>
            <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 px-4 py-4">
              <div className="font-label text-[10px] uppercase tracking-[0.18em] text-foreground/35">edges</div>
              <div className="mt-2 font-display text-2xl font-semibold text-foreground tabular-nums">{snapshot.edge_count}</div>
            </div>
          </div>

          <div className="mt-5 grid gap-4 xl:grid-cols-2">
            <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/80 px-4 py-4">
              <div className="flex items-center gap-2 font-label text-[11px] uppercase tracking-[0.18em] text-foreground/35">
                <Network size={13} />
                Node preview
              </div>
              <div className="mt-3 space-y-3">
                {nodePreview.map((node) => (
                  <div key={node.node_id} className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-3">
                    <div className="font-headline text-sm font-semibold text-foreground">{node.title}</div>
                    <div className="mt-1 text-xs text-foreground/55">{node.kind} · {node.status}</div>
                    <div className="mt-2 break-all font-mono text-[11px] leading-5 text-foreground/45">{node.page_path}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/80 px-4 py-4">
              <div className="flex items-center gap-2 font-label text-[11px] uppercase tracking-[0.18em] text-foreground/35">
                <GitBranch size={13} />
                Edge preview
              </div>
              <div className="mt-3 space-y-3">
                {edgePreview.map((edge) => (
                  <div key={edge.edge_id} className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-3">
                    <div className="font-headline text-sm font-semibold text-foreground">{edge.edge_type}</div>
                    <div className="mt-1 text-xs text-foreground/55">{edge.source_id} → {edge.target_id}</div>
                    <div className="mt-1 text-xs text-foreground/45">confidence: {edge.confidence} · weight: {edge.weight}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="mt-5 rounded-2xl border border-outline-variant/30 bg-surface-high/60 px-4 py-8 text-center text-sm text-foreground/45">
          {isLoading ? '正在读取 wiki graph…' : '当前 graph payload 还没有结构化 node/edge 视图。'}
        </div>
      )}
    </section>
  );
}