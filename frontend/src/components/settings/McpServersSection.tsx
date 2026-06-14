import React, { useCallback, useEffect, useState } from 'react';
import {
  Check,
  Loader2,
  Plus,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Trash2,
  X,
  Zap,
} from 'lucide-react';
import {
  type McpApprovalState,
  type McpServerConfigCreate,
  type McpServerConfigPublic,
  type McpTestResponse,
  type McpToolDescriptor,
  type McpToolCapability,
  type McpTransport,
  createMcpServer,
  deleteMcpServer,
  listMcpServers,
  listMcpServerTools,
  testMcpServer,
  updateMcpServer,
} from '@/services/mcpApi';
import { McpAuditPanel } from '@/components/settings/McpAuditPanel';
import { formatMcpActionError, MCP_TRANSPORT_LABELS, sanitizeMcpDisplayLabel, sanitizeMcpVisibleText } from './mcpDisplay';

// ---------------------------------------------------------------------------
// UI types
// ---------------------------------------------------------------------------

type FormMode = 'idle' | 'create';

interface FormState {
  name: string;
  server_slug: string;
  transport: McpTransport;
  // stdio fields
  command: string;
  args: string; // newline / space separated; UI splits on newline
  env: string; // KEY=value per line
  // streamable_http fields
  url: string;
  headers: string; // KEY: value per line
  notes: string;
}

const EMPTY_FORM: FormState = {
  name: '',
  server_slug: '',
  transport: 'stdio',
  command: 'python',
  args: '',
  env: '',
  url: '',
  headers: '',
  notes: '',
};

const APPROVAL_LABELS: Record<McpApprovalState, string> = {
  registered: '已登记，未启用',
  catalog_reviewed: '已审阅，未授权',
  enabled_for_session: '本次会话已授权',
};

const APPROVAL_NEXT: Record<McpApprovalState, McpApprovalState | null> = {
  registered: 'catalog_reviewed',
  catalog_reviewed: 'enabled_for_session',
  enabled_for_session: null,
};

const TOOL_CAPABILITY_LABELS: Record<McpToolCapability, string> = {
  read: '读取',
  write: '写入',
  network: '联网',
  filesystem: '文件',
  destructive: '高风险',
  unknown: '未分类',
};

function parseLinesToMap(raw: string, sep: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const idx = trimmed.indexOf(sep);
    if (idx <= 0) continue;
    const k = trimmed.slice(0, idx).trim();
    const v = trimmed.slice(idx + sep.length).trim();
    if (k) out[k] = v;
  }
  return out;
}

function parseArgs(raw: string): string[] {
  return raw.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
}

function formatProbeResult(result: McpTestResponse): string {
  if (result.status === 'ok') {
    return `可用 · ${result.tool_count ?? 0} 个工具`;
  }
  const reason = sanitizeMcpVisibleText(result.reason, '测试没有通过，请检查服务配置。');
  if (result.status === 'skipped') return reason;
  return reason;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function McpServersSection(): JSX.Element {
  const [list, setList] = useState<McpServerConfigPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<FormMode>('idle');
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, McpTestResponse>>({});
  const [toolsByServer, setToolsByServer] = useState<Record<string, McpToolDescriptor[]>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listMcpServers();
      setList(data);
    } catch (exc) {
      setError(formatMcpActionError(exc, '加载 MCP 服务器失败，请稍后重试。'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = async () => {
    setError(null);
    if (!form.name || !form.server_slug) {
      setError('请填写名称和本地注册名');
      return;
    }
    try {
      const body: McpServerConfigCreate = {
        name: form.name,
        server_slug: form.server_slug,
        transport: form.transport,
        notes: form.notes,
        provenance: 'runtime_user_confirmed',
      };
      if (form.transport === 'stdio') {
        body.stdio = {
          command: form.command,
          args: parseArgs(form.args),
          env: parseLinesToMap(form.env, '='),
        };
      } else {
        body.http = {
          url: form.url,
          headers: parseLinesToMap(form.headers, ':'),
        };
      }
      await createMcpServer(body);
      setMode('idle');
      setForm(EMPTY_FORM);
      await refresh();
    } catch (exc) {
      setError(formatMcpActionError(exc, '新增 MCP 服务器失败，请检查填写内容。'));
    }
  };

  const handleAdvanceApproval = async (server: McpServerConfigPublic) => {
    const next = APPROVAL_NEXT[server.approval_state];
    if (!next) return;
    setBusyId(server.server_id);
    setError(null);
    try {
      await updateMcpServer(server.server_id, { approval_state: next });
      await refresh();
    } catch (exc) {
      setError(formatMcpActionError(exc, '更新授权状态失败，请稍后重试。'));
    } finally {
      setBusyId(null);
    }
  };

  const handleRevokeApproval = async (server: McpServerConfigPublic) => {
    if (server.approval_state === 'registered') return;
    const serverLabel = sanitizeMcpDisplayLabel(server.name, 'MCP 服务');
    const confirmed = window.confirm(
      `撤销 ${serverLabel} 的会话授权？\n\n` +
      `状态将从「${APPROVAL_LABELS[server.approval_state]}」回到「已登记，未启用」。` +
      `\n该服务的工具调用会被拦截，直到再次完成授权。`
    );
    if (!confirmed) return;
    setBusyId(server.server_id);
    setError(null);
    try {
      await updateMcpServer(server.server_id, { approval_state: 'registered' });
      await refresh();
    } catch (exc) {
      setError(formatMcpActionError(exc, '撤销授权失败，请稍后重试。'));
    } finally {
      setBusyId(null);
    }
  };

  const handleTest = async (server: McpServerConfigPublic) => {
    setBusyId(server.server_id);
    setError(null);
    try {
      const result = await testMcpServer(server.server_id);
      setTestResults(prev => ({ ...prev, [server.server_id]: result }));
      if (result.tools) {
        setToolsByServer(prev => ({ ...prev, [server.server_id]: result.tools! }));
      }
      await refresh();
    } catch (exc) {
      setError(formatMcpActionError(exc, '测试 MCP 服务器失败，请检查服务是否可用。'));
    } finally {
      setBusyId(null);
    }
  };

  const handleLoadTools = async (server: McpServerConfigPublic) => {
    setBusyId(server.server_id);
    try {
      const tools = await listMcpServerTools(server.server_id);
      setToolsByServer(prev => ({ ...prev, [server.server_id]: tools }));
      setExpandedId(server.server_id);
    } catch (exc) {
      setError(formatMcpActionError(exc, '读取工具目录失败，请稍后重试。'));
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (server: McpServerConfigPublic) => {
    const serverLabel = sanitizeMcpDisplayLabel(server.name, 'MCP 服务');
    if (!confirm(`删除 MCP 服务器「${serverLabel}」？`)) {
      return;
    }
    setBusyId(server.server_id);
    setError(null);
    try {
      await deleteMcpServer(server.server_id);
      await refresh();
    } catch (exc) {
      setError(formatMcpActionError(exc, '删除 MCP 服务器失败，请稍后重试。'));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-display text-base font-semibold text-foreground">MCP 服务器</h3>
          <p className="mt-1 font-label text-[11px] leading-relaxed text-foreground/55">
            本地 MCP 服务。会话授权后可调用。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            className="rounded-md px-2 py-1.5 text-foreground/60 transition-colors hover:bg-surface-high hover:text-foreground"
            title="刷新"
            aria-label="刷新"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
          <button
            type="button"
            onClick={() => { setMode('create'); setForm(EMPTY_FORM); }}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary/10 px-3 py-1.5 font-label text-xs font-medium text-primary transition-colors hover:bg-primary/15"
          >
            <Plus size={14} /> 新增服务
          </button>
        </div>
      </div>

      {error ? (
        <div className="p-3 rounded-md border border-red-300/40 bg-red-500/5 text-red-500 font-label text-xs dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
          {error}
        </div>
      ) : null}

      {mode === 'create' ? (
        <CreateForm
          form={form}
          setForm={setForm}
          onCancel={() => { setMode('idle'); setForm(EMPTY_FORM); }}
          onSubmit={() => void handleCreate()}
        />
      ) : null}

      <div className="space-y-2">
        {list.length === 0 ? (
          <div className="p-4 rounded-md border border-dashed border-outline-variant text-foreground/40 font-label text-xs text-center">
            还没有配置 MCP 服务器。
          </div>
        ) : list.map(server => {
          const result = testResults[server.server_id];
          const tools = toolsByServer[server.server_id];
          const isBusy = busyId === server.server_id;
          const next = APPROVAL_NEXT[server.approval_state];
          const isUntrusted = server.provenance === 'runtime_untrusted_custom';
          const serverLabel = sanitizeMcpDisplayLabel(server.name, 'MCP 服务');
          return (
            <div key={server.server_id} className="p-3 rounded-md border border-outline-variant bg-surface-low">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium text-sm text-foreground truncate">{serverLabel}</span>
                    <span className="text-[10px] text-foreground/45 px-1.5 py-0.5 rounded bg-surface-high">
                      本地服务器
                    </span>
                    <span className="font-label text-[10px] text-foreground/45 px-1.5 py-0.5 rounded bg-surface-high">
                      {MCP_TRANSPORT_LABELS[server.transport]}
                    </span>
                    <ApprovalBadge state={server.approval_state} />
                    {isUntrusted ? (
                      <span title="手动添加的服务，请确认来源可信">
                        <ShieldAlert size={12} className="text-amber-500" />
                      </span>
                    ) : null}
                  </div>
                  <div className="font-label text-[10px] text-foreground/45">
                    {server.transport === 'stdio'
                      ? `本地进程 · ${(server.stdio?.args ?? []).length + 1} 项启动配置`
                      : '网络服务 · 已填写服务地址'}
                  </div>
                  {result ? (
                    <div className={`mt-1 font-label text-[11px] ${result.status === 'ok' ? 'text-emerald-500' : 'text-amber-500'}`}>
                      {formatProbeResult(result)}
                    </div>
                  ) : null}
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <button
                    type="button"
                    onClick={() => void handleTest(server)}
                    disabled={isBusy}
                    title="测试服务是否可用"
                    className="px-2 py-1.5 rounded text-foreground/60 hover:text-foreground hover:bg-surface-high transition-colors disabled:opacity-50"
                  >
                    {isBusy ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                  </button>
                  {next ? (
                    <button
                      type="button"
                      onClick={() => void handleAdvanceApproval(server)}
                      disabled={isBusy}
                      title={`推进到：${APPROVAL_LABELS[next]}`}
                      className="flex items-center gap-1 px-2 py-1.5 rounded text-emerald-600 hover:bg-emerald-500/10 transition-colors disabled:opacity-50 font-label text-[10px] dark:text-emerald-300 dark:hover:bg-emerald-500/15"
                    >
                      <Check size={12} /> 推进
                    </button>
                  ) : null}
                  {server.approval_state !== 'registered' ? (
                    <button
                      type="button"
                      onClick={() => void handleRevokeApproval(server)}
                      disabled={isBusy}
                      title="撤销本次会话授权"
                      className="flex items-center gap-1 px-2 py-1.5 rounded text-amber-600 hover:bg-amber-500/10 transition-colors disabled:opacity-50 font-label text-[10px] dark:text-amber-300 dark:hover:bg-amber-500/15"
                    >
                      <ShieldOff size={12} /> 撤销
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => void handleLoadTools(server)}
                    disabled={isBusy}
                    title="查看缓存的工具目录"
                    className="px-2 py-1.5 rounded text-foreground/60 hover:text-foreground hover:bg-surface-high transition-colors disabled:opacity-50 font-label text-[10px]"
                  >
                    工具
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDelete(server)}
                    disabled={isBusy}
                    title="删除"
                    aria-label="删除"
                    className="px-2 py-1.5 rounded text-red-500/70 hover:text-red-500 hover:bg-red-500/10 transition-colors disabled:opacity-50 dark:text-red-300/75 dark:hover:bg-red-500/15 dark:hover:text-red-300"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              {expandedId === server.server_id && tools ? (
                <div className="mt-3 pt-3 border-t border-outline-variant space-y-1">
                  {tools.length === 0 ? (
                    <div className="text-foreground/40 font-label text-[11px]">未发现工具。</div>
                  ) : tools.map(t => (
                    <div key={t.name} className="flex items-baseline gap-2">
                      <span className="font-label text-[11px] text-foreground">{sanitizeMcpDisplayLabel(t.name, 'MCP 工具')}</span>
                      <span className="text-[10px] text-foreground/40">
                        {TOOL_CAPABILITY_LABELS[t.capability] ?? '未分类'}
                      </span>
                      <span className="font-label text-[11px] text-foreground/60 truncate">
                        {sanitizeMcpVisibleText(t.description, '该工具用于服务提供的扩展操作。')}
                      </span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
      <McpAuditPanel />
    </div>
  );
}

function ApprovalBadge({ state }: { state: McpApprovalState }): JSX.Element {
  const styles: Record<McpApprovalState, string> = {
    registered: 'bg-foreground/10 text-foreground/60',
    catalog_reviewed: 'bg-blue-500/10 text-blue-500 dark:bg-blue-500/15 dark:text-blue-300',
    enabled_for_session: 'bg-emerald-500/10 text-emerald-500 dark:bg-emerald-500/15 dark:text-emerald-300',
  };
  return (
    <span className={`flex items-center gap-1 px-1.5 py-0.5 rounded font-label text-[10px] font-medium ${styles[state]}`}>
      {state === 'enabled_for_session' ? <ShieldCheck size={10} /> : null}
      {APPROVAL_LABELS[state]}
    </span>
  );
}

interface CreateFormProps {
  form: FormState;
  setForm: React.Dispatch<React.SetStateAction<FormState>>;
  onCancel: () => void;
  onSubmit: () => void;
}

function CreateForm({ form, setForm, onCancel, onSubmit }: CreateFormProps): JSX.Element {
  const isStdio = form.transport === 'stdio';
  return (
    <div className="p-3 rounded-md border border-outline-variant bg-surface-low space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="font-display text-sm font-semibold text-foreground">新增 MCP 服务器</h4>
        <button
          type="button"
          onClick={onCancel}
          className="p-1 rounded text-foreground/40 hover:text-foreground hover:bg-surface-high"
        >
          <X size={14} />
        </button>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Input label="名称" value={form.name} onChange={v => setForm(p => ({ ...p, name: v }))} />
        <Input label="本地注册名" value={form.server_slug} onChange={v => setForm(p => ({ ...p, server_slug: v }))} />
      </div>

      <div>
        <label className="font-label text-[10px] text-foreground/60">连接方式</label>
        <div className="flex gap-2 mt-1">
          {(['stdio', 'streamable_http'] as McpTransport[]).map(t => (
            <button
              key={t}
              type="button"
              onClick={() => setForm(p => ({ ...p, transport: t }))}
              className={`px-3 py-1.5 rounded font-mono text-[11px] ${form.transport === t ? 'bg-primary/10 text-primary' : 'bg-surface-high text-foreground/60'}`}
            >
              {t === 'stdio' ? '本地进程' : '网络服务'}
            </button>
          ))}
        </div>
      </div>

      {isStdio ? (
        <>
          <Input label="启动命令" value={form.command} onChange={v => setForm(p => ({ ...p, command: v }))} mono />
          <TextArea label="启动参数（每行一项）" value={form.args} rows={3} onChange={v => setForm(p => ({ ...p, args: v }))} mono />
          <TextArea label="普通配置（每行一项）" value={form.env} rows={3} onChange={v => setForm(p => ({ ...p, env: v }))} />
        </>
      ) : (
        <>
          <Input label="服务地址" value={form.url} onChange={v => setForm(p => ({ ...p, url: v }))} mono />
          <TextArea label="网络请求配置（名称: 内容，每行一项）" value={form.headers} rows={3} onChange={v => setForm(p => ({ ...p, headers: v }))} mono />
          <p className="font-label text-[10px] text-amber-500">
            该传输方式需要先在本地运行配置中开启。
          </p>
        </>
      )}

      <TextArea label="备注" value={form.notes} rows={2} onChange={v => setForm(p => ({ ...p, notes: v }))} />

      <div className="flex justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 rounded font-label text-xs text-foreground/60 hover:bg-surface-high"
        >
          取消
        </button>
        <button
          type="button"
          onClick={onSubmit}
          className="px-3 py-1.5 rounded bg-primary text-primary-foreground font-label text-xs font-medium hover:bg-primary/90"
        >
          创建
        </button>
      </div>
    </div>
  );
}

interface InputProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  mono?: boolean;
}

function Input({ label, value, onChange, mono }: InputProps): JSX.Element {
  return (
    <label className="block">
      <span className="font-label text-[10px] text-foreground/60">{label}</span>
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        className={`mt-1 w-full px-2 py-1.5 rounded border border-outline-variant bg-surface-lowest text-foreground text-xs ${mono ? 'font-mono' : ''}`}
      />
    </label>
  );
}

interface TextAreaProps extends InputProps {
  rows: number;
}

function TextArea({ label, value, onChange, rows, mono }: TextAreaProps): JSX.Element {
  return (
    <label className="block">
      <span className="font-label text-[10px] text-foreground/60">{label}</span>
      <textarea
        value={value}
        rows={rows}
        onChange={e => onChange(e.target.value)}
        className={`mt-1 w-full px-2 py-1.5 rounded border border-outline-variant bg-surface-lowest text-foreground text-xs ${mono ? 'font-mono' : ''}`}
      />
    </label>
  );
}

export default McpServersSection;
