/**
 * WritingRuntimeClient Implementation for Electron Frontend
 * 
 * Provides a client for consuming the WritingRuntime backend APIs.
 * Supports session/job management, lifecycle control, and event streaming.
 */

import axios, { AxiosInstance } from 'axios';
import {
  WritingSession,
  WritingJob,
  WritingEvent,
  WritingArtifact,
  CreateSessionRequest,
  CreateJobRequest,
  JobStatusDetail,
  WritingRuntimeClient,
  EventType,
} from '../types/runtime';

export class HttpWritingRuntimeClient implements WritingRuntimeClient {
  private http: AxiosInstance;
  private baseUrl: string;
  private eventSubscriptions: Map<
    string,
    Array<(event: WritingEvent) => void>
  > = new Map();
  private eventPollers: Map<string, NodeJS.Timeout> = new Map();

  constructor(baseUrl: string = 'http://127.0.0.1:8000') {
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

  async getJobEvents(jobId: string): Promise<WritingEvent[]> {
    const response = await this.http.get<WritingEvent[]>(
      `/runtime/job/${jobId}/events`
    );
    return response.data;
  }

  async getJobArtifacts(jobId: string): Promise<WritingArtifact[]> {
    const response = await this.http.get<WritingArtifact[]>(
      `/runtime/job/${jobId}/artifacts`
    );
    return response.data;
  }

  // ==========================================================================
  // Job Lifecycle Control
  // ==========================================================================

  async startJob(jobId: string): Promise<{ job_id: string; status: string }> {
    const response = await this.http.post(
      `/runtime/job/${jobId}/start`,
      {}
    );
    return response.data;
  }

  async pauseJob(jobId: string): Promise<{ job_id: string; status: string }> {
    const response = await this.http.post(
      `/runtime/job/${jobId}/pause`,
      {}
    );
    return response.data;
  }

  async resumeJob(jobId: string): Promise<{ job_id: string; status: string }> {
    const response = await this.http.post(
      `/runtime/job/${jobId}/resume`,
      {}
    );
    return response.data;
  }

  async cancelJob(jobId: string): Promise<{ job_id: string; status: string }> {
    const response = await this.http.post(
      `/runtime/job/${jobId}/cancel`,
      {}
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

  private startEventPolling(sessionId: string): NodeJS.Timeout {
    let lastEventCount = 0;

    return setInterval(async () => {
      try {
        // This is a placeholder - in a real implementation,
        // you would query for new events since lastEventId
        // For now, we demonstrate the pattern
      } catch (error) {
        console.warn(`Error polling events for session ${sessionId}:`, error);
      }
    }, 1000);  // Poll every second
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
