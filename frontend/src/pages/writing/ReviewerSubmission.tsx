import React, { useState } from 'react';
import { ShieldCheck, CheckCircle2, AlertTriangle, XCircle, Clock, Send, ChevronRight, FileCheck } from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { PageHeader } from '@/components/common/PageHeader';
import { SectionCard } from '@/components/common/SectionCard';
import { StatusPill, type StatusTone } from '@/components/common/StatusPill';

type CheckStatus = 'pass' | 'warn' | 'fail' | 'pending';

interface CheckItem {
  id: string;
  label: string;
  description: string;
  status: CheckStatus;
}

interface JournalOption {
  id: string;
  name: string;
  impactFactor?: string;
  reviewCycle?: string;
  acceptanceRate?: string;
}

const MOCK_CHECKS: CheckItem[] = [
  { id: 'c1', label: 'writing.reviewer.check_format', description: 'writing.reviewer.check_format_desc', status: 'pass' },
  { id: 'c2', label: 'writing.reviewer.check_citations', description: 'writing.reviewer.check_citations_desc', status: 'pass' },
  { id: 'c3', label: 'writing.reviewer.check_figures', description: 'writing.reviewer.check_figures_desc', status: 'warn' },
  { id: 'c4', label: 'writing.reviewer.check_wordcount', description: 'writing.reviewer.check_wordcount_desc', status: 'pass' },
  { id: 'c5', label: 'writing.reviewer.check_plagiarism', description: 'writing.reviewer.check_plagiarism_desc', status: 'pending' },
  { id: 'c6', label: 'writing.reviewer.check_language', description: 'writing.reviewer.check_language_desc', status: 'warn' },
  { id: 'c7', label: 'writing.reviewer.check_reproducibility', description: 'writing.reviewer.check_reproducibility_desc', status: 'fail' },
];

const statusConfigBase: Record<CheckStatus, { icon: React.ElementType; tone: StatusTone; labelKey: string }> = {
  pass: { icon: CheckCircle2, tone: 'success', labelKey: 'writing.reviewer.status_pass' },
  warn: { icon: AlertTriangle, tone: 'warning', labelKey: 'writing.reviewer.status_warn' },
  fail: { icon: XCircle, tone: 'danger', labelKey: 'writing.reviewer.status_fail' },
  pending: { icon: Clock, tone: 'info', labelKey: 'writing.reviewer.status_pending' },
};

const JOURNAL_OPTIONS: JournalOption[] = [
  { id: 'ai-generic-review', name: 'AI 通用审稿（不指定期刊）', reviewCycle: '即时', acceptanceRate: '—' },
  { id: 'nature-communications', name: 'Nature Communications', impactFactor: '16.6', reviewCycle: '4-8 周', acceptanceRate: '7-9%' },
  { id: 'advanced-materials', name: 'Advanced Materials', impactFactor: '27.4', reviewCycle: '3-6 周', acceptanceRate: '10-15%' },
  { id: 'journal-of-materials-processing-tech', name: 'Journal of Materials Processing Technology', impactFactor: '7.1', reviewCycle: '6-10 周', acceptanceRate: '20-30%' },
];

/**
 * 审稿与投稿 — Long-Run v2 Slice I rebuild.
 * 视觉参考: `07_object_surfaces/21_writing_reviewer_submission.png`
 */
export function ReviewerSubmission() {
  const { t } = useI18n();
  const [selectedJournal, setSelectedJournal] = useState('ai-generic-review');

  const selectedJournalMeta = JOURNAL_OPTIONS.find((option) => option.id === selectedJournal);

  const passCount = MOCK_CHECKS.filter((c) => c.status === 'pass').length;
  const totalCount = MOCK_CHECKS.length;
  const score = Math.round((passCount / totalCount) * 100);
  const ringColor = score >= 70 ? 'text-emerald-500' : score >= 40 ? 'text-amber-500' : 'text-red-500';

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-6 py-4">
        <PageHeader
          icon={<ShieldCheck size={18} />}
          title={t('writing.reviewer.title')}
          subtitle={t('writing.reviewer.subtitle')}
          className="mb-0"
          actions={
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 font-label text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
              <Send size={13} />
              {t('writing.reviewer.prepare_submission')}
            </button>
          }
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-6 py-5">
        {/* Top row: readiness ring + journal selector */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <SectionCard className="flex flex-col items-center justify-center text-center" bodyClassName="flex flex-col items-center gap-2 py-4">
            <div className="relative h-24 w-24">
              <svg viewBox="0 0 100 100" className="-rotate-90">
                <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" className="text-surface-high" strokeWidth="8" />
                <circle
                  cx="50" cy="50" r="42" fill="none" stroke="currentColor"
                  className={ringColor}
                  strokeWidth="8"
                  strokeDasharray={`${score * 2.64} 264`}
                  strokeLinecap="round"
                />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="font-headline text-2xl font-bold text-foreground">{score}</span>
              </div>
            </div>
            <p className="font-label text-xs text-foreground/55">{t('writing.reviewer.readiness')}</p>
            <p className="font-label text-[11px] text-foreground/45">
              已通过 {passCount} / {totalCount} 项检查
            </p>
          </SectionCard>

          <SectionCard
            title={t('writing.reviewer.target_journal')}
            icon={<FileCheck size={14} />}
            className="lg:col-span-2"
          >
            <select
              value={selectedJournal}
              onChange={(e) => setSelectedJournal(e.target.value)}
              title={t('writing.reviewer.target_journal')}
              aria-label={t('writing.reviewer.target_journal')}
              className="w-full rounded-md border border-outline-variant/60 bg-surface-low px-3 py-2 text-sm font-label text-foreground transition-colors focus:border-primary/40 focus:outline-none"
            >
              {JOURNAL_OPTIONS.map((option) => (
                <option key={option.id} value={option.id}>{option.name}</option>
              ))}
            </select>
            <div className="mt-3 flex flex-wrap items-center gap-3 font-label text-[10px] text-foreground/55">
              <span>{t('reviewer.impact_factor')}: {selectedJournalMeta?.impactFactor ?? '—'}</span>
              <span>{t('writing.reviewer.review_cycle')}: {selectedJournalMeta?.reviewCycle ?? t('reviewer.review_cycle_value')}</span>
              <span>{t('writing.reviewer.acceptance_rate')}: {selectedJournalMeta?.acceptanceRate ?? '—'}</span>
            </div>
          </SectionCard>
        </div>

        {/* Checklist */}
        <SectionCard
          title={t('writing.reviewer.checklist_title')}
          icon={<FileCheck size={14} />}
          headerRight={
            <StatusPill tone="neutral">{passCount}/{totalCount} {t('writing.reviewer.passed')}</StatusPill>
          }
        >
          <ul className="divide-y divide-outline-variant/30">
            {MOCK_CHECKS.map((check, i) => {
              const cfg = statusConfigBase[check.status];
              return (
                <motion.li
                  key={check.id}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.03 }}
                  className="group flex cursor-pointer items-center gap-3 px-1 py-2 transition-colors hover:bg-surface-default/40"
                >
                  <div className={cn(
                    'flex h-7 w-7 shrink-0 items-center justify-center rounded-md',
                    cfg.tone === 'success' ? 'bg-emerald-50 dark:bg-emerald-950/30' :
                    cfg.tone === 'warning' ? 'bg-amber-50 dark:bg-amber-950/30' :
                    cfg.tone === 'danger' ? 'bg-red-50 dark:bg-red-950/30' :
                    'bg-sky-50 dark:bg-sky-950/30',
                  )}>
                    <cfg.icon size={14} className={cn(
                      cfg.tone === 'success' ? 'text-emerald-600' :
                      cfg.tone === 'warning' ? 'text-amber-600' :
                      cfg.tone === 'danger' ? 'text-red-600' :
                      'text-sky-600',
                    )} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h4 className="font-label text-sm font-medium text-foreground">{t(check.label)}</h4>
                    <p className="font-body text-[11px] text-foreground/50">{t(check.description)}</p>
                  </div>
                  <StatusPill tone={cfg.tone}>{t(cfg.labelKey)}</StatusPill>
                  <ChevronRight size={13} className="text-foreground/25 opacity-0 transition-opacity group-hover:opacity-100" />
                </motion.li>
              );
            })}
          </ul>
        </SectionCard>
      </div>
    </div>
  );
}
