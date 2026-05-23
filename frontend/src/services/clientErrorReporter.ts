/**
 * Forward uncaught frontend errors to the backend so they land in
 * `<user_root>/runtime_state/logs/backend.log` alongside server-side
 * errors. Three call sites: ErrorBoundary (React render crashes),
 * window.onerror (sync exceptions), and unhandledrejection (async).
 *
 * Best-effort: a failed report must never throw, never block render,
 * and never recurse (so console.error stays the source of truth in dev
 * tools — this just forwards a copy).
 */
import { getApiBaseUrl } from './apiBaseUrl';

type ClientErrorKind = 'render' | 'window' | 'unhandledrejection';

interface ClientErrorPayload {
  kind: ClientErrorKind;
  component?: string;
  message: string;
  stack?: string;
  url?: string;
  userAgent?: string;
}

// In-process dedup so a render loop or a noisy library does not flood
// the backend log. Key = kind + first line of message + first line of
// stack. TTL keeps us from leaking memory on long sessions.
const DEDUP_TTL_MS = 60_000;
const seen = new Map<string, number>();

const dedupKey = (p: ClientErrorPayload): string => {
  const firstStack = (p.stack ?? '').split('\n', 1)[0] ?? '';
  return `${p.kind}|${p.message.slice(0, 200)}|${firstStack.slice(0, 200)}`;
};

const shouldSkip = (p: ClientErrorPayload): boolean => {
  const now = Date.now();
  // Cheap GC: prune expired entries when the map gets non-trivial.
  if (seen.size > 64) {
    for (const [k, t] of seen) {
      if (now - t > DEDUP_TTL_MS) seen.delete(k);
    }
  }
  const key = dedupKey(p);
  const last = seen.get(key);
  if (last !== undefined && now - last < DEDUP_TTL_MS) return true;
  seen.set(key, now);
  return false;
};

export const reportClientError = (payload: ClientErrorPayload): void => {
  if (shouldSkip(payload)) return;

  const body = JSON.stringify({
    kind: payload.kind,
    component: payload.component,
    message: payload.message,
    stack: payload.stack,
    url: payload.url ?? (typeof window !== 'undefined' ? window.location.href : undefined),
    userAgent: payload.userAgent ?? (typeof navigator !== 'undefined' ? navigator.userAgent : undefined),
  });

  // sendBeacon survives page unload — the right primitive for
  // unhandledrejection on a closing tab. fetch+keepalive is the
  // fallback for browsers/contexts that reject Beacon (e.g. when the
  // dev server is on a different origin).
  const url = `${getApiBaseUrl()}/api/client-error`;
  try {
    if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
      const blob = new Blob([body], { type: 'application/json' });
      if (navigator.sendBeacon(url, blob)) return;
    }
    void fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => {
      /* swallow */
    });
  } catch {
    /* swallow — never disturb the host page */
  }
};

let installed = false;

export const installGlobalClientErrorReporter = (): void => {
  if (installed || typeof window === 'undefined') return;
  installed = true;

  window.addEventListener('error', (event) => {
    const err = event.error;
    reportClientError({
      kind: 'window',
      message: (err && err.message) || event.message || 'window.onerror',
      stack: err && err.stack,
      url: typeof event.filename === 'string' ? event.filename : undefined,
    });
  });

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason;
    const message =
      reason instanceof Error
        ? reason.message
        : typeof reason === 'string'
          ? reason
          : (() => {
              try {
                return JSON.stringify(reason);
              } catch {
                return String(reason);
              }
            })();
    reportClientError({
      kind: 'unhandledrejection',
      message,
      stack: reason instanceof Error ? reason.stack : undefined,
    });
  });
};
