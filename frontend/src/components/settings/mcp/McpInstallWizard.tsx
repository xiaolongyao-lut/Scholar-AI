/**
 * MCP install wizard (S4a stub / plan 2026-05-20 §A4).
 *
 * Wizard states (from plan):
 *   1. Select recommended capability or local source path
 *   2. Scan package
 *   3. Choose launch candidate if multiple
 *   4. Fill generated non-secret config fields
 *   5. Bind required credentials through shared CredentialPicker
 *   6. Review tools / permissions / approval
 *   7. Install and enable (with trust checkbox per Locked Revisions M7)
 *
 * S4a: structure + props contract only. S4b implements steps 1-5.
 * S4c implements step 6-7 with the trust checkbox + probe + approval.
 */
import type {
  McpPackageScanResult,
  McpLaunchCandidate,
  McpInstallationInstallResponse,
} from '@/services/mcpInstallApi';

export interface McpInstallWizardProps {
  initialPath?: string;
  templateHint?: string;
  onClose: () => void;
  onInstalled?: (response: McpInstallationInstallResponse) => void;
}

export function McpInstallWizard(props: McpInstallWizardProps): JSX.Element {
  void props;
  return (
    <div className="rounded-md border border-dashed border-outline-variant p-4 font-label text-[11px] text-foreground/40 text-center">
      S4a stub · 安装向导 (scan → candidate → config → credentials → review → install) 在 S4b/S4c 落地。
    </div>
  );
}

export default McpInstallWizard;

// Re-export shapes that downstream views import from the wizard surface.
export type { McpPackageScanResult, McpLaunchCandidate };
