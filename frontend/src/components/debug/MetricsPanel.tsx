import type { DebugMetrics } from '@/services/chatDebugApi';

interface MetricsPanelProps {
  metrics: DebugMetrics;
  traceId: string;
}

function ms(value?: number | null): string {
  if (value === null || value === undefined) return '—';
  return `${value.toFixed(1)} ms`;
}

function tokens(value?: number | null): string {
  if (value === null || value === undefined) return '—';
  return value.toLocaleString();
}

export function MetricsPanel({ metrics, traceId }: MetricsPanelProps) {
  const rows: Array<[string, string]> = [
    ['Trace ID', traceId],
    ['Query rewrite', ms(metrics.query_rewrite_time_ms)],
    ['Retrieval', ms(metrics.retrieval_time_ms)],
    ['Rerank', ms(metrics.rerank_time_ms)],
    ['Prompt build', ms(metrics.prompt_build_time_ms)],
    ['Generation', ms(metrics.generation_time_ms)],
    ['Total', ms(metrics.total_time_ms)],
    ['Input tokens', tokens(metrics.input_tokens)],
    ['Output tokens', tokens(metrics.output_tokens)],
    ['Total tokens', tokens(metrics.total_tokens)],
  ];
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between border-b border-gray-100 py-1">
          <dt className="text-gray-500">{k}</dt>
          <dd className="font-mono text-gray-800 truncate ml-2">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
