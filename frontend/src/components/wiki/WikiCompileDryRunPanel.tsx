import { AlertTriangle, RefreshCw, ShieldCheck, TerminalSquare } from 'lucide-react';
import { useState } from 'react';

import { cn } from '@/lib/utils';
import type { WikiCompileDryRunInputModel, WikiCompileDryRunModel } from '@/types/wiki';

interface WikiCompileDryRunPanelProps {
  result: WikiCompileDryRunModel | null;
  isLoading: boolean;
  error: string | null;
  isWikiEnabled: boolean;
  isWikiStale: boolean;
  onRun: (input: WikiCompileDryRunInputModel) => void;
}

export function WikiCompileDryRunPanel({
  result,
  isLoading,
  error,
  isWikiEnabled,
  isWikiStale,
  onRun,
}: WikiCompileDryRunPanelProps) {
  const [sourceId, setSourceId] = useState('');
  const [projectId, setProjectId] = useState('');
  const budget = result?.budget_summary ?? null;
  const formattedCost = budget
    ? `${budget.currency} ${budget.estimated_cost_usd.toFixed(6)}`
    : 'USD 0.000000';

  const handleRun = () => {
    onRun({
      source_id: sourceId.trim() || null,
      project_id: projectId.trim() || null,
    });
  };

  return (
    <section className="glass-card rounded-2xl border border-outline-variant/40 p-5 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-label text-[11px] uppercase tracking-[0.22em] text-foreground/35">Compile</span>
            <span className="rounded-full border border-emerald-200/80 bg-emerald-50 px-2.5 py-1 text-[10px] font-label uppercase tracking-[0.18em] text-emerald-700">
              safe mode
            </span>
            <span className="rounded-full border border-outline-variant/40 bg-surface-high px-2.5 py-1 text-[10px] font-label uppercase tracking-[0.18em] text-foreground/55">
              read-only
            </span>
          </div>
          <h2 className="mt-2 font-display text-2xl font-semibold text-foreground">Wiki Compile Dry-Run</h2>
          <p className="mt-2 max-w-2xl font-body text-sm leading-6 text-foreground/55">
            这里只做预编译推演，不触发真实写盘。先把 compile contract 接进工作台，让 planned paths、warnings 与当前 scope 一眼可见。
          </p>
        </div>

        <button
          type="button"
          onClick={handleRun}
          disabled={isLoading || !isWikiEnabled}
          className="inline-flex items-center gap-2 self-start rounded-xl border border-primary/25 bg-primary/8 px-3 py-2 text-xs font-label text-primary transition-colors hover:border-primary/40 hover:bg-primary/12 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw size={14} className={cn(isLoading && 'animate-spin')} />
          执行 dry-run 推演
        </button>
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/75 p-4">
          <div className="flex items-center gap-2 text-foreground">
            <ShieldCheck size={16} className="text-primary/65" />
            <h3 className="font-headline text-sm font-semibold">Compile scope</h3>
          </div>

          <div className="mt-4 space-y-3">
            <label className="block text-xs text-foreground/55">
              <span className="font-label uppercase tracking-[0.18em] text-foreground/35">source_id（可选）</span>
              <input
                value={sourceId}
                onChange={(event) => setSourceId(event.target.value)}
                placeholder="例如 source:paper-001"
                className="mt-2 w-full rounded-xl border border-outline-variant/40 bg-surface-high px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:outline-none focus:ring-2 focus:ring-primary/10"
              />
            </label>

            <label className="block text-xs text-foreground/55">
              <span className="font-label uppercase tracking-[0.18em] text-foreground/35">project_id（可选）</span>
              <input
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
                placeholder="例如 literature-assistant"
                className="mt-2 w-full rounded-xl border border-outline-variant/40 bg-surface-high px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:outline-none focus:ring-2 focus:ring-primary/10"
              />
            </label>

            {!isWikiEnabled ? (
              <div className="rounded-xl border border-amber-200/80 bg-amber-50 px-3 py-3 text-sm text-amber-800">
                Wiki 当前仍是 disabled 状态，所以这里只显示安全边界，不会触发 dry-run 请求。
              </div>
            ) : null}

            {isWikiStale ? (
              <div className="rounded-xl border border-amber-200/80 bg-amber-50 px-3 py-3 text-sm text-amber-800">
                当前 status 标记为 stale。你仍可先做 dry-run 观察，但建议结合 Doctor / Graph 面板一起判断。
              </div>
            ) : null}

            <div className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-3 text-xs leading-6 text-foreground/50">
              这一步只调用 `/api/wiki/compile` 的 dry-run contract slice：允许你验证 scope、planned paths 与 warnings，但不会写入页面正文。
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800/70 bg-slate-950/85 p-4 text-slate-100 shadow-inner">
          <div className="flex items-center gap-2 text-slate-100">
            <TerminalSquare size={16} className="text-emerald-300" />
            <h3 className="font-headline text-sm font-semibold">Dry-run console</h3>
          </div>

          {error ? (
            <div className="mt-4 rounded-xl border border-red-400/30 bg-red-500/10 px-3 py-3 text-sm text-red-100">
              {error}
            </div>
          ) : null}

          {isLoading ? (
            <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-8 text-center text-sm text-slate-300">
              正在内存中推演 compile 链路…
            </div>
          ) : result ? (
            <>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-400">planned</div>
                  <div className="mt-2 text-2xl font-semibold tabular-nums text-white">{result.planned_paths.length}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-400">written</div>
                  <div className="mt-2 text-2xl font-semibold tabular-nums text-white">{result.written_paths.length}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-400">tokens</div>
                  <div className="mt-2 text-2xl font-semibold tabular-nums text-white">{budget?.total_tokens ?? 0}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-400">cost</div>
                  <div className="mt-2 break-words text-lg font-semibold tabular-nums text-white">{formattedCost}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-400">warnings</div>
                  <div className="mt-2 text-2xl font-semibold tabular-nums text-white">{result.warnings.length}</div>
                </div>
              </div>

              <div className="mt-4 space-y-4">
                <div>
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-400">budget_estimate</div>
                  <div className="mt-2 grid gap-2 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-3 text-xs leading-6 text-slate-300 sm:grid-cols-2">
                    <div>input_tokens: <span className="font-mono text-slate-100">{budget?.input_tokens ?? 0}</span></div>
                    <div>output_tokens: <span className="font-mono text-slate-100">{budget?.output_tokens ?? 0}</span></div>
                    <div>pricing: <span className="font-mono text-slate-100">{budget?.pricing_source ?? 'not_configured'}</span></div>
                    <div>configured: <span className="font-mono text-slate-100">{budget?.pricing_configured ? 'true' : 'false'}</span></div>
                  </div>
                  {!budget?.pricing_configured ? (
                    <div className="mt-2 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2 text-xs leading-5 text-slate-400">
                      当前未配置模型价格，成本按 0 显示；token 估算仍可用于预算阈值判断。
                    </div>
                  ) : null}
                </div>

                <div>
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-400">planned_paths</div>
                  {result.planned_paths.length ? (
                    <ul className="mt-2 space-y-2 text-xs text-slate-200">
                      {result.planned_paths.map((path) => (
                        <li key={path} className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2 font-mono leading-5">
                          {path}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="mt-2 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-3 text-xs text-slate-400">
                      当前 contract slice 还没有返回具体 planned paths；这通常表示后端还处于 compile skeleton 阶段。
                    </div>
                  )}
                </div>

                <div>
                  <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-slate-400">
                    <AlertTriangle size={12} />
                    warnings
                  </div>
                  {result.warnings.length ? (
                    <ul className="mt-2 space-y-2 text-xs leading-6 text-amber-100">
                      {result.warnings.map((warning) => (
                        <li key={warning} className="rounded-lg border border-amber-400/20 bg-amber-500/10 px-3 py-2">
                          {warning}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="mt-2 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-3 text-xs text-slate-400">
                      本次 dry-run 没有返回 warnings。
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-8 text-center text-sm text-slate-400">
              还没有执行 dry-run。可先填写可选 scope，再触发一次安全推演。
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
