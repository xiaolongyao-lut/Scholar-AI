import { cn } from '@/lib/utils';
import { DimensionGraphViewer, type GraphDensity } from './DimensionGraphViewer';
import type { GraphNavigateTarget } from './GraphPayloadViewer';
import { useGraphNavigation } from './useGraphNavigation';
import { type GraphPayloadV0 } from './payloadToRf';
import type { ReasoningDimension } from './dimensionGraph';

interface WikiGraphSegmentedViewProps {
  payload: GraphPayloadV0 | null;
  loading?: boolean;
  error?: string | null;
  className?: string;
  projectId?: string | null;
  onNavigateTarget?: (target: GraphNavigateTarget) => void;
  /** rail = 右栏轻量预览；explorer = 全宽工作台。默认 rail。 */
  variant?: GraphDensity;
  /** rail 模式下「展开图谱」按钮回调。 */
  onExpand?: () => void;
  /** 受控筛选状态，让 rail 与 explorer 之间、切 tab 之间不丢筛选。 */
  selectedDimensions?: Set<ReasoningDimension>;
  onChangeSelectedDimensions?: (next: Set<ReasoningDimension>) => void;
}

/**
 * 统一维度图谱视图。rail / explorer 两种密度共用同一份 payload 和导航逻辑，
 * 节点点击只选中，跳转只在详情面板「打开原文」触发。
 */
export function WikiGraphSegmentedView({
  payload,
  loading,
  error,
  className,
  projectId,
  onNavigateTarget,
  variant = 'rail',
  onExpand,
  selectedDimensions,
  onChangeSelectedDimensions,
}: WikiGraphSegmentedViewProps) {
  const { navigateNode } = useGraphNavigation({ projectId, onNavigateTarget });

  return (
    <div className={cn('flex h-full min-h-0 w-full', className)}>
      <DimensionGraphViewer
        payload={payload}
        loading={loading}
        error={error}
        density={variant}
        onExpand={onExpand}
        selectedDimensions={selectedDimensions}
        onChangeSelectedDimensions={onChangeSelectedDimensions}
        onOpenSource={(entry) => navigateNode(entry.node)}
      />
    </div>
  );
}

export default WikiGraphSegmentedView;
