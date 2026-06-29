import { BookOpenText, FileText, Globe, Wrench } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { locateChunk, type ChunkLocator } from '@/services/resourcesApi';
import { encodePdfBboxParam, type PdfBboxUnit } from '@/lib/pdfAnchor';
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
 * Consumers should pass `material_id`
 * + at least one of `page` / `chunk_id` for a useful click target.
 */
export interface EvidenceRefLike {
  material_id?: string | null;
  chunk_id?: string | null;
  page?: number | null;
  bbox?: number[] | null;
  bbox_unit?: PdfBboxUnit | null;
  text?: string | null;
  source?: string | null;
  /** Optional opaque id for cross-pane selection. */
  evidence_id?: string | null;
  /**
   * B2 (0.1.8.2): provenance classification so the UI can visually
   * distinguish local literature (📄) from web search (🌐) and MCP tool
   * results (🔧). Default 'local' when absent (older payloads).
   */
  source_kind?: 'local' | 'web' | 'mcp' | null;
  /** Project/wiki evidence family from mixed retrieval refs. */
  source_type?: 'project' | 'wiki' | null;
  /** Bounded display title for wiki or project evidence. */
  source_title?: string | null;
  /** Bounded backend path retained for audit, never rendered as visible text. */
  source_path?: string | null;
  /** Weighted project/wiki fusion score. */
  joint_score?: number | null;
  /**
   * 召回路径标签 — 后端给每条 evidence 打的"这条是怎么被选中的"标签
   * (e.g. `sibling` / `dense` / `bm25` / `tolf_text_selector`)。
   * 用于在 chat 里告诉用户这条引用是结构化兄弟召回拉进来的, 还是语义
   * 匹配 / 关键词 / 深度检索得到的。多个标签时取首个有意义的。
   */
  source_labels?: string[] | null;
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
   *  Workbench selection bus. */
  onActivate?: (evidence: EvidenceRefLike) => void;
  /** Workbench can select a pill for focus styling and still follow the
   *  canonical PDF deep-link in the same click. */
  navigateAfterActivate?: boolean;
  className?: string;
  /** Tooltip override; defaults to evidence.text. */
  title?: string;
  /** 是否在 pill 后追加召回路径小 chip (sibling/语义/关键词/深度检索)。
   *  Chat 场景默认开, 其他场景默认关以避免视觉过载。 */
  showSourceLabels?: boolean;
}

/**
 * Friendly Chinese label for each retrieval-path source_label the backend emits.
 * Returns null for labels that are not user-facing (e.g. `project_chunks`,
 * `local_context` — these are container types, not retrieval methods).
 */
function friendlySourceLabel(label: string): string | null {
  switch (label) {
    case 'sibling':
      return '上下文兄弟';
    case 'dense':
      return '语义匹配';
    case 'bm25':
      return '关键词';
    case 'tolf_text_selector':
      return '深度检索';
    case 'rerank':
      return '精排';
    case 'web_search':
      return '网络';
    default:
      return null;
  }
}

/**
 * Pick the most informative source_label to display.
 * Priority: sibling > tolf > dense > bm25 > rerank > others.
 * Falls back to the first label with a Chinese mapping.
 */
function pickPrimarySourceLabel(labels: string[] | null | undefined): string | null {
  if (!labels || labels.length === 0) return null;
  const priority = ['sibling', 'tolf_text_selector', 'dense', 'bm25', 'rerank'];
  for (const key of priority) {
    if (labels.includes(key)) return friendlySourceLabel(key);
  }
  for (const raw of labels) {
    const friendly = friendlySourceLabel(raw);
    if (friendly) return friendly;
  }
  return null;
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
  navigateAfterActivate = false,
  className,
  title,
  showSourceLabels = false,
}: EvidencePillProps) {
  const navigate = useNavigate();

  const handleClick = async () => {
    if (onActivate) {
      onActivate(evidence);
      if (!navigateAfterActivate) return;
    }
    if (!evidence.material_id) return;
    const params = new URLSearchParams();

    let pageNum =
      typeof evidence.page === 'number' && evidence.page > 0 ? evidence.page : NaN;
    let bboxParam = encodePdfBboxParam(evidence.bbox, evidence.bbox_unit);

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
      if (!bboxParam && cached?.bbox) {
        bboxParam = encodePdfBboxParam(cached.bbox, cached.bbox_unit);
      }
    }

    if (Number.isFinite(pageNum) && pageNum > 0) params.set('page', String(pageNum));
    params.set('scope', 'paper');
    params.set('material_id', evidence.material_id);
    params.set('tab', 'reader');
    if (projectId?.trim()) params.set('project_id', projectId.trim());
    if (evidence.chunk_id) params.set('chunk', evidence.chunk_id);
    if (bboxParam) params.set('bbox', bboxParam);
    navigate(`/dialog?${params.toString()}`);
  };

  const label = friendlyLabel(evidence);
  // B2 (0.1.8.2): kind-aware icon + tooltip suffix so users can tell local
  // literature from external web/MCP sources at a glance.
  const sourceType = evidence.source_type ?? 'project';
  const kind = sourceType === 'wiki' ? 'mcp' : evidence.source_kind ?? 'local';
  const KindIcon = sourceType === 'wiki' ? BookOpenText : kind === 'web' ? Globe : kind === 'mcp' ? Wrench : FileText;
  const kindHint =
    sourceType === 'wiki' ? '（Wiki 记忆）' : kind === 'web' ? '（网络搜索）' : kind === 'mcp' ? '（MCP 工具）' : '';
  const jointScore =
    typeof evidence.joint_score === 'number' && Number.isFinite(evidence.joint_score) && evidence.joint_score >= 0
      ? evidence.joint_score
      : null;
  // 召回路径: 当 showSourceLabels=true 时挑首个用户可懂的标签作为 inline 小 chip,
  // 同时把全部 labels (中文版) 拼进 tooltip 让用户能看到完整链路。
  const primarySourceLabel = showSourceLabels
    ? pickPrimarySourceLabel(evidence.source_labels)
    : null;
  const sourceLabelTooltipSuffix = (() => {
    if (!showSourceLabels) return '';
    const labels = evidence.source_labels ?? [];
    if (labels.length === 0) return '';
    const friendly = labels
      .map(friendlySourceLabel)
      .filter((s): s is string => !!s);
    if (friendly.length === 0) return '';
    return ` · 来源: ${friendly.join(' / ')}`;
  })();
  const scoreTooltipSuffix = jointScore === null ? '' : ` · 融合分 ${formatJointScore(jointScore)}`;
  const tooltip =
    (title ?? evidence.text ?? '在文献中打开此证据') +
    kindHint +
    sourceLabelTooltipSuffix +
    scoreTooltipSuffix;

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
          : sourceType === 'wiki'
            ? 'border-emerald-400/40 bg-emerald-500/5 text-emerald-700 hover:border-emerald-500/60 hover:bg-emerald-500/10 dark:border-emerald-400/30 dark:text-emerald-300'
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
      {primarySourceLabel && (
        <span
          className={cn(
            'ml-0.5 inline-flex items-center rounded px-1 py-px text-[10px] font-normal leading-none',
            'border border-outline-variant/60 bg-surface-low/60 text-foreground/55',
          )}
          aria-label={`召回路径: ${primarySourceLabel}`}
          data-source-label={primarySourceLabel}
      >
        {primarySourceLabel}
      </span>
      )}
      {sourceType === 'wiki' && (
        <span
          className="ml-0.5 inline-flex items-center rounded border border-emerald-400/30 bg-emerald-500/10 px-1 py-px text-[10px] font-normal leading-none text-emerald-700 dark:text-emerald-300"
          aria-label="证据来源: Wiki"
        >
          Wiki
        </span>
      )}
      {jointScore !== null && (
        <span
          className="ml-0.5 inline-flex items-center rounded border border-outline-variant/60 bg-surface-low/60 px-1 py-px text-[10px] font-normal leading-none text-foreground/55"
          aria-label={`融合分: ${formatJointScore(jointScore)}`}
        >
          {formatJointScore(jointScore)}
        </span>
      )}
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
  const sourceTitle = (ref.source_title ?? '').trim();
  if (sourceTitle) {
    if (typeof ref.page === 'number' && ref.page > 0) return `${truncate(sourceTitle, 26)} · p.${ref.page}`;
    return truncate(sourceTitle, 32);
  }
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

function formatJointScore(value: number): string {
  if (value >= 1) return value.toFixed(1);
  if (value >= 0.01) return value.toFixed(2);
  return value.toFixed(3);
}
