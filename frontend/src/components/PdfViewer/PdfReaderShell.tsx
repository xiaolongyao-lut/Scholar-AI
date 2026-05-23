import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronRight, Download, FileText, Highlighter, ListTree, Loader2, PanelRightClose,
  PanelRight, Plus, Trash2, X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { PdfViewer, type PdfOutlineEntry } from '@/components/PdfViewer/PdfViewer';
import {
  type AnnotationData,
  type Highlight,
  type Note,
  addNote,
  deleteNote,
  exportMarkdown,
  setLastPage,
  setLastPageBeacon,
  setLastPageKeepalive,
  updateNote,
} from '@/services/annotationApi';
import { downloadBlob } from '@/services/exportApi';

type TabId = 'highlights' | 'notes' | 'outline';

interface PdfReaderShellProps {
  url: string;
  materialId: string;
  initialPage?: number;
  /** Multi-tab fast path: bytes from the parent's LRU cache. When set,
   *  PdfViewer skips its own fetch. */
  bytes?: Uint8Array;
  onBytesLoaded?: (bytes: Uint8Array) => void;
  /** Multi-tab: external zoom for per-tab persistence. */
  scale?: number;
  onScaleChange?: (scale: number) => void;
  highlights: Highlight[];
  notes?: Note[];
  lastPage?: number | null;
  /** Pulled from a PDF.js getOutline() call by the parent (KnowledgeBase
   *  loadDetail) — null when the PDF has no outline / the call failed.
   *  Out of scope for F3 (placeholder); F5 wires the real fetch. */
  outline?: OutlineEntry[] | null;
  onAnalyzeText?: (text: string, page: number) => void;
  onAddHighlight?: (highlight: Highlight) => void;
  onDeleteHighlight?: (index: number) => void;
  onAnnotationUpdate?: (annotation: AnnotationData) => void;
  /** Multi-tab: notify parent of page changes so per-tab page can be
   *  persisted in PdfTabsContext. Fires on every confirmed page change. */
  onPageChange?: (page: number) => void;
  className?: string;
}

interface OutlineEntry {
  title: string;
  page?: number;
  children?: OutlineEntry[];
}

const TAB_STORAGE_KEY_PREFIX = 'pdf-reader-tab:';
const SIDEBAR_STORAGE_KEY_PREFIX = 'pdf-reader-sidebar:';
const READ_PROGRESS_DEBOUNCE_MS = 2000;

function loadOpenTab(materialId: string): TabId {
  if (typeof window === 'undefined') return 'highlights';
  const stored = window.localStorage.getItem(`${TAB_STORAGE_KEY_PREFIX}${materialId}`);
  return stored === 'highlights' || stored === 'notes' || stored === 'outline'
    ? (stored as TabId)
    : 'highlights';
}

function loadSidebarOpen(materialId: string): boolean {
  if (typeof window === 'undefined') return false;
  return window.localStorage.getItem(`${SIDEBAR_STORAGE_KEY_PREFIX}${materialId}`) === 'open';
}

function persistOpenTab(materialId: string, tab: TabId): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(`${TAB_STORAGE_KEY_PREFIX}${materialId}`, tab);
  } catch {
    /* storage quota / private mode — ignore */
  }
}

function persistSidebarOpen(materialId: string, open: boolean): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(`${SIDEBAR_STORAGE_KEY_PREFIX}${materialId}`, open ? 'open' : 'closed');
  } catch {
    /* ignore */
  }
}

/**
 * Track C F3 — PdfReaderShell wraps the L1 PdfViewer with a right-side
 * collapsible sidebar that hosts three tabs: Highlights (extracted),
 * Notes (new), Outline (placeholder filled by F5).
 *
 * The shell owns:
 *  - per-material open-tab + sidebar-state localStorage memory (D-PDF-4)
 *  - notes CRUD via annotationApi (D-PDF-1, D-PDF-2)
 *  - debounced + Beacon-flushed read-progress writes (D-PDF-6, F6)
 *  - Markdown export via existing downloadBlob helper (D-PDF-7, F7)
 *
 * Highlights add/delete still flow through the parent because L1's
 * MessageBubble + KnowledgeBase plumbing already owns that flow.
 */
export function PdfReaderShell({
  url,
  materialId,
  initialPage,
  bytes,
  onBytesLoaded,
  scale,
  onScaleChange,
  highlights,
  notes,
  lastPage,
  outline,
  onAnalyzeText,
  onAddHighlight,
  onDeleteHighlight,
  onAnnotationUpdate,
  onPageChange: onPageChangeExternal,
  className,
}: PdfReaderShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() => loadSidebarOpen(materialId));
  const [activeTab, setActiveTab] = useState<TabId>(() => loadOpenTab(materialId));
  const [currentPage, setCurrentPage] = useState<number>(initialPage ?? 1);
  const [pendingPage, setPendingPage] = useState<number | undefined>(initialPage);
  const [localNotes, setLocalNotes] = useState<Note[]>(notes ?? []);
  const [savingExport, setSavingExport] = useState(false);
  // Track C F5: outline auto-loaded from PDF.js. null until the
  // document resolves; then either the outline tree or null when the
  // PDF has none / call failed.
  const [loadedOutline, setLoadedOutline] = useState<PdfOutlineEntry[] | null>(null);
  // Track C F4: selection-anchored note popover state. Opened when
  // PdfViewer's "添加笔记" button fires the onAddNote callback.
  const [notePopover, setNotePopover] = useState<{
    open: boolean;
    anchorText: string;
    page: number;
  }>({ open: false, anchorText: '', page: 1 });

  // Sync controlled/optimistic notes from parent props.
  useEffect(() => { setLocalNotes(notes ?? []); }, [notes]);

  // Persist sidebar/tab + reset when material changes.
  useEffect(() => {
    setSidebarOpen(loadSidebarOpen(materialId));
    setActiveTab(loadOpenTab(materialId));
  }, [materialId]);

  const handleTabSelect = useCallback((tab: TabId) => {
    setActiveTab(tab);
    persistOpenTab(materialId, tab);
  }, [materialId]);

  const toggleSidebar = useCallback(() => {
    setSidebarOpen(prev => {
      const next = !prev;
      persistSidebarOpen(materialId, next);
      return next;
    });
  }, [materialId]);

  // ---- F6: read-progress debounce + Beacon flush --------------------------
  const lastSentRef = useRef<number | null>(typeof lastPage === 'number' ? lastPage : null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flushLastPage = useCallback((page: number) => {
    if (lastSentRef.current === page) return;
    lastSentRef.current = page;
    void setLastPage(materialId, page).catch(() => {
      /* best-effort; never disturb reading flow */
    });
  }, [materialId]);

  const handlePageChange = useCallback((page: number) => {
    setCurrentPage(page);
    if (onPageChangeExternal) onPageChangeExternal(page);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => flushLastPage(page), READ_PROGRESS_DEBOUNCE_MS);
  }, [flushLastPage, onPageChangeExternal]);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  useEffect(() => {
    const beforeUnload = () => {
      if (lastSentRef.current === currentPage) return;
      // Per amendment §0.1: Beacon only sends POST. annotationApi
      // routes to the POST alias.
      const beaconAccepted = setLastPageBeacon(materialId, currentPage);
      if (!beaconAccepted) {
        // Fallback: real keepalive PUT via fetch. A normal axios
        // request would be dropped when the page is unloading; the
        // keepalive flag tells the browser to hold the request open
        // past navigation start. setLastPageKeepalive is fire-and-
        // forget; never throws.
        setLastPageKeepalive(materialId, currentPage);
      }
      lastSentRef.current = currentPage;
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [materialId, currentPage]);

  // ---- F3 NotesTab: add / delete / edit ---------------------------------
  const handleAddNote = useCallback(async (input: { page: number; anchor_text: string; body: string; tags: string[] }) => {
    try {
      const result = await addNote(materialId, input);
      setLocalNotes(prev => [...prev, result.note]);
      if (onAnnotationUpdate) onAnnotationUpdate(result.annotation);
    } catch {
      /* swallow; UI surfaces nothing for now */
    }
  }, [materialId, onAnnotationUpdate]);

  const handleUpdateNote = useCallback(async (noteId: string, body: string, tags: string[]) => {
    try {
      const result = await updateNote(materialId, noteId, { body, tags });
      setLocalNotes(prev => prev.map(n => (n.note_id === noteId ? result.note : n)));
      if (onAnnotationUpdate) onAnnotationUpdate(result.annotation);
    } catch {
      /* swallow */
    }
  }, [materialId, onAnnotationUpdate]);

  const handleDeleteNote = useCallback(async (noteId: string) => {
    try {
      const result = await deleteNote(materialId, noteId);
      setLocalNotes(prev => prev.filter(n => n.note_id !== noteId));
      if (onAnnotationUpdate) onAnnotationUpdate(result.annotation);
    } catch {
      /* swallow */
    }
  }, [materialId, onAnnotationUpdate]);

  // ---- F7 Export ---------------------------------------------------------
  const handleExport = useCallback(async () => {
    setSavingExport(true);
    try {
      const blob = await exportMarkdown(materialId);
      if (blob) {
        // downloadBlob expects an object URL string + filename; per
        // amendment §0.1: fetch the blob first, build object URL, then
        // hand off to the existing helper which revokes the URL after
        // click.
        const objectUrl = URL.createObjectURL(blob);
        downloadBlob(objectUrl, `${materialId}.md`);
      }
    } finally {
      setSavingExport(false);
    }
  }, [materialId]);

  // ---- Outline tab navigation -------------------------------------------
  const jumpToPage = useCallback((page: number) => {
    setPendingPage(page);
  }, []);

  const handleOutlineLoaded = useCallback((entries: PdfOutlineEntry[] | null) => {
    setLoadedOutline(entries);
  }, []);

  // F4: open the popover with the selected text + the current page.
  const handleAddNoteFromSelection = useCallback((anchorText: string, page: number) => {
    setNotePopover({ open: true, anchorText, page });
    // Auto-jump to the Notes tab so the user sees the new entry
    // appear after submit.
    handleTabSelect('notes');
    setSidebarOpen(true);
    persistSidebarOpen(materialId, true);
  }, [handleTabSelect, materialId]);

  const closeNotePopover = useCallback(() => {
    setNotePopover(p => ({ ...p, open: false }));
  }, []);

  const submitNotePopover = useCallback(async (body: string, tags: string[]) => {
    await handleAddNote({
      page: notePopover.page,
      anchor_text: notePopover.anchorText,
      body,
      tags,
    });
    setNotePopover(p => ({ ...p, open: false }));
  }, [handleAddNote, notePopover.page, notePopover.anchorText]);

  // The outline can come from an explicit prop (e.g. tests) or the
  // auto-loaded outline from PdfViewer; explicit prop wins.
  const effectiveOutline = outline ?? loadedOutline;

  // Memo the count chips so the toolbar doesn't re-render every keystroke.
  const counts = useMemo(() => ({
    highlights: highlights.length,
    notes: localNotes.length,
    outline: effectiveOutline ? effectiveOutline.length : 0,
  }), [highlights.length, localNotes.length, effectiveOutline]);

  return (
    <div className={cn('flex h-full bg-surface-lowest', className)}>
      <div className="flex-1 min-w-0 flex flex-col">
        <PdfViewer
          url={url}
          materialId={materialId}
          initialPage={pendingPage ?? initialPage}
          bytes={bytes}
          onBytesLoaded={onBytesLoaded}
          scale={scale}
          onScaleChange={onScaleChange}
          onAnalyzeText={onAnalyzeText}
          onAddHighlight={onAddHighlight}
          onDeleteHighlight={onDeleteHighlight}
          highlights={highlights}
          hideHighlightPanel
          onPageChange={handlePageChange}
          onAddNote={handleAddNoteFromSelection}
          onOutlineLoaded={handleOutlineLoaded}
        />
      </div>

      {/* Sidebar toggle rail */}
      <div className="flex-none flex flex-col items-center gap-2 border-l border-outline-variant/60 bg-surface-low px-1 py-2">
        <button
          type="button"
          onClick={toggleSidebar}
          className="p-1.5 rounded text-foreground/80 hover:bg-surface-high hover:text-foreground transition-colors"
          aria-label={sidebarOpen ? '收起阅读侧栏' : '展开阅读侧栏'}
          title={sidebarOpen ? '收起' : '展开侧栏'}
        >
          {sidebarOpen ? <PanelRightClose size={16} /> : <PanelRight size={16} />}
        </button>
        <button
          type="button"
          onClick={() => void handleExport()}
          disabled={savingExport}
          className="p-1.5 rounded text-foreground/80 hover:bg-surface-high hover:text-foreground transition-colors disabled:opacity-40"
          aria-label="导出笔记 Markdown"
          title="导出笔记 (Markdown)"
        >
          {savingExport ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
        </button>
      </div>

      {sidebarOpen && (
        <aside className="w-80 flex-none flex flex-col border-l border-outline-variant/60 bg-surface-low">
          <div className="flex-none border-b border-outline-variant/60">
            <TabBar active={activeTab} counts={counts} onSelect={handleTabSelect} />
          </div>
          <div className="flex-1 min-h-0 overflow-auto">
            {activeTab === 'highlights' && (
              <HighlightsTab
                highlights={highlights}
                onJump={jumpToPage}
                onDelete={onDeleteHighlight}
              />
            )}
            {activeTab === 'notes' && (
              <NotesTab
                notes={localNotes}
                currentPage={currentPage}
                onJump={jumpToPage}
                onAdd={handleAddNote}
                onUpdate={handleUpdateNote}
                onDelete={handleDeleteNote}
              />
            )}
            {activeTab === 'outline' && (
              <OutlineTab outline={effectiveOutline} onJump={jumpToPage} />
            )}
          </div>
        </aside>
      )}

      {notePopover.open && (
        <NoteEditorPopover
          page={notePopover.page}
          anchorText={notePopover.anchorText}
          onCancel={closeNotePopover}
          onSave={submitNotePopover}
        />
      )}
    </div>
  );
}

interface NoteEditorPopoverProps {
  page: number;
  anchorText: string;
  onCancel: () => void;
  onSave: (body: string, tags: string[]) => Promise<void> | void;
}

/** Track C F4: selection-anchored note popover. Centered modal so the
 *  user keeps focus on the new note instead of bouncing back to the
 *  reader; submit hands off to the shell which routes to addNote. */
function NoteEditorPopover({ page, anchorText, onCancel, onSave }: NoteEditorPopoverProps) {
  const [body, setBody] = useState('');
  const [tags, setTags] = useState('');
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    const cleanBody = body.trim();
    if (cleanBody.length === 0) return;
    setSaving(true);
    try {
      const cleanTags = tags
        .split(',')
        .map(t => t.trim())
        .filter(t => t.length > 0)
        .slice(0, 16);
      await onSave(cleanBody, cleanTags);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-label="添加笔记"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-lg bg-surface-lowest p-4 shadow-xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-headline font-semibold text-foreground">添加笔记</h3>
            <p className="text-[10px] text-foreground/45 mt-0.5">第 {page} 页 · 选区锚定</p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="p-1 rounded hover:bg-surface-high text-foreground/50"
            aria-label="关闭"
          >
            <X size={14} />
          </button>
        </div>

        {anchorText && (
          <div className="mb-3 rounded border border-outline-variant/40 bg-amber-50/60 p-2 text-[11px] italic text-foreground/70">
            “{anchorText.length > 200 ? `${anchorText.slice(0, 200)}…` : anchorText}”
          </div>
        )}

        <div className="space-y-2">
          <textarea
            value={body}
            onChange={e => setBody(e.target.value)}
            placeholder="笔记正文…"
            rows={5}
            autoFocus
            className="w-full resize-none rounded border border-outline-variant/50 bg-surface-low px-2 py-1.5 text-sm text-foreground placeholder:text-foreground/30 focus:outline-none focus:border-primary/40"
          />
          <input
            type="text"
            value={tags}
            onChange={e => setTags(e.target.value)}
            placeholder="tags（半角逗号分隔，可选）"
            className="w-full rounded border border-outline-variant/50 bg-surface-low px-2 py-1.5 text-xs text-foreground placeholder:text-foreground/30 focus:outline-none focus:border-primary/40"
          />
        </div>

        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded px-3 py-1.5 text-xs font-label text-foreground/60 hover:text-foreground/90"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={saving || body.trim().length === 0}
            className="inline-flex items-center gap-1 rounded bg-primary px-3 py-1.5 text-xs font-label text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />} 保存笔记
          </button>
        </div>
      </div>
    </div>
  );
}

function TabBar({
  active,
  counts,
  onSelect,
}: {
  active: TabId;
  counts: { highlights: number; notes: number; outline: number };
  onSelect: (id: TabId) => void;
}) {
  const tabs: Array<{ id: TabId; icon: typeof Highlighter; label: string; count: number }> = [
    { id: 'highlights', icon: Highlighter, label: '标注', count: counts.highlights },
    { id: 'notes', icon: FileText, label: '笔记', count: counts.notes },
    { id: 'outline', icon: ListTree, label: '大纲', count: counts.outline },
  ];
  return (
    <div className="flex">
      {tabs.map(tab => {
        const Icon = tab.icon;
        return (
          <button
            key={tab.id}
            type="button"
            onClick={() => onSelect(tab.id)}
            aria-selected={active === tab.id}
            className={cn(
              'flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-label transition-colors border-b-2',
              active === tab.id
                ? 'border-primary text-primary bg-surface-lowest'
                : 'border-transparent text-foreground/55 hover:text-foreground/80',
            )}
          >
            <Icon size={13} />
            {tab.label}
            {tab.count > 0 && (
              <span className="ml-0.5 text-[10px] text-foreground/45 font-mono">({tab.count})</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

function HighlightsTab({
  highlights,
  onJump,
  onDelete,
}: {
  highlights: Highlight[];
  onJump: (page: number) => void;
  onDelete?: (index: number) => void;
}) {
  if (highlights.length === 0) {
    return (
      <EmptyState
        icon={<Highlighter size={20} className="text-foreground/30" />}
        title="还没有标注"
        hint="选中正文 → 标记，开始添加高亮。"
      />
    );
  }
  return (
    <ul className="p-2 space-y-1.5">
      {highlights.map((h, i) => (
        <li
          key={`${h.page}-${i}`}
          className="group rounded border border-outline-variant/40 bg-amber-50/50 p-2 hover:bg-amber-50 transition-colors"
        >
          <div className="flex items-start justify-between gap-1 mb-1">
            <button
              type="button"
              onClick={() => onJump(h.page)}
              className="text-[10px] font-label text-blue-700 hover:underline"
              title="跳到该页"
            >
              第 {h.page} 页
            </button>
            {onDelete && (
              <button
                type="button"
                onClick={() => onDelete(i)}
                className="opacity-0 group-hover:opacity-100 text-foreground/40 hover:text-red-600 transition-opacity"
                title="删除"
                aria-label={`删除标注 ${i + 1}`}
              >
                <Trash2 size={11} />
              </button>
            )}
          </div>
          <div className="text-[11px] text-foreground/80 leading-snug line-clamp-3">{h.text}</div>
        </li>
      ))}
    </ul>
  );
}

interface NotesTabProps {
  notes: Note[];
  currentPage: number;
  onJump: (page: number) => void;
  onAdd: (input: { page: number; anchor_text: string; body: string; tags: string[] }) => Promise<void> | void;
  onUpdate: (noteId: string, body: string, tags: string[]) => Promise<void> | void;
  onDelete: (noteId: string) => Promise<void> | void;
}

function NotesTab({
  notes,
  currentPage,
  onJump,
  onAdd,
  onUpdate,
  onDelete,
}: NotesTabProps) {
  const [draftBody, setDraftBody] = useState('');
  const [draftTags, setDraftTags] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingBody, setEditingBody] = useState('');
  const [editingTags, setEditingTags] = useState('');

  const submitDraft = async () => {
    const body = draftBody.trim();
    if (body.length === 0) return;
    const tags = draftTags
      .split(',')
      .map(t => t.trim())
      .filter(t => t.length > 0)
      .slice(0, 16);
    await onAdd({ page: currentPage, anchor_text: '', body, tags });
    setDraftBody('');
    setDraftTags('');
  };

  const startEditing = (note: Note) => {
    setEditingId(note.note_id);
    setEditingBody(note.body);
    setEditingTags(note.tags.join(', '));
  };

  const cancelEditing = () => {
    setEditingId(null);
    setEditingBody('');
    setEditingTags('');
  };

  const submitEdit = async () => {
    if (!editingId) return;
    const tags = editingTags
      .split(',')
      .map(t => t.trim())
      .filter(t => t.length > 0)
      .slice(0, 16);
    await onUpdate(editingId, editingBody, tags);
    cancelEditing();
  };

  return (
    <div className="p-2 space-y-2">
      {/* Quick-add form: defaults the page to the viewer's current page. */}
      <div className="rounded border border-outline-variant/50 bg-surface-lowest p-2 space-y-1.5">
        <div className="flex items-center justify-between text-[10px] text-foreground/50">
          <span>第 {currentPage} 页 · 页面笔记</span>
          <span>Tags 用半角逗号分隔</span>
        </div>
        <textarea
          value={draftBody}
          onChange={e => setDraftBody(e.target.value)}
          placeholder="写下这一页的想法…"
          rows={2}
          className="w-full resize-none rounded border border-outline-variant/40 bg-surface-low px-2 py-1 text-xs text-foreground placeholder:text-foreground/30 focus:outline-none focus:border-primary/40"
        />
        <input
          type="text"
          value={draftTags}
          onChange={e => setDraftTags(e.target.value)}
          placeholder="tags（可选）"
          className="w-full rounded border border-outline-variant/40 bg-surface-low px-2 py-1 text-xs text-foreground placeholder:text-foreground/30 focus:outline-none focus:border-primary/40"
        />
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => void submitDraft()}
            disabled={draftBody.trim().length === 0}
            className="inline-flex items-center gap-1 rounded bg-primary px-2 py-1 text-[10px] font-label text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
          >
            <Plus size={11} /> 添加笔记
          </button>
        </div>
      </div>

      {notes.length === 0 ? (
        <EmptyState
          icon={<FileText size={20} className="text-foreground/30" />}
          title="还没有笔记"
          hint="在上方写一段或选中正文 → 添加笔记。"
        />
      ) : (
        <ul className="space-y-1.5">
          {notes.map(note => {
            const isEditing = editingId === note.note_id;
            return (
              <li
                key={note.note_id}
                className="group rounded border border-outline-variant/40 bg-surface-lowest p-2"
              >
                <div className="flex items-start justify-between gap-1 mb-1">
                  <button
                    type="button"
                    onClick={() => onJump(note.page)}
                    className="text-[10px] font-label text-blue-700 hover:underline"
                    title="跳到该页"
                  >
                    第 {note.page} 页
                  </button>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    {!isEditing && (
                      <button
                        type="button"
                        onClick={() => startEditing(note)}
                        className="text-foreground/45 hover:text-foreground/80"
                        title="编辑"
                        aria-label={`编辑笔记 ${note.note_id}`}
                      >
                        <ChevronRight size={11} />
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => void onDelete(note.note_id)}
                      className="text-foreground/45 hover:text-red-600"
                      title="删除"
                      aria-label={`删除笔记 ${note.note_id}`}
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>
                </div>
                {note.anchor_text && (
                  <p className="text-[10px] text-foreground/50 italic line-clamp-2 mb-1">
                    “{note.anchor_text}”
                  </p>
                )}
                {isEditing ? (
                  <div className="space-y-1.5">
                    <textarea
                      value={editingBody}
                      onChange={e => setEditingBody(e.target.value)}
                      rows={2}
                      className="w-full resize-none rounded border border-outline-variant/40 bg-surface-low px-2 py-1 text-xs"
                    />
                    <input
                      type="text"
                      value={editingTags}
                      onChange={e => setEditingTags(e.target.value)}
                      placeholder="tags"
                      className="w-full rounded border border-outline-variant/40 bg-surface-low px-2 py-1 text-xs"
                    />
                    <div className="flex justify-end gap-1.5">
                      <button
                        type="button"
                        onClick={cancelEditing}
                        className="text-[10px] text-foreground/55 hover:text-foreground/80"
                      >
                        取消
                      </button>
                      <button
                        type="button"
                        onClick={() => void submitEdit()}
                        className="rounded bg-primary px-2 py-0.5 text-[10px] font-label text-primary-foreground hover:bg-primary/90"
                      >
                        保存
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="text-[11px] text-foreground/85 leading-snug whitespace-pre-wrap">
                      {note.body}
                    </p>
                    {note.tags.length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {note.tags.map(t => (
                          <span
                            key={t}
                            className="rounded bg-surface-high px-1.5 py-0.5 text-[9px] font-mono text-foreground/55"
                          >
                            #{t}
                          </span>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function OutlineTab({
  outline,
  onJump,
}: {
  outline: OutlineEntry[] | null;
  onJump: (page: number) => void;
}) {
  if (!outline || outline.length === 0) {
    return (
      <EmptyState
        icon={<ListTree size={20} className="text-foreground/30" />}
        title="无章节大纲"
        hint="该 PDF 未提供 outline；或正在加载中。"
      />
    );
  }
  return (
    <div className="p-2 text-xs">
      <OutlineList entries={outline} depth={0} onJump={onJump} />
    </div>
  );
}

function OutlineList({
  entries,
  depth,
  onJump,
}: {
  entries: OutlineEntry[];
  depth: number;
  onJump: (page: number) => void;
}) {
  return (
    <ul className="space-y-0.5" style={{ paddingLeft: depth === 0 ? 0 : 12 }}>
      {entries.map((entry, i) => (
        <li key={`${entry.title}-${i}`}>
          <button
            type="button"
            onClick={() => entry.page && entry.page > 0 && onJump(entry.page)}
            disabled={!entry.page || entry.page <= 0}
            className="text-left w-full text-foreground/75 hover:text-primary transition-colors disabled:text-foreground/30 disabled:cursor-not-allowed"
            title={entry.page ? `跳到第 ${entry.page} 页` : '无页面定位'}
          >
            {entry.title}
            {entry.page && <span className="ml-1 text-[10px] text-foreground/40">p.{entry.page}</span>}
          </button>
          {entry.children && entry.children.length > 0 && (
            <OutlineList entries={entry.children} depth={depth + 1} onJump={onJump} />
          )}
        </li>
      ))}
    </ul>
  );
}

function EmptyState({
  icon,
  title,
  hint,
}: {
  icon: React.ReactNode;
  title: string;
  hint: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-10 px-4">
      <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg border border-dashed border-outline-variant bg-surface-low">
        {icon}
      </div>
      <p className="text-xs font-label text-foreground/65">{title}</p>
      <p className="mt-1 text-[10px] text-foreground/40 leading-relaxed">{hint}</p>
    </div>
  );
}
