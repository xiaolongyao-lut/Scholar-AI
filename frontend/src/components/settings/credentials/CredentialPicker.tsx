/**
 * Shared credential picker for MCP installer wizard and Skill manager
 * (S4b / plan 2026-05-20 §B4 + Decision #8).
 *
 * Lists enabled RuntimeCredentials and lets the user pick one to bind
 * to a target env. Provider hints from the requirement highlight
 * matching credentials. v1 does NOT inline-create — instead it offers
 * a "去凭证管理新建" link that calls `onJumpToCreate` so the parent
 * can save wizard state and navigate to /settings credentials.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Check, AlertTriangle, ExternalLink, Loader2, RefreshCw } from 'lucide-react';
import {
  listCredentials,
  type RuntimeCredentialPublic,
} from '@/services/credentialsApi';

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
  const { requirement, value, onChange, onJumpToCreate, disabled } = props;
  const [state, setState] = useState<InternalState>({
    loading: true,
    error: null,
    credentials: [],
  });

  const fetchCreds = async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const list = await listCredentials({ enabledOnly: true });
      setState({ loading: false, error: null, credentials: list });
    } catch (exc) {
      setState({
        loading: false,
        error: exc instanceof Error ? exc.message : String(exc),
        credentials: [],
      });
    }
  };

  useEffect(() => {
    void fetchCreds();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const selectedCred = state.credentials.find((c) => c.credential_id === value);
  const hintMismatch = selectedCred &&
    requirement.provider_hints.length > 0 &&
    !requirement.provider_hints.some(
      (h) => h.toLowerCase() === selectedCred.provider.toLowerCase(),
    );

  return (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <label className="font-label text-[11px] text-foreground/70 font-medium block">
            {requirement.label}
            {requirement.required && (
              <span className="text-red-500 ml-0.5" aria-label="必填">*</span>
            )}
          </label>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="font-mono text-[10px] text-foreground/40">
              env={requirement.env}
            </span>
            {requirement.provider_hints.length > 0 && (
              <span className="font-mono text-[10px] text-foreground/40">
                hint: {requirement.provider_hints.join(', ')}
              </span>
            )}
          </div>
          {requirement.description && (
            <p className="mt-1 font-label text-[10px] text-foreground/55">
              {requirement.description}
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
          凭证加载失败: {state.error}
        </div>
      )}

      {!state.loading && state.credentials.length === 0 ? (
        <div className="rounded-md border border-dashed border-outline-variant p-3 text-center">
          <p className="font-label text-[11px] text-foreground/55 mb-2">
            还没有可用凭证。请先到凭证管理添加一个,再回到这里完成绑定。
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
              title="匹配 provider"
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
            所选凭证 provider「{selectedCred?.provider}」不在推荐列表(
            {requirement.provider_hints.join(', ')})内。继续将以非匹配方式绑定,
            部分实现可能不支持。
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
                    <span className="font-mono text-[11px] text-foreground font-medium">
                      {c.provider}
                    </span>
                    <span className="font-mono text-[10px] text-foreground/55 truncate">
                      {c.model}
                    </span>
                    {highlight && (
                      <span className="font-label text-[9px] text-emerald-600 dark:text-emerald-300 uppercase">
                        match
                      </span>
                    )}
                  </div>
                  <p className="font-mono text-[10px] text-foreground/40 truncate mt-0.5">
                    {c.base_url} · key={c.api_key_masked}
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

export default CredentialPicker;
