import React, { useState, useRef } from 'react';
import { BookMarked, Search, Plus, ExternalLink, FileText, Filter, ChevronDown, Quote, Calendar, User } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { PageHeader } from '@/components/common/PageHeader';

interface Reference {
  id: string;
  title: string;
  authors: string;
  year: number;
  journal: string;
  doi?: string;
  cited: boolean;
  tags: string[];
}

const MOCK_REFS_PLACEHOLDER: Reference[] = [];

export function SourcesCitations() {
  const { t } = useI18n();
  const [search, setSearch] = useState('');
  const [showCitedOnly, setShowCitedOnly] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [refs, setRefs] = useState<Reference[]>([]);

  const handleImport = () => {
    fileInputRef.current?.click();
  };

  const handleFileImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    for (const file of Array.from(files)) {
      const newRef: Reference = {
        id: `r-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        title: file.name.replace(/\.[^.]+$/, ''),
        authors: t('sources.author_placeholder'),
        year: new Date().getFullYear(),
        journal: '',
        cited: false,
        tags: [],
      };
      setRefs(prev => [...prev, newRef]);
    }
    e.target.value = '';
  };

  const filtered = refs.filter(r => {
    if (showCitedOnly && !r.cited) return false;
    if (search && !r.title.toLowerCase().includes(search.toLowerCase()) && !r.authors.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-6 py-4">
        <PageHeader
          icon={<BookMarked size={18} />}
          title={t('writing.sources.title')}
          subtitle={t('writing.sources.subtitle', { total: refs.length, cited: refs.filter(r => r.cited).length })}
          className="mb-0"
          actions={
            <>
              <button
                type="button"
                onClick={handleImport}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 font-label text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                <Plus size={13} />
                {t('writing.sources.import')}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".bib,.ris,.enw,.pdf"
                multiple
                className="hidden"
                aria-label={t('writing.sources.import')}
                title={t('writing.sources.import')}
                onChange={handleFileImport}
              />
            </>
          }
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-auto px-6 py-5">
      {/* Search + Filter */}
      <div className="flex items-center gap-3 mb-5">
        <div className="flex-1 flex items-center gap-2 bg-surface-lowest rounded-lg px-3 py-2 border border-outline-variant/50 focus-within:border-primary/40 transition-colors">
          <Search size={15} className="text-foreground/30" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder={t('writing.sources.search_placeholder')}
            className="flex-1 bg-transparent text-sm font-label text-foreground placeholder:text-foreground/30 focus:outline-none"
          />
        </div>
        <button
          type="button"
          onClick={() => setShowCitedOnly(!showCitedOnly)}
          className={cn(
            'flex items-center gap-1.5 px-3 py-2 rounded-lg border text-xs font-label font-medium transition-all',
            showCitedOnly ? 'bg-primary/10 border-primary text-primary' : 'bg-surface-high border-outline-variant text-foreground/40 hover:text-foreground'
          )}
        >
          <Quote size={13} />
          {t('writing.sources.cited_only')}
        </button>
      </div>

      {/* References list */}
      <div className="space-y-3">
        <AnimatePresence>
          {filtered.map((ref, i) => (
            <motion.div
              key={ref.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, x: -10 }}
              transition={{ delay: i * 0.03 }}
              className="glass-card rounded-lg p-4 group hover:border-primary/30 transition-all"
            >
              <div className="flex items-start gap-3">
                <div className="h-9 w-9 bg-surface-high rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5">
                  <FileText size={16} className={ref.cited ? 'text-primary' : 'text-foreground/25'} />
                </div>
                <div className="flex-1 min-w-0">
                  <h4 className="font-headline text-sm font-medium text-foreground leading-snug line-clamp-2">{ref.title}</h4>
                  <div className="flex items-center gap-3 mt-1.5 text-[11px] font-label text-foreground/40">
                    <span className="flex items-center gap-1"><User size={10} /> {ref.authors}</span>
                    <span className="flex items-center gap-1"><Calendar size={10} /> {ref.year}</span>
                  </div>
                  <p className="font-label text-[10px] text-foreground/30 mt-1 italic">{ref.journal}</p>
                  <div className="flex items-center gap-1.5 mt-2">
                    {ref.tags.map(tag => (
                      <span key={tag} className="px-1.5 py-0.5 bg-surface-high text-[9px] font-label text-foreground/40 rounded">{tag}</span>
                    ))}
                    {ref.cited && (
                      <span className="px-1.5 py-0.5 bg-primary/10 text-[9px] font-label text-primary rounded font-medium">{t('writing.sources.cited_badge')}</span>
                    )}
                  </div>
                </div>
                {ref.doi && (
                  <a href={`https://doi.org/${ref.doi}`} target="_blank" rel="noopener noreferrer" title={`DOI: ${ref.doi}`} aria-label={`DOI: ${ref.doi}`} className="p-1.5 text-foreground/20 hover:text-primary transition-colors opacity-0 group-hover:opacity-100">
                    <ExternalLink size={14} />
                  </a>
                )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
      </div>
    </div>
  );
}
