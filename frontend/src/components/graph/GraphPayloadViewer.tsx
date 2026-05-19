import { useMemo, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  type NodeMouseHandler,
} from '@xyflow/react';

import '@xyflow/react/dist/style.css';

import { layoutWithDagre } from './layoutWithDagre';
import {
  payloadToRf,
  resolveMaterialTarget,
  type GraphNode,
  type GraphPayloadV0,
} from './payloadToRf';

interface GraphPayloadViewerProps {
  payload: GraphPayloadV0 | null;
  loading?: boolean;
  error?: string | null;
  className?: string;
}

function NodeDetailPanel({
  node,
  onClose,
}: {
  node: GraphNode;
  onClose: () => void;
}) {
  const meta = node.metadata ?? {};
  const evidenceText = typeof meta.evidence_text === 'string' ? meta.evidence_text : null;
  const wikiPagePath = typeof meta.page_path === 'string' ? meta.page_path : null;
  return (
    <div className="absolute top-2 right-2 z-10 w-72 max-h-[calc(100%-1rem)] overflow-auto rounded-md border border-outline-variant/60 bg-surface-low shadow-lg">
      <div className="flex items-center justify-between px-3 py-2 border-b border-outline-variant/60">
        <span className="text-xs font-label text-foreground/70 truncate">{node.label}</span>
        <button
          onClick={onClose}
          className="text-[10px] text-foreground/50 hover:text-foreground/80"
        >
          关闭
        </button>
      </div>
      <div className="p-3 space-y-2 text-[11px] text-foreground/80">
        <div>
          <span className="text-foreground/50">类型：</span>
          <span className="font-label">{node.type}</span>
        </div>
        {node.confidence !== undefined && node.confidence !== null && (
          <div>
            <span className="text-foreground/50">置信度：</span>
            <span>{node.confidence.toFixed(2)}</span>
          </div>
        )}
        {wikiPagePath && (
          <div>
            <span className="text-foreground/50">Wiki 页：</span>
            <a
              href={`/wiki?page=${encodeURIComponent(wikiPagePath)}`}
              className="text-blue-700 hover:underline"
            >
              {wikiPagePath}
            </a>
          </div>
        )}
        {evidenceText && (
          <div>
            <div className="text-foreground/50 mb-0.5">证据文本：</div>
            <div className="leading-snug">{evidenceText}</div>
          </div>
        )}
        <details className="pt-1">
          <summary className="cursor-pointer text-foreground/40 hover:text-foreground/60">
            原始 metadata
          </summary>
          <pre className="mt-1 text-[10px] bg-surface-lowest p-2 rounded overflow-auto">
            {JSON.stringify(meta, null, 2)}
          </pre>
        </details>
      </div>
    </div>
  );
}

export function GraphPayloadViewer({
  payload,
  loading,
  error,
  className,
}: GraphPayloadViewerProps) {
  const navigate = useNavigate();
  const [selected, setSelected] = useState<GraphNode | null>(null);

  const { nodes, edges } = useMemo(() => {
    if (!payload) return { nodes: [], edges: [] };
    const rf = payloadToRf(payload);
    return layoutWithDagre(rf.nodes, rf.edges);
  }, [payload]);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_, rfNode) => {
      const raw = rfNode.data?.raw as GraphNode | undefined;
      if (!raw) return;
      const target = resolveMaterialTarget(raw);
      if (target) {
        const params = new URLSearchParams();
        if (target.page) params.set('page', String(target.page));
        if (target.chunk_id) params.set('chunk', target.chunk_id);
        const suffix = params.toString() ? `?${params.toString()}` : '';
        navigate(`/workbench/paper/${encodeURIComponent(target.material_id)}${suffix}`);
        return;
      }
      // No material backing — surface the detail panel instead.
      setSelected(raw);
    },
    [navigate],
  );

  if (loading) {
    return (
      <div className={`flex items-center justify-center h-full text-sm text-foreground/40 ${className ?? ''}`}>
        加载图谱中...
      </div>
    );
  }
  if (error) {
    return (
      <div className={`flex items-center justify-center h-full text-sm text-red-500 ${className ?? ''}`}>
        {error}
      </div>
    );
  }
  if (!payload || payload.nodes.length === 0) {
    return (
      <div className={`flex items-center justify-center h-full text-sm text-foreground/40 ${className ?? ''}`}>
        当前没有图谱数据
      </div>
    );
  }

  return (
    <div className={`relative h-full w-full ${className ?? ''}`}>
      <ReactFlowProvider>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodeClick={onNodeClick}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </ReactFlowProvider>
      {selected && <NodeDetailPanel node={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
