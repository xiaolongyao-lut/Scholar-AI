import { useMemo, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

import { GraphViewport, type GraphViewportSelection } from './GraphViewport';
import {
  payloadToGraphViewport,
  resolveMaterialTarget,
  type MaterialTarget,
  type GraphNode,
  type GraphPayloadV0,
  type GraphViewportPayload,
} from './payloadToRf';
import {
  formatWikiError,
  formatWikiPageLabel,
  sanitizeWikiVisibleText,
} from '@/components/wiki/wikiDisplay';
import { locateChunk, type ChunkLocator } from '@/services/resourcesApi';
import { encodePdfBboxParam, type PdfBboxUnit } from '@/lib/pdfAnchor';

interface GraphPayloadViewerProps {
  payload: GraphPayloadV0 | null;
  loading?: boolean;
  error?: string | null;
  className?: string;
  projectId?: string | null;
  /**
   * When provided, node clicks call this with the resolved material target
   * (page/chunk/bbox filled via the chunk locator when available) instead of
   * navigating to the paper route. Used to drive an embedded reader.
   */
  onNavigateTarget?: (target: GraphNavigateTarget) => void;
}

export interface GraphNavigateTarget {
  material_id: string;
  page: number | null;
  chunk_id: string | null;
  bbox: number[] | null;
  bbox_unit?: PdfBboxUnit | null;
}

const graphLocatorCache = new Map<string, ChunkLocator | null>();

function locatorCacheKey(projectId: string, chunkId: string): string {
  return `${projectId}::${chunkId}`;
}

function sanitizeEvidencePreviewText(value: unknown, fallback: string): string {
  const raw = typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '';
  if (!raw) return fallback;
  if (/https?:\/\/|[A-Za-z]:\\|api[_\s-]?key|authorization|bearer|token|secret|env_refs|sha256:/i.test(raw)) {
    return fallback;
  }
  return raw.length > 420 ? `${raw.slice(0, 419)}…` : raw;
}

/** @internal — exposed only for tests. */
export function __resetGraphPayloadViewerCacheForTests(): void {
  graphLocatorCache.clear();
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
  const materialTarget = resolveMaterialTarget(node);
  const firstEvidenceRef = node.evidence_refs?.find((ref) => ref.material_id || ref.text) ?? null;
  const evidencePreview = evidenceText || firstEvidenceRef?.text || null;
  const safeNodeLabel = sanitizeWikiVisibleText(node.label, '知识节点');
  const safeEvidenceText = evidencePreview
    ? sanitizeEvidencePreviewText(evidencePreview, '证据内容已隐藏，避免显示内部路径或系统字段。')
    : null;
  return (
    <div className="absolute top-2 right-2 z-10 w-72 max-h-[calc(100%-1rem)] overflow-auto rounded-md border border-outline-variant/60 bg-surface-low shadow-lg">
      <div className="flex items-center justify-between px-3 py-2 border-b border-outline-variant/60">
        <span className="text-xs font-label text-foreground/70 truncate">{safeNodeLabel}</span>
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
          <span className="font-label">{formatGraphNodeType(node.type)}</span>
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
              className="text-primary hover:underline"
            >
              {formatWikiPageLabel(wikiPagePath)}
            </a>
          </div>
        )}
        {materialTarget && (
          <div>
            <span className="text-foreground/50">定位：</span>
            <span>
              {materialTarget.material_id}
              {materialTarget.page ? ` · p.${materialTarget.page}` : ''}
              {materialTarget.chunk_id ? ` · ${materialTarget.chunk_id}` : ''}
            </span>
          </div>
        )}
        {safeEvidenceText && (
          <div>
            <div className="text-foreground/50 mb-0.5">证据文本：</div>
            <div className="leading-snug">{safeEvidenceText}</div>
          </div>
        )}
        <div className="rounded bg-surface-lowest px-2 py-1.5 text-[10px] text-foreground/45">
          已保留本地诊断信息，普通视图不展开内部字段。
        </div>
      </div>
    </div>
  );
}

function formatGraphNodeType(value: string): string {
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
  return labels[value] ?? '知识节点';
}

export function GraphPayloadViewer({
  payload,
  loading,
  error,
  className,
  projectId,
  onNavigateTarget,
}: GraphPayloadViewerProps) {
  const navigate = useNavigate();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const viewportPayload = useMemo<GraphViewportPayload>(
    () => payload ? payloadToGraphViewport(payload) : { nodes: [], edges: [] },
    [payload],
  );
  const selected = selectedNodeId
    ? viewportPayload.nodes.find((node) => node.id === selectedNodeId) ?? null
    : null;
  const selection = useMemo<GraphViewportSelection>(
    () => selected ? { kind: 'node', id: selected.id } : null,
    [selected],
  );

  const navigateToMaterialTarget = useCallback(async (target: MaterialTarget) => {
    let page = typeof target.page === 'number' && target.page > 0 ? target.page : null;
    let bbox = Array.isArray(target.bbox) && target.bbox.length === 4 ? target.bbox : null;
    let bboxUnit: PdfBboxUnit | null = target.bbox_unit ?? null;
    const normalizedProjectId = typeof projectId === 'string' ? projectId.trim() : '';

    if (target.chunk_id && normalizedProjectId && (!page || !bbox)) {
      const key = locatorCacheKey(normalizedProjectId, target.chunk_id);
      let locator = graphLocatorCache.get(key);
      if (locator === undefined) {
        locator = await locateChunk(target.chunk_id, normalizedProjectId);
        graphLocatorCache.set(key, locator);
      }
      if (locator?.material_id === target.material_id) {
        if (!page && typeof locator.page === 'number' && locator.page > 0) {
          page = locator.page;
        }
        if (!bbox && Array.isArray(locator.bbox) && locator.bbox.length === 4) {
          bbox = locator.bbox;
          bboxUnit = locator.bbox_unit ?? null;
        }
      }
    }

    if (onNavigateTarget) {
      onNavigateTarget({
        material_id: target.material_id,
        page,
        chunk_id: target.chunk_id ?? null,
        bbox,
        bbox_unit: bboxUnit,
      });
      return;
    }

    const params = new URLSearchParams();
    params.set('scope', 'paper');
    params.set('material_id', target.material_id);
    params.set('tab', 'reader');
    if (normalizedProjectId) params.set('project_id', normalizedProjectId);
    if (page) params.set('page', String(page));
    if (target.chunk_id) params.set('chunk', target.chunk_id);
    const bboxParam = encodePdfBboxParam(bbox, bboxUnit);
    if (bboxParam) params.set('bbox', bboxParam);
    navigate(`/dialog?${params.toString()}`);
  }, [navigate, onNavigateTarget, projectId]);

  const onNodeSelect = useCallback((node: GraphNode) => {
    const target = resolveMaterialTarget(node);
    if (target) {
      setSelectedNodeId(null);
      void navigateToMaterialTarget(target);
      return;
    }
    setSelectedNodeId(node.id);
  }, [navigateToMaterialTarget]);
  const viewportError = !loading && error
    ? formatWikiError(error, '加载图谱失败，请稍后重试。')
    : null;

  return (
    <div className={`relative h-full w-full ${className ?? ''}`}>
      <GraphViewport
        nodes={viewportPayload.nodes}
        edges={viewportPayload.edges}
        presentation="cards"
        selection={selection}
        layoutDirection={viewportPayload.nodes.length > 18 ? 'vertical' : 'horizontal'}
        loading={loading}
        error={viewportError}
        emptyMessage="当前没有图谱数据"
        ariaLabel="文献关系图谱"
        fit={{ padding: 0.22, minZoom: 0.35, maxZoom: 1.15 }}
        onNodeSelect={onNodeSelect}
        onSelectionClear={() => setSelectedNodeId(null)}
      />
      {!loading && !viewportError && selected ? (
        <NodeDetailPanel node={selected} onClose={() => setSelectedNodeId(null)} />
      ) : null}
    </div>
  );
}
