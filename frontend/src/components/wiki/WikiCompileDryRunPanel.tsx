import { AlertTriangle, FilePlus2, RefreshCw, ShieldCheck, Square, TerminalSquare } from 'lucide-react';
import { useState } from 'react';

import type {
  WikiCompileDryRunInputModel,
  WikiCompileDryRunModel,
  WikiManualPageInputModel,
  WikiManualPageKind,
  WikiManualPageStatus,
  WikiPageMutationModel,
} from '@/types/wiki';
import { formatWikiError, formatWikiPageLabel, formatWikiWarning } from './wikiDisplay';

interface WikiCompileDryRunPanelProps {
  result: WikiCompileDryRunModel | null;
  isLoading: boolean;
  error: string | null;
  isWikiEnabled: boolean;
  isWikiStale: boolean;
  manualResult: WikiPageMutationModel | null;
  manualError: string | null;
  isManualLoading: boolean;
  onRun: (input: WikiCompileDryRunInputModel) => void;
  onStop: () => void;
  onCreateManual: (input: WikiManualPageInputModel) => void;
  onStopManual: () => void;
}

function formatPricingSource(value: string | undefined): string {
  switch (value) {
    case 'configured':
    case 'manual':
    case 'settings':
      return '已配置';
    case 'catalog':
    case 'model_catalog':
      return '内置价格表';
    case 'not_configured':
    case undefined:
    case '':
      return '未配置';
    default:
      return '自定义配置';
  }
}

const MANUAL_KIND_OPTIONS: Array<{ value: WikiManualPageKind; label: string }> = [
  { value: 'concept', label: '概念' },
  { value: 'synthesis', label: '综合结论' },
  { value: 'exploration', label: '探索记录' },
  { value: 'experiment', label: '实验结果' },
  { value: 'question', label: '问题' },
  { value: 'paper', label: '论文摘要' },
];

const MANUAL_STATUS_OPTIONS: Array<{ value: WikiManualPageStatus; label: string }> = [
  { value: 'draft', label: '草稿' },
  { value: 'review', label: '待审' },
  { value: 'final', label: '确认知识' },
];

export function WikiCompileDryRunPanel({
  result,
  isLoading,
  error,
  isWikiEnabled,
  isWikiStale,
  manualResult,
  manualError,
  isManualLoading,
  onRun,
  onStop,
  onCreateManual,
  onStopManual,
}: WikiCompileDryRunPanelProps) {
  const [sourceId, setSourceId] = useState('');
  const [projectId, setProjectId] = useState('');
  const [allowWrite, setAllowWrite] = useState(false);
  const [manualTitle, setManualTitle] = useState('');
  const [manualKind, setManualKind] = useState<WikiManualPageKind>('concept');
  const [manualStatus, setManualStatus] = useState<WikiManualPageStatus>('draft');
  const [manualBody, setManualBody] = useState('');
  const budget = result?.budget_summary ?? null;
  const formattedCost = budget
    ? `${budget.currency} ${budget.estimated_cost_usd.toFixed(6)}`
    : 'USD 0.000000';

  const handleRun = () => {
    onRun({
      source_id: sourceId.trim() || null,
      project_id: projectId.trim() || null,
      allow_write: allowWrite,
    });
  };

  const handleCreateManual = () => {
    onCreateManual({
      title: manualTitle.trim(),
      kind: manualKind,
      status: manualStatus,
      body: manualBody.trim(),
    });
  };

  const compileActionLabel = allowWrite ? '写入 Wiki 页面' : '生成编译预案';

  return (
    <section className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-label text-[11px] tracking-[0.16em] text-foreground/35">编译与手动沉淀</span>
          </div>
          <h2 className="mt-1 font-headline text-base font-semibold text-foreground">Wiki 知识写入</h2>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-foreground/55">
            编译会把已注册来源转换成 Wiki 页面；手动录入用于把你已确认的知识直接沉淀成页面。
          </p>
        </div>

        <button
          type="button"
          onClick={isLoading ? onStop : handleRun}
          disabled={!isWikiEnabled}
          className="inline-flex items-center gap-1.5 self-start rounded-md border border-primary/25 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/15 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isLoading ? <Square size={13} /> : <RefreshCw size={13} />}
          {isLoading ? '停止' : compileActionLabel}
        </button>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <div className="space-y-4">
          <div className="rounded-md border border-outline-variant/50 bg-surface-low p-4">
            <div className="flex items-center gap-2 text-foreground">
              <ShieldCheck size={16} className="text-primary/65" />
              <h3 className="font-headline text-sm font-semibold">来源编译</h3>
            </div>
            <p className="mt-2 text-xs leading-5 text-foreground/55">
              当前接口按 Wiki 注册表中的来源生成预案；只填写项目不会筛选数据源，后端会把 project_id 作为前向兼容字段接收。
            </p>

            <div className="mt-4 space-y-3">
              <label className="block text-xs text-foreground/55">
                <span className="font-label text-[11px] text-foreground/45">来源 ID（可选）</span>
                <input
                  value={sourceId}
                  onChange={(event) => setSourceId(event.target.value)}
                  placeholder="source_id，例如 paper-source-003"
                  className="mt-1.5 w-full rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
                />
              </label>

              <label className="block text-xs text-foreground/55">
                <span className="font-label text-[11px] text-foreground/45">项目 ID（可选）</span>
                <input
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                  placeholder="project_id，仅作兼容记录"
                  className="mt-1.5 w-full rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
                />
              </label>

              <label className="flex items-start gap-2 rounded-md border border-outline-variant/40 bg-surface-lowest px-3 py-2 text-xs text-foreground/65">
                <input
                  type="checkbox"
                  checked={allowWrite}
                  onChange={(event) => setAllowWrite(event.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  直接写入 Wiki 页面。关闭时只生成预案和预算，不改动页面文件。
                </span>
              </label>

              {!isWikiEnabled ? (
                <div className="rounded-md border border-amber-200/80 bg-amber-50 px-3 py-3 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
                  Wiki 当前未启用，开启后可编译或录入知识。
                </div>
              ) : null}

              {isWikiStale ? (
                <div className="rounded-md border border-amber-200/80 bg-amber-50 px-3 py-3 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
                  当前索引需要重新生成，建议写入后刷新状态、图谱和检索索引。
                </div>
              ) : null}
            </div>
          </div>

          <div className="rounded-md border border-outline-variant/50 bg-surface-low p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2 text-foreground">
                <FilePlus2 size={16} className="shrink-0 text-primary/65" />
                <h3 className="font-headline text-sm font-semibold">手动录入确认知识</h3>
              </div>
              <button
                type="button"
                onClick={isManualLoading ? onStopManual : handleCreateManual}
                disabled={!isWikiEnabled}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-2.5 py-1.5 text-[11px] font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isManualLoading ? <Square size={12} /> : <FilePlus2 size={12} />}
                {isManualLoading ? '停止' : '沉淀为 Wiki'}
              </button>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label className="block text-xs text-foreground/55 sm:col-span-2">
                <span className="font-label text-[11px] text-foreground/45">标题</span>
                <input
                  value={manualTitle}
                  onChange={(event) => setManualTitle(event.target.value)}
                  placeholder="例如：DED-LB 晶粒细化判断规则"
                  className="mt-1.5 w-full rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
                />
              </label>
              <label className="block text-xs text-foreground/55">
                <span className="font-label text-[11px] text-foreground/45">类型</span>
                <select
                  value={manualKind}
                  onChange={(event) => setManualKind(event.target.value as WikiManualPageKind)}
                  className="mt-1.5 w-full rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none"
                >
                  {MANUAL_KIND_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label className="block text-xs text-foreground/55">
                <span className="font-label text-[11px] text-foreground/45">状态</span>
                <select
                  value={manualStatus}
                  onChange={(event) => setManualStatus(event.target.value as WikiManualPageStatus)}
                  className="mt-1.5 w-full rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none"
                >
                  {MANUAL_STATUS_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label className="block text-xs text-foreground/55 sm:col-span-2">
                <span className="font-label text-[11px] text-foreground/45">知识正文</span>
                <textarea
                  value={manualBody}
                  onChange={(event) => setManualBody(event.target.value)}
                  rows={6}
                  placeholder="写入你已经确认的结论、边界条件、证据说明或操作规则。"
                  className="mt-1.5 min-h-32 w-full resize-y rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm leading-6 text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
                />
              </label>
            </div>

            {manualError ? (
              <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
                {formatWikiError(manualError, '手动录入失败，请稍后重试。')}
              </div>
            ) : null}
            {manualResult ? (
              <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300">
                已写入 Wiki：{manualResult.slug}
              </div>
            ) : null}
          </div>
        </div>

        <div className="rounded-md border border-slate-800/70 bg-slate-950/85 p-4 text-slate-100 shadow-inner">
          <div className="flex items-center gap-2 text-slate-100">
            <TerminalSquare size={16} className="text-emerald-300" />
            <h3 className="font-headline text-sm font-semibold">编译结果</h3>
          </div>

          {error ? (
            <div className="mt-4 rounded-md border border-red-400/30 bg-red-500/10 px-3 py-3 text-sm text-red-100">
              {formatWikiError(error, '生成编译预案失败，请稍后重试。')}
            </div>
          ) : null}

          {isLoading ? (
            <div className="mt-4 rounded-md border border-slate-800 bg-slate-900/70 px-3 py-8 text-center text-sm text-slate-300">
              正在处理 Wiki 编译…
            </div>
          ) : result ? (
            <>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                <ResultMetric label="计划页面" value={result.planned_paths.length} />
                <ResultMetric label={result.dry_run ? '将更新' : '已写入'} value={result.dry_run ? result.written_paths.length : result.created + result.updated} />
                <ResultMetric label="模型用量" value={budget?.total_tokens ?? 0} />
                <ResultMetric label="预算" value={formattedCost} compact />
                <ResultMetric label="告警" value={result.warnings.length} />
              </div>

              <div className="mt-4 space-y-4">
                <div>
                  <div className="text-[10px] tracking-[0.18em] text-slate-400">预算估算</div>
                  <div className="mt-2 grid gap-2 rounded-md border border-slate-800 bg-slate-900/70 px-3 py-3 text-xs leading-6 text-slate-300 sm:grid-cols-2">
                    <div>输入用量：<span className="font-mono text-slate-100">{budget?.input_tokens ?? 0}</span></div>
                    <div>输出用量：<span className="font-mono text-slate-100">{budget?.output_tokens ?? 0}</span></div>
                    <div>价格来源：<span className="text-slate-100">{formatPricingSource(budget?.pricing_source)}</span></div>
                    <div>价格配置：<span className="font-mono text-slate-100">{budget?.pricing_configured ? '已配置' : '未配置'}</span></div>
                  </div>
                  {!budget?.pricing_configured ? (
                    <div className="mt-2 rounded-md border border-slate-800 bg-slate-900/70 px-3 py-2 text-xs leading-5 text-slate-400">
                      当前未配置模型价格，成本按 0 显示；模型用量估算仍可用于预算阈值判断。
                    </div>
                  ) : null}
                </div>

                <div>
                  <div className="text-[10px] tracking-[0.18em] text-slate-400">计划页面</div>
                  {result.planned_paths.length ? (
                    <ul className="mt-2 space-y-2 text-xs text-slate-200">
                      {result.planned_paths.map((path, index) => (
                        <li key={path} className="rounded-md border border-slate-800 bg-slate-900/70 px-3 py-2 leading-5">
                          {formatWikiPageLabel(path, `计划页面 ${index + 1}`)}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="mt-2 rounded-md border border-slate-800 bg-slate-900/70 px-3 py-3 text-xs text-slate-400">
                      暂未返回具体页面。没有注册来源时，先用手动录入或导入文献后再编译。
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
                      {result.warnings.map((warning, index) => (
                        <li key={warning} className="rounded-md border border-amber-400/20 bg-amber-500/10 px-3 py-2">
                          {formatWikiWarning(warning) || `告警 ${index + 1}`}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="mt-2 rounded-md border border-slate-800 bg-slate-900/70 px-3 py-3 text-xs text-slate-400">
                      本次没有返回告警。
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="mt-4 rounded-md border border-slate-800 bg-slate-900/70 px-3 py-8 text-center text-sm text-slate-400">
              还没有生成编译预案。
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function ResultMetric({ label, value, compact = false }: { label: string; value: number | string; compact?: boolean }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-900/70 px-3 py-3">
      <div className="text-[10px] tracking-[0.18em] text-slate-400">{label}</div>
      <div className={compact ? 'mt-2 break-words text-lg font-semibold tabular-nums text-white' : 'mt-2 text-2xl font-semibold tabular-nums text-white'}>
        {value}
      </div>
    </div>
  );
}
