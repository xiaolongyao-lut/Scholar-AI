import React, { useCallback, useEffect, useState } from 'react';
import {
  Check,
  Loader2,
  Plus,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
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
  type McpTransport,
  createMcpServer,
  deleteMcpServer,
  listMcpServers,
  listMcpServerTools,
  testMcpServer,
  updateMcpServer,
} from '@/services/mcpApi';

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
  registered: 'Registered (untested)',
  catalog_reviewed: 'Catalog reviewed',
  enabled_for_session: 'Enabled for session',
};

const APPROVAL_NEXT: Record<McpApprovalState, McpApprovalState | null> = {
  registered: 'catalog_reviewed',
  catalog_reviewed: 'enabled_for_session',
  enabled_for_session: null,
};

function toMessage(exc: unknown): string {
  if (exc && typeof exc === 'object' && 'response' in exc) {
    const resp = (exc as { response?: { data?: { detail?: string }; status?: number } }).response;
    if (resp?.data?.detail) return String(resp.data.detail);
    if (resp?.status) return `HTTP ${resp.status}`;
  }
  if (exc instanceof Error) return exc.message;
  return String(exc);
}

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
      setError(toMessage(exc));
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
      setError('name and server_slug are required');
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
      setError(toMessage(exc));
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
      setError(toMessage(exc));
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
      setError(toMessage(exc));
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
      setError(toMessage(exc));
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (server: McpServerConfigPublic) => {
    if (!confirm(`Delete MCP server "${server.name}" (${server.server_slug})?`)) {
      return;
    }
    setBusyId(server.server_id);
    setError(null);
    try {
      await deleteMcpServer(server.server_id);
      await refresh();
    } catch (exc) {
      setError(toMessage(exc));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-display text-base font-semibold text-foreground">MCP Servers</h3>
          <p className="font-label text-[11px] text-foreground/50 mt-1 leading-relaxed">
            Local-only Model Context Protocol servers. Approval state must reach
            <span className="font-medium text-foreground/70"> enabled_for_session </span>
            before chat can call any tool. Local process runner — not a true sandbox.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            className="px-2 py-1.5 rounded-md text-foreground/60 hover:text-foreground hover:bg-surface-high transition-colors"
            title="Refresh"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
          <button
            type="button"
            onClick={() => { setMode('create'); setForm(EMPTY_FORM); }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary/10 text-primary hover:bg-primary/15 font-label text-xs font-medium transition-colors"
          >
            <Plus size={14} /> Add server
          </button>
        </div>
      </div>

      {error ? (
        <div className="p-3 rounded-md border border-red-300/40 bg-red-500/5 text-red-500 font-label text-xs">
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
            No MCP servers configured.
          </div>
        ) : list.map(server => {
          const result = testResults[server.server_id];
          const tools = toolsByServer[server.server_id];
          const isBusy = busyId === server.server_id;
          const next = APPROVAL_NEXT[server.approval_state];
          const isUntrusted = server.provenance === 'runtime_untrusted_custom';
          return (
            <div key={server.server_id} className="p-3 rounded-md border border-outline-variant bg-surface-low">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium text-sm text-foreground truncate">{server.name}</span>
                    <span className="font-mono text-[10px] text-foreground/40 px-1.5 py-0.5 rounded bg-surface-high">
                      {server.server_slug}
                    </span>
                    <span className="font-mono text-[10px] text-foreground/40 px-1.5 py-0.5 rounded bg-surface-high">
                      {server.transport}
                    </span>
                    <ApprovalBadge state={server.approval_state} />
                    {isUntrusted ? (
                      <span title="provenance: runtime_untrusted_custom">
                        <ShieldAlert size={12} className="text-amber-500" />
                      </span>
                    ) : null}
                  </div>
                  <div className="font-mono text-[10px] text-foreground/40 break-all">
                    {server.transport === 'stdio'
                      ? `${server.stdio?.command} ${(server.stdio?.args ?? []).join(' ')}`
                      : server.http?.url}
                  </div>
                  {result ? (
                    <div className={`mt-1 font-label text-[11px] ${result.status === 'ok' ? 'text-emerald-500' : 'text-amber-500'}`}>
                      {result.status === 'ok'
                        ? `OK · ${result.tool_count ?? 0} tools · fingerprint ${result.fingerprint ?? ''}`
                        : `${result.status}${result.reason ? ` — ${result.reason}` : ''}`}
                    </div>
                  ) : null}
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <button
                    type="button"
                    onClick={() => void handleTest(server)}
                    disabled={isBusy}
                    title="Probe (list_tools)"
                    className="px-2 py-1.5 rounded text-foreground/60 hover:text-foreground hover:bg-surface-high transition-colors disabled:opacity-50"
                  >
                    {isBusy ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                  </button>
                  {next ? (
                    <button
                      type="button"
                      onClick={() => void handleAdvanceApproval(server)}
                      disabled={isBusy}
                      title={`Advance → ${APPROVAL_LABELS[next]}`}
                      className="flex items-center gap-1 px-2 py-1.5 rounded text-emerald-600 hover:bg-emerald-500/10 transition-colors disabled:opacity-50 font-label text-[10px]"
                    >
                      <Check size={12} /> Advance
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => void handleLoadTools(server)}
                    disabled={isBusy}
                    title="Show cached tool catalog"
                    className="px-2 py-1.5 rounded text-foreground/60 hover:text-foreground hover:bg-surface-high transition-colors disabled:opacity-50 font-label text-[10px]"
                  >
                    Tools
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDelete(server)}
                    disabled={isBusy}
                    title="Delete"
                    className="px-2 py-1.5 rounded text-red-500/70 hover:text-red-500 hover:bg-red-500/10 transition-colors disabled:opacity-50"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              {expandedId === server.server_id && tools ? (
                <div className="mt-3 pt-3 border-t border-outline-variant space-y-1">
                  {tools.length === 0 ? (
                    <div className="text-foreground/40 font-label text-[11px]">No tools advertised.</div>
                  ) : tools.map(t => (
                    <div key={t.name} className="flex items-baseline gap-2">
                      <span className="font-mono text-[11px] text-foreground">{t.name}</span>
                      <span className="font-mono text-[10px] text-foreground/40">[{t.capability}]</span>
                      <span className="font-label text-[11px] text-foreground/60 truncate">{t.description}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ApprovalBadge({ state }: { state: McpApprovalState }): JSX.Element {
  const styles: Record<McpApprovalState, string> = {
    registered: 'bg-foreground/10 text-foreground/60',
    catalog_reviewed: 'bg-blue-500/10 text-blue-500',
    enabled_for_session: 'bg-emerald-500/10 text-emerald-500',
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
        <h4 className="font-display text-sm font-semibold text-foreground">Add MCP server</h4>
        <button
          type="button"
          onClick={onCancel}
          className="p-1 rounded text-foreground/40 hover:text-foreground hover:bg-surface-high"
        >
          <X size={14} />
        </button>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Input label="Name" value={form.name} onChange={v => setForm(p => ({ ...p, name: v }))} />
        <Input label="server_slug (URL-safe)" value={form.server_slug} onChange={v => setForm(p => ({ ...p, server_slug: v }))} mono />
      </div>

      <div>
        <label className="font-label text-[10px] text-foreground/60">Transport</label>
        <div className="flex gap-2 mt-1">
          {(['stdio', 'streamable_http'] as McpTransport[]).map(t => (
            <button
              key={t}
              type="button"
              onClick={() => setForm(p => ({ ...p, transport: t }))}
              className={`px-3 py-1.5 rounded font-mono text-[11px] ${form.transport === t ? 'bg-primary/10 text-primary' : 'bg-surface-high text-foreground/60'}`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {isStdio ? (
        <>
          <Input label="Command" value={form.command} onChange={v => setForm(p => ({ ...p, command: v }))} mono />
          <TextArea label="Args (one per line)" value={form.args} rows={3} onChange={v => setForm(p => ({ ...p, args: v }))} mono />
          <TextArea label="Env (KEY=value per line)" value={form.env} rows={3} onChange={v => setForm(p => ({ ...p, env: v }))} mono />
        </>
      ) : (
        <>
          <Input label="URL" value={form.url} onChange={v => setForm(p => ({ ...p, url: v }))} mono />
          <TextArea label="Headers (Header: value per line)" value={form.headers} rows={3} onChange={v => setForm(p => ({ ...p, headers: v }))} mono />
          <p className="font-label text-[10px] text-amber-500">
            Streamable HTTP execution is gated behind LITERATURE_ENABLE_MCP_STREAMABLE_HTTP=1.
          </p>
        </>
      )}

      <TextArea label="Notes" value={form.notes} rows={2} onChange={v => setForm(p => ({ ...p, notes: v }))} />

      <div className="flex justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 rounded font-label text-xs text-foreground/60 hover:bg-surface-high"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onSubmit}
          className="px-3 py-1.5 rounded bg-primary text-primary-foreground font-label text-xs font-medium hover:bg-primary/90"
        >
          Create
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
