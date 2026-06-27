import { useCallback, useMemo, useRef, useState } from 'react';
import { CheckCircle2, Copy, ExternalLink, FilePlus2, FolderOpen, RefreshCw, Square } from 'lucide-react';

import { cn } from '@/lib/utils';
import { createWikiImportMarkdown } from '@/services/wikiApi';
import type { WikiImportItemModel, WikiImportResponseModel, WikiManualPageKind, WikiManualPageStatus } from '@/types/wiki';
import { formatWikiError, formatWikiPageLabel, formatWikiWarning } from './wikiDisplay';

interface WikiImportMarkdownPanelProps {
  isWikiEnabled: boolean;
  reviewQueueCount: number;
  onImported?: () => void;
}

function splitSourcePaths(text: string): string[] {
  return text
    .split(/\r?\n|[;,]/g)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function normalizePathInput(value: string): string {
  return value.replace(/\r/g, '').trim();
}

function formatImportStatusLabel(result: WikiImportResponseModel | null): string {
  if (!result) {
    return '等待导入';
  }
  return result.dry_run ? '已生成预案' : '已写入待审草稿';
}

function hasEvidenceLocator(item: WikiImportItemModel): boolean {
  return item.ref_id.length > 0 && item.chunk_id.length > 0 && item.read_endpoint.length > 0;
}

function formatImportSpan(item: WikiImportItemModel): string {
  if (item.span_start === null && item.span_end === null) {
    return 'span 未返回';
  }
  return `span ${item.span_start ?? '?'}-${item.span_end ?? '?'}`;
}

function buildEvidenceLocatorText(item: WikiImportItemModel): string {
  return [
    `ref_id=${item.ref_id}`,
    `chunk_id=${item.chunk_id}`,
    `read_endpoint=${item.read_endpoint}`,
    `span_start=${item.span_start ?? ''}`,
    `span_end=${item.span_end ?? ''}`,
    `source_hash=${item.source_hash}`,
    `content_hash=${item.content_hash}`,
    `import_source_hash=${item.import_source_hash}`,
  ].join('\n');
}

export function WikiImportMarkdownPanel({ isWikiEnabled, reviewQueueCount, onImported }: WikiImportMarkdownPanelProps) {
  const [sourcePathsText, setSourcePathsText] = useState('');
  const [kind, setKind] = useState<WikiManualPageKind>('synthesis');
  const [status, setStatus] = useState<WikiManualPageStatus>('review');
  const [overwrite, setOverwrite] = useState(false);
  const [isDryRun, setIsDryRun] = useState(true);
  const [confirmWrite, setConfirmWrite] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WikiImportResponseModel | null>(null);
  const [sourceHint, setSourceHint] = useState('每行一个 .md 路径，也可以用逗号或分号分隔。');
  const [copiedLocatorId, setCopiedLocatorId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const sourcePaths = useMemo(() => splitSourcePaths(sourcePathsText), [sourcePathsText]);

  const dryRunModeLabel = isDryRun ? '仅生成预案' : '确认写入草稿';
  const actionLabel = isDryRun ? '运行预览' : '写入待审草稿';
  const submitDisabled = !isLoading && (!isWikiEnabled || sourcePaths.length === 0 || (!isDryRun && !confirmWrite));

  const handlePickFiles = useCallback(async () => {
    const picker = window.pywebview?.api?.open_dialog;
    if (!picker) {
      setSourceHint('原生文件选择不可用，请直接粘贴本地 .md 路径。');
      return;
    }
    try {
      const selected = await picker(['Markdown Files (*.md)']);
      const nextPath = normalizePathInput(selected ?? '');
      if (!nextPath) {
        return;
      }
      setSourcePathsText((current) => {
        const merged = new Set(splitSourcePaths(current));
        merged.add(nextPath);
        return Array.from(merged).join('\n');
      });
      setSourceHint('已加入一个本地 Markdown 路径。');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '选择文件失败。');
    }
  }, []);

  const handleRun = useCallback(async () => {
    if (!isWikiEnabled) {
      setError('Wiki 未启用。');
      return;
    }
    const paths = splitSourcePaths(sourcePathsText);
    if (paths.length === 0) {
      setError('请输入至少一个本地 Markdown 路径。');
      return;
    }
    if (!isDryRun && !confirmWrite) {
      setError('确认写入时必须勾选 confirm_write。');
      return;
    }

    setIsLoading(true);
    setError(null);
    setResult(null);
    abortRef.current?.abort();
    const abortController = new AbortController();
    abortRef.current = abortController;
    try {
      const next = await createWikiImportMarkdown(
        {
          source_paths: paths,
          dry_run: isDryRun,
          confirm_write: confirmWrite,
          overwrite,
          kind,
          status,
        },
        isDryRun ? 30000 : 45000,
        { signal: abortController.signal },
      );
      if (abortController.signal.aborted) {
        return;
      }
      setResult(next);
      setSourceHint(next.dry_run ? '预览已完成，检查 review queue 后再确认写入。' : '已写入为待审草稿，等待复审队列批准。');
      if (!next.dry_run) {
        onImported?.();
      }
    } catch (err: unknown) {
      if (abortController.signal.aborted) {
        setError('已停止导入。');
        return;
      }
      setError(err instanceof Error ? formatWikiError(err.message, '本地 Markdown 导入失败。') : '本地 Markdown 导入失败。');
    } finally {
      if (abortRef.current === abortController) {
        abortRef.current = null;
        setIsLoading(false);
      }
    }
  }, [confirmWrite, kind, isDryRun, isWikiEnabled, onImported, overwrite, sourcePathsText, status]);

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsLoading(false);
    setError('已停止导入。');
  }, []);

  const handleCopyEvidenceLocator = useCallback(async (item: WikiImportItemModel) => {
    if (!hasEvidenceLocator(item)) {
      setError('导入结果缺少可复制的证据定位字段。');
      return;
    }
    const writeText = navigator.clipboard?.writeText;
    if (!writeText) {
      setError('当前环境不支持剪贴板复制，请手动复制 read_endpoint。');
      return;
    }
    try {
      await writeText.call(navigator.clipboard, buildEvidenceLocatorText(item));
      setCopiedLocatorId(item.chunk_id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '证据定位复制失败。');
    }
  }, []);

  const pages = result?.pages ?? [];
  const dryRunCount = result ? result.pages.filter((item) => item.action.startsWith('planned')).length : 0;

  return (
    <section className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-foreground">
            <FilePlus2 size={16} className="text-primary/70" />
            <h2 className="font-headline text-base font-semibold">本地 Markdown 导入</h2>
          </div>
          <p className="mt-2 max-w-3xl text-xs leading-6 text-foreground/55">
            先 dry-run，再确认写入。写入结果会进入 private review queue，且保留 runtime recovery 记录。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handlePickFiles}
            disabled={!isWikiEnabled}
            className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 text-xs font-medium text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-not-allowed disabled:opacity-60"
          >
            <FolderOpen size={13} />
            选择文件
          </button>
          <button
            type="button"
            onClick={isLoading ? handleStop : handleRun}
            disabled={submitDisabled}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isLoading ? <Square size={13} /> : <RefreshCw size={13} />}
            {isLoading ? '停止' : actionLabel}
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
        <div className="space-y-3">
          <label className="block text-xs text-foreground/55">
            <span className="font-label text-[11px] text-foreground/45">Markdown 路径</span>
            <textarea
              value={sourcePathsText}
              onChange={(event) => setSourcePathsText(event.target.value)}
              rows={6}
              placeholder="C:\\Users\\xiao\\Desktop\\tools\\Modular-Pipeline-Script\\notes\\draft.md"
              className="mt-1.5 w-full rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm leading-6 text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
            />
          </label>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-xs text-foreground/55">
              <span className="font-label text-[11px] text-foreground/45">导入类型</span>
              <select
                value={kind}
                onChange={(event) => setKind(event.target.value as WikiManualPageKind)}
                className="mt-1.5 w-full rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none"
              >
                <option value="synthesis">综合结论</option>
                <option value="concept">概念</option>
                <option value="exploration">探索记录</option>
                <option value="experiment">实验结果</option>
                <option value="question">问题</option>
                <option value="paper">论文摘要</option>
              </select>
            </label>
            <label className="block text-xs text-foreground/55">
              <span className="font-label text-[11px] text-foreground/45">写入状态</span>
              <select
                value={status}
                onChange={(event) => setStatus(event.target.value as WikiManualPageStatus)}
                className="mt-1.5 w-full rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none"
              >
                <option value="review">待审</option>
                <option value="draft">草稿</option>
                <option value="final">确认知识</option>
              </select>
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <label className="inline-flex items-center gap-2 text-xs text-foreground/65">
              <input type="checkbox" checked={isDryRun} onChange={(event) => setIsDryRun(event.target.checked)} />
              先 dry-run 预览
            </label>
            <label className="inline-flex items-center gap-2 text-xs text-foreground/65">
              <input type="checkbox" checked={confirmWrite} onChange={(event) => setConfirmWrite(event.target.checked)} />
              confirm_write
            </label>
            <label className="inline-flex items-center gap-2 text-xs text-foreground/65">
              <input type="checkbox" checked={overwrite} onChange={(event) => setOverwrite(event.target.checked)} />
              overwrite
            </label>
          </div>

          <div className="rounded-md border border-outline-variant/50 bg-surface-high px-3 py-3 text-xs leading-6 text-foreground/55">
            <div className="font-medium text-foreground/70">{dryRunModeLabel}</div>
            <div className="mt-1">已选 {sourcePaths.length} 个路径 · {reviewQueueCount} 条待审</div>
            <div className="mt-1">{sourceHint}</div>
          </div>
        </div>

        <div className="space-y-3">
          <div className="rounded-md border border-outline-variant/50 bg-surface-high px-3 py-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] text-foreground/45">导入结果</span>
              <span className="text-[11px] text-foreground/55">{formatImportStatusLabel(result)}</span>
            </div>
            <div className="mt-2 grid gap-2 sm:grid-cols-3">
              <div className="rounded-md border border-outline-variant/40 bg-surface-low px-2 py-2">
                <div className="text-[10px] text-foreground/45">导入</div>
                <div className="mt-1 text-sm font-medium text-foreground">{result?.imported ?? 0}</div>
              </div>
              <div className="rounded-md border border-outline-variant/40 bg-surface-low px-2 py-2">
                <div className="text-[10px] text-foreground/45">预览</div>
                <div className="mt-1 text-sm font-medium text-foreground">{dryRunCount}</div>
              </div>
              <div className="rounded-md border border-outline-variant/40 bg-surface-low px-2 py-2">
                <div className="text-[10px] text-foreground/45">错误</div>
                <div className="mt-1 text-sm font-medium text-foreground">{result?.errored ?? 0}</div>
              </div>
            </div>
          </div>

          {error ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
              {formatWikiError(error, '本地 Markdown 导入失败。')}
            </div>
          ) : null}

          {!isDryRun && !confirmWrite ? (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
              确认写入时需要勾选 confirm_write。
            </div>
          ) : null}

          {result?.warnings.length ? (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
              {result.warnings.map((warning) => formatWikiWarning(warning)).join(' ')}
            </div>
          ) : null}

          {result?.pages.length ? (
            <div className="space-y-2">
              {pages.map((item) => (
                <article key={`${item.source_path}-${item.slug}`} className="rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                        <CheckCircle2 size={14} className={cn(item.error ? 'text-red-500' : 'text-emerald-500')} />
                        <span className="truncate">{item.title || formatWikiPageLabel(item.path, item.slug || item.source_path)}</span>
                      </div>
                      <div className="mt-1 text-[11px] text-foreground/45">
                        {item.source_path} · {item.action} · {item.review_item_id}
                      </div>
                    </div>
                    <div className="text-[11px] text-foreground/55">{item.runtime_job_id || '待生成 runtime'}</div>
                  </div>
                  {item.error ? (
                    <div className="mt-2 rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
                      {item.error}
                    </div>
                  ) : null}
                  {hasEvidenceLocator(item) ? (
                    <div className="mt-2 rounded-md border border-outline-variant/40 bg-surface-low px-2 py-2">
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0 space-y-1 text-[11px] leading-5 text-foreground/55">
                          <div className="font-medium text-foreground/70">证据定位</div>
                          <div className="truncate" title={item.ref_id}>ref: {item.ref_id}</div>
                          <div className="truncate" title={item.chunk_id}>chunk: {item.chunk_id}</div>
                          <div>{formatImportSpan(item)}</div>
                          <div className="truncate" title={item.content_hash}>hash: {item.content_hash.slice(0, 12)}</div>
                        </div>
                        <div className="flex shrink-0 flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => void handleCopyEvidenceLocator(item)}
                            className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-high px-2 py-1 text-[11px] font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary"
                            aria-label={`复制证据定位 ${item.chunk_id}`}
                          >
                            <Copy size={12} />
                            {copiedLocatorId === item.chunk_id ? '已复制' : '复制'}
                          </button>
                          <a
                            href={item.read_endpoint}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-high px-2 py-1 text-[11px] font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary"
                            aria-label={`打开 bounded read ${item.ref_id}`}
                          >
                            <ExternalLink size={12} />
                            打开
                          </a>
                        </div>
                      </div>
                      <div className="mt-1 truncate text-[11px] text-foreground/40" title={item.read_endpoint}>
                        {item.read_endpoint}
                      </div>
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
