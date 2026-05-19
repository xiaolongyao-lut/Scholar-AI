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
            <span className="font-label text-[11px] tracking-[0.18em] text-foreground/35">编译计划</span>
          </div>
          <h2 className="mt-2 font-display text-2xl font-semibold text-foreground">Wiki 编译</h2>
        </div>

        <button
          type="button"
          onClick={handleRun}
          disabled={isLoading || !isWikiEnabled}
          className="inline-flex items-center gap-2 self-start rounded-xl border border-primary/25 bg-primary/8 px-3 py-2 text-xs font-label text-primary transition-colors hover:border-primary/40 hover:bg-primary/12 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw size={14} className={cn(isLoading && 'animate-spin')} />
          生成编译计划
        </button>
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/75 p-4">
          <div className="flex items-center gap-2 text-foreground">
            <ShieldCheck size={16} className="text-primary/65" />
            <h3 className="font-headline text-sm font-semibold">编译范围</h3>
          </div>

          <div className="mt-4 space-y-3">
            <label className="block text-xs text-foreground/55">
              <span className="font-label tracking-[0.12em] text-foreground/35">来源（可选）</span>
              <input
                value={sourceId}
                onChange={(event) => setSourceId(event.target.value)}
                placeholder="例如：论文 A"
                className="mt-2 w-full rounded-xl border border-outline-variant/40 bg-surface-high px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:outline-none focus:ring-2 focus:ring-primary/10"
              />
            </label>

            <label className="block text-xs text-foreground/55">
              <span className="font-label tracking-[0.12em] text-foreground/35">项目（可选）</span>
              <input
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
                placeholder="例如：文献助手"
                className="mt-2 w-full rounded-xl border border-outline-variant/40 bg-surface-high px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:outline-none focus:ring-2 focus:ring-primary/10"
              />
            </label>

            {!isWikiEnabled ? (
              <div className="rounded-xl border border-amber-200/80 bg-amber-50 px-3 py-3 text-sm text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
                Wiki 当前未启用，开启后可生成编译计划。
              </div>
            ) : null}

            {isWikiStale ? (
              <div className="rounded-xl border border-amber-200/80 bg-amber-50 px-3 py-3 text-sm text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
                当前索引需要重新生成，建议先刷新状态与知识图谱。
              </div>
            ) : null}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800/70 bg-slate-950/85 p-4 text-slate-100 shadow-inner">
          <div className="flex items-center gap-2 text-slate-100">
            <TerminalSquare size={16} className="text-emerald-300" />
            <h3 className="font-headline text-sm font-semibold">编译计划结果</h3>
          </div>

          {error ? (
            <div className="mt-4 rounded-xl border border-red-400/30 bg-red-500/10 px-3 py-3 text-sm text-red-100">
              {error}
            </div>
          ) : null}

          {isLoading ? (
            <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-8 text-center text-sm text-slate-300">
              正在生成编译计划…
            </div>
          ) : result ? (
            <>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3">
                  <div className="text-[10px] tracking-[0.18em] text-slate-400">计划页面</div>
                  <div className="mt-2 text-2xl font-semibold tabular-nums text-white">{result.planned_paths.length}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3">
                  <div className="text-[10px] tracking-[0.18em] text-slate-400">将更新</div>
                  <div className="mt-2 text-2xl font-semibold tabular-nums text-white">{result.written_paths.length}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3">
                  <div className="text-[10px] tracking-[0.18em] text-slate-400">Token</div>
                  <div className="mt-2 text-2xl font-semibold tabular-nums text-white">{budget?.total_tokens ?? 0}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3">
                  <div className="text-[10px] tracking-[0.18em] text-slate-400">预算</div>
                  <div className="mt-2 break-words text-lg font-semibold tabular-nums text-white">{formattedCost}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3">
                  <div className="text-[10px] tracking-[0.18em] text-slate-400">告警</div>
                  <div className="mt-2 text-2xl font-semibold tabular-nums text-white">{result.warnings.length}</div>
                </div>
              </div>

              <div className="mt-4 space-y-4">
                <div>
                  <div className="text-[10px] tracking-[0.18em] text-slate-400">预算估算</div>
                  <div className="mt-2 grid gap-2 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-3 text-xs leading-6 text-slate-300 sm:grid-cols-2">
                    <div>输入 Token：<span className="font-mono text-slate-100">{budget?.input_tokens ?? 0}</span></div>
                    <div>输出 Token：<span className="font-mono text-slate-100">{budget?.output_tokens ?? 0}</span></div>
                    <div>价格来源：<span className="font-mono text-slate-100">{budget?.pricing_source ?? '未配置'}</span></div>
                    <div>价格配置：<span className="font-mono text-slate-100">{budget?.pricing_configured ? '已配置' : '未配置'}</span></div>
                  </div>
                  {!budget?.pricing_configured ? (
                    <div className="mt-2 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2 text-xs leading-5 text-slate-400">
                      当前未配置模型价格，成本按 0 显示；token 估算仍可用于预算阈值判断。
                    </div>
                  ) : null}
                </div>

                <div>
                  <div className="text-[10px] tracking-[0.18em] text-slate-400">计划页面</div>
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
                      暂未返回具体页面，编译器可能仍在准备。
                    </div>
                  )}
                </div>

                <div>
                  <div className="flex items-center gap-2 text-[10px] tracking-[0.14em] text-slate-400">
                    <AlertTriangle size={12} />
                    告警
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
                      本次没有返回告警。
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-8 text-center text-sm text-slate-400">
              还没有生成编译计划。
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
