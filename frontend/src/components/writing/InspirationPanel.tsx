import React, { useState, useCallback, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Link } from 'react-router-dom';
import {
  Sparkles,
  GitBranch,
  AlertTriangle,
  Search,
  ChevronRight,
  Lightbulb,
  PenLine,
  Loader2,
  RefreshCw,
  Square,
  Target,
  Download,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { getInspirationService } from '@/services/inspirationService';
import { downloadBlob } from '@/services/exportApi';
import { getSampling } from '@/services/samplingApi';
import { useWriting } from '@/contexts/WritingContext';
import { ProjectBiasSurfaceToggle } from '@/components/knowledge/ProjectBiasSurfaceToggle';
import { useProjectReasoningBiasState } from '@/hooks/useProjectReasoningBiasState';
import { buildSettingsSectionPath } from '@/pages/settingsSections';
import type { InspirationSpark, ContinuationContext } from '@/types/writing';
import type { InspirationEvidenceRef } from '@/services/inspirationService';
import { summarizeInspirationSampling } from './inspirationSamplingStatus';
import { SparkEvidencePills } from '@/components/inspiration/SparkEvidencePills';
import { InspirationAnalysisChain } from '@/components/inspiration/InspirationAnalysisChain';
import { sanitizeInspirationVisibleText } from '@/components/inspiration/inspirationDisplay';

const inspirationService = getInspirationService();

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

const sparkTypeConfig: Record<string, { icon: React.ElementType; label: string; color: string }> = {
  causal_extension: { icon: GitBranch, label: '因果延伸', color: 'text-blue-600 bg-blue-50 border-blue-200 dark:text-blue-300 dark:bg-blue-500/15 dark:border-blue-700/40' },
  conflict:         { icon: AlertTriangle, label: '矛盾碰撞', color: 'text-amber-600 bg-amber-50 border-amber-200 dark:text-amber-300 dark:bg-amber-500/15 dark:border-amber-700/40' },
  analogy:          { icon: RefreshCw, label: '类比迁移', color: 'text-violet-600 bg-violet-50 border-violet-200 dark:text-violet-300 dark:bg-violet-500/15 dark:border-violet-700/40' },
  gap:              { icon: Target, label: '空白发现', color: 'text-rose-600 bg-rose-50 border-rose-200 dark:text-rose-300 dark:bg-rose-500/15 dark:border-rose-700/40' },
  synthesis:        { icon: Sparkles, label: '多源综合', color: 'text-emerald-600 bg-emerald-50 border-emerald-200 dark:text-emerald-300 dark:bg-emerald-500/15 dark:border-emerald-700/40' },
  memory_association: { icon: Lightbulb, label: '记忆联想', color: 'text-primary bg-primary/5 border-primary/20' },
};

interface InspirationPanelProps {
  onContinueWrite: (context: ContinuationContext) => void;
}

function parseSourceLabelsInput(raw: string): string[] {
  const labels = raw
    .split(/[,，\n]+/u)
    .map((label) => label.trim())
    .filter((label) => label.length > 0);
  return Array.from(new Set(labels)).slice(0, 12);
}

function evidenceRefTitle(ref: InspirationEvidenceRef): string {
  const candidates = [ref.label, ref.source_label, ref.source];
  for (const candidate of candidates) {
    const visible = sanitizeInspirationVisibleText(candidate, '');
    if (visible) return visible;
  }
  return '证据资料';
}

function evidenceRefMeta(ref: InspirationEvidenceRef): string {
  const parts = ['资料'];
  if (typeof ref.page === 'number') {
    parts.push(`p.${ref.page}`);
  }
  return parts.join(' · ');
}

function evidenceSourceLabels(labels: readonly string[]): string[] {
  return Array.from(
    new Set(
      labels
        .map((label) => sanitizeInspirationVisibleText(label, ''))
        .filter((label) => label.length > 0),
    ),
  ).slice(0, 8);
}

export function InspirationPanel({ onContinueWrite }: InspirationPanelProps) {
  const { activeProjectId } = useWriting();
  const [query, setQuery] = useState('');
  const [sparks, setSparks] = useState<InspirationSpark[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [continuationLoading, setContinuationLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [samplingStatus, setSamplingStatus] = useState(() => summarizeInspirationSampling());
  const [sourceLabelsInput, setSourceLabelsInput] = useState('');
  const [appliedSourceLabels, setAppliedSourceLabels] = useState<string[]>([]);
  const [evidenceRefs, setEvidenceRefs] = useState<InspirationEvidenceRef[]>([]);
  const [evidenceTotal, setEvidenceTotal] = useState(0);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceExporting, setEvidenceExporting] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const projectReasoningBias = useProjectReasoningBiasState(activeProjectId);
  const defaultProjectBiasEnabled = projectReasoningBias.isEnabledForSurface('analysis_chain');
  const [projectBiasEnabled, setProjectBiasEnabled] = useState(defaultProjectBiasEnabled);
  const requestAbortControllerRef = useRef<AbortController | null>(null);
  const stopRequestedRef = useRef(false);

  useEffect(() => () => {
    requestAbortControllerRef.current?.abort();
  }, []);

  useEffect(() => {
    setProjectBiasEnabled(defaultProjectBiasEnabled);
  }, [defaultProjectBiasEnabled, activeProjectId]);

  const handleSearch = useCallback(async () => {
    if (!query.trim() || loading) return;
    const abortController = new AbortController();
    requestAbortControllerRef.current = abortController;
    stopRequestedRef.current = false;
    setLoading(true);
    setError(null);
    setNotice('正在生成启发点…');
    try {
      const results = await inspirationService.generateSparks(
        query.trim(),
        10,
        activeProjectId ?? undefined,
        {
          projectReasoningBiasEnabled: defaultProjectBiasEnabled ? projectBiasEnabled : undefined,
          signal: abortController.signal,
        },
      );
      setSparks(results);
      if (results.length === 0) {
        setError('未找到相关启发点，请尝试其他关键词');
        setNotice(null);
      } else {
        setNotice(`已生成 ${results.length} 条启发点。`);
      }
    } catch (error: unknown) {
      if (stopRequestedRef.current || isAbortLikeError(error)) {
        setError('已停止生成。');
      } else {
        setError('启发点生成失败，请检查后端服务');
      }
      setNotice(null);
    } finally {
      if (requestAbortControllerRef.current === abortController) {
        requestAbortControllerRef.current = null;
      }
      stopRequestedRef.current = false;
      setLoading(false);
    }
  }, [query, loading, activeProjectId, defaultProjectBiasEnabled, projectBiasEnabled]);

  const handleStopGeneration = useCallback(() => {
    stopRequestedRef.current = true;
    requestAbortControllerRef.current?.abort();
    setNotice('正在停止生成…');
  }, []);

  const loadEvidenceRefs = useCallback(async (labels: string[]) => {
    setEvidenceLoading(true);
    setEvidenceError(null);
    try {
      const response = await inspirationService.listEvidenceRefs({
        sourceLabels: labels,
        page: 1,
        pageSize: 12,
      });
      setEvidenceRefs(response.refs);
      setEvidenceTotal(response.total);
      setSourceLabelsInput(response.filtered_by_labels.join(', '));
    } catch {
      setEvidenceRefs([]);
      setEvidenceTotal(0);
      setEvidenceError('独立证据索引加载失败');
    } finally {
      setEvidenceLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    getSampling()
      .then((data) => {
        if (!cancelled) {
          setSamplingStatus(summarizeInspirationSampling(data.tasks?.inspiration));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSamplingStatus(summarizeInspirationSampling());
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    void loadEvidenceRefs(appliedSourceLabels);
  }, [appliedSourceLabels, loadEvidenceRefs]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSearch();
    }
  };

  const handleContinue = useCallback(async (sparkId: string) => {
    setContinuationLoading(sparkId);
    setError(null);
    setNotice('正在加载续写上下文…');
    try {
      const ctx = await inspirationService.getSparkContext(sparkId);
      onContinueWrite(ctx);
      setNotice('续写上下文已发送到手稿编辑区。');
    } catch {
      setNotice(null);
      setError('续写上下文加载失败，启发点未插入，请稍后重试。');
    } finally {
      setContinuationLoading(null);
    }
  }, [onContinueWrite]);

  const handleEvidenceFilterSubmit = useCallback((event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setAppliedSourceLabels(parseSourceLabelsInput(sourceLabelsInput));
  }, [sourceLabelsInput]);

  const handleResetEvidenceFilter = useCallback(() => {
    setSourceLabelsInput('');
    setAppliedSourceLabels([]);
  }, []);

  const handleEvidenceExport = useCallback(async () => {
    if (evidenceExporting) return;
    setEvidenceExporting(true);
    setError(null);
    setNotice('正在导出证据引用…');
    try {
      const { blob, filename } = await inspirationService.exportEvidenceRefs({
        format: 'json',
        sourceLabels: appliedSourceLabels,
      });
      const objectUrl = URL.createObjectURL(blob);
      downloadBlob(objectUrl, filename);
      setNotice(appliedSourceLabels.length > 0 ? '已导出当前过滤条件下的证据引用。' : '证据引用已导出。');
    } catch {
      setNotice(null);
      setError('证据引用导出失败，请稍后重试。');
    } finally {
      setEvidenceExporting(false);
    }
  }, [appliedSourceLabels, evidenceExporting]);

  return (
    <div className="space-y-4">
      {/* 搜索栏 */}
      <div className="relative">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-foreground/30" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入研究主题，探索灵感..."
          className="w-full pl-9 pr-20 py-3 font-label text-[12px] rounded-sm border border-outline-variant bg-surface-lowest focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/30 placeholder:text-foreground/30 transition-all"
        />
        {loading ? (
          <button
            type="button"
            onClick={handleStopGeneration}
            className="absolute right-2 top-1/2 -translate-y-1/2 inline-flex items-center gap-1 rounded-sm bg-red-600 px-3 py-1.5 font-label text-[10px] font-medium uppercase tracking-wider text-white transition-all hover:bg-red-700"
          >
            <Square size={12} />
            停止
          </button>
        ) : (
          <button
            type="button"
            onClick={handleSearch}
            disabled={!query.trim()}
            className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1.5 font-label text-[10px] font-medium uppercase tracking-wider rounded-sm bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            探索
          </button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-[10px] font-label text-foreground/40">
        <ProjectBiasSurfaceToggle
          enabled={projectBiasEnabled && defaultProjectBiasEnabled}
          label={projectBiasEnabled && defaultProjectBiasEnabled ? '思维链偏置已启用' : '思维链偏置已关闭'}
          disabled={!defaultProjectBiasEnabled || projectReasoningBias.loading || loading}
          onChange={setProjectBiasEnabled}
        />
        <span>
          {defaultProjectBiasEnabled ? '仅影响本次灵感生成' : '当前项目未启用思维链偏置'}
        </span>
      </div>
      <div className="flex items-center gap-2 text-[10px] font-label text-foreground/40">
        <span>{samplingStatus}</span>
        <Link to={buildSettingsSectionPath('sampling')} className="text-primary hover:text-primary/80 transition-colors">
          去设置
        </Link>
      </div>

      <section className="rounded-sm border border-outline-variant/60 bg-surface-lowest p-4 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-label text-[11px] font-semibold uppercase tracking-wide text-foreground/55">
              独立证据索引
            </h2>
            <p className="mt-1 text-[11px] leading-5 text-foreground/45">
              按来源标签筛选可复用证据，生成灵感前也能先检查证据范围。
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="rounded-full bg-surface-low px-2 py-1 text-[10px] font-medium text-foreground/45">
              {evidenceTotal} 条
            </span>
            <button
              type="button"
              onClick={handleEvidenceExport}
              disabled={evidenceExporting}
              className="inline-flex min-h-7 items-center gap-1.5 rounded-sm border border-outline-variant/60 bg-surface-low px-2.5 text-[10px] font-medium text-foreground/65 transition-colors hover:border-primary/30 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              {evidenceExporting ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
              导出
            </button>
          </div>
        </div>

        <form className="flex flex-col gap-2 sm:flex-row" onSubmit={handleEvidenceFilterSubmit}>
          <label className="sr-only" htmlFor="inspiration-source-label-filter">
            按来源标签过滤
          </label>
          <input
            id="inspiration-source-label-filter"
            type="text"
            value={sourceLabelsInput}
            onChange={(event) => setSourceLabelsInput(event.target.value)}
            placeholder="例如 method, figure, spark"
            className="min-w-0 flex-1 rounded-sm border border-outline-variant bg-surface-low px-3 py-2 text-[12px] font-label text-foreground placeholder:text-foreground/30 focus:border-primary/30 focus:outline-none focus:ring-2 focus:ring-primary/20"
          />
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={evidenceLoading}
              className="inline-flex items-center justify-center rounded-sm bg-primary px-3 py-2 text-[11px] font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {evidenceLoading ? '加载中…' : '应用过滤'}
            </button>
            <button
              type="button"
              onClick={handleResetEvidenceFilter}
              disabled={evidenceLoading || (sourceLabelsInput.trim().length === 0 && appliedSourceLabels.length === 0)}
              className="inline-flex items-center justify-center rounded-sm border border-outline-variant/60 bg-surface-low px-3 py-2 text-[11px] font-medium text-foreground/70 transition-colors hover:border-primary/30 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
            >
              重置
            </button>
          </div>
        </form>

        {appliedSourceLabels.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {appliedSourceLabels.map((label) => (
              <span
                key={label}
                className="inline-flex items-center rounded-full border border-primary/20 bg-primary/5 px-2 py-0.5 text-[10px] font-medium text-primary"
              >
                {label}
              </span>
            ))}
          </div>
        )}

        {evidenceError && (
          <div className="rounded-sm border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
            {evidenceError}
          </div>
        )}

        {!evidenceError && evidenceLoading && evidenceRefs.length === 0 && (
          <div className="flex items-center gap-2 text-[11px] text-foreground/45">
            <Loader2 size={12} className="animate-spin" />
            正在加载独立证据引用…
          </div>
        )}

        {!evidenceError && !evidenceLoading && evidenceRefs.length === 0 && (
          <p className="text-[11px] leading-5 text-foreground/40">
            当前过滤条件下没有证据引用。
          </p>
        )}

        {evidenceRefs.length > 0 && (
          <div className="max-h-56 space-y-2 overflow-auto pr-1">
            {evidenceRefs.map((ref) => {
              const visibleSourceLabels = evidenceSourceLabels(ref.source_labels);
              return (
                <article
                  key={`${ref.material_id}:${ref.chunk_id}`}
                  className="rounded-sm border border-outline-variant/60 bg-surface-low p-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-[11px] font-medium text-foreground">
                        {evidenceRefTitle(ref)}
                      </p>
                      <p className="mt-0.5 text-[10px] text-foreground/45">
                        {evidenceRefMeta(ref)}
                      </p>
                    </div>
                    {typeof ref.score === 'number' && (
                      <span className="shrink-0 rounded-full bg-surface-lowest px-2 py-0.5 text-[10px] text-foreground/45">
                        {Math.round(ref.score * 100)}%
                      </span>
                    )}
                  </div>
                  {ref.text && (
                    <p className="mt-2 line-clamp-2 text-[11px] leading-5 text-foreground/70">
                      {sanitizeInspirationVisibleText(ref.text, '证据片段包含内部信息，已隐藏。')}
                    </p>
                  )}
                  {visibleSourceLabels.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {visibleSourceLabels.map((label) => (
                        <span
                          key={`${ref.chunk_id}:${label}`}
                          className="inline-flex items-center rounded-full bg-surface-lowest px-2 py-0.5 text-[10px] text-foreground/50"
                        >
                          {label}
                        </span>
                      ))}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>

      {/* 错误/空状态 */}
      {error && (
        <div role="alert" className="rounded-sm border border-amber-200 bg-amber-50/50 p-3 font-label text-[11px] text-amber-700">
          {error}
        </div>
      )}

      {notice && !error && (
        <div role="status" className="rounded-sm border border-emerald-200 bg-emerald-50/60 p-3 font-label text-[11px] text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300">
          {notice}
        </div>
      )}

      {/* 启发点列表 */}
      <AnimatePresence mode="popLayout">
        {sparks.map((spark, index) => {
          const config = sparkTypeConfig[spark.spark_type] || sparkTypeConfig.memory_association;
          const Icon = config.icon;
          const isExpanded = expandedId === spark.id;
          const isContinuing = continuationLoading === spark.id;
          const detailsId = `inspiration-spark-details-${spark.id}`;
          const toggleExpanded = () => setExpandedId(isExpanded ? null : spark.id);
          const handleDisclosureKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            toggleExpanded();
          };

          return (
            <motion.div
              key={spark.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ delay: index * 0.05 }}
              className={cn(
                "rounded-sm border transition-all cursor-pointer group",
                isExpanded
                  ? "bg-surface-lowest border-primary/20 shadow-md"
                  : "bg-surface-low border-outline-variant/50 hover:bg-surface-lowest hover:border-primary/10 hover:shadow-sm"
              )}
            >
              <div
                className="p-4"
                role="button"
                tabIndex={0}
                aria-expanded={isExpanded}
                aria-controls={detailsId}
                onClick={toggleExpanded}
                onKeyDown={handleDisclosureKeyDown}
              >
                {/* 标签行 */}
                <div className="flex items-center gap-2 mb-2">
                  <div className={cn("p-1 rounded-sm border", config.color)}>
                    <Icon size={12} />
                  </div>
                  <span className="font-label text-[9px] font-medium uppercase tracking-wider text-foreground/40">
                    {config.label}
                  </span>
                  <div className="flex-1" />
                  <span className="font-label text-[9px] font-medium text-foreground/30">
                    {Math.round(spark.confidence * 100)}%
                  </span>
                  <ChevronRight
                    size={12}
                    className={cn(
                      "text-foreground/30 transition-transform",
                      isExpanded && "rotate-90"
                    )}
                  />
                </div>

                {/* 内容 */}
                <p className={cn(
                  "text-[11px] leading-[1.7] text-foreground",
                  !isExpanded && "line-clamp-2"
                )}>
                  {sanitizeInspirationVisibleText(spark.content, '启发内容包含内部信息，已隐藏。')}
                </p>

                {/* 来源 */}
                  {spark.source_papers.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {spark.source_papers.slice(0, 2).map((paper, i) => (
                      <span
                        key={i}
                        className="text-[8px] px-2 py-0.5 rounded-sm bg-surface-container font-label text-foreground/50 truncate max-w-[140px]"
                      >
                        {sanitizeInspirationVisibleText(paper, '来源已隐藏')}
                      </span>
                    ))}
                  </div>
                )}

                {/* Track B: clickable evidence anchors when the spark
                    carries chunk metadata (D-EVR-1..6). */}
                <SparkEvidencePills
                  refs={spark.evidence_refs}
                  projectId={activeProjectId}
                  className="mt-2"
                />
              </div>

              {/* 展开详情 + 续写按钮 */}
              <AnimatePresence>
                {isExpanded && (
                  <motion.div
                    id={detailsId}
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="overflow-hidden"
                  >
                    <div className="space-y-3 border-t border-outline-variant/30 px-4 pb-4 pt-3">
                      <InspirationAnalysisChain spark={spark} compact />
                      {spark.actionable && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleContinue(spark.id);
                          }}
                          disabled={isContinuing}
                          className="w-full flex items-center justify-center gap-2 py-2.5 rounded-sm bg-primary/5 text-primary font-label text-[11px] font-medium hover:bg-primary/10 active:scale-[0.98] transition-all disabled:opacity-50"
                        >
                          {isContinuing ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            <PenLine size={14} />
                          )}
                          基于此启发点续写
                        </button>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          );
        })}
      </AnimatePresence>

      {/* 初始空状态 */}
      {sparks.length === 0 && !loading && !error && (
        <div className="rounded-sm border border-dashed border-outline-variant bg-surface-low p-6 text-center">
          <Lightbulb size={24} className="mx-auto mb-3 text-primary/40" />
          <p className="font-body text-[11px] text-foreground/50 leading-6">
            输入研究主题或关键词，<br />
            系统将从已分析的文献记忆中生成联想启发
          </p>
        </div>
      )}
    </div>
  );
}
