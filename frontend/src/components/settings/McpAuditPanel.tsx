/**
 * McpAuditPanel — tail the MCP tool-call audit log with frontend-only filters.
 *
 * Per `docs/plans/active/2026-05-16-mcp-tool-use-ux-plan.md` D-MCPUX-7:
 * - Calls `/api/mcp/audit?limit=500` once per refresh; no backend query API.
 * - Filters apply on the loaded slice: server / tool name substring /
 *   capability tag (when present) / blocked-or-error vs ok / time window.
 * - Backend already redacts `preview` text; this panel never re-fetches
 *   raw env or header values.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, AlertTriangle, CheckCircle2, ShieldAlert } from 'lucide-react';
import {
  listMcpAuditRecords,
  type McpAuditRecord,
  type McpToolCapability,
} from '@/services/mcpApi';

const CAPABILITY_OPTIONS: Array<McpToolCapability | 'all'> = [
  'all',
  'read',
  'write',
  'network',
  'filesystem',
  'destructive',
  'unknown',
];

// 用户视角的能力分类中文名。enum 值保留在 value，避免触动后端契约。
const CAPABILITY_LABELS_ZH: Record<McpToolCapability | 'all', string> = {
  all: '全部能力',
  read: '只读',
  write: '写入',
  network: '网络',
  filesystem: '本地文件',
  destructive: '危险操作',
  unknown: '未分类',
};

/** 把后端返回的英文 blocked_reason 收敛成一行人话；详情仍可展开看原文。 */
function friendlyBlockedReason(raw: string): string {
  const lower = raw.toLowerCase();
  if (lower.startsWith('approval_blocked')) return '已被授权策略拦截';
  if (lower.startsWith('capability_blocked')) return '已被能力策略拦截';
  if (lower.startsWith('unknown_tool_on_server')) return '该服务上找不到此工具';
  if (lower.startsWith('unknown_tool')) return '工具名称无法识别';
  if (lower.startsWith('rate_limit')) return '请求过于频繁，已被限流';
  if (lower.startsWith('timeout')) return '调用超时';
  return '被拦截';
}

type StatusFilter = 'any' | 'ok' | 'error_or_blocked';

interface FilterState {
  serverId: string;
  toolNameQuery: string;
  capability: McpToolCapability | 'all';
  status: StatusFilter;
  windowMinutes: number | 'all';
}

const DEFAULT_FILTERS: FilterState = {
  serverId: '',
  toolNameQuery: '',
  capability: 'all',
  status: 'any',
  windowMinutes: 'all',
};

function filterRecords(records: McpAuditRecord[], f: FilterState): McpAuditRecord[] {
  const lowerQuery = f.toolNameQuery.trim().toLowerCase();
  const cutoff =
    f.windowMinutes === 'all'
      ? null
      : Date.now() - f.windowMinutes * 60_000;
  return records.filter((r) => {
    if (f.serverId && r.server_id !== f.serverId) return false;
    if (lowerQuery && !r.tool_name.toLowerCase().includes(lowerQuery)) return false;
    if (f.capability !== 'all') {
      // capability is optional on records older than the schema bump;
      // treat absence as "unknown" so the filter still works.
      const cap = r.capability ?? 'unknown';
      if (cap !== f.capability) return false;
    }
    if (f.status === 'ok' && r.is_error) return false;
    if (f.status === 'error_or_blocked' && !r.is_error && !r.blocked_reason) return false;
    if (cutoff !== null) {
      const ts = Date.parse(r.ts);
      if (Number.isFinite(ts) && ts < cutoff) return false;
    }
    return true;
  });
}

interface McpAuditPanelProps {
  initialLimit?: number;
}

export function McpAuditPanel({ initialLimit = 500 }: McpAuditPanelProps) {
  const [records, setRecords] = useState<McpAuditRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await listMcpAuditRecords({ limit: initialLimit });
      setRecords(resp.records);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load audit log';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [initialLimit]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => filterRecords(records, filters), [records, filters]);

  const distinctServers = useMemo(() => {
    const set = new Set<string>();
    records.forEach((r) => set.add(r.server_id));
    return Array.from(set).sort();
  }, [records]);

  return (
    <div className="rounded-lg border border-outline-variant bg-surface-low p-3 space-y-3" data-testid="mcp-audit-panel">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ShieldAlert size={14} className="text-foreground/60" />
          <span className="text-xs font-label text-foreground/70">
            MCP 调用日志 <span className="text-foreground/40">· 最近 {initialLimit} 条 · 显示 {filtered.length}/{records.length} 条</span>
          </span>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="text-xs font-label text-foreground/60 hover:text-foreground/80 inline-flex items-center gap-1 disabled:opacity-40"
          data-testid="mcp-audit-refresh"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          {loading ? '加载中…' : '刷新'}
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-[11px]">
        <select
          value={filters.serverId}
          onChange={(e) => setFilters({ ...filters, serverId: e.target.value })}
          className="border rounded px-1.5 py-1 bg-surface-lowest"
          data-testid="mcp-audit-filter-server"
          aria-label="按服务筛选"
        >
          <option value="">全部服务</option>
          {distinctServers.map((sid) => (
            <option key={sid} value={sid}>{sid}</option>
          ))}
        </select>
        <input
          type="text"
          placeholder="工具名子串"
          value={filters.toolNameQuery}
          onChange={(e) => setFilters({ ...filters, toolNameQuery: e.target.value })}
          className="border rounded px-1.5 py-1 bg-surface-lowest"
          data-testid="mcp-audit-filter-tool"
          aria-label="按工具名筛选"
        />
        <select
          value={filters.capability}
          onChange={(e) => setFilters({ ...filters, capability: e.target.value as McpToolCapability | 'all' })}
          className="border rounded px-1.5 py-1 bg-surface-lowest"
          data-testid="mcp-audit-filter-capability"
          aria-label="按能力筛选"
        >
          {CAPABILITY_OPTIONS.map((cap) => (
            <option key={cap} value={cap}>{CAPABILITY_LABELS_ZH[cap]}</option>
          ))}
        </select>
        <select
          value={filters.status}
          onChange={(e) => setFilters({ ...filters, status: e.target.value as StatusFilter })}
          className="border rounded px-1.5 py-1 bg-surface-lowest"
          data-testid="mcp-audit-filter-status"
          aria-label="按状态筛选"
        >
          <option value="any">全部状态</option>
          <option value="ok">仅成功</option>
          <option value="error_or_blocked">错误/被阻止</option>
        </select>
        <select
          value={String(filters.windowMinutes)}
          onChange={(e) => setFilters({ ...filters, windowMinutes: e.target.value === 'all' ? 'all' : Number(e.target.value) })}
          className="border rounded px-1.5 py-1 bg-surface-lowest"
          data-testid="mcp-audit-filter-window"
          aria-label="按时间范围筛选"
        >
          <option value="all">全部时间</option>
          <option value="15">最近 15 分钟</option>
          <option value="60">最近 1 小时</option>
          <option value="1440">最近 24 小时</option>
        </select>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-[11px] text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
          <AlertTriangle size={12} />
          <span>{error}</span>
        </div>
      )}

      <div className="space-y-1.5 max-h-[420px] overflow-auto">
        {filtered.length === 0 && !loading && (
          <div className="text-xs text-foreground/40 italic px-2 py-3 text-center">
            没有匹配的记录。
          </div>
        )}
        {filtered.map((r) => (
          <div
            key={r.tool_call_id}
            className="rounded border border-outline-variant bg-surface-lowest p-2 text-[11px] space-y-1"
            data-testid={`mcp-audit-record-${r.tool_call_id}`}
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 truncate">
                {r.is_error ? (
                  <AlertTriangle size={12} className="text-red-500 flex-shrink-0" />
                ) : (
                  <CheckCircle2 size={12} className="text-emerald-500 flex-shrink-0" />
                )}
                <span className="font-mono truncate">
                  {r.server_slug || r.server_id}<span className="text-foreground/40">::</span>{r.tool_name}
                </span>
                {r.capability && (
                  <span className="text-[10px] px-1 rounded bg-primary/10 text-primary">
                    {CAPABILITY_LABELS_ZH[(r.capability as McpToolCapability) ?? 'unknown'] ?? '未分类'}
                  </span>
                )}
              </div>
              <span className="text-[10px] text-foreground/40 font-mono whitespace-nowrap">
                {r.elapsed_ms}ms · {new Date(r.ts).toLocaleTimeString()}
              </span>
            </div>
            {r.preview && (
              <p className="text-[11px] text-foreground/70 whitespace-pre-wrap break-words line-clamp-3">
                {r.preview}{r.truncated ? '…' : ''}
              </p>
            )}
            {r.blocked_reason && (
              <details className="text-[10px]">
                <summary className="cursor-pointer list-none text-amber-700 hover:underline dark:text-amber-300">
                  {friendlyBlockedReason(r.blocked_reason)}
                  <span className="ml-1 text-amber-700/60 dark:text-amber-300/70">· 查看详情</span>
                </summary>
                <p className="mt-1 break-all rounded bg-amber-50 px-2 py-1 font-mono text-[10px] text-amber-800 dark:bg-amber-500/15 dark:text-amber-300">
                  {r.blocked_reason}
                </p>
              </details>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export const __test = { filterRecords, DEFAULT_FILTERS };
