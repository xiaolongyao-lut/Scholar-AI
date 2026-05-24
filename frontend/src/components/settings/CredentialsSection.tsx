import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Check,
  Download,
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
  Zap,
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
import { discoverModels, type DiscoveredModel } from '@/services/chatApi';

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
  // 2026-05-24: default to runtime_user_confirmed so a freshly-created
  // credential pointing at a third-party / NewAPI / sub2api gateway is
  // usable immediately — the prior `runtime_untrusted_custom` default
  // showed a confusing "已拦截 official_provider_host_mismatch" badge in
  // the list until the user manually re-saved with a different trust source.
  trust_source: 'runtime_user_confirmed',
  enabled: true,
  notes: '',
};

const CATEGORY_OPTIONS: CredentialCategory[] = ['generation', 'embedding', 'rerank'];
const CATEGORY_LABELS: Record<CredentialCategory, string> = {
  generation: '聊天与生成',
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
  openai_chat_completions: 'OpenAI 聊天补全',
  openai_responses: 'OpenAI Responses',
  anthropic_messages: 'Anthropic Messages',
  embeddings: '向量嵌入',
  rerank: '重排序',
};
const TRUST_OPTIONS: { value: CredentialTrustSource; label: string }[] = [
  { value: 'official_provider', label: '官方服务商' },
  { value: 'env_configured_gateway', label: '环境配置网关' },
  { value: 'runtime_user_confirmed', label: '本机已确认' },
  { value: 'runtime_untrusted_custom', label: '本机待确认' },
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
    if (!window.confirm(`确认删除 ${cred.provider}/${cred.model}？`)) {
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
        '浏览器旧设置里发现了一个 API Key。是否作为新的 API 配置导入并补全提供商与模型？',
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

  // ------------------------------------------------------------------ render
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-headline text-base font-semibold text-foreground">
            API 凭证
          </h3>
          <p className="font-label text-[11px] text-foreground/50 mt-0.5">
            管理聊天、语义路由和多智能体可复用的 API 配置。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            aria-label="刷新 API 列表"
            className="p-2 text-foreground/60 hover:text-foreground rounded-md hover:bg-surface-high transition-colors"
            title="刷新"
          >
            {loading ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />}
          </button>
          <button
            type="button"
            onClick={onAddNew}
            className="flex items-center gap-1.5 bg-primary text-primary-foreground px-3 py-1.5 rounded-md text-xs font-medium hover:bg-primary/90 transition-all"
          >
            <Plus size={12} aria-hidden="true" /> 新增
          </button>
        </div>
      </div>

      {legacyKey && (
        <div className="border border-amber-300 bg-amber-50 rounded-lg p-3 flex items-start gap-3 dark:border-amber-700/40 dark:bg-amber-500/15">
          <Upload size={14} className="text-amber-700 mt-0.5 dark:text-amber-300" aria-hidden="true" />
          <div className="flex-1">
            <p className="font-label text-xs text-amber-900 leading-relaxed dark:text-amber-200">
              浏览器旧设置里发现了一个 API Key。可以导入为本机 API 配置，系统不会自动导入。
            </p>
            <div className="flex gap-2 mt-2">
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
          className="border border-red-300 bg-red-50 rounded-lg p-3 flex items-start gap-2 dark:border-red-700/40 dark:bg-red-500/15"
          role="alert"
          aria-live="polite"
        >
          <ShieldAlert size={14} className="text-red-700 mt-0.5 dark:text-red-300" aria-hidden="true" />
          <p className="font-label text-xs text-red-900 flex-1 dark:text-red-200">{error}</p>
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
          editingId={mode === 'edit' ? editingId : null}
        />
      )}

      <div className="space-y-2">
        {list.length === 0 && !loading && (
          <div className="border border-dashed border-outline-variant rounded-lg p-6 text-center">
            <p className="font-label text-xs text-foreground/50">
              还没有保存 API。点击“新增”添加一套配置。
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
  /** When editing an existing credential, pass its id so the "测试连接"
   *  button can call /test against the persisted record. Omitted in
   *  create mode (test happens after save). */
  editingId?: string | null;
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
  editingId,
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
        setDiscoverError(result.error || '未能获取模型列表');
        return;
      }
      setDiscovered(result.models);
      if (result.models.length === 0) {
        setDiscoverError('上游返回空列表 — 请确认 API Key 与协议是否匹配');
      }
    } catch (err) {
      setDiscoverError(err instanceof Error ? err.message : String(err));
    } finally {
      setDiscovering(false);
    }
  }, [form.base_url, form.api_key, subsystem]);

  const handleTestConnection = useCallback(async () => {
    if (!editingId) {
      setTestMessage('请先保存后再测试连接');
      return;
    }
    setTesting(true);
    setTestMessage(null);
    try {
      const result = await testCredential(editingId);
      if (result.status === 'ok' && result.probe?.ok) {
        const latency = result.probe.status_code ? ` (HTTP ${result.probe.status_code})` : '';
        setTestMessage(`✓ 连接正常${latency}`);
      } else if (result.status === 'ok') {
        setTestMessage('✓ 凭证已通过策略校验(未实际探测上游)');
      } else {
        const probeErr = result.probe?.error;
        const detail = probeErr || result.reason || result.decision.reason || '连接失败';
        setTestMessage(`✗ ${result.status}: ${detail}`);
      }
    } catch (err) {
      setTestMessage(`✗ ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setTesting(false);
    }
  }, [editingId]);

  return (
    <div className="border border-outline-variant rounded-lg p-4 bg-surface-low space-y-3">
      <h4 className="font-headline text-sm font-semibold text-foreground">
        {mode === 'create' ? '新增 API' : '编辑 API'}
      </h4>
      <div className="grid grid-cols-2 gap-3">
        <FormField label="用途" htmlFor={fieldId('category')}>
          <select
            id={fieldId('category')}
            value={form.category}
            onChange={e => onForm({ ...form, category: e.target.value as CredentialCategory })}
            className="w-full px-2 py-1.5 border border-outline rounded text-xs bg-surface"
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
            placeholder="OpenAI / Anthropic / DeepSeek / ..."
            className="w-full px-2 py-1.5 border border-outline rounded text-xs bg-surface"
          />
        </FormField>
        <FormField label="模型" htmlFor={fieldId('model')}>
          <div className="flex gap-1.5">
            <input
              id={fieldId('model')}
              type="text"
              value={form.model}
              onChange={e => onForm({ ...form, model: e.target.value })}
              placeholder="gpt-4o / claude-opus-4-7 / ..."
              className="flex-1 min-w-0 px-2 py-1.5 border border-outline rounded text-xs bg-surface"
            />
            <button
              type="button"
              onClick={handleDiscover}
              disabled={discovering || !form.base_url.trim()}
              title="向服务地址发送 GET /v1/models 自动获取可用模型(NewAPI/sub2api/OneAPI/Ollama/vLLM 等 OpenAI 兼容端点均支持)"
              className="shrink-0 inline-flex items-center gap-1 px-2 py-1.5 border border-outline rounded text-[11px] font-medium text-foreground/75 hover:bg-surface-high hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
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
                  className="w-full text-left px-2 py-1 text-[11px] hover:bg-primary/10 font-mono text-foreground/85"
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
            className="w-full px-2 py-1.5 border border-outline rounded text-xs bg-surface"
          >
            {PROTOCOL_OPTIONS.map(p => (
              <option key={p} value={p}>{PROTOCOL_LABELS[p]}</option>
            ))}
          </select>
        </FormField>
        <FormField label="服务地址" full htmlFor={fieldId('base-url')}>
          <input
            id={fieldId('base-url')}
            type="url"
            value={form.base_url}
            onChange={e => onForm({ ...form, base_url: e.target.value })}
            placeholder="https://api.openai.com/v1 · https://your-newapi.com/v1 · http://localhost:11434"
            className="w-full px-2 py-1.5 border border-outline rounded text-xs bg-surface font-mono"
          />
          <p className="mt-1 text-[10px] text-foreground/50">
            填到 <code className="px-0.5 rounded bg-surface-high font-mono">/v1</code> 一级即可。任何 OpenAI 兼容端点(NewAPI、sub2api、OneAPI、Ollama、vLLM、LM Studio、OpenRouter、SiliconFlow 等)均可使用,无需匹配官方域名。
          </p>
        </FormField>
        <FormField
          label={mode === 'edit' ? 'API Key（留空保留当前值）' : 'API Key'}
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
              aria-label={revealKey ? '隐藏 API Key' : '显示 API Key'}
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
            className="w-full px-2 py-1.5 border border-outline rounded text-xs bg-surface"
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
            className="w-full px-2 py-1.5 border border-outline rounded text-xs bg-surface"
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
      <div className="flex items-center justify-between gap-2 pt-2">
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
        <div className="flex shrink-0 gap-2">
          {mode === 'edit' && editingId && (
            <button
              type="button"
              onClick={handleTestConnection}
              disabled={busy || testing}
              title="对已保存的凭证发起一次连接探测"
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-outline rounded hover:bg-surface-high disabled:opacity-60"
            >
              {testing ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
              测试连接
            </button>
          )}
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="px-3 py-1.5 text-xs font-medium border border-outline rounded hover:bg-surface-high"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={busy}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-60"
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
            <span className="text-[10px] text-foreground/40">{CATEGORY_LABELS[cred.category]}</span>
            {!cred.enabled && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-foreground/10 text-foreground/60">
                已停用
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
            aria-label={`测试 ${cred.provider} ${cred.model}`}
            className="p-1.5 text-foreground/60 hover:text-primary rounded hover:bg-surface-high"
            title="测试连接"
          >
            {busy ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <ShieldCheck size={14} aria-hidden="true" />}
          </button>
          <button
            type="button"
            onClick={onEdit}
            disabled={busy}
            aria-label={`编辑 ${cred.provider} ${cred.model}`}
            className="p-1.5 text-foreground/60 hover:text-primary rounded hover:bg-surface-high"
            title="编辑"
          >
            <Edit3 size={14} aria-hidden="true" />
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
        </div>
      </div>

      {onConfirmTrust && onCancelTrust && (
        <div
          className="mt-3 border-t border-outline-variant pt-3 flex items-start gap-2"
          role="alertdialog"
          aria-label="Trust this endpoint"
        >
          <ShieldAlert size={14} className="text-amber-700 mt-0.5 dark:text-amber-300" aria-hidden="true" />
          <div className="flex-1">
            <p className="font-label text-xs text-foreground/80">
              这个端点还没有被信任，因此跳过了网络测试。确认后会在本机信任并重新测试。
            </p>
            <div className="flex gap-2 mt-2">
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

function CredentialTestBadge({ result }: { result: CredentialTestResponse }) {
  const statusLabel = (() => {
    switch (result.status) {
      case 'ok':
        return '连接通过';
      case 'skipped':
        return '已跳过';
      case 'rejected':
        return '已拦截';
      case 'probe_failed':
      default:
        return '测试失败';
    }
  })();
  const tone = (() => {
    switch (result.status) {
      case 'ok':
        return 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300';
      case 'skipped':
        return 'bg-amber-50 text-amber-800 border border-amber-200 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300';
      case 'rejected':
        return 'bg-red-50 text-red-800 border border-red-200 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300';
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
      {statusLabel}{detail ? ` · ${detail}` : ''}
    </p>
  );
}

function trustBadgeFor(t: CredentialTrustSource): { label: string; cls: string } {
  switch (t) {
    case 'official_provider':
      return { label: '官方', cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' };
    case 'env_configured_gateway':
      return { label: '环境配置', cls: 'bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300' };
    case 'runtime_user_confirmed':
      return { label: '已信任', cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' };
    case 'runtime_untrusted_custom':
      return { label: '待确认', cls: 'bg-amber-50 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300' };
  }
}

function toMessage(exc: unknown): string {
  if (typeof exc === 'object' && exc && 'message' in exc) {
    const e = exc as { response?: { data?: { detail?: string } }; message?: string };
    if (e.response?.data?.detail) return e.response.data.detail;
    return e.message ?? '未知错误';
  }
  return String(exc);
}

export default CredentialsSection;
