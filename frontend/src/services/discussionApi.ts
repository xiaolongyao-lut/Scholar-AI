import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl.ts';

const API_BASE = '/api/discussion';

type JsonObject = Record<string, unknown>;

export interface AgentRole {
  value: 'proponent' | 'opponent' | 'reviewer' | 'moderator';
}

export interface CreateDiscussionRequest {
  topic: string;
  roles: string[];
  max_turns?: number;
}

export interface CreateDiscussionResponse {
  session_id: string;
  topic: string;
  roles: string[];
  max_turns: number;
}

export interface DiscussionMessage {
  id: string;
  role: string;
  message_type: string;
  content: string;
  timestamp: string;
  metadata: JsonObject;
}

export interface DiscussionStatusResponse {
  session_id: string;
  topic: string;
  status: string;
  current_turn: number;
  total_messages: number;
  synthesis: string | null;
}

export interface DiscussionHistoryResponse {
  session_id: string;
  messages: DiscussionMessage[];
}

export interface RunTurnResponse {
  session_id: string;
  turn_number: number;
  messages: DiscussionMessage[];
  status: string;
}

export type DiscussionAgentRole =
  | 'proposer'
  | 'critic'
  | 'devil_advocate'
  | 'domain_expert'
  | 'synthesizer'
  | 'custom';

export type DiscussionEvidenceMode = 'from_project' | 'manual_chunk_ids' | 'none';

export type DiscussionSynthesisStrategy = 'synthesize' | 'vote' | 'debate';

export interface DiscussionLLMConfig {
  provider: string;
  model: string;
  base_url: string;
  api_key: string;
  protocol?: string;
  temperature?: number;
  max_tokens?: number;
}

export interface DiscussionAgentConfig {
  agent_id: string;
  role: DiscussionAgentRole;
  role_label?: string;
  system_prompt?: string;
  credential_id?: string | null;
  llm?: DiscussionLLMConfig | null;
  strict_pin?: boolean;
  priority?: number;
  metadata?: JsonObject;
}

export interface DiscussionMcpOverrides {
  server_ids: string[];
  allow_high_risk_tools?: boolean;
  // per_agent intentionally omitted from the TS surface in v1 — backend
  // accepts it but the UI hides per-agent scoping per D-MCPUX-5.
}

export interface DiscussionRunConfig {
  project_id?: string | null;
  query: string;
  agent_configs: DiscussionAgentConfig[];
  synthesizer_agent_id?: string | null;
  max_turns?: number;
  evidence_mode?: DiscussionEvidenceMode;
  evidence_top_k?: number;
  evidence_chunk_ids?: string[];
  evidence_inline?: string[];
  synthesis_strategy?: DiscussionSynthesisStrategy;
  timeout_seconds?: number;
  max_concurrency?: number | null;
  auto_stop?: boolean;
  min_turns?: number;
  convergence_threshold?: number;
  convergence_judge_agent_id?: string | null;
  mcp_overrides?: DiscussionMcpOverrides | null;
}

export interface DiscussionEvidencePackPayload {
  pack_id: string;
  pack_version: string;
  project_id: string;
  query: string;
  snippets: JsonObject[];
  truncated: boolean;
  evidence_ids?: string[];
}

export interface AnalysisChainPayload {
  observation?: string;
  mechanism?: string;
  evidence?: string[];
  boundary?: string;
  counter_evidence?: string[];
  next_action?: string;
}

export interface DiscussionAgentTrace {
  agent_id: string;
  role: string;
  role_label: string;
  credential_id: string | null;
  provider: string;
  model: string;
  latency_ms: number;
  success: boolean;
  answer: string;
  error: JsonObject | null;
  cited_evidence_ids?: string[];
  analysis_chain?: AnalysisChainPayload | null;
}

export interface DiscussionTurnTrace {
  turn_index: number;
  agent_traces: DiscussionAgentTrace[];
}

export interface DiscussionSynthesis {
  text: string;
  strategy: string;
  synthesizer_agent_id: string | null;
  synthesizer_provider: string;
  synthesizer_model: string;
  success: boolean;
  error: JsonObject | null;
}

export interface DiscussionConvergenceJudgeCall {
  turn_index: number;
  similarity: number;
  done: boolean;
  confidence: number;
  reason: string;
}

export interface DiscussionConvergenceJudgeError {
  turn_index: number;
  stage: 'embedding' | 'judge' | 'parse';
  error_class: string;
  message: string;
}

export interface DiscussionConvergenceTrace {
  per_turn_similarity: number[];
  judge_calls: DiscussionConvergenceJudgeCall[];
  judge_errors: DiscussionConvergenceJudgeError[];
  decision_turn_index: number | null;
}

export type DiscussionStopReason = 'max_turns' | 'converged' | 'error';

export interface DiscussionRunResult {
  run_id: string;
  project_id: string | null;
  query: string;
  evidence: DiscussionEvidencePackPayload | null;
  turns: DiscussionTurnTrace[];
  synthesis: DiscussionSynthesis;
  elapsed_ms: number;
  stopped_early?: boolean;
  stop_reason?: DiscussionStopReason;
  convergence?: DiscussionConvergenceTrace | null;
}

const client = () => axios.create({
  baseURL: getApiBaseUrl(),
  timeout: 120_000,
});

export const discussionApi = {
  async createDiscussion(req: CreateDiscussionRequest): Promise<CreateDiscussionResponse> {
    const response = await client().post(`${API_BASE}/create`, req);
    return response.data;
  },

  async getStatus(sessionId: string): Promise<DiscussionStatusResponse> {
    const response = await client().get(`${API_BASE}/${sessionId}/status`);
    return response.data;
  },

  async getHistory(sessionId: string): Promise<DiscussionHistoryResponse> {
    const response = await client().get(`${API_BASE}/${sessionId}/history`);
    return response.data;
  },

  async runTurn(sessionId: string): Promise<RunTurnResponse> {
    const response = await client().post(`${API_BASE}/${sessionId}/run`);
    return response.data;
  },

  async runDiscussion(
    req: DiscussionRunConfig,
    opts?: { signal?: AbortSignal },
  ): Promise<DiscussionRunResult> {
    const response = await client().post<DiscussionRunResult>(
      `${API_BASE}/runs`,
      req,
      { signal: opts?.signal },
    );
    return response.data;
  },

  async runDiscussionStream(
    req: DiscussionRunConfig,
    opts: {
      onEvent: (event: DiscussionStreamEvent) => void;
      signal?: AbortSignal;
    },
  ): Promise<void> {
    const url = `${getApiBaseUrl()}${API_BASE}/runs/stream`;
    await consumeDiscussionSseStream(url, 'POST', JSON.stringify(req), opts);
  },

  // B1 (0.1.8.2): persistence — query a registered run's snapshot.
  // Returns null when the backend has no record (404); the caller should
  // drop any stored run_id and fall back to idle.
  async getDiscussionRun(runId: string): Promise<DiscussionRunSnapshot | null> {
    try {
      const response = await client().get<DiscussionRunSnapshot>(
        `${API_BASE}/runs/${encodeURIComponent(runId)}`,
      );
      return response.data;
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 404) return null;
      throw err;
    }
  },

  // B1: reconnect SSE for an existing run. Replays the event log then tails
  // live events until done/error. Same onEvent shape as runDiscussionStream.
  async resumeDiscussionStream(
    runId: string,
    opts: {
      onEvent: (event: DiscussionStreamEvent) => void;
      signal?: AbortSignal;
    },
  ): Promise<void> {
    const url = `${getApiBaseUrl()}${API_BASE}/runs/${encodeURIComponent(runId)}/stream/resume`;
    await consumeDiscussionSseStream(url, 'POST', undefined, opts);
  },
};

// Shared SSE consumer used by both runDiscussionStream and resumeDiscussionStream.
async function consumeDiscussionSseStream(
  url: string,
  method: 'POST',
  body: string | undefined,
  opts: {
    onEvent: (event: DiscussionStreamEvent) => void;
    signal?: AbortSignal;
  },
): Promise<void> {
  const response = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body,
    signal: opts.signal,
  });
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new DiscussionStreamError(
      `stream request failed: ${response.status} ${text}`.trim(),
      response.status,
    );
  }
  if (!response.body) {
    throw new DiscussionStreamError('stream response has no body', response.status);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      while (true) {
        const sep = buffer.indexOf('\n\n');
        if (sep < 0) break;
        const chunk = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        for (const line of chunk.split('\n')) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          const payload = trimmed.slice(5).trim();
          if (!payload) continue;
          try {
            const parsed = JSON.parse(payload) as DiscussionStreamEvent;
            opts.onEvent(parsed);
          } catch {
            /* malformed SSE line; skip */
          }
        }
      }
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      /* already released on abort */
    }
  }
}

export interface DiscussionRunSnapshot {
  run_id: string;
  state: 'pending' | 'running' | 'completed' | 'cancelled' | 'error';
  created_at: number;
  updated_at: number;
  current_stage: string | null;
  current_turn_index: number;
  live_traces: DiscussionAgentTrace[];
  synthesis: DiscussionRunResult['synthesis'] | null;
  final_result: DiscussionRunResult | null;
  error: string | null;
  event_log_length: number;
}

export class DiscussionStreamError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'DiscussionStreamError';
    this.status = status;
  }
}

export type DiscussionStreamEvent =
  | {
      // B7 (0.1.8.2): early event so UI can flip from "可运行" to "正在检索"
      // within ~100ms instead of black-screen for retrieval+first-LLM latency.
      event: 'started';
      run_id: string;
      stage: string;
      agent_count: number;
      max_turns: number;
    }
  | {
      // B7: stage transition (e.g. "agents_prep" after evidence built).
      event: 'stage_progress';
      stage: string;
      evidence_chunk_count?: number;
    }
  | {
      event: 'agent_done';
      turn_index: number;
      agent_id: string;
      trace: DiscussionAgentTrace;
    }
  | {
      event: 'turn_done';
      turn_index: number;
      agent_count: number;
    }
  | {
      event: 'synthesis_done';
      synthesis: DiscussionRunResult['synthesis'];
    }
  | {
      event: 'done';
      result: DiscussionRunResult;
    }
  | {
      event: 'error';
      status: number;
      error: string;
    };
