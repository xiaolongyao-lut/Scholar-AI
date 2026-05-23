import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

/**
 * Multi-PDF tab manager.
 *
 * Zotero learnings driving the design:
 *  - #2955: Windows process address space caps active PDFs hard. Don't try
 *    to keep every opened PDF's bytes in memory.
 *  - #2383: tabs and bytes are decoupled — tabs are cheap UI rows,
 *    bytes are an LRU on top.
 *  - #3271: never store the same PDF's bytes twice.
 *  - Session.save(): tab list survives reload; bytes do not.
 *
 * Concretely:
 *  - tabs[] is unbounded; the strip scrolls.
 *  - bytesCache holds at most BYTES_CACHE_SIZE entries (active + N-1).
 *    Pdf bytes are owned here in a ref Map so cache evictions don't
 *    trigger React re-renders.
 *  - perTabView holds page/scale/sidebar state per materialId so tab
 *    switches restore the exact spot the user left.
 *  - tab list + activeId persist to sessionStorage (lost on browser
 *    close, restored on reload — the Zotero Session.save() lite path).
 */

const STORAGE_KEY = 'pdf-tabs:v1';
const BYTES_CACHE_SIZE = 3;

export interface PdfTab {
  materialId: string;
  title: string;
}

export interface PdfViewState {
  page: number;
  scale: number;
  scrollTop: number;
  sidebarOpen?: boolean;
  sidebarTab?: 'highlights' | 'notes' | 'outline';
}

interface PersistedState {
  tabs: PdfTab[];
  activeId: string | null;
  views: Record<string, PdfViewState>;
}

interface PdfTabsContextValue {
  tabs: PdfTab[];
  activeId: string | null;
  openTab: (tab: PdfTab, opts?: { activate?: boolean }) => void;
  closeTab: (materialId: string) => string | null;
  setActive: (materialId: string) => void;
  setTitle: (materialId: string, title: string) => void;

  getView: (materialId: string) => PdfViewState | undefined;
  updateView: (materialId: string, patch: Partial<PdfViewState>) => void;

  getCachedBytes: (materialId: string) => Uint8Array | undefined;
  setCachedBytes: (materialId: string, bytes: Uint8Array) => void;
}

const PdfTabsContext = createContext<PdfTabsContextValue | null>(null);

function loadPersisted(): PersistedState {
  if (typeof window === 'undefined') {
    return { tabs: [], activeId: null, views: {} };
  }
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return { tabs: [], activeId: null, views: {} };
    const parsed = JSON.parse(raw) as Partial<PersistedState>;
    return {
      tabs: Array.isArray(parsed.tabs) ? parsed.tabs.filter(t => t && typeof t.materialId === 'string') : [],
      activeId: typeof parsed.activeId === 'string' ? parsed.activeId : null,
      views: (parsed.views && typeof parsed.views === 'object') ? parsed.views as Record<string, PdfViewState> : {},
    };
  } catch {
    return { tabs: [], activeId: null, views: {} };
  }
}

function persist(state: PersistedState): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* quota / private mode — ignore */
  }
}

export function PdfTabsProvider({ children }: { children: React.ReactNode }) {
  const initial = useMemo(loadPersisted, []);
  const [tabs, setTabs] = useState<PdfTab[]>(initial.tabs);
  const [activeId, setActiveId] = useState<string | null>(initial.activeId);
  const viewsRef = useRef<Record<string, PdfViewState>>(initial.views);

  // bytesCache is intentionally outside React state. Eviction must not
  // re-render every consumer; bytes are pulled on-demand by PdfViewer.
  const bytesCacheRef = useRef<Map<string, Uint8Array>>(new Map());
  // LRU order: most-recent at the end.
  const lruRef = useRef<string[]>([]);

  // Persist tab list + activeId. Views snapshot is pushed via updateView's
  // own persistence below so we don't have to re-stringify on every tab op.
  useEffect(() => {
    persist({ tabs, activeId, views: viewsRef.current });
  }, [tabs, activeId]);

  const openTab = useCallback<PdfTabsContextValue['openTab']>((tab, opts) => {
    const activate = opts?.activate !== false;
    setTabs(prev => {
      const exists = prev.find(t => t.materialId === tab.materialId);
      if (exists) {
        // Update the title if the caller has a better one; otherwise keep.
        if (tab.title && tab.title !== exists.title) {
          return prev.map(t => (t.materialId === tab.materialId ? { ...t, title: tab.title } : t));
        }
        return prev;
      }
      return [...prev, tab];
    });
    if (activate) setActiveId(tab.materialId);
  }, []);

  const closeTab = useCallback<PdfTabsContextValue['closeTab']>((materialId) => {
    // Compute the next active id BEFORE we mutate so we can return it
    // synchronously to the caller (router uses this to decide where to
    // navigate next).
    let nextActive: string | null = null;
    setTabs(prev => {
      const idx = prev.findIndex(t => t.materialId === materialId);
      if (idx < 0) return prev;
      const next = prev.slice(0, idx).concat(prev.slice(idx + 1));
      if (activeId === materialId) {
        const neighbor = next[idx] ?? next[idx - 1] ?? null;
        nextActive = neighbor ? neighbor.materialId : null;
      } else {
        nextActive = activeId;
      }
      return next;
    });
    if (activeId === materialId) {
      setActiveId(nextActive);
    }

    // Drop bytes + view state for the closed tab so memory follows the UI.
    bytesCacheRef.current.delete(materialId);
    lruRef.current = lruRef.current.filter(id => id !== materialId);
    if (viewsRef.current[materialId]) {
      const { [materialId]: _removed, ...rest } = viewsRef.current;
      void _removed;
      viewsRef.current = rest;
      persist({ tabs, activeId: nextActive, views: viewsRef.current });
    }

    return nextActive;
  }, [activeId, tabs]);

  const setActive = useCallback<PdfTabsContextValue['setActive']>((materialId) => {
    setActiveId(materialId);
  }, []);

  const setTitle = useCallback<PdfTabsContextValue['setTitle']>((materialId, title) => {
    setTabs(prev => prev.map(t => (t.materialId === materialId ? { ...t, title } : t)));
  }, []);

  const getView = useCallback<PdfTabsContextValue['getView']>((materialId) => {
    return viewsRef.current[materialId];
  }, []);

  const updateView = useCallback<PdfTabsContextValue['updateView']>((materialId, patch) => {
    const prev = viewsRef.current[materialId] ?? { page: 1, scale: 1.2, scrollTop: 0 };
    const next = { ...prev, ...patch };
    viewsRef.current = { ...viewsRef.current, [materialId]: next };
    // Persist view snapshot in the same blob — cheap, low-frequency since
    // page/scale only change on user action.
    persist({ tabs, activeId, views: viewsRef.current });
  }, [tabs, activeId]);

  const getCachedBytes = useCallback<PdfTabsContextValue['getCachedBytes']>((materialId) => {
    const hit = bytesCacheRef.current.get(materialId);
    if (hit) {
      // Touch LRU.
      lruRef.current = lruRef.current.filter(id => id !== materialId);
      lruRef.current.push(materialId);
    }
    return hit;
  }, []);

  const setCachedBytes = useCallback<PdfTabsContextValue['setCachedBytes']>((materialId, bytes) => {
    bytesCacheRef.current.set(materialId, bytes);
    lruRef.current = lruRef.current.filter(id => id !== materialId);
    lruRef.current.push(materialId);
    // Evict LRU entries that aren't the active tab. Active tab is
    // protected so a long load of a 4th PDF can't kick out the user's
    // current page.
    while (lruRef.current.length > BYTES_CACHE_SIZE) {
      const victimIdx = lruRef.current.findIndex(id => id !== activeId);
      if (victimIdx < 0) break;
      const [victim] = lruRef.current.splice(victimIdx, 1);
      bytesCacheRef.current.delete(victim);
    }
  }, [activeId]);

  const value = useMemo<PdfTabsContextValue>(() => ({
    tabs,
    activeId,
    openTab,
    closeTab,
    setActive,
    setTitle,
    getView,
    updateView,
    getCachedBytes,
    setCachedBytes,
  }), [tabs, activeId, openTab, closeTab, setActive, setTitle, getView, updateView, getCachedBytes, setCachedBytes]);

  return <PdfTabsContext.Provider value={value}>{children}</PdfTabsContext.Provider>;
}

export function usePdfTabs(): PdfTabsContextValue {
  const ctx = useContext(PdfTabsContext);
  if (!ctx) throw new Error('usePdfTabs must be used inside <PdfTabsProvider>');
  return ctx;
}
