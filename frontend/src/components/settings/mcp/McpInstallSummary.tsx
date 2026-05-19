/**
 * MCP install summary card (S4a stub).
 *
 * Post-install success surface: shows installed server slug, approval state
 * progression, probed tools, and next-step suggestions. Lands fully in S4c.
 */
import type { McpInstallationInstallResponse } from '@/services/mcpInstallApi';

export interface McpInstallSummaryProps {
  response: McpInstallationInstallResponse;
  onClose: () => void;
}

export function McpInstallSummary(props: McpInstallSummaryProps): JSX.Element {
  void props;
  return (
    <div className="rounded-md border border-dashed border-outline-variant p-4 font-label text-[11px] text-foreground/40 text-center">
      S4a stub · 安装完成后的汇总卡片在 S4c 落地。
    </div>
  );
}

export default McpInstallSummary;
