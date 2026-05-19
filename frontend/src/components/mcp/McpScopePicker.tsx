/**
 * McpScopePicker — chip row of enabled MCP servers for chat / Discussion
 * run-level scope selection.
 *
 * Per `docs/plans/active/2026-05-16-mcp-tool-use-ux-plan.md` D-MCPUX-5
 * (Discussion = run-level only) + D-MCPUX-8 (default off):
 * - Loads `/api/mcp/servers?approval_state=enabled_for_session` once on
 *   mount; user toggles servers in/out of the active scope per-call.
 * - Selection is fully owned by the parent via `selected` + `onChange`.
 * - When zero enabled servers exist, the picker renders a disabled hint
 *   pointing the user at Settings -> MCP servers.
 * - Never enables anything by default; `selected` starts as the parent
 *   passes it (typically empty).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Server, Plus, Loader2 } from 'lucide-react';
import { listMcpServers, type McpServerConfigPublic } from '@/services/mcpApi';

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
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load enabled MCP servers';
      setError(msg);
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

  const visible = useMemo(() => servers, [servers]);

  if (visible.length === 0 && hideWhenEmpty && !loading && !error) return null;

  return (
    <div
      className={`flex flex-wrap items-center gap-1.5 text-[11px] ${className}`}
      data-testid="mcp-scope-picker"
    >
      <Server size={12} className="text-foreground/50" />
      <span className="text-foreground/50">MCP:</span>
      {loading && <Loader2 size={12} className="animate-spin text-foreground/40" />}
      {error && <span className="text-amber-700">{error}</span>}
      {!loading && !error && visible.length === 0 && (
        <span className="text-foreground/40 italic">
          没有已启用的 MCP server。先到 Settings · MCP 启用一个。
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
              'px-2 py-0.5 rounded-full border font-mono transition-colors ' +
              (active
                ? 'bg-primary text-primary-foreground border-primary'
                : 'bg-surface-lowest text-foreground/70 border-outline-variant hover:bg-primary/10')
            }
            title={s.notes || s.server_slug}
          >
            {active ? '✓ ' : <Plus size={10} className="inline mr-0.5" />}
            {s.name || s.server_slug}
          </button>
        );
      })}
    </div>
  );
}
