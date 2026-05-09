import React, { useState } from 'react';
import { ShieldCheck, CheckCircle2, AlertTriangle, XCircle, Clock, Send, ChevronRight, FileCheck, BarChart3 } from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';

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

const statusConfigBase: Record<CheckStatus, { icon: React.ElementType; color: string; bg: string; labelKey: string }> = {
  pass: { icon: CheckCircle2, color: 'text-emerald-600', bg: 'bg-emerald-50', labelKey: 'writing.reviewer.status_pass' },
  warn: { icon: AlertTriangle, color: 'text-amber-600', bg: 'bg-amber-50', labelKey: 'writing.reviewer.status_warn' },
  fail: { icon: XCircle, color: 'text-red-600', bg: 'bg-red-50', labelKey: 'writing.reviewer.status_fail' },
  pending: { icon: Clock, color: 'text-blue-600', bg: 'bg-blue-50', labelKey: 'writing.reviewer.status_pending' },
};

const JOURNAL_OPTIONS: JournalOption[] = [
  {
    id: 'ai-generic-review',
    name: 'AI 通用审稿（不指定期刊）',
    reviewCycle: '即时',
    acceptanceRate: '—',
  },
  {
    id: 'nature-communications',
    name: 'Nature Communications',
    impactFactor: '16.6',
    reviewCycle: '4-8 周',
    acceptanceRate: '7-9%',
  },
  {
    id: 'advanced-materials',
    name: 'Advanced Materials',
    impactFactor: '27.4',
    reviewCycle: '3-6 周',
    acceptanceRate: '10-15%',
  },
  {
    id: 'journal-of-materials-processing-tech',
    name: 'Journal of Materials Processing Technology',
    impactFactor: '7.1',
    reviewCycle: '6-10 周',
    acceptanceRate: '20-30%',
  },
];

export function ReviewerSubmission() {
  const { t } = useI18n();
  const [selectedJournal, setSelectedJournal] = useState('ai-generic-review');

  const selectedJournalMeta = JOURNAL_OPTIONS.find(option => option.id === selectedJournal);

  const passCount = MOCK_CHECKS.filter(c => c.status === 'pass').length;
  const totalCount = MOCK_CHECKS.length;
  const score = Math.round((passCount / totalCount) * 100);

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <div className="flex justify-between items-start mb-8">
        <div>
          <h1 className="font-display text-xl font-semibold text-foreground flex items-center gap-2.5">
            <ShieldCheck size={22} className="text-primary" />
            {t('writing.reviewer.title')}
          </h1>
          <p className="font-label text-xs text-foreground/40 mt-1">
            {t('writing.reviewer.subtitle')}
          </p>
        </div>
        <button type="button" className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2.5 rounded-lg font-label text-sm font-medium shadow-md shadow-primary/20 hover:bg-primary/90 transition-all">
          <Send size={16} />
          {t('writing.reviewer.prepare_submission')}
        </button>
      </div>

      {/* Score Card */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 mb-8">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass-card rounded-lg p-5 lg:col-span-1 flex flex-col items-center justify-center"
        >
          <div className="relative w-24 h-24 mb-3">
            <svg viewBox="0 0 100 100" className="transform -rotate-90">
              <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" className="text-surface-high" strokeWidth="8" />
              <circle
                cx="50" cy="50" r="42" fill="none" stroke="currentColor"
                className={cn(score >= 70 ? 'text-emerald-500' : score >= 40 ? 'text-amber-500' : 'text-red-500')}
                strokeWidth="8"
                strokeDasharray={`${score * 2.64} 264`}
                strokeLinecap="round"
              />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="font-headline text-2xl font-bold text-foreground">{score}</span>
            </div>
          </div>
          <p className="font-label text-xs text-foreground/50">
            {t('writing.reviewer.readiness')}
          </p>
        </motion.div>

        {/* Journal Selector */}
        <div className="lg:col-span-2 glass-card rounded-lg p-5">
          <h3 className="font-headline font-semibold text-sm text-foreground mb-3">
            {t('writing.reviewer.target_journal')}
          </h3>
          <select
            value={selectedJournal}
            onChange={e => setSelectedJournal(e.target.value)}
            title={t('writing.reviewer.target_journal')}
            aria-label={t('writing.reviewer.target_journal')}
            className="w-full bg-surface-high rounded-lg px-3 py-2.5 border border-outline-variant/50 text-sm font-label text-foreground focus:outline-none focus:border-primary/40 transition-colors"
          >
            {JOURNAL_OPTIONS.map(option => (
              <option key={option.id} value={option.id}>{option.name}</option>
            ))}
          </select>
          <div className="mt-3 flex items-center gap-4 font-label text-[10px] text-foreground/30">
            <span>{t('reviewer.impact_factor')}: {selectedJournalMeta?.impactFactor ?? '—'}</span>
            <span>{t('writing.reviewer.review_cycle')}: {selectedJournalMeta?.reviewCycle ?? t('reviewer.review_cycle_value')}</span>
            <span>{t('writing.reviewer.acceptance_rate')}: {selectedJournalMeta?.acceptanceRate ?? '—'}</span>
          </div>
        </div>
      </div>

      {/* Checklist */}
      <div className="glass-card rounded-lg p-5">
        <h3 className="font-headline font-semibold text-sm text-foreground mb-4 flex items-center gap-2">
          <FileCheck size={16} className="text-primary" />
            {t('writing.reviewer.checklist_title')}
          <span className="ml-auto font-label text-[10px] text-foreground/30">{passCount}/{totalCount} {t('writing.reviewer.passed')}</span>
        </h3>
        <div className="space-y-2">
          {MOCK_CHECKS.map((check, i) => {
            const cfg = statusConfigBase[check.status];
            return (
              <motion.div
                key={check.id}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.04 }}
                className="flex items-center gap-3 p-3 rounded-lg hover:bg-surface-high/50 transition-colors cursor-pointer group"
              >
                <div className={cn('h-8 w-8 rounded-lg flex items-center justify-center flex-shrink-0', cfg.bg)}>
                  <cfg.icon size={16} className={cfg.color} />
                </div>
                <div className="flex-1 min-w-0">
                  <h4 className="font-label text-sm font-medium text-foreground">{t(check.label)}</h4>
                  <p className="font-body text-[11px] text-foreground/40">{t(check.description)}</p>
                </div>
                <span className={cn('px-2 py-0.5 text-[9px] font-label font-medium uppercase rounded', cfg.bg, cfg.color)}>
                  {t(cfg.labelKey)}
                </span>
                <ChevronRight size={14} className="text-foreground/15 opacity-0 group-hover:opacity-100 transition-opacity" />
              </motion.div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
