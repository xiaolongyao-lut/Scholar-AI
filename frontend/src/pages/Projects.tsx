import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Folder, Clock, CheckCircle2, AlertCircle, Loader2, ChevronRight, Search, Upload, X, Trash2, CheckSquare, Square } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { useWriting } from '@/contexts/WritingContext';
import { EmptyState } from '@/components/common/EmptyState';
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

function StatusBadge({ status }: { status: ProjectStatus }) {
  const { t } = useI18n();
  const styles: Record<ProjectStatus, string> = {
    draft: 'bg-surface-high text-foreground/50 border-outline-variant',
    active: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    archived: 'bg-amber-50 text-amber-700 border-amber-200',
    indexing: 'bg-blue-50 text-blue-700 border-blue-200',
    failed: 'bg-red-50 text-red-700 border-red-200',
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
  const { setActiveProjectId } = useWriting();
  const [searchQuery, setSearchQuery] = useState('');
  const [filterStatus, setFilterStatus] = useState<ProjectStatus | ''>('');
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loadError, setLoadError] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [cleaning, setCleaning] = useState(false);

  const batchMode = selectedIds.size > 0;

  const filtered = useMemo(() => {
    let list = projects;
    if (searchQuery) list = list.filter(p => p.title.toLowerCase().includes(searchQuery.toLowerCase()));
    if (filterStatus) list = list.filter(p => p.status === filterStatus);
    return list;
  }, [searchQuery, filterStatus, projects]);

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
      window.alert(`清理失败：${err instanceof Error ? err.message : String(err)}`);
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
      });
      setShowCreateDialog(false);
      setNewTitle('');
      setNewDesc('');
      setActiveProjectId(created.project_id);
      await loadProjects();
      navigate('/writing/draft');
    } catch (err: unknown) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="p-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex justify-between items-start mb-8">
        <div>
          <h1 className="font-display text-2xl font-semibold text-foreground">
            {t('projects.title')}
          </h1>
          <p className="font-label text-sm text-foreground/50 mt-1">
            {t('projects.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleHistoricalCleanup}
            disabled={cleaning}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg font-label text-sm font-medium border border-outline-variant/50 text-foreground/70 hover:text-foreground hover:border-outline-variant disabled:opacity-50 transition-all"
            title="预览并清理历史脏项目/无文本材料"
            aria-label="预览并清理历史脏项目/无文本材料"
          >
            {cleaning ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
            数据清理
          </button>
          {projects.length > 0 && (
            <button
              type="button"
              onClick={() => batchMode ? setSelectedIds(new Set()) : toggleSelectAll()}
              className={cn(
                'flex items-center gap-2 px-4 py-2.5 rounded-lg font-label text-sm font-medium transition-all border',
                batchMode
                  ? 'border-primary/30 text-primary bg-primary/5 hover:bg-primary/10'
                  : 'border-outline-variant/50 text-foreground/50 hover:text-foreground hover:border-outline-variant'
              )}
            >
              {batchMode ? <CheckSquare size={16} /> : <Square size={16} />}
              {batchMode ? `已选 ${selectedIds.size} 项` : '批量管理'}
            </button>
          )}
          {batchMode && (
            <button
              type="button"
              onClick={handleBatchDelete}
              disabled={deleting}
              className="flex items-center gap-2 bg-red-500 text-white px-4 py-2.5 rounded-lg font-label text-sm font-medium shadow-sm hover:bg-red-600 disabled:opacity-50 transition-all"
            >
              {deleting ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
              删除 ({selectedIds.size})
            </button>
          )}
          <button
            type="button"
            onClick={() => setShowCreateDialog(true)}
            className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2.5 rounded-lg font-label text-sm font-medium shadow-md shadow-primary/20 hover:shadow-lg hover:bg-primary/90 active:scale-[0.98] transition-all"
          >
            <Plus size={16} />
            {t('projects.new_project')}
          </button>
        </div>
      </div>

      {/* Create Project Dialog */}
      <AnimatePresence>
        {showCreateDialog && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
            onClick={() => !creating && setShowCreateDialog(false)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              onClick={e => e.stopPropagation()}
              className="bg-surface-lowest border border-outline-variant rounded-xl p-6 w-full max-w-md shadow-xl"
            >
              <div className="flex items-center justify-between mb-5">
                <h2 className="font-headline text-lg font-semibold text-foreground">{t('projects.create_title')}</h2>
                <button
                  type="button"
                  onClick={() => !creating && setShowCreateDialog(false)}
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
                    id="new-project-title"
                    value={newTitle}
                    onChange={e => setNewTitle(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleCreateProject()}
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
                {loadError && <p className="text-red-500 text-xs font-label">{loadError}</p>}
                <div className="flex justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => { setShowCreateDialog(false); setNewTitle(''); setNewDesc(''); setLoadError(''); }}
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
                onClick={() => { if (!batchMode) { setActiveProjectId(project.id); navigate('/writing/draft'); } else { toggleSelect(project.id, { stopPropagation: () => {} } as React.MouseEvent); } }}
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
                    <span>{project.documentCount} docs</span>
                    <span>{(project.wordCount / 1000).toFixed(1)}k words</span>
                  </div>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
