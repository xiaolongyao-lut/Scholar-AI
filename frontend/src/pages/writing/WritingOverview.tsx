import { BarChart3, FileText, PencilLine, Eye, Clock, TrendingUp, Target, BookOpen, Inbox } from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { useWriting } from '@/contexts/WritingContext';
import { PageHeader } from '@/components/common/PageHeader';
import { SectionCard } from '@/components/common/SectionCard';
import { StatusPill } from '@/components/common/StatusPill';

const stats = [
  { key: 'total_words', icon: PencilLine, value: '0', delta: '', up: false, color: 'text-primary' },
  { key: 'references', icon: BookOpen, value: '0', delta: '', up: false, color: 'text-emerald-500' },
  { key: 'sections', icon: FileText, value: '0', delta: '', up: false, color: 'text-amber-500' },
  { key: 'revisions', icon: Eye, value: '0', delta: '', up: false, color: 'text-violet-500' },
];

/**
 * 写作总览 — Long-Run v2 Slice I rebuild.
 * 视觉参考: `07_object_surfaces/20_writing_overview.png`
 * 与研究工作台明确区分：本页是产出/写作模式，不包含 PDF canvas。
 */
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
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-6 py-4">
        <PageHeader
          icon={<BarChart3 size={18} />}
          title={t('writing.overview.title')}
          subtitle="管理当前手稿的写作进度、来源覆盖、最近活动与投稿准备"
          className="mb-0"
          actions={<StatusPill tone={activeProjectId ? 'success' : 'neutral'}>{activeProjectId ? '项目已激活' : '未激活项目'}</StatusPill>}
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-6 py-5">
        {/* Stat row (compact pills, not card grid) */}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {stats.map((s, i) => (
            <motion.div
              key={s.key}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04 }}
              className="rounded-md border border-outline-variant/60 bg-surface-lowest p-3"
            >
              <div className="flex items-center justify-between">
                <div className={cn('flex h-7 w-7 items-center justify-center rounded-md bg-surface-high', s.color)}>
                  <s.icon size={14} />
                </div>
                {s.up && (
                  <StatusPill tone="success">{s.delta}</StatusPill>
                )}
              </div>
              <div className="mt-2 font-headline text-lg font-semibold text-foreground tabular-nums">{s.value}</div>
              <div className="mt-0.5 font-label text-[11px] text-foreground/45">{statLabels[s.key]}</div>
            </motion.div>
          ))}
        </div>

        {/* Two-column layout */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
          {/* Writing Progress */}
          <SectionCard
            title={t('writing.overview.writing_progress')}
            icon={<Target size={14} />}
            className="lg:col-span-2"
          >
            <div className="space-y-3 py-2">
              {!activeProjectId ? (
                <div className="flex flex-col items-center justify-center py-6 text-center">
                  <Inbox size={24} className="mb-2 text-foreground/25" />
                  <p className="font-label text-xs text-foreground/45">{t('writing.overview.no_data_desc')}</p>
                </div>
              ) : (
                <p className="py-4 text-center font-label text-xs text-foreground/45">{t('writing.overview.no_data_desc')}</p>
              )}
            </div>
          </SectionCard>

          {/* Recent Activity */}
          <SectionCard
            title={t('writing.overview.recent_activity')}
            icon={<Clock size={14} />}
            className="lg:col-span-3"
          >
            <div className="space-y-0">
              {recentActivities.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-6 text-center">
                  <Clock size={24} className="mb-2 text-foreground/25" />
                  <p className="font-label text-xs text-foreground/45">{t('writing.overview.no_data_desc')}</p>
                </div>
              ) : (
                recentActivities.map((activity, i) => (
                  <div key={i} className="flex items-start gap-3 border-b border-outline-variant/30 py-3 last:border-0">
                    <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-high">
                      {activity.type === 'ai' ? (
                        <TrendingUp size={12} className="text-primary" />
                      ) : (
                        <PencilLine size={12} className="text-foreground/45" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="font-body text-sm text-foreground/80">{activity.action}</p>
                      <p className="mt-0.5 font-label text-[10px] text-foreground/40">{activity.time}</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
