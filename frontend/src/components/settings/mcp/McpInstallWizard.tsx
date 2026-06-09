/** MCP install wizard for scan, config, credential binding, review, and install. */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  Loader2,
  X,
  Zap,
} from 'lucide-react';
import {
  scanLocalMcpPackage,
  installMcpPackage,
  McpInstallApiError,
  type McpInstallationInstallResponse,
  type McpInstallErrorCode,
  type McpPackageScanResult,
} from '@/services/mcpInstallApi';
import CredentialPicker from '@/components/settings/credentials/CredentialPicker';
import {
  clearWizardState,
  defaultWizardState,
  loadWizardState,
  saveWizardState,
  type WizardState,
  type WizardStep,
} from './wizardState';
import { sanitizeMcpDisplayLabel, sanitizeMcpVisibleText } from '@/components/settings/mcpDisplay';
import {
  formatDynamicConfigFieldLabel,
  formatDynamicCredentialLabel,
  formatDynamicDescription,
  formatDynamicOptionLabel,
  getDynamicConfigManualEntryHint,
} from '@/components/settings/dynamicConfigDisplay';

export interface McpInstallWizardProps {
  initialPath?: string;
  templateHint?: string;
  presetSlug?: string;
  presetDisplayName?: string;
  open: boolean;
  onClose: () => void;
  onInstalled?: (response: McpInstallationInstallResponse) => void;
}

const VISIBLE_STEPS: WizardStep[] = [
  'source',
  'candidate',
  'config',
  'credentials',
  'review',
];

const STEP_LABELS: Record<WizardStep, string> = {
  source: '本地路径',
  scanning: '扫描中',
  candidate: '启动方式',
  config: '配置项',
  credentials: '绑定凭证',
  review: '确认',
  installing: '安装中',
  done: '完成',
  error: '失败',
};

export function McpInstallWizard(props: McpInstallWizardProps): JSX.Element | null {
  const {
    initialPath,
    templateHint,
    presetSlug,
    presetDisplayName,
    open,
    onClose,
    onInstalled,
  } = props;
  const navigate = useNavigate();

  const [state, setState] = useState<WizardState>(() => {
    const restored = loadWizardState();
    if (restored && isRestoredWizardForCurrentOpen(restored, {
      initialPath,
      templateHint,
      presetSlug,
      presetDisplayName,
    })) return restored;
    if (restored) clearWizardState();
    return defaultWizardState({
      sourcePath: initialPath ?? '',
      templateHint,
      serverSlug: presetSlug ?? '',
      displayName: presetDisplayName ?? '',
    });
  });

  useEffect(() => {
    if (open) saveWizardState(state);
  }, [open, state]);

  const close = () => {
    clearWizardState();
    onClose();
  };

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="mcp-wizard-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 md:p-8"
    >
      <div className="bg-surface-lowest rounded-lg shadow-xl border border-outline-variant w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
        <header className="flex items-center justify-between px-4 py-3 border-b border-outline-variant flex-shrink-0">
          <h3 id="mcp-wizard-title" className="font-display text-sm font-semibold text-foreground">
            安装 MCP 服务器
            {state.scan_result?.display_name && (
              <span className="text-foreground/55 font-normal"> · {state.scan_result.display_name}</span>
            )}
          </h3>
          <button
            type="button"
            onClick={close}
            aria-label="关闭"
            className="p-1.5 rounded text-foreground/55 hover:text-foreground hover:bg-surface-high"
          >
            <X size={14} />
          </button>
        </header>

        <ProgressBar step={state.step} />

        <div className="flex-1 overflow-auto p-4">
          {state.step === 'source' && <SourceStep state={state} setState={setState} />}
          {state.step === 'scanning' && <ScanningStep />}
          {state.step === 'candidate' && state.scan_result && (
            <CandidateStep
              scan={state.scan_result}
              selectedSha={state.selected_candidate_sha}
              onPick={(sha) =>
                setState({ ...state, selected_candidate_sha: sha, step: 'config' })
              }
            />
          )}
          {state.step === 'config' && state.scan_result && (
            <ConfigStep
              scan={state.scan_result}
              configValues={state.config_values}
              setConfigValues={(v) => setState({ ...state, config_values: v })}
            />
          )}
          {state.step === 'credentials' && state.scan_result && (
            <CredentialsStep
              scan={state.scan_result}
              bindings={state.credential_bindings}
              setBindings={(b) => setState({ ...state, credential_bindings: b })}
              onJumpToCreate={() => {
                saveWizardState(state);
                navigate('/settings?section=credentials');
              }}
            />
          )}
          {state.step === 'review' && state.scan_result && (
            <ReviewStep state={state} setState={setState} />
          )}
          {state.step === 'installing' && <InstallingStep />}
          {state.step === 'done' && state.install_result && (
            <DoneStep result={state.install_result} />
          )}
          {state.step === 'error' && (
            <ErrorStep
              code={state.install_error_code}
              message={state.install_error_message}
              onRetry={() => setState({ ...state, step: 'review' })}
              onFix={() => setState({ ...state, step: 'config' })}
            />
          )}
        </div>

        <WizardFooter
          state={state}
          setState={setState}
          onClose={close}
          onInstalled={(r) => {
            setState((s) => ({ ...s, install_result: r, step: 'done' }));
            onInstalled?.(r);
          }}
        />
      </div>
    </div>
  );
}

function ProgressBar({ step }: { step: WizardStep }): JSX.Element {
  const effectiveStep: WizardStep =
    step === 'scanning' ? 'source'
    : step === 'installing' ? 'review'
    : step === 'done' || step === 'error' ? 'review'
    : step;
  const currentIdx = VISIBLE_STEPS.indexOf(effectiveStep);
  return (
    <nav
      aria-label="安装进度"
      className="flex items-center gap-1 px-4 py-2 bg-surface-low border-b border-outline-variant text-[11px] font-label overflow-x-auto"
    >
      {VISIBLE_STEPS.map((s, i) => {
        const done = i < currentIdx;
        const active = i === currentIdx;
        return (
          <React.Fragment key={s}>
            <span
              className={[
                'inline-flex items-center gap-1 px-2 py-0.5 rounded whitespace-nowrap',
                active
                  ? 'bg-primary/10 text-primary font-medium'
                  : done
                  ? 'text-foreground/55'
                  : 'text-foreground/30',
              ].join(' ')}
            >
              {done && <Check size={10} />}
              <span>{i + 1}. {STEP_LABELS[s]}</span>
            </span>
            {i < VISIBLE_STEPS.length - 1 && <span className="text-foreground/30">·</span>}
          </React.Fragment>
        );
      })}
    </nav>
  );
}

function SourceStep(props: {
  state: WizardState;
  setState: (s: WizardState) => void;
}): JSX.Element {
  const { state, setState } = props;
  const [error, setError] = useState<string | null>(null);

  const runScan = async () => {
    setError(null);
    setState({ ...state, step: 'scanning' });
    try {
      const result = await scanLocalMcpPackage({
        source_path: state.source_path.trim(),
        template_hint: state.template_hint,
      });
      const next: WizardState = {
        ...state,
        scan_result: result,
        selected_candidate_sha:
          result.launch_candidates.length === 1
            ? result.launch_candidates[0].sha
            : undefined,
        step: result.needs_manual_launch
          ? 'error'
          : result.launch_candidates.length === 1
          ? 'config'
          : 'candidate',
        server_slug: deriveServerSlug(state.server_slug, result),
        display_name: state.display_name || result.display_name || '',
        config_values: applyDefaults(state.config_values, result),
      };
      if (result.needs_manual_launch) {
        next.install_error_code = 'scan_rejected';
        next.install_error_message =
          '扫描完成但未能识别可信启动方式。请到「高级 / 手动添加」手动配置,或回退检查包内容。';
      }
      setState(next);
    } catch (exc) {
      const code: McpInstallErrorCode =
        exc instanceof McpInstallApiError ? exc.code : 'install_error';
      const message = sanitizeMcpVisibleText(
        exc instanceof Error ? exc.message : String(exc),
        '扫描失败，请检查本地包是否完整。',
      );
      setError(message);
      setState({
        ...state,
        step: 'error',
        install_error_code: code,
        install_error_message: message,
      });
    }
  };

  return (
    <div className="space-y-3">
      <p className="font-label text-[12px] text-foreground/70">
        粘贴你已经下载到本地的 MCP 包路径(目录或 zip)。后端将扫描包内的声明文件并自动识别启动方式、配置项和所需凭证。
      </p>
      <label className="block">
        <span className="font-label text-[11px] text-foreground/55">本地路径</span>
        <input
          type="text"
          value={state.source_path}
          onChange={(e) => setState({ ...state, source_path: e.target.value })}
          placeholder="选择或粘贴本机 MCP 包目录"
          className="mt-1 w-full px-3 py-2 rounded border border-outline-variant bg-surface-lowest text-foreground text-xs"
        />
      </label>
      {error && (
        <div className="rounded-md border border-red-300/40 bg-red-500/5 dark:border-red-700/40 dark:bg-red-500/15 p-2 text-[11px] text-red-600 dark:text-red-300 font-label">
          {error}
        </div>
      )}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => void runScan()}
          disabled={!state.source_path.trim()}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 font-label text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          扫描 <ArrowRight size={12} />
        </button>
      </div>
    </div>
  );
}

function applyDefaults(
  current: Record<string, string>,
  scan: McpPackageScanResult,
): Record<string, string> {
  const next = { ...current };
  for (const f of scan.config_fields) {
    if (next[f.env] === undefined && f.default !== null) {
      next[f.env] = f.default;
    }
  }
  return next;
}

function normalizeWizardPath(value: string | undefined): string {
  return String(value ?? '').trim().replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
}

function isRestoredWizardForCurrentOpen(
  restored: WizardState,
  current: {
    initialPath?: string;
    templateHint?: string;
    presetSlug?: string;
    presetDisplayName?: string;
  },
): boolean {
  const currentHint = current.templateHint?.trim();
  if (currentHint) {
    return restored.template_hint === currentHint;
  }
  const currentPath = normalizeWizardPath(current.initialPath);
  if (currentPath) {
    return normalizeWizardPath(restored.source_path) === currentPath;
  }
  return !restored.template_hint;
}

function deriveServerSlug(
  currentSlug: string,
  scan: McpPackageScanResult,
): string {
  const current = currentSlug.trim();
  if (current) return current;

  const scanned = scan.server_slug?.trim();
  if (scanned) return scanned;

  return scan.package_id
    .trim()
    .toLowerCase()
    .replace(/^lit[-_]mcp[-_]/, '')
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function ScanningStep(): JSX.Element {
  return (
    <div className="flex flex-col items-center justify-center py-12 gap-3 text-foreground/60">
      <Loader2 size={24} className="animate-spin text-primary" />
      <p className="font-label text-[12px]">正在扫描包...</p>
      <p className="font-label text-[11px] text-foreground/40">只读操作,不会执行任何包代码。</p>
    </div>
  );
}

function InstallingStep(): JSX.Element {
  return (
    <div className="flex flex-col items-center justify-center py-12 gap-3 text-foreground/60">
      <Loader2 size={24} className="animate-spin text-primary" />
      <p className="font-label text-[12px]">正在注册服务器...</p>
    </div>
  );
}

function CandidateStep(props: {
  scan: McpPackageScanResult;
  selectedSha: string | undefined;
  onPick: (sha: string) => void;
}): JSX.Element {
  const { scan, selectedSha, onPick } = props;
  return (
    <div className="space-y-3">
      <p className="font-label text-[12px] text-foreground/70">
        扫描发现 {scan.launch_candidates.length} 种可能的启动方式。请选择一种;命令将以 argv 数组执行,不经过 shell。
      </p>
      <ul className="space-y-2">
        {scan.launch_candidates.map((c) => {
          const active = c.sha === selectedSha;
          return (
            <li key={c.sha}>
              <button
                type="button"
                onClick={() => onPick(c.sha)}
                className={[
                  'w-full text-left px-3 py-2 rounded-md border transition-colors',
                  active ? 'border-primary bg-primary/5' : 'border-outline-variant hover:border-outline',
                ].join(' ')}
              >
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-foreground font-medium">
                    启动方式 {scan.launch_candidates.indexOf(c) + 1}
                  </span>
                  <span className="text-[10px] text-foreground/55">
                    {c.args.length + 1} 项启动配置
                  </span>
                  <ConfidenceBadge confidence={c.confidence} />
                </div>
                <p className="font-label text-[10px] text-foreground/40 mt-0.5" title="自动识别的启动方式">
                  启动配置已识别 · 识别来源：{formatCandidateSource(c.source)}
                </p>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function formatCandidateSource(value: string): string {
  if (value.includes('manifest')) return '声明文件';
  if (value.includes('package')) return '包描述';
  if (value.includes('pyproject')) return 'Python 项目配置';
  return '扫描结果';
}

function ConfidenceBadge({ confidence }: { confidence: string }): JSX.Element {
  const map: Record<string, string> = {
    high: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
    medium: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
    low: 'bg-orange-500/15 text-orange-700 dark:text-orange-300',
    none: 'bg-red-500/15 text-red-700 dark:text-red-300',
  };
  const cls = map[confidence] ?? 'bg-foreground/10 text-foreground/55';
  const labelMap: Record<string, string> = {
    high: '高可信',
    medium: '需确认',
    low: '低可信',
    none: '需手动确认',
  };
  return (
    <span className={`font-label text-[9px] px-1.5 py-0.5 rounded ${cls}`}>
      {labelMap[confidence] ?? '需确认'}
    </span>
  );
}

function ConfigStep(props: {
  scan: McpPackageScanResult;
  configValues: Record<string, string>;
  setConfigValues: (v: Record<string, string>) => void;
}): JSX.Element {
  const { scan, configValues, setConfigValues } = props;
  if (scan.config_fields.length === 0) {
    return <p className="font-label text-[12px] text-foreground/55">此包未声明配置项,直接进入凭证绑定。</p>;
  }
  return (
    <div className="space-y-4">
      <p className="font-label text-[12px] text-foreground/70">
        按 MCP 包声明自动生成配置项。普通配置可选预设也可手动填写；敏感信息请在下一步绑定已保存凭证。
      </p>
      {scan.config_fields.map((f, fieldIndex) => {
        const label = formatDynamicConfigFieldLabel(f.label, fieldIndex);
        const description = formatDynamicDescription(f.description);
        const manualHint = getDynamicConfigManualEntryHint(f);
        return (
        <div key={f.id} className="space-y-1">
          <label className="font-label text-[11px] text-foreground/70 font-medium block">
            {label}
            {f.required && <span className="text-red-500 ml-0.5" aria-label="必填">*</span>}
          </label>
          {description && (
            <p className="font-label text-[10px] text-foreground/55">{description}</p>
          )}
          {f.type === 'select' && f.options ? (
            <div className="space-y-2">
              <select
                value={configValues[f.env] ?? f.default ?? ''}
                onChange={(e) => setConfigValues({ ...configValues, [f.env]: e.target.value })}
                className="w-full px-2 py-1.5 rounded border border-outline-variant bg-surface-lowest text-foreground text-xs"
              >
                <option value="">手动填写 / 不使用预设</option>
                {f.options.map((o, optionIndex) => (
                  <option key={o.value} value={o.value}>
                    {formatDynamicOptionLabel(o.label, optionIndex)}
                  </option>
                ))}
              </select>
              <input
                type="text"
                value={configValues[f.env] ?? f.default ?? ''}
                onChange={(e) => setConfigValues({ ...configValues, [f.env]: e.target.value })}
                placeholder="手动填写自定义取值"
                className="w-full px-2 py-1.5 rounded border border-outline-variant bg-surface-lowest text-foreground text-xs"
              />
            </div>
          ) : f.type === 'boolean' ? (
            <button
              type="button"
              role="switch"
              aria-checked={(configValues[f.env] ?? f.default ?? '') === 'true'}
              onClick={() => {
                const current = configValues[f.env] ?? f.default ?? '';
                setConfigValues({ ...configValues, [f.env]: current === 'true' ? 'false' : 'true' });
              }}
              className={[
                'w-full flex items-center justify-between px-3 py-2 rounded border text-xs font-label transition-colors',
                (configValues[f.env] ?? f.default ?? '') === 'true'
                  ? 'border-primary/40 bg-primary/10 text-primary'
                  : 'border-outline-variant bg-surface-lowest text-foreground/60',
              ].join(' ')}
            >
              <span>{(configValues[f.env] ?? f.default ?? '') === 'true' ? '已开启' : '已关闭'}</span>
              <span className="text-[10px] text-foreground/45">点击切换</span>
            </button>
          ) : (
            <input
              type={f.type === 'number' ? 'number' : 'text'}
              value={configValues[f.env] ?? f.default ?? ''}
              min={f.min ?? undefined}
              max={f.max ?? undefined}
              step={f.step ?? undefined}
              onChange={(e) => setConfigValues({ ...configValues, [f.env]: e.target.value })}
              placeholder={manualHint}
              className="w-full px-2 py-1.5 rounded border border-outline-variant bg-surface-lowest text-foreground text-xs font-mono"
            />
          )}
          {f.type !== 'boolean' && (
            <p className="font-label text-[10px] leading-relaxed text-foreground/45">
              {manualHint}
            </p>
          )}
        </div>
        );
      })}
    </div>
  );
}

function CredentialsStep(props: {
  scan: McpPackageScanResult;
  bindings: Record<string, string>;
  setBindings: (b: Record<string, string>) => void;
  onJumpToCreate: () => void;
}): JSX.Element {
  const { scan, bindings, setBindings, onJumpToCreate } = props;
  if (scan.required_credentials.length === 0) {
    return <p className="font-label text-[12px] text-foreground/55">此包未声明所需凭证,直接进入安装确认。</p>;
  }
  return (
    <div className="space-y-5">
      <p className="font-label text-[12px] text-foreground/70">
        为下面每个敏感配置选择一个已保存的凭证。系统只保存凭证引用，不会把原始密钥写入 MCP 配置文件。
      </p>
      {scan.required_credentials.map((rc) => (
        <CredentialPicker
          key={rc.id}
          requirement={rc}
          value={bindings[rc.env] ?? null}
          onChange={(id) => setBindings({ ...bindings, [rc.env]: id ?? '' })}
          onJumpToCreate={onJumpToCreate}
        />
      ))}
    </div>
  );
}

function ReviewStep(props: {
  state: WizardState;
  setState: (s: WizardState) => void;
}): JSX.Element {
  const { state, setState } = props;
  if (!state.scan_result || !state.selected_candidate_sha) return <></>;
  const candidate = state.scan_result.launch_candidates.find(
    (c) => c.sha === state.selected_candidate_sha,
  );
  return (
    <div className="space-y-4">
      <p className="font-label text-[12px] text-foreground/70">请确认以下信息后安装。</p>
      <div className="rounded-md border border-outline-variant bg-surface-low p-3 space-y-2 text-[11px] text-foreground/70">
        <Row label="名称" value={state.display_name || state.scan_result.display_name} />
        <Row label="本地注册名" value="系统自动生成" />
        <Row label="启动方式" value={candidate ? `${candidate.args.length + 1} 项启动配置` : '自动识别'} />
        <Row label="普通配置" value={summarizeConfigFields(state)} />
        <Row
          label="凭证引用"
          value={summarizeCredentialBindings(state)}
        />
      </div>

      <label className="flex items-start gap-2 p-3 rounded-md border border-amber-300/40 bg-amber-50/40 dark:border-amber-700/40 dark:bg-amber-500/10 cursor-pointer">
        <input
          type="checkbox"
          checked={state.trust_to_probe}
          onChange={(e) => setState({ ...state, trust_to_probe: e.target.checked })}
          className="mt-1 flex-shrink-0"
        />
        <div>
          <p className="font-label text-[12px] text-amber-800 dark:text-amber-200 font-medium">
            我信任此包,允许启动进程探测工具列表
          </p>
          <p className="font-label text-[11px] text-amber-700/80 dark:text-amber-200/80 mt-0.5">
            探测会运行该 MCP 包的启动方式，并读取它公开的工具列表。未勾选时仅注册不启用，你可以之后在「已安装」单独探测。
          </p>
        </div>
      </label>

      {state.trust_to_probe && (
        <label className="flex items-center gap-2 ml-5 text-[11px] text-foreground/70">
          <input
            type="checkbox"
            checked={state.enable_for_session}
            onChange={(e) => setState({ ...state, enable_for_session: e.target.checked })}
          />
          探测成功后立即启用(本次会话)
        </label>
      )}
    </div>
  );
}

function Row(props: { label: string; value: React.ReactNode }): JSX.Element {
  return (
    <div className="flex items-baseline gap-3">
      <span className="text-foreground/40 text-[10px] w-20 flex-shrink-0">{props.label}</span>
      <span className="flex-1 break-all">{props.value}</span>
    </div>
  );
}

function summarizeConfigFields(state: WizardState): string {
  const fields = state.scan_result?.config_fields ?? [];
  const labels = fields.flatMap((field, index): string[] => {
    const value = state.config_values[field.env]?.trim();
    const label = formatDynamicConfigFieldLabel(field.label, index);
    return value ? [`${label}: 已填写`] : [];
  });
  return labels.length > 0 ? labels.join('，') : '无';
}

function summarizeCredentialBindings(state: WizardState): string {
  const requirements = state.scan_result?.required_credentials ?? [];
  const labels = requirements.flatMap((item, index): string[] => {
    const binding = state.credential_bindings[item.env]?.trim();
    const label = formatDynamicCredentialLabel(item.label, index);
    return binding ? [`${label}: 已绑定`] : [];
  });
  return labels.length > 0 ? labels.join('，') : '无';
}

function DoneStep(props: { result: McpInstallationInstallResponse }): JSX.Element {
  const { result } = props;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300">
        <Check size={18} />
        <h4 className="font-display text-sm font-semibold">安装完成</h4>
      </div>
      <div className="rounded-md border border-outline-variant bg-surface-low p-3 text-[11px] text-foreground/70 space-y-1">
        <div>注册信息: 已保存</div>
        <div>本机记录: 已保存</div>
        <div>运行配置: 已生成</div>
        <div>审批状态: {formatApprovalState(result.approval_state)}</div>
        <div>探测结果: {formatProbeStatus(result.probe.status)}（{result.probe.tool_count} 个工具）</div>
      </div>
      {result.probe.status === 'ok' && result.probe.tools.length > 0 && (
        <div>
          <p className="font-label text-[11px] text-foreground/55 mb-1">已发现的工具:</p>
          <ul className="text-[11px] space-y-0.5">
            {result.probe.tools.map((t, i) => (
              <li key={i} className="text-foreground/70">
                · {sanitizeMcpDisplayLabel(String((t as { name?: string }).name ?? ''), `工具 ${i + 1}`)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function formatApprovalState(value: string): string {
  if (value === 'trusted') return '已信任';
  if (value === 'pending') return '待确认';
  if (value === 'blocked') return '已阻止';
  return value || '未知';
}

function formatProbeStatus(value: McpInstallationInstallResponse['probe']['status']): string {
  if (value === 'ok') return '成功';
  if (value === 'skipped_untrusted') return '已跳过';
  return '失败';
}

function ErrorStep(props: {
  code: string | undefined;
  message: string | undefined;
  onRetry: () => void;
  onFix: () => void;
}): JSX.Element {
  const { code, message, onRetry, onFix } = props;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-red-600 dark:text-red-300">
        <AlertTriangle size={18} />
        <h4 className="font-display text-sm font-semibold">安装失败</h4>
      </div>
      <div className="rounded-md border border-red-300/40 bg-red-500/5 dark:border-red-700/40 dark:bg-red-500/15 p-3 text-[11px] text-red-700 dark:text-red-200 font-label space-y-1">
        {code && <div>失败类型：{formatInstallErrorCode(code)}</div>}
        {message && <p>{message}</p>}
      </div>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onFix}
          className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant px-3 py-1.5 font-label text-xs text-foreground/70 hover:bg-surface-high"
        >
          修复配置
        </button>
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary/10 px-3 py-1.5 font-label text-xs font-medium text-primary hover:bg-primary/15"
        >
          <Zap size={12} /> 重试
        </button>
      </div>
    </div>
  );
}

function formatInstallErrorCode(value: string): string {
  const labels: Record<string, string> = {
    scan_rejected: '未识别可用启动方式',
    scan_not_found: '扫描结果已丢失',
    scan_expired: '扫描结果已过期',
    candidate_mismatch: '启动方式已变化',
    credential_not_found: '凭证不存在',
    credential_disabled: '凭证已停用',
    transport_unsupported: '暂不支持的连接方式',
    server_slug_conflict: '本地注册名已被占用',
    install_error: '安装失败',
  };
  return labels[value] ?? '安装失败';
}

function WizardFooter(props: {
  state: WizardState;
  setState: (s: WizardState) => void;
  onClose: () => void;
  onInstalled: (r: McpInstallationInstallResponse) => void;
}): JSX.Element | null {
  const { state, setState, onClose, onInstalled } = props;

  if (state.step === 'scanning' || state.step === 'installing') return null;

  if (state.step === 'done' || state.step === 'error') {
    return (
      <footer className="px-4 py-3 border-t border-outline-variant flex justify-end gap-2 flex-shrink-0">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md bg-primary px-3 py-1.5 font-label text-xs font-medium text-primary-foreground hover:bg-primary/90"
        >
          完成
        </button>
      </footer>
    );
  }

  const back = backStepFor(state.step);
  const nextInfo = nextStepFor(state);

  async function doInstall() {
    setState({ ...state, step: 'installing' });
    try {
      const result = await installMcpPackage({
        scan_id: state.scan_result!.scan_id,
        launch_candidate_sha: state.selected_candidate_sha!,
        server_slug: state.server_slug.trim(),
        display_name:
          state.display_name.trim() || state.scan_result?.display_name || state.server_slug.trim(),
        config_values: state.config_values,
        credential_bindings: state.credential_bindings,
        trust_to_probe: state.trust_to_probe,
        enable_for_session: state.enable_for_session,
      });
      onInstalled(result);
    } catch (exc) {
      const code = exc instanceof McpInstallApiError ? exc.code : 'install_error';
      const message = sanitizeMcpVisibleText(
        exc instanceof Error ? exc.message : String(exc),
        '安装失败，请检查配置后重试。',
      );
      setState({
        ...state,
        step: 'error',
        install_error_code: code,
        install_error_message: message,
      });
    }
  }

  return (
    <footer className="px-4 py-3 border-t border-outline-variant flex items-center justify-between gap-2 flex-shrink-0">
      <button
        type="button"
        onClick={onClose}
        className="font-label text-xs text-foreground/55 hover:text-foreground"
      >
        取消
      </button>
      <div className="flex items-center gap-2">
        {back && (
          <button
            type="button"
            onClick={() => setState({ ...state, step: back })}
            className="inline-flex items-center gap-1 rounded-md border border-outline-variant px-3 py-1.5 font-label text-xs text-foreground/70 hover:bg-surface-high"
          >
            <ArrowLeft size={12} /> 上一步
          </button>
        )}
        {state.step === 'review' ? (
          <button
            type="button"
            disabled={!state.trust_to_probe || !state.server_slug.trim()}
            onClick={() => void doInstall()}
            title={
              !state.trust_to_probe
                ? '请先勾选信任确认'
                : !state.server_slug.trim()
                ? '请返回上一步重新扫描'
                : '注册并探测'
            }
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 font-label text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            <Zap size={12} /> 安装
          </button>
        ) : state.step === 'source' ? null : (
          <button
            type="button"
            disabled={!nextInfo.canProceed}
            onClick={() => setState({ ...state, step: nextInfo.target })}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 font-label text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            下一步 <ArrowRight size={12} />
          </button>
        )}
      </div>
    </footer>
  );
}

function backStepFor(step: WizardStep): WizardStep | null {
  const order: WizardStep[] = ['source', 'candidate', 'config', 'credentials', 'review'];
  const i = order.indexOf(step);
  if (i <= 0) return null;
  return order[i - 1];
}

function nextStepFor(state: WizardState): { target: WizardStep; canProceed: boolean } {
  switch (state.step) {
    case 'candidate':
      return { target: 'config', canProceed: !!state.selected_candidate_sha };
    case 'config': {
      const scan = state.scan_result;
      const requiredMissing =
        scan?.config_fields
          .filter((f) => f.required)
          .some((f) => !state.config_values[f.env]?.trim()) ?? false;
      return { target: 'credentials', canProceed: !requiredMissing };
    }
    case 'credentials': {
      const scan = state.scan_result;
      const requiredMissing =
        scan?.required_credentials
          .filter((rc) => rc.required)
          .some((rc) => !state.credential_bindings[rc.env]?.trim()) ?? false;
      return { target: 'review', canProceed: !requiredMissing };
    }
    default:
      return { target: state.step, canProceed: false };
  }
}

export default McpInstallWizard;
export type { WizardState };
