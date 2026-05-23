import React, { useState, useEffect, useCallback } from 'react';
import {
  Settings as SettingsIcon, Key, Cpu, Network, FolderOpen, Layers, Server,
  Activity, Check, ChevronRight, Info, Zap,
  Loader2, RefreshCw, AlertCircle, CheckCircle2, XCircle, Users,
  Plus, Trash2, FlaskConical,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { useTrackedTimeout } from '@/hooks/useTrackedTimeout';
import axios from 'axios';
import { loadSettings, saveSettings, readLegacyCredentialBlob, clearLegacyCredentialBlob, type AppSettings } from '@/services/settingsStore';
import { getApiBaseUrl } from '@/services/apiBaseUrl';
import { discoverModels, type DiscoveredModel } from '@/services/chatApi';
import { getSampling, putSampling, deleteSamplingTask, type SamplingParams, type TaskDefaults } from '@/services/samplingApi';
import { buildSamplingSaveRequest, hasSamplingOverrides, updateSamplingOverrides } from '@/services/samplingPayload';
import { listFeatureFlags, setFeatureFlag, type FeatureFlagEntry } from '@/services/featureFlagsApi';
import { Tooltip as UiTooltip } from '@/components/ui/Tooltip';
import { migrateLegacyCredentials } from '@/components/settings/subsystemMigration';
import {
  createCredential,
  listCredentials,
  testCredential,
  updateCredential,
  type RuntimeCredentialPublic,
} from '@/services/credentialsApi';
import { ApiEndpointForm, type ApiEndpointFormValue } from '@/components/settings/ApiEndpointForm';
import {
  DISCUSSION_DEFAULT_BOUNDS,
  DISCUSSION_TURN_WARNING_THRESHOLD,
} from '@/services/discussionDefaults';
import {
  type SectionId,
  isSectionId,
  normalizeSection,
  resolveInitialSection,
} from '@/pages/settingsSections';
import {
  DISCUSSION_API_MODE_LABELS,
  DISCUSSION_API_MODES,
  DISCUSSION_ROLE_LABELS,
  createCustomDiscussionProfile,
  describeApiBinding,
  isBuiltInDiscussionProfile,
  loadDiscussionProfileStore,
  saveDiscussionProfileStore,
  type DiscussionAgentProfile,
  type DiscussionApiBindingMode,
  type DiscussionProfileId,
} from '@/services/discussionProfiles';

const SkillManagerLazy = React.lazy(() => import('@/components/skills/SkillManager'));
const CredentialsSectionLazy = React.lazy(() => import('@/components/settings/CredentialsSection'));
const McpServersSectionLazy = React.lazy(() => import('@/components/settings/mcp/McpServersSection'));

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
// SectionId, SECTION_IDS, isSectionId, normalizeSection, and
// resolveInitialSection live in `@/pages/settingsSections` so the URL
// back-compat contract has its own unit-test surface.

function getInitialSection(): SectionId {
  return resolveInitialSection();
}

interface HealthEntry {
  labelKey: string;
  status: 'online' | 'offline' | 'ready' | 'loaded' | 'missing';
}

/* ------------------------------------------------------------------ */
/*  Initial health data (updated from /health API)                     */
/* ------------------------------------------------------------------ */
const HEALTH_ENTRIES: HealthEntry[] = [
  { labelKey: 'settings.health_backend', status: 'offline' },
];

const healthColor: Record<string, string> = {
  online: 'text-emerald-600 bg-emerald-50 dark:bg-emerald-500/15 dark:text-emerald-300',
  ready: 'text-emerald-600 bg-emerald-50 dark:bg-emerald-500/15 dark:text-emerald-300',
  loaded: 'text-blue-600 bg-blue-50 dark:bg-blue-500/15 dark:text-blue-300',
  offline: 'text-foreground/40 bg-surface-high',
  missing: 'text-red-600 bg-red-50 dark:bg-red-500/15 dark:text-red-300',
};

const healthDot: Record<string, string> = {
  online: 'bg-emerald-500 dark:bg-emerald-400',
  ready: 'bg-emerald-500 dark:bg-emerald-400',
  loaded: 'bg-blue-500 dark:bg-blue-400',
  offline: 'bg-foreground/20',
  missing: 'bg-red-500 dark:bg-red-400',
};

/* ------------------------------------------------------------------ */
/*  Small helpers                                                      */
/* ------------------------------------------------------------------ */
function Tooltip({ text }: { text: string }) {
  return (
    <UiTooltip content={text} delay={120} className="text-left">
      <span className="ml-1 inline-flex cursor-help rounded-sm align-middle focus:outline-none focus:ring-2 focus:ring-primary/30" tabIndex={0}>
        <Info size={12} className="text-foreground/25 transition-colors hover:text-foreground/50" />
      </span>
    </UiTooltip>
  );
}

function Field({
  label,
  tooltip,
  htmlFor,
  children,
}: {
  label: string;
  tooltip?: string;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="font-label text-xs font-medium text-foreground/70 flex items-center">
        {label}
        {tooltip && <Tooltip text={tooltip} />}
      </label>
      {children}
    </div>
  );
}

function TextInput({
  id,
  value,
  placeholder,
  mono,
  ariaLabel,
  onChange,
}: {
  id?: string;
  value: string;
  placeholder?: string;
  mono?: boolean;
  ariaLabel?: string;
  onChange?: (v: string) => void;
}) {
  return (
    <input
      id={id}
      type="text"
      value={value}
      onChange={e => onChange?.(e.target.value)}
      placeholder={placeholder}
      aria-label={ariaLabel ?? placeholder ?? '文本输入'}
      readOnly={!onChange}
      className={cn(
        'w-full bg-surface-high rounded-lg px-3 py-2 border border-outline-variant/50 text-sm text-foreground',
        'focus:outline-none focus:border-primary/40 transition-colors',
        mono && 'font-mono text-xs',
      )}
    />
  );
}

function SelectInput({
  id,
  value,
  options,
  ariaLabel,
  onChange,
}: {
  id?: string;
  value: string;
  options: string[];
  ariaLabel?: string;
  onChange?: (v: string) => void;
}) {
  return (
    <select
      id={id}
      value={value}
      onChange={e => onChange?.(e.target.value)}
      aria-label={ariaLabel ?? '选择选项'}
      className="w-full bg-surface-high rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-label text-foreground focus:outline-none focus:border-primary/40 transition-colors"
    >
      {options.map(o => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

function SliderInput({
  id,
  value,
  min,
  max,
  step,
  ariaLabel,
  onChange,
}: {
  id?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  ariaLabel?: string;
  onChange?: (v: number) => void;
}) {
  const [v, setV] = useState(value);
  useEffect(() => { setV(value); }, [value]);
  return (
    <div className="flex items-center gap-3">
      <input
        id={id}
        type="range" min={min} max={max} step={step} value={v}
        onChange={e => { const n = Number(e.target.value); setV(n); onChange?.(n); }}
        aria-label={ariaLabel ?? '滑动输入'}
        className="flex-1 accent-primary h-1.5"
      />
      <span className="font-mono text-xs text-foreground/60 w-10 text-right tabular-nums">{v}</span>
    </div>
  );
}

function StatusPill({ status, t }: { status: string; t: (k: string) => string }) {
  const key = `settings.${status}`;
  return (
    <span className={cn('inline-flex items-center gap-1.5 px-2 py-0.5 text-[10px] font-label font-medium rounded-full', healthColor[status])}>
      <span className={cn('w-1.5 h-1.5 rounded-full', healthDot[status])} />
      {t(key)}
    </span>
  );
}

function ToggleSwitch({
  defaultChecked,
  checked,
  onChange,
  id,
  ariaLabel,
  labelledBy,
}: {
  defaultChecked?: boolean;
  checked?: boolean;
  onChange?: (next: boolean) => void;
  id?: string;
  ariaLabel?: string;
  labelledBy?: string;
}) {
  const [innerOn, setInnerOn] = useState(defaultChecked ?? false);
  const on = checked ?? innerOn;

  const toggle = () => {
    const next = !on;
    if (checked === undefined) {
      setInnerOn(next);
    }
    onChange?.(next);
  };

  return (
    <button
      id={id}
      type="button"
      onClick={toggle}
      aria-label={ariaLabel ?? '切换设置'}
      aria-labelledby={labelledBy}
      className={cn(
        'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
        on ? 'bg-primary' : 'bg-foreground/15',
      )}
    >
      <span className={cn('inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform shadow-sm', on ? 'translate-x-4' : 'translate-x-0.5')} />
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Section Components                                                 */
/* ------------------------------------------------------------------ */
interface ChatPublicConfig {
  provider: string;
  base_url: string;
  model: string;
  has_api_key: boolean;
  api_key_masked: string;
  updated_at: string;
}

interface EmbeddingPublicConfig {
  provider: string;
  base_url: string;
  model: string;
  has_api_key: boolean;
  api_key_masked: string;
  updated_at: string;
}

function SectionChat({ t, settings, onChange, isDirty }: { t: (k: string, p?: Record<string, string | number>) => string; settings: AppSettings; onChange: (s: AppSettings) => void; isDirty: boolean }) {
  const llm = settings.llm;
  const setLlm = (patch: Partial<typeof llm>) => onChange({ ...settings, llm: { ...llm, ...patch } });
  const trackedTimeout = useTrackedTimeout();

  const [config, setConfig] = useState<ChatPublicConfig | null>(null);
  const [form, setForm] = useState<ApiEndpointFormValue>({ provider: '', baseUrl: '', apiKey: '', model: '' });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'fail'>('idle');
  const [saveError, setSaveError] = useState('');

  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testError, setTestError] = useState('');
  const [discoveredModels, setDiscoveredModels] = useState<DiscoveredModel[]>([]);
  const [discoverStatus, setDiscoverStatus] = useState<'idle' | 'loading' | 'ok' | 'fail'>('idle');
  const [discoverError, setDiscoverError] = useState('');

  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get<ChatPublicConfig>(`${getApiBaseUrl()}/api/chat/config`);
      setConfig(data);
      setForm({ provider: data.provider, baseUrl: data.base_url, apiKey: '', model: data.model });

      const legacy = readLegacyCredentialBlob('llm');
      const migration = await migrateLegacyCredentials(getApiBaseUrl(), 'chat', data, legacy);
      if (migration) {
        setConfig(migration.migratedConfig);
        setForm({
          provider: migration.migratedConfig.provider,
          baseUrl: migration.migratedConfig.base_url,
          apiKey: '',
          model: migration.migratedConfig.model,
        });
        if (migration.shouldClearLocalStorage) {
          clearLegacyCredentialBlob('llm');
        }
      }
    } catch {
      setConfig({ provider: '', base_url: '', model: '', has_api_key: false, api_key_masked: '', updated_at: '' });
    } finally {
      setLoading(false);
    }

  }, []);

  useEffect(() => { void loadConfig(); }, [loadConfig]);

  const handleSave = async () => {
    setSaving(true);
    setSaveError('');
    setSaveStatus('idle');
    try {
      const payload: Record<string, string | null> = {
        provider: form.provider,
        base_url: form.baseUrl,
        model: form.model,
      };
      payload.api_key = form.apiKey === '' ? null : form.apiKey;
      const { data } = await axios.put<ChatPublicConfig>(`${getApiBaseUrl()}/api/chat/config`, payload);
      setConfig(data);
      setForm({ provider: data.provider, baseUrl: data.base_url, apiKey: '', model: data.model });
      setSaveStatus('saved');
      trackedTimeout(() => setSaveStatus('idle'), 3000);
    } catch (err: unknown) {
      setSaveStatus('fail');
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    if (!window.confirm('清除当前 chat 配置覆盖，恢复 .env 默认？')) return;
    setSaving(true);
    try {
      const { data } = await axios.delete<ChatPublicConfig>(`${getApiBaseUrl()}/api/chat/config`);
      setConfig(data);
      setForm({ provider: '', baseUrl: '', apiKey: '', model: '' });
      setSaveStatus('saved');
      trackedTimeout(() => setSaveStatus('idle'), 3000);
    } catch (err: unknown) {
      setSaveStatus('fail');
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleTestConnection = async () => {
    setTestStatus('testing');
    setTestError('');
    try {
      const { data } = await axios.post<{ ok: boolean; status: number; error: string; elapsed_ms: number }>(
        `${getApiBaseUrl()}/api/chat/test`,
        {
          provider: form.provider,
          base_url: form.baseUrl,
          api_key: form.apiKey === '' ? null : form.apiKey,
          model: form.model,
        },
      );
      if (!data.ok) {
        throw new Error(data.error || `HTTP ${data.status}`);
      }
      setTestStatus('ok');
      if (isDirty) {
        saveSettings(settings);
      }
    } catch (err: unknown) {
      let msg = err instanceof Error ? err.message : String(err);
      if (axios.isAxiosError(err) && err.response) {
        const d = err.response.data;
        if (d?.error?.message) {
          msg = d.error.message;
        } else if (d?.detail) {
          msg = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail);
        } else {
          msg = `请求失败 (${err.response.status})`;
        }
      }
      setTestStatus('fail');
      setTestError(msg);
    }
    trackedTimeout(() => setTestStatus('idle'), 6000);
  };

  const handleDiscover = async () => {
    setDiscoverStatus('loading');
    setDiscoverError('');
    const result = await discoverModels(form.baseUrl, form.apiKey, 'chat');
    if (result.ok) {
      setDiscoveredModels(result.models);
      setDiscoverStatus('ok');
    } else {
      setDiscoveredModels([]);
      setDiscoverStatus('fail');
      setDiscoverError(result.error || '获取失败');
    }
    trackedTimeout(() => setDiscoverStatus('idle'), 4000);
  };

  return (
    <section id="section-chat" className="space-y-5">
      <div className="flex items-center justify-between">
        <h3 className="font-headline text-sm font-semibold text-foreground flex items-center gap-2">
          <Zap size={16} className="text-primary" />
          {t('settings.section_chat')}
          <Tooltip text={t('settings.section_chat_tooltip')} />
        </h3>
        <StatusPill status={config?.has_api_key ? 'online' : 'ready'} t={t} />
      </div>
      {loading ? (
        <p className="text-xs text-foreground/40 italic">加载中…</p>
      ) : (
        <>
          <ApiEndpointForm
            idPrefix="chat"
            value={form}
            onChange={setForm}
            providerLabel={t('settings.provider')}
            apiKeyLabel={t('settings.api_key')}
            modelLabel={t('settings.chat_model')}
            baseUrlLabel={t('settings.base_url')}
            providerPlaceholder="DeepSeek / OpenAI / Claude / 自定义"
            apiKeyPlaceholder="sk-***************"
            modelPlaceholder={t('settings.chat_model_placeholder') || '模型 ID，如 deepseek-chat、gpt-4o'}
            apiKeyTooltip={t('settings.api_key_tooltip')}
            modelTooltip={t('settings.chat_model_tooltip')}
            baseUrlTooltip={t('settings.base_url_tooltip')}
            savedKeyMasked={config?.has_api_key ? config.api_key_masked : ''}
            updatedAt={config?.updated_at}
            models={discoveredModels}
            onDiscover={handleDiscover}
            discoverStatus={discoverStatus}
            discoverError={discoverError}
            onTest={handleTestConnection}
            testStatus={testStatus}
            testError={testError ? t('settings.test_fail_detail', { provider: form.provider || 'chat', error: testError }) : ''}
            onSave={handleSave}
            saveStatus={saving ? 'saving' : saveStatus}
            saveError={saveError}
            clearButton={config?.has_api_key ? (
              <button
                type="button"
                onClick={() => void handleClear()}
                disabled={saving}
                className="px-4 py-2 rounded-lg text-sm font-label text-red-600 border border-red-200 hover:bg-red-50 transition-colors disabled:opacity-50 dark:border-red-700/40 dark:text-red-300 dark:hover:bg-red-500/15"
              >
                恢复 .env 默认
              </button>
            ) : null}
          />
        </>
      )}

      <div className="grid grid-cols-3 gap-4 pt-2 border-t border-outline-variant/30">
        <Field label={t('settings.temperature')} htmlFor="chat-temperature">
          <SliderInput id="chat-temperature" value={llm.temperature} min={0} max={2} step={0.1} ariaLabel={t('settings.temperature')} onChange={v => setLlm({ temperature: v })} />
        </Field>
        <Field label={t('settings.top_p')} htmlFor="chat-top-p">
          <SliderInput id="chat-top-p" value={llm.topP} min={0} max={1} step={0.05} ariaLabel={t('settings.top_p')} onChange={v => setLlm({ topP: v })} />
        </Field>
        <Field label={t('settings.max_tokens')} htmlFor="chat-max-tokens">
          <input id="chat-max-tokens" type="number" value={llm.maxTokens} onChange={e => setLlm({ maxTokens: Number(e.target.value) })}
            aria-label={t('settings.max_tokens')}
            className="w-full bg-surface-high rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-mono text-foreground focus:outline-none focus:border-primary/40 transition-colors" />
        </Field>
      </div>
      <Field label={t('settings.system_prompt')} tooltip={t('settings.system_prompt_tooltip')} htmlFor="chat-system-prompt">
        <textarea
          id="chat-system-prompt"
          rows={3}
          value={llm.systemPrompt}
          onChange={e => setLlm({ systemPrompt: e.target.value })}
          placeholder={t('settings.system_prompt_placeholder')}
          aria-label={t('settings.system_prompt')}
          className="w-full bg-surface-high rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-label text-foreground focus:outline-none focus:border-primary/40 transition-colors resize-none"
        />
      </Field>
    </section>
  );
}

function EmbeddingCard({ t, settings, onChange }: { t: (k: string, p?: Record<string, string | number>) => string; settings: AppSettings; onChange: (s: AppSettings) => void }) {
  const trackedTimeout = useTrackedTimeout();
  const [config, setConfig] = useState<EmbeddingPublicConfig | null>(null);
  const [form, setForm] = useState<ApiEndpointFormValue>({ provider: '', baseUrl: '', apiKey: '', model: '' });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'fail'>('idle');
  const [saveError, setSaveError] = useState('');
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testError, setTestError] = useState('');
  const [discoveredModels, setDiscoveredModels] = useState<DiscoveredModel[]>([]);
  const [discoverStatus, setDiscoverStatus] = useState<'idle' | 'loading' | 'ok' | 'fail'>('idle');
  const [discoverError, setDiscoverError] = useState('');

  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get<EmbeddingPublicConfig>(`${getApiBaseUrl()}/api/embedding/config`);
      setConfig(data);
      setForm({ provider: data.provider, baseUrl: data.base_url, apiKey: '', model: data.model });

      const legacy = readLegacyCredentialBlob('embedding');
      const migration = await migrateLegacyCredentials(getApiBaseUrl(), 'embedding', data, legacy);
      if (migration) {
        setConfig(migration.migratedConfig);
        setForm({
          provider: migration.migratedConfig.provider,
          baseUrl: migration.migratedConfig.base_url,
          apiKey: '',
          model: migration.migratedConfig.model,
        });
        if (migration.shouldClearLocalStorage) {
          clearLegacyCredentialBlob('embedding');
        }
      }
    } catch {
      setConfig({ provider: '', base_url: '', model: '', has_api_key: false, api_key_masked: '', updated_at: '' });
    } finally {
      setLoading(false);
    }

  }, []);

  useEffect(() => { void loadConfig(); }, [loadConfig]);

  const handleSave = async () => {
    setSaving(true);
    setSaveError('');
    setSaveStatus('idle');
    try {
      const payload: Record<string, string | null> = {
        provider: form.provider,
        base_url: form.baseUrl,
        model: form.model,
      };
      payload.api_key = form.apiKey === '' ? null : form.apiKey;
      const { data } = await axios.put<EmbeddingPublicConfig>(`${getApiBaseUrl()}/api/embedding/config`, payload);
      setConfig(data);
      setForm({ provider: data.provider, baseUrl: data.base_url, apiKey: '', model: data.model });
      setSaveStatus('saved');
      trackedTimeout(() => setSaveStatus('idle'), 3000);
    } catch (err: unknown) {
      setSaveStatus('fail');
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    if (!window.confirm('清除当前 embedding 配置覆盖，恢复 .env 默认？')) return;
    setSaving(true);
    try {
      const { data } = await axios.delete<EmbeddingPublicConfig>(`${getApiBaseUrl()}/api/embedding/config`);
      setConfig(data);
      setForm({ provider: '', baseUrl: '', apiKey: '', model: '' });
      setSaveStatus('saved');
      trackedTimeout(() => setSaveStatus('idle'), 3000);
    } catch (err: unknown) {
      setSaveStatus('fail');
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTestStatus('testing');
    setTestError('');
    try {
      const { data } = await axios.post<{ ok: boolean; status: number; error: string; elapsed_ms: number }>(
        `${getApiBaseUrl()}/api/embedding/test`,
        {
          provider: form.provider,
          base_url: form.baseUrl,
          api_key: form.apiKey === '' ? null : form.apiKey,
          model: form.model,
        }
      );
      if (data.ok) {
        setTestStatus('ok');
      } else {
        setTestStatus('fail');
        setTestError(data.error || `HTTP ${data.status}`);
      }
      trackedTimeout(() => setTestStatus('idle'), 6000);
    } catch (err: unknown) {
      setTestStatus('fail');
      setTestError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleDiscover = async () => {
    setDiscoverStatus('loading');
    setDiscoverError('');
    const result = await discoverModels(form.baseUrl, form.apiKey, 'embedding');
    if (result.ok) {
      setDiscoveredModels(result.models);
      setDiscoverStatus('ok');
    } else {
      setDiscoveredModels([]);
      setDiscoverStatus('fail');
      setDiscoverError(result.error || '获取失败');
    }
    trackedTimeout(() => setDiscoverStatus('idle'), 4000);
  };

  return (
    <div className="space-y-4 p-4 bg-surface-lowest rounded-lg border border-outline-variant/40">
      <div className="flex items-center justify-between">
        <h4 className="font-headline text-xs font-semibold text-foreground flex items-center gap-2">
          <Network size={14} className="text-primary" />
          {t('settings.section_embedding')}
        </h4>
        <div className="flex items-center gap-2">
          <StatusPill status={config?.has_api_key ? 'online' : 'ready'} t={t} />
        </div>
      </div>

      {loading ? (
        <p className="text-xs text-foreground/40 italic">加载中…</p>
      ) : (
        <>
          <ApiEndpointForm
            idPrefix="embedding"
            value={form}
            onChange={setForm}
            providerLabel={t('settings.embedding_provider')}
            apiKeyLabel={t('settings.embedding_api_key')}
            modelLabel={t('settings.embedding_model')}
            baseUrlLabel={t('settings.embedding_base_url')}
            providerPlaceholder="OpenAI / Jina / Cohere / 自定义"
            apiKeyPlaceholder="sk-emb-***************"
            modelPlaceholder="text-embedding-3-small / bge-large-zh-v1.5"
            apiKeyTooltip={t('settings.embedding_api_key_tooltip')}
            modelTooltip={t('settings.embedding_model_tooltip')}
            savedKeyMasked={config?.has_api_key ? config.api_key_masked : ''}
            updatedAt={config?.updated_at}
            models={discoveredModels}
            onDiscover={handleDiscover}
            discoverStatus={discoverStatus}
            discoverError={discoverError}
            onTest={handleTest}
            testStatus={testStatus}
            testError={testError}
            onSave={handleSave}
            saveStatus={saving ? 'saving' : saveStatus}
            saveError={saveError}
            clearButton={config?.has_api_key ? (
              <button
                type="button"
                onClick={() => void handleClear()}
                disabled={saving}
                className="px-4 py-2 rounded-lg text-sm font-label text-red-600 border border-red-200 hover:bg-red-50 transition-colors disabled:opacity-50 dark:border-red-700/40 dark:text-red-300 dark:hover:bg-red-500/15"
              >
                恢复 .env 默认
              </button>
            ) : null}
          />
        </>
      )}
    </div>
  );
}



function SectionWorkspace({
  t,
  settings,
  onChange,
}: {
  t: (k: string, p?: Record<string, string | number>) => string;
  settings: AppSettings;
  onChange: (s: AppSettings) => void;
}) {
  const ws = settings.workspace;
  const setWs = (patch: Partial<typeof ws>) => onChange({ ...settings, workspace: { ...ws, ...patch } });

  return (
    <section id="section-workspace" className="space-y-5">
      <h3 className="font-headline text-sm font-semibold text-foreground flex items-center gap-2">
        <FolderOpen size={16} className="text-primary" />
        {t('settings.section_workspace')}
      </h3>
      <div className="grid grid-cols-1 gap-4">
        <Field label={t('settings.local_storage_path')} htmlFor="workspace-local-storage-path">
          <TextInput
            id="workspace-local-storage-path"
            value={ws.localStoragePath}
            mono
            ariaLabel={t('settings.local_storage_path')}
            onChange={value => setWs({ localStoragePath: value })}
          />
        </Field>
        <div className="flex items-center justify-between">
          <label id="workspace-auto-index-label" className="font-label text-xs font-medium text-foreground">{t('settings.auto_index')}</label>
          <ToggleSwitch
            id="workspace-auto-index"
            labelledBy="workspace-auto-index-label"
            checked={ws.autoIndex}
            onChange={next => setWs({ autoIndex: next })}
          />
        </div>
        <Field
          label="检索 Top-K"
          tooltip="Workbench 文献问答每次向后端请求的候选片段数量，范围 3-20。"
          htmlFor="workspace-retrieval-top-k"
        >
          <input
            id="workspace-retrieval-top-k"
            type="number"
            min={3}
            max={20}
            step={1}
            value={ws.retrievalTopK}
            aria-label="检索 Top-K"
            onChange={event => {
              const next = Number(event.target.value);
              if (Number.isFinite(next)) {
                setWs({ retrievalTopK: Math.min(20, Math.max(3, Math.round(next))) });
              }
            }}
            className="w-full bg-surface-high rounded-lg px-3 py-2 border border-outline-variant/50 text-sm text-foreground focus:outline-none focus:border-primary/40 transition-colors"
          />
        </Field>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Rerank Section — runtime override for the rerank backend           */
/*  Backend endpoints in routers/rerank_config_router.py               */
/* ------------------------------------------------------------------ */
interface RerankPublicConfig {
  provider: string;
  base_url: string;
  model: string;
  has_api_key: boolean;
  api_key_masked: string;
  updated_at: string;
}

function RerankCard({ t: _t }: { t: (k: string, p?: Record<string, string | number>) => string }) {
  const trackedTimeout = useTrackedTimeout();
  const [config, setConfig] = useState<RerankPublicConfig | null>(null);
  const [form, setForm] = useState<ApiEndpointFormValue>({ provider: '', baseUrl: '', apiKey: '', model: '' });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testMessage, setTestMessage] = useState('');
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'fail'>('idle');
  const [saveError, setSaveError] = useState('');
  const [discoveredModels, setDiscoveredModels] = useState<DiscoveredModel[]>([]);
  const [discoverStatus, setDiscoverStatus] = useState<'idle' | 'loading' | 'ok' | 'fail'>('idle');
  const [discoverError, setDiscoverError] = useState('');

  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get<RerankPublicConfig>(`${getApiBaseUrl()}/api/rerank/config`);
      setConfig(data);
      setForm({ provider: data.provider, baseUrl: data.base_url, apiKey: '', model: data.model });
    } catch {
      setConfig({ provider: '', base_url: '', model: '', has_api_key: false, api_key_masked: '', updated_at: '' });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadConfig(); }, [loadConfig]);

  const handleSave = async () => {
    setSaving(true);
    setSaveError('');
    setSaveStatus('idle');
    try {
      const payload: Record<string, string | null> = {
        provider: form.provider,
        base_url: form.baseUrl,
        model: form.model,
      };
      payload.api_key = form.apiKey === '' ? null : form.apiKey;
      const { data } = await axios.put<RerankPublicConfig>(`${getApiBaseUrl()}/api/rerank/config`, payload);
      setConfig(data);
      setForm({ provider: data.provider, baseUrl: data.base_url, apiKey: '', model: data.model });
      setSaveStatus('saved');
      trackedTimeout(() => setSaveStatus('idle'), 3000);
    } catch (err: unknown) {
      setSaveStatus('fail');
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    if (!window.confirm('清除当前 rerank 配置覆盖，恢复 .env 设置？')) return;
    setSaving(true);
    try {
      const { data } = await axios.delete<RerankPublicConfig>(`${getApiBaseUrl()}/api/rerank/config`);
      setConfig(data);
      setForm({ provider: '', baseUrl: '', apiKey: '', model: '' });
      setSaveStatus('saved');
      trackedTimeout(() => setSaveStatus('idle'), 3000);
    } catch (err: unknown) {
      setSaveStatus('fail');
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTestStatus('testing');
    setTestMessage('');
    try {
      const { data } = await axios.post<{ ok: boolean; status: number; error: string; elapsed_ms: number }>(
        `${getApiBaseUrl()}/api/rerank/test`,
        {
          provider: form.provider,
          base_url: form.baseUrl,
          api_key: form.apiKey === '' ? null : form.apiKey,
          model: form.model,
        }
      );
      if (data.ok) {
        setTestStatus('ok');
        setTestMessage(`HTTP ${data.status} · ${data.elapsed_ms} ms`);
      } else {
        setTestStatus('fail');
        setTestMessage(data.error || `HTTP ${data.status}`);
      }
      trackedTimeout(() => setTestStatus('idle'), 6000);
    } catch (err: unknown) {
      setTestStatus('fail');
      setTestMessage(err instanceof Error ? err.message : String(err));
    }
  };

  const handleDiscover = async () => {
    setDiscoverStatus('loading');
    setDiscoverError('');
    const result = await discoverModels(form.baseUrl, form.apiKey, 'rerank');
    if (result.ok) {
      setDiscoveredModels(result.models);
      setDiscoverStatus('ok');
    } else {
      setDiscoveredModels([]);
      setDiscoverStatus('fail');
      setDiscoverError(result.error || '获取失败');
    }
    trackedTimeout(() => setDiscoverStatus('idle'), 4000);
  };

  return (
    <div className="space-y-4 p-4 bg-surface-lowest rounded-lg border border-outline-variant/40">
      <div className="flex items-center justify-between">
        <h4 className="font-headline text-xs font-semibold text-foreground flex items-center gap-2">
          <Layers size={14} className="text-primary" />
          Rerank 模型配置
          <Tooltip text="文献检索后排序的 reranker 模型 — 默认用 SiliconFlow，可填本地 BGE 等 OpenAI/Cohere 兼容服务。配置写到 runtime_state/rerank_override.json 并立刻生效（不需要重启）。" />
        </h4>
        <StatusPill status={config?.has_api_key ? 'online' : 'ready'} t={_t} />
      </div>

      {testStatus === 'ok' && testMessage && (
        <div className="flex items-start gap-2 p-3 bg-emerald-50 border border-emerald-200 rounded-lg min-w-0 dark:border-emerald-700/40 dark:bg-emerald-500/15">
          <CheckCircle2 size={16} className="text-emerald-500 flex-shrink-0 mt-0.5" />
          <p className="font-body text-[11px] text-emerald-700 leading-relaxed break-all flex-1 min-w-0 dark:text-emerald-300">{testMessage}</p>
        </div>
      )}

      {loading ? (
        <p className="text-xs text-foreground/40 italic">加载中…</p>
      ) : (
        <>
          <ApiEndpointForm
            idPrefix="rerank"
            value={form}
            onChange={setForm}
            providerLabel="供应商"
            apiKeyLabel="API Key"
            modelLabel="模型 ID"
            baseUrlLabel="服务地址"
            providerPlaceholder="SiliconFlow / DashScope / 本地服务"
            apiKeyPlaceholder="sk-..."
            modelPlaceholder="bge-reranker-v2-m3 / qwen3-rerank"
            baseUrlPlaceholder="http://localhost:7997/rerank"
            apiKeyTooltip="保存为本地运行时配置；本地 rerank 服务可留空。"
            modelTooltip="例如 bge-reranker-v2-m3、qwen3-rerank、gte-rerank。"
            baseUrlTooltip="OpenAI/Cohere 兼容的 rerank 端点完整地址。"
            savedKeyMasked={config?.has_api_key ? config.api_key_masked : ''}
            updatedAt={config?.updated_at}
            models={discoveredModels}
            onDiscover={handleDiscover}
            discoverStatus={discoverStatus}
            discoverError={discoverError}
            onTest={handleTest}
            testStatus={testStatus}
            testError={testMessage}
            onSave={handleSave}
            saveStatus={saving ? 'saving' : saveStatus}
            saveError={saveError}
            clearButton={config?.has_api_key ? (
              <button
                type="button"
                onClick={() => void handleClear()}
                disabled={saving}
                className="px-4 py-2 rounded-lg text-sm font-label text-red-600 border border-red-200 hover:bg-red-50 transition-colors disabled:opacity-50 dark:border-red-700/40 dark:text-red-300 dark:hover:bg-red-500/15"
              >
                恢复 .env 默认
              </button>
            ) : null}
          />

          <details className="text-[11px] text-foreground/50">
            <summary className="cursor-pointer hover:text-foreground/70">本地 rerank 服务怎么搭？</summary>
            <p className="mt-2 p-2 bg-surface-high rounded text-[11px] leading-relaxed">
              本地 rerank 是<strong>独立服务</strong>，桌面 App 通过 HTTP 调用。只要服务兼容 Cohere <code>/rerank</code> 协议，
              填上面的 Base URL + 模型 ID 就能用。
              <br />
              <br />
              三种部署方式（Docker / Python 参考脚本 / 复用已有服务）、协议规范、故障排查见仓库文档：
              <br />
              <code className="text-foreground/80">docs/local-rerank.md</code>
            </p>
          </details>
        </>
      )}
    </div>
  );
}

function SectionSemanticRouting({ t, settings, onChange }: { t: (k: string, p?: Record<string, string | number>) => string; settings: AppSettings; onChange: (s: AppSettings) => void }) {
  return (
    <section id="section-semantic-routing" className="space-y-5">
      <div className="flex items-center justify-between">
        <h3 className="font-headline text-sm font-semibold text-foreground flex items-center gap-2">
          <Network size={16} className="text-primary" />
          {t('settings.section_semantic_routing')}
          <Tooltip text={t('settings.section_semantic_routing_tooltip')} />
        </h3>
      </div>
      <p className="text-xs text-foreground/50 leading-relaxed">
        {t('settings.section_semantic_routing_intro')}
      </p>
      <EmbeddingCard t={t} settings={settings} onChange={onChange} />
      <RerankCard t={t} />
    </section>
  );
}

function SectionSampling({ t }: { t: (k: string, p?: Record<string, string | number>) => string }) {
  const trackedTimeout = useTrackedTimeout();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [taskDefaults, setTaskDefaults] = useState<Record<string, TaskDefaults>>({});
  const [modelMaxTokens, setModelMaxTokens] = useState(32768);
  const [userOverrides, setUserOverrides] = useState<Record<string, SamplingParams>>({});
  const [expandedTask, setExpandedTask] = useState<string | null>('chat');
  const [saveStatus, setSaveStatus] = useState<Record<string, 'idle' | 'saving' | 'saved' | 'error'>>({});
  const [saveError, setSaveError] = useState<Record<string, string>>({});

  const tasks = [
    { id: 'chat', labelKey: 'settings.sampling_task_chat', tooltip: 'settings.sampling_task_chat_tooltip' },
    { id: 'inspiration', labelKey: 'settings.sampling_task_inspiration', tooltip: 'settings.sampling_task_inspiration_tooltip' },
    { id: 'extraction', labelKey: 'settings.sampling_task_extraction', tooltip: 'settings.sampling_task_extraction_tooltip' },
    { id: 'summarization', labelKey: 'settings.sampling_task_summarization', tooltip: 'settings.sampling_task_summarization_tooltip' },
    { id: 'rewrite', labelKey: 'settings.sampling_task_rewrite', tooltip: 'settings.sampling_task_rewrite_tooltip' },
  ];

  const loadSamplingData = useCallback(async () => {
    setLoading(true);
    setError(null);
    // Frontend fallback defaults — used when the backend response is missing
    // task_defaults entirely or for any individual task the backend forgot.
    // Keeps the panel usable on older backends + offline / partial responses.
    const FALLBACK_TASK_DEFAULTS: Record<string, TaskDefaults> = {
      chat: { temperature: 0.7, top_p: 0.9, top_k: 50, max_tokens: 2048 },
      inspiration: { temperature: 0.85, top_p: 0.95, top_k: 80, max_tokens: 1024 },
      extraction: { temperature: 0.1, top_p: 0.5, top_k: 20, max_tokens: 4096 },
      summarization: { temperature: 0.3, top_p: 0.7, top_k: 30, max_tokens: 2048 },
      rewrite: { temperature: 0.5, top_p: 0.8, top_k: 40, max_tokens: 2048 },
    };
    try {
      const data = await getSampling();
      const backendDefaults = (data?.task_defaults && typeof data.task_defaults === 'object')
        ? data.task_defaults
        : {};
      setTaskDefaults({ ...FALLBACK_TASK_DEFAULTS, ...backendDefaults });
      setModelMaxTokens(data?.model_max_tokens ?? 32768);
      setUserOverrides(data?.tasks ?? {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      // Even on backend failure, keep panel renderable with frontend defaults
      // so users can at least see what the sampling shape looks like.
      setTaskDefaults(FALLBACK_TASK_DEFAULTS);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadSamplingData(); }, [loadSamplingData]);

  const getEffectiveValue = (task: string, field: keyof TaskDefaults): number => {
    return userOverrides[task]?.[field] ?? taskDefaults[task]?.[field] ?? 0;
  };

  const handleFieldChange = (task: string, field: keyof SamplingParams, value: number | undefined) => {
    setUserOverrides(prev => {
      const nextTaskOverrides = updateSamplingOverrides(prev[task], field, value);

      if (!nextTaskOverrides) {
        const next = { ...prev };
        delete next[task];
        return next;
      }

      return {
        ...prev,
        [task]: nextTaskOverrides,
      };
    });
  };

  const handleSave = async (task: string) => {
    setSaveStatus(prev => ({ ...prev, [task]: 'saving' }));
    setSaveError(prev => ({ ...prev, [task]: '' }));
    try {
      const request = buildSamplingSaveRequest(task, userOverrides[task]);

      if (request.type === 'delete') {
        await deleteSamplingTask(request.task);
        setUserOverrides(prev => {
          const next = { ...prev };
          delete next[task];
          return next;
        });
      } else {
        await putSampling(request.payload);
        setUserOverrides(prev => ({
          ...prev,
          [task]: request.payload[task],
        }));
      }

      setSaveStatus(prev => ({ ...prev, [task]: 'saved' }));
      trackedTimeout(() => setSaveStatus(prev => ({ ...prev, [task]: 'idle' })), 2000);
    } catch (err) {
      let msg = err instanceof Error ? err.message : String(err);
      if (axios.isAxiosError(err) && err.response?.status === 422) {
        const detail = err.response.data?.detail;
        msg = typeof detail === 'string' ? detail : JSON.stringify(detail);
      }
      setSaveStatus(prev => ({ ...prev, [task]: 'error' }));
      setSaveError(prev => ({ ...prev, [task]: msg }));
      trackedTimeout(() => setSaveStatus(prev => ({ ...prev, [task]: 'idle' })), 4000);
    }
  };

  const handleReset = async (task: string) => {
    try {
      await deleteSamplingTask(task);
      setUserOverrides(prev => {
        const next = { ...prev };
        delete next[task];
        return next;
      });
      setSaveError(prev => {
        const next = { ...prev };
        delete next[task];
        return next;
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setSaveError(prev => ({ ...prev, [task]: msg }));
    }
  };

  if (loading) {
    return (
      <section className="space-y-5">
        <div className="flex items-center gap-2 text-foreground/40">
          <Loader2 size={16} className="animate-spin" />
          <span className="text-sm">{t('common.loading')}</span>
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="space-y-5">
        <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg dark:border-red-700/40 dark:bg-red-500/15">
          <AlertCircle size={16} className="text-red-500 flex-shrink-0 mt-0.5" />
          <p className="font-body text-xs text-red-700 dark:text-red-300">{error}</p>
        </div>
      </section>
    );
  }

  return (
    <section id="section-sampling" className="space-y-5">
      <h3 className="font-headline text-sm font-semibold text-foreground flex items-center gap-2">
        <Cpu size={16} className="text-primary" />
        {t('settings.section_sampling')}
        <Tooltip text={t('settings.section_sampling_tooltip')} />
      </h3>
      <p className="text-xs text-foreground/50 leading-relaxed">
        {t('settings.sampling_description')}
      </p>

      <div className="space-y-2">
        {tasks.map(task => {
          const isExpanded = expandedTask === task.id;
          // Defensive optional chaining: if the backend response missed a
          // key or the user's runtime override store is partially populated,
          // accessing taskDefaults[task.id] / userOverrides[task.id] on an
          // undefined dict throws "Cannot read properties of undefined".
          // The early-return below already handles missing defaults gracefully.
          const defaults = taskDefaults?.[task.id];
          const overrides = userOverrides?.[task.id];
          const hasOverrides = hasSamplingOverrides(overrides);
          const status = saveStatus?.[task.id] || 'idle';
          const errMsg = saveError?.[task.id];

          if (!defaults) return null;

          return (
            <div key={task.id} className="border border-outline-variant rounded-lg overflow-hidden">
              <button
                type="button"
                onClick={() => setExpandedTask(isExpanded ? null : task.id)}
                className="w-full flex items-center justify-between px-4 py-3 bg-surface-high hover:bg-surface-highest transition-colors"
              >
                <div className="flex items-center gap-2">
                  <ChevronRight size={14} className={cn('transition-transform text-foreground/40', isExpanded && 'rotate-90')} />
                  <span className="font-label text-sm text-foreground">{t(task.labelKey)}</span>
                  <Tooltip text={t(task.tooltip)} />
                  {hasOverrides && (
                    <span className="text-[9px] px-1.5 py-0.5 bg-primary/10 text-primary rounded-full font-label">
                      {t('settings.sampling_customized')}
                    </span>
                  )}
                </div>
                <span className="text-xs text-foreground/30 font-mono">
                  T={getEffectiveValue(task.id, 'temperature').toFixed(2)}
                </span>
              </button>

              {isExpanded && (
                <div className="px-4 py-4 space-y-4 bg-surface-low border-t border-outline-variant">
                  {errMsg && (
                    <div className="flex items-start gap-2 p-2.5 bg-red-50 border border-red-200 rounded-md dark:border-red-700/40 dark:bg-red-500/15">
                      <AlertCircle size={14} className="text-red-500 flex-shrink-0 mt-0.5" />
                      <p className="font-body text-[11px] text-red-700 leading-relaxed dark:text-red-300">{errMsg}</p>
                    </div>
                  )}

                  <div className="grid grid-cols-2 gap-4">
                    <Field
                      label={`${t('settings.temperature')} (0-2)`}
                      tooltip={t('settings.sampling_temperature_tooltip')}
                      htmlFor={`sampling-${task.id}-temperature`}
                    >
                      <div className="space-y-1">
                        <input
                          id={`sampling-${task.id}-temperature`}
                          type="number"
                          min={0}
                          max={2}
                          step={0.05}
                          value={overrides?.temperature ?? ''}
                          placeholder={defaults.temperature.toFixed(2)}
                          onChange={e => handleFieldChange(task.id, 'temperature', e.target.value ? Number(e.target.value) : undefined)}
                          className="w-full bg-surface-highest rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-mono text-foreground focus:outline-none focus:border-primary/40 transition-colors"
                        />
                        <p className="text-[10px] text-foreground/40">
                          {t('settings.sampling_default')}: {defaults.temperature.toFixed(2)}
                        </p>
                      </div>
                    </Field>

                    <Field
                      label={`${t('settings.top_p')} (0-1)`}
                      tooltip={t('settings.sampling_top_p_tooltip')}
                      htmlFor={`sampling-${task.id}-top-p`}
                    >
                      <div className="space-y-1">
                        <input
                          id={`sampling-${task.id}-top-p`}
                          type="number"
                          min={0}
                          max={1}
                          step={0.05}
                          value={overrides?.top_p ?? ''}
                          placeholder={defaults.top_p.toFixed(2)}
                          onChange={e => handleFieldChange(task.id, 'top_p', e.target.value ? Number(e.target.value) : undefined)}
                          className="w-full bg-surface-highest rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-mono text-foreground focus:outline-none focus:border-primary/40 transition-colors"
                        />
                        <p className="text-[10px] text-foreground/40">
                          {t('settings.sampling_default')}: {defaults.top_p.toFixed(2)}
                        </p>
                      </div>
                    </Field>

                    <Field
                      label={`${t('settings.top_k')} (1-200)`}
                      tooltip={t('settings.sampling_top_k_tooltip')}
                      htmlFor={`sampling-${task.id}-top-k`}
                    >
                      <div className="space-y-1">
                        <input
                          id={`sampling-${task.id}-top-k`}
                          type="number"
                          min={1}
                          max={200}
                          step={1}
                          value={overrides?.top_k ?? ''}
                          placeholder={String(defaults.top_k)}
                          onChange={e => handleFieldChange(task.id, 'top_k', e.target.value ? Number(e.target.value) : undefined)}
                          className="w-full bg-surface-highest rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-mono text-foreground focus:outline-none focus:border-primary/40 transition-colors"
                        />
                        <p className="text-[10px] text-foreground/40">
                          {t('settings.sampling_default')}: {defaults.top_k}
                        </p>
                      </div>
                    </Field>

                    <Field
                      label={`${t('settings.max_tokens')} (1-${modelMaxTokens})`}
                      tooltip={t('settings.sampling_max_tokens_tooltip')}
                      htmlFor={`sampling-${task.id}-max-tokens`}
                    >
                      <div className="space-y-1">
                        <input
                          id={`sampling-${task.id}-max-tokens`}
                          type="number"
                          min={1}
                          max={modelMaxTokens}
                          step={128}
                          value={overrides?.max_tokens ?? ''}
                          placeholder={String(defaults.max_tokens)}
                          onChange={e => handleFieldChange(task.id, 'max_tokens', e.target.value ? Number(e.target.value) : undefined)}
                          className="w-full bg-surface-highest rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-mono text-foreground focus:outline-none focus:border-primary/40 transition-colors"
                        />
                        <p className="text-[10px] text-foreground/40">
                          {t('settings.sampling_default')}: {defaults.max_tokens}
                        </p>
                      </div>
                    </Field>
                  </div>

                  <div className="flex justify-end gap-2 pt-2">
                    <button
                      type="button"
                      onClick={() => handleReset(task.id)}
                      className="px-3 py-1.5 text-xs font-label text-foreground/60 hover:text-foreground border border-outline-variant rounded-lg transition-colors"
                    >
                      {t('settings.sampling_reset')}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleSave(task.id)}
                      disabled={status === 'saving'}
                      className={cn(
                        'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-label font-medium transition-colors',
                        status === 'saved' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300' :
                        status === 'error' ? 'bg-red-50 text-red-700 border border-red-200 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300' :
                        'bg-primary text-primary-foreground hover:bg-primary/90',
                      )}
                    >
                      {status === 'saving' ? <Loader2 size={12} className="animate-spin" /> :
                       status === 'saved' ? <Check size={12} /> :
                       status === 'error' ? <XCircle size={12} /> : null}
                      {status === 'saving' ? t('common.saving') :
                       status === 'saved' ? t('common.saved') :
                       status === 'error' ? t('common.error') :
                       t('common.save')}
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Discussion Defaults Section (C3b carry-over plan)                */
/* ------------------------------------------------------------------ */
function SectionDiscussion({ t }: { t: (k: string) => string }) {
  const trackedTimeout = useTrackedTimeout();
  type DiscussionDefaults = {
    auto_stop: boolean;
    min_turns: number;
    convergence_threshold: number;
    convergence_judge_agent_id: string;
  };

  type SaveState = 'idle' | 'saved' | 'error';
  type ProbeState = 'idle' | 'testing' | 'ok' | 'fail';
  type DiscoverState = 'idle' | 'loading' | 'ok' | 'fail';

  const apiModeLabels: Record<DiscussionApiBindingMode, string> = {
    inline: DISCUSSION_API_MODE_LABELS.inline,
    default: DISCUSSION_API_MODE_LABELS.default,
    credential: DISCUSSION_API_MODE_LABELS.credential,
  };

  const [defaults, setDefaults] = React.useState<{
    auto_stop: boolean | null;
    min_turns: number | null;
    convergence_threshold: number | null;
    convergence_judge_agent_id: string | null;
  }>({
    auto_stop: null,
    min_turns: null,
    convergence_threshold: null,
    convergence_judge_agent_id: null,
  });
  const [profileStore, setProfileStore] = React.useState(loadDiscussionProfileStore);
  const [activeProfileId, setActiveProfileId] = React.useState<DiscussionProfileId>('proposer');
  const [roleNameDraft, setRoleNameDraft] = React.useState('');
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [saveState, setSaveState] = React.useState<SaveState>('idle');
  const [credentials, setCredentials] = React.useState<RuntimeCredentialPublic[]>([]);
  const [credentialLoading, setCredentialLoading] = React.useState(false);
  const [credentialError, setCredentialError] = React.useState('');
  const [roleApiSaving, setRoleApiSaving] = React.useState(false);
  const [roleApiSaveState, setRoleApiSaveState] = React.useState<SaveState>('idle');
  const [roleApiSaveError, setRoleApiSaveError] = React.useState('');
  const [roleApiTestState, setRoleApiTestState] = React.useState<ProbeState>('idle');
  const [roleApiTestError, setRoleApiTestError] = React.useState('');
  const [roleModels, setRoleModels] = React.useState<DiscoveredModel[]>([]);
  const [roleDiscoverState, setRoleDiscoverState] = React.useState<DiscoverState>('idle');
  const [roleDiscoverError, setRoleDiscoverError] = React.useState('');

  const normalizeDefaults = (value: typeof defaults): DiscussionDefaults => ({
    auto_stop: value.auto_stop ?? false,
    min_turns: Math.min(
      DISCUSSION_DEFAULT_BOUNDS.min_turns.max,
      Math.max(DISCUSSION_DEFAULT_BOUNDS.min_turns.min, value.min_turns ?? 2),
    ),
    convergence_threshold: Math.min(
      DISCUSSION_DEFAULT_BOUNDS.convergence_threshold.max,
      Math.max(DISCUSSION_DEFAULT_BOUNDS.convergence_threshold.min, value.convergence_threshold ?? 0.85),
    ),
    convergence_judge_agent_id: value.convergence_judge_agent_id?.trim() ?? '',
  });

  const normalizedDefaults = normalizeDefaults(defaults);
  const thresholdPercent = Math.round(normalizedDefaults.convergence_threshold * 100);
  const activeProfile = profileStore.profiles.find((profile) => profile.id === activeProfileId)
    ?? profileStore.profiles[0];
  const configuredApiCount = profileStore.profiles.filter((profile) => (
    (profile.apiMode === 'credential' && profile.credentialId.trim())
    || (profile.apiMode === 'inline' && (profile.credentialId.trim() || (profile.provider.trim() && profile.baseUrl.trim() && profile.model.trim())))
  )).length;
  const defaultJudgeProfile = profileStore.profiles.find((profile) => profile.id === profileStore.defaultJudgeProfileId);
  const turnWarning = normalizedDefaults.min_turns > DISCUSSION_TURN_WARNING_THRESHOLD;
  const roleApiValue: ApiEndpointFormValue = {
    provider: activeProfile.provider,
    baseUrl: activeProfile.baseUrl,
    apiKey: activeProfile.apiKey,
    model: activeProfile.model,
  };
  const defaultJudgeProfileLabel = defaultJudgeProfile?.displayName ?? DISCUSSION_ROLE_LABELS.synthesizer;
  const canPersistJudge = normalizedDefaults.convergence_judge_agent_id === ''
    || profileStore.profiles.some((profile) => profile.id === normalizedDefaults.convergence_judge_agent_id);
  const persistedDefaults: DiscussionDefaults = {
    ...normalizedDefaults,
    convergence_judge_agent_id: canPersistJudge ? normalizedDefaults.convergence_judge_agent_id : '',
  };

  React.useEffect(() => {
    const load = async () => {
      try {
        const { data } = await axios.get(`${getApiBaseUrl()}/api/discussion/defaults`);
        setDefaults({
          auto_stop: data.auto_stop ?? false,
          min_turns: data.min_turns ?? 2,
          convergence_threshold: data.convergence_threshold ?? 0.85,
          convergence_judge_agent_id: '',
        });
      } catch {
        setDefaults({
          auto_stop: false,
          min_turns: 2,
          convergence_threshold: 0.85,
          convergence_judge_agent_id: '',
        });
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  React.useEffect(() => {
    setRoleNameDraft('');
    setRoleApiSaveState('idle');
    setRoleApiSaveError('');
    setRoleApiTestState('idle');
    setRoleApiTestError('');
    setRoleDiscoverState('idle');
    setRoleDiscoverError('');
    setRoleModels([]);
  }, [activeProfileId]);

  React.useEffect(() => {
    let alive = true;
    const loadCredentialList = async () => {
      setCredentialLoading(true);
      setCredentialError('');
      try {
        const data = await listCredentials({ category: 'generation', enabledOnly: true });
        if (alive) {
          setCredentials(data);
        }
      } catch {
        if (alive) {
          setCredentials([]);
          setCredentialError('模型凭证加载失败。');
        }
      } finally {
        if (alive) {
          setCredentialLoading(false);
        }
      }
    };
    void loadCredentialList();
    return () => {
      alive = false;
    };
  }, []);

  const updateProfile = (id: DiscussionProfileId, patch: Partial<DiscussionAgentProfile>) => {
    setProfileStore((current) => ({
      ...current,
      profiles: current.profiles.map((profile) => (
        profile.id === id ? { ...profile, ...patch, id, role: isBuiltInDiscussionProfile(profile) ? profile.role : 'custom' } : profile
      )),
    }));
    setSaveState('idle');
    setRoleApiSaveState('idle');
  };

  const refreshCredentials = React.useCallback(async () => {
    setCredentialLoading(true);
    setCredentialError('');
    try {
      const data = await listCredentials({ category: 'generation', enabledOnly: true });
      setCredentials(data);
    } catch {
      setCredentials([]);
      setCredentialError('模型凭证加载失败。');
    } finally {
      setCredentialLoading(false);
    }
  }, []);

  const addCustomRole = () => {
    const customCount = profileStore.profiles.filter((profile) => profile.role === 'custom').length + 1;
    const displayName = roleNameDraft.trim() || `自定义角色 ${customCount}`;
    setProfileStore((current) => {
      const nextProfile = createCustomDiscussionProfile(current.profiles, displayName);
      setActiveProfileId(nextProfile.id);
      return {
        ...current,
        profiles: [...current.profiles, nextProfile],
      };
    });
    setRoleNameDraft('');
    setSaveState('idle');
  };

  const removeCustomRole = (profileId: DiscussionProfileId) => {
    const profile = profileStore.profiles.find((item) => item.id === profileId);
    if (!profile || isBuiltInDiscussionProfile(profile)) {
      return;
    }
    setProfileStore((current) => {
      const nextProfiles = current.profiles.filter((item) => item.id !== profileId);
      const nextJudge = current.defaultJudgeProfileId === profileId ? 'synthesizer' : current.defaultJudgeProfileId;
      setActiveProfileId(nextProfiles[0]?.id ?? 'proposer');
      return {
        ...current,
        defaultJudgeProfileId: nextJudge,
        profiles: nextProfiles,
      };
    });
    setSaveState('idle');
  };

  const handleRoleApiChange = (next: ApiEndpointFormValue) => {
    updateProfile(activeProfile.id, {
      apiMode: 'inline',
      provider: next.provider,
      baseUrl: next.baseUrl,
      apiKey: next.apiKey,
      model: next.model,
    });
  };

  const handleRoleDiscover = async () => {
    setRoleDiscoverState('loading');
    setRoleDiscoverError('');
    const result = await discoverModels(activeProfile.baseUrl, activeProfile.apiKey, 'chat');
    if (result.ok) {
      setRoleModels(result.models);
      setRoleDiscoverState('ok');
    } else {
      setRoleModels([]);
      setRoleDiscoverState('fail');
      setRoleDiscoverError(result.error || '获取失败');
    }
    trackedTimeout(() => setRoleDiscoverState('idle'), 4000);
  };

  const handleRoleApiSave = async () => {
    const provider = activeProfile.provider.trim();
    const baseUrl = activeProfile.baseUrl.trim();
    const model = activeProfile.model.trim();
    const apiKey = activeProfile.apiKey.trim();
    if (!provider || !baseUrl || !model) {
      setRoleApiSaveState('error');
      setRoleApiSaveError('供应商、Base URL 和模型不能为空。');
      return;
    }
    if (!apiKey && !activeProfile.credentialId.trim()) {
      setRoleApiSaveState('error');
      setRoleApiSaveError('首次保存角色 API 时需要填写 API Key。');
      return;
    }
    if (activeProfile.credentialId.trim()) {
      const credential = credentials.find((item) => item.credential_id === activeProfile.credentialId.trim());
      if (credential && credential.category !== 'generation') {
        setRoleApiSaveState('error');
        setRoleApiSaveError('角色 API 只能绑定生成类凭证。');
        return;
      }
    }
    setRoleApiSaving(true);
    setRoleApiSaveState('idle');
    setRoleApiSaveError('');
    try {
      let saved: RuntimeCredentialPublic;
      if (activeProfile.credentialId.trim()) {
        saved = await updateCredential(activeProfile.credentialId.trim(), {
          provider,
          base_url: baseUrl,
          model,
          protocol: 'openai_chat_completions',
          enabled: true,
          strategy_hint: 'discussion',
          trust_source: 'runtime_user_confirmed',
          tags: ['discussion', activeProfile.id],
          notes: `多智能体角色：${activeProfile.displayName}`,
          ...(apiKey ? { api_key: apiKey } : {}),
        });
      } else {
        saved = await createCredential({
          category: 'generation',
          provider,
          base_url: baseUrl,
          model,
          api_key: apiKey,
          protocol: 'openai_chat_completions',
          enabled: true,
          priority: 100,
          strategy_hint: 'discussion',
          trust_source: 'runtime_user_confirmed',
          tags: ['discussion', activeProfile.id],
          notes: `多智能体角色：${activeProfile.displayName}`,
        });
      }
      const nextStore = {
        ...profileStore,
        profiles: profileStore.profiles.map((profile) => (
          profile.id === activeProfile.id
            ? {
              ...profile,
              apiMode: 'inline' as const,
              credentialId: saved.credential_id,
              provider: saved.provider,
              baseUrl: saved.base_url,
              model: saved.model,
              apiKey: '',
              apiKeyMasked: saved.api_key_masked,
              protocol: saved.protocol,
            }
            : profile
        )),
      };
      setProfileStore(nextStore);
      saveDiscussionProfileStore(nextStore);
      await refreshCredentials();
      setRoleApiSaveState('saved');
      trackedTimeout(() => setRoleApiSaveState('idle'), 2500);
    } catch (err: unknown) {
      setRoleApiSaveState('error');
      setRoleApiSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setRoleApiSaving(false);
    }
  };

  const handleRoleApiTest = async () => {
    setRoleApiTestState('testing');
    setRoleApiTestError('');
    try {
      if (activeProfile.credentialId.trim() && !activeProfile.apiKey.trim()) {
        const result = await testCredential(activeProfile.credentialId.trim(), {
          trustSourceOverride: 'runtime_user_confirmed',
        });
        if (result.status !== 'ok' && result.status !== 'skipped') {
          throw new Error(result.reason || result.probe?.error || result.status);
        }
      } else {
        const { data } = await axios.post<{ ok: boolean; status: number; error: string; elapsed_ms: number }>(
          `${getApiBaseUrl()}/api/chat/test`,
          {
            provider: activeProfile.provider,
            base_url: activeProfile.baseUrl,
            api_key: activeProfile.apiKey || null,
            model: activeProfile.model,
          },
        );
        if (!data.ok) {
          throw new Error(data.error || `HTTP ${data.status}`);
        }
      }
      setRoleApiTestState('ok');
    } catch (err: unknown) {
      setRoleApiTestState('fail');
      setRoleApiTestError(err instanceof Error ? err.message : String(err));
    } finally {
      trackedTimeout(() => setRoleApiTestState('idle'), 6000);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveState('idle');
    saveDiscussionProfileStore(profileStore);
    const backendDefaults: DiscussionDefaults = persistedDefaults;
    try {
      await axios.put(`${getApiBaseUrl()}/api/discussion/defaults`, backendDefaults);
      setDefaults(backendDefaults);
      setSaveState('saved');
    } catch {
      setSaveState('error');
    } finally {
      setSaving(false);
    }
  };

  if (loading || !activeProfile) {
    return (
      <section className="flex items-center justify-center py-12">
        <Loader2 size={20} className="animate-spin text-foreground/40" />
      </section>
    );
  }

  return (
    <section id="section-discussion" className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="font-headline text-sm font-semibold text-foreground flex items-center gap-2">
            <Users size={16} className="text-primary" />
            {t('settings.section_discussion')}
          </h3>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-foreground/50">
            为每个讨论角色配置名称、API 绑定、输出参数和提示词；讨论页选中角色后直接使用这里的设置。
          </p>
        </div>
        <span className={cn(
          'inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-label',
          normalizedDefaults.auto_stop ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' : 'bg-surface-high text-foreground/55',
        )}>
          <span className={cn('h-1.5 w-1.5 rounded-full', normalizedDefaults.auto_stop ? 'bg-emerald-500 dark:bg-emerald-400' : 'bg-foreground/25')} />
          {normalizedDefaults.auto_stop ? '自动停止' : '固定轮次'}
        </span>
      </div>

      <div className="grid gap-3 lg:grid-cols-4">
        <div className="rounded-lg border border-outline-variant bg-surface-lowest px-3 py-2">
          <p className="text-[11px] text-foreground/45">最小轮次</p>
          <p className="mt-1 font-mono text-base font-semibold text-foreground">{normalizedDefaults.min_turns}</p>
        </div>
        <div className="rounded-lg border border-outline-variant bg-surface-lowest px-3 py-2">
          <p className="text-[11px] text-foreground/45">收敛阈值</p>
          <p className="mt-1 font-mono text-base font-semibold text-foreground">{thresholdPercent}%</p>
        </div>
        <div className="rounded-lg border border-outline-variant bg-surface-lowest px-3 py-2">
          <p className="text-[11px] text-foreground/45">默认裁判</p>
          <p className="mt-1 truncate text-sm font-semibold text-foreground">
            {defaultJudgeProfileLabel}
          </p>
        </div>
        <div className="rounded-lg border border-outline-variant bg-surface-lowest px-3 py-2">
          <p className="text-[11px] text-foreground/45">接口绑定</p>
          <p className="mt-1 font-mono text-base font-semibold text-foreground">{configuredApiCount}/{profileStore.profiles.length}</p>
        </div>
      </div>

      <div className="rounded-lg border border-outline-variant bg-surface-lowest p-4 shadow-sm">
        <div className="flex items-center justify-between gap-4 border-b border-outline-variant/50 pb-4">
          <div>
            <label className="font-label text-xs font-medium text-foreground/75">自动停止</label>
            <p className="mt-1 text-xs leading-relaxed text-foreground/45">达到阈值后，由裁判角色判断是否结束。</p>
          </div>
          <ToggleSwitch
            checked={normalizedDefaults.auto_stop}
            onChange={next => setDefaults({ ...defaults, auto_stop: next })}
            ariaLabel="切换自动停止"
          />
        </div>

        <div className="grid gap-4 py-4 lg:grid-cols-3">
          <Field label="最小轮次" tooltip="至少完成这个轮次后才进入收敛判断。">
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={DISCUSSION_DEFAULT_BOUNDS.min_turns.min}
                max={DISCUSSION_DEFAULT_BOUNDS.min_turns.max}
                step={1}
                value={normalizedDefaults.min_turns}
                onChange={e => setDefaults({ ...defaults, min_turns: Number(e.target.value) })}
                className="flex-1 accent-primary"
                aria-label="最小轮次"
              />
              <input
                type="number"
                min={DISCUSSION_DEFAULT_BOUNDS.min_turns.min}
                max={DISCUSSION_DEFAULT_BOUNDS.min_turns.max}
                value={normalizedDefaults.min_turns}
                onChange={e => setDefaults({ ...defaults, min_turns: Number(e.target.value) })}
                aria-label="最小轮次"
                className="w-16 rounded-md border border-outline-variant/50 bg-surface-low px-2 py-1.5 text-center text-xs text-foreground"
              />
            </div>
            {turnWarning ? (
              <p className="mt-2 rounded-md border border-amber-200/70 bg-amber-50 px-2 py-1.5 text-[11px] leading-relaxed text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
                超过 {DISCUSSION_TURN_WARNING_THRESHOLD} 轮会明显增加耗时和模型调用成本。
              </p>
            ) : null}
          </Field>

          <Field label="收敛阈值" tooltip="阈值越高，越需要明确一致后才结束。">
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={0.5}
                max={1}
                step={0.05}
                value={normalizedDefaults.convergence_threshold}
                onChange={e => setDefaults({ ...defaults, convergence_threshold: Number(e.target.value) })}
                className="flex-1 accent-primary"
                aria-label="收敛阈值"
              />
              <span className="w-12 text-right font-mono text-xs text-foreground/60">{thresholdPercent}%</span>
            </div>
          </Field>

          <Field label="默认裁判角色" tooltip="讨论页会优先从已选角色中匹配这个裁判。">
            <select
              value={profileStore.defaultJudgeProfileId}
              onChange={(event) => {
                const next = event.target.value as DiscussionProfileId;
                setProfileStore((current) => ({ ...current, defaultJudgeProfileId: next }));
                setDefaults((current) => ({ ...current, convergence_judge_agent_id: next }));
                setSaveState('idle');
              }}
              className="w-full rounded-lg border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none"
              aria-label="默认裁判角色"
            >
              {profileStore.profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.displayName}</option>
              ))}
            </select>
          </Field>
        </div>
      </div>

      <div className="rounded-lg border border-outline-variant bg-surface-lowest p-4 shadow-sm">
        <div className="mb-4 flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <h4 className="font-headline text-sm font-semibold text-foreground">角色与 API</h4>
            <p className="mt-1 text-xs text-foreground/45">这里维护可选角色。讨论页选择角色后，会直接带上对应 API、输出参数和提示词。</p>
          </div>
          <div className="flex w-full min-w-0 flex-col gap-2 sm:flex-row xl:w-[360px]">
            <input
              type="text"
              value={roleNameDraft}
              onChange={(event) => setRoleNameDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  addCustomRole();
                }
              }}
              placeholder="新角色名称，如 统计顾问"
              aria-label="新角色名称"
              className="min-w-0 flex-1 rounded-lg border border-outline-variant/50 bg-surface-low px-3 py-2 text-xs text-foreground placeholder:text-foreground/35 focus:border-primary/40 focus:outline-none"
            />
            <button
              type="button"
              onClick={addCustomRole}
              className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-primary/25 bg-primary/8 px-3 py-2 text-xs font-medium text-primary transition-colors hover:bg-primary/12"
            >
              <Plus size={13} /> 新增角色
            </button>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-[240px_minmax(0,1fr)]">
          <div className="grid content-start gap-2 sm:grid-cols-2 xl:grid-cols-1">
            {profileStore.profiles.map((profile) => (
              <div
                key={profile.id}
                className={cn(
                  'group flex items-center gap-2 rounded-lg border px-3 py-2 transition-colors',
                  activeProfileId === profile.id
                    ? 'border-primary/45 bg-primary/10 text-primary'
                    : 'border-outline-variant/50 bg-surface-low hover:border-primary/30 hover:bg-surface-high',
                )}
              >
                <button
                  type="button"
                  onClick={() => setActiveProfileId(profile.id)}
                  className="min-w-0 flex-1 text-left"
                >
                  <span className="block truncate text-xs font-semibold">{profile.displayName}</span>
                  <span className="mt-1 block truncate text-[10px] text-foreground/45">{describeApiBinding(profile)}</span>
                </button>
                {!isBuiltInDiscussionProfile(profile) ? (
                  <button
                    type="button"
                    onClick={() => removeCustomRole(profile.id)}
                    className="rounded-md p-1 text-foreground/30 transition-colors hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/15 dark:hover:text-red-300"
                    title="删除角色"
                    aria-label={`删除 ${profile.displayName}`}
                  >
                    <Trash2 size={12} />
                  </button>
                ) : null}
              </div>
            ))}
          </div>

          <div className="space-y-4 rounded-lg border border-outline-variant/50 bg-surface-low p-4">
            <div className="flex flex-col gap-2 border-b border-outline-variant/40 pb-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-foreground">{activeProfile.displayName}</p>
                <p className="mt-0.5 text-[11px] text-foreground/45">{describeApiBinding(activeProfile)}</p>
              </div>
              <span className="inline-flex w-fit items-center rounded-md bg-surface-high px-2 py-1 text-[10px] text-foreground/50">
                {isBuiltInDiscussionProfile(activeProfile) ? '内置角色' : '自定义角色'}
              </span>
            </div>

            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px]">
              <Field label="角色名称" htmlFor={`discussion-profile-${activeProfile.id}-name`}>
                <input
                  id={`discussion-profile-${activeProfile.id}-name`}
                  value={activeProfile.displayName}
                  onChange={(event) => updateProfile(activeProfile.id, { displayName: event.target.value })}
                  className="w-full rounded-lg border border-outline-variant/50 bg-surface-lowest px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none"
                />
              </Field>
              <Field
                label="API 绑定方式"
                tooltip="每个角色都可以复用聊天与生成设置、选择已保存 API，或单独填写一套 API。"
                htmlFor={`discussion-profile-${activeProfile.id}-api-mode`}
              >
                <select
                  id={`discussion-profile-${activeProfile.id}-api-mode`}
                  value={activeProfile.apiMode}
                  onChange={(event) => updateProfile(activeProfile.id, { apiMode: event.target.value as DiscussionApiBindingMode })}
                  className="w-full rounded-lg border border-outline-variant/50 bg-surface-lowest px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none"
                >
                  {DISCUSSION_API_MODES.map((mode) => (
                    <option key={mode} value={mode}>{apiModeLabels[mode]}</option>
                  ))}
                </select>
              </Field>
            </div>

            {activeProfile.apiMode === 'inline' ? (
              <ApiEndpointForm
                idPrefix={`discussion-profile-${activeProfile.id}`}
                value={roleApiValue}
                onChange={handleRoleApiChange}
                providerLabel="供应商"
                apiKeyLabel="API Key"
                modelLabel="模型 ID"
                baseUrlLabel="Base URL"
                providerPlaceholder="OpenAI / DeepSeek / Claude / 自定义"
                apiKeyPlaceholder="sk-***************"
                modelPlaceholder="deepseek-chat / gpt-4o / claude-3-5-sonnet"
                baseUrlPlaceholder="https://api.openai.com/v1"
                apiKeyTooltip="每个角色可使用不同 API Key；保存后会进入本机已保存 API 配置，并在讨论时按角色调用。"
                modelTooltip="该角色发言时使用的模型。"
                baseUrlTooltip="OpenAI Chat Completions 兼容端点。"
                savedKeyMasked={activeProfile.apiKeyMasked}
                models={roleModels}
                onDiscover={handleRoleDiscover}
                discoverStatus={roleDiscoverState}
                discoverError={roleDiscoverError}
                onTest={handleRoleApiTest}
                testStatus={roleApiTestState}
                testError={roleApiTestError}
                onSave={handleRoleApiSave}
                saveStatus={roleApiSaving ? 'saving' : roleApiSaveState === 'error' ? 'fail' : roleApiSaveState}
                saveError={roleApiSaveError}
                saveLabel="保存角色 API"
              />
            ) : null}

            {activeProfile.apiMode === 'credential' ? (
              <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
                <Field label="已保存 API" tooltip="来自“API 凭证”页的生成类 API 配置。" htmlFor={`discussion-profile-${activeProfile.id}-credential`}>
                  <select
                    id={`discussion-profile-${activeProfile.id}-credential`}
                    value={activeProfile.credentialId}
                    onChange={(event) => updateProfile(activeProfile.id, { credentialId: event.target.value })}
                    disabled={credentialLoading}
                    className="w-full rounded-lg border border-outline-variant/50 bg-surface-lowest px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none disabled:opacity-60"
                  >
                    <option value="">{credentialLoading ? '正在加载 API…' : '选择已保存 API'}</option>
                    {credentials.map((credential) => (
                      <option key={credential.credential_id} value={credential.credential_id}>
                        {formatDiscussionCredentialLabel(credential)}
                      </option>
                    ))}
                    {activeProfile.credentialId.trim() && !credentials.some((credential) => credential.credential_id === activeProfile.credentialId.trim()) ? (
                      <option value={activeProfile.credentialId}>当前已选 API 不可见</option>
                    ) : null}
                  </select>
                  {credentialError ? (
                    <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-300">{credentialError}</p>
                  ) : credentials.length === 0 && !credentialLoading ? (
                    <p className="mt-1 text-[11px] text-foreground/45">没有可选 API，可切换到“单独填写 API”保存一套角色 API。</p>
                  ) : null}
                </Field>
                <button
                  type="button"
                  onClick={() => void refreshCredentials()}
                  disabled={credentialLoading}
                  className="self-end rounded-lg border border-outline-variant/60 bg-surface-lowest px-3 py-2 text-xs text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:opacity-50"
                >
                  {credentialLoading ? '刷新中…' : '刷新 API'}
                </button>
              </div>
            ) : null}

            {activeProfile.apiMode === 'default' ? (
              <div className="rounded-lg border border-outline-variant/60 bg-surface-lowest px-3 py-2 text-xs leading-relaxed text-foreground/55">
                该角色直接使用“聊天与生成”分区的模型配置。需要单独指定模型或 Key 时，切换到“单独填写 API”。
              </div>
            ) : null}

            <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
              <Field label="温度" tooltip="控制发散程度，0 更稳定，2 更发散。" htmlFor={`discussion-profile-${activeProfile.id}-temperature`}>
                <input
                  id={`discussion-profile-${activeProfile.id}-temperature`}
                  type="number"
                  min={0}
                  max={2}
                  step={0.05}
                  value={activeProfile.temperature}
                  onChange={(event) => updateProfile(activeProfile.id, { temperature: Number(event.target.value) })}
                  className="w-full rounded-lg border border-outline-variant/50 bg-surface-lowest px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none"
                />
              </Field>
              <Field label="最大输出" tooltip="单次角色发言的最大 token 数。" htmlFor={`discussion-profile-${activeProfile.id}-max-tokens`}>
                <input
                  id={`discussion-profile-${activeProfile.id}-max-tokens`}
                  type="number"
                  min={64}
                  max={32000}
                  step={64}
                  value={activeProfile.maxTokens}
                  onChange={(event) => updateProfile(activeProfile.id, { maxTokens: Number(event.target.value) })}
                  className="w-full rounded-lg border border-outline-variant/50 bg-surface-lowest px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none"
                />
              </Field>
              <label className="flex items-center justify-between gap-3 rounded-lg border border-outline-variant/50 bg-surface-lowest px-3 py-2 text-xs text-foreground/70">
                固定接口
                <ToggleSwitch
                  checked={activeProfile.strictPin}
                  onChange={(next) => updateProfile(activeProfile.id, { strictPin: next })}
                  ariaLabel="固定接口"
                />
              </label>
            </div>

            <Field label="角色提示词" htmlFor={`discussion-profile-${activeProfile.id}-prompt`}>
              <textarea
                id={`discussion-profile-${activeProfile.id}-prompt`}
                value={activeProfile.systemPrompt}
                onChange={(event) => updateProfile(activeProfile.id, { systemPrompt: event.target.value })}
                rows={4}
                placeholder="写清这个角色在讨论中的判断标准、语气和输出边界。"
                className="w-full resize-none rounded-lg border border-outline-variant/50 bg-surface-lowest px-3 py-2 text-sm leading-relaxed text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
              />
            </Field>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className={cn(
          'text-xs',
          saveState === 'saved' ? 'text-emerald-600 dark:text-emerald-300' : saveState === 'error' ? 'text-red-600 dark:text-red-300' : 'text-foreground/40',
        )}>
          {saveState === 'saved'
            ? '多智能体设置已保存。'
            : saveState === 'error'
              ? '角色预设已保存，本次默认轮次未同步。'
              : '保存后，新打开的讨论会使用这些预设。'}
        </p>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className={cn(
            'flex min-h-10 items-center justify-center gap-2 rounded-lg px-4 py-2 font-label text-sm font-medium shadow-sm transition-all disabled:opacity-60',
            saveState === 'saved'
              ? 'bg-emerald-600 text-white hover:bg-emerald-700'
              : saveState === 'error'
                ? 'bg-red-600 text-white hover:bg-red-700'
                : 'bg-primary text-primary-foreground hover:bg-primary/90',
          )}
        >
          {saving ? <Loader2 size={16} className="animate-spin" /> : saveState === 'error' ? <XCircle size={16} /> : <Check size={16} />}
          {saveState === 'saved' ? '已保存' : '保存讨论设置'}
        </button>
      </div>
    </section>
  );
}

function formatDiscussionCredentialLabel(credential: RuntimeCredentialPublic): string {
  const provider = credential.provider.trim() || '自定义供应商';
  const model = credential.model.trim() || '未命名模型';
  const hint = credential.strategy_hint === 'discussion' ? ' · 讨论优先' : '';
  return `${provider} · ${model}${hint}`;
}



/* ------------------------------------------------------------------ */
/*  Experimental Features section                                      */
/* ------------------------------------------------------------------ */
function SectionExperimental({ t }: { t: (k: string, p?: Record<string, string | number>) => string }) {
  const [flags, setFlags] = useState<FeatureFlagEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [saveError, setSaveError] = useState<Record<string, string>>({});

  const loadFlags = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await listFeatureFlags();
      setFlags(data);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadFlags(); }, [loadFlags]);

  const handleToggle = async (name: string, next: boolean) => {
    setSaving(prev => ({ ...prev, [name]: true }));
    setSaveError(prev => ({ ...prev, [name]: '' }));
    try {
      const updated = await setFeatureFlag(name, next);
      setFlags(prev => prev.map(f => f.name === name ? updated : f));
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setSaveError(prev => ({ ...prev, [name]: msg }));
    } finally {
      setSaving(prev => ({ ...prev, [name]: false }));
    }
  };

  const sourceLabel = (source: FeatureFlagEntry['source']) => {
    if (source === 'override') return t('settings.experimental_source_override');
    if (source === 'env') return t('settings.experimental_source_env');
    return t('settings.experimental_source_default');
  };

  return (
    <div className="space-y-4">
      <div className="bg-surface-lowest border border-outline-variant rounded-lg p-4">
        <p className="text-xs text-foreground/70 leading-relaxed">{t('settings.experimental_intro')}</p>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-xs text-foreground/60">
          <Loader2 size={14} className="animate-spin" />
          {t('settings.experimental_loading')}
        </div>
      )}

      {loadError && (
        <div className="flex items-center gap-2 text-xs text-error">
          <AlertCircle size={14} />
          {t('settings.experimental_load_failed', { error: loadError })}
        </div>
      )}

      {!loading && !loadError && flags.length === 0 && (
        <p className="text-xs text-foreground/50">{t('settings.experimental_empty')}</p>
      )}

      {!loading && flags.map(flag => (
        <div key={flag.name} className="border border-outline-variant rounded-lg p-4 bg-surface">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <h3 className="font-semibold text-sm text-foreground">{flag.label}</h3>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-lowest text-foreground/60 border border-outline-variant">
                  {sourceLabel(flag.source)}
                </span>
              </div>
              <p className="text-xs text-foreground/60 leading-relaxed whitespace-pre-line">{flag.description}</p>
              {flag.env_var && (
                <p className="text-[10px] text-foreground/40 mt-1.5 font-mono">env: {flag.env_var}</p>
              )}
            </div>
            <button
              type="button"
              onClick={() => handleToggle(flag.name, !flag.current)}
              disabled={!!saving[flag.name]}
              className={cn(
                'relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full transition-colors',
                flag.current ? 'bg-primary' : 'bg-surface-lowest border border-outline-variant',
                saving[flag.name] && 'opacity-50 cursor-wait',
              )}
              aria-pressed={flag.current}
              aria-label={flag.label}
            >
              <span
                className={cn(
                  'inline-block h-4 w-4 transform rounded-full bg-surface shadow transition-transform',
                  flag.current ? 'translate-x-6' : 'translate-x-1',
                )}
              />
            </button>
          </div>
          {saveError[flag.name] && (
            <p className="text-xs text-error mt-2">
              {t('settings.experimental_save_error', { error: saveError[flag.name] })}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}



/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */
const TABS: { id: SectionId; icon: React.ElementType; labelKey: string }[] = [
  { id: 'chat', icon: Zap, labelKey: 'settings.section_chat' },
  { id: 'semantic-routing', icon: Network, labelKey: 'settings.section_semantic_routing' },
  { id: 'sampling', icon: Cpu, labelKey: 'settings.section_sampling' },
  { id: 'workspace', icon: FolderOpen, labelKey: 'settings.section_workspace' },
  { id: 'skills', icon: Layers, labelKey: 'skills.settings_section' },
  { id: 'credentials', icon: Key, labelKey: 'settings.section_credentials' },
  { id: 'mcp', icon: Server, labelKey: 'settings.section_mcp' },
  { id: 'discussion', icon: Users, labelKey: 'settings.section_discussion' },
  { id: 'experimental', icon: FlaskConical, labelKey: 'settings.section_experimental' },
];

export function SettingsPage() {
  const { t } = useI18n();
  const trackedTimeout = useTrackedTimeout();
  const [activeSection, setActiveSection] = useState<SectionId>(getInitialSection);
  const [healthEntries, setHealthEntries] = useState<HealthEntry[]>(HEALTH_ENTRIES);
  const [healthLoading, setHealthLoading] = useState(false);
  const [lastCheck, setLastCheck] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [settings, setSettings] = useState<AppSettings>(loadSettings);
  const isDirty = JSON.stringify(settings) !== JSON.stringify(loadSettings());
  const showGlobalSave = activeSection === 'workspace' && isDirty;

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const section = new URLSearchParams(window.location.search).get('section');
    if (isSectionId(section)) {
      setActiveSection(normalizeSection(section));
    }
  }, []);

  const checkHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const storedBase = localStorage.getItem('scholar-ai-api-base')?.trim().replace(/\/+$/, '') ?? '';
      const base = storedBase.length > 0 ? storedBase : getApiBaseUrl();
      const { data } = await axios.get(`${base}/health`, { timeout: 5000 });
      const newEntries: HealthEntry[] = [
        { labelKey: 'settings.health_backend', status: data.status === 'ok' ? 'online' : 'offline' },
      ];
      if (data.modules && typeof data.modules === 'object') {
        for (const [key, val] of Object.entries(data.modules)) {
          const status = val === true || val === 'ok' || val === 'online' || val === 'loaded'
            ? 'online'
            : val === 'ready' ? 'ready'
            : 'offline';
          newEntries.push({ labelKey: `settings.health_${key}`, status });
        }
      }
      if (newEntries.length > 1) {
        setHealthEntries(newEntries);
      } else {
        setHealthEntries(prev => prev.map((e, i) => i === 0 ? { ...e, status: 'online' } : e));
      }
      setLastCheck(new Date().toLocaleTimeString());
    } catch {
      setHealthEntries(prev => prev.map((e, i) => i === 0 ? { ...e, status: 'offline' } : e));
      setLastCheck(new Date().toLocaleTimeString());
    }
    setHealthLoading(false);
  }, []);

  useEffect(() => { checkHealth(); }, [checkHealth]);

  const handleSave = () => {
    setSaving(true);
    saveSettings(settings);
    trackedTimeout(() => {
      setSaving(false);
      setSaved(true);
      trackedTimeout(() => setSaved(false), 2000);
    }, 200);
  };

  const sectionMap: Record<SectionId, React.ReactNode> = {
    chat: <SectionChat t={t} settings={settings} onChange={setSettings} isDirty={isDirty} />,
    embedding: <SectionSemanticRouting t={t} settings={settings} onChange={setSettings} />,
    rerank: <SectionSemanticRouting t={t} settings={settings} onChange={setSettings} />,
    'semantic-routing': <SectionSemanticRouting t={t} settings={settings} onChange={setSettings} />,
    sampling: <SectionSampling t={t} />,
    workspace: <SectionWorkspace t={t} settings={settings} onChange={setSettings} />,
    skills: <SkillManagerLazy />,
    credentials: (
      <React.Suspense fallback={<Loader2 size={16} className="animate-spin text-foreground/40" />}>
        <CredentialsSectionLazy />
      </React.Suspense>
    ),
    mcp: (
      <React.Suspense fallback={<Loader2 size={16} className="animate-spin text-foreground/40" />}>
        <McpServersSectionLazy />
      </React.Suspense>
    ),
    discussion: <SectionDiscussion t={t} />,
    experimental: <SectionExperimental t={t} />,
  };

  return (
    <div className="flex h-full">
      {/* -------- Left sidebar: tabs -------- */}
      <div className="w-52 border-r border-outline-variant bg-surface-lowest p-4 flex flex-col flex-shrink-0">
        <h2 className="font-display text-lg font-semibold text-foreground mb-1 px-2">{t('settings.title')}</h2>
        <p className="font-label text-[10px] text-foreground/40 mb-4 px-2 leading-relaxed">{t('settings.description')}</p>

        <nav className="space-y-0.5 flex-1">
          {TABS.map(tab => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveSection(tab.id)}
              className={cn(
                'w-full flex items-center gap-2.5 px-3 py-2 rounded-lg font-label text-xs transition-all',
                activeSection === tab.id
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-foreground/50 hover:text-foreground hover:bg-surface-high',
              )}
            >
              <tab.icon size={14} />
              {t(tab.labelKey)}
            </button>
          ))}
        </nav>

      </div>

      {/* -------- Center content -------- */}
      <form autoComplete="off" onSubmit={e => e.preventDefault()} className="flex-1 p-8 overflow-y-auto custom-scrollbar">
        <motion.div
          key={activeSection}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.15 }}
          className="max-w-2xl space-y-6"
        >
          {sectionMap[activeSection]}

          {showGlobalSave ? (
            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg font-label text-sm font-medium shadow-sm hover:bg-primary/90 disabled:opacity-60 transition-all"
              >
                {saving ? <Loader2 size={16} className="animate-spin" /> : saved ? <Check size={16} /> : <Check size={16} />}
                {saved ? t('settings.saved') : t('settings.save_workspace')}
              </button>
            </div>
          ) : null}
        </motion.div>
      </form>

      {/* -------- Right panel: System Health -------- */}
      <div className="w-56 border-l border-outline-variant bg-surface-lowest p-4 flex-shrink-0 flex flex-col">
        <div className="flex items-center justify-between mb-1">
          <h3 className="font-headline text-sm font-semibold text-foreground flex items-center gap-2">
            <Activity size={14} className="text-primary" />
            {t('settings.section_health')}
          </h3>
          <button
            type="button"
            onClick={checkHealth}
            disabled={healthLoading}
            aria-label={t('settings.refresh_health')}
            className="p-1 text-foreground/30 hover:text-primary transition-colors"
            title={t('settings.refresh_health')}
          >
            {healthLoading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          </button>
        </div>
        <p className="font-label text-[9px] text-foreground/30 mb-4">
          {t('settings.last_check')}: {lastCheck || t('settings.never')}
        </p>

        <div className="space-y-2.5 flex-1">
          {healthEntries.map(entry => (
            <div key={entry.labelKey} className="flex items-center justify-between">
              <span className="font-label text-[11px] text-foreground/60">{t(entry.labelKey)}</span>
              <span className={cn('flex items-center gap-1 text-[9px] font-label font-medium rounded-full px-1.5 py-0.5', healthColor[entry.status])}>
                <span className={cn('w-1.5 h-1.5 rounded-full', healthDot[entry.status])} />
                {t(`settings.${entry.status}`)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
