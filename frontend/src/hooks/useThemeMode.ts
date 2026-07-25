import { useCallback, useEffect, useState } from 'react';

export type ThemeMode = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'scholar-ai.theme';
const DARK_SCHEME_QUERY = '(prefers-color-scheme: dark)';

function isAgentSidebarRoute(): boolean {
  if (typeof window === 'undefined') return false;
  const pathname = window.location.pathname;
  return pathname === '/agent-sidebar' || pathname.startsWith('/agent-sidebar/');
}

function readSystemPref(): ResolvedTheme {
  if (typeof window === 'undefined' || !window.matchMedia) return 'light';
  return window.matchMedia(DARK_SCHEME_QUERY).matches ? 'dark' : 'light';
}

function readStoredMode(): ThemeMode {
  if (typeof window === 'undefined') return 'system';
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === 'light' || raw === 'dark' || raw === 'system') return raw;
  } catch {
    /* localStorage unavailable */
  }
  return 'system';
}

function resolve(mode: ThemeMode): ResolvedTheme {
  return mode === 'system' ? readSystemPref() : mode;
}

function resolveForCurrentRoute(mode: ThemeMode): ResolvedTheme {
  return isAgentSidebarRoute() ? readSystemPref() : resolve(mode);
}

function applyDocumentClass(resolved: ResolvedTheme) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (resolved === 'dark') root.classList.add('dark');
  else root.classList.remove('dark');
  root.dataset.theme = resolved;
}

export function useThemeMode() {
  const [mode, setModeState] = useState<ThemeMode>(() => readStoredMode());
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolveForCurrentRoute(readStoredMode()));

  const setMode = useCallback((next: ThemeMode) => {
    const sidebarRoute = isAgentSidebarRoute();
    setModeState(next);
    if (!sidebarRoute) {
      try {
        window.localStorage.setItem(STORAGE_KEY, next);
      } catch {
        /* ignore quota / private mode */
      }
    }
    const r = sidebarRoute ? readSystemPref() : resolve(next);
    setResolved(r);
    applyDocumentClass(r);
  }, []);

  useEffect(() => {
    applyDocumentClass(resolveForCurrentRoute(mode));
  }, [mode]);

  useEffect(() => {
    const followsSystem = isAgentSidebarRoute() || mode === 'system';
    if (!followsSystem || typeof window === 'undefined' || !window.matchMedia) return;
    const mql = window.matchMedia(DARK_SCHEME_QUERY);
    const handler = (e: MediaQueryListEvent) => {
      const next: ResolvedTheme = e.matches ? 'dark' : 'light';
      setResolved(next);
      applyDocumentClass(next);
    };
    mql.addEventListener?.('change', handler);
    return () => mql.removeEventListener?.('change', handler);
  }, [mode]);

  return { mode, resolved, setMode } as const;
}
