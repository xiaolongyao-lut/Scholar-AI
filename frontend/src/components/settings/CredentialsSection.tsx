import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Check,
  Edit3,
  Eye,
  EyeOff,
  Loader2,
  Plus,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import {
  type CredentialCategory,
  type CredentialProtocol,
  type CredentialTrustSource,
  type RuntimeCredentialCreate,
  type RuntimeCredentialPublic,
  type RuntimeCredentialUpdate,
  type CredentialTestResponse,
  createCredential,
  deleteCredential,
  listCredentials,
  testCredential,
  updateCredential,
} from '@/services/credentialsApi';

// ---------------------------------------------------------------------------
// Local UI state
// ---------------------------------------------------------------------------

type FormMode = 'idle' | 'create' | 'edit';

interface FormState {
  category: CredentialCategory;
  provider: string;
  model: string;
  base_url: string;
  protocol: CredentialProtocol;
  api_key: string;
  trust_source: CredentialTrustSource;
  enabled: boolean;
  notes: string;
}

const EMPTY_FORM: FormState = {
  category: 'generation',
  provider: '',
  model: '',
  base_url: '',
  protocol: 'openai_chat_completions',
  api_key: '',
  trust_source: 'runtime_untrusted_custom',
  enabled: true,
  notes: '',
};

const CATEGORY_OPTIONS: CredentialCategory[] = ['generation', 'embedding', 'rerank'];
const PROTOCOL_OPTIONS: CredentialProtocol[] = [
  'openai_chat_completions',
  'openai_responses',
  'anthropic_messages',
  'embeddings',
  'rerank',
];
const TRUST_OPTIONS: { value: CredentialTrustSource; label: string }[] = [
  { value: 'official_provider', label: 'Official provider (allowlisted host)' },
  { value: 'env_configured_gateway', label: 'Env-configured gateway (.env)' },
  { value: 'runtime_user_confirmed', label: 'Runtime — user confirmed trust' },
  { value: 'runtime_untrusted_custom', label: 'Runtime — untrusted (skip network)' },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CredentialsSection(): JSX.Element {
  const [list, setList] = useState<RuntimeCredentialPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<FormMode>('idle');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [revealKey, setRevealKey] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, CredentialTestResponse>>({});
  const [legacyKey, setLegacyKey] = useState<string | null>(null);
  const [pendingTrust, setPendingTrust] = useState<RuntimeCredentialPublic | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listCredentials();
      setList(data);
    } catch (exc) {
      setError(toMessage(exc));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Hard Constraint #15: never auto-upload localStorage api_key. Just show a CTA.
  useEffect(() => {
    try {
      const raw = localStorage.getItem('scholar-ai-settings');
      if (!raw) return;
      const parsed = JSON.parse(raw);
      const k = parsed?.llm?.apiKey;
      if (typeof k === 'string' && k.trim().length > 0) {
        setLegacyKey(k.trim());
      }
    } catch {
      /* ignore */
    }
  }, []);

  const onAddNew = () => {
    setMode('create');
    setEditingId(null);
    setForm(EMPTY_FORM);
    setRevealKey(false);
  };

  const onEdit = (cred: RuntimeCredentialPublic) => {
    setMode('edit');
    setEditingId(cred.credential_id);
    setForm({
      category: cred.category,
      provider: cred.provider,
      model: cred.model,
      base_url: cred.base_url,
      protocol: cred.protocol,
      api_key: '',
      trust_source: cred.trust_source,
      enabled: cred.enabled,
      notes: cred.notes ?? '',
    });
    setRevealKey(false);
  };

  const onCancel = () => {
    setMode('idle');
    setEditingId(null);
    setForm(EMPTY_FORM);
    setRevealKey(false);
  };

  const onSubmit = async () => {
    setError(null);
    setBusyId('__form__');
    try {
      if (mode === 'create') {
        const body: RuntimeCredentialCreate = {
          category: form.category,
          provider: form.provider.trim(),
          model: form.model.trim(),
          base_url: form.base_url.trim(),
          protocol: form.protocol,
          api_key: form.api_key,
          trust_source: form.trust_source,
          enabled: form.enabled,
          notes: form.notes,
        };
        await createCredential(body);
      } else if (mode === 'edit' && editingId) {
        const body: RuntimeCredentialUpdate = {
          provider: form.provider.trim() || undefined,
          model: form.model.trim() || undefined,
          base_url: form.base_url.trim() || undefined,
          protocol: form.protocol,
          trust_source: form.trust_source,
          enabled: form.enabled,
          notes: form.notes,
        };
        if (form.api_key.trim().length > 0) {
          body.api_key = form.api_key;
        }
        await updateCredential(editingId, body);
      }
      onCancel();
      await refresh();
    } catch (exc) {
      setError(toMessage(exc));
    } finally {
      setBusyId(null);
    }
  };

  const onDelete = async (cred: RuntimeCredentialPublic) => {
    if (!window.confirm(`Delete credential ${cred.provider}/${cred.model}?`)) {
      return;
    }
    setBusyId(cred.credential_id);
    try {
      await deleteCredential(cred.credential_id);
      await refresh();
    } catch (exc) {
      setError(toMessage(exc));
    } finally {
      setBusyId(null);
    }
  };

  const onTest = async (
    cred: RuntimeCredentialPublic,
    trustOverride?: CredentialTrustSource,
  ) => {
    setBusyId(cred.credential_id);
    try {
      const r = await testCredential(cred.credential_id, {
        trustSourceOverride: trustOverride,
      });
      setTestResult(prev => ({ ...prev, [cred.credential_id]: r }));
      // Hard Constraint #18: if untrusted, the user must explicitly confirm.
      if (
        r.status === 'skipped' &&
        cred.trust_source === 'runtime_untrusted_custom'
      ) {
        setPendingTrust(cred);
      }
    } catch (exc) {
      setError(toMessage(exc));
    } finally {
      setBusyId(null);
    }
  };

  const onConfirmTrust = async (cred: RuntimeCredentialPublic) => {
    setBusyId(cred.credential_id);
    try {
      // Persist the trust upgrade
      await updateCredential(cred.credential_id, {
        trust_source: 'runtime_user_confirmed',
      });
      setPendingTrust(null);
      await refresh();
      // Re-test now that trust has been upgraded
      await onTest(cred);
    } catch (exc) {
      setError(toMessage(exc));
    } finally {
      setBusyId(null);
    }
  };

  const onCancelTrust = () => {
    setPendingTrust(null);
  };

  const onImportLegacy = async () => {
    if (!legacyKey) return;
    if (
      !window.confirm(
        'Import the api key currently saved in browser localStorage as a new credential? You will be prompted to fill in provider/model details.',
      )
    ) {
      return;
    }
    setMode('create');
    setForm({
      ...EMPTY_FORM,
      api_key: legacyKey,
      trust_source: 'runtime_untrusted_custom',
      notes: 'imported from local browser settings',
    });
    setRevealKey(true);
    setLegacyKey(null);
    try {
      const raw = localStorage.getItem('scholar-ai-settings');
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (parsed?.llm) {
        delete parsed.llm.apiKey;
        localStorage.setItem('scholar-ai-settings', JSON.stringify(parsed));
      }
    } catch {
      /* ignore */
    }
  };

  // ------------------------------------------------------------------ render
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-headline text-base font-semibold text-foreground">
            API Credentials
          </h3>
          <p className="font-label text-[11px] text-foreground/50 mt-0.5">
            Multi-credential CRUD with masked storage. Secrets stay on this machine.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            aria-label="Reload credential list"
            className="p-2 text-foreground/60 hover:text-foreground rounded-md hover:bg-surface-high transition-colors"
            title="Reload"
          >
            {loading ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />}
          </button>
          <button
            type="button"
            onClick={onAddNew}
            className="flex items-center gap-1.5 bg-primary text-primary-foreground px-3 py-1.5 rounded-md text-xs font-medium hover:bg-primary/90 transition-all"
          >
            <Plus size={12} aria-hidden="true" /> New
          </button>
        </div>
      </div>

      {legacyKey && (
        <div className="border border-amber-300 bg-amber-50 rounded-lg p-3 flex items-start gap-3">
          <Upload size={14} className="text-amber-700 mt-0.5" aria-hidden="true" />
          <div className="flex-1">
            <p className="font-label text-xs text-amber-900 leading-relaxed">
              An API key was found in this browser&rsquo;s old localStorage settings.
              Import it as a managed credential? <strong>It will not be auto-imported.</strong>
            </p>
            <div className="flex gap-2 mt-2">
              <button
                type="button"
                onClick={onImportLegacy}
                className="text-[11px] font-medium px-2.5 py-1 bg-amber-700 text-white rounded hover:bg-amber-800"
              >
                Import and review
              </button>
              <button
                type="button"
                onClick={() => setLegacyKey(null)}
                className="text-[11px] font-medium px-2.5 py-1 bg-white text-amber-900 border border-amber-300 rounded hover:bg-amber-50"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div
          className="border border-red-300 bg-red-50 rounded-lg p-3 flex items-start gap-2"
          role="alert"
          aria-live="polite"
        >
          <ShieldAlert size={14} className="text-red-700 mt-0.5" aria-hidden="true" />
          <p className="font-label text-xs text-red-900 flex-1">{error}</p>
          <button
            type="button"
            onClick={() => setError(null)}
            aria-label="Dismiss error"
            className="text-red-700 hover:text-red-900"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      )}

      {mode !== 'idle' && (
        <CredentialForm
          mode={mode}
          form={form}
          onForm={setForm}
          revealKey={revealKey}
          onToggleReveal={() => setRevealKey(v => !v)}
          onCancel={onCancel}
          onSubmit={onSubmit}
          busy={busyId === '__form__'}
        />
      )}

      <div className="space-y-2">
        {list.length === 0 && !loading && (
          <div className="border border-dashed border-outline-variant rounded-lg p-6 text-center">
            <p className="font-label text-xs text-foreground/50">
              No credentials configured. Click &ldquo;New&rdquo; to add one.
            </p>
          </div>
        )}
        {list.map(cred => (
          <CredentialCard
            key={cred.credential_id}
            cred={cred}
            test={testResult[cred.credential_id]}
            busy={busyId === cred.credential_id}
            onEdit={() => onEdit(cred)}
            onDelete={() => onDelete(cred)}
            onTest={() => onTest(cred)}
            onConfirmTrust={
              pendingTrust && pendingTrust.credential_id === cred.credential_id
                ? () => onConfirmTrust(cred)
                : null
            }
            onCancelTrust={
              pendingTrust && pendingTrust.credential_id === cred.credential_id
                ? onCancelTrust
                : null
            }
          />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Form
// ---------------------------------------------------------------------------

interface CredentialFormProps {
  mode: FormMode;
  form: FormState;
  onForm: (next: FormState) => void;
  revealKey: boolean;
  onToggleReveal: () => void;
  onCancel: () => void;
  onSubmit: () => void;
  busy: boolean;
}

function CredentialForm({
  mode,
  form,
  onForm,
  revealKey,
  onToggleReveal,
  onCancel,
  onSubmit,
  busy,
}: CredentialFormProps) {
  const baseId = React.useId();
  const fieldId = (suffix: string) => `${baseId}-${suffix}`;
  return (
    <div className="border border-outline-variant rounded-lg p-4 bg-surface-low space-y-3">
      <h4 className="font-headline text-sm font-semibold text-foreground">
        {mode === 'create' ? 'Add credential' : 'Edit credential'}
      </h4>
      <div className="grid grid-cols-2 gap-3">
        <FormField label="Category" htmlFor={fieldId('category')}>
          <select
            id={fieldId('category')}
            value={form.category}
            onChange={e => onForm({ ...form, category: e.target.value as CredentialCategory })}
            className="w-full px-2 py-1.5 border border-outline rounded text-xs bg-surface"
          >
            {CATEGORY_OPTIONS.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </FormField>
        <FormField label="Provider" htmlFor={fieldId('provider')}>
          <input
            id={fieldId('provider')}
            type="text"
            value={form.provider}
            onChange={e => onForm({ ...form, provider: e.target.value })}
            placeholder="OpenAI / Anthropic / DeepSeek / ..."
            className="w-full px-2 py-1.5 border border-outline rounded text-xs bg-surface"
          />
        </FormField>
        <FormField label="Model" htmlFor={fieldId('model')}>
          <input
            id={fieldId('model')}
            type="text"
            value={form.model}
            onChange={e => onForm({ ...form, model: e.target.value })}
            placeholder="gpt-4o / claude-opus-4-7 / ..."
            className="w-full px-2 py-1.5 border border-outline rounded text-xs bg-surface"
          />
        </FormField>
        <FormField label="Protocol" htmlFor={fieldId('protocol')}>
          <select
            id={fieldId('protocol')}
            value={form.protocol}
            onChange={e => onForm({ ...form, protocol: e.target.value as CredentialProtocol })}
            className="w-full px-2 py-1.5 border border-outline rounded text-xs bg-surface"
          >
            {PROTOCOL_OPTIONS.map(p => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </FormField>
        <FormField label="Base URL" full htmlFor={fieldId('base-url')}>
          <input
            id={fieldId('base-url')}
            type="url"
            value={form.base_url}
            onChange={e => onForm({ ...form, base_url: e.target.value })}
            placeholder="https://api.openai.com/v1"
            className="w-full px-2 py-1.5 border border-outline rounded text-xs bg-surface font-mono"
          />
        </FormField>
        <FormField
          label={mode === 'edit' ? 'API key (leave blank to keep existing)' : 'API key'}
          full
          htmlFor={fieldId('api-key')}
        >
          <div className="flex gap-2">
            <input
              id={fieldId('api-key')}
              type={revealKey ? 'text' : 'password'}
              value={form.api_key}
              onChange={e => onForm({ ...form, api_key: e.target.value })}
              placeholder={mode === 'edit' ? '••••••••' : 'sk-...'}
              className="flex-1 px-2 py-1.5 border border-outline rounded text-xs bg-surface font-mono"
              autoComplete="off"
            />
            <button
              type="button"
              onClick={onToggleReveal}
              aria-label={revealKey ? 'Hide API key' : 'Reveal API key'}
              aria-pressed={revealKey}
              className="px-2 text-foreground/50 hover:text-foreground"
              title={revealKey ? 'Hide' : 'Reveal'}
            >
              {revealKey ? <EyeOff size={14} aria-hidden="true" /> : <Eye size={14} aria-hidden="true" />}
            </button>
          </div>
        </FormField>
        <FormField label="Trust source" full htmlFor={fieldId('trust')}>
          <select
            id={fieldId('trust')}
            value={form.trust_source}
            onChange={e => onForm({ ...form, trust_source: e.target.value as CredentialTrustSource })}
            className="w-full px-2 py-1.5 border border-outline rounded text-xs bg-surface"
          >
            {TRUST_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </FormField>
        <FormField label="Notes" full htmlFor={fieldId('notes')}>
          <input
            id={fieldId('notes')}
            type="text"
            value={form.notes}
            onChange={e => onForm({ ...form, notes: e.target.value })}
            placeholder="optional"
            className="w-full px-2 py-1.5 border border-outline rounded text-xs bg-surface"
          />
        </FormField>
        <FormField label="Enabled" htmlFor={fieldId('enabled')}>
          <input
            id={fieldId('enabled')}
            type="checkbox"
            checked={form.enabled}
            onChange={e => onForm({ ...form, enabled: e.target.checked })}
            className="h-4 w-4"
          />
        </FormField>
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="px-3 py-1.5 text-xs font-medium border border-outline rounded hover:bg-surface-high"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onSubmit}
          disabled={busy}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-60"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
          {mode === 'create' ? 'Create' : 'Save'}
        </button>
      </div>
    </div>
  );
}

function FormField({
  label,
  full,
  htmlFor,
  children,
}: {
  label: string;
  full?: boolean;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={full ? 'col-span-2 space-y-1' : 'space-y-1'}>
      <label
        htmlFor={htmlFor}
        className="font-label text-[10px] font-medium text-foreground/60 uppercase tracking-wide"
      >
        {label}
      </label>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

function CredentialCard({
  cred,
  test,
  busy,
  onEdit,
  onDelete,
  onTest,
  onConfirmTrust,
  onCancelTrust,
}: {
  cred: RuntimeCredentialPublic;
  test?: CredentialTestResponse;
  busy: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onTest: () => void;
  onConfirmTrust: (() => void) | null;
  onCancelTrust: (() => void) | null;
}) {
  const trustBadge = useMemo(() => trustBadgeFor(cred.trust_source), [cred.trust_source]);
  return (
    <div className="border border-outline-variant rounded-lg p-3 bg-surface-low">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-headline text-sm font-semibold text-foreground">
              {cred.provider} / {cred.model}
            </span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${trustBadge.cls}`}>
              {trustBadge.label}
            </span>
            <span className="text-[10px] text-foreground/40">{cred.category}</span>
            {!cred.enabled && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-foreground/10 text-foreground/60">
                disabled
              </span>
            )}
          </div>
          <p className="font-mono text-[11px] text-foreground/60 mt-1 truncate">
            {cred.base_url} · {cred.api_key_masked || '(no key)'}
          </p>
          {cred.notes && (
            <p className="font-label text-[11px] text-foreground/50 mt-1">{cred.notes}</p>
          )}
          {test && (
            <CredentialTestBadge result={test} />
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={onTest}
            disabled={busy}
            aria-label={`Test endpoint for ${cred.provider} ${cred.model}`}
            className="p-1.5 text-foreground/60 hover:text-primary rounded hover:bg-surface-high"
            title="Test endpoint"
          >
            {busy ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <ShieldCheck size={14} aria-hidden="true" />}
          </button>
          <button
            type="button"
            onClick={onEdit}
            disabled={busy}
            aria-label={`Edit ${cred.provider} ${cred.model}`}
            className="p-1.5 text-foreground/60 hover:text-primary rounded hover:bg-surface-high"
            title="Edit"
          >
            <Edit3 size={14} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={busy}
            aria-label={`Delete ${cred.provider} ${cred.model}`}
            className="p-1.5 text-foreground/60 hover:text-red-600 rounded hover:bg-red-50"
            title="Delete"
          >
            <Trash2 size={14} aria-hidden="true" />
          </button>
        </div>
      </div>

      {onConfirmTrust && onCancelTrust && (
        <div
          className="mt-3 border-t border-outline-variant pt-3 flex items-start gap-2"
          role="alertdialog"
          aria-label="Trust this endpoint"
        >
          <ShieldAlert size={14} className="text-amber-700 mt-0.5" aria-hidden="true" />
          <div className="flex-1">
            <p className="font-label text-xs text-foreground/80">
              This endpoint is marked untrusted. Network test was skipped.
              Confirm to trust it for this machine and re-test now.
            </p>
            <div className="flex gap-2 mt-2">
              <button
                type="button"
                onClick={onConfirmTrust}
                className="text-[11px] font-medium px-2.5 py-1 bg-primary text-primary-foreground rounded hover:bg-primary/90"
              >
                Import and Trust
              </button>
              <button
                type="button"
                onClick={onCancelTrust}
                className="text-[11px] font-medium px-2.5 py-1 bg-surface border border-outline rounded hover:bg-surface-high"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CredentialTestBadge({ result }: { result: CredentialTestResponse }) {
  const tone = (() => {
    switch (result.status) {
      case 'ok':
        return 'bg-emerald-50 text-emerald-700 border border-emerald-200';
      case 'skipped':
        return 'bg-amber-50 text-amber-800 border border-amber-200';
      case 'rejected':
        return 'bg-red-50 text-red-800 border border-red-200';
      case 'probe_failed':
      default:
        return 'bg-foreground/5 text-foreground/70 border border-outline-variant';
    }
  })();
  const detail = result.probe?.status_code
    ? `HTTP ${result.probe.status_code}`
    : result.reason ?? '';
  return (
    <p
      role="status"
      className={`mt-2 inline-block text-[10px] font-medium px-2 py-0.5 rounded ${tone}`}
    >
      {result.status}{detail ? ` · ${detail}` : ''}
    </p>
  );
}

function trustBadgeFor(t: CredentialTrustSource): { label: string; cls: string } {
  switch (t) {
    case 'official_provider':
      return { label: 'official', cls: 'bg-emerald-50 text-emerald-700' };
    case 'env_configured_gateway':
      return { label: 'env', cls: 'bg-blue-50 text-blue-700' };
    case 'runtime_user_confirmed':
      return { label: 'trusted', cls: 'bg-emerald-50 text-emerald-700' };
    case 'runtime_untrusted_custom':
      return { label: 'untrusted', cls: 'bg-amber-50 text-amber-800' };
  }
}

function toMessage(exc: unknown): string {
  if (typeof exc === 'object' && exc && 'message' in exc) {
    const e = exc as { response?: { data?: { detail?: string } }; message?: string };
    if (e.response?.data?.detail) return e.response.data.detail;
    return e.message ?? 'unknown error';
  }
  return String(exc);
}

export default CredentialsSection;
