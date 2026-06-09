/**
 * McpScopePicker — enabled MCP service chips for chat and discussion scope.
 *
 * Per `docs/plans/active/2026-05-16-mcp-tool-use-ux-plan.md` D-MCPUX-5
 * (Discussion = run-level only) + D-MCPUX-8 (default off):
 * - Loads `/api/mcp/servers?approval_state=enabled_for_session` once on
 *   mount; user toggles servers in/out of the active scope per-call.
 * - Selection is fully owned by the parent via `selected` + `onChange`.
 * - When zero enabled servers exist, the picker renders a disabled hint
 *   pointing the user at the settings MCP service page.
 * - Never enables anything by default; `selected` starts as the parent
 *   passes it (typically empty).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Server, Plus, Loader2 } from 'lucide-react';
import { listMcpServers, type McpServerConfigPublic } from '@/services/mcpApi';
import { sanitizeMcpDisplayLabel, sanitizeMcpVisibleText } from '@/components/settings/mcpDisplay';

interface McpScopePickerProps {
  selected: string[];
  onChange: (next: string[]) => void;
  /** Optional: hide entirely when no enabled servers exist. Default false. */
  hideWhenEmpty?: boolean;
  /** Test seam: skip the network call and use this server list. */
  injectedServers?: McpServerConfigPublic[];
  className?: string;
}

export function McpScopePicker({
  selected,
  onChange,
  hideWhenEmpty = false,
  injectedServers,
  className = '',
}: McpScopePickerProps) {
  const [servers, setServers] = useState<McpServerConfigPublic[]>(injectedServers ?? []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (injectedServers) return;
    setLoading(true);
    setError(null);
    try {
      const list = await listMcpServers({ approvalState: 'enabled_for_session' });
      setServers(list);
    } catch {
      setError('无法加载已启用的 MCP 服务，请稍后重试。');
    } finally {
      setLoading(false);
    }
  }, [injectedServers]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (sid: string) => {
    if (selected.includes(sid)) {
      onChange(selected.filter((id) => id !== sid));
    } else {
      onChange([...selected, sid]);
    }
  };

  const visible = useMemo(
    () =>
      servers.map((server, index) => ({
        ...server,
        displayName: sanitizeMcpDisplayLabel(server.name, `MCP 服务 ${index + 1}`),
        displayTitle: sanitizeMcpVisibleText(server.notes, `MCP 服务 ${index + 1}`),
      })),
    [servers],
  );

  if (visible.length === 0 && hideWhenEmpty && !loading && !error) return null;

  return (
    <div
      className={`flex flex-wrap items-center gap-1.5 text-[11px] ${className}`}
      data-testid="mcp-scope-picker"
    >
      <Server size={12} className="text-foreground/50" />
      <span className="text-foreground/50">MCP 服务：</span>
      {loading && <Loader2 size={12} className="animate-spin text-foreground/40" />}
      {error && <span className="text-amber-700">{error}</span>}
      {!loading && !error && visible.length === 0 && (
        <span className="text-foreground/40 italic">
          没有已启用的 MCP 服务。请先到“设置 · MCP 服务器”启用一个。
        </span>
      )}
      {visible.map((s) => {
        const active = selected.includes(s.server_id);
        return (
          <button
            type="button"
            key={s.server_id}
            onClick={() => toggle(s.server_id)}
            data-testid={`mcp-scope-chip-${s.server_id}`}
            aria-pressed={active}
            className={
              'px-2 py-0.5 rounded-full border transition-colors ' +
              (active
                ? 'bg-primary text-primary-foreground border-primary'
                : 'bg-surface-lowest text-foreground/70 border-outline-variant hover:bg-primary/10')
            }
            title={s.displayTitle}
          >
            {active ? '✓ ' : <Plus size={10} className="inline mr-0.5" />}
            {s.displayName}
          </button>
        );
      })}
    </div>
  );
}
