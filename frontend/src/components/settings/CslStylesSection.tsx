import { useState, useEffect, useRef, useCallback } from 'react';
import { Loader2, AlertCircle, Upload, Trash2, Check, CheckCircle2 } from 'lucide-react';
import { useI18n } from '@/contexts/I18nContext';
import { cn } from '@/lib/utils';
import {
  listCslStyles,
  importCslStyle,
  setActiveCslStyle,
  deleteCslStyle,
  type CslStyleMeta,
} from '@/services/cslStylesApi';

function extractApiError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
  }
  return fallback;
}

export function CslStylesSection() {
  const { t } = useI18n();
  const [styles, setStyles] = useState<CslStyleMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listCslStyles();
      setStyles(data.styles);
    } catch (err) {
      setError(extractApiError(err, t('settings.csl_load_failed')));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleActivate = async (style: CslStyleMeta) => {
    if (style.active || busyId) return;
    setBusyId(style.id);
    setError(null);
    setNotice(null);
    try {
      await setActiveCslStyle(style.id);
      await refresh();
    } catch (err) {
      setError(extractApiError(err, t('settings.csl_activate_failed')));
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (style: CslStyleMeta) => {
    if (!style.can_delete || busyId) return;
    if (!window.confirm(t('settings.csl_delete_confirm', { title: style.title }))) return;
    setBusyId(style.id);
    setError(null);
    setNotice(null);
    try {
      await deleteCslStyle(style.id);
      await refresh();
    } catch (err) {
      setError(extractApiError(err, t('settings.csl_delete_failed')));
    } finally {
      setBusyId(null);
    }
  };

  const handleFile = async (file: File | null) => {
    if (!file) return;
    setImporting(true);
    setError(null);
    setNotice(null);
    try {
      const text = await file.text();
      const meta = await importCslStyle(text);
      setNotice(t('settings.csl_import_ok', { title: meta.title }));
      await refresh();
    } catch (err) {
      setError(extractApiError(err, t('settings.csl_import_failed')));
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 rounded-lg border border-outline-variant bg-surface-lowest p-4">
        <p className="flex-1 text-xs leading-relaxed text-foreground/70">{t('settings.csl_intro')}</p>
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={importing}
          className={cn(
            'inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90',
            importing && 'cursor-wait opacity-60',
          )}
        >
          {importing ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          {importing ? t('settings.csl_importing') : t('settings.csl_import')}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".csl,application/xml,text/xml"
          className="hidden"
          onChange={(event) => void handleFile(event.target.files?.[0] ?? null)}
        />
      </div>

      {notice && (
        <div className="flex items-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-600 dark:text-emerald-400">
          <CheckCircle2 size={14} />
          {notice}
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 text-xs text-error">
          <AlertCircle size={14} />
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-foreground/60">
          <Loader2 size={14} className="animate-spin" />
          {t('settings.csl_loading')}
        </div>
      ) : styles.length === 0 ? (
        <p className="text-xs text-foreground/50">{t('settings.csl_empty')}</p>
      ) : (
        <div className="space-y-2">
          {styles.map((style) => (
            <div
              key={style.id}
              className={cn(
                'flex items-center justify-between gap-3 rounded-lg border p-3 transition-colors',
                style.active
                  ? 'border-primary/45 bg-primary/10'
                  : 'border-outline-variant bg-surface hover:border-primary/30',
              )}
            >
              <button
                type="button"
                onClick={() => void handleActivate(style)}
                disabled={style.active || busyId === style.id}
                className="flex min-w-0 flex-1 items-center gap-3 text-left disabled:cursor-default"
              >
                <span
                  className={cn(
                    'flex h-5 w-5 shrink-0 items-center justify-center rounded-full border',
                    style.active ? 'border-primary bg-primary text-primary-foreground' : 'border-outline-variant',
                  )}
                >
                  {style.active && <Check size={12} />}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-foreground">{style.title}</span>
                  <span className="text-[10px] uppercase tracking-wider text-foreground/45">
                    {style.source === 'builtin' ? t('settings.csl_builtin') : t('settings.csl_uploaded')}
                    {style.active ? ` · ${t('settings.csl_active')}` : ''}
                  </span>
                </span>
              </button>
              <div className="flex shrink-0 items-center gap-2">
                {!style.active && (
                  <button
                    type="button"
                    onClick={() => void handleActivate(style)}
                    disabled={busyId === style.id}
                    className="rounded-md border border-outline-variant bg-surface-lowest px-2.5 py-1 text-[11px] font-medium text-foreground/70 transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-50"
                  >
                    {busyId === style.id ? <Loader2 size={12} className="animate-spin" /> : t('settings.csl_set_active')}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void handleDelete(style)}
                  disabled={!style.can_delete || busyId === style.id}
                  title={t('settings.csl_delete')}
                  aria-label={t('settings.csl_delete')}
                  className="rounded-md p-1.5 text-foreground/45 transition-colors hover:bg-rose-500/10 hover:text-rose-500 disabled:cursor-not-allowed disabled:opacity-30"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
