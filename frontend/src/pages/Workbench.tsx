import React, { lazy, Suspense, useState, useEffect, useCallback, useRef } from 'react';
import { BookOpen, Search, MessageSquare, Loader2, Send, Sparkles, FileText, ChevronRight, Trash2, History, PenLine, Download, X, Database, ListPlus, FolderInput, GitFork, Pencil, Square } from 'lucide-react';
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
import { formatChatVisibleError } from '@/components/chat/chatDisplay';
import axios from 'axios';
import { SessionDrawer } from '@/components/writing/SessionDrawer';
import type { ResumeSessionResult } from '@/types/runtime';
import { exportToDocx, downloadBlob } from '@/services/exportApi';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { useSmartReadCostTier } from '@/hooks/useSmartReadCostTier';
import {
  retrievalTopKForTier,
  workspaceCostProfileForTier,
} from '@/services/smartReadTiers';

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
const LOCAL_SMOKE_ASSISTANT_HISTORY_PATTERNS = [
  'Smoke answer for evidence graph locator',
] as const;
const LOCAL_SMOKE_QUESTION_HISTORY_PATTERNS = [
  '这篇焊接论文第一段证据在哪里？',
] as const;

const RETRIEVAL_TOP_K_MIN = 3;
const RETRIEVAL_TOP_K_MAX = 20;
const RETRIEVAL_TOP_K_DEFAULT = 6;
const FIRST_QUESTION_SCAN_DEFAULTS = {
  ingestLimit: 8,
  scanMode: 'fast',
  scanBatchSize: 24,
  scanMaxWorkers: 8,
} as const;
const WORKBENCH_ASK_TIMEOUT_MS = 60_000;
const WORKBENCH_ASK_TIMEOUT_SECONDS = WORKBENCH_ASK_TIMEOUT_MS / 1000;

const INGEST_MODE_OPTIONS: Array<{
  id: 'none' | 'query' | 'full';
  label: string;
  shortLabel: string;
  tooltip: string;
  icon: typeof Search;
}> = [
  {
    id: 'none',
    label: '无入库',
    shortLabel: '无',
    tooltip: '只检索已经切块入库的内容。',
    icon: Database,
  },
  {
    id: 'query',
    label: '按需入库',
    shortLabel: '需',
    tooltip: '按当前问题筛选源文件夹里的待索引文献，先切块再检索。',
    icon: ListPlus,
  },
  {
    id: 'full',
    label: '全量入库',
    shortLabel: '全',
    tooltip: '先处理源文件夹里的全部待索引文件，再检索。',
    icon: FolderInput,
  },
];

function isAbortLikeError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === 'AbortError') return true;
  if (!error || typeof error !== 'object') return false;
  const record = error as { name?: unknown; code?: unknown; message?: unknown };
  return (
    record.name === 'AbortError' ||
    record.code === 'ERR_CANCELED' ||
    (typeof record.message === 'string' && record.message.toLowerCase().includes('aborted'))
  );
}

function isWorkbenchMessage(value: unknown): value is Message {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const record = value as { id?: unknown; role?: unknown; content?: unknown };
  return (
    typeof record.id === 'number' &&
    Number.isFinite(record.id) &&
    (record.role === 'user' || record.role === 'assistant') &&
    typeof record.content === 'string'
  );
}

function isLocalSmokeAssistantHistoryMessage(message: Message): boolean {
  return (
    message.role === 'assistant' &&
    LOCAL_SMOKE_ASSISTANT_HISTORY_PATTERNS.some((pattern) => message.content.includes(pattern))
  );
}

function isLocalSmokeQuestionHistoryMessage(message: Message): boolean {
  return (
    message.role === 'user' &&
    LOCAL_SMOKE_QUESTION_HISTORY_PATTERNS.some((pattern) => message.content.includes(pattern))
  );
}

function parseStoredMessages(raw: string): Message[] {
  const parsed: unknown = JSON.parse(raw);
  if (!Array.isArray(parsed)) return [];
  const messages = parsed.filter(isWorkbenchMessage);
  const restored: Message[] = [];
  for (const message of messages) {
    if (isLocalSmokeAssistantHistoryMessage(message)) {
      const previous = restored[restored.length - 1];
      if (previous && isLocalSmokeQuestionHistoryMessage(previous)) {
        restored.pop();
      }
      continue;
    }
    restored.push(message);
  }
  return restored;
}

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
      <span title="输入用量" className="flex items-center gap-0.5 text-[10px] font-label text-foreground/40">
        <span className="text-blue-400/80">↑</span>{fmtTokens(input)}
      </span>
      <span title="输出用量" className="flex items-center gap-0.5 text-[10px] font-label text-foreground/40">
        <span className="text-emerald-400/80">↓</span>{fmtTokens(output)}
      </span>
      <span title="总用量" className="flex items-center gap-0.5 text-[10px] font-label text-foreground/55 font-medium">
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
  const [requestElapsedSec, setRequestElapsedSec] = useState(0);
  const [ingestMode, setIngestMode] = useState<'none' | 'query' | 'full'>(
    loadSettings().workspace.ingestMode ?? 'query',
  );
  const [smartReadTier] = useSmartReadCostTier(
    loadSettings().workspace.smartReadCostTier ?? 'medium',
  );
  const aiCostProfile = workspaceCostProfileForTier(smartReadTier);
  const [sessionDrawerOpen, setSessionDrawerOpen] = useState(false);
  const [isRehydrating, setIsRehydrating] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorContent, setEditorContent] = useState('');
  const [mcpServerIds, setMcpServerIds] = useState<string[]>(
    () => loadSettings().workspace.mcpServerIds ?? [],
  );
  const [editorJson, setEditorJson] = useState<object>({});
  const [exporting, setExporting] = useState(false);
  const requestAbortControllerRef = useRef<AbortController | null>(null);
  const stopRequestedRef = useRef(false);

  useEffect(() => () => {
    requestAbortControllerRef.current?.abort();
  }, []);

  useEffect(() => {
    if (!isLoading) {
      setRequestElapsedSec(0);
      return;
    }
    const startedAt = Date.now();
    setRequestElapsedSec(0);
    const timer = window.setInterval(() => {
      setRequestElapsedSec(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isLoading]);

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

  // Hydration guard — race fix (2026-05-24).
  // The earlier two-useEffect pattern had a window where the write effect
  // ran with stale `messages = []` immediately after `activeProjectId`
  // landed but before the read effect's `setMessages(raw)` re-rendered,
  // wiping the saved history. We now mark `hydratedRef` only AFTER the
  // read settles so the write effect knows to skip until the restore is
  // visible in state. The first real write after that flushes the
  // rehydrated list back to localStorage; subsequent edits flow normally.
  const hydratedRef = useRef(false);
  const storageKey = activeProjectId
    ? `${CHAT_HISTORY_KEY}_${activeProjectId}`
    : null;

  // Load saved messages when project changes
  useEffect(() => {
    hydratedRef.current = false;
    if (!storageKey) {
      setMessages([]);
      hydratedRef.current = true;
      return;
    }
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) {
        setMessages([]);
      } else {
        const restored = parseStoredMessages(raw);
        setMessages(restored);
        if (JSON.stringify(restored) !== raw) {
          if (restored.length > 0) {
            localStorage.setItem(storageKey, JSON.stringify(restored));
          } else {
            localStorage.removeItem(storageKey);
          }
        }
      }
    } catch {
      setMessages([]);
    }
    hydratedRef.current = true;
  }, [storageKey]);

  // Persist messages to localStorage on every change
  useEffect(() => {
    if (!hydratedRef.current) return;
    if (!storageKey) return;
    // 2026-05-24: NEVER write `[]` here. The earlier hydration-race fix
    // moved `hydratedRef.current = true` ahead of React's reconciliation
    // of `setMessages(raw)`, so the write effect still fired with stale
    // `messages = []` immediately after `storageKey` landed, wiping the
    // restored history. handleClearHistory is the only legitimate clear
    // path; it calls localStorage.removeItem directly (see L275). Skipping
    // empty-array writes here makes the write effect idempotent against
    // the hydration race regardless of effect ordering.
    if (messages.length === 0) return;
    try {
      const toSave = messages.slice(-50);
      localStorage.setItem(storageKey, JSON.stringify(toSave));
    } catch { /* storage quota */ }
  }, [messages, storageKey]);

  const retrieveDocContext = useCallback(async (currentQuery: string, signal?: AbortSignal) => {
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
            Math.max(
              RETRIEVAL_TOP_K_MIN,
              retrievalTopKForTier(smartReadTier)
                || loadSettings().workspace.retrievalTopK
                || RETRIEVAL_TOP_K_DEFAULT,
            ),
          ),
          ingest_mode: ingestMode,
          ai_cost_profile: aiCostProfile,
          ingest_limit: FIRST_QUESTION_SCAN_DEFAULTS.ingestLimit,
          scan_mode: FIRST_QUESTION_SCAN_DEFAULTS.scanMode,
          scan_batch_size: FIRST_QUESTION_SCAN_DEFAULTS.scanBatchSize,
          scan_max_workers: FIRST_QUESTION_SCAN_DEFAULTS.scanMaxWorkers,
        },
        timeout: WORKBENCH_ASK_TIMEOUT_MS,
        signal,
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
            excerpt: chunk.content.slice(0, 600),
          })),
        };
      }

      const { data: docs } = await axios.get(`${getApiBaseUrl()}/resources/documents`, {
        params: { project_id: activeProjectId },
        timeout: 10000,
        signal,
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
    } catch (error: unknown) {
      if (isAbortLikeError(error)) {
        throw error;
      }
      return { context: [] as string[], sources: [] as MessageSource[] };
    }
  }, [activeProjectId, ingestMode, aiCostProfile, smartReadTier]);

  const handleClearHistory = () => {
    if (activeProjectId) localStorage.removeItem(`${CHAT_HISTORY_KEY}_${activeProjectId}`);
    setMessages([]);
  };

  const handleInsertToEditor = useCallback((text: string) => {
    setEditorContent(prev => prev ? prev + '<p>' + text.replace(/\n/g, '<br>') + '</p>' : '<p>' + text.replace(/\n/g, '<br>') + '</p>');
    if (!editorOpen) setEditorOpen(true);
  }, [editorOpen]);

  const handleStopGeneration = useCallback(() => {
    stopRequestedRef.current = true;
    requestAbortControllerRef.current?.abort();
  }, []);

  const handleEditMessage = useCallback((message: Message) => {
    if (isLoading || message.role !== 'user') return;
    const index = messages.findIndex((item) => item.id === message.id);
    if (index < 0) return;
    setMessages(messages.slice(0, index));
    setQuery(message.content);
  }, [isLoading, messages]);

  const handleForkMessage = useCallback((message: Message) => {
    if (isLoading) return;
    const index = messages.findIndex((item) => item.id === message.id);
    if (index < 0) return;
    setMessages(messages.slice(0, index + 1));
    toast('已从所选消息创建本地分叉', 'success');
  }, [isLoading, messages, toast]);

  const handleSubmit = async () => {
    if (!query.trim() || isLoading) return;
    const abortController = new AbortController();
    requestAbortControllerRef.current = abortController;
    stopRequestedRef.current = false;
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

      const retrieval = await retrieveDocContext(currentQuery, abortController.signal);

      const data = await askChatWithConfig({
        query: currentQuery,
        context: retrieval.context,
        history: historySnapshot,
        llm: llmConfig,
        aiCostProfile,
        timeoutMs: WORKBENCH_ASK_TIMEOUT_MS,
        signal: abortController.signal,
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
      const stopped = stopRequestedRef.current || isAbortLikeError(err);
      const errMsg = stopped ? '已停止生成。' : formatChatVisibleError(err);
      const assistantMsg: Message = {
        id: Date.now() + 1,
        role: 'assistant',
        content: errMsg,
        error: !stopped,
      };
      setMessages(prev => [...prev, assistantMsg]);
    } finally {
      if (requestAbortControllerRef.current === abortController) {
        requestAbortControllerRef.current = null;
      }
      stopRequestedRef.current = false;
      setIsLoading(false);
    }
  };

  return (
    <div className="relative flex flex-row h-full">
      {/* Left: Chat panel */}
      <div className={cn('relative flex flex-col h-full transition-all', editorOpen ? 'w-1/2 min-w-0' : 'w-full')}>
      <div className="flex min-h-12 shrink-0 items-center justify-end gap-2 border-b border-outline-variant/60 bg-surface-low px-4 py-2">
        <button
          type="button"
          onClick={() => setEditorOpen(v => !v)}
          aria-label={editorOpen ? '关闭写作面板' : '打开写作面板'}
          title={editorOpen ? '关闭写作面板' : '打开写作面板'}
          className={cn(
            'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors',
            editorOpen
              ? 'border-primary/30 bg-primary/15 text-primary hover:bg-primary/25'
              : 'border-outline-variant/60 bg-surface-lowest text-foreground/70 hover:border-primary/35 hover:text-foreground'
          )}
        >
          <PenLine size={13} />
          <span>写作</span>
        </button>
        <button
          type="button"
          onClick={() => setSessionDrawerOpen(true)}
          aria-label="打开会话历史"
          title="会话历史（恢复 / 分叉 / 回退）"
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-2.5 text-xs font-medium text-foreground/70 transition-colors hover:border-primary/35 hover:text-foreground"
        >
          <History size={13} />
          <span>会话</span>
        </button>
      </div>
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
                    : msg.error
                      ? 'border border-red-200 bg-red-50/80 text-red-800 dark:border-red-700/50 dark:bg-red-500/15 dark:text-red-200'
                      : 'border border-outline-variant/60 bg-surface-low text-foreground'
                )}>
                  {msg.role === 'assistant' && !msg.error ? (
                    <div className="prose prose-sm max-w-none break-words font-body text-sm leading-relaxed text-foreground [overflow-wrap:anywhere] prose-headings:my-3 prose-headings:text-foreground prose-p:my-2 prose-p:text-foreground prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-li:text-foreground prose-a:break-all prose-a:text-primary prose-strong:font-semibold prose-strong:text-foreground prose-em:text-foreground/90 prose-code:break-words prose-code:rounded prose-code:bg-foreground/10 prose-code:px-1 prose-code:py-0.5 prose-code:text-[12px] prose-code:text-foreground prose-code:before:content-none prose-code:after:content-none prose-pre:max-w-full prose-pre:overflow-x-auto prose-pre:bg-foreground/10 prose-pre:text-foreground prose-table:block prose-table:max-w-full prose-table:overflow-x-auto">
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
                        projectId={activeProjectId}
                      />
                    );
                  })()}
                  {msg.usage && !msg.error && (
                    <TokenBadge usage={msg.usage} model={msg.model} />
                  )}
                  {/* Insert to editor button — only on assistant messages */}
                  {msg.role === 'assistant' && !msg.error && (
                    <div className="mt-2 pt-2 border-t border-outline-variant/20 flex flex-wrap justify-end gap-1.5">
                      <button
                        type="button"
                        onClick={() => handleForkMessage(msg)}
                        disabled={isLoading}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-label text-foreground/50 hover:bg-surface-high hover:text-foreground disabled:opacity-40 transition-all"
                        title="从这里分叉"
                        aria-label="从这里分叉"
                      >
                        <GitFork size={11} /> 分叉
                      </button>
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
                  {msg.role === 'user' && (
                    <div className="mt-2 flex justify-end gap-1.5 border-t border-primary-foreground/20 pt-2">
                      <button
                        type="button"
                        onClick={() => handleEditMessage(msg)}
                        disabled={isLoading}
                        className="inline-flex items-center gap-1 rounded px-2 py-1 text-[10px] font-label text-primary-foreground/75 transition-all hover:bg-primary-foreground/15 hover:text-primary-foreground disabled:opacity-40"
                        title="修改这条消息并从这里继续"
                        aria-label="修改这条消息并从这里继续"
                      >
                        <Pencil size={11} /> 修改
                      </button>
                      <button
                        type="button"
                        onClick={() => handleForkMessage(msg)}
                        disabled={isLoading}
                        className="inline-flex items-center gap-1 rounded px-2 py-1 text-[10px] font-label text-primary-foreground/75 transition-all hover:bg-primary-foreground/15 hover:text-primary-foreground disabled:opacity-40"
                        title="从这里分叉"
                        aria-label="从这里分叉"
                      >
                        <GitFork size={11} /> 分叉
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
              <span className="font-label text-xs">
                {t('workbench.thinking')} · {requestElapsedSec}s / {WORKBENCH_ASK_TIMEOUT_SECONDS}s
              </span>
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
              <span className="text-[10px] font-label text-foreground/30" title="本次会话模型用量">
                本次会话用量 ∑{fmtTokens(sessionTokens)}
              </span>
            </div>
          );
        })()}
        <div className="max-w-2xl mx-auto mb-3">
          <McpScopePicker
            selected={mcpServerIds}
            onChange={(next) => {
              setMcpServerIds(next);
              const s = loadSettings();
              s.workspace.mcpServerIds = next;
              saveSettings(s);
            }}
            hideWhenEmpty
          />
        </div>
        <div className="max-w-2xl mx-auto flex items-end gap-3">
          <div className="flex flex-col gap-1.5" aria-label="入库模式">
            {INGEST_MODE_OPTIONS.map((option) => {
              const Icon = option.icon;
              const active = ingestMode === option.id;
              return (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => {
                    setIngestMode(option.id);
                    const s = loadSettings();
                    s.workspace.ingestMode = option.id;
                    saveSettings(s);
                  }}
                  disabled={!activeProjectId || isLoading}
                  title={`${option.label}：${option.tooltip}`}
                  aria-label={`入库模式：${option.label}`}
                  className={cn(
                    'flex h-8 w-8 items-center justify-center rounded-lg border text-[10px] font-semibold transition-all',
                    active
                      ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                      : 'border-outline-variant/60 bg-surface-high text-foreground/55 hover:border-primary/40 hover:text-foreground',
                    (!activeProjectId || isLoading) && 'cursor-not-allowed opacity-45',
                  )}
                >
                  <Icon size={14} />
                  <span className="sr-only">{option.shortLabel}</span>
                </button>
              );
            })}
          </div>
          <div className="flex-1 flex items-start gap-2 bg-surface-high rounded-xl px-4 py-2.5 border border-outline-variant/50 focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10 transition-all">
            <Search size={16} className="mt-1 text-foreground/30 flex-shrink-0" />
            <textarea
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  void handleSubmit();
                }
              }}
              rows={2}
              placeholder={activeProjectId ? '向文献提问...' : t('workbench.no_project_input')}
              disabled={!activeProjectId}
              className="min-h-[44px] max-h-48 flex-1 resize-y bg-transparent text-sm font-label leading-6 text-foreground placeholder:text-foreground/30 focus:outline-none disabled:cursor-not-allowed"
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
          {isLoading ? (
            <button
              type="button"
              onClick={handleStopGeneration}
              aria-label="停止生成"
              title={`停止生成 · ${requestElapsedSec}s / ${WORKBENCH_ASK_TIMEOUT_SECONDS}s`}
              className="p-2.5 bg-red-600 text-white rounded-xl hover:bg-red-700 transition-all active:scale-95 shadow-sm"
            >
              <Square size={18} />
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!activeProjectId || !query.trim()}
              aria-label="发送问题"
              title="发送问题"
              className="p-2.5 bg-primary text-primary-foreground rounded-xl hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-all active:scale-95 shadow-sm"
            >
              <Send size={18} />
            </button>
          )}
        </div>
        {isLoading ? (
          <div className="mx-auto mt-2 max-w-2xl text-right text-[10px] text-foreground/40">
            请求已等待 {requestElapsedSec}s，当前超时上限 {WORKBENCH_ASK_TIMEOUT_SECONDS}s。
          </div>
        ) : null}
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
              <ErrorBoundary fallbackTitle="编辑器暂时无法显示">
                <Suspense fallback={<TipTapEditorFallback />}>
                  <TipTapEditor
                    content={editorContent}
                    onChange={(html, json) => { setEditorContent(html); setEditorJson(json); }}
                    placeholder="在这里撰写论文笔记..."
                  />
                </Suspense>
              </ErrorBoundary>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
