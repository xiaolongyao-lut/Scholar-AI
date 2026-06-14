import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, FileText, History, Loader2, RefreshCw, Search } from 'lucide-react';

import { cn } from '@/lib/utils';
import { getWikiReview, searchWiki, WikiApiError } from '@/services/wikiApi';
import { searchSourceVaultChunks } from '@/services/sourceVaultApi';
import type { WikiReviewItemModel, WikiSearchEvidenceRefModel } from '@/types/wiki';

export interface RecallPanelContext {
  /** 当前论文 / 阅读上下文，用于「来自当前论文」检索。 */
  materialTitle?: string;
  /** 当前项目 id，传给源库搜索做范围过滤。 */
  projectId?: string | null;
  /** 写作时的初始关键词（如当前段落 / 选区）。 */
  defaultQuery?: string;
}

interface RecallPanelProps {
  context: RecallPanelContext;
  /** 紧凑度：full 是写作侧栏；compact 是 PDF 侧栏。 */
  density?: 'full' | 'compact';
  /** 跳转到 Wiki 页面（点击「相关沉淀」结果）。 */
  onOpenWikiPage?: (pagePath: string) => void;
  /** 跳转到来源 / 分块（点击「来自当前论文」结果）。 */
  onOpenSourceChunk?: (sourceId: string, chunkIndex: number) => void;
  className?: string;
}

interface RecentSourceChunk {
  sourceId: string;
  title: string;
  chunkIndex: number;
  text: string;
}

interface RecallState {
  query: string;
  wikiResults: WikiSearchEvidenceRefModel[];
  paperResults: RecentSourceChunk[];
  recentInbox: WikiReviewItemModel[];
  isLoadingWiki: boolean;
  isLoadingPaper: boolean;
  isLoadingInbox: boolean;
  wikiError: string | null;
  paperError: string | null;
  inboxError: string | null;
}

const INITIAL_STATE: Omit<RecallState, 'query'> = {
  wikiResults: [],
  paperResults: [],
  recentInbox: [],
  isLoadingWiki: false,
  isLoadingPaper: false,
  isLoadingInbox: false,
  wikiError: null,
  paperError: null,
  inboxError: null,
};

function formatError(err: unknown, fallback: string): string {
  if (err instanceof WikiApiError) return err.message;
  if (err instanceof Error) {
    return err.message === 'Failed to fetch' ? '后端不可达。' : err.message;
  }
  return fallback;
}

/**
 * 紧凑召回面板：把「相关沉淀 / 来自当前论文 / 最近确认」合在一处，
 * 让写作和阅读时不用跳到 KnowledgeDeposits 也能引用已沉淀的知识。
 *
 * 输入：上下文（论文标题 / 项目 / 默认关键词）。
 * 输出：本地搜索框（默认填充 defaultQuery）+ 三段紧凑结果。
 *       不写入任何数据，仅触发既有 GET 接口。
 */
export function RecallPanel({
  context,
  density = 'full',
  onOpenWikiPage,
  onOpenSourceChunk,
  className,
}: RecallPanelProps) {
  const [state, setState] = useState<RecallState>(() => ({
    query: context.defaultQuery ?? '',
    ...INITIAL_STATE,
  }));

  const update = useCallback(<K extends keyof RecallState>(patch: Pick<RecallState, K> | Partial<RecallState>) => {
    setState((prev) => ({ ...prev, ...patch }));
  }, []);

  const runWiki = useCallback(
    async (query: string) => {
      const normalized = query.trim();
      if (!normalized) {
        update({ wikiResults: [], wikiError: null });
        return;
      }
      update({ isLoadingWiki: true, wikiError: null });
      try {
        const result = await searchWiki(normalized);
        update({ wikiResults: result.evidence_refs.slice(0, 6) });
      } catch (err: unknown) {
        update({ wikiResults: [], wikiError: formatError(err, '相关沉淀查询失败。') });
      } finally {
        update({ isLoadingWiki: false });
      }
    },
    [update],
  );

  const runPaper = useCallback(
    async (query: string) => {
      const normalized = query.trim();
      if (!normalized) {
        update({ paperResults: [], paperError: null });
        return;
      }
      update({ isLoadingPaper: true, paperError: null });
      try {
        const result = await searchSourceVaultChunks(normalized, {
          projectId: context.projectId ?? undefined,
          limit: 6,
        });
        const chunks: RecentSourceChunk[] = result.results.map((row) => ({
          sourceId: row.source_id,
          title: row.title,
          chunkIndex: row.chunk_index,
          text: row.text,
        }));
        update({ paperResults: chunks });
      } catch (err: unknown) {
        update({ paperResults: [], paperError: formatError(err, '来源检索失败。') });
      } finally {
        update({ isLoadingPaper: false });
      }
    },
    [context.projectId, update],
  );

  const runInbox = useCallback(async () => {
    update({ isLoadingInbox: true, inboxError: null });
    try {
      const result = await getWikiReview();
      const recent = [...result.items]
        .filter((item) => item.status === 'approved')
        .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
        .slice(0, 5);
      update({ recentInbox: recent });
    } catch (err: unknown) {
      update({ recentInbox: [], inboxError: formatError(err, '收件箱读取失败。') });
    } finally {
      update({ isLoadingInbox: false });
    }
  }, [update]);

  // 初次挂载时把默认查询发出去 + 拉收件箱。
  useEffect(() => {
    void runWiki(state.query);
    void runPaper(state.query);
    void runInbox();
    // 故意只在挂载时跑一次；后续靠搜索框 / 刷新按钮主动触发。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSubmit = () => {
    void runWiki(state.query);
    void runPaper(state.query);
  };

  const titleClass = density === 'compact' ? 'text-[11px]' : 'text-xs';
  const sectionGap = density === 'compact' ? 'gap-2' : 'gap-3';

  const showPaperSection = useMemo(() => Boolean(context.materialTitle || context.projectId), [context.materialTitle, context.projectId]);

  return (
    <section className={cn('rounded-lg border border-outline-variant/60 bg-surface-lowest p-3 shadow-sm', className)}>
      <header className="flex flex-wrap items-center gap-2">
        <span className={cn('font-label font-semibold text-foreground/75', titleClass)}>
          可召回的沉淀
        </span>
        <span className="text-[10px] text-foreground/45">
          写作 / 阅读时直接引用，不用跳到知识沉淀页
        </span>
        <button
          type="button"
          onClick={() => {
            void runWiki(state.query);
            void runPaper(state.query);
            void runInbox();
          }}
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-outline-variant/50 bg-surface-low px-2 py-0.5 text-[10px] text-foreground/65 transition-colors hover:border-primary/30 hover:text-foreground"
          aria-label="刷新召回"
        >
          <RefreshCw size={11} />
          刷新
        </button>
      </header>

      <div className="mt-2 flex gap-2">
        <input
          type="search"
          value={state.query}
          onChange={(event) => update({ query: event.target.value })}
          onKeyDown={(event) => {
            if (event.key === 'Enter') handleSubmit();
          }}
          placeholder={context.defaultQuery ? `按 Enter 重新搜索（默认：${context.defaultQuery}）` : '输入关键词后按 Enter'}
          className="min-w-0 flex-1 rounded-md border border-outline-variant/50 bg-surface-high px-2.5 py-1.5 text-xs text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
        />
        <button
          type="button"
          onClick={handleSubmit}
          className="inline-flex shrink-0 items-center gap-1 rounded-md bg-primary px-2.5 py-1.5 text-[11px] font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          <Search size={11} />
          搜索
        </button>
      </div>

      <div className={cn('mt-3 flex flex-col', sectionGap)}>
        <RecallSection
          icon={<FileText size={13} className="text-primary/70" />}
          title="相关沉淀"
          emptyText={state.wikiError ? state.wikiError : state.query.trim() ? '没有匹配的已沉淀页面。' : '输入关键词后查看 Wiki 已沉淀页面。'}
          loading={state.isLoadingWiki}
        >
          {state.wikiResults.map((ref, index) => {
            const pagePath = typeof ref.page_path === 'string' ? ref.page_path : '';
            return (
              <button
                key={`${pagePath}-${index}`}
                type="button"
                onClick={() => pagePath && onOpenWikiPage?.(pagePath)}
                disabled={!pagePath}
                className="min-w-0 rounded-md border border-outline-variant/50 bg-surface-low px-2.5 py-1.5 text-left transition-colors hover:border-primary/30 hover:bg-surface-high disabled:cursor-default disabled:opacity-70"
              >
                <div className="truncate text-xs font-medium text-foreground">
                  {ref.title || pagePath || 'Wiki 页面'}
                </div>
                {ref.snippet ? (
                  <div className="mt-0.5 line-clamp-2 text-[11px] leading-5 text-foreground/55">
                    {ref.snippet}
                  </div>
                ) : null}
              </button>
            );
          })}
        </RecallSection>

        {showPaperSection ? (
          <RecallSection
            icon={<Activity size={13} className="text-primary/70" />}
            title={context.materialTitle ? `来自当前论文 · ${context.materialTitle}` : '来自当前项目'}
            emptyText={state.paperError ? state.paperError : state.query.trim() ? '没有命中的原文分块。' : '输入关键词后查看原文片段。'}
            loading={state.isLoadingPaper}
          >
            {state.paperResults.map((chunk, index) => (
              <button
                key={`${chunk.sourceId}-${chunk.chunkIndex}-${index}`}
                type="button"
                onClick={() => onOpenSourceChunk?.(chunk.sourceId, chunk.chunkIndex)}
                className="min-w-0 rounded-md border border-outline-variant/50 bg-surface-low px-2.5 py-1.5 text-left transition-colors hover:border-primary/30 hover:bg-surface-high"
              >
                <div className="truncate text-xs font-medium text-foreground">
                  {chunk.title || chunk.sourceId}
                </div>
                <div className="mt-0.5 line-clamp-2 text-[11px] leading-5 text-foreground/55">
                  #{chunk.chunkIndex + 1} · {chunk.text.slice(0, 220)}
                </div>
              </button>
            ))}
          </RecallSection>
        ) : null}

        <RecallSection
          icon={<History size={13} className="text-primary/70" />}
          title="最近确认"
          emptyText={state.inboxError ?? '还没有已确认的沉淀。'}
          loading={state.isLoadingInbox}
        >
          {state.recentInbox.map((item, index) => (
            <div
              key={`${item.item_id || item.page_path || 'inbox'}-${index}`}
              className="min-w-0 rounded-md border border-outline-variant/50 bg-surface-low px-2.5 py-1.5"
            >
              <div className="truncate text-xs font-medium text-foreground">
                {item.title || item.page_path || '已确认条目'}
              </div>
              {item.created_at ? (
                <div className="mt-0.5 text-[10px] text-foreground/45">
                  {item.created_at}
                </div>
              ) : null}
            </div>
          ))}
        </RecallSection>
      </div>
    </section>
  );
}

interface RecallSectionProps {
  icon: React.ReactNode;
  title: string;
  emptyText: string;
  loading: boolean;
  children: React.ReactNode;
}

function RecallSection({ icon, title, emptyText, loading, children }: RecallSectionProps) {
  const items = Array.isArray(children) ? children : children ? [children] : [];
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5">
        {icon}
        <span className="font-label text-[11px] font-medium text-foreground/70">{title}</span>
        {loading ? <Loader2 size={11} className="animate-spin text-foreground/35" /> : null}
      </div>
      {items.length > 0 ? (
        <div className="grid gap-1.5">{children}</div>
      ) : (
        <div className="rounded-md border border-dashed border-outline-variant/50 bg-surface-low px-2.5 py-1.5 text-[11px] leading-5 text-foreground/45">
          {emptyText}
        </div>
      )}
    </div>
  );
}

export default RecallPanel;
