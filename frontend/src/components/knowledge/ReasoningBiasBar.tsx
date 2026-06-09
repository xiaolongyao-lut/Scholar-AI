import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, Save, Sparkles } from 'lucide-react';
import { cn } from '@/lib/utils';
import type {
  ProjectReasoningBiasOptimizeResponse,
  ProjectReasoningBiasPayload,
  ProjectReasoningBiasScopes,
} from '@/types/resources';
import {
  emptyProjectReasoningBias,
  getProjectReasoningBias,
  isProjectReasoningBiasRequestCanceled,
  optimizeProjectReasoningBias,
  saveProjectReasoningBias,
} from '@/services/projectReasoningBiasApi';
import { ReasoningBiasOptimizerDialog } from './ReasoningBiasOptimizerDialog';
import { ReasoningBiasScopePopover } from './ReasoningBiasScopePopover';
import { ProjectBiasSurfaceToggle } from './ProjectBiasSurfaceToggle';
import { formatChatVisibleError } from '@/components/chat/chatDisplay';

interface ReasoningBiasBarProps {
  projectId: string | null;
}

type BiasStatus = 'idle' | 'loading' | 'saving' | 'saved' | 'error';

function scopesToTargetScopes(scopes: ProjectReasoningBiasScopes) {
  const result: Array<'analysis_chain' | 'chat_generation' | 'discussion_agent' | 'project_wide'> = [];
  if (scopes.analysis_chain) result.push('analysis_chain');
  if (scopes.chat_generation) result.push('chat_generation');
  if (scopes.discussion_agent_ids.length > 0) result.push('discussion_agent');
  if (scopes.project_wide) result.push('project_wide');
  return result;
}

function scopeSummary(scopes: ProjectReasoningBiasScopes): string {
  const enabled = [
    scopes.analysis_chain ? '思维链' : '',
    scopes.chat_generation ? '聊天与生成' : '',
    scopes.discussion_agent_ids.length > 0 ? `讨论智能体 ${scopes.discussion_agent_ids.length} 个` : '',
    scopes.project_wide ? '全项目' : '',
  ].filter(Boolean);
  return enabled.length > 0 ? enabled.join(' · ') : '未启用范围';
}

export function ReasoningBiasBar({ projectId }: ReasoningBiasBarProps) {
  const [payload, setPayload] = useState<ProjectReasoningBiasPayload>(() => emptyProjectReasoningBias());
  const [draft, setDraft] = useState('');
  const [scopes, setScopes] = useState<ProjectReasoningBiasScopes>(() => emptyProjectReasoningBias().scopes);
  const [status, setStatus] = useState<BiasStatus>('idle');
  const [message, setMessage] = useState('');
  const [optimizerOpen, setOptimizerOpen] = useState(false);
  const [optimizerLoading, setOptimizerLoading] = useState(false);
  const [optimizerError, setOptimizerError] = useState('');
  const [optimizerResult, setOptimizerResult] = useState<ProjectReasoningBiasOptimizeResponse | null>(null);
  const optimizerAbortControllerRef = useRef<AbortController | null>(null);
  const optimizerRunIdRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    optimizerAbortControllerRef.current?.abort();
    optimizerAbortControllerRef.current = null;
    optimizerRunIdRef.current += 1;
    setOptimizerLoading(false);
    if (!projectId) {
      setPayload(emptyProjectReasoningBias());
      setDraft('');
      setScopes(emptyProjectReasoningBias().scopes);
      setStatus('idle');
      setMessage('');
      return undefined;
    }

    setStatus('loading');
    setMessage('');
    getProjectReasoningBias(projectId)
      .then((nextPayload) => {
        if (cancelled) return;
        setPayload(nextPayload);
        setDraft(nextPayload.human_bias);
        setScopes(nextPayload.scopes);
        setStatus('idle');
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setStatus('error');
        setMessage(formatChatVisibleError(error));
      });
    return () => {
      cancelled = true;
      optimizerAbortControllerRef.current?.abort();
      optimizerAbortControllerRef.current = null;
    };
  }, [projectId]);

  const dirty = draft !== payload.human_bias || JSON.stringify(scopes) !== JSON.stringify(payload.scopes);
  const charCount = draft.length;
  const overSoftLimit = charCount > 3800;
  const canSubmit = Boolean(projectId) && status !== 'saving' && status !== 'loading' && charCount <= 4000;
  const statusText = useMemo(() => {
    if (status === 'loading') return '加载中';
    if (status === 'saving') return '保存中';
    if (status === 'error') return message || '保存失败';
    if (dirty) return '有未保存更改';
    if (status === 'saved') return '已保存';
    return payload.updated_at ? '已同步' : '默认设置';
  }, [dirty, message, payload.updated_at, status]);

  const handleSave = async () => {
    if (!projectId || !canSubmit) return;
    setStatus('saving');
    setMessage('');
    try {
      const saved = await saveProjectReasoningBias(projectId, {
        human_bias: draft,
        scopes,
        language: payload.language,
      });
      setPayload(saved);
      setDraft(saved.human_bias);
      setScopes(saved.scopes);
      setStatus('saved');
    } catch (error: unknown) {
      setStatus('error');
      setMessage(formatChatVisibleError(error));
    }
  };

  const stopOptimizer = useCallback(() => {
    const controller = optimizerAbortControllerRef.current;
    if (!controller) return;
    optimizerRunIdRef.current += 1;
    controller.abort();
    optimizerAbortControllerRef.current = null;
    setOptimizerLoading(false);
    setOptimizerError('已停止生成建议。');
    setOptimizerResult(null);
  }, []);

  const handleOptimize = async () => {
    if (!projectId) return;
    optimizerAbortControllerRef.current?.abort();
    const controller = new AbortController();
    const runId = optimizerRunIdRef.current + 1;
    optimizerRunIdRef.current = runId;
    optimizerAbortControllerRef.current = controller;
    setOptimizerOpen(true);
    setOptimizerLoading(true);
    setOptimizerError('');
    setOptimizerResult(null);
    try {
      const result = await optimizeProjectReasoningBias(projectId, {
        human_bias: draft,
        language: payload.language,
        target_scopes: scopesToTargetScopes(scopes),
      }, {
        signal: controller.signal,
      });
      if (optimizerRunIdRef.current !== runId) return;
      setOptimizerResult(result);
    } catch (error: unknown) {
      if (optimizerRunIdRef.current !== runId) return;
      if (isProjectReasoningBiasRequestCanceled(error)) {
        setOptimizerError('已停止生成建议。');
        return;
      }
      setOptimizerError(formatChatVisibleError(error));
    } finally {
      if (optimizerRunIdRef.current === runId) {
        setOptimizerLoading(false);
        optimizerAbortControllerRef.current = null;
      }
    }
  };

  const closeOptimizer = useCallback(() => {
    if (optimizerLoading) {
      stopOptimizer();
    }
    setOptimizerOpen(false);
  }, [optimizerLoading, stopOptimizer]);

  if (!projectId) {
    return null;
  }

  return (
    <section className="mb-3 rounded-md border border-outline-variant/60 bg-surface-lowest p-3">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-start">
        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <h2 className="text-xs font-semibold text-foreground">项目思维偏置</h2>
            <span className="rounded-sm bg-surface-low px-1.5 py-0.5 text-[10px] text-foreground/55">
              {scopeSummary(scopes)}
            </span>
            <span
              className={cn(
                'inline-flex items-center gap-1 text-[10px]',
                status === 'error' ? 'text-red-600 dark:text-red-300' : 'text-foreground/45',
              )}
            >
              {status === 'error' ? <AlertTriangle size={11} /> : <CheckCircle2 size={11} />}
              {statusText}
            </span>
          </div>
          <textarea
            value={draft}
            aria-label="项目思维偏置输入"
            onChange={(event) => {
              setDraft(event.target.value);
              setStatus('idle');
            }}
            maxLength={4000}
            rows={2}
            placeholder="写下本项目希望 AI 优先关注的研究偏好、证据边界、反证要求或下一步动作。"
            className="min-h-[66px] w-full resize-y rounded-md border border-outline-variant/60 bg-surface-low px-3 py-2 text-xs leading-5 text-foreground placeholder:text-foreground/35 focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/20"
          />
          <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-[10px] text-foreground/45">
            <span>偏置作为低优先级项目偏好参与本页 AI 功能，不会自动生成参考文献目录。</span>
            <span className={cn(overSoftLimit && 'text-amber-600 dark:text-amber-300')}>
              {charCount} / 4000
            </span>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2 xl:w-[320px] xl:justify-end">
          <ProjectBiasSurfaceToggle
            enabled={draft.trim().length > 0}
            label={draft.trim().length > 0 ? '本页 AI 默认受影响' : '本页 AI 未启用'}
          />
          <button
            type="button"
            disabled={!projectId || optimizerLoading || status === 'loading'}
            onClick={() => void handleOptimize()}
            className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1 text-xs font-medium text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-50"
          >
            {optimizerLoading ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
            AI 优化
          </button>
          <button
            type="button"
            disabled={!canSubmit || !dirty}
            onClick={() => void handleSave()}
            className="inline-flex min-h-8 items-center gap-1.5 rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
          >
            {status === 'saving' ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
            保存
          </button>
        </div>
      </div>

      <div className="mt-3">
        <ReasoningBiasScopePopover
          scopes={scopes}
          onChange={(nextScopes) => {
            setScopes(nextScopes);
            setStatus('idle');
          }}
          disabled={status === 'loading'}
        />
      </div>

      <ReasoningBiasOptimizerDialog
        open={optimizerOpen}
        result={optimizerResult}
        loading={optimizerLoading}
        error={optimizerError}
        onClose={closeOptimizer}
        onStop={stopOptimizer}
        onAdopt={(optimizedBias) => {
          setDraft(optimizedBias);
          setStatus('idle');
          setOptimizerOpen(false);
        }}
      />
    </section>
  );
}
