import React, { lazy, Suspense, useState, useEffect, useCallback, useRef } from 'react';
import { BookOpen, Search, MessageSquare, Loader2, Send, Sparkles, FileText, ChevronRight, Trash2, History, PenLine, Download, X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { useWriting } from '@/contexts/WritingContext';
import { getLLMConfig, loadSettings, saveSettings } from '@/services/settingsStore';
import { getApiBaseUrl } from '@/services/apiBaseUrl';
import { askChatWithConfig, type ChatHistoryMessage } from '@/services/chatApi';
import axios from 'axios';
import { SessionDrawer } from '@/components/writing/SessionDrawer';
import type { ResumeSessionResult } from '@/types/runtime';
import { exportToDocx, downloadBlob } from '@/services/exportApi';

const TipTapEditor = lazy(() =>
  import('@/components/TipTapEditor/TipTapEditor').then((m) => ({
    default: m.TipTapEditor,
  })),
);

const TipTapEditorFallback = () => (
  <div className="flex h-full w-full items-center justify-center text-foreground/40">
    <Loader2 className="h-6 w-6 animate-spin" aria-label="Loading editor" />
  </div>
);

interface TokenUsage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  // Claude API uses different field names
  input_tokens?: number;
  output_tokens?: number;
}

import { mapTimelineToMessages, type WorkbenchMessage } from '@/components/writing/sessionDrawerHelpers';
import { EvidenceGraphPanel } from '@/components/graph/EvidenceGraphPanel';
import { McpScopePicker } from '@/components/mcp/McpScopePicker';

type Message = WorkbenchMessage;
type MessageSource = NonNullable<WorkbenchMessage['sources']>[number];

interface RetrievedChunk {
  chunk_id: string;
  material_id: string;
  title: string;
  chunk_index: number;
  content: string;
  score?: number;
  page?: number | null;
}

const EXAMPLE_QUERIES = [
  '总结文献中的核心方法与结论',
  '提取关键实验数据并对比分析',
  '对比不同方案的优缺点',
];

const CHAT_HISTORY_KEY = 'smart_reading_history_v1';

const RETRIEVAL_TOP_K_MIN = 3;
const RETRIEVAL_TOP_K_MAX = 20;
const RETRIEVAL_TOP_K_DEFAULT = 6;
const FIRST_QUESTION_SCAN_DEFAULTS = {
  ingestLimit: 8,
  scanMode: 'fast',
  scanBatchSize: 24,
  scanMaxWorkers: 8,
} as const;

/** Normalize token usage across OpenAI-compatible (prompt_tokens/completion_tokens)
 *  and Claude (input_tokens/output_tokens) response formats. */
function normalizeUsage(raw: TokenUsage): { input: number; output: number; total: number } {
  const input = raw.prompt_tokens ?? raw.input_tokens ?? 0;
  const output = raw.completion_tokens ?? raw.output_tokens ?? 0;
  const total = raw.total_tokens ?? input + output;
  return { input, output, total };
}

function fmtTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

/** Compact token usage badge displayed under each assistant reply. */
function TokenBadge({ usage, model }: { usage: TokenUsage; model?: string }) {
  const { input, output, total } = normalizeUsage(usage);
  if (total === 0 && input === 0 && output === 0) return null;
  return (
    <div className="mt-2.5 pt-2.5 border-t border-outline-variant/20 flex flex-wrap items-center gap-x-3 gap-y-1">
      <span title="输入 tokens" className="flex items-center gap-0.5 text-[10px] font-label text-foreground/40">
        <span className="text-blue-400/80">↑</span>{fmtTokens(input)}
      </span>
      <span title="输出 tokens" className="flex items-center gap-0.5 text-[10px] font-label text-foreground/40">
        <span className="text-emerald-400/80">↓</span>{fmtTokens(output)}
      </span>
      <span title="总 tokens" className="flex items-center gap-0.5 text-[10px] font-label text-foreground/55 font-medium">
        ∑{fmtTokens(total)}
      </span>
      {model && (
        <span className="ml-auto text-[10px] font-label text-foreground/25 truncate max-w-[200px]" title={model}>
          {model}
        </span>
      )}
    </div>
  );
}

import { useToast } from '@/components/ui/Toast';

export function Workbench() {
  const { t } = useI18n();
  const { toast } = useToast();
  const navigate = useNavigate();
  const { activeProjectId } = useWriting();
  const inputStorageKey = `workbench-input_${activeProjectId || 'default'}`;
  const [query, setQuery] = useState<string>(() => {
    try { return localStorage.getItem(inputStorageKey) ?? ''; } catch { return ''; }
  });
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [ingestMode, setIngestMode] = useState<'none' | 'query' | 'full'>('query');
  const [aiCostProfile, setAiCostProfile] = useState<'balanced' | 'aggressive' | 'quality'>(
    loadSettings().workspace.aiCostProfile ?? 'balanced'
  );
  const [sessionDrawerOpen, setSessionDrawerOpen] = useState(false);
  const [isRehydrating, setIsRehydrating] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorContent, setEditorContent] = useState('');
  const [mcpServerIds, setMcpServerIds] = useState<string[]>([]);
  const [editorJson, setEditorJson] = useState<object>({});
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    try {
      if (query) localStorage.setItem(inputStorageKey, query);
      else localStorage.removeItem(inputStorageKey);
    } catch { /* storage quota */ }
  }, [query, inputStorageKey]);

  useEffect(() => {
    try {
      setQuery(localStorage.getItem(inputStorageKey) ?? '');
    } catch { setQuery(''); }
  }, [inputStorageKey]);

  /**
   * Resume handler — minimal MVP hook. Full timeline rehydration into the
   * Workbench chat view lives behind the backend session memory contract;
   * here we surface a toast so the user sees the action landed, then close
   * the drawer. Richer rewire (replay timeline into `messages`) is queued
   * for post-MVP (`OPEN_THREADS.md A7`).
   */
  const handleSessionResumed = useCallback((result: ResumeSessionResult) => {
    setIsRehydrating(true);
    const mappedMessages = mapTimelineToMessages(result.timeline || []);
    setTimeout(() => {
      setMessages(mappedMessages);
      setIsRehydrating(false);
      toast(t('workbench.session_resumed'), 'success');
      setSessionDrawerOpen(false);
    }, 600);
  }, [t, toast]);

  const handleSessionForked = useCallback((result: ResumeSessionResult) => {
    setIsRehydrating(true);
    const mappedMessages = mapTimelineToMessages(result.timeline || []);
    setTimeout(() => {
      setMessages(mappedMessages);
      setIsRehydrating(false);
      toast(t('workbench.session_forked'), 'success');
      setSessionDrawerOpen(false);
    }, 800);
  }, [t, toast]);

  const handleSessionRewound = useCallback((result: ResumeSessionResult) => {
    setIsRehydrating(true);
    const mappedMessages = mapTimelineToMessages(result.timeline || []);
    setTimeout(() => {
      setMessages(mappedMessages);
      setIsRehydrating(false);
      toast(t('workbench.session_rewound'), 'success');
    }, 500);
  }, [t, toast]);

  // Load saved messages when project changes
  useEffect(() => {
    if (!activeProjectId) { setMessages([]); return; }
    try {
      const raw = localStorage.getItem(`${CHAT_HISTORY_KEY}_${activeProjectId}`);
      setMessages(raw ? (JSON.parse(raw) as Message[]) : []);
    } catch { setMessages([]); }
  }, [activeProjectId]);

  // Persist messages to localStorage on every change
  useEffect(() => {
    if (!activeProjectId) return;
    try {
      const toSave = messages.filter(m => !m.error).slice(-50);
      if (toSave.length === 0) {
        localStorage.removeItem(`${CHAT_HISTORY_KEY}_${activeProjectId}`);
      } else {
        localStorage.setItem(`${CHAT_HISTORY_KEY}_${activeProjectId}`, JSON.stringify(toSave));
      }
    } catch { /* storage quota */ }
  }, [messages, activeProjectId]);

  const retrieveDocContext = useCallback(async (currentQuery: string) => {
    if (!activeProjectId) {
      return { context: [] as string[], sources: [] as MessageSource[] };
    }

    try {
      const { data } = await axios.get(`${getApiBaseUrl()}/resources/chunks/search`, {
        params: {
          project_id: activeProjectId,
          query: currentQuery,
          top_k: Math.min(
            RETRIEVAL_TOP_K_MAX,
            Math.max(RETRIEVAL_TOP_K_MIN, loadSettings().workspace.retrievalTopK ?? RETRIEVAL_TOP_K_DEFAULT),
          ),
          ingest_mode: ingestMode,
          ai_cost_profile: aiCostProfile,
          ingest_limit: FIRST_QUESTION_SCAN_DEFAULTS.ingestLimit,
          scan_mode: FIRST_QUESTION_SCAN_DEFAULTS.scanMode,
          scan_batch_size: FIRST_QUESTION_SCAN_DEFAULTS.scanBatchSize,
          scan_max_workers: FIRST_QUESTION_SCAN_DEFAULTS.scanMaxWorkers,
        },
        timeout: 60000,
      });

      const results: RetrievedChunk[] = (data.results ?? []).filter(
        (chunk: RetrievedChunk) => chunk.content && chunk.content.trim(),
      );

      if (results.length > 0) {
        return {
          context: results.map(chunk => `【${chunk.title}｜片段 ${chunk.chunk_index + 1}】\n${chunk.content}`),
          sources: results.map(chunk => ({
            title: chunk.title,
            page: `片段 ${chunk.chunk_index + 1}`,
            material_id: chunk.material_id,
            chunk_id: chunk.chunk_id,
            page_number: typeof chunk.page === 'number' && chunk.page > 0 ? chunk.page : undefined,
          })),
        };
      }

      const { data: docs } = await axios.get(`${getApiBaseUrl()}/resources/documents`, {
        params: { project_id: activeProjectId },
        timeout: 10000,
      });

      const fallbackDocs = (docs as { material_id?: string; title: string; content: string }[])
        .filter(doc => doc.content && doc.content.trim())
        .slice(0, 2);

      return {
        context: fallbackDocs.map(doc => `【${doc.title}】\n${doc.content.slice(0, 1600)}`),
        sources: fallbackDocs.map(doc => ({
          title: doc.title,
          page: '文档摘要',
          material_id: doc.material_id,
        })),
      };
    } catch {
      return { context: [] as string[], sources: [] as MessageSource[] };
    }
  }, [activeProjectId, ingestMode, aiCostProfile]);

  const handleClearHistory = () => {
    if (activeProjectId) localStorage.removeItem(`${CHAT_HISTORY_KEY}_${activeProjectId}`);
    setMessages([]);
  };

  const handleInsertToEditor = useCallback((text: string) => {
    setEditorContent(prev => prev ? prev + '<p>' + text.replace(/\n/g, '<br>') + '</p>' : '<p>' + text.replace(/\n/g, '<br>') + '</p>');
    if (!editorOpen) setEditorOpen(true);
  }, [editorOpen]);

  const handleSubmit = async () => {
    if (!query.trim() || isLoading) return;
    const userMsg: Message = { id: Date.now(), role: 'user', content: query };
    // Capture current history BEFORE adding the new user message
    const historySnapshot: ChatHistoryMessage[] = messages
      .filter(m => !m.error)
      .map(m => ({ role: m.role, content: m.content }));
    setMessages(prev => [...prev, userMsg]);
    const currentQuery = query;
    setQuery('');
    setIsLoading(true);

    try {
      const llmConfig = getLLMConfig();

      const retrieval = await retrieveDocContext(currentQuery);

      const data = await askChatWithConfig({
        query: currentQuery,
        context: retrieval.context,
        history: historySnapshot,
        llm: llmConfig,
        aiCostProfile,
        mcpServerIds: mcpServerIds.length > 0 ? mcpServerIds : undefined,
      });

      const assistantMsg: Message = {
        id: Date.now() + 1,
        role: 'assistant',
        content: data.answer,
        sources: retrieval.sources.length > 0 ? retrieval.sources : undefined,
        usage: data.usage ?? undefined,
        model: data.model ?? undefined,
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (err: unknown) {
      let errMsg = '未知错误';
      if (axios.isAxiosError(err) && err.response) {
        const d = err.response.data;
        // Support new ErrorResponse format { ok: false, error: { message: "..." } }
        if (d?.error?.message) {
          errMsg = d.error.message;
        } else if (d?.detail) {
          errMsg = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail);
        } else {
          errMsg = `请求失败 (${err.response.status})`;
        }
        const lowered = String(errMsg).toLowerCase();
        if (lowered.includes('authentication') || lowered.includes('invalid api key') || lowered.includes('api key') || lowered.includes('unauthorized')) {
          errMsg = 'LLM 鉴权失败：当前 Key 可能无效或已过期。请在「系统设置」更新 Key，或改为使用服务端环境变量 Key。';
        } else if (lowered.includes('invalidendpointormodel.notfound') || lowered.includes('model or endpoint') || lowered.includes('model_not_found')) {
          errMsg = '模型或端点不存在：请检查「Provider / Base URL / Model」三项是否匹配，并确认账号已开通该模型权限。';
        }
      } else if (err instanceof Error) {
        errMsg = err.message;
      }
      const assistantMsg: Message = {
        id: Date.now() + 1,
        role: 'assistant',
        content: errMsg,
        error: true,
      };
      setMessages(prev => [...prev, assistantMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative flex flex-row h-full">
      {/* Left: Chat panel */}
      <div className={cn('relative flex flex-col h-full transition-all', editorOpen ? 'w-1/2 min-w-0' : 'w-full')}>
      {/* Session drawer trigger — top-right floating button */}
      <button
        type="button"
        onClick={() => setSessionDrawerOpen(true)}
        aria-label="打开会话历史"
        title="会话历史（恢复 / fork / rewind）"
        className="absolute top-4 right-4 z-40 inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-surface-high/80 backdrop-blur border border-outline-variant/60 font-label text-[11px] text-foreground/70 hover:text-foreground hover:border-primary/30 transition-all shadow-sm"
      >
        <History size={13} />
        <span>会话</span>
      </button>
      {/* Writing panel toggle */}
      <button
        type="button"
        onClick={() => setEditorOpen(v => !v)}
        aria-label={editorOpen ? '关闭写作面板' : '打开写作面板'}
        title={editorOpen ? '关闭写作面板' : '打开写作面板'}
        className={cn(
          'absolute top-4 right-24 z-40 inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md backdrop-blur border font-label text-[11px] transition-all shadow-sm',
          editorOpen
            ? 'bg-primary/15 text-primary border-primary/30 hover:bg-primary/25'
            : 'bg-surface-high/80 text-foreground/70 border-outline-variant/60 hover:text-foreground hover:border-primary/30'
        )}
      >
        <PenLine size={13} />
        <span>写作</span>
      </button>
      <SessionDrawer
        isOpen={sessionDrawerOpen}
        onClose={() => setSessionDrawerOpen(false)}
        onSessionResumed={handleSessionResumed}
        onSessionForked={handleSessionForked}
        onSessionRewound={handleSessionRewound}
      />

      {messages.length === 0 ? (
        /* Empty state — welcome screen */
        <div className="flex-1 flex flex-col items-center justify-center p-8">
          {!activeProjectId ? (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35 }}
              className="text-center max-w-lg"
            >
              <div className="h-16 w-16 bg-primary/8 rounded-2xl flex items-center justify-center mx-auto mb-6">
                <BookOpen size={28} className="text-primary" />
              </div>
              <h2 className="font-display text-2xl font-semibold text-foreground mb-2">
                {t('workbench.no_project_title')}
              </h2>
              <p className="font-body text-sm text-foreground/50 leading-relaxed mb-8">
                {t('workbench.no_project_desc')}
              </p>
              <button
                type="button"
                onClick={() => navigate('/projects')}
                className="inline-flex items-center gap-2 px-4 py-2.5 bg-primary text-primary-foreground rounded-lg font-label text-sm font-medium shadow-sm hover:bg-primary/90 transition-all"
              >
                {t('workbench.go_projects')}
                <ChevronRight size={14} />
              </button>
            </motion.div>
          ) : (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4 }}
              className="text-center max-w-lg"
            >
              <div className="h-16 w-16 bg-primary/8 rounded-2xl flex items-center justify-center mx-auto mb-6">
                <Sparkles size={28} className="text-primary" />
              </div>
              <h2 className="font-display text-2xl font-semibold text-foreground mb-2">
                {t('workbench.title')}
              </h2>
              <p className="font-body text-sm text-foreground/50 leading-relaxed mb-8">
                {t('workbench.subtitle')}
              </p>

              <div className="flex flex-col gap-2.5 w-full">
                {EXAMPLE_QUERIES.map((q, i) => (
                  <button
                    type="button"
                    key={i}
                    onClick={() => setQuery(q)}
                    className="flex items-center gap-3 px-4 py-3 glass-card rounded-lg text-left group hover:border-primary/30 transition-all"
                  >
                    <MessageSquare size={15} className="text-primary/40 group-hover:text-primary transition-colors flex-shrink-0" />
                    <span className="font-label text-sm text-foreground/70 group-hover:text-foreground transition-colors">
                      {q}
                    </span>
                    <ChevronRight size={14} className="ml-auto text-foreground/20 group-hover:text-primary/40 transition-colors" />
                  </button>
                ))}
              </div>
            </motion.div>
          )}
        </div>
      ) : isRehydrating ? (
        /* Skeleton rehydration state */
        <div className="flex-1 overflow-y-auto px-8 py-6 space-y-6">
          {[1, 2, 3].map(i => (
            <div key={i} className={cn('max-w-2xl', i % 2 === 0 ? 'ml-auto' : '')}>
              <div className="rounded-lg px-4 py-3 bg-surface-high/40 border border-outline-variant/30 animate-pulse">
                <div className="h-4 bg-foreground/5 rounded w-3/4 mb-2" />
                <div className="h-4 bg-foreground/5 rounded w-1/2" />
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Messages list */
        <div className="flex-1 overflow-y-auto custom-scrollbar px-8 py-6 space-y-6">
          <AnimatePresence>
            {messages.map((msg, msgIndex) => (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className={cn('max-w-2xl', msg.role === 'user' ? 'ml-auto' : '')}
              >
                <div className={cn(
                  'rounded-lg px-4 py-3',
                  msg.role === 'user'
                    ? 'bg-primary text-primary-foreground'
                    : msg.error ? 'glass-card border-red-200 bg-red-50/50' : 'glass-card'
                )}>
                  {msg.role === 'assistant' && !msg.error ? (
                    <div className="prose prose-sm max-w-none font-body text-sm leading-relaxed prose-p:my-2 prose-headings:my-3 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-code:bg-surface-high prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-[12px] prose-code:before:content-none prose-code:after:content-none prose-pre:bg-surface-high prose-pre:text-foreground/90 prose-strong:text-foreground prose-strong:font-semibold prose-a:text-primary">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                    </div>
                  ) : (
                    <p className="font-body text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                  )}
                  {msg.sources && (
                    <div className="mt-3 pt-3 border-t border-outline-variant/30 flex flex-wrap gap-2">
                      {msg.sources.map((s, i) => {
                        const canOpen = !!s.material_id;
                        const handleOpen = () => {
                          if (!s.material_id) return;
                          const page = typeof s.page_number === 'number' && s.page_number > 0 ? s.page_number : undefined;
                          const params = page ? new URLSearchParams({ page: String(page) }) : new URLSearchParams();
                          if (s.chunk_id) params.set('chunk', s.chunk_id);
                          const suffix = params.toString() ? `?${params.toString()}` : '';
                          navigate(`/workbench/paper/${encodeURIComponent(s.material_id)}${suffix}`);
                        };
                        return (
                          <button
                            type="button"
                            key={i}
                            onClick={handleOpen}
                            disabled={!canOpen}
                            title={canOpen ? '在阅读工作台中打开此文献' : '无可打开的文献链接'}
                            className={cn(
                              'flex items-center gap-1.5 px-2 py-1 rounded text-[10px] font-label transition-all',
                              canOpen
                                ? 'bg-primary/10 text-primary hover:bg-primary/20 cursor-pointer'
                                : 'bg-surface-high text-foreground/50 cursor-not-allowed',
                            )}
                          >
                            <FileText size={10} /> {s.title} · {s.page}
                          </button>
                        );
                      })}
                    </div>
                  )}
                  {msg.sources && msg.role === 'assistant' && !msg.error && (() => {
                    // Walk back to the most recent user message — that's the
                    // query this answer responds to. Falls back to '当前问题'
                    // when none is found (shouldn't happen in practice).
                    let priorQuery = '';
                    for (let i = msgIndex - 1; i >= 0; i -= 1) {
                      if (messages[i].role === 'user') {
                        priorQuery = messages[i].content;
                        break;
                      }
                    }
                    return (
                      <EvidenceGraphPanel
                        query={priorQuery}
                        sources={msg.sources}
                      />
                    );
                  })()}
                  {msg.usage && !msg.error && (
                    <TokenBadge usage={msg.usage} model={msg.model} />
                  )}
                  {/* Insert to editor button — only on assistant messages */}
                  {msg.role === 'assistant' && !msg.error && (
                    <div className="mt-2 pt-2 border-t border-outline-variant/20 flex justify-end">
                      <button
                        type="button"
                        onClick={() => handleInsertToEditor(msg.content)}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-label text-primary/70 hover:bg-primary/10 hover:text-primary transition-all"
                        title="插入到写作面板"
                      >
                        <PenLine size={11} /> 插入编辑器
                      </button>
                    </div>
                  )}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
          {isLoading && (
            <div className="flex items-center gap-2 text-foreground/40">
              <Loader2 size={16} className="animate-spin" />
              <span className="font-label text-xs">{t('workbench.thinking')}</span>
            </div>
          )}
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-outline-variant bg-surface-lowest px-8 py-4">
        {(() => {
          const sessionTokens = messages
            .filter(m => m.usage)
            .reduce((sum, m) => {
              const { total } = normalizeUsage(m.usage!);
              return sum + total;
            }, 0);
          if (sessionTokens === 0) return null;
          return (
            <div className="max-w-2xl mx-auto mb-2 flex justify-end">
              <span className="text-[10px] font-label text-foreground/30" title="本次会话消耗 tokens">
                本次会话 ∑{fmtTokens(sessionTokens)} tokens
              </span>
            </div>
          );
        })()}
        {/* Ingest Mode Selector */}
        <div className="max-w-2xl mx-auto mb-3 flex items-center gap-2">
          <span className="text-xs font-label text-foreground/60 min-w-fit">入库模式：</span>
          <div className="flex gap-1">
            {(['none', 'query', 'full'] as const).map(mode => (
              <button
                key={mode}
                onClick={() => setIngestMode(mode)}
                disabled={!activeProjectId}
                title={
                  mode === 'none' ? '仅检索已入库 chunk' :
                  mode === 'query' ? '按提问内容筛选候选并入库（推荐）' :
                  '把待入库候选全部入库'
                }
                className={cn(
                  'px-2.5 py-1 rounded-md text-xs font-label transition-all',
                  ingestMode === mode
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-surface-high text-foreground/60 hover:text-foreground/80',
                  !activeProjectId && 'opacity-40 cursor-not-allowed'
                )}
              >
                {mode === 'none' ? '无入库' : mode === 'query' ? '按需入库' : '全量入库'}
              </button>
            ))}
          </div>
        </div>
        <div className="max-w-2xl mx-auto mb-3 flex items-center gap-2">
          <span className="text-xs font-label text-foreground/60 min-w-fit">AI 成本模式：</span>
          <div className="flex gap-1">
            {([
              ['balanced', '平衡'],
              ['aggressive', '省钱'],
              ['quality', '质量优先'],
            ] as const).map(([mode, label]) => (
              <button
                key={mode}
                onClick={() => {
                  setAiCostProfile(mode);
                  const s = loadSettings();
                  s.workspace.aiCostProfile = mode;
                  saveSettings(s);
                }}
                disabled={!activeProjectId}
                title={
                  mode === 'aggressive'
                    ? '减少高成本 AI 步骤，优先省钱'
                    : mode === 'quality'
                    ? '保留更多增强步骤，质量优先'
                    : '默认平衡策略'
                }
                className={cn(
                  'px-2.5 py-1 rounded-md text-xs font-label transition-all',
                  aiCostProfile === mode
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-surface-high text-foreground/60 hover:text-foreground/80',
                  !activeProjectId && 'opacity-40 cursor-not-allowed'
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="max-w-2xl mx-auto mb-3">
          <McpScopePicker
            selected={mcpServerIds}
            onChange={setMcpServerIds}
            hideWhenEmpty
          />
        </div>
        <div className="max-w-2xl mx-auto flex items-center gap-3">
          <div className="flex-1 flex items-center gap-2 bg-surface-high rounded-xl px-4 py-2.5 border border-outline-variant/50 focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10 transition-all">
            <Search size={16} className="text-foreground/30 flex-shrink-0" />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSubmit()}
              placeholder={activeProjectId ? '向文献提问...' : t('workbench.no_project_input')}
              disabled={!activeProjectId}
              className="flex-1 bg-transparent text-sm font-label text-foreground placeholder:text-foreground/30 focus:outline-none"
            />
          </div>
          {messages.length > 0 && (
            <button
              type="button"
              onClick={handleClearHistory}
              disabled={isLoading}
              aria-label="清空对话"
              title="清空对话"
              className="p-2.5 text-foreground/40 rounded-xl hover:text-foreground/70 hover:bg-surface-high disabled:opacity-40 disabled:cursor-not-allowed transition-all active:scale-95"
            >
              <Trash2 size={18} />
            </button>
          )}
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!activeProjectId || !query.trim() || isLoading}
            aria-label="发送问题"
            title="发送问题"
            className="p-2.5 bg-primary text-primary-foreground rounded-xl hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-all active:scale-95 shadow-sm"
          >
            <Send size={18} />
          </button>
        </div>
      </div>
      {/* Close chat panel div */}
      </div>

      {/* Right: Writing panel */}
      <AnimatePresence>
        {editorOpen && (
          <motion.div
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: '50%', opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="flex flex-col h-full border-l border-outline-variant bg-surface-lowest overflow-hidden"
          >
            {/* Editor header */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-outline-variant/60 bg-surface-low">
              <span className="font-label text-xs text-foreground/60">写作面板</span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={async () => {
                    if (exporting) return;
                    setExporting(true);
                    try {
                      const { url, filename } = await exportToDocx({
                        html: editorContent,
                        json: editorJson,
                        title: '文献笔记',
                      });
                      downloadBlob(url, filename);
                    } catch (err) {
                      console.error('Export failed:', err);
                    } finally {
                      setExporting(false);
                    }
                  }}
                  disabled={exporting || !editorContent}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-label text-primary/80 hover:bg-primary/10 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                  title="导出 Word 文档"
                >
                  <Download size={12} /> {exporting ? '导出中...' : '导出 .docx'}
                </button>
                <button
                  type="button"
                  onClick={() => setEditorOpen(false)}
                  className="p-1 rounded text-foreground/40 hover:text-foreground/70 hover:bg-surface-high transition-all"
                  title="关闭写作面板"
                >
                  <X size={14} />
                </button>
              </div>
            </div>
            {/* TipTap editor */}
            <div className="flex-1 overflow-y-auto">
              <Suspense fallback={<TipTapEditorFallback />}>
                <TipTapEditor
                  content={editorContent}
                  onChange={(html, json) => { setEditorContent(html); setEditorJson(json); }}
                  placeholder="在这里撰写论文笔记..."
                />
              </Suspense>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
