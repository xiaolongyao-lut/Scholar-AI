import { FileText, Globe, Wrench } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { locateChunk, type ChunkLocator } from '@/services/resourcesApi';
import { cn } from '@/lib/utils';

/**
 * Process-wide locator cache, keyed by `${projectId}::${chunkId}`.
 *
 * Lifted out of the per-component `useRef` so multiple `EvidencePill`
 * instances rendered for the same evidence share the lookup. This
 * preserves the original `SparkEvidencePills` per-spark cache promise
 * across calls and across remounts within a session.
 *
 * Cache size is bounded by realistic evidence-pill turnover in a
 * session; we don't TTL-expire because the locator response is
 * derived from immutable chunk metadata.
 */
const locatorCache = new Map<string, ChunkLocator | null>();

function cacheKey(projectId: string, chunkId: string): string {
  return `${projectId}::${chunkId}`;
}

/** @internal — exposed only for tests. */
export function __resetEvidencePillCacheForTests(): void {
  locatorCache.clear();
}

/**
 * Canonical evidence reference shape consumed by `EvidencePill`,
 * `EvidenceCard`, and Workbench drawer rows.
 *
 * Designed as a superset of `SparkEvidenceRef` and the legacy
 * `EvidenceReference` (chat) so callers can pass either without
 * adapter code at the call site.
 *
 * Phase 1a contract (Slice 2): consumers SHOULD pass `material_id`
 * + at least one of `page` / `chunk_id` for a useful click target.
 */
export interface EvidenceRefLike {
  material_id?: string | null;
  chunk_id?: string | null;
  page?: number | null;
  text?: string | null;
  source?: string | null;
  /** Optional opaque id for cross-pane selection bus (Slice 3). */
  evidence_id?: string | null;
  /**
   * B2 (0.1.8.2): provenance classification so the UI can visually
   * distinguish local literature (📄) from web search (🌐) and MCP tool
   * results (🔧). Default 'local' when absent (older payloads).
   */
  source_kind?: 'local' | 'web' | 'mcp' | null;
}

interface EvidencePillProps {
  evidence: EvidenceRefLike;
  /** Active project id — used to upgrade a `chunk_id`-only ref to a
   *  page via `/api/resources/chunks/{id}/locator` at click time. */
  projectId?: string | null;
  /** Marks the pill as the focused element of the
   *  pill ↔ drawer row ↔ PDF highlight triple (K4 / MC-4). */
  selected?: boolean;
  /** Override the default Library-route navigation. When provided,
   *  click invokes the handler instead of navigating; useful for the
   *  Workbench selection bus (Slice 3). */
  onActivate?: (evidence: EvidenceRefLike) => void;
  className?: string;
  /** Tooltip override; defaults to evidence.text. */
  title?: string;
}

/**
 * Canonical inline evidence pill. Single source of truth for the
 * "friendly source label + page badge → opens at PDF target" pattern
 * used across Inspiration, Discussion, Wiki, Smart Read, Loose chat.
 *
 * Visual rules (per docs/plans/active/2026-05-16-scholar-workbench-visual-baseline.md):
 *   - Selected pill shares one accent color with its drawer row + PDF highlight.
 *   - Label uses friendly source + page badge; never raw IDs.
 *   - Truncates long text safely.
 *
 * Per IA plan R5 / R5.1: never renders `material_id` / `chunk_id` /
 * other developer identifiers as user-visible text.
 */
export function EvidencePill({
  evidence,
  projectId,
  selected,
  onActivate,
  className,
  title,
}: EvidencePillProps) {
  const navigate = useNavigate();

  const handleClick = async () => {
    if (onActivate) {
      onActivate(evidence);
      return;
    }
    if (!evidence.material_id) return;
    const params = new URLSearchParams();

    let pageNum =
      typeof evidence.page === 'number' && evidence.page > 0 ? evidence.page : NaN;

    if (!(Number.isFinite(pageNum) && pageNum > 0) && evidence.chunk_id && projectId) {
      const key = cacheKey(projectId, evidence.chunk_id);
      let cached: ChunkLocator | null | undefined = locatorCache.get(key);
      if (cached === undefined) {
        cached = await locateChunk(evidence.chunk_id, projectId);
        locatorCache.set(key, cached);
      }
      if (cached && typeof cached.page === 'number' && cached.page > 0) {
        pageNum = cached.page;
      }
    }

    if (Number.isFinite(pageNum) && pageNum > 0) params.set('page', String(pageNum));
    if (evidence.chunk_id) params.set('chunk', evidence.chunk_id);
    const suffix = params.toString() ? `?${params.toString()}` : '';
    navigate(`/workbench/paper/${encodeURIComponent(evidence.material_id)}${suffix}`);
  };

  const label = friendlyLabel(evidence);
  // B2 (0.1.8.2): kind-aware icon + tooltip suffix so users can tell local
  // literature from external web/MCP sources at a glance.
  const kind = evidence.source_kind ?? 'local';
  const KindIcon = kind === 'web' ? Globe : kind === 'mcp' ? Wrench : FileText;
  const kindHint =
    kind === 'web' ? '（网络搜索）' : kind === 'mcp' ? '（MCP 工具）' : '';
  const tooltip = (title ?? evidence.text ?? '在文献中打开此证据') + kindHint;

  return (
    <button
      type="button"
      onClick={() => {
        void handleClick();
      }}
      title={tooltip}
      aria-pressed={selected ? true : undefined}
      data-evidence-id={evidence.evidence_id ?? evidence.chunk_id ?? undefined}
      data-source-kind={kind}
      className={cn(
        'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        selected
          ? 'border-primary bg-primary/10 text-primary'
          : kind === 'web'
            ? 'border-sky-400/40 bg-sky-500/5 text-sky-700 hover:border-sky-500/60 hover:bg-sky-500/10 dark:border-sky-400/30 dark:text-sky-300'
            : kind === 'mcp'
              ? 'border-violet-400/40 bg-violet-500/5 text-violet-700 hover:border-violet-500/60 hover:bg-violet-500/10 dark:border-violet-400/30 dark:text-violet-300'
              : 'border-outline-variant bg-surface-low text-foreground/75 hover:border-primary/60 hover:bg-primary/5 hover:text-foreground',
        className,
      )}
    >
      <KindIcon size={11} className="flex-shrink-0 opacity-70" aria-hidden />
      <span className="max-w-[180px] truncate">{label}</span>
    </button>
  );
}

/**
 * Build a friendly user-facing label.
 *
 * Priority:
 *   1. Trimmed `source` if present (e.g. "Vaswani 2017")
 *   2. Trimmed `text` excerpt (truncated to keep pill compact)
 *   3. Fallback to "证据" — NEVER raw `chunk_id` / `material_id` (R5).
 */
function friendlyLabel(ref: EvidenceRefLike): string {
  const source = (ref.source ?? '').trim();
  if (source) {
    if (typeof ref.page === 'number' && ref.page > 0) return `${truncate(source, 26)} · p.${ref.page}`;
    return truncate(source, 32);
  }
  const text = (ref.text ?? '').trim();
  if (text) return truncate(text, 28);
  return '证据';
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return `${s.slice(0, max - 1)}…`;
}
