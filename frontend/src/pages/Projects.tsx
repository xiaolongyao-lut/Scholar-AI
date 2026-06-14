import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Folder, Clock, Loader2, Search, X, Trash2, CheckSquare, Square, FolderOpen } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { useWriting } from '@/contexts/WritingContext';
import { EmptyState } from '@/components/common/EmptyState';
import { PageHeader } from '@/components/common/PageHeader';
import { getWritingBackendService } from '@/services/writingBackend';
import type { WritingProject } from '@/types/resources';

type ProjectStatus = 'draft' | 'active' | 'archived' | 'indexing' | 'failed';

interface ProjectSummary {
  id: string;
  title: string;
  status: ProjectStatus;
  documentCount: number;
  wordCount: number;
  updatedAt: string;
  description: string;
}

function sanitizeProjectVisibleError(value: string, fallback: string): string {
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (!normalized) return fallback;
  if (
    /(?:\/(?:api|runtime|resources|pipeline|memory)\/|https?:\/\/|[A-Za-z]:[\\/]|api[_\s-]?key|base[_\s-]?url|authorization|bearer|token|secret|env=|env_refs|capability_[a-z0-9_]*|[{}[\]"`])/i.test(normalized)
    || /^[a-z]+(?:_[a-z0-9]+){1,}$/i.test(normalized)
  ) {
    return fallback;
  }
  return normalized.length > 120 ? `${normalized.slice(0, 117)}…` : normalized;
}

export function formatProjectActionError(error: unknown, fallback = '操作失败，请稍后重试。'): string {
  if (error instanceof Error) {
    return sanitizeProjectVisibleError(error.message, fallback);
  }
  if (typeof error === 'string') {
    return sanitizeProjectVisibleError(error, fallback);
  }
  return fallback;
}

function StatusBadge({ status }: { status: ProjectStatus }) {
  const { t } = useI18n();
  const styles: Record<ProjectStatus, string> = {
    draft: 'bg-surface-high text-foreground/50 border-outline-variant',
    active: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-700/40',
    archived: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:border-amber-700/40',
    indexing: 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/15 dark:text-blue-300 dark:border-blue-700/40',
    failed: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-500/15 dark:text-red-300 dark:border-red-700/40',
  };
  const labels: Record<ProjectStatus, string> = { draft: t('projects.status_draft'), active: t('projects.status_active'), archived: t('projects.status_archived'), indexing: t('projects.status_indexing'), failed: t('projects.status_failed') };

  return (
    <span className={cn('px-2 py-0.5 text-[10px] font-label uppercase tracking-wider rounded-sm border flex items-center gap-1.5 w-fit', styles[status])}>
      {status === 'indexing' && <Loader2 size={10} className="animate-spin" />}
      {labels[status]}
    </span>
  );
}

export function Projects() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { activeProjectId, setActiveProjectId } = useWriting();
  const [searchQuery, setSearchQuery] = useState('');
  const [filterStatus, setFilterStatus] = useState<ProjectStatus | ''>('');
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newFolder, setNewFolder] = useState('');
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loadError, setLoadError] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const newProjectTitleRef = React.useRef<HTMLInputElement | null>(null);

  const batchMode = selectedIds.size > 0;

  const filtered = useMemo(() => {
    let list = projects;
    if (searchQuery) list = list.filter(p => p.title.toLowerCase().includes(searchQuery.toLowerCase()));
    if (filterStatus) list = list.filter(p => p.status === filterStatus);
    return list;
  }, [searchQuery, filterStatus, projects]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === activeProjectId) ?? null,
    [activeProjectId, projects],
  );

  const toggleSelect = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === filtered.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filtered.map(p => p.id)));
    }
  };

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0 || deleting) return;
    if (!window.confirm(`确定要删除选中的 ${selectedIds.size} 个项目吗？删除后无法恢复。`)) return;
    setDeleting(true);
    try {
      const svc = getWritingBackendService();
      for (const id of selectedIds) {
        try { await svc.deleteProject(id); } catch { /* skip */ }
      }
      setSelectedIds(new Set());
      await loadProjects();
    } finally {
      setDeleting(false);
    }
  };

  const handleHistoricalCleanup = async () => {
    if (cleaning) return;
    setCleaning(true);
    try {
      const svc = getWritingBackendService();
      const preview = await svc.cleanupHistoricalData(true);
      const duplicateCount = preview.preview.duplicate_project_count;
      const emptyMaterialCount = preview.preview.empty_material_count;

      if (duplicateCount === 0 && emptyMaterialCount === 0) {
        window.alert('未检测到可清理的历史脏数据。');
        return;
      }

      const shouldExecute = window.confirm(
        `检测到可清理内容：\n- 重复项目：${duplicateCount} 个\n- 无文本材料：${emptyMaterialCount} 条\n\n是否立即执行清理？（此操作不可恢复）`
      );
      if (!shouldExecute) return;

      const executed = await svc.cleanupHistoricalData(false);
      window.alert(
        `清理完成：\n- 已删除重复项目：${executed.deleted.duplicate_project_count} 个\n- 已删除无文本材料：${executed.deleted.empty_material_count} 条`
      );
      await loadProjects();
      setSelectedIds(new Set());
    } catch (err: unknown) {
      window.alert(`清理失败：${formatProjectActionError(err, '项目清理失败，请稍后重试。')}`);
    } finally {
      setCleaning(false);
    }
  };

  const loadProjects = useCallback(async () => {
    try {
      const svc = getWritingBackendService();
      const list = await svc.listProjects();
      setProjects(list.map((p: WritingProject) => ({
        id: p.project_id,
        title: p.title,
        status: (p.status as ProjectStatus) || 'draft',
        documentCount: 0,
        wordCount: 0,
        updatedAt: p.updated_at ? new Date(p.updated_at).toISOString().slice(0, 10) : '',
        description: p.description || '',
      })));
    } catch {
      // Keep empty state when backend list is unavailable
      setProjects([]);
    }
  }, []);

  useEffect(() => { loadProjects(); }, [loadProjects]);

  const resetCreateDialog = useCallback((): void => {
    setShowCreateDialog(false);
    setNewTitle('');
    setNewDesc('');
    setNewFolder('');
    setLoadError('');
  }, []);

  const closeCreateDialog = useCallback((): void => {
    if (creating) return;
    resetCreateDialog();
  }, [creating, resetCreateDialog]);

  useEffect(() => {
    if (!showCreateDialog) return undefined;
    const handleEscape = (event: KeyboardEvent): void => {
      if ((event.key === 'Escape' || event.key === 'Esc' || event.code === 'Escape') && !creating) {
        event.preventDefault();
        event.stopPropagation();
        resetCreateDialog();
      }
    };
    const focusTimer = window.setTimeout(() => newProjectTitleRef.current?.focus(), 0);
    document.addEventListener('keydown', handleEscape, true);
    document.addEventListener('keyup', handleEscape, true);
    window.addEventListener('keydown', handleEscape, true);
    window.addEventListener('keyup', handleEscape, true);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('keydown', handleEscape, true);
      document.removeEventListener('keyup', handleEscape, true);
      window.removeEventListener('keydown', handleEscape, true);
      window.removeEventListener('keyup', handleEscape, true);
    };
  }, [creating, resetCreateDialog, showCreateDialog]);

  const handleCreateProject = async () => {
    if (!newTitle.trim() || creating) return;
    setCreating(true);
    setLoadError('');
    try {
      const svc = getWritingBackendService();
      const created = await svc.createProject({
        title: newTitle.trim(),
        description: newDesc.trim(),
        content_type: 'general',
        source_folder: newFolder.trim(),
      });
      setShowCreateDialog(false);
      setNewTitle('');
      setNewDesc('');
      setNewFolder('');
      setActiveProjectId(created.project_id);
      await loadProjects();
      navigate('/knowledge');
    } catch (err: unknown) {
      setLoadError(formatProjectActionError(err, '项目创建失败，请稍后重试。'));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-6 py-4">
        <PageHeader
          icon={<Folder size={18} />}
          title={t('projects.title')}
          subtitle={t('projects.subtitle')}
          className="mb-0"
          actions={
            <>
              <button
                type="button"
                onClick={handleHistoricalCleanup}
                disabled={cleaning}
                className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-2.5 py-1.5 font-label text-xs text-foreground/75 transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-50"
                title="预览并清理历史脏项目/无文本材料"
                aria-label="预览并清理历史脏项目/无文本材料"
              >
                {cleaning ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                数据清理
              </button>
              {projects.length > 0 && (
                <button
                  type="button"
                  onClick={() => (batchMode ? setSelectedIds(new Set()) : toggleSelectAll())}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 font-label text-xs font-medium transition-colors',
                    batchMode
                      ? 'border-primary/40 bg-primary/10 text-primary hover:bg-primary/15'
                      : 'border-outline-variant/60 bg-surface-lowest text-foreground/65 hover:border-primary/40 hover:text-foreground',
                  )}
                >
                  {batchMode ? <CheckSquare size={13} /> : <Square size={13} />}
                  {batchMode ? `已选 ${selectedIds.size} 项` : '批量管理'}
                </button>
              )}
              {batchMode && (
                <button
                  type="button"
                  onClick={handleBatchDelete}
                  disabled={deleting}
                  className="inline-flex items-center gap-1.5 rounded-md bg-red-500 px-2.5 py-1.5 font-label text-xs font-medium text-white transition-colors hover:bg-red-600 disabled:opacity-50"
                >
                  {deleting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                  删除 ({selectedIds.size})
                </button>
              )}
              <button
                type="button"
                onClick={() => setShowCreateDialog(true)}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 font-label text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                <Plus size={13} />
                {t('projects.new_project')}
              </button>
            </>
          }
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-auto px-6 py-4">

      {/* Create Project Dialog */}
      <AnimatePresence>
        {showCreateDialog && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
            onClick={closeCreateDialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="new-project-dialog-title"
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              onClick={e => e.stopPropagation()}
              className="bg-surface-lowest border border-outline-variant rounded-xl p-6 w-full max-w-md shadow-xl"
            >
              <div className="flex items-center justify-between mb-5">
                <h2 id="new-project-dialog-title" className="font-headline text-lg font-semibold text-foreground">{t('projects.create_title')}</h2>
                <button
                  type="button"
                  onClick={closeCreateDialog}
                  title={t('common.close')}
                  aria-label={t('common.close')}
                  className="p-1.5 text-foreground/30 hover:text-foreground transition-colors"
                >
                  <X size={18} />
                </button>
              </div>
              <div className="space-y-4">
                <div>
                  <label htmlFor="new-project-title" className="font-label text-xs font-medium text-foreground/70 mb-1.5 block">{t('projects.field_title')}</label>
                  <input
                    ref={newProjectTitleRef}
                    id="new-project-title"
                    value={newTitle}
                    onChange={e => setNewTitle(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        void handleCreateProject();
                      }
                    }}
                    placeholder={t('projects.field_title_placeholder')}
                    aria-label={t('projects.field_title')}
                    className="w-full bg-surface-high rounded-lg px-3 py-2.5 border border-outline-variant/50 text-sm font-label text-foreground focus:outline-none focus:border-primary/40 transition-colors"
                    autoFocus
                  />
                </div>
                <div>
                  <label htmlFor="new-project-desc" className="font-label text-xs font-medium text-foreground/70 mb-1.5 block">{t('projects.field_desc')}</label>
                  <textarea
                    id="new-project-desc"
                    value={newDesc}
                    onChange={e => setNewDesc(e.target.value)}
                    placeholder={t('projects.field_desc_placeholder')}
                    aria-label={t('projects.field_desc')}
                    rows={3}
                    className="w-full bg-surface-high rounded-lg px-3 py-2.5 border border-outline-variant/50 text-sm font-label text-foreground focus:outline-none focus:border-primary/40 transition-colors resize-none"
                  />
                </div>
                <div>
                  <label htmlFor="new-project-folder" className="font-label text-xs font-medium text-foreground/70 mb-1.5 flex items-center gap-1.5">
                    <FolderOpen size={13} className="text-foreground/50" />
                    文献文件夹路径
                    <span className="text-foreground/30 font-normal">（可选）</span>
                  </label>
                  <input
                    id="new-project-folder"
                    value={newFolder}
                    onChange={e => setNewFolder(e.target.value)}
                    placeholder="选择或粘贴本机文献文件夹"
                    aria-label="文献文件夹路径"
                    className="w-full bg-surface-high rounded-lg px-3 py-2.5 border border-outline-variant/50 text-sm font-label text-foreground focus:outline-none focus:border-primary/40 transition-colors font-mono"
                  />
                  <p className="text-[11px] text-foreground/40 mt-1 font-label leading-relaxed">
                    设置后，切片数据将保存在该文件夹的 <code className="bg-surface-high px-1 rounded">.scholarai/</code> 子目录中，与文献文件放在一起
                  </p>
                </div>
                {loadError && <p className="text-red-500 text-xs font-label">{loadError}</p>}
                <div className="flex justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={closeCreateDialog}
                    disabled={creating}
                    className="px-4 py-2 text-sm font-label font-medium text-foreground/50 hover:text-foreground transition-colors"
                  >
                    {t('common.cancel')}
                  </button>
                  <button
                    type="button"
                    onClick={handleCreateProject}
                    disabled={!newTitle.trim() || creating}
                    className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-label font-medium shadow-sm hover:bg-primary/90 disabled:opacity-40 transition-all"
                  >
                    {creating && <Loader2 size={14} className="animate-spin" />}
                    {t('projects.create_btn')}
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Search & Filter bar */}
      <div className="flex items-center gap-3 mb-6">
        <div className="flex-1 flex items-center gap-2 bg-surface-lowest rounded-lg px-3 py-2 border border-outline-variant/50 focus-within:border-primary/40 transition-colors">
          <Search size={16} className="text-foreground/30" />
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder={t('projects.search_placeholder')}
            aria-label={t('projects.search_placeholder')}
            className="flex-1 bg-transparent text-sm font-label text-foreground placeholder:text-foreground/30 focus:outline-none"
          />
        </div>
        {selectedProject && (
          <button
            type="button"
            onClick={() => {
              setActiveProjectId('');
            }}
            className="inline-flex max-w-[260px] items-center gap-1.5 rounded-lg border border-primary/25 bg-primary/8 px-3 py-2 text-xs font-label text-primary transition-colors hover:bg-primary/12"
            title={`当前激活项目：${selectedProject.title}`}
          >
            <Folder size={13} />
            <span className="shrink-0 text-primary/70">当前</span>
            <span className="truncate">{selectedProject.title}</span>
            <X size={13} />
          </button>
        )}
        <div className="flex gap-1 p-1 bg-surface-high rounded-lg border border-outline-variant/30">
          {[{ key: '', label: t('projects.filter_all') }, { key: 'active', label: t('projects.filter_active') }, { key: 'draft', label: t('projects.filter_draft') }, { key: 'archived', label: t('projects.filter_archived') }].map(f => (
            <button
              type="button"
              key={f.key}
              onClick={() => setFilterStatus(f.key as ProjectStatus | '')}
              className={cn(
                'px-3 py-1.5 text-xs font-label font-medium rounded transition-all',
                filterStatus === f.key ? 'bg-primary text-primary-foreground shadow-sm' : 'text-foreground/40 hover:text-foreground'
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Project grid */}
      {filtered.length === 0 ? (
        <EmptyState
          title={t('projects.empty_title')}
          description={t('projects.empty_description')}
          icon={<Folder size={40} />}
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          <AnimatePresence>
            {filtered.map((project, i) => (
              <motion.div
                key={project.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95 }}
                transition={{ duration: 0.2, delay: i * 0.05 }}
                onClick={() => { if (!batchMode) { setActiveProjectId(project.id); navigate('/knowledge'); } else { toggleSelect(project.id, { stopPropagation: () => {} } as React.MouseEvent); } }}
                className={cn(
                  'glass-card p-5 rounded-lg group cursor-pointer transition-all relative',
                  selectedIds.has(project.id) ? 'border-primary/50 bg-primary/3 ring-1 ring-primary/20' : 'hover:border-primary/30'
                )}
              >
                {batchMode && (
                  <div
                    onClick={e => toggleSelect(project.id, e)}
                    className="absolute top-3 right-3 z-10"
                  >
                    {selectedIds.has(project.id)
                      ? <CheckSquare size={18} className="text-primary" />
                      : <Square size={18} className="text-foreground/30 hover:text-foreground/60 transition-colors" />}
                  </div>
                )}
                <div className="flex justify-between items-start mb-3">
                  <div className="h-10 w-10 bg-primary/8 rounded-lg flex items-center justify-center text-primary group-hover:bg-primary/12 transition-all">
                    <Folder size={20} />
                  </div>
                  <StatusBadge status={project.status} />
                </div>
                <h3 className="font-headline font-semibold text-base mb-1.5 text-foreground group-hover:text-primary transition-colors line-clamp-1">
                  {project.title}
                </h3>
                <p className="font-body text-xs text-foreground/50 line-clamp-2 leading-relaxed min-h-[2.5rem]">
                  {project.description}
                </p>
                <div className="mt-4 flex items-center justify-between text-[10px] border-t border-outline-variant/30 pt-3">
                  <span className="font-label text-foreground/40 flex items-center gap-1">
                    <Clock size={10} /> {project.updatedAt}
                  </span>
                  <div className="flex items-center gap-3 font-label text-foreground/40 tabular-nums">
                    <span>{project.documentCount} 篇</span>
                    <span>{(project.wordCount / 1000).toFixed(1)} 千字</span>
                  </div>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}
      </div>
    </div>
  );
}
