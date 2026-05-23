import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Send, Copy, Clock, CheckCircle2, XCircle, Plus, Trash2, Zap, Square, Layers3, Route, SlidersHorizontal, Settings2, AlertCircle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { discussionApi, type DiscussionRunConfig, type DiscussionRunResult, type DiscussionAgentConfig, type DiscussionAgentTrace, type DiscussionEvidenceMode } from '../../services/discussionApi';
import { useWriting } from '@/contexts/WritingContext';
import { useDiscussion } from '@/contexts/DiscussionContext';
import { AnalysisChainPanel } from '@/components/analysis_chain/AnalysisChainPanel';
import { cn } from '@/lib/utils';
import { discussionToGraphPayload } from '@/components/graph/discussionToGraphPayload';
import { GraphPayloadViewer } from '@/components/graph/GraphPayloadViewer';
import { McpScopePicker } from '@/components/mcp/McpScopePicker';
import {
  DISCUSSION_ROLE_LABELS,
  DISCUSSION_PROFILE_STORE_CHANGED_EVENT,
  DISCUSSION_API_MODE_LABELS,
  buildAgentConfigFromProfile,
  describeApiBinding,
  isDiscussionProfileId,
  loadDiscussionProfileStore,
  type DiscussionAgentProfile,
  type DiscussionProfileId,
} from '@/services/discussionProfiles';
import {
  DISCUSSION_DEFAULT_BOUNDS,
  DISCUSSION_TURN_WARNING_THRESHOLD,
} from '@/services/discussionDefaults';

interface DiscussionPanelProps {
  onInsertToEditor?: (content: string) => void;
  defaults?: {
    auto_stop?: boolean;
    min_turns?: number;
    convergence_threshold?: number;
    convergence_judge_agent_id?: string;
  };
}

const ROLE_OPTIONS: { value: DiscussionAgentConfig['role']; label: string; color: string }[] = [
  { value: 'proposer', label: '支持方', color: 'bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-700/40' },
  { value: 'critic', label: '批评方', color: 'bg-rose-50 text-rose-800 border-rose-200 dark:bg-rose-500/15 dark:text-rose-300 dark:border-rose-700/40' },
  { value: 'devil_advocate', label: '魔鬼代言人', color: 'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:border-amber-700/40' },
  { value: 'domain_expert', label: '领域专家', color: 'bg-sky-50 text-sky-800 border-sky-200 dark:bg-sky-500/15 dark:text-sky-300 dark:border-sky-700/40' },
  { value: 'synthesizer', label: '综合者', color: 'bg-indigo-50 text-indigo-800 border-indigo-200 dark:bg-indigo-500/15 dark:text-indigo-300 dark:border-indigo-700/40' },
  { value: 'custom', label: '自定义', color: 'bg-slate-50 text-slate-700 border-slate-200' },
];

const ROLE_COLOR_MAP: Record<string, string> = Object.fromEntries(
  ROLE_OPTIONS.map(r => [r.value, r.color])
);

const MAX_DISCUSSION_AGENTS = 8;

const SETUP_STORAGE_KEY = 'discussion-panel-setup-v1';

interface PersistedSetup {
  query?: string;
  agents?: AgentSlot[];
  maxTurns?: number;
  autoStop?: boolean;
  minTurns?: number;
  judgeAgentId?: string;
  evidenceMode?: DiscussionEvidenceMode;
  manualChunkIds?: string;
  mcpServerIds?: string[];
}

function loadPersistedSetup(): PersistedSetup {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(SETUP_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return typeof parsed === 'object' && parsed !== null ? (parsed as PersistedSetup) : {};
  } catch {
    return {};
  }
}

function persistSetup(value: PersistedSetup): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(SETUP_STORAGE_KEY, JSON.stringify(value));
  } catch {
    /* quota or disabled storage — drop silently */
  }
}

function getRoleLabel(role: string): string {
  return ROLE_OPTIONS.find(r => r.value === role)?.label || role;
}

export function evidenceSnippetDomId(evidenceId: string): string {
  return `evidence-snippet-${evidenceId}`;
}

export function scrollToEvidence(evidenceId: string): void {
  if (typeof document === 'undefined') return;
  const el = document.getElementById(evidenceSnippetDomId(evidenceId));
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  el.classList.add('ring-2', 'ring-primary');
  window.setTimeout(() => {
    el.classList.remove('ring-2', 'ring-primary');
  }, 1500);
}

interface AgentSlot {
  id: string;
  profileId: DiscussionProfileId;
  roleLabel: string;
  systemPrompt: string;
}

function makeSlot(index: number, profileId: DiscussionProfileId = 'proposer', profile?: DiscussionAgentProfile): AgentSlot {
  return {
    id: `${profileId}_${index}`,
    profileId,
    roleLabel: profile?.displayName ?? '',
    systemPrompt: profile?.systemPrompt ?? '',
  };
}

function clampNumber(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.min(max, Math.max(min, value));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readErrorDetail(error: unknown): string | null {
  if (!isRecord(error) || !isRecord(error.response)) {
    return null;
  }
  const data = error.response.data;
  if (!isRecord(data)) {
    return null;
  }
  const detail = data.detail;
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    return '讨论配置未通过校验，请检查角色、证据和自动停止设置。';
  }
  return null;
}

function formatDiscussionRunError(error: unknown): string {
  const raw = readErrorDetail(error) ?? (error instanceof Error ? error.message : '');
  if (!raw) {
    return '讨论运行失败，请检查角色接口和证据配置。';
  }
  if (raw.includes('convergence_judge_agent_id')) {
    return '裁判角色必须来自当前角色列表。';
  }
  if (raw.includes('project_id is required')) {
    return '当前证据来源需要先选择项目。';
  }
  if (raw.includes('evidence_chunk_ids')) {
    return '手动证据需要填写至少一个证据编号。';
  }
  if (raw.trim().startsWith('{') || raw.length > 220) {
    return '讨论运行失败，请检查角色接口和证据配置。';
  }
  return raw;
}

function getSynthesisStrategyLabel(strategy: string): string {
  switch (strategy) {
    case 'vote':
      return '投票';
    case 'debate':
      return '辩论';
    case 'synthesize':
      return '综合';
    default:
      return '综合';
  }
}

export const DiscussionPanel: React.FC<DiscussionPanelProps> = ({ onInsertToEditor, defaults }) => {
  const navigate = useNavigate();
  const { activeProjectId } = useWriting();
  const [profileStore, setProfileStore] = useState(loadDiscussionProfileStore);
  // User-visible inputs survive across route navigation via localStorage
  // (2026-05-24 user report: switching pages should not wipe the form).
  const [persistedSetup] = useState<PersistedSetup>(() => loadPersistedSetup());
  const [query, setQuery] = useState<string>(persistedSetup.query ?? '');
  const [agents, setAgents] = useState<AgentSlot[]>(() => {
    if (persistedSetup.agents && persistedSetup.agents.length >= 2) {
      return persistedSetup.agents;
    }
    return [
      makeSlot(1, 'proposer', profileStore.profiles.find((profile) => profile.id === 'proposer')),
      makeSlot(2, 'critic', profileStore.profiles.find((profile) => profile.id === 'critic')),
    ];
  });
  const [maxTurns, setMaxTurns] = useState<number>(persistedSetup.maxTurns ?? 3);
  const [autoStop, setAutoStop] = useState<boolean>(persistedSetup.autoStop ?? defaults?.auto_stop ?? false);
  const [minTurns, setMinTurns] = useState<number>(persistedSetup.minTurns ?? defaults?.min_turns ?? 2);
  const [judgeAgentId, setJudgeAgentId] = useState<string>(persistedSetup.judgeAgentId ?? '');
  const [evidenceMode, setEvidenceMode] = useState<DiscussionEvidenceMode>(persistedSetup.evidenceMode ?? 'none');
  const [manualChunkIds, setManualChunkIds] = useState<string>(persistedSetup.manualChunkIds ?? '');
  const [mcpServerIds, setMcpServerIds] = useState<string[]>(persistedSetup.mcpServerIds ?? []);
  const [expandedAgentId, setExpandedAgentId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<DiscussionRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsedSec, setElapsedSec] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const startedAtRef = useRef<number>(0);
  const nextAgentIndexRef = useRef(3);

  // Persist every setup-form change so navigating away and back keeps the
  // inputs intact. Run-time state (running/result/error) is owned by the
  // DiscussionContext from Slice 2 and lives there.
  useEffect(() => {
    persistSetup({
      query,
      agents,
      maxTurns,
      autoStop,
      minTurns,
      judgeAgentId,
      evidenceMode,
      manualChunkIds,
      mcpServerIds,
    });
  }, [query, agents, maxTurns, autoStop, minTurns, judgeAgentId, evidenceMode, manualChunkIds, mcpServerIds]);

  // DSE Slice 2: cross-route persistent discussion session.
  const { session, startSession, cancelSession } = useDiscussion();

  // Sync Context session state into local state so existing rendering logic
  // (which references `running` / `result` / `error`) keeps working unchanged.
  // The Context is the source of truth for running state across navigations;
  // local state mirrors it for component-internal derived rendering.
  useEffect(() => {
    setRunning(session.state === 'running');
    if (session.finalResult !== null) {
      setResult(session.finalResult);
    }
    if (session.state === 'cancelled') {
      setError('已停止等待，当前模型调用可能仍在收尾。');
    } else if (session.error !== null) {
      setError(session.error);
    } else if (session.state === 'running' || session.state === 'idle') {
      setError(null);
    }
    if (session.state === 'running' && session.startedAt) {
      startedAtRef.current = session.startedAt;
    }
  }, [session.state, session.finalResult, session.error, session.startedAt]);

  const updateAgent = useCallback((id: string, patch: Partial<AgentSlot>) => {
    setAgents((current) => current.map((agent) => (
      agent.id === id ? { ...agent, ...patch } : agent
    )));
  }, []);

  const profileForId = useCallback((profileId: DiscussionProfileId) => {
    const profile = profileStore.profiles.find((item) => item.id === profileId);
    if (profile) return profile;
    return profileStore.profiles[0];
  }, [profileStore.profiles]);

  const applyProfileDefaults = useCallback((agentId: string, profileId: DiscussionProfileId) => {
    const profile = profileForId(profileId);
    if (!profile) return;
    updateAgent(agentId, {
      profileId,
      roleLabel: profile.displayName,
      systemPrompt: profile.systemPrompt,
    });
  }, [profileForId, updateAgent]);

  useEffect(() => {
    const normalizedMinTurns = clampNumber(
      defaults?.min_turns ?? 2,
      DISCUSSION_DEFAULT_BOUNDS.min_turns.min,
      DISCUSSION_DEFAULT_BOUNDS.min_turns.max,
    );
    setAutoStop(defaults?.auto_stop ?? false);
    setMinTurns(normalizedMinTurns);
    setMaxTurns((current) => Math.max(current, normalizedMinTurns));
  }, [defaults?.auto_stop, defaults?.min_turns]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === 'scholar-ai-discussion-profiles') {
        setProfileStore(loadDiscussionProfileStore());
      }
    };
    const onStoreChanged = () => {
      setProfileStore(loadDiscussionProfileStore());
    };
    window.addEventListener('storage', onStorage);
    window.addEventListener(DISCUSSION_PROFILE_STORE_CHANGED_EVENT, onStoreChanged);
    return () => {
      window.removeEventListener('storage', onStorage);
      window.removeEventListener(DISCUSSION_PROFILE_STORE_CHANGED_EVENT, onStoreChanged);
    };
  }, []);

  useEffect(() => {
    if (!running) {
      setElapsedSec(0);
      return;
    }
    startedAtRef.current = Date.now();
    const t = setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - startedAtRef.current) / 1000));
    }, 500);
    return () => clearInterval(t);
  }, [running]);

  const fromProjectBlocked = evidenceMode === 'from_project' && !activeProjectId;
  const manualBlocked = evidenceMode === 'manual_chunk_ids' && !manualChunkIds.trim();
  const canRun = query.trim().length > 0 && agents.length >= 2 && !fromProjectBlocked && !manualBlocked;
  const configuredPrompts = agents.filter((agent) => {
    const profile = profileForId(agent.profileId);
    return Boolean((agent.systemPrompt || profile?.systemPrompt || '').trim());
  }).length;
  const evidenceLabel = evidenceMode === 'none'
    ? '无证据'
    : evidenceMode === 'from_project'
      ? '当前项目'
      : '手动证据';
  const defaultJudgeAgentId = agents.find((agent) => agent.profileId === profileStore.defaultJudgeProfileId)?.id
    ?? agents.find((agent) => agent.profileId === 'synthesizer')?.id
    ?? agents[0]?.id
    ?? '';
  const persistedJudgeAgentId = defaults?.convergence_judge_agent_id?.trim() ?? '';
  const judgeProfileMissing = autoStop && !agents.some((agent) => agent.profileId === profileStore.defaultJudgeProfileId);
  const turnWarning = maxTurns > DISCUSSION_TURN_WARNING_THRESHOLD || (autoStop && minTurns > DISCUSSION_TURN_WARNING_THRESHOLD);
  const incompleteRoleApiCount = agents.filter((agent) => {
    const profile = profileForId(agent.profileId);
    return profile?.apiMode === 'inline' && !profile.credentialId.trim() && !profile.apiKey.trim();
  }).length;

  useEffect(() => {
    setJudgeAgentId((current) => {
      if (persistedJudgeAgentId && agents.some((agent) => agent.id === persistedJudgeAgentId)) {
        return persistedJudgeAgentId;
      }
      return agents.some((agent) => agent.id === current) ? current : defaultJudgeAgentId;
    });
  }, [agents, defaultJudgeAgentId, persistedJudgeAgentId]);

  const addAgent = (profileId?: DiscussionProfileId) => {
    if (agents.length >= MAX_DISCUSSION_AGENTS) return;
    const nextProfileId = profileId ?? profileStore.profiles.find((profile) => (
      !agents.some((agent) => agent.profileId === profile.id)
    ))?.id ?? profileStore.profiles[0]?.id ?? 'proposer';
    const profile = profileForId(nextProfileId);
    const nextIndex = nextAgentIndexRef.current;
    nextAgentIndexRef.current += 1;
    setAgents([
      ...agents,
      {
        ...makeSlot(nextIndex, nextProfileId),
        roleLabel: profile?.displayName ?? DISCUSSION_ROLE_LABELS.custom,
        systemPrompt: profile?.systemPrompt ?? '',
      },
    ]);
  };

  const removeAgent = (id: string) => {
    if (agents.length <= 2) return;
    setAgents(agents.filter(a => a.id !== id));
  };

  const handleRun = async () => {
    if (!query.trim()) return;
    if (agents.length < 2) return;

    let agentConfigs: DiscussionAgentConfig[];
    try {
      agentConfigs = agents.map((agent) => {
        const profile = profileForId(agent.profileId);
        if (!profile) {
          throw new Error('讨论角色配置缺失。');
        }
        return buildAgentConfigFromProfile(profile, {
          agentId: agent.id,
          roleLabel: agent.roleLabel,
          systemPrompt: agent.systemPrompt,
        });
      });
    } catch (err) {
      setError(formatDiscussionRunError(err));
      return;
    }

    const config: DiscussionRunConfig = {
      query: query.trim(),
      agent_configs: agentConfigs,
      max_turns: maxTurns,
      evidence_mode: evidenceMode,
      synthesis_strategy: 'synthesize',
      timeout_seconds: 120,
    };
    if (evidenceMode === 'from_project' && activeProjectId) {
      config.project_id = activeProjectId;
    }
    if (evidenceMode === 'manual_chunk_ids') {
      const ids = manualChunkIds.split(/[,\s]+/).map(s => s.trim()).filter(Boolean);
      if (ids.length > 0) {
        config.evidence_chunk_ids = ids;
      }
    }
    if (autoStop) {
      config.auto_stop = true;
      config.min_turns = Math.min(minTurns, maxTurns);
      if (judgeAgentId && agents.some((agent) => agent.id === judgeAgentId)) {
        config.convergence_judge_agent_id = judgeAgentId;
      }
    }
    if (mcpServerIds.length > 0) {
      config.mcp_overrides = { server_ids: [...mcpServerIds] };
    }

    // DSE Slice 2: delegate run lifecycle to the cross-route Context.
    // The Context owns the SSE stream + AbortController + fallback to
    // non-streaming runDiscussion; local state mirrors via useEffect above.
    await startSession(config);
  };

  const handleStop = () => {
    cancelSession();
  };

  const handleInsertSynthesis = () => {
    if (result?.synthesis?.text && onInsertToEditor) {
      onInsertToEditor(result.synthesis.text);
    }
  };

  return (
    <div className="h-full flex flex-col gap-4">
      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-lg border border-outline-variant bg-surface-lowest px-3 py-2">
          <div className="flex items-center gap-1.5 text-[11px] text-foreground/45">
            <Layers3 size={12} />
            智能体
          </div>
            <p className="mt-1 font-mono text-sm font-semibold text-foreground">{agents.length}/{MAX_DISCUSSION_AGENTS}</p>
        </div>
        <div className="rounded-lg border border-outline-variant bg-surface-lowest px-3 py-2">
          <div className="flex items-center gap-1.5 text-[11px] text-foreground/45">
            <Route size={12} />
            证据
          </div>
          <p className="mt-1 truncate text-sm font-semibold text-foreground">{evidenceLabel}</p>
        </div>
        <div className="rounded-lg border border-outline-variant bg-surface-lowest px-3 py-2">
          <div className="flex items-center gap-1.5 text-[11px] text-foreground/45">
            <Zap size={12} />
            终止
          </div>
          <p className="mt-1 text-sm font-semibold text-foreground">{autoStop ? `${minTurns}+ 轮` : '关闭'}</p>
        </div>
      </div>

      {/* Config panel */}
      <div className="rounded-lg border border-outline-variant bg-surface-lowest p-4 shadow-sm">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="font-headline text-sm font-semibold text-foreground">讨论编排</h2>
            <p className="mt-0.5 text-xs text-foreground/45">选择角色、证据来源和结束条件</p>
          </div>
          <div className="flex items-center gap-2">
            {/* Live session state pill — separate from "可运行" (which only
                reflects setup-form validity). 2026-05-24: users couldn't tell
                whether a discussion had ever started, completed, or errored. */}
            {session.state !== 'idle' && (
              <span className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-label',
                session.state === 'running' && 'bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300',
                session.state === 'completed' && 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300',
                session.state === 'cancelled' && 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
                session.state === 'error' && 'bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300',
              )}>
                <span className={cn('h-1.5 w-1.5 rounded-full',
                  session.state === 'running' && 'bg-blue-500 dark:bg-blue-400 animate-pulse',
                  session.state === 'completed' && 'bg-emerald-500 dark:bg-emerald-400',
                  session.state === 'cancelled' && 'bg-amber-500 dark:bg-amber-400',
                  session.state === 'error' && 'bg-rose-500 dark:bg-rose-400',
                )} />
                {session.state === 'running' && `运行中 · 已收到 ${session.liveTraces.length} 条`}
                {session.state === 'completed' && `已完成 · ${session.finalResult?.turns?.length ?? 0} 轮`}
                {session.state === 'cancelled' && '已取消'}
                {session.state === 'error' && '出错'}
              </span>
            )}
            <span className={cn(
              'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-label',
              canRun ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' : 'bg-surface-high text-foreground/45',
            )}>
              <span className={cn('h-1.5 w-1.5 rounded-full', canRun ? 'bg-emerald-500 dark:bg-emerald-400' : 'bg-foreground/25')} />
              {canRun ? '可运行' : '待配置'}
            </span>
          </div>
        </div>

        <div className="space-y-4">
        <div>
          <label className="font-label text-xs font-medium text-foreground/70 mb-1.5 block">讨论问题</label>
          <textarea
            rows={2}
            placeholder="输入你想让多位智能体讨论的问题…"
            value={query}
            onChange={e => setQuery(e.target.value)}
            className="w-full rounded-lg border border-outline-variant/60 bg-surface-low px-3 py-2 text-sm text-foreground transition-colors placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none resize-none"
          />
        </div>

        <div>
          <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <label className="font-label text-xs font-medium text-foreground/70">角色配置（{agents.length}/{MAX_DISCUSSION_AGENTS}）</label>
              <p className="mt-0.5 text-[11px] text-foreground/45">角色来自系统设置，新增角色和绑定 API 后会自动出现在这里。</p>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => navigate('/settings?section=discussion')}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-foreground/50 transition-colors hover:bg-surface-high hover:text-foreground"
              >
                <Settings2 size={12} /> 管理角色与 API
              </button>
              <button
                type="button"
                onClick={() => addAgent()}
                disabled={agents.length >= MAX_DISCUSSION_AGENTS}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-primary transition-colors hover:bg-primary/10 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Plus size={12} /> 添加
              </button>
            </div>
          </div>
          <div className="grid gap-2 xl:grid-cols-2">
            {agents.map((agent) => {
              const profile = profileForId(agent.profileId);
              return (
              <div key={agent.id} className="group rounded-lg border border-outline-variant/60 bg-surface-low p-2 transition-colors hover:border-primary/25">
                <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                  <label className="space-y-1">
                    <span className="text-[10px] font-label text-foreground/45">角色</span>
                    <select
                      value={agent.profileId}
                      onChange={e => {
                        const next = e.target.value;
                        if (isDiscussionProfileId(next)) {
                          applyProfileDefaults(agent.id, next);
                        }
                      }}
                      className="w-full rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1.5 text-xs font-label text-foreground focus:border-primary/40 focus:outline-none"
                    >
                      {profileStore.profiles.map((profileOption) => (
                        <option key={profileOption.id} value={profileOption.id}>{profileOption.displayName}</option>
                      ))}
                    </select>
                  </label>
                  <label className="space-y-1">
                    <span className="text-[10px] font-label text-foreground/45">本次名称</span>
                    <input
                      type="text"
                      value={agent.roleLabel}
                      onChange={e => updateAgent(agent.id, { roleLabel: e.target.value })}
                      placeholder="显示名称"
                      className="w-full rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1.5 text-xs text-foreground/70 placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
                    />
                  </label>
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <span
                    className={cn(
                      'min-w-0 flex-1 truncate rounded-md px-2 py-1 text-[10px]',
                      profile?.apiMode === 'inline' && !profile.model.trim()
                        ? 'bg-amber-50 text-amber-700'
                        : 'bg-surface-lowest text-foreground/45',
                    )}
                    title={profile ? `${DISCUSSION_API_MODE_LABELS[profile.apiMode]} · ${describeApiBinding(profile)}` : DISCUSSION_API_MODE_LABELS.default}
                  >
                    {profile ? describeApiBinding(profile) : DISCUSSION_API_MODE_LABELS.default}
                  </span>
                  <button
                    type="button"
                    onClick={() => setExpandedAgentId(prev => prev === agent.id ? null : agent.id)}
                    className={cn(
                      'text-[10px] px-2 py-1 rounded-md font-label transition-colors',
                      agent.systemPrompt
                        ? 'text-primary bg-primary/10 hover:bg-primary/20'
                        : 'text-foreground/40 hover:text-foreground/70'
                    )}
                    title="自定义系统提示"
                  >
                    提示词
                  </button>
                  <button
                    type="button"
                    onClick={() => removeAgent(agent.id)}
                    disabled={agents.length <= 2}
                    className="rounded-md p-1 text-foreground/30 transition-colors hover:bg-red-50 hover:text-red-500 disabled:cursor-not-allowed disabled:opacity-30"
                    aria-label="删除角色"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
                {expandedAgentId === agent.id && (
                  <div className="mt-2">
                    <textarea
                      rows={3}
                      value={agent.systemPrompt}
                      onChange={e => updateAgent(agent.id, { systemPrompt: e.target.value })}
                      placeholder="自定义系统提示（可选，例如：扮演方法学批评者，重点关注样本偏差与统计有效性）"
                      className="w-full rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1.5 text-xs text-foreground placeholder:text-foreground/30 resize-none focus:border-primary/40 focus:outline-none"
                    />
                  </div>
                )}
              </div>
              );
            })}
          </div>
          {incompleteRoleApiCount > 0 && (
            <div className="mt-2 flex items-start gap-2 rounded-md border border-amber-200/70 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800">
              <AlertCircle size={13} className="mt-0.5 shrink-0" />
              <span>{incompleteRoleApiCount} 个角色还没有保存 API。可继续运行并使用聊天与生成设置，也可以先到系统设置中补齐。</span>
            </div>
          )}
          {configuredPrompts > 0 && (
            <p className="mt-2 text-[11px] text-foreground/45">{configuredPrompts} 个角色已配置提示词。</p>
          )}
        </div>

        <div className="space-y-2">
          <div className="grid gap-3 sm:grid-cols-[116px_1fr]">
            <div className="flex items-center gap-2 rounded-lg border border-outline-variant/60 bg-surface-low px-2 py-2">
              <label className="font-label text-xs text-foreground/70">轮次</label>
              <input
                type="number"
                min={DISCUSSION_DEFAULT_BOUNDS.min_turns.min}
                max={DISCUSSION_DEFAULT_BOUNDS.min_turns.max}
                value={maxTurns}
                onChange={e => setMaxTurns(clampNumber(
                  Number(e.target.value),
                  DISCUSSION_DEFAULT_BOUNDS.min_turns.min,
                  DISCUSSION_DEFAULT_BOUNDS.min_turns.max,
                ))}
                className="w-14 rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1 text-center text-xs text-foreground"
              />
            </div>
            <button
              type="button"
              onClick={running ? handleStop : handleRun}
              disabled={!running && !canRun}
              className={cn(
                'flex min-h-10 items-center justify-center gap-2 rounded-lg px-4 py-2 font-label text-sm font-medium transition-all',
                running
                  ? 'bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100'
                  : 'bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50',
              )}
            >
              {running ? <Square size={12} /> : <Send size={14} />}
              {running ? `停止等待 · ${elapsedSec}s` : '开始讨论'}
            </button>
          </div>
          {turnWarning ? (
            <p className="rounded-md border border-amber-200/70 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800">
              超过 {DISCUSSION_TURN_WARNING_THRESHOLD} 轮会明显增加耗时和模型调用成本。
            </p>
          ) : null}
        </div>

        <div className="rounded-lg border border-outline-variant/50 bg-surface-low px-3 py-2">
          <div className="grid items-center gap-2 md:grid-cols-[max-content_minmax(180px,220px)_minmax(220px,1fr)]">
            <label className="flex items-center gap-1.5 whitespace-nowrap font-label text-xs text-foreground/70">
              <Route size={12} className="text-primary/70" />
              证据来源
            </label>
            <select
              value={evidenceMode}
              onChange={e => setEvidenceMode(e.target.value as DiscussionEvidenceMode)}
              className="rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1.5 text-xs text-foreground"
            >
              <option value="none">无</option>
              <option value="from_project" disabled={!activeProjectId}>
                {activeProjectId ? '当前项目' : '当前项目（未选择）'}
              </option>
              <option value="manual_chunk_ids">手动证据编号</option>
            </select>
            {evidenceMode === 'manual_chunk_ids' && (
              <input
                type="text"
                value={manualChunkIds}
                onChange={e => setManualChunkIds(e.target.value)}
                placeholder="证据编号，用逗号分隔"
                className="min-w-0 rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1.5 text-xs text-foreground placeholder:text-foreground/30"
              />
            )}
            {fromProjectBlocked && (
              <span className="text-[11px] text-amber-600">需要先在写作工作台选择项目</span>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-outline-variant/50 bg-surface-low px-3 py-2 space-y-2">
          <McpScopePicker
            selected={mcpServerIds}
            onChange={setMcpServerIds}
            hideWhenEmpty
          />
          <p className="text-[10px] text-foreground/40">
            选择后，本次讨论的所有角色都可使用这些工具。
          </p>
        </div>

        <div className="rounded-lg border border-outline-variant/50 bg-surface-low px-3 py-2">
          <label className="flex cursor-pointer select-none items-center justify-between gap-3 text-xs text-foreground/70">
            <span className="flex items-center gap-1.5">
              <SlidersHorizontal size={12} className="text-primary/70" />
              自动停止
            </span>
            <span className={cn('relative inline-flex h-5 w-9 items-center rounded-full transition-colors', autoStop ? 'bg-primary' : 'bg-foreground/15')}>
              <input
                type="checkbox"
                checked={autoStop}
                onChange={e => setAutoStop(e.target.checked)}
                className="sr-only"
              />
              <span className={cn('inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform', autoStop ? 'translate-x-4' : 'translate-x-0.5')} />
            </span>
          </label>
          {autoStop && (
            <div className="mt-3 grid gap-2 lg:grid-cols-[160px_minmax(0,1fr)_auto]">
              <div className="flex items-center gap-2">
                <label className="font-label text-xs text-foreground/70">最小轮次</label>
                <input
                  type="number"
                  min={DISCUSSION_DEFAULT_BOUNDS.min_turns.min}
                  max={DISCUSSION_DEFAULT_BOUNDS.min_turns.max}
                  value={minTurns}
                  onChange={e => setMinTurns(clampNumber(
                    Number(e.target.value),
                    DISCUSSION_DEFAULT_BOUNDS.min_turns.min,
                    DISCUSSION_DEFAULT_BOUNDS.min_turns.max,
                  ))}
                  className="w-14 rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1 text-center text-xs text-foreground"
                />
              </div>
              <div className="flex items-center gap-2">
                <label className="font-label text-xs text-foreground/70" htmlFor="discussion-judge-agent">裁判角色</label>
                <select
                  id="discussion-judge-agent"
                  value={judgeAgentId}
                  onChange={(e) => setJudgeAgentId(e.target.value)}
                  className="min-w-0 flex-1 rounded-md border border-outline-variant/50 bg-surface-lowest px-2 py-1 text-xs text-foreground focus:border-primary/40 focus:outline-none"
                >
                  {agents.map((a) => (
                    <option key={a.id} value={a.id}>{a.roleLabel || profileForId(a.profileId)?.displayName || getRoleLabel(profileForId(a.profileId)?.role ?? 'custom')}</option>
                  ))}
                </select>
              </div>
              {judgeProfileMissing && agents.length < MAX_DISCUSSION_AGENTS ? (
                <button
                  type="button"
                  onClick={() => addAgent(profileStore.defaultJudgeProfileId)}
                  className="rounded-md border border-primary/25 bg-primary/8 px-2 py-1 text-xs text-primary transition-colors hover:bg-primary/12"
                >
                  添加裁判角色
                </button>
              ) : null}
            </div>
          )}
        </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg">
          <XCircle size={14} className="text-red-500 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-red-700">{error}</p>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="flex-1 overflow-auto space-y-3 custom-scrollbar">
          {result.stopped_early && result.convergence && (
            <div className="flex items-center gap-2 px-3 py-2 bg-emerald-50 border border-emerald-200 rounded-lg dark:bg-emerald-500/10 dark:border-emerald-700/40">
              <Zap size={12} className="text-emerald-600 dark:text-emerald-400" />
              <span className="text-xs text-emerald-800 dark:text-emerald-300">
                早停 · 收敛于第 {(result.convergence.decision_turn_index ?? 0) + 1} 轮 / 共 {result.turns.length} 轮
              </span>
              {result.convergence.judge_calls.length > 0 && (
                <span className="ml-auto text-[10px] text-emerald-700/70 font-mono">
                  相似度 {result.convergence.judge_calls.at(-1)?.similarity.toFixed(2)}
                </span>
              )}
            </div>
          )}
          {result.convergence && (result.convergence.judge_errors.length > 0) && (
            <div className="flex items-start gap-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg">
              <XCircle size={12} className="text-amber-600 mt-0.5 flex-shrink-0" />
              <span className="text-[11px] text-amber-800">
                收敛检查有 {result.convergence.judge_errors.length} 项失败（已记录但未阻断讨论）
              </span>
            </div>
          )}
          {/* Evidence pack — anchor cards for cited_evidence_ids pills.
              Each card carries id={evidenceSnippetDomId(eid)} so the
              per-trace pill onClick handler can scroll the card into view. */}
          <DiscussionEvidencePackSection result={result} />
          {/* Turns */}
          {result.turns.map(turn => (
            <div key={turn.turn_index} className="space-y-2">
              <h4 className="font-label text-[10px] font-medium text-foreground/40 uppercase tracking-wider">
                第 {turn.turn_index + 1} 轮
              </h4>
              {turn.agent_traces.map((trace: DiscussionAgentTrace) => (
                <div
                  key={trace.agent_id}
                  className={cn(
                    'rounded-lg border p-3 space-y-1.5 shadow-sm',
                    ROLE_COLOR_MAP[trace.role] || 'bg-gray-50 text-gray-700 border-gray-200',
                  )}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-label text-xs font-medium">
                        {trace.role_label || getRoleLabel(trace.role)}
                      </span>
                      <span className="text-[10px] text-foreground/40 font-mono">
                        {trace.provider}/{trace.model}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      {trace.success ? (
                        <CheckCircle2 size={10} className="text-emerald-500" />
                      ) : (
                        <XCircle size={10} className="text-red-500" />
                      )}
                      <span className="text-[10px] text-foreground/40 flex items-center gap-0.5">
                        <Clock size={9} />
                        {trace.latency_ms}ms
                      </span>
                    </div>
                  </div>
                  {trace.success && trace.answer && (
                    <p className="text-xs text-foreground/80 leading-relaxed whitespace-pre-wrap">
                      {trace.answer}
                    </p>
                  )}
                  {trace.success && trace.analysis_chain && (
                    <AnalysisChainPanel chain={trace.analysis_chain} className="mt-2" />
                  )}
                  {trace.success && trace.cited_evidence_ids && trace.cited_evidence_ids.length > 0 && (
                    <div
                      className="mt-1 flex flex-wrap gap-1"
                      data-testid={`cited-evidence-pills-${trace.agent_id}`}
                    >
                      {trace.cited_evidence_ids.map((eid) => (
                        <button
                          type="button"
                          key={eid}
                          onClick={() => scrollToEvidence(eid)}
                          className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-primary/10 text-primary hover:bg-primary/20"
                          aria-label={`定位证据 ${eid}`}
                        >
                          {eid}
                        </button>
                      ))}
                    </div>
                  )}
                  {!trace.success && trace.error && (
                    <p className="text-xs text-red-600">
                      此角色调用失败，请检查对应 API 设置。
                    </p>
                  )}
                </div>
              ))}
            </div>
          ))}

          {/* Synthesis */}
          {result.synthesis && (
            <div className="rounded-lg border border-primary/20 bg-surface-lowest p-4 shadow-sm space-y-2">
              <div className="flex items-center justify-between">
                <h4 className="font-label text-xs font-semibold text-primary">综合结论</h4>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-foreground/40 font-mono">
                    {result.synthesis.synthesizer_provider}/{result.synthesis.synthesizer_model}
                  </span>
                  <button
                    type="button"
                    onClick={() => navigator.clipboard.writeText(result.synthesis.text)}
                    className="text-foreground/30 hover:text-foreground/60"
                    title="复制"
                  >
                    <Copy size={12} />
                  </button>
                  {onInsertToEditor && (
                    <button
                      type="button"
                      onClick={handleInsertSynthesis}
                      className="text-xs text-primary hover:text-primary/80 font-label"
                    >
                      插入写作区
                    </button>
                  )}
                </div>
              </div>
              <p className="text-sm text-foreground/80 leading-relaxed whitespace-pre-wrap">
                {result.synthesis.text}
              </p>
              <p className="text-[10px] text-foreground/30">
                耗时 {result.elapsed_ms}ms · 策略：{getSynthesisStrategyLabel(result.synthesis.strategy)}
              </p>
            </div>
          )}

          {/* GraphPayload v0 viewer — plan §4.11 KG-1 Discussion-source
              prototype. Bipartite agent ↔ evidence; "uses" relation.
              No-data case (e.g. evidence_mode="none") yields agent-only. */}
          <DiscussionGraphSection result={result} />
        </div>
      )}
    </div>
  );
};

function DiscussionGraphSection({ result }: { result: DiscussionRunResult }) {
  const payload = useMemo(() => discussionToGraphPayload(result), [result]);
  const evidenceCount = payload.nodes.filter((n) => n.type === 'evidence').length;
  return (
    <div className="rounded-lg border border-outline-variant overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-outline-variant bg-surface-low">
        <span className="text-xs font-label text-foreground/70">
          讨论图谱 <span className="text-foreground/40">· 智能体 {payload.nodes.length - evidenceCount} · 证据 {evidenceCount} · 边 {payload.edges.length}</span>
        </span>
        {evidenceCount === 0 && (
          <span className="text-[10px] text-foreground/40">
            未启用证据来源，仅显示智能体
          </span>
        )}
      </div>
      <div className="h-[360px] bg-surface-lowest">
        <GraphPayloadViewer payload={payload} />
      </div>
    </div>
  );
}

interface EvidenceSnippetShape {
  chunk_id?: string;
  content?: string;
  source?: string;
  score?: number;
  material_id?: string;
  section_path?: string;
}

export function DiscussionEvidencePackSection({ result }: { result: DiscussionRunResult }) {
  const evidence = result.evidence;
  if (!evidence || !evidence.snippets || evidence.snippets.length === 0) return null;
  const snippets = evidence.snippets as unknown as EvidenceSnippetShape[];
  const ids = evidence.evidence_ids ?? snippets.map((_, i) => `E${i + 1}`);
  return (
    <div
      className="rounded-lg border border-outline-variant overflow-hidden"
      data-testid="discussion-evidence-pack"
    >
      <div className="px-3 py-2 border-b border-outline-variant bg-surface-low">
        <span className="text-xs font-label text-foreground/70">
          证据池 <span className="text-foreground/40">· {snippets.length} 条</span>
        </span>
      </div>
      <div className="p-2 space-y-1.5 bg-surface-lowest">
        {snippets.map((snippet, i) => {
          const eid = ids[i] ?? `E${i + 1}`;
          return (
            <div
              key={eid}
              id={evidenceSnippetDomId(eid)}
              data-testid={`evidence-snippet-${eid}`}
              className="rounded border border-outline-variant bg-white p-2 transition-shadow"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] font-mono text-primary">{eid}</span>
                <span className="text-[10px] text-foreground/40 font-mono truncate max-w-[60%]">
                  {snippet.source ?? snippet.chunk_id ?? ''}
                </span>
              </div>
              <p className="text-xs text-foreground/80 leading-relaxed line-clamp-3">
                {snippet.content ?? ''}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
