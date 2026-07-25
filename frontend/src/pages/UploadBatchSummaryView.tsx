import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';

import { StatusPill } from '@/components/common/StatusPill';
import { useI18n } from '@/contexts/I18nContext';
import { summarizeUploadBatch, type UploadBatchSummaryInput } from './uploadBatchSummary';

interface UploadBatchSummaryProps {
  result: UploadBatchSummaryInput;
}

export function UploadBatchSummary({ result }: UploadBatchSummaryProps) {
  const { t } = useI18n();
  const summary = summarizeUploadBatch(result);
  const stateIcon = summary.queued > 0 ? (
    <Loader2
      aria-label={t('kb.upload_summary_state_processing')}
      className="shrink-0 animate-spin text-amber-600 dark:text-amber-300"
      size={12}
    />
  ) : summary.failed > 0 ? (
    <AlertTriangle
      aria-label={t('kb.upload_summary_state_warning')}
      className="shrink-0 text-amber-600 dark:text-amber-300"
      size={12}
    />
  ) : (
    <CheckCircle2
      aria-label={t('kb.upload_summary_state_completed')}
      className="shrink-0 text-emerald-600 dark:text-emerald-300"
      size={12}
    />
  );

  return (
    <>
      {stateIcon}
      <StatusPill tone="primary">
        {t('kb.upload_summary_accepted', { count: summary.accepted })}
      </StatusPill>
      <StatusPill tone={summary.queued > 0 ? 'warning' : 'neutral'}>
        {t('kb.upload_summary_queued', { count: summary.queued })}
      </StatusPill>
      <StatusPill tone="success">
        {t('kb.upload_summary_completed', { count: summary.completed })}
      </StatusPill>
      <StatusPill tone="neutral">
        {t('kb.upload_summary_duplicate', { count: summary.duplicate })}
      </StatusPill>
      <StatusPill tone="neutral">
        {t('kb.upload_summary_skipped', { count: summary.skipped })}
      </StatusPill>
      <StatusPill tone={summary.failed > 0 ? 'danger' : 'neutral'}>
        {t('kb.upload_summary_failed', { count: summary.failed })}
      </StatusPill>
      <StatusPill tone="info">
        {t('kb.upload_summary_chunks', { count: summary.chunks })}
      </StatusPill>
    </>
  );
}
