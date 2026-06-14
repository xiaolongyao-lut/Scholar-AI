/** Local install entry view wired to the install wizard. */
import React, { useState } from 'react';
import { FolderInput, AlertTriangle } from 'lucide-react';
import McpInstallWizard from './McpInstallWizard';

export function McpLocalInstallView(): JSX.Element {
  const [open, setOpen] = useState(false);
  const [initialPath, setInitialPath] = useState('');

  return (
    <div className="space-y-3">
      <p className="font-label text-[11px] text-foreground/55">从本地路径安装。</p>

      <div className="rounded-md border border-amber-300/40 bg-amber-50/40 dark:border-amber-700/40 dark:bg-amber-500/10 p-3 flex items-start gap-2">
        <AlertTriangle size={14} className="text-amber-600 dark:text-amber-300 mt-0.5 flex-shrink-0" />
        <div className="space-y-1">
          <p className="font-label text-[11px] text-amber-700 dark:text-amber-200 font-medium">
            安全提示
          </p>
          <ul className="font-label text-[11px] text-amber-700/80 dark:text-amber-200/80 list-disc list-inside space-y-0.5">
            <li>仅接受本地路径。</li>
            <li>扫描只读声明文件。</li>
            <li>探测前需要勾选信任。</li>
          </ul>
        </div>
      </div>

      <div className="flex items-end gap-2">
        <label className="flex-1">
          <span className="font-label text-[11px] text-foreground/55">本地路径(可选,向导内也可修改)</span>
          <input
            type="text"
            value={initialPath}
            onChange={(e) => setInitialPath(e.target.value)}
            placeholder="选择或粘贴本机 MCP 包目录"
            className="mt-1 w-full px-2 py-1.5 rounded border border-outline-variant bg-surface-lowest text-foreground text-xs"
          />
        </label>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary/10 px-3 py-1.5 font-label text-xs font-medium text-primary hover:bg-primary/15"
        >
          <FolderInput size={12} /> 开始扫描
        </button>
      </div>

      <McpInstallWizard
        open={open}
        initialPath={initialPath}
        onClose={() => setOpen(false)}
      />
    </div>
  );
}

export default McpLocalInstallView;
