import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';

interface ChartRendererProps {
  spec: Record<string, unknown> | null | undefined;
  fallbackText?: string;
}

const ALLOWED_KEYS = new Set([
  'title',
  'tooltip',
  'legend',
  'grid',
  'xAxis',
  'yAxis',
  'radar',
  'series',
  'dataset',
  'color',
  'backgroundColor',
  'animation',
]);

function pickAllowed(spec: Record<string, unknown>): EChartsOption {
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(spec)) {
    if (ALLOWED_KEYS.has(key)) {
      out[key] = spec[key];
    }
  }
  return out as EChartsOption;
}

export function ChartRenderer({ spec, fallbackText }: ChartRendererProps) {
  const option = useMemo<EChartsOption | null>(() => {
    if (!spec || typeof spec !== 'object') return null;
    return pickAllowed(spec as Record<string, unknown>);
  }, [spec]);

  if (!option) {
    return (
      <div className="text-sm text-gray-600">
        {fallbackText || 'Chart spec was invalid; showing text fallback.'}
      </div>
    );
  }

  return (
    <div className="w-full">
      <ReactECharts option={option} style={{ height: 320, width: '100%' }} notMerge lazyUpdate />
    </div>
  );
}
