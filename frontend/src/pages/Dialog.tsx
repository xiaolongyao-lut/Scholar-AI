import axios from 'axios';
import { useState, useRef, useEffect, useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { MessageCircle, RefreshCw, Send, AlertCircle, History, X, BookOpen, Sparkles, Paperclip, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { TierSelector } from '@/components/chat/TierSelector';
import { MessageBubble } from '@/components/chat/MessageBubble';
import {
  sendIntelligentChatMessage,
  listChatSessions,
  resumeChatSession,
  isSessionModeConflictError,
  ContextTier,
  ChatMode,
  IntelligentChatResponse,
  ChatSessionSummary,
  ChatResumeMessage,
  ImageAttachment,
} from '@/services/intelligentChatApi';
import { useWriting } from '@/contexts/WritingContext';

// Dialog mode — see docs/plans/active/2026-05-13-dialog-merge-plan.md
// A2 ships the UI; A3 wires the backend `mode` JSON body field.
// 2026-05-24: inspiration mode removed from the Dialog UI; the backend
// ChatMode enum still recognises `inspiration` for any other caller, but
// Dialog itself only exposes direct + literature_qa.
export type DialogMode = 'direct' | 'literature_qa';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  tierUsed?: ContextTier;
  contextMetadata?: IntelligentChatResponse['context_metadata'];
  evidenceRefs?: IntelligentChatResponse['evidence_refs'];
  actualSamplingParams?: IntelligentChatResponse['actual_sampling_params'];
  timestamp: Date;
  insufficientContext?: boolean;
}

type ChatState = 'ready' | 'responding' | 'error' | 'unavailable';
type HistoryState = 'idle' | 'loading' | 'error';

function getChatErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error) && error.response) {
    const detail = error.response.data?.detail ?? error.response.data?.error?.message;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object') return JSON.stringify(detail);
    return `Request failed (${error.response.status})`;
  }
  if (error instanceof Error) return error.message;
  return 'Failed to send message. Please try again.';
}

function isUnavailableError(error: unknown): boolean {
  if (!axios.isAxiosError(error) || !error.response) return false;
  if (error.response.status !== 400) return false;
  const detail = error.response.data?.detail;
  const message = typeof detail === 'string' ? detail : error.response.data?.error?.message;
  return typeof message === 'string' && message.toLowerCase().includes('no literature source paths configured');
}

function parseChatTimestamp(value: string): Date {
  if (!value.trim()) return new Date();
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
}

function toChatMessage(message: ChatResumeMessage): ChatMessage {
  if (message.role !== 'user' && message.role !== 'assistant') {
    throw new Error('Unsupported chat message role');
  }
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    tierUsed: message.tier_used ?? undefined,
    contextMetadata: message.context_metadata ?? undefined,
    evidenceRefs: message.evidence_refs ?? undefined,
    timestamp: parseChatTimestamp(message.timestamp),
    insufficientContext: message.role === 'assistant' && !message.context_metadata,
  };
}

function parseInitialMode(search: string): DialogMode {
  const params = new URLSearchParams(search);
  const m = params.get('mode');
  if (m === 'direct' || m === 'literature_qa') return m;
  // 2026-05-24: inspiration mode removed from Dialog UI; redirect callers
  // to literature_qa so old bookmarks / nav links keep landing somewhere.
  return 'literature_qa';
}

// Vision P0 image attachment limits (Slice 2.5 prerequisite — frontend only, no provider call).
const VISION_MAX_IMAGES = 6;
const VISION_MAX_BYTES = 4 * 1024 * 1024; // 4 MB per image
const VISION_ALLOWED_MIME = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== 'string') {
        reject(new Error('FileReader returned non-string result'));
        return;
      }
      const commaIdx = result.indexOf(',');
      resolve(commaIdx >= 0 ? result.slice(commaIdx + 1) : result);
    };
    reader.onerror = () => reject(reader.error ?? new Error('FileReader error'));
    reader.readAsDataURL(file);
  });
}

const MODE_META: Record<DialogMode, { label: string; placeholder: string; emptyHint: string; icon: typeof BookOpen }> = {
  direct: {
    label: '直调',
    placeholder: '直接向 AI 提问（不检索文献）…',
    emptyHint: '直调模式：AI 直接回答你的问题（不检索文献库）。',
    icon: Sparkles,
  },
  literature_qa: {
    label: '文献问答',
    placeholder: '从你的文献库中提问…',
    emptyHint: '文献模式：AI 会从你的文献库中检索相关内容并基于证据回答。',
    icon: BookOpen,
  },
};

export function Dialog() {
  const { activeProjectId } = useWriting();
  const location = useLocation();
  const navigate = useNavigate();

  // mode is initial-seeded from URL ?mode=; subsequent toggles do not write the URL back
  // to avoid history thrashing. The redirect targets from /chat /inspiration use this
  // mechanism (A6 ships the redirect).
  const [mode, setMode] = useState<DialogMode>(() => parseInitialMode(location.search));

  // Persistence keys are scoped by project + mode so switching modes doesn't
  // contaminate history. Leaving the page (route change) used to drop messages
  // entirely; rehydration below restores them on re-entry.
  const inputStorageKey = `dialog-input_${activeProjectId || 'default'}_${mode}`;
  const sessionStorageKey = `dialog-session_${activeProjectId || 'default'}_${mode}`;
  const messagesStorageKey = `dialog-messages_${activeProjectId || 'default'}_${mode}`;
  const loadPersistedMessages = (): ChatMessage[] => {
    try {
      const raw = localStorage.getItem(messagesStorageKey);
      if (!raw) return [];
      const parsed = JSON.parse(raw) as Array<Omit<ChatMessage, 'timestamp'> & { timestamp: string }>;
      return parsed.map(m => ({ ...m, timestamp: new Date(m.timestamp) }));
    } catch {
      return [];
    }
  };
  const [messages, setMessages] = useState<ChatMessage[]>(() => loadPersistedMessages());
  const [inputValue, setInputValue] = useState<string>(() => {
    try { return localStorage.getItem(inputStorageKey) ?? ''; } catch { return ''; }
  });
  const [sessionId, setSessionId] = useState<string | undefined>(() => {
    try { return localStorage.getItem(sessionStorageKey) ?? undefined; } catch { return undefined; }
  });
  const [selectedTier, setSelectedTier] = useState<ContextTier>('balanced');
  const [chatState, setChatState] = useState<ChatState>('ready');
  const [historyState, setHistoryState] = useState<HistoryState>('idle');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isUnavailable, setIsUnavailable] = useState(false);
  // Vision P0 image attachment state (Slice 2.5 prerequisite, no provider call).
  const [attachedImages, setAttachedImages] = useState<ImageAttachment[]>([]);
  const [imageReadingCount, setImageReadingCount] = useState(0);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      if (inputValue) localStorage.setItem(inputStorageKey, inputValue);
      else localStorage.removeItem(inputStorageKey);
    } catch { /* storage quota */ }
  }, [inputValue, inputStorageKey]);

  useEffect(() => {
    try { setInputValue(localStorage.getItem(inputStorageKey) ?? ''); } catch { setInputValue(''); }
  }, [inputStorageKey]);

  // Persist messages and sessionId so route changes don't drop in-flight conversations.
  // Cap at the last 50 messages to avoid localStorage quota issues on long chats.
  useEffect(() => {
    try {
      if (messages.length === 0) {
        localStorage.removeItem(messagesStorageKey);
      } else {
        const trimmed = messages.slice(-50);
        localStorage.setItem(messagesStorageKey, JSON.stringify(trimmed));
      }
    } catch { /* storage quota */ }
  }, [messages, messagesStorageKey]);

  useEffect(() => {
    try {
      if (sessionId) localStorage.setItem(sessionStorageKey, sessionId);
      else localStorage.removeItem(sessionStorageKey);
    } catch { /* storage quota */ }
  }, [sessionId, sessionStorageKey]);

  // When project/mode storage keys change, rehydrate messages and session.
  useEffect(() => {
    setMessages(loadPersistedMessages());
    try { setSessionId(localStorage.getItem(sessionStorageKey) ?? undefined); } catch { setSessionId(undefined); }

  }, [messagesStorageKey, sessionStorageKey]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => { scrollToBottom(); }, [messages]);

  const handleModeChange = (next: DialogMode) => {
    if (next === mode) return;
    // Per D-DM-5: session.mode is immutable. If we already have messages in
    // the current session, opening a new mode means a new session — drop
    // session_id so the next send creates one. The 409 backend enforcement
    // lands in A3; for A2 the UI is the only gate.
    if (messages.length > 0) {
      setSessionId(undefined);
      setMessages([]);
    }
    setMode(next);
    // Clear ?mode= from the URL once the user toggles inside the page so the
    // back button does not re-seed the wrong mode.
    if (location.search) navigate(location.pathname, { replace: true });
  };

  const refreshSessions = async () => {
    setHistoryState('loading');
    try {
      const next = await listChatSessions();
      setSessions(next);
      setHistoryState('idle');
    } catch (error) {
      setHistoryState('error');
      setErrorMessage(getChatErrorMessage(error));
    }
  };

  const handleNewSession = () => {
    setMessages([]);
    setSessionId(undefined);
    setErrorMessage(null);
    setIsUnavailable(false);
    setChatState('ready');
  };

  const handleOpenHistory = async () => {
    setHistoryOpen(true);
    await refreshSessions();
  };

  const handleResumeSession = async (nextSessionId: string) => {
    const normalizedSessionId = nextSessionId.trim();
    if (!normalizedSessionId || chatState === 'responding') return;
    setHistoryState('loading');
    setErrorMessage(null);
    try {
      const response = await resumeChatSession({ session_id: normalizedSessionId, limit: 100 });
      setSessionId(response.session_id);
      setMessages(response.messages.map(toChatMessage));
      setIsUnavailable(false);
      setChatState('ready');
      setHistoryOpen(false);
      setHistoryState('idle');
    } catch (error) {
      setHistoryState('error');
      setErrorMessage(getChatErrorMessage(error));
    }
  };

  const handleImagePick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = '';
    if (files.length === 0) return;
    const remaining = VISION_MAX_IMAGES - attachedImages.length - imageReadingCount;
    if (remaining <= 0) {
      setErrorMessage(`最多 ${VISION_MAX_IMAGES} 张图片`);
      return;
    }
    const slice = files.slice(0, remaining);
    if (files.length > remaining) {
      setErrorMessage(`只能再添加 ${remaining} 张图片，已忽略多余文件`);
    }
    setImageReadingCount((c) => c + slice.length);
    const accepted: ImageAttachment[] = [];
    for (const file of slice) {
      if (!VISION_ALLOWED_MIME.has(file.type)) {
        setErrorMessage(`不支持的图片类型：${file.type || '未知'}`);
        continue;
      }
      if (file.size > VISION_MAX_BYTES) {
        setErrorMessage(`「${file.name}」超过 ${VISION_MAX_BYTES / 1024 / 1024} MB 单图上限`);
        continue;
      }
      try {
        const data_b64 = await fileToBase64(file);
        accepted.push({ mime: file.type, data_b64, size: file.size, name: file.name });
      } catch {
        setErrorMessage(`无法读取「${file.name}」`);
      }
    }
    setAttachedImages((prev) => [...prev, ...accepted]);
    setImageReadingCount((c) => Math.max(0, c - slice.length));
  };

  const removeImage = (idx: number) => {
    setAttachedImages((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleSendMessage = async () => {
    const query = inputValue.trim();
    if (!query || chatState === 'responding') return;

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: query,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setChatState('responding');
    setErrorMessage(null);

    // A3-onwards: pass structured `mode` to the backend. On 409
    // session_mode_conflict (D-DM-5), drop session_id and retry once
    // automatically — the user already saw the local message echo, no
    // need to re-type.
    const sendOnce = async (currentSessionId: string | undefined) =>
      sendIntelligentChatMessage({
        query,
        session_id: currentSessionId,
        tier: selectedTier,
        project_id: activeProjectId || undefined,
        mode,
        images: attachedImages.length > 0 ? attachedImages : undefined,
      });

    try {
      let response: IntelligentChatResponse;
      try {
        response = await sendOnce(sessionId);
      } catch (firstError) {
        const conflict = isSessionModeConflictError(firstError);
        if (!conflict) throw firstError;
        // Mode-immutable session — open a new one transparently
        setSessionId(undefined);
        response = await sendOnce(undefined);
      }

      if (!sessionId || response.session_id !== sessionId) setSessionId(response.session_id);
      setIsUnavailable(false);

      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.response,
        tierUsed: response.tier_used,
        contextMetadata: response.context_metadata,
        evidenceRefs: response.evidence_refs,
        actualSamplingParams: response.actual_sampling_params,
        timestamp: new Date(),
        insufficientContext: response.context_chunks_used === 0,
      };
      setMessages((prev) => [...prev, assistantMessage]);
      setChatState('ready');
      if (attachedImages.length > 0) setAttachedImages([]);
    } catch (error) {
      const errorMsg = getChatErrorMessage(error);
      if (isUnavailableError(error)) {
        setIsUnavailable(true);
        setChatState('unavailable');
      } else {
        setIsUnavailable(false);
        setErrorMessage(errorMsg);
        setChatState('error');
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const isInputDisabled = chatState === 'responding';
  const meta = useMemo(() => MODE_META[mode], [mode]);

  return (
    <div className="flex h-full flex-col bg-background">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 border-b border-outline-variant/60 bg-surface-low px-6 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <MessageCircle className="h-5 w-5 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0">
            <h1 className="truncate font-display text-lg font-semibold text-foreground">对话</h1>
            <p className="truncate font-label text-xs text-foreground/55">
              单 Agent 对话：直问 / 文献问答 / 灵感生成，切换模式会开启新会话
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={handleOpenHistory}
            className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-2.5 py-1.5 text-xs font-medium text-foreground/75 transition-colors hover:border-primary/40 hover:text-foreground"
          >
            <History className="h-3.5 w-3.5" /> 历史会话
          </button>
          <button
            type="button"
            onClick={handleNewSession}
            className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-2.5 py-1.5 text-xs font-medium text-foreground/75 transition-colors hover:border-primary/40 hover:text-foreground"
          >
            <RefreshCw className="h-3.5 w-3.5" /> 新建会话
          </button>
        </div>
      </div>

      {/* Mode toggle bar (plan §12 D-DM-2: top horizontal button group) */}
      <div className="flex items-center gap-2 border-b border-outline-variant/60 bg-surface-lowest px-6 py-2.5">
        {(['direct', 'literature_qa'] as const).map((m) => {
          const M = MODE_META[m];
          const Icon = M.icon;
          const active = m === mode;
          return (
            <button
              key={m}
              type="button"
              onClick={() => handleModeChange(m)}
              disabled={isInputDisabled}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors',
                active
                  ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                  : 'border-outline-variant/60 bg-surface-lowest text-foreground/70 hover:border-primary/40 hover:text-foreground',
                'disabled:cursor-not-allowed disabled:opacity-50',
              )}
            >
              <Icon className="h-4 w-4" />
              {M.label}
            </button>
          );
        })}
      </div>

      {historyOpen && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={() => setHistoryOpen(false)}>
          <aside
            className="h-full w-full max-w-md bg-surface-lowest shadow-xl border-l border-outline-variant/60 flex flex-col"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-outline-variant/60 px-5 py-4">
              <div>
                <h2 className="text-lg font-semibold text-foreground">历史会话</h2>
                <p className="text-xs text-foreground/55">恢复一段此前的对话以继续讨论</p>
              </div>
              <button
                type="button"
                onClick={() => setHistoryOpen(false)}
                className="rounded-md p-2 text-foreground/55 transition-colors hover:bg-surface-high hover:text-foreground"
                aria-label="关闭历史"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="border-b border-outline-variant/40 px-5 py-3">
              <button
                type="button"
                onClick={refreshSessions}
                disabled={historyState === 'loading'}
                className="flex w-full items-center justify-center gap-2 rounded-md border border-outline-variant/60 bg-surface-low px-3 py-2 text-sm font-medium text-foreground/75 transition-colors hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
              >
                <RefreshCw className={`h-4 w-4 ${historyState === 'loading' ? 'animate-spin' : ''}`} />
                刷新会话列表
              </button>
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              {historyState === 'loading' && sessions.length === 0 ? (
                <div className="py-8 text-center text-sm text-foreground/55">正在加载会话…</div>
              ) : sessions.length === 0 ? (
                <div className="py-8 text-center text-sm text-foreground/55">暂无保存的会话</div>
              ) : (
                sessions.map((item) => {
                  // Legacy sessions can carry the now-removed `inspiration` mode;
                  // map those to literature_qa so the history pill stays useful.
                  const sessionMode: DialogMode | null =
                    item.mode === 'direct' || item.mode === 'literature_qa'
                      ? item.mode
                      : item.mode === 'inspiration'
                        ? 'literature_qa'
                        : null;
                  const modeMeta = sessionMode ? MODE_META[sessionMode] : null;
                  // Friendly short label hides raw session_xxx ids per R5.
                  const shortLabel = `会话 #${item.session_id.slice(-6)}`;
                  return (
                    <button
                      key={item.session_id}
                      type="button"
                      onClick={() => handleResumeSession(item.session_id)}
                      disabled={historyState === 'loading' || chatState === 'responding'}
                      className="w-full rounded-md border border-outline-variant/60 bg-surface-low p-4 text-left transition-colors hover:border-primary/40 hover:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <div className="mb-2 flex items-center justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className="truncate text-xs font-medium text-foreground/70">{shortLabel}</span>
                          {modeMeta && (
                            <span className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                              <modeMeta.icon className="h-3 w-3" />
                              {modeMeta.label}
                            </span>
                          )}
                          {item.legacy_mode_inferred && (
                            <span
                              title="此会话早于模式区分，按文献问答恢复"
                              className="inline-flex items-center rounded-md border border-outline-variant bg-surface-high px-1.5 py-0.5 text-[10px] text-foreground/60"
                            >
                              旧版
                            </span>
                          )}
                        </div>
                        <span className="whitespace-nowrap text-xs text-foreground/55">{item.total_turns} 轮</span>
                      </div>
                      <p className="line-clamp-2 text-sm text-foreground/85">{item.preview || '（无标题会话）'}</p>
                      {item.updated_at && (
                        <p className="mt-2 text-xs text-foreground/55">
                          最近更新 {parseChatTimestamp(item.updated_at).toLocaleString()}
                        </p>
                      )}
                    </button>
                  );
                })
              )}
            </div>
          </aside>
        </div>
      )}

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {isUnavailable && (
          <div className="mb-4 p-4 bg-yellow-50 border-l-4 border-yellow-400 rounded-lg">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" />
              <div>
                <h3 className="text-sm font-semibold text-yellow-800 mb-1">Chat Service Unavailable</h3>
                <p className="text-sm text-yellow-700 mb-2">
                  No literature sources are currently configured in the knowledge base.
                </p>
                <p className="text-xs text-yellow-600">
                  To use literature mode, please add literature sources in the <strong>Knowledge Base</strong> section first.
                </p>
              </div>
            </div>
          </div>
        )}

        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <MessageCircle className="mb-4 h-16 w-16 text-foreground/25" />
            <h2 className="mb-2 text-xl font-semibold text-foreground/75">开始一段对话</h2>
            <p className="max-w-md text-foreground/55">{meta.emptyHint}</p>
          </div>
        ) : (
          messages.map((message) => (
            <MessageBubble
              key={message.id}
              role={message.role}
              content={message.content}
              tierUsed={message.tierUsed}
              contextMetadata={message.contextMetadata}
              evidenceRefs={message.evidenceRefs}
              actualSamplingParams={message.actualSamplingParams}
              timestamp={message.timestamp}
              insufficientContext={message.insufficientContext}
              projectId={activeProjectId}
            />
          ))
        )}

        {chatState === 'responding' && (
          <div className="flex justify-start">
            <div className="rounded-md border border-outline-variant/60 bg-surface-low px-4 py-3">
              <div className="flex items-center gap-2 text-foreground/65">
                <div className="flex gap-1">
                  <span className="h-2 w-2 animate-bounce rounded-full bg-foreground/40" style={{ animationDelay: '0ms' }} />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-foreground/40" style={{ animationDelay: '150ms' }} />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-foreground/40" style={{ animationDelay: '300ms' }} />
                </div>
                <span className="text-sm">Thinking...</span>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Error banner */}
      {errorMessage && (
        <div className="px-6 py-3 bg-red-50 border-t border-red-200">
          <div className="flex items-center justify-between">
            <p className="text-sm text-red-800">{errorMessage}</p>
            <button
              type="button"
              onClick={() => setErrorMessage(null)}
              className="text-sm text-red-600 hover:text-red-800 font-medium"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-outline-variant/60 bg-surface-low px-6 py-4">
        {mode !== 'direct' && (
          <div className="mb-3">
            <TierSelector
              selectedTier={selectedTier}
              onTierChange={setSelectedTier}
              disabled={isInputDisabled}
            />
          </div>
        )}

        {(attachedImages.length > 0 || imageReadingCount > 0) && (
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {attachedImages.map((img, idx) => (
              <div key={`${img.name ?? 'img'}-${idx}`} className="group relative">
                <img
                  src={`data:${img.mime};base64,${img.data_b64}`}
                  alt={img.name ?? `附件图片 ${idx + 1}`}
                  className="h-16 w-16 rounded-md border border-outline-variant/60 object-cover"
                />
                <button
                  type="button"
                  onClick={() => removeImage(idx)}
                  aria-label={`移除「${img.name ?? `图片 ${idx + 1}`}」`}
                  title="移除图片"
                  className="absolute -right-1.5 -top-1.5 inline-flex h-5 w-5 items-center justify-center rounded-full bg-foreground/80 text-background opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
            {imageReadingCount > 0 && (
              <div
                role="status"
                aria-label="正在读取图片"
                className="flex h-16 w-16 items-center justify-center rounded-md border border-dashed border-outline-variant/60 bg-surface-lowest"
              >
                <Loader2 className="h-4 w-4 animate-spin text-foreground/40" />
              </div>
            )}
            <span className="font-label text-[10px] text-foreground/45">
              {attachedImages.length}/{VISION_MAX_IMAGES} · 视觉辅助暂未启用,图片随消息传输但不会被分析
            </span>
          </div>
        )}

        <div className="flex gap-3">
          <textarea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isInputDisabled}
            placeholder={meta.placeholder}
            className="flex-1 resize-none rounded-md border border-outline-variant/60 bg-surface-lowest px-4 py-3 text-sm text-foreground transition-colors focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:cursor-not-allowed disabled:bg-surface-low"
            rows={3}
          />
          <input
            ref={fileInputRef}
            type="file"
            accept={Array.from(VISION_ALLOWED_MIME).join(',')}
            multiple
            onChange={handleImagePick}
            className="hidden"
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isInputDisabled || attachedImages.length + imageReadingCount >= VISION_MAX_IMAGES}
            aria-label={`添加图片附件,最多 ${VISION_MAX_IMAGES} 张,单张 ≤ ${VISION_MAX_BYTES / 1024 / 1024} MB`}
            title={`添加图片附件 (最多 ${VISION_MAX_IMAGES} 张,单张 ≤ ${VISION_MAX_BYTES / 1024 / 1024} MB)`}
            className="inline-flex items-center justify-center rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-3 text-foreground/70 transition-colors hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Paperclip className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={handleSendMessage}
            disabled={isInputDisabled || !inputValue.trim()}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-5 py-3 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
            发送
          </button>
        </div>

        <p className="mt-2 text-xs text-foreground/55">
          按 Enter 发送，Shift+Enter 换行
        </p>
      </div>
    </div>
  );
}
