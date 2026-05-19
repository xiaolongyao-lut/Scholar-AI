/**
 * McpToolApprovalModal — UI skeleton for per-call confirmation of
 * write/network/filesystem/unknown capability tools.
 *
 * Per `docs/plans/active/2026-05-16-mcp-tool-use-ux-plan.md`:
 * - D-MCPUX-3: modal-only confirmation; no inline approval pill in v1.
 * - D-MCPUX-4: "remember for this run" toggle is in-memory only; no
 *   cross-session persistence.
 * - D-MCPUX-2: server-reported tool annotations are advisory; the modal
 *   shows the backend classification (capability tag) as the source of
 *   truth.
 * - Stop condition: this is a UI-render skeleton. The backend pending-
 *   call protocol does not exist yet; this component renders its props
 *   and reports the user's choice via `onApprove` / `onCancel`. The
 *   chat / discussion runtimes do not yet drive it. Wiring is gated on
 *   Phase 2 backend work in MCP v0.4.
 */
import React, { useState } from 'react';
import { ShieldAlert, ShieldCheck, X } from 'lucide-react';
import type { McpToolCapability } from '@/services/mcpApi';

export interface McpPendingToolCall {
  call_id: string;
  server_id: string;
  server_label: string;
  tool_name: string;
  capability: McpToolCapability;
  args_preview?: string;
}

interface McpToolApprovalModalProps {
  pending: McpPendingToolCall | null;
  onApprove: (call_id: string, opts: { rememberForRun: boolean }) => void;
  onCancel: (call_id: string) => void;
}

const CAPABILITY_DESCRIPTION: Record<McpToolCapability, string> = {
  read: '只读：从外部源读取数据。',
  write: '写入：会修改外部状态（创建/更新文件、记录、issue 等）。',
  network: '网络：会向外部服务发送请求。',
  filesystem: '文件系统：会读写本机文件。',
  destructive: '破坏性：可能不可逆，例如删除、迁移或覆盖。默认阻止。',
  unknown: '未知：后端无法分类。需要明确确认。',
};

export function McpToolApprovalModal({ pending, onApprove, onCancel }: McpToolApprovalModalProps) {
  const [remember, setRemember] = useState(false);
  if (!pending) return null;
  const isBlocked = pending.capability === 'destructive';
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="mcp-approval-title"
      data-testid="mcp-tool-approval-modal"
    >
      <div className="w-[420px] max-w-[90vw] bg-surface-lowest border border-outline-variant rounded-lg shadow-xl">
        <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant">
          <div className="flex items-center gap-2">
            {isBlocked ? (
              <ShieldAlert size={16} className="text-red-600" />
            ) : (
              <ShieldCheck size={16} className="text-amber-600" />
            )}
            <h3 id="mcp-approval-title" className="text-sm font-label font-semibold">
              确认 MCP 工具调用
            </h3>
          </div>
          <button
            type="button"
            onClick={() => onCancel(pending.call_id)}
            className="text-foreground/40 hover:text-foreground/70"
            aria-label="cancel"
          >
            <X size={16} />
          </button>
        </div>
        <div className="px-4 py-3 space-y-2 text-xs">
          <dl className="grid grid-cols-[6em_1fr] gap-y-1">
            <dt className="text-foreground/50">Server</dt>
            <dd className="font-mono">{pending.server_label}</dd>
            <dt className="text-foreground/50">Tool</dt>
            <dd className="font-mono">{pending.tool_name}</dd>
            <dt className="text-foreground/50">Capability</dt>
            <dd className="font-mono" data-testid="mcp-approval-capability">
              {pending.capability}
            </dd>
          </dl>
          <p className="text-[11px] text-foreground/70">
            {CAPABILITY_DESCRIPTION[pending.capability]}
          </p>
          {pending.args_preview && (
            <pre
              className="text-[11px] bg-surface-low rounded p-2 overflow-auto max-h-32 whitespace-pre-wrap break-all"
              data-testid="mcp-approval-args-preview"
            >
              {pending.args_preview}
            </pre>
          )}
          {!isBlocked && (
            <label className="flex items-center gap-2 text-[11px] text-foreground/70 select-none">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                data-testid="mcp-approval-remember"
              />
              本次会话内记住该选择（不跨会话）
            </label>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-outline-variant">
          <button
            type="button"
            onClick={() => onCancel(pending.call_id)}
            className="text-xs px-3 py-1.5 rounded border border-outline-variant hover:bg-surface-low"
            data-testid="mcp-approval-cancel"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => onApprove(pending.call_id, { rememberForRun: remember })}
            disabled={isBlocked}
            className={
              'text-xs px-3 py-1.5 rounded text-white ' +
              (isBlocked ? 'bg-red-300 cursor-not-allowed' : 'bg-primary hover:bg-primary/90')
            }
            data-testid="mcp-approval-approve"
          >
            {isBlocked ? '该 capability 默认阻止' : '允许调用'}
          </button>
        </div>
      </div>
    </div>
  );
}
