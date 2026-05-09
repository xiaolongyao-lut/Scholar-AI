import React from 'react';
import { BarChart3, FileText, PencilLine, Eye, Clock, TrendingUp, Target, BookOpen, Inbox } from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { useWriting } from '@/contexts/WritingContext';

const stats = [
  { key: 'total_words', icon: PencilLine, value: '0', delta: '', up: false, color: 'text-primary' },
  { key: 'references', icon: BookOpen, value: '0', delta: '', up: false, color: 'text-emerald-500' },
  { key: 'sections', icon: FileText, value: '0', delta: '', up: false, color: 'text-amber-500' },
  { key: 'revisions', icon: Eye, value: '0', delta: '', up: false, color: 'text-violet-500' },
];

export function WritingOverview() {
  const { t } = useI18n();
  const { activeProjectId } = useWriting();

  const recentActivities: { time: string; action: string; type: string }[] = [];

  const statLabels: Record<string, string> = {
    total_words: t('writing.overview.total_words'),
    references: t('writing.overview.references'),
    sections: t('writing.overview.sections'),
    revisions: t('writing.overview.revisions'),
  };

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8">
      {/* Title */}
      <div>
        <h1 className="font-display text-2xl font-semibold text-foreground">
          {t('writing.overview.title')}
        </h1>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((s, i) => (
          <motion.div
            key={s.key}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.06 }}
            className="glass-card p-4 rounded-lg"
          >
            <div className="flex items-center justify-between mb-3">
              <div className={cn('h-9 w-9 rounded-lg flex items-center justify-center bg-surface-high', s.color)}>
                <s.icon size={18} />
              </div>
              {s.up && (
                <span className="text-[10px] font-label font-medium text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">
                  {s.delta}
                </span>
              )}
            </div>
            <div className="font-headline text-xl font-semibold text-foreground tabular-nums">{s.value}</div>
            <div className="font-label text-[11px] text-foreground/40 mt-0.5">{statLabels[s.key]}</div>
          </motion.div>
        ))}
      </div>

      {/* Progress + Recent Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Writing Progress */}
        <div className="lg:col-span-2 glass-card rounded-lg p-5">
          <h3 className="font-headline font-semibold text-sm text-foreground mb-4 flex items-center gap-2">
            <Target size={16} className="text-primary" />
            {t('writing.overview.writing_progress')}
          </h3>
          <div className="space-y-4">
            {!activeProjectId ? (
              <div className="flex flex-col items-center justify-center py-6 text-center">
                <Inbox size={28} className="text-foreground/15 mb-2" />
                <p className="font-label text-xs text-foreground/40">{t('writing.overview.no_data_desc')}</p>
              </div>
            ) : (
              <p className="font-label text-xs text-foreground/40 text-center py-4">{t('writing.overview.no_data_desc')}</p>
            )}
          </div>
        </div>

        {/* Recent Activity */}
        <div className="lg:col-span-3 glass-card rounded-lg p-5">
          <h3 className="font-headline font-semibold text-sm text-foreground mb-4 flex items-center gap-2">
            <Clock size={16} className="text-primary" />
            {t('writing.overview.recent_activity')}
          </h3>
          <div className="space-y-0">
            {recentActivities.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-6 text-center">
                <Clock size={28} className="text-foreground/15 mb-2" />
                <p className="font-label text-xs text-foreground/40">{t('writing.overview.no_data_desc')}</p>
              </div>
            ) : (
              recentActivities.map((activity, i) => (
              <div key={i} className="flex items-start gap-3 py-3 border-b border-outline-variant/30 last:border-0">
                <div className="w-7 h-7 bg-surface-high rounded-full flex items-center justify-center flex-shrink-0 mt-0.5">
                  {activity.type === 'ai' ? (
                    <TrendingUp size={12} className="text-primary" />
                  ) : (
                    <PencilLine size={12} className="text-foreground/40" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-body text-sm text-foreground/80">{activity.action}</p>
                  <p className="font-label text-[10px] text-foreground/30 mt-0.5">{activity.time}</p>
                </div>
              </div>
            ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
