import React, { useState, useCallback } from 'react';
import { List, Plus, GripVertical, ChevronRight, ChevronDown, FileText, MoreHorizontal, Trash2, Edit3, X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { PageHeader } from '@/components/common/PageHeader';
import { useWriting } from '@/contexts/WritingContext';
import { getWritingBackendService } from '@/services/writingBackend';

interface OutlineNode {
  id: string;
  label: string;
  level: number;
  status: 'done' | 'wip' | 'empty';
  wordCount: number;
  children?: OutlineNode[];
}

const MOCK_OUTLINE_PLACEHOLDER: OutlineNode[] = [];

function OutlineItem({ node, onDelete }: { node: OutlineNode; onDelete?: (id: string) => void }) {
  const [open, setOpen] = React.useState(true);
  const [menuOpen, setMenuOpen] = React.useState(false);
  const { t } = useI18n();
  const statusColor = { done: 'bg-emerald-500 dark:bg-emerald-400', wip: 'bg-amber-500 dark:bg-amber-400', empty: 'bg-surface-highest' }[node.status];

  return (
    <div>
      <div className={cn(
        'group flex items-center gap-2 px-3 py-2.5 rounded-lg hover:bg-surface-high/50 transition-colors cursor-pointer',
        node.level > 0 && 'ml-8'
      )}>
        <GripVertical size={14} className="text-foreground/15 opacity-0 group-hover:opacity-100 transition-opacity cursor-grab" />
        {node.children ? (
          <button
            type="button"
            onClick={() => setOpen(!open)}
            aria-label={open ? `折叠 ${node.label}` : `展开 ${node.label}`}
            title={open ? `折叠 ${node.label}` : `展开 ${node.label}`}
            className="p-0.5"
          >
            {open ? <ChevronDown size={14} className="text-foreground/30" /> : <ChevronRight size={14} className="text-foreground/30" />}
          </button>
        ) : (
          <div className="w-5" />
        )}
        <div className={cn('w-2 h-2 rounded-full flex-shrink-0', statusColor)} />
        <span className="font-label text-sm font-medium text-foreground flex-1">{node.label}</span>
        <span className="font-label text-[10px] text-foreground/30 tabular-nums">{node.wordCount > 0 ? `${node.wordCount} ${t('common.unit_chars')}` : '—'}</span>
        <div className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen(!menuOpen)}
            aria-label={`章节操作 ${node.label}`}
            title={`章节操作 ${node.label}`}
            className="p-1 text-foreground/20 opacity-0 group-hover:opacity-100 hover:text-foreground/40 transition-all"
          >
            <MoreHorizontal size={14} />
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-full mt-1 w-32 bg-surface-lowest border border-outline-variant rounded-lg shadow-lg z-20 py-1">
              <button
                type="button"
                onClick={() => { onDelete?.(node.id); setMenuOpen(false); }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs font-label text-red-500 hover:bg-red-50 transition-colors"
              >
                <Trash2 size={12} /> {t('common.delete')}
              </button>
            </div>
          )}
        </div>
      </div>
      {node.children && open && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          className="overflow-hidden"
        >
          {node.children.map(child => <OutlineItem key={child.id} node={child} onDelete={onDelete} />)}
        </motion.div>
      )}
    </div>
  );
}

export function OutlineManager() {
  const { t } = useI18n();
  const { activeProjectId } = useWriting();

  const MOCK_OUTLINE: OutlineNode[] = [];

  const [outline, setOutline] = useState<OutlineNode[]>(MOCK_OUTLINE);
  const [adding, setAdding] = useState(false);

  const handleAddSection = useCallback(async () => {
    if (!activeProjectId) {
      // No active project — add locally
      const newId = String(outline.length + 1);
      const label = `新章节 ${newId}`;
      setOutline(prev => [...prev, { id: newId, label, level: 0, status: 'empty', wordCount: 0 }]);
      return;
    }
    setAdding(true);
    try {
      const svc = getWritingBackendService();
      const title = `新章节 ${outline.length + 1}`;
      const section = await svc.createSection({
        project_id: activeProjectId,
        title,
        order: outline.length,
        description: '',
      });
      setOutline(prev => [...prev, { id: section.section_id, label: section.title, level: 0, status: 'empty', wordCount: 0 }]);
    } catch {
      // fallback: add locally
      const newId = `local-${Date.now()}`;
      const label = `新章节 ${outline.length + 1}`;
      setOutline(prev => [...prev, { id: newId, label, level: 0, status: 'empty', wordCount: 0 }]);
    }
    setAdding(false);
  }, [activeProjectId, outline.length]);

  const handleDelete = useCallback((id: string) => {
    setOutline(prev => prev.filter(n => n.id !== id));
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-6 py-4">
        <PageHeader
          icon={<List size={18} />}
          title={t('writing.outline.title')}
          subtitle={t('writing.outline.subtitle')}
          className="mb-0"
          actions={
            <button
              type="button"
              onClick={handleAddSection}
              disabled={adding}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 font-label text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
            >
              <Plus size={13} />
              {t('writing.outline.add_section')}
            </button>
          }
        />
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-auto px-6 py-5">
        <div className="rounded-md border border-outline-variant/60 bg-surface-lowest p-3 space-y-0.5">
          {outline.map(node => <OutlineItem key={node.id} node={node} onDelete={handleDelete} />)}
        </div>

        {/* Legend */}
        <div className="mt-4 flex items-center gap-5 px-2">
          {[
            { label: t('writing.outline.status_done'), color: 'bg-emerald-500 dark:bg-emerald-400' },
            { label: t('writing.outline.status_wip'), color: 'bg-amber-500 dark:bg-amber-400' },
            { label: t('writing.outline.status_empty'), color: 'bg-surface-highest' },
          ].map(l => (
            <span key={l.label} className="flex items-center gap-1.5 font-label text-[10px] text-foreground/45">
              <span className={cn('h-2 w-2 rounded-full', l.color)} />
              {l.label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
