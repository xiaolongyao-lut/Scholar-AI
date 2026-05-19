/**
 * Local install entry view (S4a stub / plan 2026-05-20 §A4).
 *
 * User pastes / picks a local path; backend scans it; wizard renders the
 * generated UI. In S4a this is a stub explaining the flow; S4b wires the
 * scanner call + wizard.
 */
import { FolderInput, AlertTriangle } from 'lucide-react';

export function McpLocalInstallView(): JSX.Element {
  return (
    <div className="space-y-3">
      <p className="font-label text-[11px] text-foreground/55">
        从本地路径安装第三方 MCP 服务器。请先把目标包下载到本地（可以是源码目录或解压后的 zip）；
        粘贴路径后，后端会扫描包内的 <code className="font-mono text-[10px]">literature-mcp.json</code> /
        <code className="font-mono text-[10px]">package.json</code> /
        <code className="font-mono text-[10px]">pyproject.toml</code>，
        自动识别启动命令、配置字段和所需凭证。
      </p>

      <div className="rounded-md border border-amber-300/40 bg-amber-50/40 dark:border-amber-700/40 dark:bg-amber-500/10 p-3 flex items-start gap-2">
        <AlertTriangle size={14} className="text-amber-600 dark:text-amber-300 mt-0.5 flex-shrink-0" />
        <div className="space-y-1">
          <p className="font-label text-[11px] text-amber-700 dark:text-amber-200 font-medium">
            安全提示
          </p>
          <ul className="font-label text-[11px] text-amber-700/80 dark:text-amber-200/80 list-disc list-inside space-y-0.5">
            <li>本地路径会被 normalize 后做安全检查；远端 URL 会被拒绝。</li>
            <li>扫描阶段**不会**执行任何包代码，只读取声明文件。</li>
            <li>启动包进程进行 list_tools 探测需要你在最后一步显式勾选信任。</li>
          </ul>
        </div>
      </div>

      <button
        type="button"
        disabled
        title="S4b 接入扫描向导后启用"
        className="inline-flex items-center gap-1.5 rounded-md bg-primary/10 px-3 py-1.5 font-label text-xs font-medium text-primary opacity-50 cursor-not-allowed"
      >
        <FolderInput size={12} /> 选择本地路径
      </button>

      <p className="font-label text-[10px] text-foreground/40">
        S4a 仅落地 IA 骨架。扫描向导、CredentialPicker、安装/探测流程将分别在 S4b / S4c 中开放。
      </p>
    </div>
  );
}

export default McpLocalInstallView;
