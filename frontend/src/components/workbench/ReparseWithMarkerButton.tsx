/**
 * A16b "重新解析以获取结构化索引" button.
 *
 * Triggers POST /resources/projects/{project_id}/reparse-with-marker. Shows
 * pending state, success counts, and per-material errors. Intended to live
 * on a project workbench / knowledge base page; this component just
 * renders the button + status, the parent passes the project_id.
 *
 * Per A16 guidance: this is the PRIMARY workflow for upgrading a project's
 * chunk metadata after enabling marker. "Clear chunk cache" is intentionally
 * NOT exposed here — it's a destructive operation that loses bbox/table_csv
 * irreversibly because doc_store doesn't store them.
 */
import { useState } from 'react';
import { reparseProjectWithMarker, type ReparseResult } from '@/services/reparseApi';

export interface ReparseWithMarkerButtonProps {
  projectId: string;
  /** Optional callback after a successful reparse so caller can refresh state. */
  onComplete?: (result: ReparseResult) => void;
}

export function ReparseWithMarkerButton({
  projectId,
  onComplete,
}: ReparseWithMarkerButtonProps): JSX.Element {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ReparseResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleClick(): Promise<void> {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await reparseProjectWithMarker(projectId);
      setResult(r);
      onComplete?.(r);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '重新解析失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className={
          'rounded px-3 py-1.5 text-sm font-medium transition '
          + (busy
            ? 'bg-slate-200 dark:bg-slate-700 text-slate-500 cursor-wait'
            : 'bg-primary text-primary-foreground hover:bg-primary/90')
        }
      >
        {busy ? '正在重新解析项目 PDF...' : '重新解析以获取结构化索引'}
      </button>
      <div className="text-xs text-slate-500 dark:text-slate-400">
        用当前 PDF 解析后端(见 Settings → 实验性功能)重新提取项目里每篇 PDF 的文本、表格、
        公式和章节层级。已索引的旧 chunks 会被替换;源 PDF 文件不动。
        marker 后端首次解析每篇约 5-15 分钟,期间界面可关闭后台继续。
      </div>
      {error && (
        <div className="rounded border border-rose-300 dark:border-rose-700 bg-rose-50 dark:bg-rose-900/20 p-2 text-xs text-rose-800 dark:text-rose-200">
          {error}
        </div>
      )}
      {result && (
        <div className="rounded border border-slate-200 dark:border-slate-700 p-2 text-xs space-y-1">
          <div className="font-medium text-slate-900 dark:text-slate-100">
            重新解析完成(后端 = {result.backend})
          </div>
          <div>
            重新解析 <span className="font-mono">{result.reparsed_count}</span> 篇 ·
            跳过 <span className="font-mono">{result.skipped_count}</span> 篇 ·
            失败 <span className="font-mono">{result.failed_count}</span> 篇
          </div>
          {result.failed.length > 0 && (
            <details>
              <summary className="cursor-pointer text-rose-700 dark:text-rose-300">
                失败明细 ({result.failed.length})
              </summary>
              <ul className="ml-4 mt-1 list-disc space-y-0.5">
                {result.failed.slice(0, 20).map((f) => (
                  <li key={f.material_id}>
                    <span className="font-mono">{f.material_id}</span>:{f.error}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {result.skipped.length > 0 && (
            <details>
              <summary className="cursor-pointer text-amber-700 dark:text-amber-300">
                跳过明细 ({result.skipped.length})
              </summary>
              <ul className="ml-4 mt-1 list-disc space-y-0.5">
                {result.skipped.slice(0, 20).map((s) => (
                  <li key={s.material_id}>
                    <span className="font-mono">{s.material_id}</span>:{
                      s.reason === 'source_missing' ? '源文件缺失' : '非 PDF'
                    }
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
