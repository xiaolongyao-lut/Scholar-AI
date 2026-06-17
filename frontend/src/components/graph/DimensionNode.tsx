import { Handle, Position, type NodeProps } from '@xyflow/react';

import { cn } from '@/lib/utils';
import { DIMENSION_META, type DimensionGraphNode } from './dimensionGraph';
import {
  DIMENSION_SOURCE_BOTTOM_HANDLE,
  DIMENSION_SOURCE_LEFT_HANDLE,
  DIMENSION_SOURCE_RIGHT_HANDLE,
  DIMENSION_TARGET_LEFT_HANDLE,
  DIMENSION_TARGET_RIGHT_HANDLE,
  DIMENSION_TARGET_TOP_HANDLE,
} from './DimensionBusEdge';

export interface DimensionNodeData extends Record<string, unknown> {
  dimensionEntry: DimensionGraphNode;
}

function formatConfidence(value: number | null): string | null {
  if (value === null || Number.isNaN(value)) return null;
  if (value >= 0 && value <= 1) return `置信 ${(value * 100).toFixed(0)}%`;
  return `置信 ${value.toFixed(2)}`;
}

/**
 * 维度节点：三层结构 — 顶部维度徽标 + 类型；中间标题；底部来源/证据/置信度。
 *
 * 点击行为由父组件 (DimensionGraphViewer) 统一监听 React Flow 的 onNodeClick，
 * 避免自定义节点 DOM click 与 React Flow click 冒泡后重复触发。
 */
export function DimensionNode({ data, selected }: NodeProps) {
  const typed = data as DimensionNodeData;
  const entry = typed.dimensionEntry;
  if (!entry) {
    // 兜底：data 没传期望的字段时也别让 React Flow 崩，渲染一个最小占位节点。
    return (
      <div className="rounded-md border border-outline-variant/60 bg-surface-low px-3 py-2 text-xs text-foreground/45">
        节点信息缺失
      </div>
    );
  }
  const meta = DIMENSION_META[entry.dimension];
  const confidenceText = formatConfidence(entry.display.confidence);
  const isBackground = entry.dimension === 'background';

  return (
    <div
      className={cn(
        'group flex w-full min-w-0 cursor-pointer flex-col gap-1.5 rounded-md border bg-surface-low px-3 py-2 text-foreground transition-shadow',
        selected ? 'shadow-md ring-2 ring-primary/30' : 'shadow-sm hover:shadow-md',
        isBackground && 'opacity-70',
      )}
      style={{
        borderColor: meta.border,
        background: meta.surface,
      }}
      data-dimension={entry.dimension}
      aria-label={`${meta.label}: ${entry.display.title}`}
      title={entry.display.title}
    >
      <Handle id={DIMENSION_TARGET_LEFT_HANDLE} type="target" position={Position.Left} className="!size-1.5 !border-0 !bg-transparent" />
      <Handle id={DIMENSION_SOURCE_LEFT_HANDLE} type="source" position={Position.Left} className="!size-1.5 !border-0 !bg-transparent" />
      <Handle id={DIMENSION_TARGET_TOP_HANDLE} type="target" position={Position.Top} className="!size-1.5 !border-0 !bg-transparent" />
      <div className="flex flex-wrap items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide">
        <span
          className="inline-flex h-4 min-w-4 items-center justify-center rounded-sm px-1 text-[10px] font-semibold text-white"
          style={{ background: meta.accent }}
          title={meta.description}
        >
          {meta.glyph}
        </span>
        <span style={{ color: meta.accent }} className="truncate">
          {meta.label}
        </span>
        <span className="rounded-sm border border-outline-variant/50 px-1 text-foreground/55">
          {entry.display.typeLabel}
        </span>
        {entry.display.status ? (
          <span className="rounded-sm border border-outline-variant/40 px-1 text-foreground/45">
            {entry.display.status}
          </span>
        ) : null}
      </div>
      <div className="line-clamp-3 break-words text-[13px] font-medium leading-[1.4] text-foreground">
        {entry.display.title}
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-foreground/55">
        {entry.display.sourceLabel ? (
          <span className="truncate max-w-[220px]" title={entry.display.sourceLabel}>
            来源 · {entry.display.sourceLabel}
          </span>
        ) : null}
        {entry.display.evidenceCount > 0 ? (
          <span>证据 {entry.display.evidenceCount}</span>
        ) : null}
        {confidenceText ? <span>{confidenceText}</span> : null}
      </div>
      <Handle id={DIMENSION_SOURCE_RIGHT_HANDLE} type="source" position={Position.Right} className="!size-1.5 !border-0 !bg-transparent" />
      <Handle id={DIMENSION_TARGET_RIGHT_HANDLE} type="target" position={Position.Right} className="!size-1.5 !border-0 !bg-transparent" />
      <Handle id={DIMENSION_SOURCE_BOTTOM_HANDLE} type="source" position={Position.Bottom} className="!size-1.5 !border-0 !bg-transparent" />
    </div>
  );
}

export default DimensionNode;
