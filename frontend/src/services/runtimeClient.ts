/**
 * WritingRuntimeClient Implementation for Electron Frontend
 * 
 * Provides a client for consuming the WritingRuntime backend APIs.
 * Supports session/job management, lifecycle control, and event streaming.
 */

import axios, { AxiosInstance } from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';
import {
  WritingSession,
  WritingJob,
  WritingEvent,
  WritingArtifact,
  CreateSessionRequest,
  CreateJobRequest,
  JobStatusDetail,
  WritingRuntimeClient,
  JobStatus,
  JobEventQueryOptions,
  JobEventSnapshot,
  ListJobsQuery,
} from '../types/runtime';

export class HttpWritingRuntimeClient implements WritingRuntimeClient {
  private http: AxiosInstance;
  private baseUrl: string;
  private eventSubscriptions: Map<
    string,
    Array<(event: WritingEvent) => void>
  > = new Map();
  private eventPollers: Map<string, NodeJS.Timeout> = new Map();

  constructor(baseUrl: string = getApiBaseUrl()) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.http = axios.create({
      baseURL: this.baseUrl,
      timeout: 30000,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  // ==========================================================================
  // Session Management
  // ==========================================================================

  async createSession(request: CreateSessionRequest): Promise<WritingSession> {
    const response = await this.http.post<WritingSession>(
      '/runtime/session',
      request
    );
    return response.data;
  }

  async getSession(sessionId: string): Promise<WritingSession> {
    const response = await this.http.get<WritingSession>(
      `/runtime/session/${sessionId}`
    );
    return response.data;
  }

  // ==========================================================================
  // Job Management
  // ==========================================================================

  async createJob(request: CreateJobRequest): Promise<WritingJob> {
    const response = await this.http.post<WritingJob>('/runtime/job', request);
    return response.data;
  }

  async listJobs(query: ListJobsQuery = {}): Promise<WritingJob[]> {
    const response = await this.http.get<WritingJob[]>('/runtime/jobs', {
      params: {
        session_id: query.sessionId ?? undefined,
        status: query.status ?? undefined,
        limit: query.limit ?? undefined,
      },
    });
    return response.data;
  }

  async getJob(jobId: string): Promise<WritingJob> {
    const response = await this.http.get<WritingJob>(`/runtime/job/${jobId}`);
    return response.data;
  }

  async getJobStatus(jobId: string): Promise<JobStatusDetail> {
    const response = await this.http.get<JobStatusDetail>(
      `/runtime/job/${jobId}/status`
    );
    return response.data;
  }

  async getJobEvents(
    jobId: string,
    options: JobEventQueryOptions = {}
  ): Promise<WritingEvent[]> {
    const response = await this.http.get<WritingEvent[]>(
      `/runtime/job/${jobId}/events`,
      {
        params: {
          since_timestamp: options.sinceTimestamp ?? undefined,
          after_event_id: options.afterEventId ?? undefined,
          after_sequence: options.afterSequence ?? undefined,
          limit: options.limit ?? undefined,
        },
      }
    );
    return response.data;
  }

  async getJobEventSnapshot(
    jobId: string,
    options: JobEventQueryOptions = {}
  ): Promise<JobEventSnapshot> {
    const response = await this.http.get<JobEventSnapshot>(
      `/runtime/job/${jobId}/snapshot`,
      {
        params: {
          since_timestamp: options.sinceTimestamp ?? undefined,
          after_event_id: options.afterEventId ?? undefined,
          after_sequence: options.afterSequence ?? undefined,
          limit: options.limit ?? undefined,
        },
      }
    );
    return response.data;
  }

  async getJobArtifacts(jobId: string): Promise<WritingArtifact[]> {
    const response = await this.http.get<WritingArtifact[]>(
      `/runtime/job/${jobId}/artifacts`
    );
    return response.data;
  }

  async getJobs(query: ListJobsQuery = {}): Promise<WritingJob[]> {
    return this.listJobs(query);
  }

  // ==========================================================================
  // Job Lifecycle Control
  // ==========================================================================

  async startJob(jobId: string): Promise<{ job_id: string; status: JobStatus }> {
    const response = await this.http.post<{ job_id: string; status: JobStatus }>(
      `/runtime/job/${jobId}/start`,
      {}
    );
    return response.data;
  }

  async pauseJob(jobId: string): Promise<{ job_id: string; status: JobStatus }> {
    const response = await this.http.post<{ job_id: string; status: JobStatus }>(
      `/runtime/job/${jobId}/pause`,
      {}
    );
    return response.data;
  }

  async resumeJob(jobId: string): Promise<{ job_id: string; status: JobStatus }> {
    const response = await this.http.post<{ job_id: string; status: JobStatus }>(
      `/runtime/job/${jobId}/resume`,
      {}
    );
    return response.data;
  }

  async cancelJob(jobId: string): Promise<{ job_id: string; status: JobStatus }> {
    const response = await this.http.post<{ job_id: string; status: JobStatus }>(
      `/runtime/job/${jobId}/cancel`,
      {}
    );
    return response.data;
  }

  async deleteJob(jobId: string): Promise<{ job_id: string; deleted: boolean }> {
    const response = await this.http.delete<{ job_id: string; deleted: boolean }>(
      `/runtime/job/${jobId}`
    );
    return response.data;
  }

  // ==========================================================================
  // Event Subscription (Polling-based for now)
  // ==========================================================================

  subscribeToEvents(
    sessionId: string,
    onEvent: (event: WritingEvent) => void
  ): () => void {
    // Register callback
    if (!this.eventSubscriptions.has(sessionId)) {
      this.eventSubscriptions.set(sessionId, []);
    }
    this.eventSubscriptions.get(sessionId)!.push(onEvent);

    // Start polling if not already started
    if (!this.eventPollers.has(sessionId)) {
      const pollerId = this.startEventPolling(sessionId);
      this.eventPollers.set(sessionId, pollerId);
    }

    // Return unsubscribe function
    return () => {
      const callbacks = this.eventSubscriptions.get(sessionId);
      if (callbacks) {
        const index = callbacks.indexOf(onEvent);
        if (index >= 0) {
          callbacks.splice(index, 1);
        }
      }
    };
  }

  private startEventPolling(_sessionId: string): NodeJS.Timeout {
    return setInterval(() => {
      // Session-level event polling is intentionally idle; job timelines use
      // `useJobEventPolling` with concrete job ids.
    }, 1000);
  }

  stopEventPolling(sessionId: string): void {
    const pollerId = this.eventPollers.get(sessionId);
    if (pollerId) {
      clearInterval(pollerId);
      this.eventPollers.delete(sessionId);
    }
    this.eventSubscriptions.delete(sessionId);
  }
}

// Global singleton instance
let runtimeClient: HttpWritingRuntimeClient | null = null;

export function getWritingRuntimeClient(
  baseUrl?: string
): HttpWritingRuntimeClient {
  if (!runtimeClient) {
    runtimeClient = new HttpWritingRuntimeClient(baseUrl);
  }
  return runtimeClient;
}
