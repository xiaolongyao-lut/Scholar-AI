import { AlertTriangle, Eye, FileSearch, RefreshCw, TextQuote } from 'lucide-react';

import { cn } from '@/lib/utils';
import { extractCitationWarnings } from '@/services/wikiApi';
import type { WikiPageDetailModel } from '@/types/wiki';

interface WikiPagePreviewPanelProps {
  selectedPath: string | null;
  page: WikiPageDetailModel | null;
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
}

function formatFrontmatterValue(value: unknown): string {
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.every((item) => typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean')
      ? value.map((item) => String(item)).join(', ')
      : JSON.stringify(value, null, 2);
  }
  if (value && typeof value === 'object') {
    return JSON.stringify(value, null, 2);
  }
  return '—';
}

export function WikiPagePreviewPanel({ selectedPath, page, isLoading, error, onRefresh }: WikiPagePreviewPanelProps) {
  const frontmatterEntries = Object.entries(page?.frontmatter ?? {});
  const citationWarnings = page ? extractCitationWarnings(page) : [];

  return (
    <section className="glass-card rounded-2xl border border-outline-variant/40 p-5 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="font-label text-[11px] uppercase tracking-[0.22em] text-foreground/35">Preview</div>
          <h2 className="mt-2 font-display text-2xl font-semibold text-foreground">Wiki 页面预览</h2>
          <p className="mt-2 max-w-2xl font-body text-sm leading-6 text-foreground/55">
            这里保持 read-only，只展示当前页面的 frontmatter 与正文预览；就算后端暂时离线，也要让错误原因说人话。
          </p>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={!selectedPath || isLoading}
          className="inline-flex items-center gap-2 self-start rounded-xl border border-outline-variant/40 bg-surface-high px-3 py-2 text-xs font-label text-foreground/70 transition-colors hover:border-primary/30 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw size={14} className={cn(isLoading && 'animate-spin')} />
          刷新预览
        </button>
      </div>

      {error ? (
        <div className="mt-5 rounded-xl border border-red-200/80 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      {!selectedPath ? (
        <div className="mt-5 rounded-2xl border border-dashed border-outline-variant/40 bg-surface-lowest/70 px-5 py-10 text-center text-sm text-foreground/50">
          <FileSearch size={20} className="mx-auto text-primary/55" />
          <div className="mt-3 font-medium text-foreground/70">请先在左侧页面列表中选中一个页面</div>
          <p className="mt-2 text-xs leading-6 text-foreground/45">
            选中后，这里会展示 `frontmatter`、正文 body 与当前路径，形成最小 preview 闭环。
          </p>
        </div>
      ) : isLoading ? (
        <div className="mt-5 rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 px-5 py-10 text-center text-sm text-foreground/50">
          正在读取页面预览…
        </div>
      ) : page ? (
        <>
          <div className="mt-5 rounded-2xl border border-outline-variant/30 bg-surface-lowest/75 px-4 py-4">
            <div className="font-label text-[11px] uppercase tracking-[0.18em] text-foreground/35">Selected page</div>
            <div className="mt-2 break-all font-mono text-[11px] leading-5 text-foreground/65">{page.path}</div>
          </div>

          {citationWarnings.length > 0 && (
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4">
              <div className="flex items-center gap-2 text-amber-800">
                <AlertTriangle size={16} />
                <h3 className="font-headline text-sm font-semibold">文内引用与证据预警</h3>
              </div>
              <ul className="mt-3 list-inside list-disc space-y-2 text-sm text-amber-900/80">
                {citationWarnings.map((warning, index) => (
                  <li key={index} className="leading-6">{warning}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/75 p-4">
              <div className="flex items-center gap-2 text-foreground">
                <Eye size={16} className="text-primary/65" />
                <h3 className="font-headline text-sm font-semibold">Frontmatter</h3>
              </div>

              {frontmatterEntries.length ? (
                <div className="mt-4 space-y-3">
                  {frontmatterEntries.map(([key, value]) => (
                    <div key={key} className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-3">
                      <div className="font-label text-[10px] uppercase tracking-[0.18em] text-foreground/35">{key}</div>
                      <pre className="mt-2 whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-foreground/70">
                        {formatFrontmatterValue(value)}
                      </pre>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-4 rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-5 text-sm text-foreground/45">
                  当前页面没有 frontmatter 字段，或者后端返回的是空对象。
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/75 p-4">
              <div className="flex items-center gap-2 text-foreground">
                <TextQuote size={16} className="text-primary/65" />
                <h3 className="font-headline text-sm font-semibold">Body preview</h3>
              </div>

              {page.body.trim() ? (
                <div className="mt-4 max-h-[34rem] overflow-auto rounded-xl border border-outline-variant/30 bg-surface-high/70 px-4 py-4">
                  <pre className="whitespace-pre-wrap break-words font-body text-sm leading-7 text-foreground/80">
                    {page.body}
                  </pre>
                </div>
              ) : (
                <div className="mt-4 rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-5 text-sm text-foreground/45">
                  当前页面正文为空，preview 面仍然保留路径与 frontmatter 信息供人工判断。
                </div>
              )}
            </div>
          </div>
        </>
      ) : (
        <div className="mt-5 rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 px-5 py-10 text-center text-sm text-foreground/50">
          页面预览尚未加载。
        </div>
      )}
    </section>
  );
}
