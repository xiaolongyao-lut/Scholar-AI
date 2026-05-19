import React, { useState, useCallback, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
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
  Target,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { getInspirationService } from '@/services/inspirationService';
import { getSampling } from '@/services/samplingApi';
import { useWriting } from '@/contexts/WritingContext';
import type { InspirationSpark, ContinuationContext } from '@/types/writing';
import { summarizeInspirationSampling } from './inspirationSamplingStatus';
import { SparkEvidencePills } from '@/components/inspiration/SparkEvidencePills';

const inspirationService = getInspirationService();

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

export function InspirationPanel({ onContinueWrite }: InspirationPanelProps) {
  const { activeProjectId } = useWriting();
  const [query, setQuery] = useState('');
  const [sparks, setSparks] = useState<InspirationSpark[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [continuationLoading, setContinuationLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [samplingStatus, setSamplingStatus] = useState(() => summarizeInspirationSampling());

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const results = await inspirationService.generateSparks(query.trim(), 10, activeProjectId ?? undefined);
      setSparks(results);
      if (results.length === 0) {
        setError('未找到相关启发点，请尝试其他关键词');
      }
    } catch {
      setError('启发点生成失败，请检查后端服务');
    } finally {
      setLoading(false);
    }
  }, [query]);

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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSearch();
    }
  };

  const handleContinue = useCallback(async (sparkId: string) => {
    setContinuationLoading(sparkId);
    try {
      const ctx = await inspirationService.getSparkContext(sparkId);
      onContinueWrite(ctx);
    } catch {
      setError('续写上下文加载失败');
    } finally {
      setContinuationLoading(null);
    }
  }, [onContinueWrite]);

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
        <button
          onClick={handleSearch}
          disabled={loading || !query.trim()}
          className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1.5 font-label text-[10px] font-medium uppercase tracking-wider rounded-sm bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
        >
          {loading ? <Loader2 size={12} className="animate-spin" /> : '探索'}
        </button>
      </div>
      <div className="flex items-center gap-2 text-[10px] font-label text-foreground/40">
        <span>{samplingStatus}</span>
        <a href="/settings#section-sampling" className="text-primary hover:text-primary/80 transition-colors">
          去设置
        </a>
      </div>

      {/* 错误/空状态 */}
      {error && (
        <div className="rounded-sm border border-amber-200 bg-amber-50/50 p-3 font-label text-[11px] text-amber-700">
          {error}
        </div>
      )}

      {/* 启发点列表 */}
      <AnimatePresence mode="popLayout">
        {sparks.map((spark, index) => {
          const config = sparkTypeConfig[spark.spark_type] || sparkTypeConfig.memory_association;
          const Icon = config.icon;
          const isExpanded = expandedId === spark.id;
          const isContinuing = continuationLoading === spark.id;

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
                onClick={() => setExpandedId(isExpanded ? null : spark.id)}
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
                  {spark.content}
                </p>

                {/* 来源 */}
                {spark.source_papers.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {spark.source_papers.slice(0, 2).map((paper, i) => (
                      <span
                        key={i}
                        className="text-[8px] px-2 py-0.5 rounded-sm bg-surface-container font-label text-foreground/50 truncate max-w-[140px]"
                      >
                        {paper}
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
                {isExpanded && spark.actionable && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="overflow-hidden"
                  >
                    <div className="px-4 pb-4 pt-0 border-t border-outline-variant/30">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleContinue(spark.id);
                        }}
                        disabled={isContinuing}
                        className="mt-3 w-full flex items-center justify-center gap-2 py-2.5 rounded-sm bg-primary/5 text-primary font-label text-[11px] font-medium hover:bg-primary/10 active:scale-[0.98] transition-all disabled:opacity-50"
                      >
                        {isContinuing ? (
                          <Loader2 size={14} className="animate-spin" />
                        ) : (
                          <PenLine size={14} />
                        )}
                        基于此启发点续写
                      </button>
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
