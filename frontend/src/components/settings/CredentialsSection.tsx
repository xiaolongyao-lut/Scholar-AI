import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  Check,
  ChevronRight,
  Download,
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
  Zap,
} from 'lucide-react';
import {
  type CredentialCategory,
  isCredentialNotFoundError,
  type CredentialProtocol,
  type CredentialStrategyHint,
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
import { discoverModels, type DiscoveredModel } from '@/services/chatApi';
import { cn } from '@/lib/utils';

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
  strategy_hint: CredentialStrategyHint;
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
  strategy_hint: 'medium',
  // 2026-05-24: default to runtime_user_confirmed so a freshly-created
  // credential pointing at a third-party / NewAPI / sub2api gateway is
  // usable immediately — the prior `runtime_untrusted_custom` default
  // showed a confusing internal rejection badge until the user manually
  // re-saved with a different trust source.
  trust_source: 'runtime_user_confirmed',
  enabled: true,
  notes: '',
};

const CATEGORY_OPTIONS: CredentialCategory[] = ['generation', 'embedding', 'rerank'];
const CATEGORY_LABELS: Record<CredentialCategory, string> = {
  generation: '研读和写作',
  embedding: '语义召回',
  rerank: '语义精排',
};
const PROTOCOL_OPTIONS: CredentialProtocol[] = [
  'openai_chat_completions',
  'openai_responses',
  'anthropic_messages',
  'embeddings',
  'rerank',
];
const PROTOCOL_LABELS: Record<CredentialProtocol, string> = {
  openai_chat_completions: '聊天补全兼容',
  openai_responses: '响应式兼容',
  anthropic_messages: '消息协议兼容',
  embeddings: '向量嵌入',
  rerank: '重排序',
};
const TRUST_OPTIONS: { value: CredentialTrustSource; label: string }[] = [
  { value: 'official_provider', label: '官方服务商' },
  { value: 'env_configured_gateway', label: '环境配置网关' },
  { value: 'runtime_user_confirmed', label: '本机已确认' },
  { value: 'runtime_untrusted_custom', label: '本机待确认' },
];
const STRATEGY_OPTIONS: { value: CredentialStrategyHint; label: string; hint: string }[] = [
  { value: 'low', label: '低', hint: '低成本、短问答优先' },
  { value: 'medium', label: '中', hint: '默认平衡档' },
  { value: 'high', label: '高', hint: '复杂分析与长证据' },
  { value: 'xhigh', label: 'XHigh', hint: 'Codex 路由优先' },
  { value: 'max', label: 'Max', hint: 'Claude Max 路由优先' },
];
const INPUT_CLASS = 'min-w-0 max-w-full w-full rounded-lg border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground transition-colors placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none disabled:opacity-60';

function defaultProtocolForCategory(category: CredentialCategory): CredentialProtocol {
  if (category === 'embedding') {
    return 'embeddings';
  }
  if (category === 'rerank') {
    return 'rerank';
  }
  return 'openai_chat_completions';
}

function canonicalStrategyHint(value: CredentialStrategyHint | string | null | undefined): CredentialStrategyHint {
  const normalized = String(value ?? '').trim().toLowerCase();
  if (normalized === 'low' || normalized === 'cheap' || normalized === 'save' || normalized === 'aggressive') {
    return 'low';
  }
  if (normalized === 'high' || normalized === 'quality' || normalized === 'high-quality' || normalized === 'high_quality') {
    return 'high';
  }
  if (normalized === 'xhigh') {
    return 'xhigh';
  }
  if (normalized === 'max') {
    return 'max';
  }
  return 'medium';
}

export function strategyHintLabel(value: CredentialStrategyHint | string | null | undefined): string {
  const canonical = canonicalStrategyHint(value);
  return STRATEGY_OPTIONS.find(option => option.value === canonical)?.label ?? '中';
}

function strategyHintDescription(value: CredentialStrategyHint | string | null | undefined): string {
  const canonical = canonicalStrategyHint(value);
  const option = STRATEGY_OPTIONS.find(item => item.value === canonical);
  return option ? `${option.label} · ${option.hint}` : '中 · 默认平衡档';
}

const CREDENTIAL_INTERNAL_TEXT_PATTERN =
  /(?:\/api\/|https?:\/\/|[A-Za-z]:[\\/]|api[_-]?key|base[_-]?url|authorization|bearer|token|secret|env=|env_refs|sk-[A-Za-z0-9_-]+|\b[a-z]+(?:_[a-z0-9]+){1,}\b|[{}[\]"`]|[A-Za-z0-9+/]{32,}={0,2})/i;

export function sanitizeCredentialVisibleText(value: unknown, fallback: string): string {
  const raw = typeof value === 'string' ? value.trim() : '';
  if (!raw || raw.length > 180 || CREDENTIAL_INTERNAL_TEXT_PATTERN.test(raw)) {
    return fallback;
  }
  return raw;
}

export function formatCredentialProbeError(
  value: unknown,
  fallback = '连接失败，请检查服务地址、访问密钥和接口协议。',
): string {
  return sanitizeCredentialVisibleText(value, fallback);
}

export function formatCredentialCardSecondary(credential: Pick<RuntimeCredentialPublic, 'base_url' | 'has_api_key'>): string {
  const address = credential.base_url.trim() ? '服务地址已填写' : '未填写服务地址';
  const secret = credential.has_api_key ? '访问密钥已保存' : '未保存访问密钥';
  return `${address} · ${secret}`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Renders the reusable API credential manager.
 *
 * The component keeps credential material in the existing backend credential API and only
 * edits masked/public credential metadata on screen unless the user enters a
 * new access credential explicitly.
 */
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

  const handleMissingCredential = useCallback(async (credentialId: string) => {
    setMode('idle');
    setEditingId(null);
    setForm(EMPTY_FORM);
    setRevealKey(false);
    setPendingTrust(current => (
      current?.credential_id === credentialId ? null : current
    ));
    setTestResult(current => {
      if (!(credentialId in current)) {
        return current;
      }
      const next = { ...current };
      delete next[credentialId];
      return next;
    });
    await refresh();
  }, [refresh]);

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
      strategy_hint: canonicalStrategyHint(cred.strategy_hint),
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
          strategy_hint: form.strategy_hint,
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
          strategy_hint: form.strategy_hint,
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
      if (mode === 'edit' && editingId && isCredentialNotFoundError(exc)) {
        await handleMissingCredential(editingId);
        setError('该 API 凭证已不存在，列表已刷新。请重新选择或新建凭证。');
      } else {
        setError(toMessage(exc));
      }
    } finally {
      setBusyId(null);
    }
  };

  const onDelete = async (cred: RuntimeCredentialPublic) => {
    if (!window.confirm(`确认删除 ${cred.provider}/${cred.model}？`)) {
      return;
    }
    setBusyId(cred.credential_id);
    try {
      await deleteCredential(cred.credential_id);
      await refresh();
      if (editingId === cred.credential_id) {
        onCancel();
      }
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
      await onTest({ ...cred, trust_source: 'runtime_user_confirmed' });
    } catch (exc) {
      if (isCredentialNotFoundError(exc)) {
        await handleMissingCredential(cred.credential_id);
        setError('该 API 凭证已不存在，列表已刷新。请重新选择或新建凭证。');
      } else {
        setError(toMessage(exc));
      }
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
        '浏览器旧设置里发现了一个访问密钥。是否作为新的 API 配置导入并补全提供商与模型？',
      )
    ) {
      return;
    }
    setMode('create');
    setForm({
      ...EMPTY_FORM,
      api_key: legacyKey,
      notes: '从浏览器旧设置导入',
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

  const selectedCredential = useMemo(
    () => (editingId ? list.find(cred => cred.credential_id === editingId) ?? null : null),
    [editingId, list],
  );
  const selectedStatusBadge = useMemo(
    () => selectedCredential
      ? credentialStatusBadge(selectedCredential, testResult[selectedCredential.credential_id])
      : null,
    [selectedCredential, testResult],
  );
  const detailOpen = mode !== 'idle';
  const detailTitle = mode === 'create'
    ? '新增 API'
    : selectedCredential
      ? `${selectedCredential.provider || '未命名提供商'} / ${selectedCredential.model || '未填模型'}`
      : '编辑 API';
  const detailSubtitle = mode === 'create'
    ? '创建后会出现在列表中，可被研读和写作、语义路由和多智能体复用。'
    : selectedCredential
      ? `${CATEGORY_LABELS[selectedCredential.category]} · ${formatCredentialCardSecondary(selectedCredential)}`
      : '该 API 凭证可能已被删除，请返回列表刷新。';

  // ------------------------------------------------------------------ render
  return (
    <div className="rounded-lg border border-outline-variant bg-surface-lowest p-4 shadow-sm">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 className="font-headline text-base font-semibold text-foreground">
            API 凭证
          </h3>
          <p className="mt-1 font-label text-xs text-foreground/45">
            统一管理可复用的提供商、服务地址、模型、密钥和调用档位。
          </p>
        </div>
        {!detailOpen ? (
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={refresh}
              disabled={loading}
              aria-label="刷新 API 列表"
              className="rounded-md p-2 text-foreground/60 transition-colors hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              title="刷新"
            >
              {loading ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />}
            </button>
            <button
              type="button"
              onClick={onAddNew}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
              <Plus size={12} aria-hidden="true" /> 新增
            </button>
          </div>
        ) : null}
      </div>
      {legacyKey && (
        <div className="mb-4 flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 dark:border-amber-700/40 dark:bg-amber-500/15">
          <Upload size={14} className="mt-0.5 text-amber-700 dark:text-amber-300" aria-hidden="true" />
          <div className="flex-1">
            <p className="font-label text-xs leading-relaxed text-amber-900 dark:text-amber-200">
              浏览器旧设置里发现了一个访问密钥。可以导入为本机 API 配置，系统不会自动导入。
            </p>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                onClick={onImportLegacy}
                className="text-[11px] font-medium px-2.5 py-1 bg-amber-700 text-white rounded hover:bg-amber-800 dark:bg-amber-500 dark:text-amber-950 dark:hover:bg-amber-400"
              >
                导入并检查
              </button>
              <button
                type="button"
                onClick={() => setLegacyKey(null)}
                className="text-[11px] font-medium px-2.5 py-1 bg-white text-amber-900 border border-amber-300 rounded hover:bg-amber-50 dark:border-amber-700/40 dark:bg-amber-500/10 dark:text-amber-200 dark:hover:bg-amber-500/15"
              >
                忽略
              </button>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div
          className="mb-4 flex items-start gap-2 rounded-lg border border-red-300 bg-red-50 p-3 dark:border-red-700/40 dark:bg-red-500/15"
          role="alert"
          aria-live="polite"
        >
          <ShieldAlert size={14} className="mt-0.5 text-red-700 dark:text-red-300" aria-hidden="true" />
          <p className="flex-1 font-label text-xs text-red-900 dark:text-red-200">{error}</p>
          <button
            type="button"
            onClick={() => setError(null)}
            aria-label="关闭错误"
            className="text-red-700 hover:text-red-900 dark:text-red-300 dark:hover:text-red-200"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      )}

      {!detailOpen ? (
        <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
          {loading && list.length === 0 ? (
            <div className="rounded-lg border border-outline-variant/50 bg-surface-low px-3 py-4 text-center text-xs text-foreground/45 sm:col-span-2">
              <Loader2 size={14} className="mx-auto mb-2 animate-spin" aria-hidden="true" />
              正在加载 API 凭证
            </div>
          ) : null}

          {list.length === 0 && !loading ? (
            <div className="rounded-lg border border-dashed border-outline-variant/70 bg-surface-low px-4 py-8 text-center sm:col-span-2">
              <p className="font-label text-xs text-foreground/50">
                还没有保存 API。点击“新增”添加一套配置。
              </p>
              <button
                type="button"
                onClick={onAddNew}
                className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                <Plus size={12} aria-hidden="true" /> 新增 API
              </button>
            </div>
          ) : null}

          {list.map(cred => (
            <CredentialListItem
              key={cred.credential_id}
              cred={cred}
              active={false}
              test={testResult[cred.credential_id]}
              busy={busyId === cred.credential_id}
              onSelect={() => onEdit(cred)}
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
      ) : (
        <div className="min-w-0 space-y-4 rounded-lg border border-outline-variant/50 bg-surface-low p-4 sm:p-5">
          <div className="flex flex-col gap-3 border-b border-outline-variant/40 pb-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <button
                type="button"
                onClick={onCancel}
                className="mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-outline-variant bg-surface-lowest text-foreground/60 transition-colors hover:border-primary/35 hover:text-primary"
                aria-label="返回 API 列表"
                title="返回"
              >
                <ArrowLeft size={15} aria-hidden="true" />
              </button>
              <div className="min-w-0">
                <h4 className="truncate font-headline text-sm font-semibold text-foreground">
                  {detailTitle}
                </h4>
                <p className="mt-0.5 text-[11px] leading-relaxed text-foreground/45">
                  {detailSubtitle}
                </p>
              </div>
            </div>
            {mode === 'edit' && selectedCredential && selectedStatusBadge ? (
              <span
                className={cn('inline-flex w-fit max-w-full items-center truncate rounded-md px-2 py-1 text-[10px]', selectedStatusBadge.cls)}
                title={selectedStatusBadge.label}
              >
                {selectedStatusBadge.label}
              </span>
            ) : null}
          </div>

          {mode === 'edit' && !selectedCredential ? (
            <div className="rounded-lg border border-dashed border-outline-variant/70 bg-surface-lowest px-4 py-8 text-center">
              <p className="font-label text-xs text-foreground/50">
                该 API 凭证已不在当前列表中。返回列表刷新后重新选择。
              </p>
            </div>
          ) : (
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
        </div>
      )}
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
  const [discovering, setDiscovering] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const [discovered, setDiscovered] = useState<DiscoveredModel[] | null>(null);
  const [testing, setTesting] = useState(false);
  const [testMessage, setTestMessage] = useState<string | null>(null);

  // Subsystem mapping: a credential's category drives which /api/{x}/models/
  // discover backend endpoint we call. Generation → chat;
  // embedding/rerank pass through verbatim.
  const subsystem: 'chat' | 'embedding' | 'rerank' =
    form.category === 'generation' ? 'chat' : form.category;

  const handleDiscover = useCallback(async () => {
    if (!form.base_url.trim()) {
      setDiscoverError('请先填写服务地址');
      return;
    }
    setDiscovering(true);
    setDiscoverError(null);
    setDiscovered(null);
    try {
      const result = await discoverModels(form.base_url, form.api_key, subsystem);
      if (!result.ok) {
        setDiscoverError(formatCredentialProbeError(result.error, '未能获取模型列表，请检查服务配置。'));
        return;
      }
      setDiscovered(result.models);
      if (result.models.length === 0) {
        setDiscoverError('上游返回空列表 — 请确认访问密钥与接口协议是否匹配');
      }
    } catch (err) {
      setDiscoverError(formatCredentialProbeError(err instanceof Error ? err.message : String(err), '未能获取模型列表，请稍后重试。'));
    } finally {
      setDiscovering(false);
    }
  }, [form.base_url, form.api_key, subsystem]);

  const handleTestConnection = useCallback(async () => {
    if (!form.base_url.trim()) {
      setTestMessage('请先填写服务地址');
      return;
    }
    setTesting(true);
    setTestMessage(null);
    try {
      // 2026-05-24: parity with 「研读和写作」 — probe directly from form
      // data (base_url + api_key) without requiring a saved credential id.
      // Reuses `/api/{subsystem}/models/discover` which already does an
      // authenticated GET against the upstream and returns ok/error.
      // Works in both create and edit modes; lets the user verify the
      // endpoint *before* committing the form.
      const result = await discoverModels(form.base_url, form.api_key, subsystem);
      if (result.ok) {
        const count = result.models.length;
        setTestMessage(
          count > 0
            ? `✓ 连接正常 · 上游返回 ${count} 个可用模型`
            : '✓ 连接正常',
        );
      } else {
        setTestMessage(`✗ ${formatCredentialProbeError(result.error)}`);
      }
    } catch (err) {
      setTestMessage(`✗ ${formatCredentialProbeError(err instanceof Error ? err.message : String(err))}`);
    } finally {
      setTesting(false);
    }
  }, [form.base_url, form.api_key, subsystem]);

  return (
    <div className="space-y-4">
      <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
        <FormField label="用途" htmlFor={fieldId('category')}>
          <select
            id={fieldId('category')}
            value={form.category}
            onChange={e => {
              const category = e.target.value as CredentialCategory;
              onForm({ ...form, category, protocol: defaultProtocolForCategory(category) });
            }}
            className={INPUT_CLASS}
          >
            {CATEGORY_OPTIONS.map(c => (
              <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>
            ))}
          </select>
        </FormField>
        <FormField label="提供商" htmlFor={fieldId('provider')}>
          <input
            id={fieldId('provider')}
            type="text"
            value={form.provider}
            onChange={e => onForm({ ...form, provider: e.target.value })}
            placeholder="任意兼容服务名称，可手动填写"
            className={INPUT_CLASS}
          />
        </FormField>
        <FormField label="模型" htmlFor={fieldId('model')}>
          <div className="flex min-w-0 gap-1.5">
            <input
              id={fieldId('model')}
              type="text"
              value={form.model}
              onChange={e => onForm({ ...form, model: e.target.value })}
              placeholder="填写服务提供的模型名称"
              className="min-w-0 flex-1 rounded border border-outline bg-surface px-2 py-1.5 text-xs"
            />
            <button
              type="button"
              onClick={handleDiscover}
              disabled={discovering || !form.base_url.trim()}
              title="尝试从服务地址读取可用模型"
              className="inline-flex shrink-0 items-center gap-1 rounded border border-outline px-2 py-1.5 text-[11px] font-medium text-foreground/75 hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
            >
              {discovering ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
              获取模型
            </button>
          </div>
          {discoverError && (
            <p className="mt-1 text-[10px] text-amber-700 dark:text-amber-300">⚠ {discoverError}</p>
          )}
          {discovered && discovered.length > 0 && (
            <div className="mt-1 max-h-40 overflow-auto rounded border border-outline-variant bg-surface-lowest">
              {discovered.map(m => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => {
                    onForm({ ...form, model: m.id });
                    setDiscovered(null);
                    setDiscoverError(null);
                  }}
                  className="w-full min-w-0 truncate px-2 py-1 text-left font-mono text-[11px] text-foreground/85 hover:bg-primary/10"
                  title={m.description || m.name}
                >
                  {m.id}
                  {m.name && m.name !== m.id && (
                    <span className="ml-1.5 text-foreground/40">— {m.name}</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </FormField>
        <FormField label="协议" htmlFor={fieldId('protocol')}>
          <select
            id={fieldId('protocol')}
            value={form.protocol}
            onChange={e => onForm({ ...form, protocol: e.target.value as CredentialProtocol })}
            className={INPUT_CLASS}
          >
            {PROTOCOL_OPTIONS.map(p => (
              <option key={p} value={p}>{PROTOCOL_LABELS[p]}</option>
            ))}
          </select>
        </FormField>
        <FormField label="调用档位" htmlFor={fieldId('strategy')}>
          <select
            id={fieldId('strategy')}
            value={form.strategy_hint}
            onChange={e => onForm({ ...form, strategy_hint: e.target.value as CredentialStrategyHint })}
            className={INPUT_CLASS}
          >
            {STRATEGY_OPTIONS.map(option => (
              <option key={option.value} value={option.value}>
                {option.label} · {option.hint}
              </option>
            ))}
          </select>
          <p className="mt-1 text-[10px] leading-relaxed text-foreground/45">
            {strategyHintDescription(form.strategy_hint)}。低/中/高控制成本与上下文预算；XHigh 和 Max 用于区分 Codex、Claude Max 等高预算模型路由。
          </p>
        </FormField>
        <FormField label="服务地址" full htmlFor={fieldId('base-url')}>
          <input
            id={fieldId('base-url')}
            type="url"
            value={form.base_url}
            onChange={e => onForm({ ...form, base_url: e.target.value })}
            placeholder="填写兼容服务地址"
            className={`${INPUT_CLASS} font-mono text-xs`}
          />
          <p className="mt-1 text-[10px] text-foreground/50">
            请按服务商文档填写兼容地址；官方、聚合或本地服务都可以手动填写，无需固定域名。
          </p>
        </FormField>
        <FormField
          label={mode === 'edit' ? '访问密钥（留空保留当前值）' : '访问密钥'}
          full
          htmlFor={fieldId('api-key')}
        >
          <div className="flex min-w-0 gap-2">
            <input
              id={fieldId('api-key')}
              type={revealKey ? 'text' : 'password'}
              value={form.api_key}
              onChange={e => onForm({ ...form, api_key: e.target.value })}
              placeholder={mode === 'edit' ? '已保存，留空保留' : '粘贴服务提供的访问密钥'}
              className="min-w-0 flex-1 rounded-lg border border-outline-variant/50 bg-surface-high px-3 py-2 font-mono text-xs text-foreground transition-colors placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none disabled:opacity-60"
              autoComplete="off"
            />
            <button
              type="button"
              onClick={onToggleReveal}
              aria-label={revealKey ? '隐藏访问密钥' : '显示访问密钥'}
              aria-pressed={revealKey}
              className="px-2 text-foreground/50 hover:text-foreground"
              title={revealKey ? '隐藏' : '显示'}
            >
              {revealKey ? <EyeOff size={14} aria-hidden="true" /> : <Eye size={14} aria-hidden="true" />}
            </button>
          </div>
        </FormField>
        <FormField label="信任来源" full htmlFor={fieldId('trust')}>
          <select
            id={fieldId('trust')}
            value={form.trust_source}
            onChange={e => onForm({ ...form, trust_source: e.target.value as CredentialTrustSource })}
            className={INPUT_CLASS}
          >
            {TRUST_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </FormField>
        <FormField label="备注" full htmlFor={fieldId('notes')}>
          <input
            id={fieldId('notes')}
            type="text"
            value={form.notes}
            onChange={e => onForm({ ...form, notes: e.target.value })}
            placeholder="可选"
            className={INPUT_CLASS}
          />
        </FormField>
        <FormField label="启用" htmlFor={fieldId('enabled')}>
          <input
            id={fieldId('enabled')}
            type="checkbox"
            checked={form.enabled}
            onChange={e => onForm({ ...form, enabled: e.target.checked })}
            className="h-4 w-4"
          />
        </FormField>
      </div>
      <div className="flex flex-col gap-2 pt-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex-1 min-w-0">
          {testMessage && (
            <p
              className={`text-[11px] truncate ${
                testMessage.startsWith('✓')
                  ? 'text-emerald-700 dark:text-emerald-300'
                  : 'text-rose-700 dark:text-rose-300'
              }`}
              title={testMessage}
            >
              {testMessage}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <button
            type="button"
            onClick={handleTestConnection}
            disabled={busy || testing || !form.base_url.trim()}
            title="用当前表单的服务地址与访问密钥实时探测上游(不需要先保存)"
            className="flex items-center gap-1.5 rounded-lg border border-outline-variant/50 bg-surface-high px-3 py-2 text-xs font-medium text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary disabled:opacity-60"
          >
            {testing ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
            测试连接
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-lg border border-outline-variant/50 bg-surface-high px-3 py-2 text-xs font-medium text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary disabled:opacity-60"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
          >
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
            {mode === 'create' ? '创建' : '保存'}
          </button>
        </div>
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
    <div className={full ? 'min-w-0 space-y-1 md:col-span-2' : 'min-w-0 space-y-1'}>
      <label
        htmlFor={htmlFor}
        className="font-label text-[11px] font-medium text-foreground/65"
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

function CredentialListItem({
  cred,
  active,
  test,
  busy,
  onSelect,
  onEdit,
  onDelete,
  onTest,
  onConfirmTrust,
  onCancelTrust,
}: {
  cred: RuntimeCredentialPublic;
  active: boolean;
  test?: CredentialTestResponse;
  busy: boolean;
  onSelect: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onTest: () => void;
  onConfirmTrust: (() => void) | null;
  onCancelTrust: (() => void) | null;
}) {
  const statusBadge = useMemo(() => credentialStatusBadge(cred, test), [cred, test]);
  return (
    <div
      className={cn(
        'group rounded-lg border p-3 transition-colors',
        active
          ? 'border-primary/45 bg-primary/10 text-primary'
          : 'border-outline-variant/50 bg-surface-low hover:border-primary/30 hover:bg-surface-high',
      )}
    >
      <div className="flex min-w-0 items-start gap-2">
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={onSelect}
            className="block w-full min-w-0 text-left"
            aria-pressed={active}
          >
            <span className="block truncate text-sm font-semibold">
              {cred.provider || '(未命名提供商)'}
            </span>
            <span className="mt-1 block truncate font-mono text-[11px] text-foreground/45">
              {cred.model || '(未填模型)'}
            </span>
          </button>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span
              className={cn('max-w-full truncate rounded px-1.5 py-0.5 text-[10px]', statusBadge.cls)}
              title={statusBadge.label}
            >
              {statusBadge.label}
            </span>
            <span className="rounded bg-surface-lowest px-1.5 py-0.5 text-[10px] text-foreground/45">
              {CATEGORY_LABELS[cred.category]}
            </span>
            <span className="rounded bg-surface-lowest px-1.5 py-0.5 text-[10px] text-foreground/45">
              档位 {strategyHintLabel(cred.strategy_hint)}
            </span>
            {!cred.enabled && (
              <span className="rounded bg-foreground/10 px-1.5 py-0.5 text-[10px] text-foreground/60">
                已停用
              </span>
            )}
          </div>
          <p className="mt-2 truncate font-mono text-[10px] text-foreground/40">
            {formatCredentialCardSecondary(cred)}
          </p>
          {cred.notes && (
            <p className="mt-1 truncate font-label text-[10px] text-foreground/45">{cred.notes}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={onTest}
            disabled={busy}
            aria-label={`测试 ${cred.provider} ${cred.model}`}
            className="p-1.5 text-foreground/60 hover:text-primary rounded hover:bg-surface-high"
            title="测试连接"
          >
            {busy ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <ShieldCheck size={14} aria-hidden="true" />}
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={busy}
            aria-label={`删除 ${cred.provider} ${cred.model}`}
            className="p-1.5 text-foreground/60 hover:text-red-600 rounded hover:bg-red-50 dark:hover:bg-red-500/15 dark:hover:text-red-300"
            title="删除"
          >
            <Trash2 size={14} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={onEdit}
            disabled={busy}
            aria-label={`进入 ${cred.provider} ${cred.model} 详情`}
            className="p-1.5 text-foreground/50 hover:text-primary rounded hover:bg-surface-high"
            title="进入详情"
          >
            <ChevronRight size={14} aria-hidden="true" />
          </button>
        </div>
      </div>

      {onConfirmTrust && onCancelTrust && (
        <div
          className="mt-3 flex items-start gap-2 border-t border-outline-variant pt-3"
          role="alertdialog"
          aria-label="Trust this endpoint"
        >
          <ShieldAlert size={14} className="mt-0.5 text-amber-700 dark:text-amber-300" aria-hidden="true" />
          <div className="flex-1">
            <p className="font-label text-xs text-foreground/80">
              这个端点还没有被信任，因此跳过了网络测试。确认后会在本机信任并重新测试。
            </p>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                onClick={onConfirmTrust}
                className="text-[11px] font-medium px-2.5 py-1 bg-primary text-primary-foreground rounded hover:bg-primary/90"
              >
                信任并测试
              </button>
              <button
                type="button"
                onClick={onCancelTrust}
                className="text-[11px] font-medium px-2.5 py-1 bg-surface border border-outline rounded hover:bg-surface-high"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function credentialStatusBadge(
  cred: RuntimeCredentialPublic,
  test: CredentialTestResponse | undefined,
): { label: string; cls: string } {
  if (!cred.enabled) {
    return { label: '已停用', cls: 'bg-foreground/10 text-foreground/60' };
  }
  if (test?.status === 'rejected') {
    const reason = formatCredentialProbeError(
      test.reason?.trim() || test.decision.reason,
      '策略拒绝，请确认服务来源或信任设置。',
    );
    return { label: `已拦截 · ${reason}`, cls: 'bg-red-50 text-red-800 dark:bg-red-500/15 dark:text-red-300' };
  }
  if (test?.status === 'probe_failed') {
    const reason = formatCredentialProbeError(test.probe?.error || test.reason);
    return { label: `连接失败 · ${reason}`, cls: 'bg-amber-50 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300' };
  }
  if (cred.trust_source === 'runtime_untrusted_custom') {
    return { label: '已拦截 · 待确认', cls: 'bg-amber-50 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300' };
  }
  return { label: '已信任', cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' };
}

function toMessage(exc: unknown): string {
  if (typeof exc === 'object' && exc && 'message' in exc) {
    const e = exc as { response?: { data?: { detail?: string } }; message?: string };
    return formatCredentialProbeError(e.response?.data?.detail ?? e.message, '操作失败，请稍后重试。');
  }
  return formatCredentialProbeError(String(exc), '操作失败，请稍后重试。');
}

export default CredentialsSection;
