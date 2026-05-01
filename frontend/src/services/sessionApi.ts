/**
 * Session API — thin HTTP client for conversation-persistence endpoints.
 *
 * Covers `/runtime/sessions`, `/runtime/session/current`, `/runtime/session/{id}/...`
 * from `routers/runtime_router.py`. Kept separate from `writingBackend.ts` so the
 * conversation-persistence scope stays independently testable / revertable
 * (see plan §S-3.2 and §6.1 rollback lever).
 *
 * Plan: docs/superpowers/plans/2026-04-20-conversation-persistence-mvp.md §S-3
 */

import axios, { AxiosInstance } from "axios";
import { getApiBaseUrl } from "./apiBaseUrl";
import type {
  SessionSummary,
  TimelinePage,
  CheckpointMeta,
  ResumeSessionResult,
  RewindSessionRequest,
  ForkSessionRequest,
  ListSessionsQuery,
  GetCurrentSessionQuery,
  GetTimelineQuery,
} from "../types/runtime";

export class SessionApiService {
  private readonly client: AxiosInstance;

  constructor(baseURL: string = getApiBaseUrl()) {
    this.client = axios.create({
      baseURL,
      headers: { "Content-Type": "application/json" },
    });
  }

  /** List sessions scoped to a workspace binding. */
  async listSessions(query: ListSessionsQuery = {}): Promise<SessionSummary[]> {
    const response = await this.client.get<SessionSummary[]>(
      "/runtime/sessions",
      { params: query },
    );
    return response.data;
  }

  /**
   * Get the latest active session for the current workspace binding.
   * Returns null instead of throwing when the backend answers 404.
   */
  async getCurrentSession(
    query: GetCurrentSessionQuery = {},
  ): Promise<SessionSummary | null> {
    try {
      const response = await this.client.get<SessionSummary>(
        "/runtime/session/current",
        { params: query },
      );
      return response.data;
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 404) {
        return null;
      }
      throw err;
    }
  }

  /** Get a session by ID. */
  async getSession(sessionId: string): Promise<SessionSummary> {
    const response = await this.client.get<SessionSummary>(
      `/runtime/session/${encodeURIComponent(sessionId)}`,
    );
    return response.data;
  }

  /** Resume a persisted session and return its current transcript head. */
  async resumeSession(sessionId: string): Promise<ResumeSessionResult> {
    const response = await this.client.post<ResumeSessionResult>(
      `/runtime/session/${encodeURIComponent(sessionId)}/resume`,
    );
    return response.data;
  }

  /** Fetch the active transcript lineage for a session (cursor-paginated). */
  async getTimeline(
    sessionId: string,
    query: GetTimelineQuery = {},
  ): Promise<TimelinePage> {
    const response = await this.client.get<TimelinePage>(
      `/runtime/session/${encodeURIComponent(sessionId)}/timeline`,
      { params: query },
    );
    return response.data;
  }

  /** List rewind/fork checkpoints for a session. */
  async listCheckpoints(sessionId: string): Promise<CheckpointMeta[]> {
    const response = await this.client.get<CheckpointMeta[]>(
      `/runtime/session/${encodeURIComponent(sessionId)}/checkpoints`,
    );
    return response.data;
  }

  /**
   * Rewind a session back to a checkpoint.
   * When `request.mode === 'with_files'`, the backend also creates a
   * `.rollback_snapshots/rewind-<ts>/` directory before touching workspace
   * files — see plan §S-5 safety gate.
   */
  async rewindSession(
    sessionId: string,
    request: RewindSessionRequest,
  ): Promise<ResumeSessionResult> {
    const response = await this.client.post<ResumeSessionResult>(
      `/runtime/session/${encodeURIComponent(sessionId)}/rewind`,
      request,
    );
    return response.data;
  }

  /** Fork a new session branch from a checkpoint. */
  async forkSession(
    sessionId: string,
    request: ForkSessionRequest,
  ): Promise<ResumeSessionResult> {
    const response = await this.client.post<ResumeSessionResult>(
      `/runtime/session/${encodeURIComponent(sessionId)}/fork`,
      request,
    );
    return response.data;
  }
}

// Global singleton (consistent with writingBackend.ts pattern).
let instance: SessionApiService | null = null;

export function getSessionApi(baseURL?: string): SessionApiService {
  if (!instance) {
    instance = new SessionApiService(baseURL);
  }
  return instance;
}

export default SessionApiService;
