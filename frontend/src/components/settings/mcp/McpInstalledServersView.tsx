/**
 * Installed MCP servers view (S4c · live list from /api/mcp/servers).
 *
 * Lightweight read-mostly view; full CRUD (manual edit / approval state
 * machine / tool catalog drill-down) stays in the legacy
 * McpServersSection embedded under the [高级] tab. Here we show the
 * essentials a normal user cares about after running the wizard:
 *   - name / slug / transport / approval state
 *   - delete (which also triggers backend cleanup_install_dir)
 *   - refresh
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Loader2,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Trash2,
} from 'lucide-react';
import {
  deleteMcpServer,
  listMcpServers,
  type McpApprovalState,
  type McpServerConfigPublic,
} from '@/services/mcpApi';

const APPROVAL_LABEL: Record<McpApprovalState, string> = {
  registered: '已登记',
  catalog_reviewed: '已审阅',
  enabled_for_session: '本次会话已启用',
};

const APPROVAL_ICON: Record<McpApprovalState, React.ElementType> = {
  registered: ShieldAlert,
  catalog_reviewed: ShieldOff,
  enabled_for_session: ShieldCheck,
};

const APPROVAL_TONE: Record<McpApprovalState, string> = {
  registered: 'text-amber-600 dark:text-amber-300',
  catalog_reviewed: 'text-blue-600 dark:text-blue-300',
  enabled_for_session: 'text-emerald-600 dark:text-emerald-300',
};

export function McpInstalledServersView(): JSX.Element {
  const [servers, setServers] = useState<McpServerConfigPublic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listMcpServers();
      setServers(list);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleDelete = async (server: McpServerConfigPublic) => {
    if (
      !window.confirm(
        `删除 MCP 服务器「${server.name}」(${server.server_slug})?\n` +
          '后端会一并清理对应的 install_record 目录。',
      )
    ) {
      return;
    }
    setBusyId(server.server_id);
    try {
      await deleteMcpServer(server.server_id);
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-2">
        <p className="font-label text-[11px] text-foreground/55 flex-1">
          通过「推荐」或「本地安装」注册的 MCP 服务器在此列出。
          需要修改命令/参数或切换 approval 状态,请到「高级 / 手动添加」tab 的传统表单操作。
        </p>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          aria-label="刷新列表"
          title="刷新列表"
          className="p-1.5 rounded text-foreground/55 hover:text-foreground hover:bg-surface-high disabled:opacity-50"
        >
          {loading ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <RefreshCw size={14} />
          )}
        </button>
      </div>

      {error && (
        <div className="rounded-md border border-red-300/40 bg-red-500/5 dark:border-red-700/40 dark:bg-red-500/15 p-2 text-[11px] text-red-600 dark:text-red-300 font-label">
          {error}
        </div>
      )}

      {!loading && servers.length === 0 && (
        <div className="rounded-md border border-dashed border-outline-variant p-6 font-label text-[11px] text-foreground/40 text-center">
          还没有已安装的 MCP 服务器。请到「推荐」或「本地安装」开始。
        </div>
      )}

      {servers.length > 0 && (
        <ul className="space-y-2">
          {servers.map((s) => {
            const Icon = APPROVAL_ICON[s.approval_state];
            const tone = APPROVAL_TONE[s.approval_state];
            const isBusy = busyId === s.server_id;
            return (
              <li
                key={s.server_id}
                className="rounded-md border border-outline-variant bg-surface-low p-3 flex items-start gap-3"
              >
                <div className={`p-1.5 rounded-md bg-surface-high mt-0.5 ${tone}`}>
                  <Icon size={14} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-display text-sm font-semibold text-foreground">
                      {s.name}
                    </span>
                    <span className="font-mono text-[10px] text-foreground/40 px-1.5 py-0.5 rounded bg-surface-high">
                      {s.server_slug}
                    </span>
                    <span className="font-mono text-[10px] text-foreground/40 px-1.5 py-0.5 rounded bg-surface-high">
                      {s.transport}
                    </span>
                    <span className={`font-label text-[10px] ${tone}`}>
                      {APPROVAL_LABEL[s.approval_state]}
                    </span>
                  </div>
                  {s.stdio && (
                    <p className="mt-1 font-mono text-[10px] text-foreground/40 break-all">
                      {s.stdio.command} {s.stdio.args.join(' ')}
                    </p>
                  )}
                  {s.http && (
                    <p className="mt-1 font-mono text-[10px] text-foreground/40 break-all">
                      {s.http.url}
                    </p>
                  )}
                  {s.stdio?.env_refs && Object.keys(s.stdio.env_refs).length > 0 && (
                    <p className="mt-1 font-label text-[10px] text-foreground/55">
                      绑定凭证 env: {Object.keys(s.stdio.env_refs).join(', ')}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => void handleDelete(s)}
                  disabled={isBusy}
                  aria-label={`删除 ${s.name}`}
                  title="删除并清理 install_record"
                  className="p-2 rounded text-red-500/70 hover:text-red-500 hover:bg-red-500/10 disabled:opacity-50 dark:text-red-300/75 dark:hover:bg-red-500/15 dark:hover:text-red-300"
                >
                  {isBusy ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Trash2 size={14} />
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export default McpInstalledServersView;
