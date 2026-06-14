import { CheckCircle2, ShieldCheck, Wrench, X } from 'lucide-react';
import type { McpInstallationInstallResponse } from '@/services/mcpInstallApi';

export interface McpInstallSummaryProps {
  response: McpInstallationInstallResponse;
  onClose: () => void;
}

export function McpInstallSummary(props: McpInstallSummaryProps): JSX.Element {
  const { response, onClose } = props;
  const toolCount = response.probe.tool_count;
  const probeLabel =
    response.probe.status === 'ok'
      ? `探测成功，发现 ${toolCount} 个工具`
      : response.probe.status === 'skipped_untrusted'
        ? '已安装，尚未启动探测'
        : '已安装，探测未通过';
  const approvalLabel =
    response.approval_state === 'enabled_for_session'
      ? '本次会话已启用'
      : response.approval_state === 'trusted'
        ? '已信任'
        : response.approval_state === 'blocked'
          ? '已阻止'
          : '待确认';

  return (
    <div className="rounded-lg border border-emerald-200/70 bg-emerald-50/70 p-4 text-emerald-950 shadow-sm dark:border-emerald-700/40 dark:bg-emerald-500/10 dark:text-emerald-100">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-md bg-emerald-600 p-1.5 text-white">
          <CheckCircle2 size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="font-label text-sm font-semibold">安装完成</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1 text-emerald-900/60 hover:bg-emerald-100 hover:text-emerald-950 dark:text-emerald-100/60 dark:hover:bg-emerald-500/15"
              aria-label="关闭安装摘要"
              title="关闭"
            >
              <X size={14} />
            </button>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <div className="rounded-md border border-emerald-200/70 bg-white/60 px-3 py-2 dark:border-emerald-700/40 dark:bg-black/10">
              <div className="flex items-center gap-1.5 text-[11px] font-semibold">
                <ShieldCheck size={12} />
                授权状态
              </div>
              <p className="mt-1 text-xs text-emerald-900/75 dark:text-emerald-100/75">{approvalLabel}</p>
            </div>
            <div className="rounded-md border border-emerald-200/70 bg-white/60 px-3 py-2 dark:border-emerald-700/40 dark:bg-black/10">
              <div className="flex items-center gap-1.5 text-[11px] font-semibold">
                <Wrench size={12} />
                可用性
              </div>
              <p className="mt-1 text-xs text-emerald-900/75 dark:text-emerald-100/75">{probeLabel}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default McpInstallSummary;
