import React, { createContext, useContext, useEffect, useRef } from 'react';
import { useThemeMode, type ThemeMode, type ResolvedTheme } from '@/hooks/useThemeMode';
import { useReducedMotion } from '@/hooks/useReducedMotion';

interface ThemeContextValue {
  mode: ThemeMode;
  resolved: ResolvedTheme;
  setMode: (mode: ThemeMode) => void;
  reducedMotion: boolean;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const OVERLAY_ID = 'theme-transition-overlay';

function ensureOverlay(): HTMLDivElement {
  let el = document.getElementById(OVERLAY_ID) as HTMLDivElement | null;
  if (!el) {
    el = document.createElement('div');
    el.id = OVERLAY_ID;
    el.setAttribute('aria-hidden', 'true');
    el.style.cssText = [
      'position:fixed', 'inset:0',
      'background:hsl(var(--background))',
      'opacity:0', 'pointer-events:none',
      'z-index:9999',
      'transform:scale(1)',
      'transition:opacity 220ms ease-out, transform 240ms ease-out',
      'will-change:opacity,transform',
    ].join(';');
    document.body.appendChild(el);
  }
  return el;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const { mode, resolved, setMode } = useThemeMode();
  const reducedMotion = useReducedMotion();
  const lastResolvedRef = useRef<ResolvedTheme>(resolved);

  useEffect(() => {
    const prev = lastResolvedRef.current;
    lastResolvedRef.current = resolved;
    if (prev === resolved) return;
    if (reducedMotion) return;

    const overlay = ensureOverlay();
    overlay.style.background = 'hsl(var(--background))';
    overlay.style.opacity = '0.85';
    overlay.style.transform = 'scale(1.02)';
    const t = window.setTimeout(() => {
      overlay.style.opacity = '0';
      overlay.style.transform = 'scale(1)';
    }, 100);
    return () => window.clearTimeout(t);
  }, [resolved, reducedMotion]);

  return (
    <ThemeContext.Provider value={{ mode, resolved, setMode, reducedMotion }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    // SSR-safe / test-safe fallback so consumers never crash.
    return {
      mode: 'system',
      resolved: 'light',
      setMode: () => {},
      reducedMotion: false,
    };
  }
  return ctx;
}
