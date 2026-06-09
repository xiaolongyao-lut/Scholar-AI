import { useCallback, useState } from 'react';
import { getSessionApi } from '@/services/sessionApi';
import { useToast } from '@/components/ui/Toast';
import { useI18n } from '@/contexts/I18nContext';
import { formatChatVisibleError } from '@/components/chat/chatDisplay';
import { CheckpointMeta, ResumeSessionResult } from '@/types/runtime';

export function useSessionPersistence() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [isBusy, setIsBusy] = useState(false);
  const api = getSessionApi();

  const resume = useCallback(async (sessionId: string) => {
    setIsBusy(true);
    try {
      const result = await api.resumeSession(sessionId);
      toast(t('workbench.session_resumed'), 'success');
      return result;
    } catch (err) {
      const msg = formatChatVisibleError(err, { fallback: '恢复会话失败，请稍后重试。' });
      toast(msg, 'error');
      throw err;
    } finally {
      setIsBusy(false);
    }
  }, [api, t, toast]);

  const fork = useCallback(async (sessionId: string, checkpoint: CheckpointMeta) => {
    setIsBusy(true);
    try {
      const result = await api.forkSession(sessionId, {
        checkpoint_id: checkpoint.checkpoint_id,
      });
      toast(t('workbench.session_forked'), 'success');
      return result;
    } catch (err) {
      const msg = formatChatVisibleError(err, { fallback: '分叉会话失败，请稍后重试。' });
      toast(msg, 'error');
      throw err;
    } finally {
      setIsBusy(false);
    }
  }, [api, t, toast]);

  const rewind = useCallback(async (
    sessionId: string, 
    checkpoint: CheckpointMeta, 
    mode: 'conversation_only' | 'with_files'
  ) => {
    setIsBusy(true);
    try {
      const result = await api.rewindSession(sessionId, {
        checkpoint_id: checkpoint.checkpoint_id,
        mode,
      });
      toast(t('workbench.session_rewound'), 'success');
      return result;
    } catch (err) {
      const msg = formatChatVisibleError(err, { fallback: '回退会话失败，请稍后重试。' });
      toast(msg, 'error');
      throw err;
    } finally {
      setIsBusy(false);
    }
  }, [api, t, toast]);

  return { resume, fork, rewind, isBusy };
}
