import { AlertTriangle, CheckCircle2, RefreshCw, ShieldAlert, Wrench } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { DoctorSeverity, WikiDoctorCheckModel, WikiDoctorModel } from '@/types/wiki';

interface DoctorReportPanelProps {
  doctor: WikiDoctorModel | null;
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
}

const STATUS_TONE: Record<DoctorSeverity, string> = {
  ok: 'bg-emerald-50 text-emerald-700 border-emerald-200/80 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300',
  warning: 'bg-amber-50 text-amber-700 border-amber-200/80 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300',
  error: 'bg-red-50 text-red-700 border-red-200/80 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300',
};

function CheckIcon({ status }: { status: DoctorSeverity }) {
  if (status === 'ok') {
    return <CheckCircle2 size={14} className="text-emerald-600 dark:text-emerald-300" />;
  }
  if (status === 'warning') {
    return <AlertTriangle size={14} className="text-amber-600 dark:text-amber-300" />;
  }
  return <ShieldAlert size={14} className="text-red-600 dark:text-red-300" />;
}

function MetricsList({ check }: { check: WikiDoctorCheckModel }) {
  const metrics = Object.entries(check.metrics).slice(0, 4);
  if (metrics.length === 0) {
    return null;
  }

  return (
    <dl className="mt-3 grid gap-2 sm:grid-cols-2">
      {metrics.map(([key, value]) => (
        <div key={key} className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-2">
          <dt className="font-label text-[10px] tracking-[0.14em] text-foreground/30">{metricLabel(key)}</dt>
          <dd className="mt-1 text-xs text-foreground/65">{String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function formatDoctorWarning(warning: string): string {
  if (warning.includes('Wiki integration is disabled')) {
    return 'Wiki 集成尚未启用。';
  }
  return warning;
}

function severityLabel(status: DoctorSeverity): string {
  if (status === 'ok') return '正常';
  if (status === 'warning') return '提醒';
  return '异常';
}

function metricLabel(key: string): string {
  const labels: Record<string, string> = {
    pages: '页面',
    checks: '检查项',
    expected_nodes: '应有节点',
    actual_nodes: '实际节点',
  };
  return labels[key] ?? key;
}

function checkLabel(label: string): string {
  const labels: Record<string, string> = {
    'Graph index': '图谱索引',
  };
  return labels[label] ?? label;
}

export function DoctorReportPanel({ doctor, isLoading, error, onRefresh }: DoctorReportPanelProps) {
  const report = doctor?.structuredReport;
  const checks = report?.checks ?? [];

  return (
    <section className="glass-card rounded-2xl border border-outline-variant/40 p-5 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="font-label text-[11px] uppercase tracking-[0.22em] text-foreground/35">健康诊断</div>
          <h2 className="mt-2 font-display text-2xl font-semibold text-foreground">健康诊断报告</h2>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="inline-flex items-center gap-2 self-start rounded-xl border border-outline-variant/40 bg-surface-high px-3 py-2 text-xs font-label text-foreground/70 transition-colors hover:border-primary/30 hover:text-foreground disabled:cursor-wait disabled:opacity-60"
        >
          <RefreshCw size={14} className={cn(isLoading && 'animate-spin')} />
          刷新诊断
        </button>
      </div>

      {error ? (
        <div className="mt-5 rounded-xl border border-red-200/80 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
          {error}
        </div>
      ) : null}

      {doctor?.warnings.length ? (
        <div className="mt-5 rounded-2xl border border-amber-200/80 bg-amber-50/80 px-4 py-4 dark:border-amber-700/40 dark:bg-amber-500/15">
          <div className="font-label text-[11px] tracking-[0.16em] text-amber-700/80 dark:text-amber-300/80">诊断告警</div>
          <ul className="mt-3 space-y-2 text-sm leading-6 text-amber-800 dark:text-amber-300">
            {doctor.warnings.map((warning) => (
              <li key={warning} className="flex items-start gap-2">
                <AlertTriangle size={14} className="mt-1 flex-shrink-0" />
                <span>{formatDoctorWarning(warning)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report ? (
        <>
          <div className="mt-5 grid gap-3 sm:grid-cols-4">
            <div className={cn('rounded-2xl border px-4 py-4', STATUS_TONE[report.status])}>
              <div className="font-label text-[10px] tracking-[0.16em]">总览</div>
              <div className="mt-2 font-display text-2xl font-semibold">{severityLabel(report.status)}</div>
            </div>
            {Object.entries(report.counts).map(([key, value]) => (
              <div key={key} className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 px-4 py-4">
                <div className="font-label text-[10px] tracking-[0.14em] text-foreground/35">{metricLabel(key)}</div>
                <div className="mt-2 font-display text-2xl font-semibold text-foreground tabular-nums">{value}</div>
              </div>
            ))}
          </div>

          <div className="mt-5 space-y-3">
            {checks.map((check) => (
              <article key={check.id} className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/80 px-4 py-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <CheckIcon status={check.status} />
                      <h3 className="font-headline text-sm font-semibold text-foreground">{checkLabel(check.label)}</h3>
                      <span className={cn('rounded-full border px-2.5 py-1 text-[10px] font-label tracking-[0.14em]', STATUS_TONE[check.status])}>
                        {severityLabel(check.status)}
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-foreground/65">{check.summary}</p>
                    {check.detail ? (
                      <p className="mt-2 whitespace-pre-wrap text-xs leading-6 text-foreground/45">{check.detail}</p>
                    ) : null}
                    <MetricsList check={check} />
                  </div>

                  {check.actions.length ? (
                    <div className="w-full shrink-0 rounded-2xl border border-outline-variant/30 bg-surface-high/70 px-4 py-3 lg:w-64">
                      <div className="flex items-center gap-2 font-label text-[10px] uppercase tracking-[0.18em] text-foreground/35">
                        <Wrench size={12} />
                        处理建议
                      </div>
                      <div className="mt-3 space-y-3">
                        {check.actions.map((action) => (
                          <div key={`${check.id}-${action.command}`}>
                            <div className="font-mono text-[11px] text-foreground/65">{action.command}</div>
                            <div className="mt-1 text-xs leading-5 text-foreground/50">{action.description}</div>
                            <div className="mt-1 text-[10px] font-label uppercase tracking-[0.16em] text-primary/70">
                              {action.safe_auto_repair ? '可自动修复' : '需手动处理'}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              </article>
            ))}

            {!isLoading && checks.length === 0 && !error ? (
              <div className="rounded-2xl border border-outline-variant/30 bg-surface-high/60 px-4 py-8 text-center text-sm text-foreground/45">
                当前诊断没有结构化检查项。
              </div>
            ) : null}
          </div>
        </>
      ) : null}

      {isLoading ? (
        <div className="mt-5 rounded-2xl border border-outline-variant/30 bg-surface-high/60 px-4 py-8 text-center text-sm text-foreground/45">
          正在读取 Wiki 诊断…
        </div>
      ) : null}
    </section>
  );
}
