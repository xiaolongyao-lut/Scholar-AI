import React, { useState, useRef, useEffect } from 'react';
import { Loader2, RefreshCw, ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface DiscoveredModel {
  id: string;
  name?: string;
  description?: string;
}

interface ModelComboInputProps {
  id?: string;
  value: string;
  onChange: (v: string) => void;
  models: DiscoveredModel[];
  onDiscover: () => Promise<void>;
  discoverStatus: 'idle' | 'loading' | 'ok' | 'fail';
  discoverError?: string;
  placeholder?: string;
  ariaLabel?: string;
}

export function ModelComboInput({
  id,
  value,
  onChange,
  models,
  onDiscover,
  discoverStatus,
  discoverError,
  placeholder = '模型 ID',
  ariaLabel,
}: ModelComboInputProps) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const filtered = models.filter(m =>
    m.id.toLowerCase().includes(filter.toLowerCase()) ||
    (m.name && m.name.toLowerCase().includes(filter.toLowerCase()))
  );

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    onChange(v);
    setFilter(v);
    if (models.length > 0) {
      setOpen(true);
    }
  };

  const handleSelect = (modelId: string) => {
    onChange(modelId);
    setFilter('');
    setOpen(false);
    inputRef.current?.focus();
  };

  const handleDiscoverClick = async () => {
    await onDiscover();
  };

  return (
    <div ref={containerRef} className="relative">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <input
            ref={inputRef}
            id={id}
            type="text"
            value={value}
            onChange={handleInputChange}
            onFocus={() => { if (models.length > 0) setOpen(true); }}
            placeholder={placeholder}
            aria-label={ariaLabel || placeholder}
            autoComplete="off"
            className="w-full bg-surface-high rounded-lg px-3 py-2 pr-8 border border-outline-variant/50 text-sm font-mono text-foreground focus:outline-none focus:border-primary/40 transition-colors"
          />
          {models.length > 0 && (
            <button
              type="button"
              onClick={() => setOpen(!open)}
              tabIndex={-1}
              aria-label="展开模型列表"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-foreground/30 hover:text-foreground/60 transition-colors"
            >
              <ChevronDown size={14} className={cn('transition-transform', open && 'rotate-180')} />
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={handleDiscoverClick}
          disabled={discoverStatus === 'loading'}
          title="从服务端点自动获取可用模型列表"
          className={cn(
            'flex-shrink-0 flex items-center gap-1 px-3 py-2 rounded-lg font-label text-[11px] font-medium transition-all border',
            discoverStatus === 'loading' ? 'bg-primary/5 border-primary/20 text-primary' :
            discoverStatus === 'ok' ? 'bg-emerald-50 border-emerald-200 text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300' :
            discoverStatus === 'fail' ? 'bg-red-50 border-red-200 text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300' :
            'bg-surface-high border-outline-variant text-foreground/60 hover:border-primary/30 hover:text-primary disabled:opacity-50'
          )}
        >
          {discoverStatus === 'loading' ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          {discoverStatus === 'loading' ? '获取中…' :
           discoverStatus === 'ok' ? `${models.length} 个模型` :
           discoverStatus === 'fail' ? '失败' :
           '获取模型'}
        </button>
      </div>

      {discoverStatus === 'fail' && discoverError && (
        <p className="text-[10px] text-red-600 mt-1 dark:text-red-300">{discoverError}</p>
      )}

      {open && filtered.length > 0 && (
        <ul
          role="listbox"
          className="absolute z-50 mt-1 w-full max-h-48 overflow-y-auto bg-surface-highest border border-outline-variant rounded-lg shadow-lg"
        >
          {filtered.map(m => (
            <li
              key={m.id}
              role="option"
              aria-selected={m.id === value}
              onClick={() => handleSelect(m.id)}
              className={cn(
                'px-3 py-2 text-sm cursor-pointer transition-colors',
                m.id === value
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-foreground hover:bg-surface-high',
              )}
            >
              <span className="font-mono text-xs">{m.id}</span>
              {m.description && (
                <span className="ml-2 text-[10px] text-foreground/40">{m.description}</span>
              )}
            </li>
          ))}
        </ul>
      )}

      {open && models.length > 0 && filtered.length === 0 && (
        <div className="absolute z-50 mt-1 w-full px-3 py-2 bg-surface-highest border border-outline-variant rounded-lg shadow-lg">
          <p className="text-xs text-foreground/40">无匹配模型</p>
        </div>
      )}
    </div>
  );
}
