import React, { useEffect, useState, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, FileEdit, FolderKanban, BookOpen, Settings, BarChart3, Layers, Keyboard, Activity, FileText, List, BookMarked, Image, ShieldCheck, Database } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';

interface CommandItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  action: () => void;
  group: string;
  keywords?: string;
}

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const { t } = useI18n();

  const groupNav = t('cmd.group_nav');
  const groupWriting = t('cmd.group_writing');

  const items: CommandItem[] = [
    { id: 'workbench', label: t('nav.workbench'), icon: <BookOpen size={16} />, action: () => navigate('/'), group: groupNav, keywords: 'research workbench 研读' },
    { id: 'overview', label: t('nav.side_writing_overview'), icon: <BarChart3 size={16} />, action: () => navigate('/writing'), group: groupWriting, keywords: 'overview 总览' },
    { id: 'draft', label: t('nav.side_draft_studio'), icon: <FileEdit size={16} />, action: () => navigate('/writing/draft'), group: groupWriting, keywords: 'draft writing 手稿 写作' },
    { id: 'outline', label: t('nav.side_outline'), icon: <List size={16} />, action: () => navigate('/writing/outline'), group: groupWriting, keywords: 'outline 大纲' },
    { id: 'sources', label: t('nav.side_sources'), icon: <BookMarked size={16} />, action: () => navigate('/writing/sources'), group: groupWriting, keywords: 'sources citations 引用 来源' },
    { id: 'figures', label: t('nav.side_figures'), icon: <Image size={16} />, action: () => navigate('/writing/figures'), group: groupWriting, keywords: 'figures tables 图表' },
    { id: 'reviewer', label: t('nav.side_submission'), icon: <ShieldCheck size={16} />, action: () => navigate('/writing/reviewer'), group: groupWriting, keywords: 'review submission 审稿 投稿' },
    { id: 'knowledge', label: t('nav.knowledge'), icon: <Database size={16} />, action: () => navigate('/knowledge'), group: groupNav, keywords: 'knowledge 知识' },
    { id: 'projects', label: t('nav.projects'), icon: <FolderKanban size={16} />, action: () => navigate('/projects'), group: groupNav, keywords: 'projects 项目' },
    { id: 'volume', label: t('nav.volume'), icon: <FileText size={16} />, action: () => navigate('/volume'), group: groupNav, keywords: 'volume 卷次 分析' },
    { id: 'jobs', label: t('nav.jobs'), icon: <Activity size={16} />, action: () => navigate('/jobs'), group: groupNav, keywords: 'jobs tasks 任务' },
    { id: 'settings', label: t('nav.settings'), icon: <Settings size={16} />, action: () => navigate('/settings'), group: groupNav, keywords: 'settings 设置' },
  ];

  const filtered = query.trim()
    ? items.filter(i => {
        const q = query.toLowerCase();
        return i.label.toLowerCase().includes(q) || (i.keywords?.toLowerCase().includes(q));
      })
    : items;

  const grouped = filtered.reduce<Record<string, CommandItem[]>>((acc, item) => {
    (acc[item.group] ??= []).push(item);
    return acc;
  }, {});

  const flatFiltered = Object.values(grouped).flat();

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      setOpen(prev => !prev);
      setQuery('');
      setSelectedIndex(0);
    }
    if (!open) return;
    if (e.key === 'Escape') { setOpen(false); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); setSelectedIndex(i => Math.min(i + 1, flatFiltered.length - 1)); }
    if (e.key === 'ArrowUp') { e.preventDefault(); setSelectedIndex(i => Math.max(i - 1, 0)); }
    if (e.key === 'Enter' && flatFiltered[selectedIndex]) {
      flatFiltered[selectedIndex].action();
      setOpen(false);
    }
  }, [open, flatFiltered, selectedIndex]);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  useEffect(() => { setSelectedIndex(0); }, [query]);

  let runningIndex = 0;

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.12 }}
          className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh] bg-black/30 backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: -10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: -10 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            className="w-full max-w-lg bg-surface-lowest rounded-xl shadow-2xl border border-outline-variant overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 px-4 py-3 border-b border-outline-variant">
              <Search size={18} className="text-foreground/30" />
              <input
                ref={inputRef}
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder={t('cmd.placeholder')}
                className="flex-1 bg-transparent text-sm font-label text-foreground placeholder:text-foreground/30 focus:outline-none"
              />
              <kbd className="hidden sm:flex items-center gap-1 px-1.5 py-0.5 bg-surface-high rounded text-[10px] font-label text-foreground/40 border border-outline-variant">
                ESC
              </kbd>
            </div>
            <div className="max-h-72 overflow-y-auto custom-scrollbar py-2">
              {flatFiltered.length === 0 && (
                <div className="px-4 py-8 text-center text-sm text-foreground/40 font-label">
                  {t('cmd.empty')}
                </div>
              )}
              {Object.entries(grouped).map(([group, groupItems]) => (
                <div key={group}>
                  <div className="px-4 py-1.5 text-[10px] font-label font-medium text-foreground/30 uppercase tracking-wider">{group}</div>
                  {groupItems.map(item => {
                    const idx = runningIndex++;
                    return (
                      <button
                        key={item.id}
                        className={cn(
                          'w-full flex items-center gap-3 px-4 py-2.5 text-sm font-label transition-colors',
                          idx === selectedIndex ? 'bg-primary/8 text-primary' : 'text-foreground/70 hover:bg-surface-high'
                        )}
                        onClick={() => { item.action(); setOpen(false); }}
                        onMouseEnter={() => setSelectedIndex(idx)}
                      >
                        <span className="text-foreground/40">{item.icon}</span>
                        <span>{item.label}</span>
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between px-4 py-2.5 border-t border-outline-variant bg-surface-low/50">
              <div className="flex items-center gap-4 text-[10px] font-label text-foreground/30">
                <span className="flex items-center gap-1"><Keyboard size={10} /> {t('cmd.nav_hint')}</span>
                <span>{t('cmd.confirm_hint')}</span>
                <span>{t('cmd.close_hint')}</span>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  );
}
