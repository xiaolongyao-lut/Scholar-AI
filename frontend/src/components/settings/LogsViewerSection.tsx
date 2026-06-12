/**
 * LogsViewerSection — read-only tail of backend.log for the Settings UI.
 *
 * Reads /api/diagnostics/logs with level + search filters and renders a
 * scrollable terminal-like list. Auto-refresh polls every 5s when on; the
 * user can pause polling and copy the tail.
 *
 * Design choices:
 *   - Polls REST instead of SSE: one screen, low traffic, no proxy gymnastics.
 *   - Continuation lines (stack frames) render inline indented under their
 *     parent so tracebacks stay grouped — matches the backend grouping.
 *   - Credentials are already redacted by the backend; we don't try to
 *     re-redact in the frontend.
 *   - No "delete" / "clear" action — log lifecycle is the rotating
 *     handler's job, not the UI's.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import {
  AlertCircle,
  CheckCircle2,
  Copy,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Search,
  ScrollText,
} from 'lucide-react';

import { getApiBaseUrl } from '@/services/apiBaseUrl';

interface LogLineEntry {
  timestamp: string;
  level: string;
  logger_name: string;
  message: string;
  raw: string;
  is_continuation: boolean;
}

interface LogTailResponse {
  file: string;
  file_size_bytes: number;
  total_returned: number;
  truncated: boolean;
  available_files: string[];
  entries: LogLineEntry[];
}

const LEVEL_OPTIONS = [
  { value: '', label: '全部级别' },
  { value: 'DEBUG', label: 'DEBUG+' },
  { value: 'INFO', label: 'INFO+' },
  { value: 'WARNING', label: 'WARNING+' },
  { value: 'ERROR', label: 'ERROR+' },
  { value: 'CRITICAL', label: '只看 CRITICAL' },
];

const TAIL_LINE_OPTIONS = [
  { value: 100, label: '最近 100 行' },
  { value: 200, label: '最近 200 行' },
  { value: 500, label: '最近 500 行' },
  { value: 1000, label: '最近 1000 行' },
  { value: 2000, label: '最近 2000 行（上限）' },
];

const POLL_INTERVAL_MS = 5000;

function levelChipClass(level: string): string {
  switch (level) {
    case 'CRITICAL':
      return 'bg-rose-200 text-rose-900 dark:bg-rose-500/40 dark:text-rose-100';
    case 'ERROR':
      return 'bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300';
    case 'WARNING':
      return 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-200';
    case 'INFO':
      return 'bg-sky-100 text-sky-700 dark:bg-sky-500/20 dark:text-sky-200';
    case 'DEBUG':
      return 'bg-slate-100 text-slate-600 dark:bg-slate-600/40 dark:text-slate-300';
    default:
      return 'bg-slate-100 text-slate-500 dark:bg-slate-700/40 dark:text-slate-400';
  }
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function LogsViewerSection() {
  const [response, setResponse] = useState<LogTailResponse | null>(null);
  const [file, setFile] = useState('backend.log');
  const [level, setLevel] = useState('');
  const [search, setSearch] = useState('');
  const [searchDebounced, setSearchDebounced] = useState('');
  const [lines, setLines] = useState(200);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'ok' | 'fail'>('idle');
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Debounce search input so each keystroke doesn't fire a request.
  useEffect(() => {
    const handle = setTimeout(() => setSearchDebounced(search.trim()), 300);
    return () => clearTimeout(handle);
  }, [search]);

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await axios.get<LogTailResponse>(
        `${getApiBaseUrl()}/api/diagnostics/logs`,
        { params: { name: file, lines, level, search: searchDebounced } },
      );
      setResponse(data);
    } catch (err) {
      const msg = axios.isAxiosError(err)
        ? (err.response?.data?.detail ?? err.message)
        : err instanceof Error ? err.message : String(err);
      setError(`读取日志失败：${msg}`);
    } finally {
      setLoading(false);
    }
  }, [file, lines, level, searchDebounced]);

  useEffect(() => { void fetchLogs(); }, [fetchLogs]);

  useEffect(() => {
    if (!autoRefresh) return;
    const handle = setInterval(() => { void fetchLogs(); }, POLL_INTERVAL_MS);
    return () => clearInterval(handle);
  }, [autoRefresh, fetchLogs]);

  // Auto-scroll to bottom on new tail.
  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [response]);

  const handleCopy = useCallback(async () => {
    if (!response) return;
    const text = response.entries.map((e) => e.raw).join('\n');
    try {
      await navigator.clipboard.writeText(text);
      setCopyState('ok');
      setTimeout(() => setCopyState('idle'), 2000);
    } catch {
      setCopyState('fail');
      setTimeout(() => setCopyState('idle'), 2000);
    }
  }, [response]);

  const filesOptions = useMemo(() => {
    if (!response || response.available_files.length === 0) {
      return [{ value: 'backend.log', label: 'backend.log（当前）' }];
    }
    return response.available_files.map((name, idx) => ({
      value: name,
      label: idx === 0 ? `${name}（当前）` : name,
    }));
  }, [response]);

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-outline-variant/40 bg-surface-lowest p-4">
        <div className="flex items-center justify-between gap-2 mb-3">
          <h3 className="font-headline text-sm font-semibold text-foreground flex items-center gap-2">
            <ScrollText size={16} className="text-primary" />
            后端日志
          </h3>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setAutoRefresh((v) => !v)}
              className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                autoRefresh
                  ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                  : 'bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-200 dark:hover:bg-slate-600'
              }`}
              title={autoRefresh ? '每 5 秒自动刷新中，点击暂停' : '点击开启 5 秒自动刷新'}
            >
              {autoRefresh ? <Pause size={12} /> : <Play size={12} />}
              {autoRefresh ? '正在自动刷新' : '自动刷新'}
            </button>
            <button
              type="button"
              onClick={() => void fetchLogs()}
              disabled={loading}
              className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50 dark:bg-slate-700 dark:text-slate-200 dark:hover:bg-slate-600"
            >
              {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              刷新
            </button>
            <button
              type="button"
              onClick={() => void handleCopy()}
              disabled={!response || response.entries.length === 0}
              className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-40 dark:bg-slate-700 dark:text-slate-200 dark:hover:bg-slate-600"
            >
              {copyState === 'ok' ? <CheckCircle2 size={12} className="text-emerald-500" /> : <Copy size={12} />}
              {copyState === 'ok' ? '已复制' : copyState === 'fail' ? '复制失败' : '复制'}
            </button>
          </div>
        </div>

        <p className="text-[11px] text-foreground/60 leading-relaxed mb-3">
          只读看后端日志，凭据已脱敏。当 chat 出现报错、rerank 回退、检索失败时，这里能看到最近的原因。
          自动刷新每 5 秒拉一次，未开启时不再轮询。
        </p>

        <div className="grid grid-cols-2 gap-2 lg:grid-cols-5">
          <label className="flex flex-col gap-1 text-[11px] text-foreground/60">
            <span>日志文件</span>
            <select
              value={file}
              onChange={(e) => setFile(e.target.value)}
              className="h-8 rounded-md border border-outline-variant bg-surface px-2 text-xs"
            >
              {filesOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-[11px] text-foreground/60">
            <span>级别过滤</span>
            <select
              value={level}
              onChange={(e) => setLevel(e.target.value)}
              className="h-8 rounded-md border border-outline-variant bg-surface px-2 text-xs"
            >
              {LEVEL_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-[11px] text-foreground/60">
            <span>行数</span>
            <select
              value={lines}
              onChange={(e) => setLines(Number(e.target.value))}
              className="h-8 rounded-md border border-outline-variant bg-surface px-2 text-xs"
            >
              {TAIL_LINE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>

          <label className="col-span-2 flex flex-col gap-1 text-[11px] text-foreground/60">
            <span>搜索（在 message 或 logger 名里包含）</span>
            <div className="relative">
              <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-foreground/40" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="例如 rerank / chat / failed"
                className="h-8 w-full rounded-md border border-outline-variant bg-surface pl-7 pr-2 text-xs"
              />
            </div>
          </label>
        </div>

        {response && (
          <div className="mt-3 flex items-center justify-between text-[11px] text-foreground/50">
            <span>
              {response.file} · 文件 {formatBytes(response.file_size_bytes)} · 已显示 {response.total_returned} 行
              {response.truncated && '（仅尾段）'}
            </span>
          </div>
        )}
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700 dark:border-rose-700/40 dark:bg-rose-500/15 dark:text-rose-300">
          <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div
        ref={scrollRef}
        className="max-h-[60vh] overflow-y-auto rounded-lg border border-outline-variant/40 bg-slate-950 p-3 font-mono text-[11px] leading-relaxed text-slate-100"
      >
        {loading && !response ? (
          <p className="italic text-slate-400">正在加载…</p>
        ) : response && response.entries.length === 0 ? (
          <p className="italic text-slate-400">这个区间没有符合条件的日志。</p>
        ) : (
          response?.entries.map((entry, idx) => (
            <div
              key={`${entry.timestamp}-${idx}`}
              className={`flex gap-2 py-0.5 ${entry.is_continuation ? 'pl-8 text-slate-300' : ''}`}
            >
              {!entry.is_continuation && (
                <>
                  <span className="text-slate-500 flex-shrink-0">{entry.timestamp}</span>
                  <span
                    className={`inline-flex h-4 items-center rounded px-1 text-[10px] font-bold flex-shrink-0 ${levelChipClass(entry.level)}`}
                  >
                    {entry.level}
                  </span>
                  <span className="text-slate-400 flex-shrink-0">{entry.logger_name}</span>
                </>
              )}
              <span className="whitespace-pre-wrap break-all">{entry.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
