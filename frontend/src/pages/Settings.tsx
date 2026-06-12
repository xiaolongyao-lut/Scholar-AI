import React, { useState, useEffect, useCallback } from 'react';
import {
  Settings as _SettingsIcon, Key, Cpu, Network, FolderOpen, Layers, Server,
  Activity, ArrowLeft, Check, ChevronRight, Info, Zap,
  Loader2, RefreshCw, AlertCircle, CheckCircle2, XCircle, Users,
  Play, Plus, Trash2, ToggleLeft, BookMarked, ScrollText,
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
import { getUnifiedSettings, type UnifiedSettings, type SettingsApiConfig } from '@/services/settingsApi';
import { Tooltip as UiTooltip } from '@/components/ui/Tooltip';
import { migrateLegacyCredentials } from '@/components/settings/subsystemMigration';
import { CslStylesSection } from '@/components/settings/CslStylesSection';
import {
  applyCredentialToSubsystem,
  createCredential,
  listCredentials,
  testCredential,
  updateCredential,
  type RuntimeCredentialPublic,
} from '@/services/credentialsApi';
import { ApiEndpointForm, type ApiEndpointFormValue } from '@/components/settings/ApiEndpointForm';
import CredentialPicker from '@/components/settings/credentials/CredentialPicker';
import { PDFBackendStatusCard } from '@/components/settings/PDFBackendStatusCard';
import { TierSelector } from '@/components/chat/TierSelector';
import { useSmartReadCostTier } from '@/hooks/useSmartReadCostTier';
import {
  workspaceCostProfileForTier,
  type SmartReadCostTier,
} from '@/services/smartReadTiers';
import {
  DISCUSSION_DEFAULT_BOUNDS,
  DISCUSSION_TURN_WARNING_THRESHOLD,
} from '@/services/discussionDefaults';
import {
  type SectionId,
  buildSettingsSectionPath,
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
const LogsViewerSectionLazy = React.lazy(() =>
  import('@/components/settings/LogsViewerSection').then((m) => ({ default: m.LogsViewerSection }))
);
const SETTINGS_API_PROBE_TIMEOUT_MS = 60_000;
const SETTINGS_API_PROBE_TIMEOUT_SECONDS = SETTINGS_API_PROBE_TIMEOUT_MS / 1000;

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
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

// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 通用下拉组件, 当前实现已被原生 select 取代, 保留供后续 UI 升级
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

function useProbeElapsedSeconds(active: boolean): number {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    if (!active) {
      setElapsedSeconds(0);
      return undefined;
    }

    const startedAt = Date.now();
    setElapsedSeconds(0);
    const intervalId = window.setInterval(() => {
      setElapsedSeconds(Math.min(
        SETTINGS_API_PROBE_TIMEOUT_SECONDS,
        Math.floor((Date.now() - startedAt) / 1000),
      ));
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [active]);

  return elapsedSeconds;
}

function sanitizeSettingsUserMessage(value: string, fallback: string): string {
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (!normalized) {
    return fallback;
  }
  if (
    /(?:\/(?:api|runtime|resources|pipeline|memory)\/|https?:\/\/|[A-Za-z]:\\|api[_\s-]?key|base[_\s-]?url|token|secret|authorization|bearer|env=|env_refs|capability_[a-z0-9_]*|[{}[\]"`])/i.test(normalized)
    || /^[a-z]+(?:_[a-z0-9]+){1,}$/i.test(normalized)
  ) {
    return fallback;
  }
  return normalized.length > 120 ? `${normalized.slice(0, 117)}…` : normalized;
}

function sanitizeSettingsProbeMessage(value: string): string {
  return sanitizeSettingsUserMessage(value, '测试失败，请检查服务地址、访问密钥和模型名称。');
}

function formatSettingsProbeDuration(elapsedMs: number | null | undefined): string {
  if (typeof elapsedMs !== 'number' || !Number.isFinite(elapsedMs) || elapsedMs < 0) {
    return '可用';
  }
  const seconds = Math.max(0.1, elapsedMs / 1000);
  return `可用 · 耗时 ${seconds.toFixed(seconds < 10 ? 1 : 0)} 秒`;
}

export function formatSettingsActionError(error: unknown, fallback = '操作失败，请稍后重试。'): string {
  let message = typeof error === 'string'
    ? error
    : error instanceof Error
      ? error.message
      : fallback;
  if (axios.isAxiosError(error) && error.response) {
    const body = error.response.data;
    if (body?.error?.message) {
      message = body.error.message;
    } else if (body?.detail) {
      message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } else {
      message = `请求失败 (${error.response.status})`;
    }
  }
  return sanitizeSettingsUserMessage(message, fallback);
}

export function formatApiConnectionSummary(config: SettingsApiConfig): string {
  const provider = sanitizeSettingsUserMessage(config.provider, '未填写供应商');
  const model = sanitizeSettingsUserMessage(config.model, '未填写模型');
  const credential = config.has_api_key ? '访问密钥已保存' : '未保存访问密钥';
  return `${provider} · ${model} · ${credential}`;
}

export function formatApiServiceAddressSummary(config: Pick<SettingsApiConfig, 'base_url'>): string {
  return config.base_url.trim() ? '服务地址已填写' : '未填写服务地址';
}

export function formatSavedCredentialSecondary(credential: RuntimeCredentialPublic): string {
  const address = credential.base_url.trim() ? '服务地址已填写' : '服务地址未填写';
  const secret = credential.has_api_key ? '访问密钥已保存' : '未保存访问密钥';
  return `${address} · ${secret}`;
}

export function ApiConfigSummaryRow({
  label,
  config,
  subsystem,
  targetSection,
  onOpen,
}: {
  label: string;
  config: SettingsApiConfig;
  subsystem: 'chat' | 'embedding' | 'rerank';
  targetSection: SectionId;
  onOpen: (section: SectionId) => void;
}) {
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testMessage, setTestMessage] = useState('');
  const testElapsedSeconds = useProbeElapsedSeconds(testStatus === 'testing');
  const configured = Boolean(config.provider || config.base_url || config.model || config.has_api_key);
  const testEndpoint = subsystem === 'chat'
    ? '/api/chat/test'
    : subsystem === 'embedding'
      ? '/api/embedding/test'
      : '/api/rerank/test';

  const runTest = async () => {
    if (!configured || testStatus === 'testing') return;
    setTestStatus('testing');
    setTestMessage('');
    try {
      const { data } = await axios.post<{ ok: boolean; status?: number; error?: string; elapsed_ms?: number }>(
        `${getApiBaseUrl()}${testEndpoint}`,
        {
          provider: config.provider,
          base_url: config.base_url,
          api_key: null,
          model: config.model,
        },
        { timeout: SETTINGS_API_PROBE_TIMEOUT_MS },
      );
      if (!data.ok) {
        throw new Error(data.error || `HTTP ${data.status ?? 0}`);
      }
      setTestStatus('ok');
      setTestMessage(formatSettingsProbeDuration(data.elapsed_ms));
    } catch (err: unknown) {
      setTestStatus('fail');
      setTestMessage(sanitizeSettingsProbeMessage(formatSettingsActionError(err, '测试失败，请检查服务地址、访问密钥和模型名称。')));
    } finally {
      window.setTimeout(() => {
        setTestStatus((current) => current === 'testing' ? current : 'idle');
        setTestMessage('');
      }, 6000);
    }
  };

  const testLabel = testStatus === 'testing'
    ? `测试中 ${testElapsedSeconds}s / ${SETTINGS_API_PROBE_TIMEOUT_SECONDS}s`
    : testStatus === 'ok'
      ? '可用'
      : testStatus === 'fail'
        ? '失败'
        : '测试';

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-outline-variant/50 bg-surface-low p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold text-foreground">{label}</h3>
          <span className={cn(
            'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium',
            configured
              ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
              : 'bg-surface-high text-foreground/45',
          )}>
            {configured ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
            {configured ? '已配置' : '未配置'}
          </span>
        </div>
        <p className="mt-1 truncate text-[11px] text-foreground/50">
          {formatApiConnectionSummary(config)}
        </p>
        <p className="mt-1 truncate text-[10px] text-foreground/35">
          {formatApiServiceAddressSummary(config)}
        </p>
        {testMessage ? (
          <p
            className={cn(
              'mt-1 line-clamp-2 text-[11px]',
              testStatus === 'ok' ? 'text-emerald-600 dark:text-emerald-300' : 'text-red-600 dark:text-red-300',
            )}
            title={testMessage}
          >
            {testMessage}
          </p>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={() => void runTest()}
          disabled={!configured || testStatus === 'testing'}
          className={cn(
            'inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
            testStatus === 'ok'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300'
              : testStatus === 'fail'
                ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300'
                : 'border-outline-variant bg-surface-high text-foreground/70 hover:border-primary/35 hover:text-primary',
          )}
        >
          {testStatus === 'testing'
            ? <Loader2 size={14} className="animate-spin" />
            : testStatus === 'ok'
              ? <CheckCircle2 size={14} />
              : <Play size={14} />}
          {testLabel}
        </button>
        <button
          type="button"
          onClick={() => onOpen(targetSection)}
          className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border border-outline-variant bg-surface-high px-3 py-2 text-xs font-medium text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary"
        >
          <ChevronRight size={14} />
          配置
        </button>
      </div>
    </div>
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

interface ChatContextCompressionConfig {
  enabled: boolean;
  trigger_tokens: number;
  target_tokens: number;
  keep_recent_turns: number;
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

type EndpointSubsystem = 'generation' | 'embedding' | 'rerank';

function SectionApiSettings({
  onOpenSection,
}: {
  onOpenSection: (section: SectionId) => void;
}) {
  const [settings, setSettings] = useState<UnifiedSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setSettings(await getUnifiedSettings());
    } catch (err: unknown) {
      setError(formatSettingsActionError(err, 'API 配置加载失败，请稍后重试。'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <section className="space-y-4">
      <div>
        <h2 className="font-headline text-lg font-semibold text-foreground">API 配置</h2>
        <p className="mt-1 text-xs leading-relaxed text-foreground/55">
          统一查看研读/写作、向量化、重排序和凭证中心状态；具体编辑仍走各自的专用表单。
        </p>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-foreground/55">
          <Loader2 size={14} className="animate-spin" />
          正在加载 API 配置…
        </div>
      ) : error ? (
        <div className="rounded-lg border border-red-500/20 bg-red-50 p-3 text-xs text-red-700 dark:bg-red-500/10 dark:text-red-300">
          {error}
        </div>
      ) : settings ? (
        <>
          <div className="grid grid-cols-1 gap-3">
            <ApiConfigSummaryRow
              label="研读和写作"
              config={settings.api.chat}
              subsystem="chat"
              targetSection="chat"
              onOpen={onOpenSection}
            />
            <ApiConfigSummaryRow
              label="向量化"
              config={settings.api.embedding}
              subsystem="embedding"
              targetSection="semantic-routing"
              onOpen={onOpenSection}
            />
            <ApiConfigSummaryRow
              label="重排序"
              config={settings.api.rerank}
              subsystem="rerank"
              targetSection="semantic-routing"
              onOpen={onOpenSection}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <button
              type="button"
              onClick={() => onOpenSection('credentials')}
              className="rounded-lg border border-outline-variant/50 bg-surface-low p-3 text-left transition-colors hover:border-primary/35"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-semibold text-foreground">API 凭证</span>
                <Key size={16} className="text-foreground/40" />
              </div>
              <p className="mt-2 text-xs text-foreground/55">
                共 {settings.credentials.total} 个，启用 {settings.credentials.enabled} 个
              </p>
              <p className="mt-1 text-[10px] text-foreground/35">
                研读/写作 {settings.credentials.generation} · 向量 {settings.credentials.embedding} · 重排 {settings.credentials.rerank}
              </p>
            </button>
            <button
              type="button"
              onClick={() => onOpenSection('experimental')}
              className="rounded-lg border border-outline-variant/50 bg-surface-low p-3 text-left transition-colors hover:border-primary/35"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-semibold text-foreground">功能开关</span>
                <ToggleLeft size={16} className="text-foreground/40" />
              </div>
              <p className="mt-2 text-xs text-foreground/55">
                {settings.feature_flags.filter((flag) => flag.current).length} / {settings.feature_flags.length} 已启用
              </p>
              <p className="mt-1 truncate text-[10px] text-foreground/35">
                管理 Wiki、经验沉淀、讨论和检索能力
              </p>
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}

function credentialToEndpointForm(credential: RuntimeCredentialPublic): ApiEndpointFormValue {
  return {
    provider: credential.provider,
    baseUrl: credential.base_url,
    apiKey: '',
    model: credential.model,
  };
}

function AppliedCredentialPicker({
  subsystem,
  selectedId,
  onSelectedIdChange,
  onApplied,
  disabled,
}: {
  subsystem: EndpointSubsystem;
  selectedId: string;
  onSelectedIdChange: (credentialId: string) => void;
  onApplied: (credential: RuntimeCredentialPublic) => void;
  disabled?: boolean;
}) {
  const trackedTimeout = useTrackedTimeout();
  const [credentials, setCredentials] = useState<RuntimeCredentialPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [status, setStatus] = useState<'idle' | 'ok' | 'fail'>('idle');
  const [message, setMessage] = useState('');

  const loadCredentials = useCallback(async () => {
    setLoading(true);
    setMessage('');
    try {
      const data = await listCredentials({
        category: subsystem,
        enabledOnly: true,
      });
      setCredentials(data);
      if (!selectedId && data.length === 1) {
        onSelectedIdChange(data[0].credential_id);
      }
    } catch (err: unknown) {
      setStatus('fail');
      setMessage(formatSettingsActionError(err, '已保存 API 加载失败，请稍后重试。'));
    } finally {
      setLoading(false);
    }
  }, [onSelectedIdChange, selectedId, subsystem]);

  useEffect(() => {
    void loadCredentials();
  }, [loadCredentials]);

  const selectedCredential = credentials.find((item) => item.credential_id === selectedId) ?? null;

  const applySelected = async () => {
    if (!selectedCredential) {
      setStatus('fail');
      setMessage('请选择一个已保存 API。');
      trackedTimeout(() => setStatus('idle'), 3000);
      return;
    }
    setApplying(true);
    setStatus('idle');
    setMessage('');
    try {
      await applyCredentialToSubsystem(subsystem, selectedCredential.credential_id);
      onApplied(selectedCredential);
      setStatus('ok');
      setMessage(`已应用 ${selectedCredential.provider} · ${selectedCredential.model}`);
      trackedTimeout(() => setStatus('idle'), 3000);
    } catch (err: unknown) {
      setStatus('fail');
      setMessage(formatSettingsActionError(err, '应用已保存 API 失败，请稍后重试。'));
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="rounded-lg border border-outline-variant/50 bg-surface-lowest p-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <Field
          label="已保存 API"
          tooltip="从 API 凭证中心选择并应用；原始访问密钥只在后端内部读取，不经过前端。"
          htmlFor={`${subsystem}-credential-picker`}
        >
          <select
            id={`${subsystem}-credential-picker`}
            value={selectedId}
            onChange={(event) => onSelectedIdChange(event.target.value)}
            disabled={disabled || loading || applying}
            className="w-full rounded-lg border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none disabled:opacity-60"
          >
            <option value="">{loading ? '正在加载 API…' : '选择已保存 API'}</option>
            {credentials.map((credential) => (
              <option key={credential.credential_id} value={credential.credential_id}>
                {formatSavedCredentialLabel(credential)}
              </option>
            ))}
          </select>
        </Field>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => void loadCredentials()}
            disabled={disabled || loading || applying}
            className="inline-flex items-center gap-1.5 rounded-lg border border-outline-variant bg-surface-high px-3 py-2 text-xs font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:opacity-50"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            刷新
          </button>
          <button
            type="button"
            onClick={() => void applySelected()}
            disabled={disabled || applying || !selectedCredential}
            className="inline-flex items-center gap-1.5 rounded-lg border border-primary bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
          >
            {applying ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            应用
          </button>
        </div>
      </div>
      {selectedCredential ? (
        <p className="mt-2 truncate text-[11px] text-foreground/45">
          {formatSavedCredentialSecondary(selectedCredential)}
        </p>
      ) : credentials.length === 0 && !loading ? (
        <p className="mt-2 text-[11px] text-foreground/45">
          没有可用凭证。请先到“API 凭证”分区新增。
        </p>
      ) : null}
      {message ? (
        <p className={cn(
          'mt-2 text-[11px]',
          status === 'ok' ? 'text-emerald-700 dark:text-emerald-300' : 'text-red-700 dark:text-red-300',
        )}>
          {message}
        </p>
      ) : null}
    </div>
  );
}

function SmartReadDefaultTierControl(): JSX.Element {
  const [tier, setTier] = useSmartReadCostTier(loadSettings().workspace.smartReadCostTier ?? 'medium');

  const handleTierChange = useCallback((nextTier: SmartReadCostTier) => {
    setTier(nextTier);
    const settings = loadSettings();
    settings.workspace.smartReadCostTier = nextTier;
    settings.workspace.aiCostProfile = workspaceCostProfileForTier(nextTier);
    saveSettings(settings);
  }, [setTier]);

  return (
    <div className="rounded-lg border border-outline-variant/50 bg-surface-low p-3">
      <div className="flex flex-col gap-3 min-[720px]:flex-row min-[720px]:items-start min-[720px]:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-foreground/75">智能研读默认成本模式</p>
          <p className="mt-1 text-[11px] leading-relaxed text-foreground/50">
            这里控制智能研读、知识库智读和工作台问答的默认调用预算；提问界面不再单独显示这个开关。
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-foreground/45">
            Claude 系列最高用 <span className="font-semibold text-foreground/70">Max</span>；
            Codex 系列最高用 <span className="font-semibold text-foreground/70">XHigh</span>，快速任务可选 Fast/低成本类配置。
          </p>
        </div>
        <TierSelector
          selectedTier={tier}
          onTierChange={handleTierChange}
          label="默认档位"
        />
      </div>
    </div>
  );
}

function SectionChat({ t, settings, onChange, isDirty }: { t: (k: string, p?: Record<string, string | number>) => string; settings: AppSettings; onChange: (s: AppSettings) => void; isDirty: boolean }) {
  const llm = settings.llm;
  const setLlm = (patch: Partial<typeof llm>) => onChange({ ...settings, llm: { ...llm, ...patch } });
  const trackedTimeout = useTrackedTimeout();

  const [config, setConfig] = useState<ChatPublicConfig | null>(null);
  const [form, setForm] = useState<ApiEndpointFormValue>({ provider: '', baseUrl: '', apiKey: '', model: '' });
  const [selectedCredentialId, setSelectedCredentialId] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'fail'>('idle');
  const [saveError, setSaveError] = useState('');

  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testError, setTestError] = useState('');
  const testElapsedSeconds = useProbeElapsedSeconds(testStatus === 'testing');
  const [discoveredModels, setDiscoveredModels] = useState<DiscoveredModel[]>([]);
  const [discoverStatus, setDiscoverStatus] = useState<'idle' | 'loading' | 'ok' | 'fail'>('idle');
  const [discoverError, setDiscoverError] = useState('');
  const [compression, setCompression] = useState<ChatContextCompressionConfig>({
    enabled: true,
    trigger_tokens: 24000,
    target_tokens: 2000,
    keep_recent_turns: 6,
    updated_at: '',
  });
  const [compressionStatus, setCompressionStatus] = useState<'idle' | 'saving' | 'saved' | 'fail'>('idle');
  const [compressionError, setCompressionError] = useState('');

  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const [{ data }, compressionResponse] = await Promise.all([
        axios.get<ChatPublicConfig>(`${getApiBaseUrl()}/api/chat/config`),
        axios.get<ChatContextCompressionConfig>(`${getApiBaseUrl()}/api/chat/context-compression`),
      ]);
      setConfig(data);
      setCompression(compressionResponse.data);
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
      setSaveError(formatSettingsActionError(err));
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    if (!window.confirm('清除当前研读和写作模型配置覆盖，恢复系统默认配置？')) return;
    setSaving(true);
    try {
      const { data } = await axios.delete<ChatPublicConfig>(`${getApiBaseUrl()}/api/chat/config`);
      setConfig(data);
      setForm({ provider: '', baseUrl: '', apiKey: '', model: '' });
      setSaveStatus('saved');
      trackedTimeout(() => setSaveStatus('idle'), 3000);
    } catch (err: unknown) {
      setSaveStatus('fail');
      setSaveError(formatSettingsActionError(err));
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
        { timeout: SETTINGS_API_PROBE_TIMEOUT_MS },
      );
      if (!data.ok) {
        throw new Error(data.error || `HTTP ${data.status}`);
      }
      setTestStatus('ok');
      if (isDirty) {
        saveSettings(settings);
      }
    } catch (err: unknown) {
      setTestStatus('fail');
      setTestError(sanitizeSettingsProbeMessage(formatSettingsActionError(err, '测试失败，请检查服务地址、访问密钥和模型名称。')));
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
      setDiscoverError(sanitizeSettingsUserMessage(result.error || '获取失败', '获取模型列表失败，请检查服务地址和访问密钥。'));
    }
    trackedTimeout(() => setDiscoverStatus('idle'), 4000);
  };

  const handleCompressionSave = async () => {
    setCompressionStatus('saving');
    setCompressionError('');
    try {
      const { data } = await axios.put<ChatContextCompressionConfig>(
        `${getApiBaseUrl()}/api/chat/context-compression`,
        compression,
      );
      setCompression(data);
      setCompressionStatus('saved');
      trackedTimeout(() => setCompressionStatus('idle'), 3000);
    } catch (err: unknown) {
      setCompressionStatus('fail');
      setCompressionError(formatSettingsActionError(err));
    }
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
      <div className="rounded-lg border border-outline-variant/50 bg-surface-low px-3 py-2">
        <p className="text-[11px] leading-relaxed text-foreground/55">
          这里配置智能研读和写作使用的 API；主界面智能研读、知识库智读和工作台问答共用这套接口。
          当前应用内同类请求会按顺序发送，避免上游并发。
        </p>
      </div>
      <SmartReadDefaultTierControl />
      {loading ? (
        <p className="text-xs text-foreground/40 italic">加载中…</p>
      ) : (
        <>
          <AppliedCredentialPicker
            subsystem="generation"
            selectedId={selectedCredentialId}
            onSelectedIdChange={setSelectedCredentialId}
            disabled={saving}
            onApplied={(credential) => {
              setConfig({
                provider: credential.provider,
                base_url: credential.base_url,
                model: credential.model,
                has_api_key: credential.has_api_key,
                api_key_masked: credential.api_key_masked,
                updated_at: new Date().toISOString(),
              });
              setForm(credentialToEndpointForm(credential));
              setSaveStatus('saved');
              trackedTimeout(() => setSaveStatus('idle'), 3000);
            }}
          />
          <ApiEndpointForm
            idPrefix="chat"
            value={form}
            onChange={setForm}
            providerLabel={t('settings.provider')}
            apiKeyLabel={t('settings.api_key')}
            modelLabel={t('settings.chat_model')}
            baseUrlLabel={t('settings.base_url')}
            providerPlaceholder="任意兼容服务名称，可手动填写"
            apiKeyPlaceholder="粘贴服务提供的访问密钥"
            modelPlaceholder={t('settings.chat_model_placeholder') || '填写服务提供的模型名称'}
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
            testElapsedSeconds={testElapsedSeconds}
            testTimeoutSeconds={SETTINGS_API_PROBE_TIMEOUT_SECONDS}
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
                恢复系统默认
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
        <Field label={t('settings.max_tokens')} tooltip="限制智能研读或写作一次回复最多生成多少内容；不是笔记数量，也不会截断已保存的原文。" htmlFor="chat-max-tokens">
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
      <div className="rounded-lg border border-outline-variant/40 bg-surface-lowest p-4">
        <div className="flex flex-col gap-3 min-[720px]:flex-row min-[720px]:items-start min-[720px]:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-semibold text-foreground/75">长对话自动摘要</p>
            <p className="mt-1 text-[11px] leading-relaxed text-foreground/50">
              对话很长时，把较早内容整理成摘要以继续提问；原始对话仍完整保留，供搜索、恢复和分叉使用。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-foreground/55">{compression.enabled ? '已启用' : '已关闭'}</span>
            <ToggleSwitch
              checked={compression.enabled}
              onChange={(enabled) => setCompression(prev => ({ ...prev, enabled }))}
              ariaLabel="启用长对话自动摘要"
            />
          </div>
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <Field label="开始整理的长度" tooltip="对话累计内容接近这个长度后，系统开始把较早消息整理成摘要。数值越大，越晚整理。" htmlFor="chat-compression-trigger">
            <input
              id="chat-compression-trigger"
              type="number"
              min={512}
              max={1000000}
              step={512}
              value={compression.trigger_tokens}
              onChange={event => setCompression(prev => ({ ...prev, trigger_tokens: Number(event.target.value) }))}
              className="w-full rounded-lg border border-outline-variant/50 bg-surface-high px-3 py-2 font-mono text-sm text-foreground focus:border-primary/40 focus:outline-none"
            />
          </Field>
          <Field label="整理后的摘要长度" tooltip="较早对话被整理后保留的大致长度，必须小于开始整理的长度。" htmlFor="chat-compression-target">
            <input
              id="chat-compression-target"
              type="number"
              min={128}
              max={64000}
              step={128}
              value={compression.target_tokens}
              onChange={event => setCompression(prev => ({ ...prev, target_tokens: Number(event.target.value) }))}
              className="w-full rounded-lg border border-outline-variant/50 bg-surface-high px-3 py-2 font-mono text-sm text-foreground focus:border-primary/40 focus:outline-none"
            />
          </Field>
          <Field label="最近对话保留轮数" tooltip="整理较早消息时，最近 N 轮会继续保留原文，方便接着追问。" htmlFor="chat-compression-keep">
            <input
              id="chat-compression-keep"
              type="number"
              min={1}
              max={100}
              value={compression.keep_recent_turns}
              onChange={event => setCompression(prev => ({ ...prev, keep_recent_turns: Number(event.target.value) }))}
              className="w-full rounded-lg border border-outline-variant/50 bg-surface-high px-3 py-2 font-mono text-sm text-foreground focus:border-primary/40 focus:outline-none"
            />
          </Field>
        </div>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className={cn(
            'text-[11px]',
            compressionStatus === 'saved' ? 'text-emerald-600 dark:text-emerald-300' : compressionStatus === 'fail' ? 'text-red-600 dark:text-red-300' : 'text-foreground/40',
          )}>
            {compressionStatus === 'saved'
              ? '长对话自动摘要设置已保存。'
              : compressionStatus === 'fail'
                ? compressionError || '长对话自动摘要设置保存失败。'
                : compression.updated_at ? `上次更新：${compression.updated_at}` : '保存后，对新的智能研读对话生效。'}
          </p>
          <button
            type="button"
            onClick={() => void handleCompressionSave()}
            disabled={compressionStatus === 'saving'}
            className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
          >
            {compressionStatus === 'saving' ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            {compressionStatus === 'saved' ? '已保存' : '保存摘要设置'}
          </button>
        </div>
      </div>
      <SectionSampling t={t} embedded />
    </section>
  );
}

function EmbeddingCard({ t, settings: _settings, onChange: _onChange }: { t: (k: string, p?: Record<string, string | number>) => string; settings: AppSettings; onChange: (s: AppSettings) => void }) {
  const trackedTimeout = useTrackedTimeout();
  const [config, setConfig] = useState<EmbeddingPublicConfig | null>(null);
  const [form, setForm] = useState<ApiEndpointFormValue>({ provider: '', baseUrl: '', apiKey: '', model: '' });
  const [selectedCredentialId, setSelectedCredentialId] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'fail'>('idle');
  const [saveError, setSaveError] = useState('');
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testError, setTestError] = useState('');
  const testElapsedSeconds = useProbeElapsedSeconds(testStatus === 'testing');
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
      setSaveError(formatSettingsActionError(err));
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    if (!window.confirm('清除当前语义向量配置覆盖，恢复系统默认配置？')) return;
    setSaving(true);
    try {
      const { data } = await axios.delete<EmbeddingPublicConfig>(`${getApiBaseUrl()}/api/embedding/config`);
      setConfig(data);
      setForm({ provider: '', baseUrl: '', apiKey: '', model: '' });
      setSaveStatus('saved');
      trackedTimeout(() => setSaveStatus('idle'), 3000);
    } catch (err: unknown) {
      setSaveStatus('fail');
      setSaveError(formatSettingsActionError(err));
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
        },
        { timeout: SETTINGS_API_PROBE_TIMEOUT_MS },
      );
      if (data.ok) {
        setTestStatus('ok');
      } else {
        setTestStatus('fail');
        setTestError(sanitizeSettingsProbeMessage(data.error || `HTTP ${data.status}`));
      }
      trackedTimeout(() => setTestStatus('idle'), 6000);
    } catch (err: unknown) {
      setTestStatus('fail');
      setTestError(formatSettingsActionError(err, '测试失败，请检查服务地址、访问密钥和模型名称。'));
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
      setDiscoverError(sanitizeSettingsUserMessage(result.error || '获取失败', '获取模型列表失败，请检查服务地址和访问密钥。'));
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
          <AppliedCredentialPicker
            subsystem="embedding"
            selectedId={selectedCredentialId}
            onSelectedIdChange={setSelectedCredentialId}
            disabled={saving}
            onApplied={(credential) => {
              setConfig({
                provider: credential.provider,
                base_url: credential.base_url,
                model: credential.model,
                has_api_key: credential.has_api_key,
                api_key_masked: credential.api_key_masked,
                updated_at: new Date().toISOString(),
              });
              setForm(credentialToEndpointForm(credential));
              setSaveStatus('saved');
              trackedTimeout(() => setSaveStatus('idle'), 3000);
            }}
          />
          <ApiEndpointForm
            idPrefix="embedding"
            value={form}
            onChange={setForm}
            providerLabel={t('settings.embedding_provider')}
            apiKeyLabel={t('settings.embedding_api_key')}
            modelLabel={t('settings.embedding_model')}
            baseUrlLabel={t('settings.embedding_base_url')}
            providerPlaceholder="任意兼容向量服务，可手动填写"
            apiKeyPlaceholder="粘贴服务提供的访问密钥"
            modelPlaceholder="填写服务提供的向量模型名称"
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
            testElapsedSeconds={testElapsedSeconds}
            testTimeoutSeconds={SETTINGS_API_PROBE_TIMEOUT_SECONDS}
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
                恢复系统默认
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
          <p className="mt-1.5 text-[11px] leading-relaxed text-foreground/45">
            默认写入安装目录下的 <code className="rounded bg-surface-high px-1 font-mono text-foreground/65">workspace_artifacts/generated/output</code>，
            生成的导出文件、报告和临时产物都集中在这里，方便备份和清理。
          </p>
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

interface LocalRerankStatus {
  available: boolean;
  disabled: boolean;
  weights_present: boolean;
  allow_download: boolean;
  model_name: string;
  device: string;
  device_source: string;
  max_length: number;
  batch_size: number;
  loaded: boolean;
  hf_cache_dir: string;
}

/**
 * Status chip for the local rerank fallback.
 *
 * Tells the user whether rerank will gracefully fall back to a local
 * model when the configured API rerank fails. Polls /api/rerank/local-status
 * once on mount — fast (<1ms backend probe, no model loading).
 *
 * Color rubric:
 *   green   → available (API failure → local fallback works)
 *   amber   → weights missing but download allowed
 *   slate   → disabled by operator (LOCAL_RERANK_DISABLED=1)
 *   red     → weights missing AND no download (API failure → static sort)
 */
function LocalRerankFallbackChip() {
  const [status, setStatus] = useState<LocalRerankStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const { data } = await axios.get<LocalRerankStatus>(
          `${getApiBaseUrl()}/api/rerank/local-status`
        );
        if (!cancelled) setStatus(data);
      } catch {
        if (!cancelled) setStatus(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <span className="text-[10px] text-foreground/40 italic">
        正在探测本地回退…
      </span>
    );
  }
  if (!status) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600 dark:bg-slate-700/40 dark:text-slate-300">
        本地回退: 状态未知
      </span>
    );
  }

  let chipClass: string;
  let label: string;
  let tip: string;

  if (status.disabled) {
    chipClass = "bg-slate-100 text-slate-600 dark:bg-slate-700/40 dark:text-slate-300";
    label = "本地回退: 已禁用";
    tip = `运维通过 LOCAL_RERANK_DISABLED=1 关闭。云端 rerank 失败时将退回到静态 hybrid_score 排序，不再尝试本地模型。`;
  } else if (status.available) {
    chipClass = "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300";
    label = `本地回退: 可用 · ${status.device.toUpperCase()}`;
    tip = `云端 rerank API 失败时，会自动回退到本地模型 ${status.model_name}（${status.device}${status.device_source === 'env_override' ? '，已手动指定' : '，自动探测'}），不需要联网。模型权重已就绪。`;
  } else if (status.weights_present === false && status.allow_download) {
    chipClass = "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300";
    label = "本地回退: 需下载";
    tip = `权重 ${status.model_name} 未在本机 HF 缓存，但允许联网下载（LOCAL_RERANK_ALLOW_DOWNLOAD=1）。首次回退会拉取大约 1.5GB。`;
  } else {
    chipClass = "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300";
    label = "本地回退: 不可用";
    tip = `本机没有 ${status.model_name} 权重，且未允许下载（LOCAL_RERANK_ALLOW_DOWNLOAD 未设置）。云端 rerank 失败时，将退回到静态 hybrid_score 排序。要启用：先 \`pip install transformers torch\`，然后把权重放到 ${status.hf_cache_dir}，或者设置 LOCAL_RERANK_ALLOW_DOWNLOAD=1 允许联网下载。`;
  }

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${chipClass}`}
      title={tip}
    >
      {label}
    </span>
  );
}

function RerankCard({ t: _t }: { t: (k: string, p?: Record<string, string | number>) => string }) {
  const trackedTimeout = useTrackedTimeout();
  const [config, setConfig] = useState<RerankPublicConfig | null>(null);
  const [form, setForm] = useState<ApiEndpointFormValue>({ provider: '', baseUrl: '', apiKey: '', model: '' });
  const [selectedCredentialId, setSelectedCredentialId] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testMessage, setTestMessage] = useState('');
  const testElapsedSeconds = useProbeElapsedSeconds(testStatus === 'testing');
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
      setSaveError(formatSettingsActionError(err));
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    if (!window.confirm('清除当前重排模型配置覆盖，恢复系统默认配置？')) return;
    setSaving(true);
    try {
      const { data } = await axios.delete<RerankPublicConfig>(`${getApiBaseUrl()}/api/rerank/config`);
      setConfig(data);
      setForm({ provider: '', baseUrl: '', apiKey: '', model: '' });
      setSaveStatus('saved');
      trackedTimeout(() => setSaveStatus('idle'), 3000);
    } catch (err: unknown) {
      setSaveStatus('fail');
      setSaveError(formatSettingsActionError(err));
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
        },
        { timeout: SETTINGS_API_PROBE_TIMEOUT_MS },
      );
      if (data.ok) {
        setTestStatus('ok');
        setTestMessage(formatSettingsProbeDuration(data.elapsed_ms));
      } else {
        setTestStatus('fail');
        setTestMessage(sanitizeSettingsProbeMessage(data.error || `HTTP ${data.status}`));
      }
      trackedTimeout(() => setTestStatus('idle'), 6000);
    } catch (err: unknown) {
      setTestStatus('fail');
      setTestMessage(formatSettingsActionError(err, '测试失败，请检查服务地址、访问密钥和模型名称。'));
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
      setDiscoverError(sanitizeSettingsUserMessage(result.error || '获取失败', '获取模型列表失败，请检查服务地址和访问密钥。'));
    }
    trackedTimeout(() => setDiscoverStatus('idle'), 4000);
  };

  return (
    <div className="space-y-4 p-4 bg-surface-lowest rounded-lg border border-outline-variant/40">
      <div className="flex items-center justify-between">
        <h4 className="font-headline text-xs font-semibold text-foreground flex items-center gap-2">
          <Layers size={14} className="text-primary" />
          Rerank 模型配置
          <Tooltip text="文献检索后的精排模型，可接云端 rerank，也可接本地 BGE 等 Cohere 兼容服务。保存后会立即应用到本机语义路由。" />
        </h4>
        <div className="flex items-center gap-2">
          <LocalRerankFallbackChip />
          <StatusPill status={config?.has_api_key ? 'online' : 'ready'} t={_t} />
        </div>
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
          <AppliedCredentialPicker
            subsystem="rerank"
            selectedId={selectedCredentialId}
            onSelectedIdChange={setSelectedCredentialId}
            disabled={saving}
            onApplied={(credential) => {
              setConfig({
                provider: credential.provider,
                base_url: credential.base_url,
                model: credential.model,
                has_api_key: credential.has_api_key,
                api_key_masked: credential.api_key_masked,
                updated_at: new Date().toISOString(),
              });
              setForm(credentialToEndpointForm(credential));
              setSaveStatus('saved');
              trackedTimeout(() => setSaveStatus('idle'), 3000);
            }}
          />
          <ApiEndpointForm
            idPrefix="rerank"
            value={form}
            onChange={setForm}
            providerLabel="供应商"
            apiKeyLabel="访问密钥"
            modelLabel="模型名称"
            baseUrlLabel="服务地址"
            providerPlaceholder="任意兼容重排服务，可手动填写"
            apiKeyPlaceholder="粘贴服务提供的访问密钥；本地服务可留空"
            modelPlaceholder="填写服务提供的重排模型名称"
            baseUrlPlaceholder="填写兼容重排服务地址"
            apiKeyTooltip="保存为本地运行时配置；本地重排服务可留空。"
            modelTooltip="例如 bge-reranker-v2-m3、qwen3-rerank、gte-rerank。"
            baseUrlTooltip="兼容重排接口的完整服务地址。"
            savedKeyMasked={config?.has_api_key ? config.api_key_masked : ''}
            updatedAt={config?.updated_at}
            models={discoveredModels}
            onDiscover={handleDiscover}
            discoverStatus={discoverStatus}
            discoverError={discoverError}
            onTest={handleTest}
            testStatus={testStatus}
            testError={testMessage}
            testElapsedSeconds={testElapsedSeconds}
            testTimeoutSeconds={SETTINGS_API_PROBE_TIMEOUT_SECONDS}
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
                恢复系统默认
              </button>
            ) : null}
          />
        </>
      )}
    </div>
  );
}

function SectionSemanticRouting({ t, settings, onChange }: { t: (k: string, p?: Record<string, string | number>) => string; settings: AppSettings; onChange: (s: AppSettings) => void }) {
  const ws = settings.workspace;
  const setWs = (patch: Partial<typeof ws>) => onChange({ ...settings, workspace: { ...ws, ...patch } });

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
      <div className="rounded-lg border border-primary/15 bg-primary/5 p-3 text-[11px] leading-relaxed text-foreground/55">
        <p className="font-medium text-foreground/70">语义路由 = Embedding 召回 + Rerank 精排</p>
        <p className="mt-1">
          Embedding 决定哪些片段先进入候选池；Rerank 决定这些候选证据的最终顺序。两者可分别绑定保存的 API 凭证，也可以指向本地服务。
        </p>
      </div>
      <div className="rounded-lg border border-outline-variant/45 bg-surface-lowest p-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-semibold text-foreground/75">检索与排序范围</p>
            <p className="mt-1 text-[11px] leading-relaxed text-foreground/50">
              语义路由只控制候选证据怎么召回、怎么精排；温度、核采样、最大输出和提示词属于生成设置，放在“研读和写作”和“多智能体讨论”里。
            </p>
          </div>
          <Field
            label="检索 Top-K"
            tooltip="智能研读和知识库智读请求候选证据的默认数量，范围 3-20。"
            htmlFor="semantic-routing-retrieval-top-k"
          >
            <input
              id="semantic-routing-retrieval-top-k"
              type="number"
              min={3}
              max={20}
              step={1}
              value={ws.retrievalTopK}
              aria-label="语义路由检索 Top-K"
              onChange={event => {
                const next = Number(event.target.value);
                if (Number.isFinite(next)) {
                  setWs({ retrievalTopK: Math.min(20, Math.max(3, Math.round(next))) });
                }
              }}
              className="w-full rounded-lg border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground transition-colors focus:border-primary/40 focus:outline-none md:w-32"
            />
          </Field>
        </div>
      </div>
      <details className="rounded-lg border border-outline-variant/45 bg-surface-lowest px-3 py-2 text-[11px] text-foreground/50">
        <summary className="cursor-pointer font-medium text-foreground/65 hover:text-foreground/80">本地向量化与重排怎么接？</summary>
        <p className="mt-2 leading-relaxed">
          本地语义路由由两段组成：向量化把文本转成可检索表示，填写兼容服务地址和模型名称；
          重排模型会对候选证据重新排序。填写兼容服务地址和模型名称；本地服务没有鉴权时访问密钥可留空。
          常见组合是本地向量服务提供语义向量，BGE、Jina 或 Cohere 兼容服务提供重排。
        </p>
      </details>
      <EmbeddingCard t={t} settings={settings} onChange={onChange} />
      <RerankCard t={t} />
    </section>
  );
}

function SectionSampling({
  t,
  embedded = false,
}: {
  t: (k: string, p?: Record<string, string | number>) => string;
  embedded?: boolean;
}) {
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
      const msg = formatSettingsActionError(err);
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
      const msg = formatSettingsActionError(err);
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
      const msg = formatSettingsActionError(err);
      setSaveError(prev => ({ ...prev, [task]: msg }));
    }
  };

  if (loading) {
    return (
      <section className={cn('space-y-5', embedded && 'rounded-lg border border-outline-variant/40 bg-surface-lowest p-4')}>
        <div className="flex items-center gap-2 text-foreground/40">
          <Loader2 size={16} className="animate-spin" />
          <span className="text-sm">{t('common.loading')}</span>
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className={cn('space-y-5', embedded && 'rounded-lg border border-outline-variant/40 bg-surface-lowest p-4')}>
        <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg dark:border-red-700/40 dark:bg-red-500/15">
          <AlertCircle size={16} className="text-red-500 flex-shrink-0 mt-0.5" />
          <p className="font-body text-xs text-red-700 dark:text-red-300">{error}</p>
        </div>
      </section>
    );
  }

  return (
    <section
      id={embedded ? 'section-chat-sampling' : 'section-sampling'}
      className={cn('space-y-5', embedded && 'rounded-lg border border-outline-variant/40 bg-surface-lowest p-4')}
    >
      <h3 className="font-headline text-sm font-semibold text-foreground flex items-center gap-2">
        <Cpu size={16} className="text-primary" />
        {embedded ? '任务采样参数' : t('settings.section_sampling')}
        <Tooltip text={t('settings.section_sampling_tooltip')} />
      </h3>
      <p className="text-xs text-foreground/50 leading-relaxed">
        {embedded
          ? '这些参数属于研读和写作调用。API 凭证页只管理上游连接；这里按任务覆写默认温度、Top-p、Top-k 和最大输出。'
          : t('settings.sampling_description')}
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
  const [roleDetailOpen, setRoleDetailOpen] = React.useState(false);
  const [roleNameDraft, setRoleNameDraft] = React.useState('');
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [saveState, setSaveState] = React.useState<SaveState>('idle');
  const [roleApiSaving, setRoleApiSaving] = React.useState(false);
  const [roleApiSaveState, setRoleApiSaveState] = React.useState<SaveState>('idle');
  const [roleApiSaveError, setRoleApiSaveError] = React.useState('');
  const [roleApiTestState, setRoleApiTestState] = React.useState<ProbeState>('idle');
  const [roleApiTestError, setRoleApiTestError] = React.useState('');
  const roleApiTestElapsedSeconds = useProbeElapsedSeconds(roleApiTestState === 'testing');
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
    setRoleDetailOpen(true);
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
      setRoleDetailOpen(false);
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
      setRoleDiscoverError(sanitizeSettingsUserMessage(result.error || '获取失败', '获取模型列表失败，请检查服务地址和访问密钥。'));
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
      setRoleApiSaveError('供应商、服务地址和模型不能为空。');
      return;
    }
    if (!apiKey && !activeProfile.credentialId.trim()) {
      setRoleApiSaveState('error');
      setRoleApiSaveError('首次保存角色 API 时需要填写访问密钥。');
      return;
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
      setRoleApiSaveState('saved');
      trackedTimeout(() => setRoleApiSaveState('idle'), 2500);
    } catch (err: unknown) {
      setRoleApiSaveState('error');
      setRoleApiSaveError(formatSettingsActionError(err));
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
          timeoutMs: SETTINGS_API_PROBE_TIMEOUT_MS,
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
          { timeout: SETTINGS_API_PROBE_TIMEOUT_MS },
        );
        if (!data.ok) {
          throw new Error(data.error || `HTTP ${data.status}`);
        }
      }
      setRoleApiTestState('ok');
    } catch (err: unknown) {
      setRoleApiTestState('fail');
      setRoleApiTestError(formatSettingsActionError(err, '测试失败，请检查服务地址、访问密钥和模型名称。'));
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

          <Field label="默认裁判角色" tooltip="讨论页会优先从已选角色中匹配这个裁判。这里使用角色详情中显示的“讨论角色 ID”，不是角色显示名称。">
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

      {!roleDetailOpen ? (
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

        <div className="grid content-start gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {profileStore.profiles.map((profile) => (
              <div
                key={profile.id}
                className={cn(
                  'group flex min-w-0 items-start gap-2 rounded-lg border px-3 py-3 transition-colors',
                  activeProfileId === profile.id
                    ? 'border-primary/45 bg-primary/10 text-primary'
                    : 'border-outline-variant/50 bg-surface-low hover:border-primary/30 hover:bg-surface-high',
                )}
              >
                <button
                  type="button"
                  onClick={() => {
                    setActiveProfileId(profile.id);
                    setRoleDetailOpen(true);
                  }}
                  className="min-w-0 flex-1 text-left"
                >
                  <span className="block truncate text-xs font-semibold">{profile.displayName}</span>
                  <span className="mt-1 block truncate text-[10px] text-foreground/45">{describeApiBinding(profile)}</span>
                  <span className="mt-2 inline-flex rounded bg-surface-lowest px-1.5 py-0.5 text-[10px] text-foreground/45">
                    T={profile.temperature.toFixed(2)} · P={profile.topP.toFixed(2)} · {profile.maxTokens}
                  </span>
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
                <button
                  type="button"
                  onClick={() => {
                    setActiveProfileId(profile.id);
                    setRoleDetailOpen(true);
                  }}
                  className="rounded-md p-1 text-foreground/35 transition-colors hover:bg-surface-high hover:text-primary"
                  title="进入详情"
                  aria-label={`进入 ${profile.displayName} 详情`}
                >
                  <ChevronRight size={13} />
                </button>
              </div>
            ))}
        </div>
      </div>
      ) : (
      <div className="rounded-lg border border-outline-variant bg-surface-lowest p-4 shadow-sm">
          <div className="space-y-4 rounded-lg border border-outline-variant/50 bg-surface-low p-4">
            <div className="flex flex-col gap-2 border-b border-outline-variant/40 pb-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex min-w-0 items-start gap-3">
                <button
                  type="button"
                  onClick={() => setRoleDetailOpen(false)}
                  className="mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-outline-variant bg-surface-lowest text-foreground/60 transition-colors hover:border-primary/35 hover:text-primary"
                  aria-label="返回角色列表"
                  title="返回"
                >
                  <ArrowLeft size={15} />
                </button>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-foreground">{activeProfile.displayName}</p>
                  <p className="mt-0.5 text-[11px] text-foreground/45">{describeApiBinding(activeProfile)}</p>
                  <p className="mt-1 break-all text-[11px] text-foreground/45">
                    讨论角色 ID：<span className="font-mono text-foreground/65">{activeProfile.id}</span>
                  </p>
                </div>
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
                tooltip="每个角色都可以复用研读和写作设置、选择已保存 API，或单独填写一套 API。"
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
                apiKeyLabel="访问密钥"
                modelLabel="模型名称"
                baseUrlLabel="服务地址"
                providerPlaceholder="任意兼容服务名称，可手动填写"
                apiKeyPlaceholder="粘贴服务提供的访问密钥"
                modelPlaceholder="填写服务提供的模型名称"
                baseUrlPlaceholder="填写兼容服务地址"
                apiKeyTooltip="每个角色可使用不同访问密钥；保存后会进入本机已保存 API 配置，并在讨论时按角色调用。"
                modelTooltip="该角色发言时使用的模型。"
                baseUrlTooltip="兼容研读和写作模型接口的服务地址。"
                savedKeyMasked={activeProfile.apiKeyMasked}
                models={roleModels}
                onDiscover={handleRoleDiscover}
                discoverStatus={roleDiscoverState}
                discoverError={roleDiscoverError}
                onTest={handleRoleApiTest}
                testStatus={roleApiTestState}
                testError={roleApiTestError}
                testElapsedSeconds={roleApiTestElapsedSeconds}
                testTimeoutSeconds={SETTINGS_API_PROBE_TIMEOUT_SECONDS}
                onSave={handleRoleApiSave}
                saveStatus={roleApiSaving ? 'saving' : roleApiSaveState === 'error' ? 'fail' : roleApiSaveState}
                saveError={roleApiSaveError}
                saveLabel="保存角色 API"
              />
            ) : null}

            {activeProfile.apiMode === 'credential' ? (
              <div className="rounded-lg border border-outline-variant/50 bg-surface-lowest p-3">
                <CredentialPicker
                  category="generation"
                  requirement={{
                    id: `discussion-profile-${activeProfile.id}-credential`,
                    label: '已保存 API',
                    env: 'CHAT_API_KEY',
                    kind: 'api_key',
                    provider_hints: [],
                    required: false,
                    description: '来自“API 凭证”页的生成类 API 配置。',
                  }}
                  value={activeProfile.credentialId.trim() || null}
                  onChange={(credentialId) => updateProfile(activeProfile.id, { credentialId: credentialId ?? '' })}
                />
              </div>
            ) : null}

            {activeProfile.apiMode === 'default' ? (
              <div className="rounded-lg border border-outline-variant/60 bg-surface-lowest px-3 py-2 text-xs leading-relaxed text-foreground/55">
                该角色直接使用“研读和写作”分区的模型配置。需要单独指定模型或 Key 时，切换到“单独填写 API”。
              </div>
            ) : null}

            <div className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto]">
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
              <Field label="核采样" tooltip="控制候选词的累计概率，1 更开放，0 更保守。" htmlFor={`discussion-profile-${activeProfile.id}-top-p`}>
                <input
                  id={`discussion-profile-${activeProfile.id}-top-p`}
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={activeProfile.topP}
                  onChange={(event) => updateProfile(activeProfile.id, { topP: Number(event.target.value) })}
                  className="w-full rounded-lg border border-outline-variant/50 bg-surface-lowest px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none"
                />
              </Field>
              <Field label="单次发言长度上限" tooltip="限制这个角色每次发言最多生成多少内容。数值越大，回答可能更长，耗时和成本也会增加。" htmlFor={`discussion-profile-${activeProfile.id}-max-tokens`}>
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
      )}

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

function formatSavedCredentialLabel(credential: RuntimeCredentialPublic): string {
  const provider = credential.provider.trim() || '自定义供应商';
  const model = credential.model.trim() || '未命名模型';
  const disabled = credential.enabled ? '' : ' · 已停用';
  return `${provider} · ${model}${disabled}`;
}



/* ------------------------------------------------------------------ */
/*  Experimental Features section                                      */
/* ------------------------------------------------------------------ */

const FEATURE_FLAG_DISPLAY_COPY: Record<string, { label?: string; description: string }> = {
  pdf_parser_marker: {
    label: 'PDF 结构化解析(marker)',
    description: '用 marker 替代默认 PyMuPDF 解析新上传的 PDF;能识别标题层级、表格、公式与图片,RAG 检索质量更好。需先在终端 `pip install marker-pdf`(~2GB,含模型权重),首次解析每篇约 5-15 分钟。已入库的旧 PDF 不会自动重做,可在项目工作台点「重新解析以获取结构化索引」按 marker 重建。关闭后新上传 PDF 走 PyMuPDF 默认链路,已抽取的结构化数据保留。',
  },
  tolf_context: {
    label: '深度证据检索',
    description: '把问题拆成多面查询，在文献图上扩散，并按硬证据筛选结果。比默认检索更慢，但更适合综述、找数据和深度调研。',
  },
  local_rerank: {
    label: '本地重排主线',
    description: '语义路由默认用本机或已配置的重排服务整理候选证据。没有可用服务或凭证时会保留现有检索结果，不会阻断答问。',
  },
  analysis_chain_rag: {
    label: '答复附推理过程',
    description: '智能研读回答时附带结构化推理过程，包括观察、机制、证据、边界、反证和下一步。默认不增加模型调用。',
  },
  analysis_chain_rag_llm: {
    label: '增强推理说明',
    description: '让模型生成更完整的推理过程，适合需要复核思路的复杂问题。失败时会自动回到基础推理过程，不影响答问。',
  },
  analysis_chain_discussion: {
    label: '多智能体讨论附推理过程',
    description: '讨论中每个智能体发言时携带自己的推理链，可在讨论面板逐个展开查看。',
  },
  analysis_chain_carryover: {
    label: '承接上一步思路',
    description: '下一位智能体或下一轮对话会参考上一步推理，减少重复思考，让讨论更连贯。',
  },
  analysis_chain_ui: {
    label: '推理过程展开入口',
    description: '答案带有推理过程时，界面提供展开入口并默认收起。关闭后只隐藏入口，不影响答问能力。',
  },
  discussion_streaming: {
    label: '讨论实时进度',
    description: '讨论运行时逐个显示智能体完成进度，长讨论不用等全部结束才看到结果。关闭后仍可完成讨论。',
  },
  inspector_embed_unified: {
    label: '工作台右侧助手',
    description: '在研究工作台右侧检视面板直接使用智能研读和多智能体讨论完整能力，关闭后回到跳转入口。',
  },
  wiki: {
    label: 'Wiki 知识沉淀',
    description: '开启后可使用 Wiki 工作台、页面检索、编译和审阅队列，把项目资料沉淀为可回看的本地知识页。关闭后保留已有页面，只暂停入口和 API 能力。',
  },
  evolution_candidate_capture: {
    label: '经验候选收纳',
    description: '开启后，智能研读、讨论、写作任务、Skill 和 MCP 工具运行完成时，会把可复用经验放入复审队列，等待人工确认。',
  },
  evolution_review_ui: {
    label: '学到的经验复审入口',
    description: '开启后显示“学到的经验”页面，用于查看、保存、忽略和撤销经验候选。关闭时不删除已有候选。',
  },
  evolution_promotion: {
    label: '经验应用到长期记忆',
    description: '开启后，已保存的经验可以继续应用到长期记忆或 Skill 草稿。关闭时仍可复审候选，但不会写入长期记忆。',
  },
  rag_chunk_type_weighting: {
    label: 'RAG 表格/公式优先送入精排',
    description: '检索时把表格、公式、章节标题等结构化片段优先排进精排候选池，让数值答案更容易被引用。默认开启；关闭会让所有片段等权进入精排，可能更容易遗漏表格数据。',
  },
  hybrid_retrieval: {
    label: '研读答问真混合检索',
    description: '研读答问的 RAG 召回走真混合：词面 + 向量 + 精排，质量明显优于关键词重叠。默认开启；关闭会回退到关键词重叠的旧行为，主要在调试时使用。',
  },
  tolf_fusion_mode: {
    label: '深度检索 + RAG 融合',
    description: '需要先开启「深度证据检索」。两路候选会用 Reciprocal Rank Fusion 合并，深度检索负责目标侧、RAG 负责词面侧，互不替代。默认开启；关闭会回到「深度检索拿到结果就丢掉 RAG 候选」的旧行为。',
  },
  rag_structured_sibling_inclusion: {
    label: '同章节表格/公式邻居自动补全',
    description: '答完最终候选后，把命中段落所在章节里同位的表格、公式、图注自动补进上下文，让 LLM 可以引用具体数值。默认开启；关闭后，回答里出现「具体数值见 Table X」时 Table X 本身可能不在上下文。',
  },
};

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
      setLoadError(formatSettingsActionError(err, '功能开关加载失败，请稍后重试。'));
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
      const msg = formatSettingsActionError(err);
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

      {!loading && flags.map(flag => {
        const displayCopy = FEATURE_FLAG_DISPLAY_COPY[flag.name];
        const displayLabel = displayCopy?.label ?? flag.label;
        const displayDescription = displayCopy?.description ?? flag.description;
        const isMarkerFlag = flag.name === 'pdf_parser_marker';
        return (
        <div key={flag.name} className="border border-outline-variant rounded-lg p-4 bg-surface">
          {isMarkerFlag && (
            <div className="mb-3">
              <PDFBackendStatusCard />
            </div>
          )}          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <h3 className="font-semibold text-sm text-foreground">{displayLabel}</h3>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-lowest text-foreground/60 border border-outline-variant">
                  {sourceLabel(flag.source)}
                </span>
              </div>
              <p className="text-xs text-foreground/60 leading-relaxed whitespace-pre-line">{displayDescription}</p>
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
              aria-label={displayLabel}
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
        );
      })}
    </div>
  );
}



/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */
export const SETTINGS_NAV_TABS: { id: SectionId; icon: React.ElementType; labelKey: string }[] = [
  { id: 'api', icon: Key, labelKey: 'settings.section_api' },
  { id: 'workspace', icon: FolderOpen, labelKey: 'settings.section_workspace' },
  { id: 'skills', icon: Layers, labelKey: 'skills.settings_section' },
  { id: 'mcp', icon: Server, labelKey: 'settings.section_mcp' },
  { id: 'discussion', icon: Users, labelKey: 'settings.section_discussion' },
  { id: 'citation-styles', icon: BookMarked, labelKey: 'settings.section_citation_styles' },
  { id: 'experimental', icon: ToggleLeft, labelKey: 'settings.section_experimental' },
  { id: 'logs', icon: ScrollText, labelKey: 'settings.section_logs' },
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

  const setSettingsSection = useCallback((section: SectionId) => {
    const normalized = normalizeSection(section);
    setActiveSection(normalized);
    if (typeof window !== 'undefined') {
      window.history.replaceState(null, '', buildSettingsSectionPath(normalized));
    }
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const section = new URLSearchParams(window.location.search).get('section');
    if (isSectionId(section)) {
      setSettingsSection(section);
    }
  }, [setSettingsSection]);

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
    api: <SectionApiSettings onOpenSection={setSettingsSection} />,
    chat: <SectionChat t={t} settings={settings} onChange={setSettings} isDirty={isDirty} />,
    embedding: <SectionSemanticRouting t={t} settings={settings} onChange={setSettings} />,
    rerank: <SectionSemanticRouting t={t} settings={settings} onChange={setSettings} />,
    'semantic-routing': <SectionSemanticRouting t={t} settings={settings} onChange={setSettings} />,
    sampling: <SectionChat t={t} settings={settings} onChange={setSettings} isDirty={isDirty} />,
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
    'citation-styles': <CslStylesSection />,
    experimental: <SectionExperimental t={t} />,
    logs: (
      <React.Suspense fallback={<Loader2 size={16} className="animate-spin text-foreground/40" />}>
        <LogsViewerSectionLazy />
      </React.Suspense>
    ),
  };

  return (
    <div className="flex h-full min-w-0 flex-col lg:flex-row">
      {/* -------- Left sidebar: tabs -------- */}
      <div className="flex shrink-0 flex-col border-b border-outline-variant bg-surface-lowest p-3 lg:w-52 lg:border-b-0 lg:border-r lg:p-4">
        <h2 className="mb-1 px-2 font-display text-base font-semibold text-foreground lg:text-lg">{t('settings.title')}</h2>
        <p className="mb-3 hidden px-2 font-label text-[10px] leading-relaxed text-foreground/40 lg:block">{t('settings.description')}</p>

        <nav className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1 lg:mx-0 lg:block lg:flex-1 lg:space-y-0.5 lg:overflow-visible lg:px-0 lg:pb-0">
          {SETTINGS_NAV_TABS.map(tab => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setSettingsSection(tab.id)}
              className={cn(
                'flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 font-label text-xs transition-all lg:w-full',
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
      <form autoComplete="off" onSubmit={e => e.preventDefault()} className="min-w-0 flex-1 overflow-y-auto p-4 custom-scrollbar lg:p-8">
        <motion.div
          key={activeSection}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.15 }}
          className={cn(
            'space-y-6',
            activeSection === 'credentials' ? 'max-w-5xl' : 'max-w-2xl',
          )}
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
      <div className="hidden w-56 flex-shrink-0 flex-col border-l border-outline-variant bg-surface-lowest p-4 xl:flex">
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
