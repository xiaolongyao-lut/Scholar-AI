import { useState } from 'react';
import type { ReactNode } from 'react';
import { AlertCircle, Check, CheckCircle2, Eye, EyeOff, Loader2, Play } from 'lucide-react';
import { cn } from '@/lib/utils';
import { ModelComboInput } from '@/components/settings/ModelComboInput';
import type { DiscoveredModel } from '@/services/chatApi';

export interface ApiEndpointFormValue {
  provider: string;
  baseUrl: string;
  apiKey: string;
  model: string;
}

type ProbeStatus = 'idle' | 'testing' | 'ok' | 'fail';
type DiscoverStatus = 'idle' | 'loading' | 'ok' | 'fail';
type SaveStatus = 'idle' | 'saving' | 'saved' | 'fail';

export interface ApiEndpointFormProps {
  idPrefix: string;
  value: ApiEndpointFormValue;
  onChange: (next: ApiEndpointFormValue) => void;
  providerLabel: string;
  apiKeyLabel: string;
  modelLabel: string;
  baseUrlLabel: string;
  providerPlaceholder?: string;
  apiKeyPlaceholder?: string;
  modelPlaceholder?: string;
  baseUrlPlaceholder?: string;
  apiKeyTooltip?: string;
  modelTooltip?: string;
  baseUrlTooltip?: string;
  savedKeyMasked?: string;
  updatedAt?: string;
  models: DiscoveredModel[];
  onDiscover: () => Promise<void> | void;
  discoverStatus: DiscoverStatus;
  discoverError?: string;
  onTest?: () => Promise<void> | void;
  testStatus?: ProbeStatus;
  testError?: string;
  testElapsedSeconds?: number;
  testTimeoutSeconds?: number;
  onSave?: () => Promise<void> | void;
  saveStatus?: SaveStatus;
  saveError?: string;
  saveLabel?: string;
  clearButton?: ReactNode;
  manualEntryHint?: string;
  className?: string;
  disabled?: boolean;
}

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="font-label text-xs font-medium text-foreground/70">
        {label}
      </label>
      {children}
      {hint ? <p className="text-[10px] leading-relaxed text-foreground/40">{hint}</p> : null}
    </div>
  );
}

export function ApiEndpointForm({
  idPrefix,
  value,
  onChange,
  providerLabel,
  apiKeyLabel,
  modelLabel,
  baseUrlLabel,
  providerPlaceholder,
  apiKeyPlaceholder,
  modelPlaceholder,
  baseUrlPlaceholder,
  apiKeyTooltip,
  modelTooltip,
  baseUrlTooltip,
  savedKeyMasked,
  updatedAt,
  models,
  onDiscover,
  discoverStatus,
  discoverError,
  onTest,
  testStatus = 'idle',
  testError = '',
  testElapsedSeconds = 0,
  testTimeoutSeconds = 60,
  onSave,
  saveStatus = 'idle',
  saveError = '',
  saveLabel = '保存配置',
  clearButton,
  manualEntryHint = '可选择已保存配置，也可手动填写任意兼容服务、服务地址和模型名称。',
  className,
  disabled = false,
}: ApiEndpointFormProps) {
  const [showKey, setShowKey] = useState(false);

  const patch = (next: Partial<ApiEndpointFormValue>) => {
    onChange({ ...value, ...next });
  };

  const testLabel =
    testStatus === 'testing' ? `测试中 ${testElapsedSeconds}s / ${testTimeoutSeconds}s` :
      testStatus === 'ok' ? '通过' :
        testStatus === 'fail' ? '失败' :
          '测试连接';

  const saveButtonLabel =
    saveStatus === 'saving' ? '保存中…' :
      saveStatus === 'saved' ? '已保存' :
        saveLabel;

  return (
    <div className={cn('space-y-4', className)}>
      <p className="rounded-lg border border-outline-variant/45 bg-surface-high px-3 py-2 text-[11px] leading-relaxed text-foreground/55">
        {manualEntryHint}
      </p>

      {testStatus === 'fail' && testError ? (
        <div className="flex min-w-0 items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-700/40 dark:bg-red-500/15">
          <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-500" />
          <p className="min-w-0 flex-1 break-all text-[11px] leading-relaxed text-red-700 dark:text-red-300">{testError}</p>
        </div>
      ) : null}

      <div className="grid gap-3 md:grid-cols-2">
        <Field label={providerLabel} htmlFor={`${idPrefix}-provider`}>
          <input
            id={`${idPrefix}-provider`}
            type="text"
            value={value.provider}
            onChange={(event) => patch({ provider: event.target.value })}
            placeholder={providerPlaceholder}
            disabled={disabled}
            className="w-full rounded-lg border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground transition-colors focus:border-primary/40 focus:outline-none disabled:opacity-60"
          />
        </Field>

        <Field label={apiKeyLabel} htmlFor={`${idPrefix}-api-key`} hint={apiKeyTooltip}>
          <div className="flex items-center gap-2">
            <input
              id={`${idPrefix}-api-key`}
              type={showKey ? 'text' : 'password'}
              value={value.apiKey}
              onChange={(event) => patch({ apiKey: event.target.value })}
              placeholder={savedKeyMasked ? `当前已存（${savedKeyMasked}），留空保留` : apiKeyPlaceholder}
              autoComplete="off"
              data-lpignore="true"
              data-form-type="other"
              disabled={disabled}
              className="min-w-0 flex-1 rounded-lg border border-outline-variant/50 bg-surface-high px-3 py-2 font-mono text-sm text-foreground transition-colors focus:border-primary/40 focus:outline-none disabled:opacity-60"
            />
            <button
              type="button"
              onClick={() => setShowKey((current) => !current)}
              className="rounded-md p-2 text-foreground/35 transition-colors hover:bg-surface-high hover:text-foreground"
              aria-label={showKey ? '隐藏访问密钥' : '显示访问密钥'}
              title={showKey ? '隐藏' : '显示'}
            >
              {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </Field>

        <Field label={modelLabel} htmlFor={`${idPrefix}-model`} hint={modelTooltip}>
          <ModelComboInput
            id={`${idPrefix}-model`}
            value={value.model}
            onChange={(next) => patch({ model: next })}
            models={models}
            onDiscover={async () => { await onDiscover(); }}
            discoverStatus={discoverStatus}
            discoverError={discoverError}
            placeholder={modelPlaceholder}
            ariaLabel={modelLabel}
          />
        </Field>

        <Field label={baseUrlLabel} htmlFor={`${idPrefix}-base-url`} hint={baseUrlTooltip}>
          <input
            id={`${idPrefix}-base-url`}
            type="text"
            value={value.baseUrl}
            onChange={(event) => patch({ baseUrl: event.target.value })}
            placeholder={baseUrlPlaceholder}
            disabled={disabled}
            className="w-full rounded-lg border border-outline-variant/50 bg-surface-high px-3 py-2 font-mono text-xs text-foreground transition-colors focus:border-primary/40 focus:outline-none disabled:opacity-60"
          />
        </Field>
      </div>

      {updatedAt ? (
        <p className="font-mono text-[10px] text-foreground/40">最后更新：{updatedAt}</p>
      ) : null}

      {(onTest || onSave || clearButton) ? (
        <div className="flex flex-wrap items-center gap-2">
          {onTest ? (
            <button
              type="button"
              onClick={() => void onTest()}
              disabled={testStatus === 'testing' || disabled}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-colors disabled:opacity-50',
                testStatus === 'ok' ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300' :
                  testStatus === 'fail' ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300' :
                    testStatus === 'testing' ? 'border-primary/20 bg-primary/5 text-primary' :
                      'border-outline-variant bg-surface-high text-foreground/65 hover:border-primary/35 hover:text-primary',
              )}
            >
              {testStatus === 'testing' ? <Loader2 size={14} className="animate-spin" /> :
                testStatus === 'ok' ? <CheckCircle2 size={14} /> :
                  <Play size={14} />}
              {testLabel}
            </button>
          ) : null}
          {onSave ? (
            <button
              type="button"
              onClick={() => void onSave()}
              disabled={saveStatus === 'saving' || disabled}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg border px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50',
                saveStatus === 'saved' ? 'border-emerald-600 bg-emerald-600 text-white' :
                  saveStatus === 'fail' ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300' :
                    'border-primary bg-primary text-primary-foreground hover:bg-primary/90',
              )}
            >
              {saveStatus === 'saving' ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              {saveButtonLabel}
            </button>
          ) : null}
          {clearButton}
        </div>
      ) : null}

      {saveStatus === 'fail' && saveError ? (
        <p className="text-xs text-red-700 dark:text-red-300">{saveError}</p>
      ) : null}
    </div>
  );
}
