import React, { useState, useCallback, useEffect, useRef } from 'react';
import { ArrowDown, ArrowUp, List, Plus, GripVertical, ChevronRight, ChevronDown, MoreHorizontal, Trash2, Loader2, Inbox, RefreshCw, Sparkles, Wand2, Save, Square } from 'lucide-react';
import { motion } from 'framer-motion';
import axios from 'axios';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { PageHeader } from '@/components/common/PageHeader';
import { useWriting } from '@/contexts/WritingContext';
import { formatWritingRuntimeError } from '@/components/writing/writingRuntimeDisplay';
import { getWritingBackendService } from '@/services/writingBackend';
import { EmptyState } from '@/components/common/EmptyState';
import type { OutlineItemResource, WritingDraft, WritingSection } from '@/types/resources';

interface OutlineNode {
  id: string;
  label: string;
  description: string;
  level: number;
  status: 'done' | 'wip' | 'empty';
  wordCount: number;
  sourceItem?: OutlineItemResource;
  children?: OutlineNode[];
}

function isRequestCanceled(error: unknown): boolean {
  return (error instanceof DOMException && error.name === 'AbortError')
    || (axios.isAxiosError(error) && error.code === 'ERR_CANCELED');
}

function OutlineItem({
  node,
  onDelete,
  onPatch,
  onMove,
  canMoveUp = false,
  canMoveDown = false,
}: {
  node: OutlineNode;
  onDelete?: (id: string) => void;
  onPatch?: (id: string, patch: Partial<Pick<OutlineNode, 'label' | 'description'>>) => void;
  onMove?: (id: string, direction: 'up' | 'down') => void;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
}) {
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
        <div className="min-w-0 flex-1 space-y-1">
          <input
            value={node.label}
            onChange={(event) => onPatch?.(node.id, { label: event.target.value })}
            aria-label={`章节标题：${node.label}`}
            className="w-full rounded-md border border-transparent bg-transparent px-2 py-1 font-label text-sm font-medium text-foreground outline-none transition-colors hover:border-outline-variant/50 focus:border-primary/50 focus:bg-surface-lowest"
          />
          <input
            value={node.description}
            onChange={(event) => onPatch?.(node.id, { description: event.target.value })}
            aria-label={`章节说明：${node.label}`}
            placeholder="章节说明"
            className="w-full rounded-md border border-transparent bg-transparent px-2 py-1 text-xs text-foreground/55 outline-none transition-colors placeholder:text-foreground/25 hover:border-outline-variant/50 focus:border-primary/50 focus:bg-surface-lowest"
          />
        </div>
        <span className="font-label text-[10px] text-foreground/30 tabular-nums">{node.wordCount > 0 ? `${node.wordCount} ${t('common.unit_chars')}` : '—'}</span>
        <button
          type="button"
          onClick={() => onMove?.(node.id, 'up')}
          disabled={!canMoveUp}
          aria-label={`上移 ${node.label}`}
          title={`上移 ${node.label}`}
          className="rounded p-1 text-foreground/30 transition-colors hover:bg-surface-high hover:text-foreground/60 disabled:cursor-not-allowed disabled:opacity-25"
        >
          <ArrowUp size={13} />
        </button>
        <button
          type="button"
          onClick={() => onMove?.(node.id, 'down')}
          disabled={!canMoveDown}
          aria-label={`下移 ${node.label}`}
          title={`下移 ${node.label}`}
          className="rounded p-1 text-foreground/30 transition-colors hover:bg-surface-high hover:text-foreground/60 disabled:cursor-not-allowed disabled:opacity-25"
        >
          <ArrowDown size={13} />
        </button>
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
          {node.children.map((child, index) => (
            <OutlineItem
              key={child.id}
              node={child}
              onDelete={onDelete}
              onPatch={onPatch}
              onMove={onMove}
              canMoveUp={index > 0}
              canMoveDown={index < (node.children?.length ?? 0) - 1}
            />
          ))}
        </motion.div>
      )}
    </div>
  );
}

export function OutlineManager() {
  const { t } = useI18n();
  const { activeProjectId, markProjectDataChanged, setActiveSectionId } = useWriting();

  const [outline, setOutline] = useState<OutlineNode[]>([]);
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [generatorOpen, setGeneratorOpen] = useState(false);
  const [generateTopic, setGenerateTopic] = useState('');
  const [generateFocusAreas, setGenerateFocusAreas] = useState('');
  const [generateTargetLength, setGenerateTargetLength] = useState('6000');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const generateAbortControllerRef = useRef<AbortController | null>(null);
  const generateStopRequestedRef = useRef(false);

  const loadOutline = useCallback(async () => {
    if (!activeProjectId) {
      setOutline([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const svc = getWritingBackendService();
      const [outlinePayload, drafts] = await Promise.all([
        svc.getOutline(activeProjectId),
        svc.listDrafts(activeProjectId),
      ]);
      setOutline(outlineItemsToOutline(outlinePayload.items ?? [], drafts));
      setDirty(false);
    } catch (err) {
      setError(formatWritingRuntimeError(err, '大纲加载失败，请稍后重试。'));
      setOutline([]);
    } finally {
      setLoading(false);
    }
  }, [activeProjectId]);

  useEffect(() => {
    void loadOutline();
  }, [loadOutline]);

  useEffect(() => {
    return () => {
      generateAbortControllerRef.current?.abort();
    };
  }, []);

  const handleAddSection = useCallback(async () => {
    if (!activeProjectId) {
      // No active project — add locally
      const newId = String(outline.length + 1);
      const label = `新章节 ${newId}`;
      setOutline(prev => [...prev, { id: newId, label, description: '', level: 0, status: 'empty', wordCount: 0 }]);
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
      setActiveSectionId(section.section_id);
      markProjectDataChanged();
      await loadOutline();
    } catch {
      // fallback: add locally
      const newId = `local-${Date.now()}`;
      const label = `新章节 ${outline.length + 1}`;
      setOutline(prev => [...prev, { id: newId, label, description: '', level: 0, status: 'empty', wordCount: 0 }]);
      setDirty(true);
    }
    setAdding(false);
  }, [activeProjectId, loadOutline, markProjectDataChanged, outline.length, setActiveSectionId]);

  const handleGenerateOutline = useCallback(async () => {
    if (!activeProjectId || generating) {
      return;
    }

    const abortController = new AbortController();
    generateAbortControllerRef.current = abortController;
    generateStopRequestedRef.current = false;
    const targetLength = parseTargetLength(generateTargetLength);
    const focusAreas = parseFocusAreas(generateFocusAreas);
    const topic = generateTopic.trim() || '当前项目研究综述';

    setGenerating(true);
    setError(null);
    setNotice(null);
    try {
      await getWritingBackendService().generateOutline({
        project_id: activeProjectId,
        topic,
        content_type: 'academic',
        target_length: targetLength,
        focus_areas: focusAreas,
        existing_materials: [],
      }, { signal: abortController.signal });
      markProjectDataChanged();
      await loadOutline();
      setNotice('已生成并写入大纲');
      setGeneratorOpen(false);
    } catch (err) {
      if (isRequestCanceled(err)) {
      if (generateStopRequestedRef.current) {
        setNotice('已停止生成大纲');
      }
      return;
    }
      setError(formatWritingRuntimeError(err, '大纲生成失败，请稍后重试。'));
    } finally {
      if (generateAbortControllerRef.current === abortController) {
        generateAbortControllerRef.current = null;
        setGenerating(false);
      }
    }
  }, [
    activeProjectId,
    generateFocusAreas,
    generateTargetLength,
    generateTopic,
    generating,
    loadOutline,
    markProjectDataChanged,
  ]);

  const stopGenerateOutline = useCallback(() => {
    const abortController = generateAbortControllerRef.current;
    if (!abortController) return;
    generateStopRequestedRef.current = true;
    abortController.abort();
    setGenerating(false);
    setNotice('已停止生成大纲');
  }, []);

  const handleDelete = useCallback(async (id: string) => {
    if (activeProjectId && !id.startsWith('local-')) {
      try {
        await getWritingBackendService().deleteOutlineItem(id);
      } catch (err) {
        setError(formatWritingRuntimeError(err, '章节删除失败，请稍后重试。'));
        return;
      }
    }
    setOutline(prev => removeOutlineNode(prev, id));
    setDirty(false);
    markProjectDataChanged();
    setNotice('已删除章节');
  }, [activeProjectId, markProjectDataChanged]);

  const handlePatchNode = useCallback((id: string, patch: Partial<Pick<OutlineNode, 'label' | 'description'>>) => {
    setOutline(prev => patchOutlineNode(prev, id, patch));
    setDirty(true);
  }, []);

  const handleMoveNode = useCallback((id: string, direction: 'up' | 'down') => {
    setOutline(prev => moveOutlineNode(prev, id, direction));
    setDirty(true);
  }, []);

  const handleSaveOutline = useCallback(async () => {
    if (!activeProjectId || saving) {
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const svc = getWritingBackendService();
      const preparedOutline = await ensurePersistedOutlineNodes(svc, outline, activeProjectId);
      const items = flattenOutlineNodes(preparedOutline, activeProjectId);
      await svc.updateOutline(activeProjectId, items);
      const sectionUpdates = extractSectionUpdates(preparedOutline);
      await Promise.all(sectionUpdates.map((item) => (
        svc.updateSection(item.sectionId, {
          title: item.title,
          description: item.description,
          order: item.order,
        })
      )));
      const [latestOutline, drafts] = await Promise.all([
        svc.getOutline(activeProjectId),
        svc.listDrafts(activeProjectId),
      ]);
      setOutline(outlineItemsToOutline(latestOutline.items ?? [], drafts));
      setNotice('大纲已保存');
      setDirty(false);
      markProjectDataChanged();
    } catch (err) {
      setError(formatWritingRuntimeError(err, '大纲保存失败，请稍后重试。'));
    } finally {
      setSaving(false);
    }
  }, [activeProjectId, markProjectDataChanged, outline, saving]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-6 py-4">
        <PageHeader
          icon={<List size={18} />}
          title={t('writing.outline.title')}
          subtitle={t('writing.outline.subtitle')}
          className="mb-0"
          actions={
            <>
              <button
                type="button"
                onClick={() => setGeneratorOpen(open => !open)}
                disabled={!activeProjectId}
                className="inline-flex items-center gap-1.5 rounded-md border border-primary/35 bg-primary/10 px-3 py-1.5 font-label text-xs font-medium text-primary transition-colors hover:bg-primary/15 disabled:cursor-not-allowed disabled:border-outline-variant/60 disabled:bg-surface-lowest disabled:text-foreground/35"
              >
                <Sparkles size={13} />
                生成大纲
              </button>
              <button
                type="button"
                onClick={handleAddSection}
                disabled={adding}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 font-label text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
              >
                <Plus size={13} />
                {t('writing.outline.add_section')}
              </button>
              <button
                type="button"
                onClick={() => void handleSaveOutline()}
                disabled={!activeProjectId || !dirty || saving}
                className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-1.5 font-label text-xs font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                保存大纲
              </button>
              <button
                type="button"
                onClick={() => void loadOutline()}
                disabled={loading}
                className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-1.5 font-label text-xs font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:opacity-60"
              >
                {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                刷新
              </button>
            </>
          }
        />
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-auto px-6 py-5">
        {generatorOpen && activeProjectId ? (
          <div className="mb-4 rounded-md border border-outline-variant/60 bg-surface-lowest p-4">
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1.5fr)_minmax(180px,0.8fr)_120px_auto]">
              <label className="flex min-w-0 flex-col gap-1.5">
                <span className="font-label text-[11px] font-medium uppercase tracking-wide text-foreground/45">主题</span>
                <input
                  value={generateTopic}
                  onChange={event => setGenerateTopic(event.target.value)}
                  placeholder="当前项目研究综述"
                  className="h-9 rounded-md border border-outline-variant/60 bg-background px-3 text-sm text-foreground outline-none transition-colors focus:border-primary/60"
                />
              </label>
              <label className="flex min-w-0 flex-col gap-1.5">
                <span className="font-label text-[11px] font-medium uppercase tracking-wide text-foreground/45">重点</span>
                <input
                  value={generateFocusAreas}
                  onChange={event => setGenerateFocusAreas(event.target.value)}
                  placeholder="机制, 方法, 证据"
                  className="h-9 rounded-md border border-outline-variant/60 bg-background px-3 text-sm text-foreground outline-none transition-colors focus:border-primary/60"
                />
              </label>
              <label className="flex min-w-0 flex-col gap-1.5">
                <span className="font-label text-[11px] font-medium uppercase tracking-wide text-foreground/45">字数</span>
                <input
                  value={generateTargetLength}
                  inputMode="numeric"
                  onChange={event => setGenerateTargetLength(event.target.value)}
                  className="h-9 rounded-md border border-outline-variant/60 bg-background px-3 text-sm text-foreground outline-none transition-colors focus:border-primary/60"
                />
              </label>
              <div className="flex items-end gap-2">
                <button
                  type="button"
                  onClick={() => generating ? stopGenerateOutline() : void handleGenerateOutline()}
                  className={cn(
                    'inline-flex h-9 items-center gap-1.5 rounded-md px-3 font-label text-xs font-medium text-primary-foreground transition-colors',
                    generating ? 'bg-red-600 hover:bg-red-700' : 'bg-primary hover:bg-primary/90',
                  )}
                >
                  {generating ? <Square size={13} /> : <Wand2 size={13} />}
                  {generating ? '停止' : '写入'}
                </button>
              </div>
            </div>
          </div>
        ) : null}
        {notice ? (
          <div className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300">
            {notice}
          </div>
        ) : null}
        {error ? (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
            {error}
          </div>
        ) : null}
        {loading ? (
          <div className="flex items-center justify-center gap-2 rounded-md border border-outline-variant/60 bg-surface-lowest px-4 py-10 text-sm text-foreground/50">
            <Loader2 size={16} className="animate-spin" />
            正在加载提纲
          </div>
        ) : outline.length === 0 ? (
          <EmptyState
            title={activeProjectId ? '还没有章节' : '未激活项目'}
            description={activeProjectId ? '添加章节后，写作工作台会按这些章节组织手稿。' : '先在写作工作台选择或创建项目，再管理提纲。'}
            icon={<Inbox size={40} />}
            action={
              <button
                type="button"
                onClick={handleAddSection}
                disabled={adding}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
              >
                {adding ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                添加章节
              </button>
            }
          />
        ) : (
          <div className="rounded-md border border-outline-variant/60 bg-surface-lowest p-3 space-y-0.5">
            {outline.map((node, index) => (
              <OutlineItem
                key={node.id}
                node={node}
                onDelete={(id) => void handleDelete(id)}
                onPatch={handlePatchNode}
                onMove={handleMoveNode}
                canMoveUp={index > 0}
                canMoveDown={index < outline.length - 1}
              />
            ))}
          </div>
        )}

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

function sectionsToOutline(sections: WritingSection[], drafts: WritingDraft[]): OutlineNode[] {
  const draftBySection = new Map<string, WritingDraft[]>();
  for (const draft of drafts) {
    if (!draft.section_id) continue;
    const existing = draftBySection.get(draft.section_id) ?? [];
    existing.push(draft);
    draftBySection.set(draft.section_id, existing);
  }

  return [...sections]
    .sort((a, b) => a.order - b.order)
    .map((section) => {
      const sectionDrafts = draftBySection.get(section.section_id) ?? [];
      const wordCount = sectionDrafts.reduce((sum, draft) => sum + draft.content.length, 0);
      return {
        id: section.section_id,
        label: section.title,
        description: section.description,
        level: 0,
        status: wordCount > 800 ? 'done' : wordCount > 0 ? 'wip' : 'empty',
        wordCount,
      };
    });
}

function outlineItemsToOutline(items: OutlineItemResource[], drafts: WritingDraft[]): OutlineNode[] {
  const draftBySection = mapDraftsBySection(drafts);
  const nodesById = new Map<string, OutlineNode>();
  const rootNodes: OutlineNode[] = [];
  const normalized = [...items].sort((a, b) => a.order - b.order);

  for (const item of normalized) {
    const nodeId = item.section_id || item.item_id;
    const sectionDrafts = item.section_id ? draftBySection.get(item.section_id) ?? [] : [];
    const wordCount = sectionDrafts.reduce((sum, draft) => sum + draft.content.length, 0);
    nodesById.set(nodeId, {
      id: nodeId,
      label: item.title,
      description: item.description,
      level: Math.max(0, item.level - 1),
      status: wordCount > 800 ? 'done' : wordCount > 0 ? 'wip' : 'empty',
      wordCount,
      sourceItem: item,
    });
  }

  for (const item of normalized) {
    const nodeId = item.section_id || item.item_id;
    const node = nodesById.get(nodeId);
    if (!node) {
      continue;
    }
    const parentId = item.parent_id ?? null;
    const parent = parentId ? nodesById.get(parentId) : undefined;
    if (parent) {
      parent.children = [...(parent.children ?? []), node];
    } else {
      rootNodes.push(node);
    }
  }

  return rootNodes;
}

function patchOutlineNode(
  nodes: OutlineNode[],
  id: string,
  patch: Partial<Pick<OutlineNode, 'label' | 'description'>>,
): OutlineNode[] {
  return nodes.map((node) => {
    if (node.id === id) {
      return { ...node, ...patch };
    }
    if (node.children && node.children.length > 0) {
      return { ...node, children: patchOutlineNode(node.children, id, patch) };
    }
    return node;
  });
}

function moveOutlineNode(
  nodes: OutlineNode[],
  id: string,
  direction: 'up' | 'down',
): OutlineNode[] {
  const currentIndex = nodes.findIndex((node) => node.id === id);
  if (currentIndex >= 0) {
    const targetIndex = direction === 'up' ? currentIndex - 1 : currentIndex + 1;
    if (targetIndex < 0 || targetIndex >= nodes.length) {
      return nodes;
    }
    const next = [...nodes];
    const [moved] = next.splice(currentIndex, 1);
    next.splice(targetIndex, 0, moved);
    return next;
  }
  return nodes.map((node) => {
    if (node.children && node.children.length > 0) {
      return { ...node, children: moveOutlineNode(node.children, id, direction) };
    }
    return node;
  });
}

function removeOutlineNode(nodes: OutlineNode[], id: string): OutlineNode[] {
  return nodes
    .filter((node) => node.id !== id)
    .map((node) => (
      node.children && node.children.length > 0
        ? { ...node, children: removeOutlineNode(node.children, id) }
        : node
    ));
}

type WritingBackendServiceInstance = ReturnType<typeof getWritingBackendService>;

async function ensurePersistedOutlineNodes(
  svc: WritingBackendServiceInstance,
  nodes: OutlineNode[],
  projectId: string,
): Promise<OutlineNode[]> {
  if (!projectId.trim()) {
    throw new Error('projectId is required before saving outline nodes');
  }

  const visit = async (
    items: OutlineNode[],
    parentId: string | null,
    level: number,
  ): Promise<OutlineNode[]> => {
    const persisted: OutlineNode[] = [];
    for (let index = 0; index < items.length; index += 1) {
      const node = items[index];
      const title = node.label.trim() || '未命名章节';
      const description = node.description.trim();
      const sourceItem = node.sourceItem ?? sectionToOutlineItemResource(
        await svc.createSection({
          project_id: projectId,
          title,
          order: index,
          description,
        }),
        level,
        parentId,
      );
      const childParentId = sourceItem.section_id ?? sourceItem.item_id;
      persisted.push({
        ...node,
        label: title,
        description,
        level: Math.max(0, level - 1),
        sourceItem,
        children: node.children && node.children.length > 0
          ? await visit(node.children, childParentId, level + 1)
          : undefined,
      });
    }
    return persisted;
  };

  return visit(nodes, null, 1);
}

function sectionToOutlineItemResource(
  section: WritingSection,
  level: number,
  parentId: string | null,
): OutlineItemResource {
  const sectionId = String(section.section_id);
  return {
    item_id: sectionId,
    project_id: String(section.project_id),
    parent_id: parentId,
    title: String(section.title),
    level: Math.min(6, Math.max(1, level)),
    order: Number.isFinite(section.order) ? section.order : 0,
    description: String(section.description ?? ''),
    section_id: sectionId,
    created_at: String(section.created_at),
    updated_at: String(section.updated_at),
  };
}

function flattenOutlineNodes(
  nodes: OutlineNode[],
  projectId: string,
): OutlineItemResource[] {
  const now = new Date().toISOString();
  const flattened: OutlineItemResource[] = [];
  const visit = (items: OutlineNode[], parentId: string | null, level: number) => {
    items.forEach((node, index) => {
      if (!node.sourceItem) {
        return;
      }
      const title = node.label.trim() || node.sourceItem.title || '未命名章节';
      const itemId = node.sourceItem.item_id || node.id;
      const sectionId = node.sourceItem.section_id ?? node.id;
      flattened.push({
        ...node.sourceItem,
        item_id: itemId,
        project_id: node.sourceItem.project_id || projectId,
        parent_id: parentId,
        section_id: sectionId,
        title,
        level: Math.min(6, Math.max(1, level)),
        description: node.description.trim(),
        order: index,
        updated_at: now,
      });
      visit(node.children ?? [], sectionId ?? itemId, level + 1);
    });
  };
  visit(nodes, null, 1);
  return flattened;
}

function extractSectionUpdates(nodes: OutlineNode[]): Array<{
  sectionId: string;
  title: string;
  description: string;
  order: number;
}> {
  const updates: Array<{
    sectionId: string;
    title: string;
    description: string;
    order: number;
  }> = [];
  const visit = (items: OutlineNode[]) => {
    items.forEach((node, index) => {
      if (node.sourceItem?.section_id) {
        updates.push({
          sectionId: node.sourceItem.section_id,
          title: node.label.trim() || '未命名章节',
          description: node.description.trim(),
          order: index,
        });
      }
      if (node.children && node.children.length > 0) {
        visit(node.children);
      }
    });
  };
  visit(nodes);
  return updates;
}

function mapDraftsBySection(drafts: WritingDraft[]): Map<string, WritingDraft[]> {
  const draftBySection = new Map<string, WritingDraft[]>();
  for (const draft of drafts) {
    if (!draft.section_id) continue;
    const existing = draftBySection.get(draft.section_id) ?? [];
    existing.push(draft);
    draftBySection.set(draft.section_id, existing);
  }
  return draftBySection;
}

function parseFocusAreas(value: string): string[] {
  return value
    .split(/[,\n;，；、]+/)
    .map(item => item.trim())
    .filter(Boolean)
    .slice(0, 8);
}

function parseTargetLength(value: string): number | null {
  const parsed = Number.parseInt(value.trim(), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return Math.min(parsed, 200000);
}
