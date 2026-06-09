import { EvidencePill } from '@/components/evidence/EvidencePill';
import type { SparkEvidenceRef } from '@/types/writing';
import { cn } from '@/lib/utils';

interface SparkEvidencePillsProps {
  /** Evidence refs from a single inspiration spark (D-EVR-1..6). May be
   *  undefined or empty; the component renders nothing in that case so
   *  callers don't need to gate. */
  refs?: SparkEvidenceRef[];
  /** Active project id, used to upgrade chunk_id-only deep-links via
   *  the locator endpoint. Omit when no project context exists;
   *  the deep-link then falls back to page=1. */
  projectId?: string | null;
  className?: string;
}

/**
 * Spark-specific wrapper around the canonical `EvidencePill`.
 *
 * Kept as a named export because the call sites (Inspiration page,
 * Dialog page inspiration-mode panel, Writing/InspirationPanel) all
 * pass a `SparkEvidenceRef[]` shape. The wrapper exists only to:
 *   - Guard the null/empty-array case once at the spark boundary.
 *   - Stamp a stable `key` that tolerates duplicate payloads.
 *
 * Pill rendering, locator upgrade, friendly label, and PDF navigation
 * are all owned by `EvidencePill` now — no inline markup, no separate
 * locator cache, no copy-pasted "打开文献" pill style.
 *
 * Per D-EVR-4 / D-EVR-5: callers must only pass refs that came from
 * real chunk metadata; this wrapper never synthesizes anchors.
 */
export function SparkEvidencePills({ refs, projectId, className }: SparkEvidencePillsProps) {
  if (!refs || refs.length === 0) return null;

  return (
    <div className={cn('flex flex-wrap gap-1.5', className)}>
      {refs.map((ref, index) => (
        <EvidencePill
          key={`${ref.material_id ?? '_'}:${ref.chunk_id ?? '_'}:${index}`}
          evidence={{
            material_id: ref.material_id ?? null,
            chunk_id: ref.chunk_id ?? null,
            page: ref.page ?? null,
            bbox: ref.bbox ?? null,
            bbox_unit: ref.bbox_unit ?? null,
            text: ref.text ?? null,
          }}
          projectId={projectId ?? null}
        />
      ))}
    </div>
  );
}
