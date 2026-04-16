import React, { useState, useRef } from 'react';
import { Image, Plus, Grid3X3, List, ZoomIn, Trash2, Tag, FileImage } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { EmptyState } from '@/components/common/EmptyState';

interface FigureItem {
  id: string;
  name: string;
  type: 'figure' | 'table';
  caption: string;
  linkedSection?: string;
  width: number;
  height: number;
}

const MOCK_FIGURES_PLACEHOLDER: FigureItem[] = [];

export function FiguresTables() {
  const { t } = useI18n();
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [items, setItems] = useState<FigureItem[]>([]);

  const handleAddFigure = () => {
    fileInputRef.current?.click();
  };

  const handleFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    for (const file of Array.from(files)) {
      const newItem: FigureItem = {
        id: `f-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        name: `图 ${items.filter(i => i.type === 'figure').length + 1}`,
        type: 'figure',
        caption: file.name,
        width: 640,
        height: 480,
      };
      setItems(prev => [...prev, newItem]);
    }
    e.target.value = '';
  };

  const figures = items.filter(f => f.type === 'figure');
  const tables = items.filter(f => f.type === 'table');

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex justify-between items-start mb-6">
        <div>
          <h1 className="font-display text-xl font-semibold text-foreground flex items-center gap-2.5">
            <Image size={22} className="text-primary" />
            {t('writing.figures.title')}
          </h1>
          <p className="font-label text-xs text-foreground/40 mt-1">
            {t('writing.figures.subtitle', { figures: figures.length, tables: tables.length })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-0.5 p-0.5 bg-surface-high rounded border border-outline-variant/30">
            <button
              type="button"
              onClick={() => setViewMode('grid')}
              aria-label="网格视图"
              title="网格视图"
              className={cn('p-1.5 rounded transition-all', viewMode === 'grid' ? 'bg-primary text-primary-foreground shadow-sm' : 'text-foreground/30')}
            >
              <Grid3X3 size={14} />
            </button>
            <button
              type="button"
              onClick={() => setViewMode('list')}
              aria-label="列表视图"
              title="列表视图"
              className={cn('p-1.5 rounded transition-all', viewMode === 'list' ? 'bg-primary text-primary-foreground shadow-sm' : 'text-foreground/30')}
            >
              <List size={14} />
            </button>
          </div>
          <button
            type="button"
            onClick={handleAddFigure}
            className="flex items-center gap-1.5 px-3 py-2 bg-primary text-primary-foreground rounded-lg font-label text-xs font-medium shadow-sm hover:bg-primary/90 transition-all"
          >
            <Plus size={14} />
            {t('writing.figures.add')}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            title={t('writing.figures.add')}
            aria-label={t('writing.figures.add')}
            onChange={handleFileSelected}
          />
        </div>
      </div>

      {/* Grid view */}
      {viewMode === 'grid' ? (
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((fig, i) => (
            <motion.div
              key={fig.id}
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: i * 0.04 }}
              className="glass-card rounded-lg overflow-hidden group hover:border-primary/30 cursor-pointer transition-all"
            >
              {/* Placeholder image area */}
              <div className="relative bg-surface-high aspect-[4/3] flex items-center justify-center">
                <FileImage size={32} className="text-foreground/10" />
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/5 transition-colors flex items-center justify-center">
                  <ZoomIn size={20} className="text-white opacity-0 group-hover:opacity-80 transition-opacity drop-shadow-md" />
                </div>
                <span className={cn(
                  'absolute top-2 left-2 px-1.5 py-0.5 text-[9px] font-label font-medium rounded',
                  fig.type === 'figure' ? 'bg-primary/90 text-white' : 'bg-amber-500/90 text-white'
                )}>
                  {fig.type === 'figure' ? 'FIG' : 'TBL'}
                </span>
              </div>
              <div className="p-3">
                <h4 className="font-headline text-sm font-medium text-foreground">{fig.name}</h4>
                <p className="font-body text-[11px] text-foreground/50 mt-0.5 line-clamp-2">{fig.caption}</p>
                {fig.linkedSection && (
                  <span className="inline-flex items-center gap-1 mt-2 px-1.5 py-0.5 bg-surface-high text-[9px] font-label text-foreground/40 rounded">
                    <Tag size={8} /> §{fig.linkedSection}
                  </span>
                )}
              </div>
            </motion.div>
          ))}
        </div>
      ) : (
        /* List view */
        <div className="glass-card rounded-lg divide-y divide-outline-variant/30">
          {items.map((fig, i) => (
            <motion.div
              key={fig.id}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: i * 0.03 }}
              className="flex items-center gap-4 p-4 hover:bg-surface-high/50 transition-colors cursor-pointer group"
            >
              <div className="w-16 h-12 bg-surface-high rounded flex items-center justify-center flex-shrink-0">
                <FileImage size={20} className="text-foreground/15" />
              </div>
              <div className="flex-1 min-w-0">
                <h4 className="font-headline text-sm font-medium text-foreground">{fig.name}</h4>
                <p className="font-body text-[11px] text-foreground/50 truncate">{fig.caption}</p>
              </div>
              <span className={cn(
                'px-2 py-0.5 text-[9px] font-label font-medium rounded',
                fig.type === 'figure' ? 'bg-primary/10 text-primary' : 'bg-amber-100 text-amber-700'
              )}>
                {fig.type.toUpperCase()}
              </span>
              {fig.linkedSection && (
                <span className="font-label text-[10px] text-foreground/30">§{fig.linkedSection}</span>
              )}
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
