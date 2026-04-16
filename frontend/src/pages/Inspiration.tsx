import React, { useState, useCallback } from 'react';
import { Lightbulb, Search, RefreshCw, ChevronRight, Tag, BookOpen, Loader2, AlertCircle, Sparkles } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { getInspirationService } from '@/services/inspirationService';
import type { InspirationSpark, ContinuationContext } from '@/types/writing';

type SparkType = InspirationSpark['spark_type'];

const SPARK_TYPE_STYLE: Record<string, { label: string; bg: string; text: string }> = {
  gap: { label: '研究空白', bg: 'bg-amber-50', text: 'text-amber-700' },
  contradiction: { label: '矛盾冲突', bg: 'bg-red-50', text: 'text-red-700' },
  extension: { label: '研究延伸', bg: 'bg-sky-50', text: 'text-sky-700' },
  application: { label: '应用场景', bg: 'bg-emerald-50', text: 'text-emerald-700' },
  default: { label: '灵感', bg: 'bg-purple-50', text: 'text-purple-700' },
};

function sparkStyle(type: SparkType) {
  return SPARK_TYPE_STYLE[String(type)] ?? SPARK_TYPE_STYLE.default;
}

/* ── Single Spark Card ── */
function SparkCard({ spark, onExpand }: { spark: InspirationSpark; onExpand: (spark: InspirationSpark) => void }) {
  const style = sparkStyle(spark.spark_type);
  const confidence = Math.round(spark.confidence * 100);

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
            {spark.content}
          </p>
          <div className="mt-2.5 flex items-center flex-wrap gap-2">
            <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium', style.bg, style.text)}>
              <Tag size={10} />
              {style.label}
            </span>
            {spark.actionable && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700">
                <Sparkles size={10} />
                可行
              </span>
            )}
            <span className="ml-auto text-xs text-foreground/40 font-mono">{confidence}%</span>
          </div>
          {spark.source_papers.length > 0 && (
            <div className="mt-2 flex items-center gap-1 text-xs text-foreground/40">
              <BookOpen size={11} />
              <span className="truncate">{spark.source_papers.join('、')}</span>
            </div>
          )}
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
  onClose,
}: {
  spark: InspirationSpark;
  context: ContinuationContext | null;
  loading: boolean;
  onClose: () => void;
}) {
  const style = sparkStyle(spark.spark_type);

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
        <p className="font-body text-sm text-foreground leading-relaxed">{spark.content}</p>

        {loading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={20} className="animate-spin text-primary" />
          </div>
        )}

        {!loading && context && (
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
                      {t}
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
                  {context.causal_chain_summary}
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
                      {angle}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </motion.div>
  );
}

/* ── Main Page ── */
export function Inspiration() {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [sparks, setSparks] = useState<InspirationSpark[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSpark, setSelectedSpark] = useState<InspirationSpark | null>(null);
  const [context, setContext] = useState<ContinuationContext | null>(null);
  const [contextLoading, setContextLoading] = useState(false);

  const handleSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setError(null);
    setSparks([]);
    setSelectedSpark(null);
    try {
      const service = getInspirationService();
      const results = await service.generateSparks(q, 20);
      setSparks(results);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [query]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) handleSearch();
  };

  const handleExpand = useCallback(async (spark: InspirationSpark) => {
    setSelectedSpark(spark);
    setContext(null);
    setContextLoading(true);
    try {
      const service = getInspirationService();
      const ctx = await service.getSparkContext(spark.id);
      setContext(ctx);
    } catch {
      // Fail silently — spark is still useful without context
    } finally {
      setContextLoading(false);
    }
  }, []);

  const handleReload = useCallback(async () => {
    try {
      await getInspirationService().reloadEngine();
    } catch { /* silent */ }
  }, []);

  return (
    <div className="flex h-full bg-surface-base">
      {/* Left panel */}
      <div className={cn('flex flex-col min-w-0 transition-all duration-200', selectedSpark ? 'w-[55%]' : 'w-full')}>
        {/* Search header */}
        <div className="p-5 border-b border-outline-variant bg-surface-lowest">
          <div className="flex items-center gap-3 mb-3">
            <Sparkles size={18} className="text-primary" />
            <h1 className="font-headline text-lg text-foreground">一句话灵感</h1>
            <button
              type="button"
              onClick={handleReload}
              title="重新加载灵感引擎"
              className="ml-auto p-1.5 rounded hover:bg-surface-high text-foreground/40 hover:text-foreground transition-colors"
            >
              <RefreshCw size={15} />
            </button>
          </div>
          <p className="font-body text-xs text-foreground/50 mb-3 leading-relaxed">
            输入研究主题，从已索引文献中挖掘研究空白、矛盾与延伸灵感
          </p>
          <div className="flex gap-2">
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="例：钛合金热处理工艺优化…"
              className="flex-1 px-3 py-2 rounded-lg border border-outline-variant bg-surface-low text-sm font-body text-foreground placeholder:text-foreground/30 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/40 transition-colors"
            />
            <button
              type="button"
              onClick={handleSearch}
              disabled={loading || !query.trim()}
              className={cn(
                'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-label transition-colors',
                loading || !query.trim()
                  ? 'bg-primary/20 text-primary/40 cursor-not-allowed'
                  : 'bg-primary text-white hover:bg-primary/90'
              )}
            >
              {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
              生成灵感
            </button>
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto p-4">
          {error && (
            <div className="flex items-center gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm mb-4">
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
              <p className="font-label text-xs text-foreground/40">正在捕捞灵感…</p>
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
                  />
                ))}
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
              onClose={() => { setSelectedSpark(null); setContext(null); }}
            />
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
