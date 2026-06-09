import { useEffect, useState } from 'react';
import { formatChatVisibleError } from '@/components/chat/chatDisplay';
import {
  emptyProjectReasoningBias,
  getProjectReasoningBias,
} from '@/services/projectReasoningBiasApi';
import type { ProjectReasoningBiasPayload } from '@/types/resources';

export type ProjectReasoningBiasSurface = 'analysis_chain' | 'chat_generation' | 'discussion_agent' | 'project_wide';

interface ProjectReasoningBiasState {
  payload: ProjectReasoningBiasPayload;
  loading: boolean;
  error: string;
  isEnabledForSurface(surface: ProjectReasoningBiasSurface): boolean;
}

function hasActiveBias(payload: ProjectReasoningBiasPayload): boolean {
  return payload.human_bias.trim().length > 0;
}

function surfaceEnabled(payload: ProjectReasoningBiasPayload, surface: ProjectReasoningBiasSurface): boolean {
  if (!hasActiveBias(payload)) return false;
  if (payload.scopes.project_wide) return true;
  if (surface === 'analysis_chain') return payload.scopes.analysis_chain;
  if (surface === 'chat_generation') return payload.scopes.chat_generation;
  if (surface === 'discussion_agent') return payload.scopes.discussion_agent_ids.length > 0;
  return false;
}

/**
 * Loads the saved project-level reasoning-bias preference for per-request UI.
 *
 * The hook intentionally keeps network failure fail-open for the surrounding
 * chat surface: it reports the error but returns disabled surface state, so a
 * missing preference endpoint cannot block a user question.
 */
export function useProjectReasoningBiasState(projectId?: string | null): ProjectReasoningBiasState {
  const [payload, setPayload] = useState<ProjectReasoningBiasPayload>(() => emptyProjectReasoningBias());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    const normalizedProjectId = String(projectId ?? '').trim();
    if (!normalizedProjectId) {
      setPayload(emptyProjectReasoningBias());
      setLoading(false);
      setError('');
      return undefined;
    }

    setLoading(true);
    setError('');
    getProjectReasoningBias(normalizedProjectId)
      .then((nextPayload) => {
        if (cancelled) return;
        setPayload(nextPayload);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setPayload(emptyProjectReasoningBias());
        setError(formatChatVisibleError(err, { fallback: '项目思维偏置加载失败，请稍后重试。' }));
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return {
    payload,
    loading,
    error,
    isEnabledForSurface(surface: ProjectReasoningBiasSurface): boolean {
      return surfaceEnabled(payload, surface);
    },
  };
}
