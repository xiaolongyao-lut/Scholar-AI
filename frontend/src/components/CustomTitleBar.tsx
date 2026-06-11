import { Minus, Square, X } from 'lucide-react';

export function CustomTitleBar() {
  const handleMinimize = () => {
    if (window.pywebview?.api?.minimize_window) {
      window.pywebview.api.minimize_window();
    }
  };

  const handleMaximize = () => {
    if (window.pywebview?.api?.maximize_window) {
      window.pywebview.api.maximize_window();
    }
  };

  const handleClose = () => {
    if (window.pywebview?.api?.close_window) {
      window.pywebview.api.close_window();
    }
  };

  return (
    <div
      className="fixed top-0 left-0 right-0 h-8 bg-background border-b flex items-center justify-between px-3 z-50 select-none"
      style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
    >
      <div className="flex items-center gap-2 text-sm font-medium text-foreground/80">
        <img src="/app-icon-32.png" alt="" className="w-4 h-4" />
        <span>Scholar AI</span>
      </div>
      <div className="flex" style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
        <button
          onClick={handleMinimize}
          className="h-8 w-10 hover:bg-accent flex items-center justify-center"
          aria-label="最小化"
        >
          <Minus className="w-4 h-4" />
        </button>
        <button
          onClick={handleMaximize}
          className="h-8 w-10 hover:bg-accent flex items-center justify-center"
          aria-label="最大化"
        >
          <Square className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={handleClose}
          className="h-8 w-10 hover:bg-destructive hover:text-destructive-foreground flex items-center justify-center"
          aria-label="关闭"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
