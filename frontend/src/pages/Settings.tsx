import React, { useState, useEffect, useCallback } from 'react';
import {
  Settings as SettingsIcon, Key, Cpu, Network, FolderOpen, Layers,
  Activity, Check, Eye, EyeOff, ChevronRight, Info, Zap,
  Loader2, RefreshCw, AlertCircle, AlertTriangle, CheckCircle2, XCircle, Play,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import axios from 'axios';
import { loadSettings, saveSettings, type AppSettings } from '@/services/settingsStore';
import { getApiBaseUrl } from '@/services/apiBaseUrl';
import { testChatConnectionWithConfig } from '@/services/chatApi';
import { getSampling, putSampling, deleteSamplingTask, type SamplingParams, type TaskDefaults } from '@/services/samplingApi';
import { buildSamplingSaveRequest, hasSamplingOverrides, updateSamplingOverrides } from '@/services/samplingPayload';

const SkillManagerLazy = React.lazy(() => import('@/components/skills/SkillManager'));

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
type SectionId = 'chat' | 'embedding' | 'workspace' | 'sampling' | 'skills';

const SECTION_IDS: readonly SectionId[] = ['chat', 'embedding', 'workspace', 'sampling', 'skills'];

function isSectionId(value: string | null): value is SectionId {
  return typeof value === 'string' && (SECTION_IDS as readonly string[]).includes(value);
}

function getInitialSection(): SectionId {
  if (typeof window === 'undefined') {
    return 'chat';
  }

  const section = new URLSearchParams(window.location.search).get('section');
  return isSectionId(section) ? section : 'chat';
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
  online: 'text-emerald-600 bg-emerald-50',
  ready: 'text-emerald-600 bg-emerald-50',
  loaded: 'text-blue-600 bg-blue-50',
  offline: 'text-foreground/40 bg-surface-high',
  missing: 'text-red-600 bg-red-50',
};

const healthDot: Record<string, string> = {
  online: 'bg-emerald-500',
  ready: 'bg-emerald-500',
  loaded: 'bg-blue-500',
  offline: 'bg-foreground/20',
  missing: 'bg-red-500',
};

/* ------------------------------------------------------------------ */
/*  Small helpers                                                      */
/* ------------------------------------------------------------------ */
function Tooltip({ text }: { text: string }) {
  return (
    <span className="relative group/tip ml-1 cursor-help">
      <Info size={12} className="text-foreground/25 group-hover/tip:text-foreground/50 transition-colors" />
      <span className="absolute left-1/2 -translate-x-1/2 bottom-full mb-1.5 px-2.5 py-1.5 text-[10px] font-label text-foreground bg-surface-highest border border-outline-variant rounded-md shadow-lg whitespace-nowrap opacity-0 pointer-events-none group-hover/tip:opacity-100 transition-opacity z-50 max-w-xs text-wrap">
        {text}
      </span>
    </span>
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
      aria-label={ariaLabel ?? placeholder ?? 'Text input'}
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
      aria-label={ariaLabel ?? 'Select option'}
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
        aria-label={ariaLabel ?? 'Range input'}
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
      aria-label={ariaLabel ?? 'Toggle setting'}
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
function SectionChat({ t, settings, onChange, isDirty }: { t: (k: string, p?: Record<string, string | number>) => string; settings: AppSettings; onChange: (s: AppSettings) => void; isDirty: boolean }) {
  const [showKey, setShowKey] = useState(false);
  const llm = settings.llm;
  const setLlm = (patch: Partial<typeof llm>) => onChange({ ...settings, llm: { ...llm, ...patch } });
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testError, setTestError] = useState('');
  const [testHint, setTestHint] = useState('');

  // Model catalog from backend
  interface CatalogModel { id: string; name: string; provider: string; default_base_url: string; context_window: number; description: string }
  interface CatalogProvider { provider: string; display_name: string; default_base_url: string; auth_tip: string; models: CatalogModel[] }
  const [catalog, setCatalog] = useState<CatalogProvider[]>([]);

  useEffect(() => {
    axios.get(`${getApiBaseUrl()}/chat/providers`, { timeout: 5000 })
      .then(res => setCatalog(res.data))
      .catch(() => {});
  }, []);

  // Find current provider from catalog
  const currentProvider = catalog.find(p => p.provider === llm.provider);
  const providerModels = currentProvider?.models ?? [];
  const authTip = currentProvider?.auth_tip ?? '';

  // When provider changes, auto-fill base_url and first model
  const handleProviderChange = (provider: string) => {
    const prov = catalog.find(p => p.provider === provider);
    if (prov) {
      const firstModel = prov.models[0];
      setLlm({
        provider,
        baseUrl: prov.default_base_url,
        model: firstModel?.id ?? '',
      });
    } else {
      setLlm({ provider });
    }
  };

  // When model changes, update description context
  const handleModelChange = (modelId: string) => {
    setLlm({ model: modelId });
  };

  // Provider list: use catalog if loaded, otherwise fallback
  const providerOptions = catalog.length > 0
    ? catalog.map(p => ({ value: p.provider, label: p.display_name }))
    : ['DeepSeek', 'OpenAI', 'Claude', 'Gemini', 'Local LLM'].map(p => ({ value: p, label: p }));

  const selectedModel = providerModels.find(m => m.id === llm.model);

  const handleTestConnection = async () => {
    setTestStatus('testing');
    setTestError('');
    setTestHint('');
    try {
      await testChatConnectionWithConfig(llm);
      if (isDirty) {
        saveSettings(settings);
      }
      setTestStatus('ok');
      if (isDirty) {
        setTestHint('测试配置已自动保存；问答页将使用同一套配置。');
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
    setTimeout(() => setTestStatus('idle'), 6000);
  };

  const testIcon = testStatus === 'testing' ? <Loader2 size={14} className="animate-spin" />
    : testStatus === 'ok' ? <CheckCircle2 size={14} className="text-emerald-500" />
    : testStatus === 'fail' ? <AlertTriangle size={15} className="text-red-500 flex-shrink-0" />
    : <Play size={14} />;

  const testLabel = testStatus === 'testing' ? t('settings.testing')
    : testStatus === 'ok' ? t('settings.test_success')
    : testStatus === 'fail' ? t('settings.test_fail')
    : t('settings.test_connection');

  return (
    <section id="section-chat" className="space-y-5">
      <div className="flex items-center justify-between">
        <h3 className="font-headline text-sm font-semibold text-foreground flex items-center gap-2">
          <Zap size={16} className="text-primary" />
          {t('settings.section_chat')}
          <Tooltip text={t('settings.section_chat_tooltip')} />
        </h3>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleTestConnection}
            disabled={testStatus === 'testing'}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-label text-xs font-medium leading-none transition-all border',
              testStatus === 'ok' ? 'bg-emerald-50 border-emerald-200 text-emerald-700' :
              testStatus === 'fail' ? 'bg-red-50 border-red-200 text-red-700' :
              testStatus === 'testing' ? 'bg-primary/5 border-primary/20 text-primary' :
              'bg-surface-high border-outline-variant text-foreground/60 hover:border-primary/30 hover:text-primary',
            )}
          >
            {testIcon}
            {testLabel}
          </button>
          <StatusPill status={testStatus === 'ok' ? 'online' : testStatus === 'fail' ? 'offline' : 'ready'} t={t} />
        </div>
      </div>
      {testStatus === 'fail' && testError && (
        <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg min-w-0">
          <AlertCircle size={16} className="text-red-500 flex-shrink-0 mt-0.5" />
          <p className="font-body text-[11px] text-red-700 leading-relaxed break-all whitespace-normal flex-1 min-w-0">{t('settings.test_fail_detail', { provider: llm.provider, error: testError })}</p>
        </div>
      )}
      {testStatus === 'ok' && testHint && (
        <div className="flex items-start gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg min-w-0">
          <AlertTriangle size={16} className="text-amber-600 flex-shrink-0 mt-0.5" />
          <p className="font-body text-[11px] text-amber-800 leading-relaxed break-all whitespace-normal flex-1 min-w-0">{testHint}</p>
        </div>
      )}
      <div className="grid grid-cols-2 gap-4">
        <Field label={t('settings.provider')} htmlFor="chat-provider">
          <select
            id="chat-provider"
            value={llm.provider}
            onChange={e => handleProviderChange(e.target.value)}
            aria-label={t('settings.provider')}
            className="w-full bg-surface-high rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-label text-foreground focus:outline-none focus:border-primary/40 transition-colors"
          >
            {providerOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          {authTip && (
            <p className="text-[10px] text-foreground/40 mt-1 leading-relaxed">{authTip}</p>
          )}
        </Field>
        <Field label={t('settings.api_key')} tooltip={t('settings.api_key_tooltip')} htmlFor="chat-api-key">
          <div className="flex items-center gap-2">
            <input id="chat-api-key" type={showKey ? 'text' : 'password'} value={llm.apiKey} onChange={e => setLlm({ apiKey: e.target.value })}
              placeholder="sk-***************" autoComplete="off" data-lpignore="true" data-form-type="other"
              aria-label={t('settings.api_key')}
              className="flex-1 bg-surface-high rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-mono text-foreground focus:outline-none focus:border-primary/40 transition-colors" />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              aria-label={showKey ? t('settings.hide') : t('settings.show')}
              title={showKey ? t('settings.hide') : t('settings.show')}
              className="p-2 text-foreground/30 hover:text-foreground transition-colors"
            >
              {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </Field>
        <Field
          label={t('settings.chat_model')}
          tooltip={t('settings.chat_model_tooltip')}
          htmlFor={providerModels.length > 0 ? 'chat-model-select' : 'chat-model-input'}
        >
          {providerModels.length > 0 ? (
            <div>
              <select
                id="chat-model-select"
                value={llm.model}
                onChange={e => handleModelChange(e.target.value)}
                aria-label={t('settings.chat_model')}
                className="w-full bg-surface-high rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-label text-foreground focus:outline-none focus:border-primary/40 transition-colors"
              >
                {providerModels.map(m => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
              {selectedModel && (
                <p className="text-[10px] text-foreground/40 mt-1">
                  {selectedModel.description}
                  {selectedModel.context_window > 0 && ` · 上下文窗口: ${(selectedModel.context_window / 1000).toFixed(0)}K`}
                </p>
              )}
            </div>
          ) : (
            <input id="chat-model-input" type="text" value={llm.model} onChange={e => setLlm({ model: e.target.value })}
              placeholder="model-id"
              aria-label={t('settings.chat_model')}
              className="w-full bg-surface-high rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-mono text-foreground focus:outline-none focus:border-primary/40 transition-colors" />
          )}
        </Field>
        <Field label={t('settings.base_url')} tooltip={t('settings.base_url_tooltip')} htmlFor="chat-base-url">
          <input id="chat-base-url" type="text" value={llm.baseUrl} onChange={e => setLlm({ baseUrl: e.target.value })}
            aria-label={t('settings.base_url')}
            className="w-full bg-surface-high rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-mono text-xs text-foreground focus:outline-none focus:border-primary/40 transition-colors" />
        </Field>
      </div>
      <div className="grid grid-cols-3 gap-4">
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

function SectionEmbedding({ t, settings, onChange }: { t: (k: string, p?: Record<string, string | number>) => string; settings: AppSettings; onChange: (s: AppSettings) => void }) {
  const [showKey, setShowKey] = useState(false);
  const emb = settings.embedding;
  const setEmb = (patch: Partial<typeof emb>) => onChange({ ...settings, embedding: { ...emb, ...patch } });
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testError, setTestError] = useState('');

  const handleTestConnection = async () => {
    setTestStatus('testing');
    setTestError('');
    try {
      const url = `${emb.baseUrl}/embeddings`;
      await axios.post(url, {
        input: 'test',
        model: emb.model,
      }, {
        timeout: 15000,
        headers: { 'Authorization': `Bearer ${emb.apiKey}`, 'Content-Type': 'application/json' },
      });
      setTestStatus('ok');
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response) {
        if (err.response.status === 401) {
          setTestStatus('fail');
          setTestError('访问密钥无效或过期');
        } else if (err.response.status < 500) {
          setTestStatus('ok');
        } else {
          setTestStatus('fail');
          setTestError(`服务器错误: ${err.response.status}`);
        }
      } else {
        const msg = err instanceof Error ? err.message : String(err);
        setTestStatus('fail');
        setTestError(msg);
      }
    }
    setTimeout(() => { if (testStatus !== 'idle') setTestStatus('idle'); }, 6000);
  };

  const testIcon = testStatus === 'testing' ? <Loader2 size={14} className="animate-spin" />
    : testStatus === 'ok' ? <CheckCircle2 size={14} className="text-emerald-500" />
    : testStatus === 'fail' ? <AlertTriangle size={15} className="text-red-500 flex-shrink-0" />
    : <Play size={14} />;

  const testLabel = testStatus === 'testing' ? t('settings.testing')
    : testStatus === 'ok' ? t('settings.test_success')
    : testStatus === 'fail' ? t('settings.test_fail')
    : t('settings.test_connection');

  return (
    <section id="section-embedding" className="space-y-5">
      <div className="flex items-center justify-between">
        <h3 className="font-headline text-sm font-semibold text-foreground flex items-center gap-2">
          <Network size={16} className="text-primary" />
          {t('settings.section_embedding')}
          <Tooltip text={t('settings.section_embedding_tooltip')} />
        </h3>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleTestConnection}
            disabled={testStatus === 'testing'}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-label text-xs font-medium leading-none transition-all border',
              testStatus === 'ok' ? 'bg-emerald-50 border-emerald-200 text-emerald-700' :
              testStatus === 'fail' ? 'bg-red-50 border-red-200 text-red-700' :
              testStatus === 'testing' ? 'bg-primary/5 border-primary/20 text-primary' :
              'bg-surface-high border-outline-variant text-foreground/60 hover:border-primary/30 hover:text-primary',
            )}
          >
            {testIcon}
            {testLabel}
          </button>
          <StatusPill status={testStatus === 'ok' ? 'online' : testStatus === 'fail' ? 'offline' : 'ready'} t={t} />
        </div>
      </div>
      {testStatus === 'fail' && testError && (
        <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg min-w-0">
          <AlertCircle size={16} className="text-red-500 flex-shrink-0 mt-0.5" />
          <p className="font-body text-[11px] text-red-700 leading-relaxed break-all whitespace-normal flex-1 min-w-0">{t('settings.test_fail_detail', { provider: emb.provider, error: testError })}</p>
        </div>
      )}
      <div className="grid grid-cols-2 gap-4">
        <Field label={t('settings.embedding_provider')} htmlFor="embedding-provider">
          <select
            id="embedding-provider"
            value={emb.provider}
            onChange={e => setEmb({ provider: e.target.value })}
            aria-label={t('settings.embedding_provider')}
            className="w-full bg-surface-high rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-label text-foreground focus:outline-none focus:border-primary/40 transition-colors"
          >
            {['OpenAI', 'Gemini', 'Jina', 'Cohere', 'Local'].map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        </Field>
        <Field label={t('settings.embedding_api_key')} tooltip={t('settings.embedding_api_key_tooltip')} htmlFor="embedding-api-key">
          <div className="flex items-center gap-2">
            <input id="embedding-api-key" type={showKey ? 'text' : 'password'} value={emb.apiKey} onChange={e => setEmb({ apiKey: e.target.value })}
              placeholder="sk-emb-***************" autoComplete="off" data-lpignore="true" data-form-type="other"
              aria-label={t('settings.embedding_api_key')}
              className="flex-1 bg-surface-high rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-mono text-foreground focus:outline-none focus:border-primary/40 transition-colors" />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              aria-label={showKey ? t('settings.hide') : t('settings.show')}
              title={showKey ? t('settings.hide') : t('settings.show')}
              className="p-2 text-foreground/30 hover:text-foreground transition-colors"
            >
              {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </Field>
        <Field label={t('settings.embedding_model')} tooltip={t('settings.embedding_model_tooltip')} htmlFor="embedding-model">
          <input id="embedding-model" type="text" value={emb.model} onChange={e => setEmb({ model: e.target.value })}
            aria-label={t('settings.embedding_model')}
            className="w-full bg-surface-high rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-mono text-foreground focus:outline-none focus:border-primary/40 transition-colors" />
        </Field>
        <Field label={t('settings.embedding_base_url')} htmlFor="embedding-base-url">
          <input id="embedding-base-url" type="text" value={emb.baseUrl} onChange={e => setEmb({ baseUrl: e.target.value })}
            aria-label={t('settings.embedding_base_url')}
            className="w-full bg-surface-high rounded-lg px-3 py-2 border border-outline-variant/50 text-sm font-mono text-xs text-foreground focus:outline-none focus:border-primary/40 transition-colors" />
        </Field>
      </div>
    </section>
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

function SectionSampling({ t }: { t: (k: string, p?: Record<string, string | number>) => string }) {
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
    try {
      const data = await getSampling();
      setTaskDefaults(data.task_defaults);
      setModelMaxTokens(data.model_max_tokens);
      setUserOverrides(data.tasks || {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
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
      setTimeout(() => setSaveStatus(prev => ({ ...prev, [task]: 'idle' })), 2000);
    } catch (err) {
      let msg = err instanceof Error ? err.message : String(err);
      if (axios.isAxiosError(err) && err.response?.status === 422) {
        const detail = err.response.data?.detail;
        msg = typeof detail === 'string' ? detail : JSON.stringify(detail);
      }
      setSaveStatus(prev => ({ ...prev, [task]: 'error' }));
      setSaveError(prev => ({ ...prev, [task]: msg }));
      setTimeout(() => setSaveStatus(prev => ({ ...prev, [task]: 'idle' })), 4000);
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
        <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg">
          <AlertCircle size={16} className="text-red-500 flex-shrink-0 mt-0.5" />
          <p className="font-body text-xs text-red-700">{error}</p>
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
          const defaults = taskDefaults[task.id];
          const overrides = userOverrides[task.id];
          const hasOverrides = hasSamplingOverrides(overrides);
          const status = saveStatus[task.id] || 'idle';
          const errMsg = saveError[task.id];

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
                    <div className="flex items-start gap-2 p-2.5 bg-red-50 border border-red-200 rounded-md">
                      <AlertCircle size={14} className="text-red-500 flex-shrink-0 mt-0.5" />
                      <p className="font-body text-[11px] text-red-700 leading-relaxed">{errMsg}</p>
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
                        status === 'saved' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' :
                        status === 'error' ? 'bg-red-50 text-red-700 border border-red-200' :
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
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */
const TABS: { id: SectionId; icon: React.ElementType; labelKey: string }[] = [
  { id: 'chat', icon: Zap, labelKey: 'settings.section_chat' },
  { id: 'embedding', icon: Network, labelKey: 'settings.section_embedding' },
  { id: 'sampling', icon: Cpu, labelKey: 'settings.section_sampling' },
  { id: 'workspace', icon: FolderOpen, labelKey: 'settings.section_workspace' },
  { id: 'skills', icon: Layers, labelKey: 'skills.settings_section' },
];

export function SettingsPage() {
  const { t } = useI18n();
  const [activeSection, setActiveSection] = useState<SectionId>(getInitialSection);
  const [healthEntries, setHealthEntries] = useState<HealthEntry[]>(HEALTH_ENTRIES);
  const [healthLoading, setHealthLoading] = useState(false);
  const [lastCheck, setLastCheck] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [settings, setSettings] = useState<AppSettings>(loadSettings);
  const isDirty = JSON.stringify(settings) !== JSON.stringify(loadSettings());

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const section = new URLSearchParams(window.location.search).get('section');
    if (isSectionId(section)) {
      setActiveSection(section);
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
    setTimeout(() => {
      setSaving(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    }, 200);
  };

  const sectionMap: Record<SectionId, React.ReactNode> = {
    chat: <SectionChat t={t} settings={settings} onChange={setSettings} isDirty={isDirty} />,
    embedding: <SectionEmbedding t={t} settings={settings} onChange={setSettings} />,
    sampling: <SectionSampling t={t} />,
    workspace: <SectionWorkspace t={t} settings={settings} onChange={setSettings} />,
    skills: <SkillManagerLazy />,
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

          <div className="flex justify-end pt-2">
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg font-label text-sm font-medium shadow-sm hover:bg-primary/90 disabled:opacity-60 transition-all"
            >
              {saving ? <Loader2 size={16} className="animate-spin" /> : saved ? <Check size={16} /> : <Check size={16} />}
              {saved ? t('settings.saved') : t('settings.save_changes')}
            </button>
          </div>
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
