import React, { useCallback, useEffect, useState } from 'react';
import {
  KeyRound,
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
import { fetchLegacyEnv } from '@/services/mcpLegacyEnvApi';
import McpLegacyEnvMigrationModal from './McpLegacyEnvMigrationModal';
import { formatMcpActionError, MCP_TRANSPORT_LABELS, sanitizeMcpDisplayLabel } from '../mcpDisplay';

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
  const [legacyCount, setLegacyCount] = useState<Record<string, number>>({});
  const [migrationTarget, setMigrationTarget] = useState<McpServerConfigPublic | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listMcpServers();
      setServers(list);
      const counts: Record<string, number> = {};
      await Promise.all(
        list.map(async (s) => {
          try {
            const r = await fetchLegacyEnv(s.server_id);
            counts[s.server_id] = r.count;
          } catch {
            counts[s.server_id] = 0;
          }
        }),
      );
      setLegacyCount(counts);
    } catch (exc) {
      setError(formatMcpActionError(exc, '加载 MCP 服务器列表失败，请稍后重试。'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleDelete = async (server: McpServerConfigPublic) => {
    const displayName = sanitizeMcpDisplayLabel(server.name, '当前服务器');
    if (
      !window.confirm(
        `删除 MCP 服务器「${displayName}」？\n` +
          '系统会一并清理对应的本地安装记录。',
      )
    ) {
      return;
    }
    setBusyId(server.server_id);
    try {
      await deleteMcpServer(server.server_id);
      await refresh();
    } catch (exc) {
      setError(formatMcpActionError(exc, '删除 MCP 服务器失败，请稍后重试。'));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-2">
        <p className="font-label text-[11px] text-foreground/55 flex-1">
          通过「推荐」或「本地安装」注册的 MCP 服务器在此列出。
          需要修改启动参数或切换授权状态，请到「高级 / 手动添加」页操作。
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
            const legacy = legacyCount[s.server_id] ?? 0;
            const displayName = sanitizeMcpDisplayLabel(s.name, 'MCP 服务器');
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
                      {displayName}
                    </span>
                    <span className="text-[10px] text-foreground/45 px-1.5 py-0.5 rounded bg-surface-high">
                      本地服务器
                    </span>
                    <span className="font-label text-[10px] text-foreground/45 px-1.5 py-0.5 rounded bg-surface-high">
                      {MCP_TRANSPORT_LABELS[s.transport]}
                    </span>
                    <span className={`font-label text-[10px] ${tone}`}>
                      {APPROVAL_LABEL[s.approval_state]}
                    </span>
                  </div>
                  {s.stdio && (
                    <p className="mt-1 font-label text-[10px] text-foreground/45">
                      本地进程 · {s.stdio.args.length + 1} 项启动配置
                    </p>
                  )}
                  {s.http && (
                    <p className="mt-1 font-label text-[10px] text-foreground/45">
                      网络服务 · 已填写服务地址
                    </p>
                  )}
                  {s.stdio?.env_refs && Object.keys(s.stdio.env_refs).length > 0 && (
                    <p className="mt-1 font-label text-[10px] text-foreground/55">
                      已绑定 {Object.keys(s.stdio.env_refs).length} 项凭证
                    </p>
                  )}

                  {legacy > 0 && (
                    <div className="mt-2 flex items-start gap-2 rounded-md border border-amber-300/40 bg-amber-50/40 dark:border-amber-700/40 dark:bg-amber-500/10 p-2">
                      <KeyRound
                        size={12}
                        className="text-amber-600 dark:text-amber-300 mt-0.5 flex-shrink-0"
                      />
                      <div className="flex-1 min-w-0">
                        <p className="font-label text-[11px] text-amber-700 dark:text-amber-200">
                          检测到 {legacy} 项旧式敏感配置。建议迁移到凭证引用。
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setMigrationTarget(s)}
                        className="flex-shrink-0 inline-flex items-center gap-1 rounded-md bg-amber-500/15 px-2 py-1 font-label text-[11px] text-amber-700 dark:text-amber-200 hover:bg-amber-500/25"
                      >
                        迁移到凭证引用
                      </button>
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => void handleDelete(s)}
                  disabled={isBusy}
                  aria-label={`删除 ${displayName}`}
                  title="删除并清理本地安装记录"
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

      {migrationTarget && (
        <McpLegacyEnvMigrationModal
          serverId={migrationTarget.server_id}
          serverName={sanitizeMcpDisplayLabel(migrationTarget.name, 'MCP 服务器')}
          open={true}
          onClose={() => setMigrationTarget(null)}
          onMigrated={() => {
            setMigrationTarget(null);
            void refresh();
          }}
        />
      )}
    </div>
  );
}

export default McpInstalledServersView;
