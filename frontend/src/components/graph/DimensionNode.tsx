import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { CSSProperties } from 'react';
import {
  ArrowRight,
  Eye,
  FileText,
  HelpCircle,
  Layers3,
  Library,
  Shield,
  Workflow,
  XCircle,
  type LucideIcon,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import {
  DIMENSION_META,
  type DimensionGraphNode,
  type ReasoningDimension,
} from './dimensionGraph';
import {
  DIMENSION_SOURCE_BOTTOM_HANDLE,
  DIMENSION_SOURCE_LEFT_HANDLE,
  DIMENSION_SOURCE_RIGHT_HANDLE,
  DIMENSION_SOURCE_TOP_HANDLE,
  DIMENSION_TARGET_BOTTOM_HANDLE,
  DIMENSION_TARGET_LEFT_HANDLE,
  DIMENSION_TARGET_RIGHT_HANDLE,
  DIMENSION_TARGET_TOP_HANDLE,
  type DimensionEdgeDensity,
} from './DimensionBusEdge';

export interface DimensionNodeData extends Record<string, unknown> {
  dimensionEntry: DimensionGraphNode;
  density?: DimensionEdgeDensity;
  performanceMode?: boolean;
}

const DIMENSION_ICONS: Record<ReasoningDimension, LucideIcon> = {
  question: HelpCircle,
  observation: Eye,
  mechanism: Workflow,
  evidence: Library,
  boundary: Shield,
  counter_evidence: XCircle,
  next_action: ArrowRight,
  background: Layers3,
};

const HANDLE_CLASS = '!pointer-events-none !size-px !min-h-px !min-w-px !border-0 !bg-transparent !opacity-0';
const HORIZONTAL_HANDLE_STYLE: CSSProperties = {
  width: 1,
  height: 1,
  minWidth: 1,
  minHeight: 1,
  transform: 'translateY(-50%)',
};
const VERTICAL_HANDLE_STYLE: CSSProperties = {
  width: 1,
  height: 1,
  minWidth: 1,
  minHeight: 1,
  transform: 'translateX(-50%)',
};

function DimensionHandles() {
  return (
    <>
      <Handle id={DIMENSION_TARGET_LEFT_HANDLE} type="target" position={Position.Left} className={HANDLE_CLASS} style={HORIZONTAL_HANDLE_STYLE} />
      <Handle id={DIMENSION_SOURCE_LEFT_HANDLE} type="source" position={Position.Left} className={HANDLE_CLASS} style={HORIZONTAL_HANDLE_STYLE} />
      <Handle id={DIMENSION_TARGET_TOP_HANDLE} type="target" position={Position.Top} className={HANDLE_CLASS} style={VERTICAL_HANDLE_STYLE} />
      <Handle id={DIMENSION_SOURCE_TOP_HANDLE} type="source" position={Position.Top} className={HANDLE_CLASS} style={VERTICAL_HANDLE_STYLE} />
      <Handle id={DIMENSION_SOURCE_RIGHT_HANDLE} type="source" position={Position.Right} className={HANDLE_CLASS} style={HORIZONTAL_HANDLE_STYLE} />
      <Handle id={DIMENSION_TARGET_RIGHT_HANDLE} type="target" position={Position.Right} className={HANDLE_CLASS} style={HORIZONTAL_HANDLE_STYLE} />
      <Handle id={DIMENSION_SOURCE_BOTTOM_HANDLE} type="source" position={Position.Bottom} className={HANDLE_CLASS} style={VERTICAL_HANDLE_STYLE} />
      <Handle id={DIMENSION_TARGET_BOTTOM_HANDLE} type="target" position={Position.Bottom} className={HANDLE_CLASS} style={VERTICAL_HANDLE_STYLE} />
    </>
  );
}

function formatConfidence(value: number | null): string | null {
  if (value === null || Number.isNaN(value)) return null;
  if (value >= 0 && value <= 1) return `置信 ${(value * 100).toFixed(0)}%`;
  return `置信 ${value.toFixed(2)}`;
}

/**
 * 维度节点只保留用于扫描的核心信息；证据摘录留在选中详情中展示。
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
  const DimensionIcon = DIMENSION_ICONS[entry.dimension];
  const confidenceText = formatConfidence(entry.display.confidence);
  const isBackground = entry.dimension === 'background';

  return (
    <div
      className={cn(
        'nodrag nopan group relative flex h-full w-full min-w-0 cursor-pointer flex-col gap-1.5 overflow-hidden rounded-md border bg-surface-lowest px-3 py-2.5 pl-3.5 text-foreground transition-[border-color,box-shadow,transform] duration-150',
        typed.performanceMode
          ? selected
            ? 'border-primary ring-2 ring-primary/20'
            : 'border-outline-variant/80 hover:border-outline'
          : selected
            ? 'border-primary shadow-md ring-2 ring-primary/25'
            : 'border-outline-variant/80 shadow-sm hover:border-outline hover:shadow-md',
        typed.performanceMode && 'transition-none',
        isBackground && 'opacity-75',
      )}
      data-dimension={entry.dimension}
      data-density={typed.density ?? 'comfortable'}
      aria-label={`${meta.label}: ${entry.display.title}`}
      title={entry.display.title}
    >
      <DimensionHandles />
      <span
        aria-hidden
        className="absolute inset-y-2 left-0 w-[3px] rounded-r-sm"
        style={{ background: meta.accent }}
      />
      <div className="flex min-w-0 items-center gap-1.5 text-[11px] font-medium">
        <span
          className="inline-flex size-[18px] shrink-0 items-center justify-center rounded-sm border"
          style={{ background: meta.surface, borderColor: meta.border, color: meta.accent }}
          title={meta.description}
        >
          <DimensionIcon className="size-3" aria-hidden />
        </span>
        <span style={{ color: meta.accent }} className="shrink-0">
          {meta.label}
        </span>
        <span className="min-w-0 truncate text-foreground/42">{entry.display.typeLabel}</span>
        {entry.display.status ? (
          <span className="ml-auto shrink-0 rounded-sm bg-surface-high px-1 text-[10px] text-foreground/55">
            {entry.display.status}
          </span>
        ) : null}
      </div>
      <div className="line-clamp-2 min-w-0 break-words text-[13px] font-medium leading-[18px] text-foreground">
        {entry.display.title}
      </div>
      <div className="mt-auto flex min-w-0 items-center gap-2 overflow-hidden text-[10px] text-foreground/52">
        {entry.display.sourceLabel ? (
          <span className="flex min-w-0 items-center gap-1 truncate" title={entry.display.sourceLabel}>
            <FileText className="size-3 shrink-0" aria-hidden />
            <span className="truncate">{entry.display.sourceLabel}</span>
          </span>
        ) : null}
        {entry.display.evidenceCount > 0 ? (
          <span className="shrink-0">证据 {entry.display.evidenceCount}</span>
        ) : null}
        {confidenceText ? <span className="ml-auto shrink-0">{confidenceText}</span> : null}
      </div>
    </div>
  );
}

export default DimensionNode;
