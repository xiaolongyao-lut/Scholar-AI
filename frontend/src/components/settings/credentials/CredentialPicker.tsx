/**
 * Shared credential picker for MCP installer wizard and Skill manager.
 *
 * Lists enabled RuntimeCredentials and lets the user pick one to bind
 * to a required sensitive setting. Provider hints from the requirement
 * highlight matching credentials. v1 does NOT inline-create — instead it offers
 * a "去凭证管理新建" link that calls `onJumpToCreate` so the parent
 * can save wizard state and navigate to /settings credentials.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Check, AlertTriangle, ExternalLink, Loader2, RefreshCw } from 'lucide-react';
import {
  type CredentialCategory,
  listCredentials,
  type RuntimeCredentialPublic,
} from '@/services/credentialsApi';
import {
  formatDynamicCredentialLabel,
  formatDynamicDescription,
} from '@/components/settings/dynamicConfigDisplay';

const INTERNAL_VISIBLE_PATTERN =
  /(?:\/api\/|https?:\/\/|[A-Za-z]:\\|[A-Z][A-Z0-9]+_[A-Z0-9_]+|(?:env|credential|provider|server|api|base|token|secret)_[a-z0-9_]+|api[_-]?key|base[_-]?url|authorization|bearer|token|secret|env=|env_refs|[{}[\]"`])/i;

export interface CredentialPickerRequirement {
  id: string;
  label: string;
  env: string;
  kind: 'api_key';
  provider_hints: string[];
  required: boolean;
  description?: string;
}

export interface CredentialPickerProps {
  requirement: CredentialPickerRequirement;
  value: string | null;
  onChange: (credentialId: string | null) => void;
  category?: CredentialCategory;
  /** Called when the user clicks "去凭证管理新建". Parent saves wizard
   *  state and navigates. Picker has no router knowledge. */
  onJumpToCreate?: () => void;
  disabled?: boolean;
}

interface InternalState {
  loading: boolean;
  error: string | null;
  credentials: RuntimeCredentialPublic[];
}

export function CredentialPicker(props: CredentialPickerProps): JSX.Element {
  const { requirement, value, onChange, category, onJumpToCreate, disabled } = props;
  const [state, setState] = useState<InternalState>({
    loading: true,
    error: null,
    credentials: [],
  });

  const fetchCreds = async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const list = await listCredentials({ category, enabledOnly: true });
      setState({ loading: false, error: null, credentials: list });
    } catch (exc) {
      setState({
        loading: false,
        error: formatCredentialPickerError(exc),
        credentials: [],
      });
    }
  };

  useEffect(() => {
    void fetchCreds();
  }, []);

  const { matches, others } = useMemo(() => {
    const hints = new Set(requirement.provider_hints.map((h) => h.toLowerCase()));
    const m: RuntimeCredentialPublic[] = [];
    const o: RuntimeCredentialPublic[] = [];
    for (const c of state.credentials) {
      if (hints.has(c.provider.toLowerCase())) m.push(c);
      else o.push(c);
    }
    return { matches: m, others: o };
  }, [state.credentials, requirement.provider_hints]);

  const safeProviderHints = useMemo(
    () => sanitizeProviderHints(requirement.provider_hints),
    [requirement.provider_hints],
  );
  const safeRequirementLabel = useMemo(
    () => formatDynamicCredentialLabel(requirement.label),
    [requirement.label],
  );
  const safeRequirementDescription = useMemo(
    () => formatDynamicDescription(requirement.description),
    [requirement.description],
  );
  const selectedCred = state.credentials.find((c) => c.credential_id === value);
  const hintMismatch = selectedCred &&
    safeProviderHints.length > 0 &&
    !requirement.provider_hints.some(
      (h) => h.toLowerCase() === selectedCred.provider.toLowerCase(),
    );

  return (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <label className="font-label text-[11px] text-foreground/70 font-medium block">
            {safeRequirementLabel}
            {requirement.required && (
              <span className="text-red-500 ml-0.5" aria-label="必填">*</span>
            )}
          </label>
          {safeProviderHints.length > 0 && (
            <div className="mt-0.5 text-[10px] text-foreground/45">
              推荐服务：{safeProviderHints.join('、')}
            </div>
          )}
          {safeRequirementDescription && (
            <p className="mt-1 font-label text-[10px] text-foreground/55">
              {safeRequirementDescription}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => void fetchCreds()}
          disabled={disabled || state.loading}
          title="重新加载凭证列表"
          aria-label="重新加载凭证列表"
          className="p-1.5 rounded text-foreground/55 hover:text-foreground hover:bg-surface-high disabled:opacity-50"
        >
          {state.loading ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <RefreshCw size={12} />
          )}
        </button>
      </div>

      {state.error && (
        <div className="text-[11px] text-red-500 font-label">
          {state.error}
        </div>
      )}

      {!state.loading && state.credentials.length === 0 ? (
        <div className="rounded-md border border-dashed border-outline-variant p-3 text-center">
          <p className="font-label text-[11px] text-foreground/55 mb-2">
            暂无可用凭证。
          </p>
          {onJumpToCreate && (
            <button
              type="button"
              onClick={() => onJumpToCreate()}
              disabled={disabled}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary/10 px-3 py-1.5 font-label text-xs font-medium text-primary hover:bg-primary/15 disabled:opacity-50"
            >
              <ExternalLink size={12} /> 去凭证管理新建
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-1">
          {matches.length > 0 && (
            <CredentialList
              title="推荐匹配"
              credentials={matches}
              value={value}
              onChange={onChange}
              highlight
              disabled={disabled}
            />
          )}
          {others.length > 0 && (
            <CredentialList
              title="其他凭证"
              credentials={others}
              value={value}
              onChange={onChange}
              disabled={disabled}
            />
          )}
          {onJumpToCreate && (
            <button
              type="button"
              onClick={() => onJumpToCreate()}
              disabled={disabled}
              className="inline-flex items-center gap-1.5 mt-1 text-[11px] text-primary hover:underline disabled:opacity-50"
            >
              <ExternalLink size={11} /> 没有合适的?去凭证管理新建
            </button>
          )}
        </div>
      )}

      {hintMismatch && (
        <div className="flex items-start gap-1.5 text-[11px] text-amber-600 dark:text-amber-300 font-label">
          <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
          <span>
            所选凭证「{formatCredentialPrimary(selectedCred)}」不在推荐服务列表（
            {safeProviderHints.join('、')}）内。继续绑定时，部分实现可能不支持。
          </span>
        </div>
      )}
    </div>
  );
}

interface CredentialListProps {
  title: string;
  credentials: RuntimeCredentialPublic[];
  value: string | null;
  onChange: (id: string | null) => void;
  highlight?: boolean;
  disabled?: boolean;
}

function CredentialList(props: CredentialListProps): JSX.Element {
  const { title, credentials, value, onChange, highlight, disabled } = props;
  return (
    <div>
      <p className="font-label text-[10px] text-foreground/40 mb-1 uppercase tracking-wide">
        {title}
      </p>
      <ul className="space-y-1">
        {credentials.map((c) => {
          const active = c.credential_id === value;
          return (
            <li key={c.credential_id}>
              <button
                type="button"
                onClick={() => onChange(active ? null : c.credential_id)}
                disabled={disabled}
                className={[
                  'w-full text-left px-3 py-2 rounded-md border transition-colors',
                  'flex items-center gap-2',
                  active
                    ? 'border-primary bg-primary/5'
                    : highlight
                    ? 'border-emerald-500/30 hover:border-emerald-500/60 bg-emerald-500/5'
                    : 'border-outline-variant hover:border-outline',
                  disabled ? 'opacity-50 cursor-not-allowed' : '',
                ].join(' ')}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-label text-[11px] text-foreground font-medium">
                      {formatCredentialPrimary(c)}
                    </span>
                    <span className="font-label text-[10px] text-foreground/55 truncate">
                      {formatCredentialSecondary(c)}
                    </span>
                    {highlight && (
                      <span className="font-label text-[9px] text-emerald-600 dark:text-emerald-300">
                        匹配
                      </span>
                    )}
                  </div>
                  <p className="font-label text-[10px] text-foreground/40 truncate mt-0.5">
                    调用配置已保存 · {c.has_api_key ? '访问密钥已保存' : '未保存访问密钥'}
                  </p>
                </div>
                {active && <Check size={14} className="text-primary flex-shrink-0" />}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function sanitizeCredentialText(value: unknown, fallback: string): string {
  const raw = typeof value === 'string' ? value.trim() : '';
  if (!raw) return fallback;
  if (INTERNAL_VISIBLE_PATTERN.test(raw)) return fallback;
  return raw;
}

function sanitizeProviderHints(hints: string[]): string[] {
  const labels = hints
    .map((hint) => sanitizeCredentialText(hint, ''))
    .filter((hint): hint is string => hint.length > 0);
  return Array.from(new Set(labels));
}

function formatCredentialPickerError(exc: unknown): string {
  const raw = exc instanceof Error ? exc.message : typeof exc === 'string' ? exc : '';
  return sanitizeCredentialText(raw, '凭证加载失败，请稍后重试。');
}

function formatCredentialPrimary(credential: RuntimeCredentialPublic | undefined): string {
  if (!credential) return '已保存凭证';
  return sanitizeCredentialText(credential.provider, '已保存凭证');
}

function formatCredentialSecondary(credential: RuntimeCredentialPublic): string {
  return sanitizeCredentialText(credential.model, '模型名称未填写');
}

export default CredentialPicker;
