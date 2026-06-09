import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Lightbulb, Search, RefreshCw, ChevronRight, Tag, BookOpen, Loader2, AlertCircle, Sparkles, Square, CheckCircle2, Download } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useWriting } from '@/contexts/WritingContext';
import { getInspirationService } from '@/services/inspirationService';
import { downloadBlob } from '@/services/exportApi';
import { SparkEvidencePills } from '@/components/inspiration/SparkEvidencePills';
import { InspirationGraphSection } from '@/components/inspiration/InspirationGraphSection';
import { InspirationAnalysisChain } from '@/components/inspiration/InspirationAnalysisChain';
import {
  formatInspirationVisibleError,
  sanitizeInspirationVisibleText,
} from '@/components/inspiration/inspirationDisplay';
import { ProjectBiasSurfaceToggle } from '@/components/knowledge/ProjectBiasSurfaceToggle';
import { useProjectReasoningBiasState } from '@/hooks/useProjectReasoningBiasState';
import type { InspirationSpark, ContinuationContext } from '@/types/writing';

type SparkType = InspirationSpark['spark_type'];

const SPARK_TYPE_STYLE: Record<string, { label: string; bg: string; text: string }> = {
  causal_extension: { label: '因果延伸', bg: 'bg-sky-50 dark:bg-sky-500/15', text: 'text-sky-700 dark:text-sky-300' },
  conflict: { label: '矛盾碰撞', bg: 'bg-red-50 dark:bg-red-500/15', text: 'text-red-700 dark:text-red-300' },
  analogy: { label: '类比迁移', bg: 'bg-violet-50 dark:bg-violet-500/15', text: 'text-violet-700 dark:text-violet-300' },
  gap: { label: '研究空白', bg: 'bg-amber-50 dark:bg-amber-500/15', text: 'text-amber-700 dark:text-amber-300' },
  synthesis: { label: '多源综合', bg: 'bg-emerald-50 dark:bg-emerald-500/15', text: 'text-emerald-700 dark:text-emerald-300' },
  memory_association: { label: '记忆联想', bg: 'bg-primary/8', text: 'text-primary' },
  contradiction: { label: '矛盾碰撞', bg: 'bg-red-50 dark:bg-red-500/15', text: 'text-red-700 dark:text-red-300' },
  extension: { label: '因果延伸', bg: 'bg-sky-50 dark:bg-sky-500/15', text: 'text-sky-700 dark:text-sky-300' },
  application: { label: '应用场景', bg: 'bg-emerald-50 dark:bg-emerald-500/15', text: 'text-emerald-700 dark:text-emerald-300' },
  default: { label: '灵感', bg: 'bg-surface-high', text: 'text-foreground/70' },
};

function sparkStyle(type: SparkType) {
  return SPARK_TYPE_STYLE[String(type)] ?? SPARK_TYPE_STYLE.default;
}

/* ── Single Spark Card ── */
function SparkCard({
  spark,
  onExpand,
  projectId,
}: {
  spark: InspirationSpark;
  onExpand: (spark: InspirationSpark) => void;
  projectId?: string | null;
}) {
  const style = sparkStyle(spark.spark_type);
  const confidence = Math.round(spark.confidence * 100);
  const visibleContent = sanitizeInspirationVisibleText(spark.content, '这条灵感包含内部诊断，已隐藏。');
  const visibleSources = spark.source_papers.map((source, index) => (
    sanitizeInspirationVisibleText(source, `来源 ${index + 1}`)
  ));

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="group bg-surface-low border border-outline-variant rounded-xl p-4 hover:border-primary/30 hover:shadow-sm transition-all cursor-pointer"
      onClick={() => onExpand(spark)}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex-shrink-0 p-1.5 rounded-lg bg-primary/8">
          <Lightbulb size={16} className="text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-body text-sm text-foreground leading-relaxed line-clamp-3">
            {visibleContent}
          </p>
          <div className="mt-2.5 flex items-center flex-wrap gap-2">
            <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium', style.bg, style.text)}>
              <Tag size={10} />
              {style.label}
            </span>
            {spark.actionable && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
                <Sparkles size={10} />
                可行
              </span>
            )}
            <span className="ml-auto text-xs text-foreground/40 font-mono">{confidence}%</span>
          </div>
          {spark.source_papers.length > 0 && (
            <div className="mt-2 flex items-center gap-1 text-xs text-foreground/40">
              <BookOpen size={11} />
              <span className="truncate">{visibleSources.join('、')}</span>
            </div>
          )}
          <SparkEvidencePills
            refs={spark.evidence_refs}
            projectId={projectId}
            className="mt-2"
          />
        </div>
        <ChevronRight size={14} className="flex-shrink-0 text-foreground/25 mt-1 group-hover:text-primary transition-colors" />
      </div>
    </motion.div>
  );
}

/* ── Context Drawer ── */
function ContextDrawer({
  spark,
  context,
  loading,
  error,
  onRetry,
  onClose,
}: {
  spark: InspirationSpark;
  context: ContinuationContext | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onClose: () => void;
}) {
  const style = sparkStyle(spark.spark_type);
  const visibleContent = sanitizeInspirationVisibleText(spark.content, '这条灵感包含内部诊断，已隐藏。');

  return (
    <motion.div
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 24 }}
      transition={{ duration: 0.2 }}
      className="flex flex-col h-full bg-surface-lowest border-l border-outline-variant overflow-y-auto"
    >
      {/* Header */}
      <div className="sticky top-0 bg-surface-lowest/90 backdrop-blur-sm p-4 border-b border-outline-variant flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Lightbulb size={16} className="text-primary flex-shrink-0" />
          <span className={cn('inline-block px-2 py-0.5 rounded-full text-xs font-medium', style.bg, style.text)}>
            {style.label}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="p-1 rounded hover:bg-surface-high text-foreground/40 hover:text-foreground transition-colors"
          aria-label="关闭"
        >
          <ChevronRight size={16} />
        </button>
      </div>

      <div className="p-4 space-y-5">
        {/* Spark content */}
        <p className="font-body text-sm text-foreground leading-relaxed">{visibleContent}</p>
        <InspirationAnalysisChain spark={spark} />

        {loading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={20} className="animate-spin text-primary" />
          </div>
        )}

        {!loading && error && (
          <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs leading-relaxed text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
            <div className="flex items-start gap-2">
              <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
              <div className="min-w-0 flex-1">
                <p>{error}</p>
                <button
                  type="button"
                  onClick={onRetry}
                  className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-red-200 bg-white px-2.5 py-1.5 text-[11px] font-medium text-red-700 transition-colors hover:bg-red-50 dark:border-red-700/40 dark:bg-red-500/10 dark:hover:bg-red-500/20"
                >
                  <RefreshCw size={12} />
                  重新加载上下文
                </button>
              </div>
            </div>
          </div>
        )}

        {!loading && !error && context && (
          <>
            {/* Evidence */}
            {context.evidence_texts.length > 0 && (
              <section>
                <h3 className="font-label text-xs font-semibold text-foreground/50 uppercase tracking-wide mb-2">
                  支撑证据
                </h3>
                <ul className="space-y-2">
                  {context.evidence_texts.map((t, i) => (
                    <li key={i} className="text-xs text-foreground/70 font-body leading-relaxed p-2.5 bg-surface-low rounded-lg border border-outline-variant/50">
                      {sanitizeInspirationVisibleText(t, '证据内容包含内部诊断，已隐藏。')}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Causal chain */}
            {context.causal_chain_summary && (
              <section>
                <h3 className="font-label text-xs font-semibold text-foreground/50 uppercase tracking-wide mb-2">
                  因果链摘要
                </h3>
                <p className="text-xs text-foreground/70 font-body leading-relaxed p-2.5 bg-surface-low rounded-lg border border-outline-variant/50">
                  {sanitizeInspirationVisibleText(context.causal_chain_summary, '摘要内容包含内部诊断，已隐藏。')}
                </p>
              </section>
            )}

            {/* Suggested angles */}
            {context.suggested_angles.length > 0 && (
              <section>
                <h3 className="font-label text-xs font-semibold text-foreground/50 uppercase tracking-wide mb-2">
                  写作切入角度
                </h3>
                <ul className="space-y-1.5">
                  {context.suggested_angles.map((angle, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-foreground/70 font-body leading-relaxed">
                      <span className="flex-shrink-0 mt-0.5 w-4 h-4 rounded-full bg-primary/10 text-primary text-[10px] flex items-center justify-center font-mono">
                        {i + 1}
                      </span>
                      {sanitizeInspirationVisibleText(angle, '切入角度包含内部诊断，已隐藏。')}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}

        {!loading && !error && !context && (
          <p className="rounded-lg border border-outline-variant/50 bg-surface-low p-3 text-xs leading-relaxed text-foreground/50">
            暂无可用续写上下文，可直接复制上方启发内容到手稿。
          </p>
        )}
      </div>
    </motion.div>
  );
}

/* ── Main Page ── */
const INSPIRATION_STORAGE_KEY = 'inspiration_state';

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

type InspirationPersistedState = {
  query: string;
  sparks: InspirationSpark[];
  selectedSpark: InspirationSpark | null;
  context: ContinuationContext | null;
};

type ActionStatus = {
  kind: 'idle' | 'loading' | 'success' | 'error';
  message: string;
};

const IDLE_ACTION_STATUS: ActionStatus = { kind: 'idle', message: '' };

export function Inspiration() {
  const { activeProjectId } = useWriting();
  const [query, setQuery] = useState('');
  const [sparks, setSparks] = useState<InspirationSpark[]>([]);
  const [loading, setLoading] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [exportingEvidenceRefs, setExportingEvidenceRefs] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionStatus, setActionStatus] = useState<ActionStatus>(IDLE_ACTION_STATUS);
  const [selectedSpark, setSelectedSpark] = useState<InspirationSpark | null>(null);
  const [context, setContext] = useState<ContinuationContext | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState<string | null>(null);
  const projectReasoningBias = useProjectReasoningBiasState(activeProjectId);
  const defaultProjectBiasEnabled = projectReasoningBias.isEnabledForSurface('analysis_chain');
  const [projectBiasEnabled, setProjectBiasEnabled] = useState(defaultProjectBiasEnabled);
  const requestAbortControllerRef = useRef<AbortController | null>(null);
  const contextRequestIdRef = useRef(0);
  const stopRequestedRef = useRef(false);

  useEffect(() => () => {
    requestAbortControllerRef.current?.abort();
  }, []);

  const storageKey = `${INSPIRATION_STORAGE_KEY}_${activeProjectId || 'default'}`;

  useEffect(() => {
    setProjectBiasEnabled(defaultProjectBiasEnabled);
  }, [defaultProjectBiasEnabled, activeProjectId]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) {
        setQuery('');
        setSparks([]);
        setSelectedSpark(null);
        setContext(null);
        setContextError(null);
        return;
      }
      const parsed = JSON.parse(raw) as InspirationPersistedState;
      setQuery(parsed.query ?? '');
      setSparks(Array.isArray(parsed.sparks) ? parsed.sparks : []);
      setSelectedSpark(parsed.selectedSpark ?? null);
      setContext(parsed.context ?? null);
      setContextError(null);
    } catch {
      setQuery('');
      setSparks([]);
      setSelectedSpark(null);
      setContext(null);
      setContextError(null);
    }
  }, [storageKey]);

  useEffect(() => {
    try {
      if (!query && sparks.length === 0 && !selectedSpark) {
        localStorage.removeItem(storageKey);
        return;
      }
      const toSave: InspirationPersistedState = { query, sparks, selectedSpark, context };
      localStorage.setItem(storageKey, JSON.stringify(toSave));
    } catch { /* storage quota */ }
  }, [query, sparks, selectedSpark, context, storageKey]);

  const handleSearch = useCallback(async () => {
    const q = query.trim();
    if (!q || loading) return;
    const abortController = new AbortController();
    requestAbortControllerRef.current = abortController;
    stopRequestedRef.current = false;
    setLoading(true);
    setError(null);
    setActionStatus({ kind: 'loading', message: '正在生成灵感…' });
    setSparks([]);
    setSelectedSpark(null);
    setContext(null);
    setContextError(null);
    contextRequestIdRef.current += 1;
    try {
      const service = getInspirationService();
      const results = await service.generateSparks(q, 20, activeProjectId ?? undefined, {
        projectReasoningBiasEnabled: defaultProjectBiasEnabled ? projectBiasEnabled : undefined,
        signal: abortController.signal,
      });
      setSparks(results);
      // Mirror result into storage immediately so that unmounting the page
      // mid-request (user switches sidebar) does not drop the response.
      try {
        const persisted: InspirationPersistedState = {
          query: q,
          sparks: results,
          selectedSpark: null,
          context: null,
        };
        localStorage.setItem(storageKey, JSON.stringify(persisted));
      } catch { /* storage quota */ }
      if (results.length === 0) {
        setError('未生成可用灵感，请换一个更具体的研究主题。');
        setActionStatus(IDLE_ACTION_STATUS);
      } else {
        setActionStatus({ kind: 'success', message: `已生成 ${results.length} 条灵感。` });
      }
    } catch (err: unknown) {
      if (stopRequestedRef.current || isAbortLikeError(err)) {
        setError('已停止生成。');
      } else {
        setError(formatInspirationVisibleError(err));
      }
      setActionStatus(IDLE_ACTION_STATUS);
    } finally {
      if (requestAbortControllerRef.current === abortController) {
        requestAbortControllerRef.current = null;
      }
      stopRequestedRef.current = false;
      setLoading(false);
    }
  }, [query, loading, activeProjectId, storageKey, defaultProjectBiasEnabled, projectBiasEnabled]);

  const handleStopGeneration = useCallback(() => {
    stopRequestedRef.current = true;
    requestAbortControllerRef.current?.abort();
    setActionStatus({ kind: 'loading', message: '正在停止生成…' });
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) handleSearch();
  };

  const handleExpand = useCallback(async (spark: InspirationSpark) => {
    const requestId = contextRequestIdRef.current + 1;
    contextRequestIdRef.current = requestId;
    setSelectedSpark(spark);
    setContext(null);
    setContextError(null);
    setContextLoading(true);
    try {
      const service = getInspirationService();
      const ctx = await service.getSparkContext(spark.id);
      if (contextRequestIdRef.current !== requestId) return;
      setContext(ctx);
    } catch (err: unknown) {
      if (contextRequestIdRef.current !== requestId) return;
      const formatted = formatInspirationVisibleError(err);
      setContextError(
        formatted
          ? `续写上下文加载失败：${formatted}`
          : '续写上下文加载失败，请稍后重试。',
      );
    } finally {
      if (contextRequestIdRef.current === requestId) {
        setContextLoading(false);
      }
    }
  }, []);

  const handleReload = useCallback(async () => {
    if (loading || reloading) return;
    setReloading(true);
    setActionStatus({ kind: 'loading', message: '正在重新加载灵感引擎…' });
    try {
      await getInspirationService().reloadEngine();
      setActionStatus({
        kind: 'success',
        message: '灵感引擎已重新加载。再次生成会使用最新文献索引。',
      });
    } catch (err: unknown) {
      setActionStatus({
        kind: 'error',
        message: formatInspirationVisibleError(err),
      });
    } finally {
      setReloading(false);
    }
  }, [loading, reloading]);

  const handleExportEvidenceRefs = useCallback(async () => {
    if (exportingEvidenceRefs) return;
    setExportingEvidenceRefs(true);
    setActionStatus({ kind: 'loading', message: '正在导出证据引用…' });
    try {
      const { blob, filename } = await getInspirationService().exportEvidenceRefs({ format: 'json' });
      const objectUrl = URL.createObjectURL(blob);
      downloadBlob(objectUrl, filename);
      setActionStatus({ kind: 'success', message: '证据引用已导出。' });
    } catch (err: unknown) {
      setActionStatus({
        kind: 'error',
        message: formatInspirationVisibleError(err),
      });
    } finally {
      setExportingEvidenceRefs(false);
    }
  }, [exportingEvidenceRefs]);

  const handleCloseContext = useCallback(() => {
    contextRequestIdRef.current += 1;
    setSelectedSpark(null);
    setContext(null);
    setContextError(null);
    setContextLoading(false);
  }, []);

  const handleRetryContext = useCallback(() => {
    if (!selectedSpark) return;
    void handleExpand(selectedSpark);
  }, [handleExpand, selectedSpark]);

  return (
    <div className="flex h-full bg-background">
      {/* Left panel */}
      <div className={cn('flex flex-col min-w-0 transition-all duration-200', selectedSpark ? 'w-[55%]' : 'w-full')}>
        {/* Search header */}
        <div className="border-b border-outline-variant/60 bg-surface-low px-5 py-4">
          <div className="mb-3 flex items-center gap-2">
            <Sparkles size={16} className="text-primary" aria-hidden />
            <h1 className="font-display text-lg font-semibold text-foreground">灵感思维链</h1>
            <button
              type="button"
              onClick={handleReload}
              disabled={loading || reloading}
              title="重新加载灵感引擎"
              aria-label="重新加载灵感引擎"
              className="ml-auto rounded p-1.5 text-foreground/45 transition-colors hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
            >
              {reloading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
            </button>
          </div>
          <p className="mb-3 font-body text-xs leading-relaxed text-foreground/55">
            输入研究主题，从已索引文献中挖掘研究空白、矛盾与延伸方向
          </p>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <ProjectBiasSurfaceToggle
              enabled={projectBiasEnabled && defaultProjectBiasEnabled}
              label={projectBiasEnabled && defaultProjectBiasEnabled ? '思维链偏置已启用' : '思维链偏置已关闭'}
              disabled={!defaultProjectBiasEnabled || projectReasoningBias.loading || loading}
              onChange={setProjectBiasEnabled}
            />
            <span className="text-[10px] text-foreground/45">
              {defaultProjectBiasEnabled ? '仅影响本次灵感生成' : '当前项目未启用思维链偏置'}
            </span>
            <button
              type="button"
              onClick={handleExportEvidenceRefs}
              disabled={exportingEvidenceRefs}
              className="ml-auto inline-flex min-h-8 items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-2.5 text-[11px] font-medium text-foreground/65 transition-colors hover:border-primary/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              {exportingEvidenceRefs ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
              导出证据引用
            </button>
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="例：钛合金热处理工艺优化…"
              className="flex-1 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-2 text-sm font-body text-foreground placeholder:text-foreground/35 transition-colors focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
            {loading ? (
              <button
                type="button"
                onClick={handleStopGeneration}
                className="inline-flex items-center gap-1.5 rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-red-700"
              >
                <Square size={14} />
                停止
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSearch}
                disabled={!query.trim()}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                  !query.trim()
                    ? 'cursor-not-allowed bg-primary/20 text-primary/40'
                    : 'bg-primary text-primary-foreground hover:bg-primary/90',
                )}
              >
                <Search size={14} />
                生成灵感
              </button>
            )}
          </div>
          {actionStatus.kind !== 'idle' && (
            <div
              role={actionStatus.kind === 'error' ? 'alert' : 'status'}
              className={cn(
                'mt-3 flex items-center gap-2 rounded-md border px-3 py-2 text-xs',
                actionStatus.kind === 'error'
                  ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300'
                  : actionStatus.kind === 'success'
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300'
                    : 'border-outline-variant/60 bg-surface-lowest text-foreground/55',
              )}
            >
              {actionStatus.kind === 'loading' ? (
                <Loader2 size={14} className="animate-spin" />
              ) : actionStatus.kind === 'success' ? (
                <CheckCircle2 size={14} />
              ) : (
                <AlertCircle size={14} />
              )}
              <span className="font-body">{actionStatus.message}</span>
            </div>
          )}
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto p-4">
          {error && (
            <div role="alert" className="flex items-center gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm mb-4 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
              <AlertCircle size={15} />
              <span className="font-body">{error}</span>
            </div>
          )}

          {!loading && sparks.length === 0 && !error && (
            <div className="flex flex-col items-center justify-center h-full py-16 gap-3 text-center">
              <div className="p-4 rounded-full bg-primary/8">
                <Lightbulb size={24} className="text-primary/50" />
              </div>
              <p className="font-label text-sm text-foreground/40">输入研究主题，按下回车生成灵感</p>
            </div>
          )}

          {loading && (
            <div className="flex flex-col items-center justify-center h-full py-16 gap-3">
              <Loader2 size={24} className="animate-spin text-primary" />
              <p className="font-label text-xs text-foreground/40">正在生成灵感…</p>
            </div>
          )}

          <AnimatePresence>
            {!loading && sparks.length > 0 && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="space-y-3"
              >
                <p className="font-label text-xs text-foreground/40 mb-3">共 {sparks.length} 条灵感</p>
                {sparks.map(spark => (
                  <SparkCard
                    key={spark.id}
                    spark={spark}
                    onExpand={handleExpand}
                    projectId={activeProjectId}
                  />
                ))}
                {/* Track B E5 (D-EVR-6): collapsible graph view of all
                    sparks' evidence_refs. Renders nothing when no spark
                    carries chunk metadata (LLM-only result). */}
                <InspirationGraphSection query={query} sparks={sparks} projectId={activeProjectId} />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Right panel — context drawer */}
      <AnimatePresence>
        {selectedSpark && (
          <div className="w-[45%] flex-shrink-0">
            <ContextDrawer
              spark={selectedSpark}
              context={context}
              loading={contextLoading}
              error={contextError}
              onRetry={handleRetryContext}
              onClose={handleCloseContext}
            />
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
