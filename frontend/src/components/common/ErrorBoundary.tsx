import React from 'react';
import { AlertTriangle } from 'lucide-react';
import { reportClientError, sanitizeClientErrorText } from '@/services/clientErrorReporter';

interface ErrorBoundaryProps {
  /** Friendly Chinese message shown to the user. Default works for any pane. */
  fallbackTitle?: string;
  fallbackHint?: string;
  /** Render-prop override for advanced custom fallbacks. Receives the error. */
  fallback?: (error: Error) => React.ReactNode;
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Pane-level error boundary.
 *
 * Catches unhandled render errors in Workbench panes / canvas surfaces
 * and renders a friendly Chinese fallback. Per R5 / R5.1, the default
 * fallback NEVER surfaces stack traces, API routes, JSON, chunk IDs,
 * or material IDs. Developer mode can still see the error via the
 * browser console.
 *
 * MC-9 scoping: an error in one pane stays in that pane. Compose by
 * wrapping each meaningful UI region (canvas, inspector, drawer) in
 * its own `<ErrorBoundary>` rather than a single global one.
 */
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    const componentStack = (info.componentStack || '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)[0];
    const safeMessage = sanitizeClientErrorText(error?.message, '客户端界面发生异常。');
    const safeStack = sanitizeClientErrorText(error?.stack?.split('\n', 1)[0], '');
    // Log to console for developer visibility, but do NOT surface to
    // the user. Production telemetry hook can plug in later via
    // a `WorkbenchEvent` (§ 20) subscriber.
    if (typeof console !== 'undefined' && typeof console.error === 'function') {
      console.error('[Workbench ErrorBoundary]', {
        component: sanitizeClientErrorText(componentStack, '') || this.props.fallbackTitle,
        message: safeMessage,
      });
    }
    // Forward to backend.log so server-side grep covers render crashes
    // too. componentStack is the first line of info — sufficient to
    // locate the failing pane without leaking the whole tree.
    reportClientError({
      kind: 'render',
      component: sanitizeClientErrorText(componentStack, '') || this.props.fallbackTitle,
      message: safeMessage,
      stack: safeStack || undefined,
    });
  }

  reset = (): void => {
    this.setState({ error: null });
  };

  render(): React.ReactNode {
    const { error } = this.state;
    if (error) {
      if (this.props.fallback) return this.props.fallback(error);
      return (
        <div
          role="alert"
          className="flex h-full min-h-[160px] flex-col items-center justify-center gap-2 p-6 text-center text-sm"
        >
          <AlertTriangle size={22} className="text-destructive/70" aria-hidden />
          <p className="font-medium text-foreground">{this.props.fallbackTitle ?? '此区域暂时无法显示'}</p>
          <p className="text-foreground/55">
            {this.props.fallbackHint ?? '请稍后重试，或刷新页面。其它区域不受影响。'}
          </p>
          <button
            type="button"
            onClick={this.reset}
            className="mt-2 rounded-md border border-outline-variant px-3 py-1 text-xs text-foreground/70 transition-colors hover:bg-surface-high hover:text-foreground"
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
