import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Loader2, X, Zap } from 'lucide-react';
import CredentialPicker from '@/components/settings/credentials/CredentialPicker';
import { formatMcpActionError, sanitizeMcpVisibleText } from '@/components/settings/mcpDisplay';
import {
  fetchLegacyEnv,
  migrateEnvToRefs,
  type LegacyEnvEntry,
} from '@/services/mcpLegacyEnvApi';

export interface McpLegacyEnvMigrationModalProps {
  serverId: string;
  serverName: string;
  open: boolean;
  onClose: () => void;
  onMigrated?: () => void;
}

export function McpLegacyEnvMigrationModal(
  props: McpLegacyEnvMigrationModalProps,
): JSX.Element | null {
  const { serverId, serverName, open, onClose, onMigrated } = props;
  const navigate = useNavigate();

  const [entries, setEntries] = useState<LegacyEnvEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [doneSummary, setDoneSummary] = useState<{
    stdio: string[];
    http: string[];
  } | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setMapping({});
    setConfirm(false);
    setDoneSummary(null);
    void (async () => {
      try {
        const data = await fetchLegacyEnv(serverId);
        if (cancelled) return;
        setEntries(data.entries);
      } catch (exc) {
        if (cancelled) return;
        setError(formatMcpActionError(exc, '扫描失败，请稍后重试。'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, serverId]);

  if (!open) return null;

  const allBound = entries.every((e) => mapping[e.target_env]?.trim());
  const canSubmit = entries.length > 0 && allBound && confirm && !busy;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await migrateEnvToRefs(serverId, {
        mapping,
        confirm_remove_raw: true,
      });
      setDoneSummary({
        stdio: result.migrated_stdio_env_keys,
        http: result.migrated_http_header_keys,
      });
      onMigrated?.();
    } catch (exc) {
      setError(formatMcpActionError(exc, '迁移失败，请检查凭证绑定后重试。'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="mcp-legacy-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 md:p-8"
    >
      <div className="bg-surface-lowest rounded-lg shadow-xl border border-outline-variant w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
        <header className="flex items-center justify-between px-4 py-3 border-b border-outline-variant flex-shrink-0">
          <h3
            id="mcp-legacy-modal-title"
            className="font-display text-sm font-semibold text-foreground"
          >
            迁移到凭证引用 · {sanitizeMcpVisibleText(serverName, '当前服务器')}
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="p-1.5 rounded text-foreground/55 hover:text-foreground hover:bg-surface-high"
          >
            <X size={14} />
          </button>
        </header>

        <div className="flex-1 overflow-auto p-4 space-y-4">
          {doneSummary ? (
            <DoneView summary={doneSummary} />
          ) : (
            <>
              <div className="rounded-md border border-amber-300/40 bg-amber-50/40 dark:border-amber-700/40 dark:bg-amber-500/10 p-3 flex items-start gap-2">
                <AlertTriangle size={14} className="text-amber-600 dark:text-amber-300 mt-0.5 flex-shrink-0" />
                <div className="space-y-1">
                  <p className="font-label text-[11px] text-amber-700 dark:text-amber-200 font-medium">
                    这一步会把敏感配置迁移到凭证管理
                  </p>
                  <p className="font-label text-[11px] text-amber-700/80 dark:text-amber-200/80">
                    迁移后，服务器只保留凭证引用；实际访问凭证保存在「凭证管理」中。
                    请确认绑定无误后再勾选下方确认。
                  </p>
                </div>
              </div>

              {loading && (
                <div className="flex items-center gap-2 text-foreground/55 font-label text-[12px]">
                  <Loader2 size={14} className="animate-spin" />
                  正在扫描该服务器的旧式敏感配置...
                </div>
              )}

              {!loading && entries.length === 0 && (
                <p className="font-label text-[12px] text-foreground/55">
                  未检测到旧式敏感配置。这个服务器已经使用凭证引用。
                </p>
              )}

              {entries.length > 0 && (
                <div className="space-y-5">
                  {entries.map((e, index) => (
                    <div key={`${e.transport_field}:${e.target_env}`} className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-label text-[11px] text-foreground font-medium">
                          敏感配置 {index + 1}
                        </span>
                        <span className="font-label text-[10px] text-foreground/40">
                          {formatLegacySource(e.transport_field)}
                        </span>
                        <span className="font-label text-[10px] text-foreground/40">
                          原值已脱敏确认
                        </span>
                      </div>
                      <CredentialPicker
                        requirement={{
                          id: e.target_env,
                          label: `绑定凭证：敏感配置 ${index + 1}`,
                          env: e.target_env,
                          kind: 'api_key',
                          provider_hints: [],
                          required: true,
                        }}
                        value={mapping[e.target_env] ?? null}
                        onChange={(id) =>
                          setMapping({ ...mapping, [e.target_env]: id ?? '' })
                        }
                        onJumpToCreate={() => {
                          // Stash mapping so a route round-trip can restore.
                          try {
                            sessionStorage.setItem(
                              'mcp.legacy.migration.draft',
                              JSON.stringify({ serverId, mapping }),
                            );
                          } catch {
                            // ignore
                          }
                          navigate('/settings?section=credentials');
                        }}
                      />
                    </div>
                  ))}
                </div>
              )}

              {error && (
                <div className="rounded-md border border-red-300/40 bg-red-500/5 dark:border-red-700/40 dark:bg-red-500/15 p-2 text-[11px] text-red-600 dark:text-red-300 font-label">
                  {error}
                </div>
              )}
            </>
          )}
        </div>

        <footer className="px-4 py-3 border-t border-outline-variant flex items-center justify-between gap-2 flex-shrink-0">
          {doneSummary ? (
            <button
              type="button"
              onClick={onClose}
              className="ml-auto rounded-md bg-primary px-3 py-1.5 font-label text-xs font-medium text-primary-foreground hover:bg-primary/90"
            >
              完成
            </button>
          ) : (
            <>
              <label className="flex items-center gap-2 text-[11px] text-foreground/70 cursor-pointer">
                <input
                  type="checkbox"
                  checked={confirm}
                  onChange={(e) => setConfirm(e.target.checked)}
                  disabled={!allBound}
                />
                我确认改为凭证引用
              </label>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="font-label text-xs text-foreground/55 hover:text-foreground"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={() => void submit()}
                  disabled={!canSubmit}
                  title={
                    !allBound
                      ? '请为每个敏感配置绑定凭证'
                      : !confirm
                      ? '请勾选确认'
                      : '执行迁移'
                  }
                  className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 font-label text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  {busy ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
                  迁移
                </button>
              </div>
            </>
          )}
        </footer>
      </div>
    </div>
  );
}

function DoneView(props: { summary: { stdio: string[]; http: string[] } }): JSX.Element {
  const { summary } = props;
  return (
    <div className="space-y-3">
      <h4 className="font-display text-sm font-semibold text-emerald-700 dark:text-emerald-300">
        迁移完成
      </h4>
      <div className="rounded-md border border-outline-variant bg-surface-low p-3 font-label text-[11px] text-foreground/70 space-y-1">
        {summary.stdio.length > 0 && (
          <div>本地进程配置已迁移 {summary.stdio.length} 项</div>
        )}
        {summary.http.length > 0 && (
          <div>网络连接配置已迁移 {summary.http.length} 项</div>
        )}
        {summary.stdio.length === 0 && summary.http.length === 0 && (
          <div className="text-foreground/40">(无变化)</div>
        )}
      </div>
      <p className="font-label text-[11px] text-foreground/55">
        提示：刷新「已安装」列表后，服务器卡片会显示已绑定的凭证数量。
      </p>
    </div>
  );
}

function formatLegacySource(value: LegacyEnvEntry['transport_field']): string {
  return value === 'http.headers' ? '网络连接配置' : '本地进程配置';
}

export default McpLegacyEnvMigrationModal;
