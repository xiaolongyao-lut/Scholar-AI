import { useEffect, useState } from 'react';
import { fetchPdfBackendStatus, type PDFBackendStatus } from '@/services/pdfBackendApi';

export function PDFBackendStatusCard(): JSX.Element {
  const [status, setStatus] = useState<PDFBackendStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchPdfBackendStatus()
      .then((s) => {
        if (!cancelled) {
          setStatus(s);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '状态获取失败');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="rounded border border-slate-200 dark:border-slate-700 p-3 text-sm text-slate-500">
        正在探测 PDF 解析后端...
      </div>
    );
  }
  if (error || !status) {
    return (
      <div className="rounded border border-amber-300 dark:border-amber-600 bg-amber-50 dark:bg-amber-900/20 p-3 text-sm text-amber-800 dark:text-amber-200">
        无法获取 PDF 解析后端状态:{error ?? '未知错误'}
      </div>
    );
  }

  const backendLabel = status.active_backend === 'pymupdf' ? 'PyMuPDF(默认)' : status.active_backend;
  const sourceLabel = (() => {
    switch (status.active_source) {
      case 'env':
        return `由环境变量 ${status.env_var_name}=${status.env_var_value ?? ''} 指定`;
      default:
        return '系统默认';
    }
  })();

  const installColor = status.marker_installed
    ? 'text-emerald-700 dark:text-emerald-300'
    : 'text-slate-500 dark:text-slate-400';
  const ocrLabel = status.ocr_selected_engine ?? status.ocr_configured_engine ?? '未选择';

  return (
    <div className="rounded border border-slate-200 dark:border-slate-700 p-3 text-sm space-y-2">
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="font-medium text-slate-900 dark:text-slate-100">当前 PDF 解析后端</span>
        <span className="font-mono text-slate-700 dark:text-slate-200">{backendLabel}</span>
        <span className="text-xs text-slate-500 dark:text-slate-400">({sourceLabel})</span>
      </div>
      <div className={`flex items-baseline gap-2 flex-wrap ${installColor}`}>
        <span>marker-pdf 可选工具:</span>
        {status.marker_installed ? (
          <span>
            已安装{status.marker_version ? `(${status.marker_version})` : ''}
          </span>
        ) : (
          <span>未安装</span>
        )}
      </div>
      {!status.marker_installed && (
        <div className="rounded bg-slate-50 dark:bg-slate-800/50 p-2 text-xs">
          <div className="text-slate-600 dark:text-slate-300 mb-1">需要结构化解析时再安装:</div>
          <code className="block font-mono text-slate-800 dark:text-slate-200 break-all">
            {status.marker_install_hint}
          </code>
        </div>
      )}
      {status.marker_installed && !status.feature_flag_enabled && status.active_source !== 'env' && (
        <div className="text-xs text-slate-500 dark:text-slate-400">
          marker 已安装但实验开关未打开。打开下方「PDF 结构化解析(marker)」后，新上传 PDF 可走结构化解析。
        </div>
      )}
      <div className="flex items-baseline gap-2 flex-wrap text-slate-700 dark:text-slate-200">
        <span>扫描件 OCR:</span>
        <span className="font-mono">{status.ocr_policy}</span>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          selected {ocrLabel} · lang {status.ocr_language} · source {status.ocr_config_source}
        </span>
      </div>
      {status.ocr_warning && (
        <div className="rounded bg-amber-50 dark:bg-amber-900/20 p-2 text-xs text-amber-800 dark:text-amber-200">
          {status.ocr_warning}
        </div>
      )}
      <div className="rounded bg-slate-50 dark:bg-slate-800/50 p-2 text-xs text-slate-600 dark:text-slate-300">
        {status.install_hint}
      </div>
    </div>
  );
}
