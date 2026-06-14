import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Database,
  FileText,
  FolderKanban,
  Hash,
  RefreshCw,
  Search,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import {
  getSourceVaultOverview,
  searchSourceVaultChunks,
  type SourceVaultOverview,
  type SourceVaultSearchResponse,
  type SourceVaultSource,
} from '@/services/sourceVaultApi';

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) {
    return '0 B';
  }
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function shortHash(value: string): string {
  const trimmed = value.trim();
  return trimmed.length > 16 ? `${trimmed.slice(0, 12)}…` : trimmed;
}

function formatSourceStatus(value: SourceVaultSource['storage_status']): string {
  if (value === 'stored') return '已存储';
  if (value === 'referenced') return '仅引用';
  return '缺失';
}

function ErrorNotice({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
      <div className="flex items-center justify-between gap-3">
        <span className="min-w-0">{message}</span>
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded border border-red-300/60 px-2 py-1 text-[11px] hover:bg-red-100 dark:border-red-700/60 dark:hover:bg-red-500/10"
        >
          重试
        </button>
      </div>
    </div>
  );
}

function SourceCard({
  source,
  selected,
  onSelect,
}: {
  source: SourceVaultSource;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'w-full min-w-0 rounded-md border px-3 py-3 text-left transition-colors',
        selected
          ? 'border-primary/45 bg-primary/10'
          : 'border-outline-variant/55 bg-surface-lowest hover:border-primary/30 hover:bg-surface-low',
      )}
    >
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-foreground">{source.title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-foreground/45">
            <span>{source.source_type}</span>
            <span>{formatBytes(source.file_size)}</span>
            <span>{source.project_ids.length} 项目</span>
          </div>
        </div>
        <span className={cn(
          'shrink-0 rounded border px-1.5 py-0.5 text-[10px]',
          source.storage_status === 'stored'
            ? 'border-emerald-300/50 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300'
            : 'border-amber-300/60 bg-amber-500/10 text-amber-700 dark:text-amber-300',
        )}>
          {formatSourceStatus(source.storage_status)}
        </span>
      </div>
      <div className="mt-2 flex min-w-0 items-center gap-1.5 text-[11px] text-foreground/45">
        <Hash size={12} className="shrink-0" />
        <span className="truncate">{shortHash(source.source_hash)}</span>
      </div>
    </button>
  );
}

function SourceDetail({ source }: { source: SourceVaultSource | null }) {
  if (!source) {
    return (
      <aside className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 text-sm text-foreground/45">
        选择一个来源。
      </aside>
    );
  }

  return (
    <aside className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
          <FileText size={17} />
        </div>
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-foreground">{source.title}</h2>
          <p className="mt-1 truncate text-xs text-foreground/45">{source.original_filename}</p>
        </div>
      </div>

      <dl className="mt-4 grid gap-2 text-xs">
        <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
          <dt className="text-foreground/45">来源 ID</dt>
          <dd className="mt-1 break-all font-mono text-[11px] text-foreground/75">{source.source_id}</dd>
        </div>
        <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
          <dt className="text-foreground/45">内容哈希</dt>
          <dd className="mt-1 break-all font-mono text-[11px] text-foreground/75">{source.source_hash}</dd>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
          <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
            <dt className="text-foreground/45">解析器</dt>
            <dd className="mt-1 truncate text-foreground/75">{source.parser_version}</dd>
          </div>
          <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
            <dt className="text-foreground/45">分块器</dt>
            <dd className="mt-1 truncate text-foreground/75">{source.chunker_version}</dd>
          </div>
        </div>
        <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
          <dt className="text-foreground/45">项目链接</dt>
          <dd className="mt-2 flex flex-wrap gap-1.5">
            {source.project_ids.length > 0 ? source.project_ids.map((projectId) => (
              <span key={projectId} className="rounded border border-outline-variant/50 bg-surface-lowest px-2 py-0.5 text-[11px] text-foreground/65">
                {projectId}
              </span>
            )) : (
              <span className="text-foreground/40">暂无项目链接</span>
            )}
          </dd>
        </div>
      </dl>
    </aside>
  );
}

export function SourceVaultPanel() {
  const navigate = useNavigate();
  const [overview, setOverview] = useState<SourceVaultOverview | null>(null);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [searchResult, setSearchResult] = useState<SourceVaultSearchResponse | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const loadOverview = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const next = await getSourceVaultOverview();
      setOverview(next);
      setSelectedSourceId((current) => current && next.sources.some((source) => source.source_id === current)
        ? current
        : next.sources[0]?.source_id ?? null);
    } catch (err: unknown) {
      setOverview(null);
      setError(err instanceof Error ? err.message : '来源库状态读取失败。');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    setIsLoading(true);
    setError(null);
    getSourceVaultOverview()
      .then((next) => {
        if (!mounted) return;
        setOverview(next);
        setSelectedSourceId(next.sources[0]?.source_id ?? null);
      })
      .catch((err: unknown) => {
        if (!mounted) return;
        setOverview(null);
        setError(err instanceof Error ? err.message : '来源库状态读取失败。');
      })
      .finally(() => {
        if (mounted) {
          setIsLoading(false);
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  const selectedSource = useMemo(
    () => overview?.sources.find((source) => source.source_id === selectedSourceId) ?? null,
    [overview, selectedSourceId],
  );

  const handleSearch = useCallback(async () => {
    const normalized = query.trim();
    if (!normalized) {
      setSearchResult(null);
      setSearchError(null);
      return;
    }
    setIsSearching(true);
    setSearchError(null);
    try {
      setSearchResult(await searchSourceVaultChunks(normalized));
    } catch (err: unknown) {
      setSearchResult(null);
      setSearchError(err instanceof Error ? err.message : '来源库搜索失败。');
    } finally {
      setIsSearching(false);
    }
  }, [query]);

  const sourceCount = overview?.total_sources ?? 0;
  const projectLinkCount = overview?.total_project_links ?? 0;
  const sources = overview?.sources ?? [];

  return (
    <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <section className="min-w-0 space-y-4">
        <div className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                <Database size={18} />
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-semibold text-foreground">来源库</h2>
              </div>
            </div>
            <button
              type="button"
              onClick={() => void loadOverview()}
              disabled={isLoading}
              className="inline-flex items-center gap-1.5 self-start rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 text-xs text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-wait disabled:opacity-60"
            >
              <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} />
              刷新
            </button>
          </div>

          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
              <div className="text-[11px] text-foreground/45">来源</div>
              <div className="mt-1 text-sm font-semibold text-foreground">{sourceCount}</div>
            </div>
            <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
              <div className="text-[11px] text-foreground/45">项目链接</div>
              <div className="mt-1 text-sm font-semibold text-foreground">{projectLinkCount}</div>
            </div>
            <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-2">
              <div className="text-[11px] text-foreground/45">全文索引</div>
              <div className="mt-1 text-sm font-semibold text-foreground">{overview?.fts_enabled ? 'FTS5' : 'LIKE'}</div>
            </div>
          </div>
        </div>

        {error ? <ErrorNotice message={error} onRetry={() => void loadOverview()} /> : null}

        <div className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="min-w-0 flex-1">
              <label className="text-[11px] font-medium text-foreground/65" htmlFor="source-vault-search">
                分块检索
              </label>
              <div className="mt-1 flex min-w-0 gap-2">
                <input
                  id="source-vault-search"
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      void handleSearch();
                    }
                  }}
                  placeholder="搜索原文片段"
                  className="min-w-0 flex-1 rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => void handleSearch()}
                  disabled={isSearching || query.trim().length === 0}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Search size={13} />
                  {isSearching ? '搜索中' : '搜索'}
                </button>
              </div>
            </div>
            <div className="text-[11px] text-foreground/45">
              {searchResult ? `${searchResult.results.length} 条片段` : '等待查询'}
            </div>
          </div>

          {searchError ? <div className="mt-3"><ErrorNotice message={searchError} onRetry={() => void handleSearch()} /></div> : null}

          {searchResult?.results.length ? (
            <div className="mt-3 grid gap-2 lg:grid-cols-2">
              {searchResult.results.map((result) => (
                <div
                  key={result.chunk_id}
                  className="min-w-0 rounded-md border border-outline-variant/50 bg-surface-low px-3 py-2 text-left transition-colors hover:border-primary/35 hover:bg-surface-high"
                >
                  <div className="flex min-w-0 items-center gap-2 text-sm font-medium text-foreground">
                    <FileText size={14} className="shrink-0 text-primary/70" />
                    <span className="truncate">{result.title}</span>
                  </div>
                  <div className="mt-1 line-clamp-2 text-xs leading-5 text-foreground/55">{result.text}</div>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <span className="mr-auto text-[10px] text-foreground/40">
                      {result.chunk_id} · #{result.chunk_index}
                    </span>
                    <button
                      type="button"
                      onClick={() => setSelectedSourceId(result.source_id)}
                      className="rounded border border-outline-variant/50 px-2 py-1 text-[11px] text-foreground/60 transition-colors hover:border-primary/35 hover:text-primary"
                    >
                      详情
                    </button>
                    <button
                      type="button"
                      onClick={() => navigate(`/wiki?section=graph&source=${encodeURIComponent(result.source_id)}`)}
                      className="rounded border border-primary/35 bg-primary/10 px-2 py-1 text-[11px] text-primary transition-colors hover:bg-primary/15"
                    >
                      图谱
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <div className="grid gap-2">
          {isLoading ? (
            <div className="rounded-lg border border-outline-variant/60 bg-surface-lowest px-4 py-10 text-center text-sm text-foreground/45">
              正在读取来源库…
            </div>
          ) : sources.length > 0 ? sources.map((source) => (
            <SourceCard
              key={source.source_id}
              source={source}
              selected={source.source_id === selectedSourceId}
              onSelect={() => setSelectedSourceId(source.source_id)}
            />
          )) : (
            <div className="rounded-lg border border-outline-variant/60 bg-surface-lowest px-4 py-10 text-center">
              <FolderKanban size={24} className="mx-auto text-foreground/30" />
              <div className="mt-3 text-sm font-medium text-foreground/60">暂无来源记录</div>
            </div>
          )}
        </div>
      </section>

      <SourceDetail source={selectedSource} />
    </div>
  );
}
