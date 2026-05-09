import type { DebugChunk, RejectedChunk } from '@/services/chatDebugApi';

interface RetrievalTraceProps {
  rewrittenQuery?: string | null;
  candidates: DebugChunk[];
  selected: DebugChunk[];
  rejected: RejectedChunk[];
}

function scoreLabel(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toFixed(3);
}

function ChunkRow({ chunk, idx, badge }: { chunk: DebugChunk; idx: number; badge?: string }) {
  return (
    <div className="border border-gray-200 rounded-lg p-3 bg-white">
      <div className="flex items-center justify-between gap-2 text-xs text-gray-500 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono">#{idx + 1}</span>
          <span className="truncate">{chunk.source}</span>
          {chunk.section && <span className="truncate text-gray-400">· {chunk.section}</span>}
          {chunk.page !== undefined && chunk.page !== null && (
            <span className="text-gray-400">p.{chunk.page}</span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {badge && (
            <span className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 text-[10px] font-medium">
              {badge}
            </span>
          )}
          <span className="font-mono">score {scoreLabel(chunk.relevance_score)}</span>
        </div>
      </div>
      <p className="text-sm text-gray-800 whitespace-pre-wrap break-words">{chunk.content_preview}</p>
      {chunk.source_labels && chunk.source_labels.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {chunk.source_labels.map((label) => (
            <span key={label} className="px-1.5 py-0.5 text-[10px] rounded bg-gray-100 text-gray-600">
              {label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function RetrievalTrace({ rewrittenQuery, candidates, selected, rejected }: RetrievalTraceProps) {
  const selectedIds = new Set(selected.map((c) => c.chunk_id ?? ''));
  return (
    <div className="space-y-3">
      {rewrittenQuery && (
        <div className="text-xs text-gray-600">
          <span className="font-semibold">Rewritten query:</span> {rewrittenQuery}
        </div>
      )}
      <div className="text-xs text-gray-500">
        Retrieved {candidates.length} · Selected {selected.length} · Rejected {rejected.length}
      </div>
      <div className="space-y-2">
        {candidates.map((chunk, idx) => (
          <ChunkRow
            key={chunk.chunk_id ?? `${idx}`}
            chunk={chunk}
            idx={idx}
            badge={selectedIds.has(chunk.chunk_id ?? '') ? 'selected' : undefined}
          />
        ))}
        {candidates.length === 0 && (
          <p className="text-sm text-gray-500 italic">No candidates returned.</p>
        )}
      </div>
      {rejected.length > 0 && (
        <details className="text-xs text-gray-600">
          <summary className="cursor-pointer">Rejected ({rejected.length})</summary>
          <ul className="mt-2 ml-4 list-disc space-y-1">
            {rejected.map((r) => (
              <li key={r.chunk_id} className="font-mono">
                {r.chunk_id} <span className="text-gray-400">({r.reason})</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
