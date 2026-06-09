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
import { RefreshCw, AlertTriangle, CheckCircle2, ShieldAlert, Trash2, ChevronDown } from 'lucide-react';
import {
  clearMcpAuditRecords,
  listMcpAuditRecords,
  type McpAuditRecord,
  type McpToolCapability,
} from '@/services/mcpApi';
import { formatMcpActionError, sanitizeMcpDisplayLabel, sanitizeMcpVisibleText } from './mcpDisplay';

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

/** 把后端返回的英文 blocked_reason 收敛成一行人话。 */
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

function buildAuditServerLabels(records: McpAuditRecord[]): Map<string, string> {
  const ids = Array.from(new Set(records.map((record) => record.server_id))).sort();
  return new Map(
    ids.map((serverId, index) => {
      const fallback = `MCP 服务 ${index + 1}`;
      const record = records.find((item) => item.server_id === serverId);
      return [serverId, sanitizeMcpDisplayLabel(record?.server_label, fallback)];
    }),
  );
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
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await listMcpAuditRecords({ limit: initialLimit });
      setRecords(resp.records);
      setLastLoadedAt(new Date().toLocaleTimeString());
    } catch (err: unknown) {
      setError(formatMcpActionError(err, '加载 MCP 调用日志失败，请稍后重试。'));
    } finally {
      setLoading(false);
    }
  }, [initialLimit]);

  const clearRecords = useCallback(async () => {
    const confirmed = window.confirm('清空 MCP 调用日志？这只会清空本地审计展示记录，不会删除 MCP 服务配置。');
    if (!confirmed) return;
    setClearing(true);
    setError(null);
    try {
      await clearMcpAuditRecords();
      setRecords([]);
      setExpandedId(null);
      setLastLoadedAt(new Date().toLocaleTimeString());
    } catch (err: unknown) {
      setError(formatMcpActionError(err, '清空 MCP 调用日志失败，请稍后重试。'));
    } finally {
      setClearing(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => filterRecords(records, filters), [records, filters]);

  const serverLabels = useMemo(() => buildAuditServerLabels(records), [records]);
  const distinctServers = useMemo(
    () => Array.from(serverLabels.entries()).map(([id, label]) => ({ id, label })),
    [serverLabels],
  );

  return (
    <div className="rounded-lg border border-outline-variant bg-surface-low p-3 space-y-3" data-testid="mcp-audit-panel">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ShieldAlert size={14} className="text-foreground/60" />
          <span className="text-xs font-label text-foreground/70">
            MCP 调用日志 <span className="text-foreground/40">· 最近 {initialLimit} 条 · 显示 {filtered.length}/{records.length} 条</span>
          </span>
          {lastLoadedAt ? (
            <span className="font-label text-[10px] text-foreground/35">上次刷新 {lastLoadedAt}</span>
          ) : null}
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => void clearRecords()}
            disabled={clearing || loading || records.length === 0}
            className="text-xs font-label text-red-500/70 hover:text-red-500 inline-flex items-center gap-1 disabled:opacity-35"
            data-testid="mcp-audit-clear"
            title="清空本地 MCP 调用日志"
          >
            {clearing ? <RefreshCw size={12} className="animate-spin" /> : <Trash2 size={12} />}
            清空
          </button>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading || clearing}
            className="text-xs font-label text-foreground/60 hover:text-foreground/80 inline-flex items-center gap-1 disabled:opacity-40"
            data-testid="mcp-audit-refresh"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            {loading ? '加载中…' : '刷新'}
          </button>
        </div>
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
          {distinctServers.map((server) => (
            <option key={server.id} value={server.id}>{server.label}</option>
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
        {filtered.map((r, index) => {
          const expanded = expandedId === r.tool_call_id;
          const serverLabel = serverLabels.get(r.server_id) ?? 'MCP 服务';
          const toolLabel = sanitizeMcpDisplayLabel(r.tool_name, `工具 ${index + 1}`);
          const preview = r.preview
            ? sanitizeMcpVisibleText(r.preview, '调用返回内容已隐藏，避免显示内部配置或本地路径。')
            : '';
          const blockedReason = r.blocked_reason ? friendlyBlockedReason(r.blocked_reason) : '';
          return (
          <div
            key={r.tool_call_id}
            className="rounded border border-outline-variant bg-surface-lowest p-2 text-[11px] space-y-1.5"
            data-testid={`mcp-audit-record-${r.tool_call_id}`}
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 truncate">
                {r.is_error ? (
                  <AlertTriangle size={12} className="text-red-500 flex-shrink-0" />
                ) : (
                  <CheckCircle2 size={12} className="text-emerald-500 flex-shrink-0" />
                )}
                <span className="font-label truncate">
                  {serverLabel}<span className="text-foreground/40"> · </span>{toolLabel}
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
            <button
              type="button"
              onClick={() => setExpandedId(expanded ? null : r.tool_call_id)}
              className="inline-flex items-center gap-1 rounded px-1 py-0.5 font-label text-[10px] text-primary hover:bg-primary/10"
              data-testid={`mcp-audit-detail-${r.tool_call_id}`}
            >
              <ChevronDown size={11} className={expanded ? 'rotate-180 transition-transform' : 'transition-transform'} />
              {expanded ? '收起详情' : '查看详情'}
            </button>
            {preview && (
              <p className="text-[11px] text-foreground/70 whitespace-pre-wrap break-words line-clamp-3">
                {preview}{r.truncated ? '…' : ''}
              </p>
            )}
            {blockedReason && (
              <details className="text-[10px]">
                <summary className="cursor-pointer list-none text-amber-700 hover:underline dark:text-amber-300">
                  {blockedReason}
                  <span className="ml-1 text-amber-700/60 dark:text-amber-300/70">· 查看详情</span>
                </summary>
                <p className="mt-1 rounded bg-amber-50 px-2 py-1 font-label text-[10px] text-amber-800 dark:bg-amber-500/15 dark:text-amber-300">
                  {blockedReason}
                </p>
              </details>
            )}
            {expanded ? (
              <dl className="mt-2 grid gap-2 rounded border border-outline-variant/40 bg-surface-low p-2 md:grid-cols-2">
                <AuditDetail label="服务" value={serverLabel} />
                <AuditDetail label="工具名称" value={toolLabel} />
                <AuditDetail label="能力类型" value={CAPABILITY_LABELS_ZH[(r.capability ?? 'unknown') as McpToolCapability] ?? '未分类'} />
                <AuditDetail label="状态" value={r.is_error ? '错误或被阻止' : '成功'} />
                <AuditDetail label="耗时" value={`${r.elapsed_ms}ms`} />
                <AuditDetail label="时间" value={new Date(r.ts).toLocaleString()} />
                {blockedReason ? <AuditDetail label="拦截原因" value={blockedReason} /> : null}
                {preview ? <AuditDetail label="返回预览" value={`${preview}${r.truncated ? '…' : ''}`} /> : null}
              </dl>
            ) : null}
          </div>
          );
        })}
      </div>
    </div>
  );
}

function AuditDetail({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="font-label text-[10px] text-foreground/40">{label}</dt>
      <dd className={`${mono ? 'font-mono' : 'font-label'} mt-0.5 whitespace-pre-wrap break-words text-[11px] text-foreground/70`}>
        {value}
      </dd>
    </div>
  );
}

export const __test = { filterRecords, DEFAULT_FILTERS };
